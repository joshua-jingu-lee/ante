"""IndicatorCalculator — PER/PBR/EPS/BPS/ROE/부채비율 파생 지표 계산.

fundamental 데이터는 cadence가 다른 두 소스로 구성된다(#1964):

- data.go.kr(``source == "data_go_kr"``): **일별** ``market_cap`` / ``shares_listed``
  (DART 재무 컬럼은 null).
- DART(``source == "dart"``): **분기별** ``net_income`` / ``total_equity`` /
  ``total_debt`` 등 재무 항목(가격/주식수 컬럼은 null).

`(date, source)` natural key로 두 소스가 **별도 행**으로 보존되므로, 단일 행
row-wise 계산(예: ``per = market_cap / net_income``)은 한 행에 cross-source
피연산자가 동시에 존재하지 않아 **모든 지표가 null**이 된다. 이를 해소하기
위해 source별로 분리한 뒤 **as-of join**으로 결합한다.

semantic(#1968, PR 명문화):
    net_income / total_equity / total_debt 는 "일별 date 기준 **가장 최근에
    보고된 분기 재무 값**"(``join_asof(strategy="backward")``)을 사용한다.
    TTM(trailing-twelve-months) 합산이나 연간환산은 **하지 않는다**(Non-Goal,
    후속 정제 이슈). 분모가 0/null이면 해당 지표는 null이다
    (``_ratio_expr`` 가드 유지). 지표는 가격 기반 지표의 자연 단위인 **일별
    행**(data.go.kr 행)에 부여하여 write-back한다.
"""

from __future__ import annotations

import logging

import polars as pl

from ante.data.schemas import FUNDAMENTAL_COLUMNS
from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)

# source별 행 분리 기준 (normalizer가 부여하는 source 문자열 SSOT).
_DAILY_SOURCE = "data_go_kr"
_QUARTERLY_SOURCE = "dart"

# as-of join 키.
_JOIN_KEY = "date"

# DART 분기 행이 기여하는 재무 컬럼 — 6종 비율의 분자/분모 피연산자다
# (net_income/total_equity/total_debt). as-of join 시 이 컬럼들만 분기
# 프레임에서 일별 프레임으로 가져온다.
#
# 주의(#1968 핵심): `store.read`는 월별 이종 파티션을 `diagonal_relaxed`로
# union하므로, source로 행을 분리해도 daily/quarterly **양쪽 sub-frame이
# 동일한 컬럼 union**을 보유한다(상대 소스 컬럼은 null-fill). 따라서 "일별에
# 없는 컬럼" 같은 동적 판별은 쓸 수 없다(모든 컬럼이 양쪽에 존재). 대신
# 컬럼의 **provenance(소스 귀속)** 를 명시 상수로 고정해, 일별 프레임에서는
# 이 재무 컬럼(일별 행에서는 null)을 **버리고**, 분기 프레임에서는 이
# 컬럼만 join 키와 함께 **가져온다**. 이로써 (1) source/symbol 충돌(_right
# 중복 누출) 차단, (2) 일별 행의 null 재무가 실제 분기 값을 덮어쓰는 사고
# 방지.
_QUARTERLY_FINANCIAL_COLUMNS: tuple[str, ...] = (
    "net_income",
    "total_equity",
    "total_debt",
)

# write-back 프레임은 FUNDAMENTAL 스키마 부분집합으로 유지한다. DART
# normalizer가 내보내는 total_assets 등 스키마 밖 컬럼이 read union으로
# 섞여 들어와도 write 전에 제거한다(스키마 일탈 방지).
_FUNDAMENTAL_COLUMN_SET = frozenset(FUNDAMENTAL_COLUMNS)


class IndicatorCalculator:
    """fundamental 데이터로부터 파생 투자 지표를 계산한다.

    계산 공식:
    - PER = 시가총액 / 당기순이익
    - PBR = 시가총액 / 자본총계
    - EPS = 당기순이익 / 상장주식수
    - BPS = 자본총계 / 상장주식수
    - ROE = 당기순이익 / 자본총계
    - 부채비율 = 부채총계 / 자본총계

    cadence가 다른 두 소스(data.go.kr 일별 / DART 분기)를 as-of join으로
    결합하여 일별 행에 지표를 부여한다(자세한 semantic은 모듈 docstring).
    """

    def compute(
        self,
        store: ParquetStore,
        symbols: list[str],
    ) -> int:
        """심볼 목록에 대해 파생 지표를 계산하여 저장한다.

        Returns:
            갱신된 행 수.
        """
        rows_updated = 0

        for sym in symbols:
            updated = self._compute_symbol(store, sym)
            rows_updated += updated

        logger.info(
            "파생 지표 계산 완료: symbols=%d rows=%d",
            len(symbols),
            rows_updated,
        )
        return rows_updated

    def _compute_symbol(
        self,
        store: ParquetStore,
        sym: str,
    ) -> int:
        """단일 심볼의 파생 지표를 as-of join으로 계산한다.

        data.go.kr 일별 행에 그 날짜 이전 가장 최근 DART 분기 재무를
        ``join_asof(strategy="backward")``로 결합한 뒤 비율을 계산하여
        일별 행을 write-back한다. 두 소스 중 하나라도 비어 있거나
        source/date 컬럼이 없으면 0을 반환한다(graceful).
        """
        try:
            fundamental = store.read(sym, "krx", data_type="fundamental")
        except Exception:
            return 0

        if fundamental.is_empty():
            return 0

        cols = set(fundamental.columns)
        if "source" not in cols or _JOIN_KEY not in cols:
            return 0

        daily = fundamental.filter(pl.col("source") == _DAILY_SOURCE)
        quarterly = fundamental.filter(pl.col("source") == _QUARTERLY_SOURCE)
        if daily.is_empty() or quarterly.is_empty():
            return 0

        joined = self._join_asof(daily, quarterly)
        if joined is None:
            return 0

        exprs = self._build_expressions(set(joined.columns))
        if not exprs:
            return 0

        updated = joined.with_columns(exprs)
        # write-back 전 FUNDAMENTAL 스키마 밖 컬럼(total_assets 등) 제거.
        keep = [c for c in updated.columns if c in _FUNDAMENTAL_COLUMN_SET]
        updated = updated.select(keep)
        store.write(sym, "krx", updated, data_type="fundamental")
        return len(updated)

    @staticmethod
    def _join_asof(
        daily: pl.DataFrame,
        quarterly: pl.DataFrame,
    ) -> pl.DataFrame | None:
        """일별 프레임에 그 날짜 기준 가장 최근 분기 재무를 as-of 결합한다.

        ``store.read``의 ``diagonal_relaxed`` union 때문에 daily/quarterly
        sub-frame은 동일한 컬럼 union을 보유한다(상대 소스 컬럼은 null-fill).
        따라서 컬럼 provenance를 명시 상수로 고정해 결합한다:

        - 일별 프레임에서 ``_QUARTERLY_FINANCIAL_COLUMNS``(일별 행에선 null)를
          **버려** join 후 분기 값이 null로 덮이지 않게 한다.
        - 분기 프레임에서는 그 재무 컬럼만 join 키(date)와 함께 **가져온다**.

        결합 결과는 일별 identity(date, symbol, source=data_go_kr,
        market_cap, shares_listed 등)를 유지하면서 그 날짜 이전 가장 최근
        분기 재무를 부여받는다. 가져올 분기 재무 컬럼이 하나도 없으면
        ``None``을 반환한다.
        """
        financial_cols = [
            col for col in _QUARTERLY_FINANCIAL_COLUMNS if col in quarterly.columns
        ]
        if not financial_cols:
            return None

        # 일별 프레임에서 분기 재무 컬럼(null-fill된 잔재)을 제거해 충돌 차단.
        daily_identity = daily.drop([c for c in financial_cols if c in daily.columns])
        quarterly_fin = quarterly.select([_JOIN_KEY, *financial_cols])

        return daily_identity.sort(_JOIN_KEY).join_asof(
            quarterly_fin.sort(_JOIN_KEY),
            on=_JOIN_KEY,
            strategy="backward",
        )

    @staticmethod
    def _build_expressions(cols: set[str]) -> list[pl.Expr]:
        """사용 가능한 컬럼에 따라 지표 계산 표현식을 생성한다."""
        has_market_cap = "market_cap" in cols
        has_shares = "shares_listed" in cols
        has_net_income = "net_income" in cols
        has_equity = "total_equity" in cols
        has_debt = "total_debt" in cols

        exprs: list[pl.Expr] = []

        if has_market_cap and has_net_income:
            exprs.append(_ratio_expr("market_cap", "net_income", "per"))

        if has_market_cap and has_equity:
            exprs.append(_ratio_expr("market_cap", "total_equity", "pbr"))

        if has_net_income and has_shares:
            exprs.append(_ratio_expr("net_income", "shares_listed", "eps"))

        if has_equity and has_shares:
            exprs.append(_ratio_expr("total_equity", "shares_listed", "bps"))

        if has_net_income and has_equity:
            exprs.append(_ratio_expr("net_income", "total_equity", "roe"))

        if has_debt and has_equity:
            exprs.append(
                _ratio_expr("total_debt", "total_equity", "debt_to_equity"),
            )

        return exprs


def _ratio_expr(
    numerator: str,
    denominator: str,
    alias: str,
) -> pl.Expr:
    """분모가 0이면 None을 반환하는 나눗셈 표현식.

    분모가 null(as-of 결합 이전 날짜 등)이면 비교/나눗셈이 null로 전파되어
    결과도 null이 된다.
    """
    return (
        pl.when(pl.col(denominator) != 0)
        .then(pl.col(numerator).cast(pl.Float64) / pl.col(denominator).cast(pl.Float64))
        .otherwise(None)
        .alias(alias)
    )
