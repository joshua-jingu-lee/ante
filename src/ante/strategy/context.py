"""StrategyContext — 전략에 노출되는 제한된 API."""

from __future__ import annotations

import logging
from typing import Any

from ante.strategy.base import DataProvider, OrderAction, OrderView, PortfolioView


class StrategyContext:
    """전략이 사용할 수 있는 API. Bot이 생성하여 전략에 주입."""

    def __init__(
        self,
        bot_id: str,
        data_provider: DataProvider,
        portfolio: PortfolioView,
        order_view: OrderView,
        logger: logging.Logger | None = None,
    ) -> None:
        self.bot_id = bot_id
        self._data = data_provider
        self._portfolio = portfolio
        self._orders = order_view
        self._log = logger or logging.getLogger(f"ante.strategy.{bot_id}")
        self._pending_actions: list[OrderAction] = []

    # ── 데이터 조회 ──

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> Any:
        """OHLCV 데이터 조회."""
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

    # ── 포트폴리오 조회 ──

    def get_positions(self) -> dict[str, Any]:
        """현재 보유 포지션 조회."""
        return self._portfolio.get_positions(self.bot_id)

    def get_balance(self) -> dict[str, float]:
        """봇 할당 자금 현황 조회."""
        return self._portfolio.get_balance(self.bot_id)

    # ── 주문 관리 ──

    def get_open_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        return self._orders.get_open_orders(self.bot_id)

    def cancel_order(self, order_id: str, reason: str = "") -> None:
        """미체결 주문 취소 요청."""
        self._pending_actions.append(
            OrderAction(action="cancel", order_id=order_id, reason=reason)
        )

    def modify_order(
        self,
        order_id: str,
        quantity: float | None = None,
        price: float | None = None,
        reason: str = "",
    ) -> None:
        """미체결 주문 정정 요청."""
        self._pending_actions.append(
            OrderAction(
                action="modify",
                order_id=order_id,
                quantity=quantity,
                price=price,
                reason=reason,
            )
        )

    def _drain_actions(self) -> list[OrderAction]:
        """Bot이 호출: 큐에 쌓인 주문 관리 액션을 모두 꺼내 반환."""
        actions = self._pending_actions.copy()
        self._pending_actions.clear()
        return actions

    # ── 로깅 ──

    def log(self, message: str, level: str = "info") -> None:
        """전략 로그 기록."""
        log_level = getattr(logging, level.upper(), logging.INFO)
        self._log.log(log_level, "[%s] %s", self.bot_id, message)
