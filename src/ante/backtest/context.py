"""Backtest용 StrategyContext."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.strategy.base import OrderAction

if TYPE_CHECKING:
    import polars as pl

    from ante.backtest.data_provider import BacktestDataProvider
    from ante.backtest.executor import BacktestExecutor

logger = logging.getLogger(__name__)


class BacktestStrategyContext:
    """백테스트 전략에 주입되는 컨텍스트.

    라이브 StrategyContext와 동일한 인터페이스를 제공하되,
    데이터는 BacktestDataProvider에서, 포트폴리오는 BacktestExecutor에서 가져온다.
    """

    def __init__(
        self,
        bot_id: str,
        data_provider: BacktestDataProvider,
        portfolio: BacktestExecutor,
    ) -> None:
        self._bot_id = bot_id
        self._data = data_provider
        self._portfolio = portfolio
        self._actions: list[OrderAction] = []
        self.logger = logging.getLogger(f"backtest.strategy.{bot_id}")

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> pl.DataFrame:
        """OHLCV 데이터 조회.

        Returns:
            Polars DataFrame with columns: timestamp, open, high, low, close, volume.
        """
        return await self._data.get_ohlcv(symbol, timeframe, limit)

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        return await self._data.get_current_price(symbol)

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """기술 지표 데이터 조회."""
        return await self._data.get_indicator(symbol, indicator, params)

    def get_positions(self) -> dict[str, Any]:
        """현재 보유 포지션."""
        return self._portfolio.get_positions(self._bot_id)

    def get_balance(self) -> dict[str, float]:
        """가용 자금 현황."""
        return self._portfolio.get_balance(self._bot_id)

    def get_open_orders(self) -> list[dict[str, Any]]:
        """백테스트에서는 미체결 주문 없음."""
        return []

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        """주문 취소 (백테스트에서는 무시)."""

    def modify_order(
        self,
        order_id: str,
        quantity: float | None = None,
        price: float | None = None,
        reason: str = "",
    ) -> None:
        """주문 정정 (백테스트에서는 무시)."""

    def log(self, message: str, level: str = "info") -> None:
        """전략 로그 출력."""
        getattr(self.logger, level, self.logger.info)(message)
