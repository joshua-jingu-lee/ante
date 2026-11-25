"""KIS 주문 접수는 buy·sell이 아닌 side를 인증·요청 한도·전송 전에 거부한다 (#3056).

인증·요청 한도 메서드를 가짜로 바꾸지 않고, 가짜 세션이 받은 전송 수로 센다.
실제 외부 API는 부르지 않는다.
"""

from __future__ import annotations

import json
import uuid

import pytest

from ante.broker.exceptions import BrokerError
from ante.broker.kis import KISDomesticAdapter
from tests.unit.test_kis_order_outcome_unknown import _Session, _status

_OK = json.dumps(
    {"access_token": "fake-token", "rt_cd": "0", "output": {"ODNO": "0000001"}}
)


def _make(*, is_paper: bool) -> tuple[KISDomesticAdapter, _Session]:
    adapter = KISDomesticAdapter(
        config={
            "app_key": f"fake-key-{uuid.uuid4().hex}",
            "app_secret": "fake-secret",
            "account_no": "0000000001",
            "is_paper": is_paper,
        }
    )
    session = _Session([_status(200, _OK)])
    adapter._session = session
    return adapter, session


@pytest.mark.parametrize("is_paper", [True, False])
async def test_valid_side_reaches_transport(is_paper: bool) -> None:
    """대조군: 같은 가짜 세션에서 buy는 인증과 주문을 실제로 전송한다."""
    adapter, session = _make(is_paper=is_paper)

    assert await adapter.place_order("005930", "buy", 1) == "0000001"
    assert session.sends == 2
    assert len(adapter._request_times) == 1


@pytest.mark.parametrize("is_paper", [True, False])
@pytest.mark.parametrize("order_type", ["market", "limit", "stop"])
@pytest.mark.parametrize("side", ["BUY", "hold", "", None, ["buy"]])
async def test_invalid_side_rejected_before_any_send(
    is_paper: bool, order_type: str, side: object
) -> None:
    """잘못된 side는 BrokerError이고 토큰·주문 요청을 하나도 보내지 않는다."""
    adapter, session = _make(is_paper=is_paper)
    price = 70_000.0 if order_type == "limit" else None

    with pytest.raises(BrokerError):
        await adapter.place_order(
            "005930",
            side,  # type: ignore[arg-type]
            1,
            order_type,
            price,
        )

    assert session.sends == 0
    assert adapter.access_token is None
    assert len(adapter._request_times) == 0
