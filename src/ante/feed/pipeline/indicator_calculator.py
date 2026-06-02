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

lookahead 제거(#2067):
    as-of join 키를 분기 **period_end(date)** 가 아니라 그 재무가 실제로
    **공시되어 알 수 있게 된 시점**(availability)로 바꾼다. period_end부터
    분기 값을 적용하면, 예컨대 Q1(3/31) 재무가 공시(5월 중순)되기 전인 4월
    거래일에 미래 정보를 쓰게 되어 lookahead bias가 발생한다.

    분기 프레임마다 effective availability 키를 계산한다::

        effective = coalesce(available_date, period_end + statutory_lag)

    - ``available_date``(#2010, DART 공시 접수일 rcept_dt)가 있으면 **그대로**
      쓴다(point-in-time 정확).
    - 없는 legacy 행은 **자본시장법 법정 제출기한**으로 보수적 fallback한다:
      분기/반기/3분기 보고서(period_end 월 ∈ {3,6,9})는 기말 후 45일,
      사업보고서(period_end 월 == 12)는 기말 후 90일.
    - 일별 거래일 ``date``(data.go.kr, point-in-time 정확)는 변경하지 않는다.

    known-limitation: available_date 없는 legacy 행의 fallback은 "법정기한 내
    공시" 가정이라 지연제출/정정공시/특수연장은 완전히 보장하지 못한다. 다만
    fallback은 실제 공시일보다 **늦은(보수적)** 쪽이라 lookahead 측면에서는
    안전하다(실제보다 며칠 늦게 반영될 뿐 미래 정보를 당겨쓰지 않는다).
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

# 분기 프레임의 period-end(기말일) 컬럼. 일별 거래일 date와 동명이지만 의미가
# 다르다(분기 행에서는 period_end, 일별 행에서는 거래일). as-of 결합은 더 이상
# 이 컬럼을 직접 join 키로 쓰지 않는다(#2067 lookahead 제거).
_PERIOD_END_KEY = "date"

# DART 공시 접수일(point-in-time availability, #2010). nullable.
_AVAILABLE_DATE_KEY = "available_date"

# effective availability 키와 join_asof 양쪽 alias용 임시 컬럼명. write-back
# 전 반드시 제거한다(FUNDAMENTAL 스키마 밖이므로 _FUNDAMENTAL_COLUMN_SET 필터로
# 자연 제거되지만, 명시적으로도 drop한다).
_EFFECTIVE_KEY = "_effective_available"
_ASOF_KEY = "_asof_join_key"

# 자본시장법 법정 제출기한(보수적 fallback). available_date가 없는 legacy 행에
# 한해 period_end 월로 분류해 더한다:
#   - 분기/반기/3분기 보고서(period_end 월 3/6/9) → 기말 후 45일
#   - 사업(연간)보고서(period_end 월 12) → 기말 후 90일
# 이 외(비표준) 월의 행은 분류 불가 → join 전 제거한다.
_LAG_QUARTERLY_DAYS = 45
_LAG_ANNUAL_DAYS = 90
_QUARTERLY_PERIOD_END_MONTHS = (3, 6, 9)
_ANNUAL_PERIOD_END_MONTH = 12

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
        """일별 거래일에 그 시점 이전 **공시된** 가장 최근 분기 재무를 결합한다.

        ``store.read``의 ``diagonal_relaxed`` union 때문에 daily/quarterly
        sub-frame은 동일한 컬럼 union을 보유한다(상대 소스 컬럼은 null-fill).
        따라서 컬럼 provenance를 명시 상수로 고정해 결합한다:

        - 일별 프레임에서 ``_QUARTERLY_FINANCIAL_COLUMNS``(일별 행에선 null)를
          **버려** join 후 분기 값이 null로 덮이지 않게 한다.
        - 분기 프레임에서는 그 재무 컬럼만 **availability 키**와 함께 가져온다.

        as-of 키는 분기 period_end가 아니라 effective availability다(#2067):

            effective = coalesce(available_date, period_end + statutory_lag)

        - ``available_date``(#2010)가 있으면 그대로(point-in-time).
        - 없으면 period_end 월로 법정 제출기한을 도출:
          {3,6,9} → +45일, 12 → +90일.
        - 비표준 period_end 월(위 4개월이 아님) 또는 effective가 끝내 null인
          행은 정렬·결합 안정성을 위해 **join 전 제거**한다.

        그 다음 일별 거래일 ``date`` ↔ 분기 ``effective``를 동일한 임시 join
        컬럼명(``_ASOF_KEY``)으로 alias하고 ``strategy="backward"``로 결합한다
        (backward는 inclusive — 거래일 == effective면 적용). 결합 결과는 일별
        identity를 유지하면서, 그 거래일 **이전(또는 당일) 공시된** 가장 최근
        분기 재무만 부여받는다. 임시 키는 결합 직후 제거한다.

        가져올 분기 재무 컬럼이 하나도 없거나, effective availability를 가진
        분기 행이 하나도 남지 않으면 ``None``을 반환한다.
        """
        financial_cols = [
            col for col in _QUARTERLY_FINANCIAL_COLUMNS if col in quarterly.columns
        ]
        if not financial_cols:
            return None

        quarterly_eff = IndicatorCalculator._with_effective_availability(quarterly)
        if quarterly_eff.is_empty():
            return None

        # 일별 프레임에서 분기 재무 컬럼(null-fill된 잔재)을 제거해 충돌 차단.
        daily_identity = daily.drop([c for c in financial_cols if c in daily.columns])

        # 양쪽을 동일한 임시 join 키로 alias: 일별=거래일 date, 분기=effective.
        daily_keyed = daily_identity.with_columns(
            pl.col(_JOIN_KEY).alias(_ASOF_KEY),
        )
        quarterly_keyed = quarterly_eff.select(
            pl.col(_EFFECTIVE_KEY).alias(_ASOF_KEY),
            *[pl.col(c) for c in financial_cols],
        )

        joined = daily_keyed.sort(_ASOF_KEY).join_asof(
            quarterly_keyed.sort(_ASOF_KEY),
            on=_ASOF_KEY,
            strategy="backward",
        )
        # 임시 join 키 제거(스키마 밖). _EFFECTIVE_KEY는 분기 프레임에만 있었고
        # select로 가져오지 않았으므로 결합 결과엔 없다.
        return joined.drop(_ASOF_KEY)

    @staticmethod
    def _with_effective_availability(quarterly: pl.DataFrame) -> pl.DataFrame:
        """분기 프레임에 effective availability 키(``_EFFECTIVE_KEY``)를 부여한다.

        ``effective = coalesce(available_date, period_end + statutory_lag)``.
        statutory_lag은 period_end 월로 분류한다(3/6/9 → +45일, 12 → +90일).
        비표준 period_end 월이면서 available_date도 없는 행, 또는 effective가
        끝내 null인 행은 **제거**한다(as-of 정렬 안정성 + lookahead 안전).

        ``available_date`` 컬럼은 #2010 이전 legacy 파티션에는 아예 없을 수
        있으므로(존재해도 nullable), 없으면 전 행 null(=법정기한 fallback만
        사용)로 취급한다.
        """
        if _AVAILABLE_DATE_KEY in quarterly.columns:
            available = pl.col(_AVAILABLE_DATE_KEY)
        else:
            available = pl.lit(None, dtype=pl.Date)

        month = pl.col(_PERIOD_END_KEY).dt.month()
        # period_end 월로 법정 제출기한(일수)을 분류. 비표준 월은 null.
        lag_days = (
            pl.when(month.is_in(list(_QUARTERLY_PERIOD_END_MONTHS)))
            .then(pl.lit(_LAG_QUARTERLY_DAYS))
            .when(month == _ANNUAL_PERIOD_END_MONTH)
            .then(pl.lit(_LAG_ANNUAL_DAYS))
            .otherwise(None)
        )
        # period_end + statutory_lag (분류 불가 월이면 lag_days null → fallback도
        # null로 전파).
        fallback = pl.col(_PERIOD_END_KEY) + pl.duration(days=lag_days)

        with_eff = quarterly.with_columns(
            pl.coalesce(available, fallback).cast(pl.Date).alias(_EFFECTIVE_KEY),
        )
        # effective가 null인 행 제거(available_date 없고 + period_end 월도 비표준).
        return with_eff.filter(pl.col(_EFFECTIVE_KEY).is_not_null())

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
