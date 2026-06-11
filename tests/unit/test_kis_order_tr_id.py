"""KIS 국내주식 order-cash TR ID 매핑 회귀 테스트 (#2342).

``KISDomesticAdapter.place_order`` 가 KIS 공식 현행 order-cash TR ID 를
``is_paper`` × ``side`` 4조합으로 정확히 전송하는지 검증한다.

공식 현행 매핑(KIS open-trading-api examples_llm + Developers 포털 2축 검증):
    - 모의(paper) 매수: VTTC0012U / 모의 매도: VTTC0011U
    - 실전(live)  매수: TTTC0012U / 실전 매도: TTTC0011U

구버전(deprecated) order-cash TR ID(VTTC0802U/TTTC0802U/VTTC0801U/TTTC0311U)
가 더 이상 전송되지 않음을 회귀 lock 한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.broker.kis import DEFAULT_EXCG_ID_DVSN_CD, KISDomesticAdapter

# 구버전(deprecated) order-cash TR ID — 회귀 lock 대상.
_DEPRECATED_ORDER_TR_IDS = frozenset(
    {"VTTC0802U", "TTTC0802U", "VTTC0801U", "TTTC0311U"}
)

# order-cash 요청 바디의 정확한 키 집합(#2344). 국내 KRX 주문에서
# EXCG_ID_DVSN_CD 가 필수이며, SLL_TYPE/CNDT_PRIC 등 추가 필드 혼입을
# 차단하기 위해 포함 단언이 아닌 exact 키 집합으로 회귀 lock 한다.
_EXPECTED_ORDER_BODY_KEYS = frozenset(
    {
        "CANO",
        "ACNT_PRDT_CD",
        "PDNO",
        "ORD_DVSN",
        "ORD_QTY",
        "ORD_UNPR",
        "EXCG_ID_DVSN_CD",
    }
)


def _make_adapter(*, is_paper: bool) -> KISDomesticAdapter:
    """네트워크 없이 place_order TR ID 선택만 검증하기 위한 어댑터."""
    config = {
        "app_key": "test-key",
        "app_secret": "test-secret",
        "account_no": "1234567890",
        "is_paper": is_paper,
    }
    return KISDomesticAdapter(config=config)


@pytest.mark.parametrize(
    ("is_paper", "side", "expected_tr_id"),
    [
        (True, "buy", "VTTC0012U"),
        (True, "sell", "VTTC0011U"),
        (False, "buy", "TTTC0012U"),
        (False, "sell", "TTTC0011U"),
    ],
)
async def test_place_order_sends_official_order_cash_tr_id(
    is_paper: bool, side: str, expected_tr_id: str
) -> None:
    """place_order 가 is_paper × side 별 공식 현행 order-cash TR ID 를 전송한다."""
    adapter = _make_adapter(is_paper=is_paper)
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    request = AsyncMock(return_value={"output": {"ODNO": "123"}})
    adapter._request = request  # type: ignore[method-assign]

    order_id = await adapter.place_order("005930", side, 10, "market")

    assert order_id == "123"
    # _request(method, url, tr_id, ...) — tr_id 는 3번째 positional 인자.
    sent_tr_id = request.call_args.args[2]
    assert sent_tr_id == expected_tr_id
    # 회귀 lock: 구버전 order-cash TR ID 가 전송되지 않음.
    assert sent_tr_id not in _DEPRECATED_ORDER_TR_IDS


@pytest.mark.parametrize("is_paper", [True, False])
@pytest.mark.parametrize("side", ["buy", "sell"])
@pytest.mark.parametrize(
    ("order_type", "price", "expected_ord_dvsn", "expected_ord_unpr"),
    [
        ("market", None, "01", "0"),
        ("limit", 70000.0, "00", "70000"),
    ],
)
async def test_place_order_body_includes_excg_id_dvsn_cd(
    is_paper: bool,
    side: str,
    order_type: str,
    price: float | None,
    expected_ord_dvsn: str,
    expected_ord_unpr: str,
) -> None:
    """order-cash 바디가 EXCG_ID_DVSN_CD 를 포함한 exact 7키만 전송한다 (#2344).

    모의/실전 × buy/sell × market/limit 전 조합에서 국내 KRX 주문 필수 필드
    EXCG_ID_DVSN_CD="KRX" 가 side·order_type 무관하게 포함되며, SLL_TYPE/
    CNDT_PRIC 등 비목표 필드가 혼입되지 않음을 exact 키 집합으로 lock 한다.
    """
    adapter = _make_adapter(is_paper=is_paper)
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    request = AsyncMock(return_value={"output": {"ODNO": "123"}})
    adapter._request = request  # type: ignore[method-assign]

    await adapter.place_order("005930", side, 10, order_type, price)

    # _request(method, url, tr_id, json_data=...) — 바디는 json_data 키워드 인자.
    body = request.call_args.kwargs["json_data"]
    # 포함 단언 금지: exact 7키 집합으로 추가/누락 필드를 모두 회귀 lock.
    assert set(body) == _EXPECTED_ORDER_BODY_KEYS
    assert body["CANO"] == "12345678"
    assert body["ACNT_PRDT_CD"] == "90"
    assert body["PDNO"] == "005930"
    assert body["ORD_DVSN"] == expected_ord_dvsn
    assert body["ORD_QTY"] == "10"
    assert body["ORD_UNPR"] == expected_ord_unpr
    # 국내 KRX 주문 필수 필드(#2344) — side·order_type 무관 상수.
    assert body["EXCG_ID_DVSN_CD"] == DEFAULT_EXCG_ID_DVSN_CD == "KRX"
