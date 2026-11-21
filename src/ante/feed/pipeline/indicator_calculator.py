"""IndicatorCalculator — PER/PBR/EPS/BPS/ROE/부채비율 파생 지표 계산."""

from __future__ import annotations

import logging

import polars as pl

from ante.data.schemas import FUNDAMENTAL_COLUMNS
from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)

_DAILY_SOURCE = "data_go_kr"
_QUARTERLY_SOURCE = "dart"

_PERIOD_END_KEY = "date"

_AVAILABLE_DATE_KEY = "available_date"

_EFFECTIVE_KEY = "_effective_available"
_ASOF_KEY = "_asof_join_key"

_LAG_QUARTERLY_DAYS = 45
_LAG_ANNUAL_DAYS = 90
_QUARTERLY_PERIOD_END_MONTHS = (3, 6, 9)
_ANNUAL_PERIOD_END_MONTH = 12

_JOIN_KEY = "date"

_QUARTERLY_FINANCIAL_COLUMNS: tuple[str, ...] = (
    "net_income",
    "total_equity",
    "total_debt",
)

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
    """

    def compute(
        self,
        store: ParquetStore,
        symbols: list[str],
    ) -> int:
        """심볼 목록에 대해 파생 지표를 계산하여 저장한다.

        Returns:
            **net-new 저장 행 수**(rows_written). 지표 계산은 기존 일별
            fundamental 행을 비율 컬럼만 채워 같은 natural key로 in-place
            overwrite하므로(행 수 불변), 보통 net-delta=0이다. 이는 정상이며
            rows_written 과대계상을 방지한다.
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
        """단일 심볼의 파생 지표를 as-of join으로 계산한다."""
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
        keep = [c for c in updated.columns if c in _FUNDAMENTAL_COLUMN_SET]
        updated = updated.select(keep)
        return store.write(sym, "krx", updated, data_type="fundamental")

    @staticmethod
    def _join_asof(
        daily: pl.DataFrame,
        quarterly: pl.DataFrame,
    ) -> pl.DataFrame | None:
        """일별 거래일에 그 시점 이전 **공시된** 가장 최근 분기 재무를 결합한다."""
        financial_cols = [
            col for col in _QUARTERLY_FINANCIAL_COLUMNS if col in quarterly.columns
        ]
        if not financial_cols:
            return None

        quarterly_eff = IndicatorCalculator._with_effective_availability(quarterly)
        if quarterly_eff.is_empty():
            return None

        daily_identity = daily.drop([c for c in financial_cols if c in daily.columns])

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
        return joined.drop(_ASOF_KEY)

    @staticmethod
    def _with_effective_availability(quarterly: pl.DataFrame) -> pl.DataFrame:
        """분기 프레임에 effective availability 키(``_EFFECTIVE_KEY``)를 부여한다."""
        if _AVAILABLE_DATE_KEY in quarterly.columns:
            available = pl.col(_AVAILABLE_DATE_KEY)
        else:
            available = pl.lit(None, dtype=pl.Date)

        month = pl.col(_PERIOD_END_KEY).dt.month()
        lag_days = (
            pl.when(month.is_in(list(_QUARTERLY_PERIOD_END_MONTHS)))
            .then(pl.lit(_LAG_QUARTERLY_DAYS))
            .when(month == _ANNUAL_PERIOD_END_MONTH)
            .then(pl.lit(_LAG_ANNUAL_DAYS))
            .otherwise(None)
        )
        fallback = pl.col(_PERIOD_END_KEY) + pl.duration(days=lag_days)

        with_eff = quarterly.with_columns(
            pl.coalesce(available, fallback).cast(pl.Date).alias(_EFFECTIVE_KEY),
        )
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
    """분모가 0이면 None을 반환하는 나눗셈 표현식."""
    return (
        pl.when(pl.col(denominator) != 0)
        .then(pl.col(numerator).cast(pl.Float64) / pl.col(denominator).cast(pl.Float64))
        .otherwise(None)
        .alias(alias)
    )
