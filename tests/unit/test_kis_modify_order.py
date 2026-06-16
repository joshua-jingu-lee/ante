"""KIS 국내주식 정정(order-rvsecncl) body 계약 테스트 (#2391, v1=price-only).

``KISDomesticAdapter.modify_order`` 는 cancel_order 를 미러링하되:

- ``RVSE_CNCL_DVSN_CD="01"`` (정정; 취소는 "02").
- ``ORD_QTY`` = 원주문 수량(불변), ``ORD_UNPR`` = 신규 정정 가격(``str(int(price))``).
- ``QTY_ALL_ORD_YN="Y"`` (전량·수량 불변), ``ORD_DVSN`` = limit("00").
- ``EXCG_ID_DVSN_CD`` = 공유 상수, ``CNDT_PRIC`` 미전송.
- ``KRX_FWDG_ORD_ORGNO`` 는 캐시 hit+영업일 일치 시 주입, **miss/stale →
  ``ModifyOrgnoUnavailableError`` raise(전송 금지, 취소와 달리 fail-closed)**.

live A/B(실전 KIS) 검증은 사용자 oracle 후속 — 본 모듈은 mock+모의 매핑/분기만.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.broker.exceptions import ModifyOrgnoUnavailableError
from ante.broker.fill_scheduler import business_date_kst
from ante.broker.kis import (
    _ORDER_TR_IDS,
    DEFAULT_EXCG_ID_DVSN_CD,
    KISDomesticAdapter,
)

_ORGNO = "00950"


def _make_adapter(*, is_paper: bool = False) -> KISDomesticAdapter:
    config = {
        "app_key": "test-key",
        "app_secret": "test-secret",
        "account_no": "1234567890",
        "is_paper": is_paper,
    }
    return KISDomesticAdapter(config=config)


def _stub_request(adapter: KISDomesticAdapter, response: dict) -> AsyncMock:
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    request = AsyncMock(return_value=response)
    adapter._request = request  # type: ignore[method-assign]
    return request


def _captured_modify_body(request: AsyncMock) -> dict:
    return request.call_args.kwargs["json_data"]


async def test_place_then_modify_body_contract() -> None:
    """place 응답 orgno 캐시 → 같은 영업일 정정 body 계약 lock."""
    adapter = _make_adapter()
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": _ORGNO}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "limit", price=50000)
    result = await adapter.modify_order(
        order_id, quantity=10, price=45000, order_type="limit"
    )
    assert result is True

    body = _captured_modify_body(request)
    assert body["RVSE_CNCL_DVSN_CD"] == "01"  # 정정 (취소 "02" 아님).
    assert body["ORD_QTY"] == "10"  # 원주문 수량 불변.
    assert body["ORD_UNPR"] == "45000"  # 신규 정정 가격.
    assert body["QTY_ALL_ORD_YN"] == "Y"
    assert body["ORD_DVSN"] == "00"  # limit.
    assert body["ORGN_ODNO"] == order_id
    assert body["KRX_FWDG_ORD_ORGNO"] == _ORGNO
    assert body["EXCG_ID_DVSN_CD"] == DEFAULT_EXCG_ID_DVSN_CD == "KRX"
    # CNDT_PRIC(조건가) 미전송.
    assert "CNDT_PRIC" not in body
    # 정확 필드 집합 lock.
    assert set(body) == {
        "CANO",
        "ACNT_PRDT_CD",
        "KRX_FWDG_ORD_ORGNO",
        "ORGN_ODNO",
        "ORD_DVSN",
        "RVSE_CNCL_DVSN_CD",
        "ORD_QTY",
        "ORD_UNPR",
        "QTY_ALL_ORD_YN",
        "EXCG_ID_DVSN_CD",
    }


async def test_modify_cache_miss_raises_typed_error() -> None:
    """캐시 miss → ModifyOrgnoUnavailableError raise + broker 전송 안 함."""
    adapter = _make_adapter()
    request = _stub_request(adapter, {"output": {}})

    with pytest.raises(ModifyOrgnoUnavailableError):
        await adapter.modify_order("9999999999", quantity=10, price=45000)

    # 전송 금지 — _request 미호출.
    request.assert_not_awaited()


async def test_modify_stale_business_day_raises_typed_error() -> None:
    """영업일 불일치(odno 재사용) → ModifyOrgnoUnavailableError + 전송 안 함."""
    adapter = _make_adapter()
    request = _stub_request(adapter, {"output": {}})

    adapter._krx_fwdg_orgno_cache["0001234567"] = (_ORGNO, "20200101")
    assert business_date_kst() != "20200101"

    with pytest.raises(ModifyOrgnoUnavailableError):
        await adapter.modify_order("0001234567", quantity=10, price=45000)

    request.assert_not_awaited()


@pytest.mark.parametrize("is_paper", [True, False])
async def test_modify_tr_id_paper_live(is_paper: bool) -> None:
    """정정 tr_id 가 모의 VTTC0013U / 실전 TTTC0013U (cancel 과 동일 패밀리)."""
    adapter = _make_adapter(is_paper=is_paper)
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": _ORGNO}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "limit", price=50000)
    await adapter.modify_order(order_id, quantity=10, price=45000)

    modify_tr_id = request.call_args_list[-1].args[2]
    assert modify_tr_id == ("VTTC0013U" if is_paper else "TTTC0013U")
    assert modify_tr_id in _ORDER_TR_IDS
    # order(주문) 분류 재시도/timeout 선택 lock.
    url = f"{adapter.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
    assert adapter._get_max_retries(url, modify_tr_id) == adapter._max_retries_order
