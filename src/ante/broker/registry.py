"""Broker Registry — broker_type 문자열을 어댑터 클래스로 매핑.

AccountService.get_broker()에서 계좌의 broker_type으로
어댑터를 인스턴스화할 때 사용한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter


class InvalidBrokerTypeError(Exception):
    """미등록 broker_type 요청 시 발생."""

    def __init__(self, broker_type: str) -> None:
        self.broker_type = broker_type
        registered = ", ".join(sorted(BROKER_REGISTRY.keys()))
        super().__init__(
            f"미등록 broker_type: '{broker_type}'. 등록된 타입: [{registered}]"
        )


def _build_registry() -> dict[str, type[BrokerAdapter]]:
    """지연 import로 순환 의존을 방지하면서 레지스트리를 구축한다."""
    from ante.broker.kis import KISDomesticAdapter
    from ante.broker.test import TestBrokerAdapter

    return {
        "test": TestBrokerAdapter,
        "kis-domestic": KISDomesticAdapter,
    }


# 모듈 로드 시 레지스트리 초기화
BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = _build_registry()


def get_broker_class(broker_type: str) -> type[BrokerAdapter]:
    """broker_type에 해당하는 어댑터 클래스를 반환한다.

    Raises:
        InvalidBrokerTypeError: 미등록 broker_type
    """
    cls = BROKER_REGISTRY.get(broker_type)
    if cls is None:
        raise InvalidBrokerTypeError(broker_type)
    return cls
