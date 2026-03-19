"""Strategy ABC, Signal, StrategyMeta, OrderAction, Provider ABCs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# ── 메타데이터 ────────────────────────────────────


@dataclass(frozen=True)
class StrategyMeta:
    """전략 메타데이터. 모든 전략이 클래스 변수로 선언해야 함."""

    name: str
    version: str
    description: str
    author: str = "agent"
    symbols: list[str] | None = None
    timeframe: str = "1d"
    exchange: str = "KRX"
    accepts_external_signals: bool = False


# ── 시그널 / 주문 액션 ────────────────────────────


@dataclass(frozen=True)
class Signal:
    """전략이 생성하는 매매 시그널."""

    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    order_type: str = "market"
    price: float | None = None
    stop_price: float | None = None
    reason: str = ""
    trading_session: str = "regular"  # "regular" | "extended"


@dataclass(frozen=True)
class OrderAction:
    """전략이 요청하는 주문 관리 액션 (취소/정정)."""

    action: str  # "cancel" | "modify"
    order_id: str
    quantity: float | None = None
    price: float | None = None
    reason: str = ""


# ── Provider ABCs ─────────────────────────────────


class DataProvider(ABC):
    """데이터 조회 인터페이스."""

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> Any:
        """OHLCV 데이터 조회."""
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        ...

    @abstractmethod
    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """기술 지표 데이터 조회."""
        ...


class PortfolioView(ABC):
    """포트폴리오 읽기 전용 인터페이스."""

    @abstractmethod
    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """현재 보유 포지션 조회."""
        ...

    @abstractmethod
    def get_balance(self, bot_id: str) -> dict[str, float]:
        """봇 할당 자금 현황 조회."""
        ...


class OrderView(ABC):
    """주문 조회 인터페이스."""

    @abstractmethod
    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        ...


class TradeHistoryView(ABC):
    """거래 이력 읽기 전용 인터페이스."""

    @abstractmethod
    async def get_trade_history(
        self,
        bot_id: str,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """봇의 거래 이력 조회. 최신순 반환."""
        ...


# ── Strategy ABC ──────────────────────────────────


class Strategy(ABC):
    """모든 전략의 기본 클래스."""

    meta: StrategyMeta

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ── 라이프사이클 ──

    def on_start(self) -> None:
        """봇 시작 시 1회 호출."""

    def on_stop(self) -> None:
        """봇 중지 시 1회 호출."""

    # ── 시그널 생성 (핵심) ──

    @abstractmethod
    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """주기적으로 호출되어 매매 시그널을 반환."""
        ...

    # ── 이벤트 핸들러 (선택) ──
    # 서브클래스에서 override하여 async 작업을 수행할 수 있으므로 async def 유지

    async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
        """주문 체결 통보."""
        return []

    async def on_order_update(self, update: dict[str, Any]) -> None:
        """주문 상태 변경 통보."""

    async def on_data(self, data: dict[str, Any]) -> list[Signal]:
        """외부 데이터 수신."""
        return []

    async def on_position_corrected(self, correction: dict[str, Any]) -> None:
        """대사에 의한 포지션 보정 통보."""

    # ── 전략별 룰 / 파라미터 (선택) ──

    def get_rules(self) -> dict[str, Any]:
        """전략별 거래 룰 반환."""
        return {}

    def get_params(self) -> dict[str, Any]:
        """백테스트 최적화 파라미터 반환."""
        return {}

    def get_param_schema(self) -> dict[str, str]:
        """파라미터 설명 반환. {파라미터명: 설명} 형식."""
        return {}
