"""StrategyContext — 전략에 노출되는 제한된 API."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ante.strategy.base import (
    DataProvider,
    OrderAction,
    OrderView,
    PortfolioView,
    TradeHistoryView,
)
from ante.strategy.exceptions import StrategyFileAccessError

logger = logging.getLogger(__name__)

# strategies/ 디렉토리 기준 경로 (프로젝트 루트 기준)
_STRATEGIES_ROOT = Path("strategies")


class StrategyContext:
    """전략이 사용할 수 있는 API. Bot이 생성하여 전략에 주입."""

    def __init__(
        self,
        bot_id: str,
        data_provider: DataProvider,
        portfolio: PortfolioView,
        order_view: OrderView,
        trade_history: TradeHistoryView | None = None,
        logger: logging.Logger | None = None,
        strategies_dir: Path | None = None,
    ) -> None:
        self.bot_id = bot_id
        self._data = data_provider
        self._portfolio = portfolio
        self._orders = order_view
        self._trade_history = trade_history
        self._log = logger or logging.getLogger(f"ante.strategy.{bot_id}")
        self._pending_actions: list[OrderAction] = []
        self._strategies_dir = (
            strategies_dir.resolve() if strategies_dir else _STRATEGIES_ROOT.resolve()
        )

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
    ) -> dict[str, Any]:
        """기술 지표 계산.

        OHLCV 데이터를 가져와 pandas-ta로 지표를 계산한다.
        pandas-ta는 정규 의존성이므로 항상 사용 가능하다.

        Args:
            symbol: 종목 코드.
            indicator: 지표 이름 (예: "sma", "rsi", "macd").
            params: pandas-ta 파라미터 오버라이드 (예: {"length": 50}).

        Returns:
            지표 결과 딕셔너리. 키는 지표명, 값은 numpy 배열.
        """
        from ante.strategy.indicators import IndicatorCalculator, ohlcv_to_dataframe

        ohlcv_data = await self._data.get_ohlcv(symbol, limit=500)
        arrays = ohlcv_to_dataframe(ohlcv_data)
        return IndicatorCalculator.compute(indicator, arrays, **(params or {}))

    # ── 포트폴리오 조회 ──

    def get_positions(self) -> dict[str, Any]:
        """현재 보유 포지션 조회."""
        return self._portfolio.get_positions(self.bot_id)

    def get_balance(self) -> dict[str, float]:
        """봇 할당 자금 현황 조회."""
        return self._portfolio.get_balance(self.bot_id)

    # ── 거래 이력 ──

    async def get_trade_history(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """봇의 거래 이력 조회. 최신순 반환."""
        if self._trade_history is None:
            return []
        return await self._trade_history.get_trade_history(
            self.bot_id, symbol=symbol, limit=limit
        )

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

    # ── 파일 접근 ──

    def _resolve_strategy_path(self, path: str) -> Path:
        """전략 파일 경로를 검증하고 절대 경로로 변환."""
        # 절대 경로 차단
        if Path(path).is_absolute():
            raise StrategyFileAccessError(f"Absolute paths are not allowed: {path}")

        # 경로 탈출 시도 차단
        resolved = (self._strategies_dir / path).resolve()
        if not resolved.is_relative_to(self._strategies_dir):
            raise StrategyFileAccessError(f"Path escapes strategies directory: {path}")

        return resolved

    def load_file(self, path: str) -> bytes:
        """전략 전용 파일 읽기 (바이너리).

        strategies/ 하위 경로만 허용. 경로 탈출 시도 차단.
        """
        resolved = self._resolve_strategy_path(path)

        if not resolved.exists():
            raise StrategyFileAccessError(f"File not found: {path}")

        self._log.info("[%s] Loading file: %s", self.bot_id, path)
        return resolved.read_bytes()

    def load_text(self, path: str, encoding: str = "utf-8") -> str:
        """전략 전용 파일 읽기 (텍스트).

        strategies/ 하위 경로만 허용. 경로 탈출 시도 차단.
        """
        data = self.load_file(path)
        return data.decode(encoding)

    # ── 로깅 ──

    def log(self, message: str, level: str = "info") -> None:
        """전략 로그 기록."""
        log_level = getattr(logging, level.upper(), logging.INFO)
        self._log.log(log_level, "[%s] %s", self.bot_id, message)
