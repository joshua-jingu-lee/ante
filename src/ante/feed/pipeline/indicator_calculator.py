"""IndicatorCalculator — PER/PBR/EPS/BPS/ROE/부채비율 파생 지표 계산."""

from __future__ import annotations

import logging

import polars as pl

from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)


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

    async def compute(
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
            updated = await self._compute_symbol(store, sym)
            rows_updated += updated

        logger.info(
            "파생 지표 계산 완료: symbols=%d rows=%d",
            len(symbols),
            rows_updated,
        )
        return rows_updated

    async def _compute_symbol(
        self,
        store: ParquetStore,
        sym: str,
    ) -> int:
        """단일 심볼의 파생 지표를 계산한다."""
        try:
            fundamental = await store.read(sym, "krx", data_type="fundamental")
        except Exception:
            return 0

        if fundamental.is_empty():
            return 0

        exprs = self._build_expressions(set(fundamental.columns))
        if not exprs:
            return 0

        updated = fundamental.with_columns(exprs)
        await store.write(sym, "krx", updated, data_type="fundamental")
        return len(updated)

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
