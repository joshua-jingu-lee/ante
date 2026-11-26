"""KIS 어댑터는 표에 없는 order_type을 전송 전에 거부한다 (#3082).

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
    {
        "access_token": "fake-token",
        "rt_cd": "0",
        "output": {
            "ODNO": "0000001",
            "KRX_FWDG_ORD_ORGNO": "00950",
            "stck_prpr": "70000",
        },
    }
)

_INVALID = ["LIMIT", "limt", "", None, 1, []]

_VALID = {
    "market": "01",
    "limit": "00",
    "conditional": "02",
    "best": "03",
    "priority": "04",
}


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


def _assert_nothing_sent(adapter: KISDomesticAdapter, session: _Session) -> None:
    assert session.sends == 0
    assert adapter.access_token is None
    assert len(adapter._request_times) == 0
    assert len(adapter._krx_fwdg_orgno_cache) == 0


@pytest.mark.parametrize("is_paper", [True, False])
@pytest.mark.parametrize("order_type", _INVALID)
async def test_place_order_rejects_unknown_type_before_any_send(
    is_paper: bool, order_type: object
) -> None:
    """모르는 order_type의 주문 접수는 BrokerError이고 아무 요청도 보내지 않는다."""
    adapter, session = _make(is_paper=is_paper)

    with pytest.raises(BrokerError):
        await adapter.place_order(
            "005930",
            "buy",
            1,
            order_type,  # type: ignore[arg-type]
            70_000.0,
        )

    _assert_nothing_sent(adapter, session)


@pytest.mark.parametrize("is_paper", [True, False])
@pytest.mark.parametrize("order_type", [*_INVALID, "stop"])
async def test_get_buyable_rejects_unknown_type_before_price_lookup(
    is_paper: bool, order_type: object
) -> None:
    """매수가능 조회는 모르는 유형을 현재가 조회 전에 거부한다."""
    adapter, session = _make(is_paper=is_paper)

    with pytest.raises(BrokerError):
        await adapter.get_buyable("005930", None, order_type)  # type: ignore[arg-type]

    _assert_nothing_sent(adapter, session)


async def test_get_buyable_market_still_sends_price_then_psbl() -> None:
    """대조군: 시장가 매수가능 조회는 토큰·현재가·매수가능 순으로 보낸다."""
    adapter, session = _make(is_paper=True)

    await adapter.get_buyable("005930")

    assert session.sends == 3


@pytest.mark.parametrize(("order_type", "code"), sorted(_VALID.items()))
def test_map_order_type_valid_codes(order_type: str, code: str) -> None:
    """매핑 표의 값은 그대로 같은 코드로 매핑된다."""
    adapter, _ = _make(is_paper=True)
    assert adapter._map_order_type(order_type) == code


@pytest.mark.parametrize("order_type", [*_INVALID, "stop"])
def test_map_order_type_rejects_unknown(order_type: object) -> None:
    """표에 없는 값은 TypeError가 아니라 BrokerError다."""
    adapter, _ = _make(is_paper=True)
    with pytest.raises(BrokerError):
        adapter._map_order_type(order_type)  # type: ignore[arg-type]


@pytest.mark.parametrize("is_paper", [True, False])
async def test_limit_order_carries_price(is_paper: bool) -> None:
    """대조군: 지정가는 ORD_DVSN=00, ORD_UNPR=가격으로 전송된다."""
    adapter, session = _make(is_paper=is_paper)
    captured: list[dict] = []
    original = adapter._request

    async def _spy(method, url, tr_id, params=None, json_data=None):  # type: ignore[no-untyped-def]
        captured.append(dict(json_data or {}))
        return await original(method, url, tr_id, params=params, json_data=json_data)

    adapter._request = _spy  # type: ignore[method-assign]

    assert await adapter.place_order("005930", "buy", 1, "limit", 70_000.0) == "0000001"
    assert captured[0]["ORD_DVSN"] == "00"
    assert captured[0]["ORD_UNPR"] == "70000"
    assert session.sends == 2


@pytest.mark.parametrize("order_type", ["stop", "stop_limit"])
async def test_place_order_stop_types_keep_value_error(order_type: str) -> None:
    """주문 접수에서 stop/stop_limit은 기존처럼 ValueError다."""
    adapter, session = _make(is_paper=True)

    with pytest.raises(ValueError) as excinfo:
        await adapter.place_order("005930", "buy", 1, order_type, 70_000.0)

    assert not isinstance(excinfo.value, BrokerError)
    _assert_nothing_sent(adapter, session)
