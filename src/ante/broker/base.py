"""BrokerAdapter 추상 기본 클래스."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ante.broker.exceptions import BrokerError

if TYPE_CHECKING:
    from ante.broker.models import CommissionInfo

ORDER_SIDES: frozenset[str] = frozenset({"buy", "sell"})


def ensure_order_side(side: object) -> None:
    """``side``가 ``ORDER_SIDES``의 문자열이 아니면 ``BrokerError``를 낸다."""
    if not isinstance(side, str) or side not in ORDER_SIDES:
        raise BrokerError(f"지원하지 않는 주문 side: {side!r}")


class BrokerAdapter(ABC):
    """증권사 API 어댑터 추상 기본 클래스."""

    broker_id: str = "unknown"
    broker_name: str = "Unknown Broker"
    broker_short_name: str = "UNK"
    websocket_url: str | None = None

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
    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict[str, float]:
        """매수가능 조회 (KIS ``inquire-psbl-order``).

        Returns:
            {"order_buyable_amount": float, "max_buyable_amount": float,
             "order_cash": float, "order_buyable_qty": float,
             "max_buyable_qty": float}
            - ``order_buyable_amount``: 미수 미사용 매수가능금액
              (**purchasable_amount SSOT** — 보수값)
            - ``order_buyable_qty`` / ``max_buyable_qty``: 종목/단가 의존 수량
        """
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
            side: "buy" | "sell"
            order_type: "market" | "limit"
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
    async def modify_order(
        self,
        order_id: str,
        *,
        quantity: float | None = None,
        price: float | None = None,
        order_type: str = "limit",
    ) -> bool:
        """주문 정정 (v1=price-only).

        v1 은 ``open`` 상태 주문의 **가격 정정**만 지원한다(수량 불변). 수량 변경
        (``quantity``)·예산 증가 buy 가격↑·부분체결/터미널·동시성은 Gateway 가
        broker 호출 **전** fail-closed 로 거부하므로 broker 까지 내려오지 않는다
        (고급 케이스는 deferred). ``quantity`` 는 forward-compat 파라미터다.
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

    @abstractmethod
    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """종목 마스터 데이터 조회.

        Returns:
            [{"symbol": str, "name": str, "name_en": str,
              "instrument_type": str, "listed": bool}, ...]
        """
        ...

    @abstractmethod
    def get_commission_info(self) -> CommissionInfo:
        """증권사별 수수료율 정보 반환."""
        ...

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
