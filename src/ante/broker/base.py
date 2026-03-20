"""BrokerAdapter 추상 기본 클래스.

모든 증권사 구현체는 이 ABC를 상속한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.broker.models import CommissionInfo


class BrokerAdapter(ABC):
    """증권사 API 어댑터 추상 기본 클래스."""

    # 서브클래스에서 오버라이드하는 브로커 메타정보
    broker_id: str = "unknown"
    broker_name: str = "Unknown Broker"
    broker_short_name: str = "UNK"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.is_connected: bool = False
        self.exchange: str = config.get("exchange", "KRX")
        self.currency: str = config.get("currency", "KRW")

    @abstractmethod
    async def connect(self) -> None:
        """API 연결 및 인증."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """연결 해제."""
        ...

    @abstractmethod
    async def get_account_balance(self) -> dict[str, float]:
        """계좌 잔고 조회.

        Returns:
            {"cash": float, "total_assets": float, ...}
        """
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회.

        Returns:
            [{"symbol": str, "quantity": float, "avg_price": float, ...}, ...]
        """
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수.

        Args:
            symbol: 종목코드
            side: "buy" | "sell"
            quantity: 주문 수량
            order_type: "market" | "limit"
            price: 지정가 주문 시 가격
            stop_price: stop 주문 가격 (브로커가 지원하는 경우)

        Returns:
            증권사 주문번호 (broker_order_id)
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소.

        Returns:
            성공 여부
        """
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회.

        Returns:
            {"order_id": str, "symbol": str, "side": str, "status": str, ...}
        """
        ...

    @abstractmethod
    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        ...

    # ── 대사(Reconciliation)용 조회 ────────────────────

    @abstractmethod
    async def get_account_positions(self) -> list[dict[str, Any]]:
        """증권사 실제 보유 잔고 조회 (대사용).

        Returns:
            [{"symbol": str, "quantity": float, "avg_price": float}, ...]
        """
        ...

    @abstractmethod
    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """증권사 주문/체결 이력 조회 (대사용).

        Returns:
            [{"order_id": str, "symbol": str, "side": str,
              "quantity": float, "filled_quantity": float,
              "price": float, "status": str, "timestamp": str}, ...]
        """
        ...

    # ── 종목 마스터 ────────────────────────────────────

    @abstractmethod
    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """종목 마스터 데이터 조회.

        Returns:
            [{"symbol": str, "name": str, "name_en": str,
              "instrument_type": str, "listed": bool}, ...]
        """
        ...

    # ── 수수료 ────────────────────────────────────────

    @abstractmethod
    def get_commission_info(self) -> CommissionInfo:
        """증권사별 수수료율 정보 반환."""
        ...

    # ── 헬퍼 메서드 ─────────────────────────────────

    def normalize_symbol(self, symbol: str) -> str:
        """종목코드 표준화 (예: '5930' → '005930')."""
        return symbol.zfill(6) if symbol.isdigit() else symbol

    async def health_check(self) -> bool:
        """API 연결 상태 확인."""
        try:
            await self.get_account_balance()
            return True
        except Exception:
            return False
