"""KIS 국내주식 취소(order-rvsecncl) body의 KRX_FWDG_ORD_ORGNO 계약 테스트 (#2345).

``KISDomesticAdapter`` 는 원주문 접수(order-cash) 응답의
``KRX_FWDG_ORD_ORGNO``(한국거래소전송주문조직번호)를 인메모리 캐시에 보존하고,
취소 시 같은 broker_order_id(ODNO)·같은 KST 영업일이면 cancel body 에 주입한다.
캐시 miss / 응답에 필드 없음 / 영업일 불일치(odno 재사용) 시에는 필드를 생략한다
(고정 9필드 — 8필드 + EXCG_ID_DVSN_CD, 네트워크/추가 조회 없음).

신세대(0013U) tr_id·필수 EXCG_ID_DVSN_CD 회귀도 함께 lock 한다(#2346).

캡처 원천: 공식 order-cash 결과 컬럼(chk_order_cash.py)에 ODNO/ORD_TMD 와 함께
``KRX_FWDG_ORD_ORGNO`` 가 정의되어 있어, place_order 가 읽는 동일 ``output`` dict
에서 직접 캡처한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.broker.fill_scheduler import business_date_kst
from ante.broker.kis import (
    _ORDER_TR_IDS,
    DEFAULT_EXCG_ID_DVSN_CD,
    KISDomesticAdapter,
)

_ORGNO = "00950"


def _make_adapter(*, is_paper: bool = False) -> KISDomesticAdapter:
    """네트워크 없이 place/cancel body 만 검증하기 위한 어댑터."""
    config = {
        "app_key": "test-key",
        "app_secret": "test-secret",
        "account_no": "1234567890",
        "is_paper": is_paper,
    }
    return KISDomesticAdapter(config=config)


def _stub_request(adapter: KISDomesticAdapter, response: dict) -> AsyncMock:
    """``_request`` 와 인증/레이트리밋을 stub 하고 mock 을 반환한다."""
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    request = AsyncMock(return_value=response)
    adapter._request = request  # type: ignore[method-assign]
    return request


def _captured_cancel_body(request: AsyncMock) -> dict:
    """캡처된 cancel POST 의 json_data(키워드 인자)를 반환한다."""
    return request.call_args.kwargs["json_data"]


async def test_place_then_cancel_includes_krx_fwdg_ord_orgno() -> None:
    """(a) place 응답에 필드 포함 → 같은 영업일 cancel body 에 캐시값 주입."""
    adapter = _make_adapter()
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": _ORGNO}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "market")
    assert order_id == "0001234567"

    result = await adapter.cancel_order(order_id)
    assert result is True

    body = _captured_cancel_body(request)
    assert body["KRX_FWDG_ORD_ORGNO"] == _ORGNO
    assert body["ORGN_ODNO"] == order_id


async def test_cancel_cache_miss_omits_field_and_succeeds() -> None:
    """(b) 캐시에 없는 order_id 취소 → 필드 생략 + 취소 정상(True)."""
    adapter = _make_adapter()
    request = _stub_request(adapter, {"output": {}})

    result = await adapter.cancel_order("9999999999")
    assert result is True

    body = _captured_cancel_body(request)
    assert "KRX_FWDG_ORD_ORGNO" not in body


async def test_place_without_orgno_field_not_cached() -> None:
    """(c) place 응답에 KRX_FWDG_ORD_ORGNO 없음 → 캐시 안 함 → cancel 시 생략."""
    adapter = _make_adapter()
    request = _stub_request(adapter, {"output": {"ODNO": "0001234567"}})

    order_id = await adapter.place_order("005930", "buy", 10, "market")
    await adapter.cancel_order(order_id)

    body = _captured_cancel_body(request)
    assert "KRX_FWDG_ORD_ORGNO" not in body


async def test_place_with_empty_orgno_not_cached() -> None:
    """(c') place 응답 필드가 빈 문자열 → 캐시 안 함(오값 전송 금지)."""
    adapter = _make_adapter()
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": ""}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "market")
    await adapter.cancel_order(order_id)

    body = _captured_cancel_body(request)
    assert "KRX_FWDG_ORD_ORGNO" not in body


async def test_cancel_stale_business_day_omits_field() -> None:
    """(d) 영업일 불일치(재사용 odno, 과거 영업일 캐시) → 필드 생략."""
    adapter = _make_adapter()
    request = _stub_request(adapter, {"output": {}})

    # 과거 영업일로 직접 캐시를 seed 해 odno 재사용 상황을 재현한다.
    adapter._krx_fwdg_orgno_cache["0001234567"] = (_ORGNO, "20200101")
    assert business_date_kst() != "20200101"

    result = await adapter.cancel_order("0001234567")
    assert result is True

    body = _captured_cancel_body(request)
    assert "KRX_FWDG_ORD_ORGNO" not in body


async def test_cancel_body_regression_lock() -> None:
    """(e) cancel body 회귀 lock (캐시 hit 시 기존 필드 불변 + EXCG 추가, #2346)."""
    adapter = _make_adapter()
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": _ORGNO}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "market")
    await adapter.cancel_order(order_id)

    body = _captured_cancel_body(request)
    assert body["CANO"] == "12345678"
    assert body["ACNT_PRDT_CD"] == "90"
    assert body["ORGN_ODNO"] == order_id
    assert body["ORD_DVSN"] == "01"
    assert body["RVSE_CNCL_DVSN_CD"] == "02"
    assert body["ORD_QTY"] == "0"
    assert body["ORD_UNPR"] == "0"
    assert body["QTY_ALL_ORD_YN"] == "Y"
    # 신세대(0013U) 필수 EXCG_ID_DVSN_CD — 공유 상수(#2344) 재사용.
    assert body["EXCG_ID_DVSN_CD"] == DEFAULT_EXCG_ID_DVSN_CD == "KRX"
    # 기존 8필드 + KRX_FWDG(조건부 hit) + EXCG = 총 10필드.
    assert set(body) == {
        "CANO",
        "ACNT_PRDT_CD",
        "ORGN_ODNO",
        "ORD_DVSN",
        "RVSE_CNCL_DVSN_CD",
        "ORD_QTY",
        "ORD_UNPR",
        "QTY_ALL_ORD_YN",
        "KRX_FWDG_ORD_ORGNO",
        "EXCG_ID_DVSN_CD",
    }


async def test_cache_is_bounded() -> None:
    """캐시는 maxlen 으로 bounded — 무한 증가하지 않고 오래된 항목부터 evict."""
    from ante.broker.kis import _KRX_FWDG_ORGNO_CACHE_MAXLEN

    adapter = _make_adapter()
    today = business_date_kst()
    for i in range(_KRX_FWDG_ORGNO_CACHE_MAXLEN + 50):
        adapter._cache_krx_fwdg_orgno(f"odno-{i}", _ORGNO)

    assert len(adapter._krx_fwdg_orgno_cache) == _KRX_FWDG_ORGNO_CACHE_MAXLEN
    # 가장 오래된 항목들이 evict 됨.
    assert "odno-0" not in adapter._krx_fwdg_orgno_cache
    # 최신 항목은 유지되고 영업일도 함께 저장됨.
    last_key = f"odno-{_KRX_FWDG_ORGNO_CACHE_MAXLEN + 49}"
    assert adapter._krx_fwdg_orgno_cache[last_key] == (_ORGNO, today)


@pytest.mark.parametrize("is_paper", [True, False])
async def test_cancel_works_for_paper_and_live(is_paper: bool) -> None:
    """모의/실전 모두 캐시 hit 시 cancel body 에 필드 주입."""
    adapter = _make_adapter(is_paper=is_paper)
    request = _stub_request(
        adapter, {"output": {"ODNO": "0001234567", "KRX_FWDG_ORD_ORGNO": _ORGNO}}
    )

    order_id = await adapter.place_order("005930", "buy", 10, "market")
    await adapter.cancel_order(order_id)

    body = _captured_cancel_body(request)
    assert body["KRX_FWDG_ORD_ORGNO"] == _ORGNO
    # tr_id 도 환경별로 올바른지(취소 tr_id 회귀): 신세대 0013U (#2346).
    cancel_tr_id = request.call_args_list[-1].args[2]
    assert cancel_tr_id == ("VTTC0013U" if is_paper else "TTTC0013U")


def test_cancel_tr_id_in_order_whitelist() -> None:
    """취소 tr_id 가 ``_ORDER_TR_IDS`` 화이트리스트에 동기화돼 있는지 직접 단언 (#2346).

    취소 본문 테스트는 ``_request`` 를 stub 하므로, ``_ORDER_TR_IDS`` 화이트리스트
    교체가 누락돼도 본문 단언은 침묵 통과한다(Codex R1 ①). 이 화이트리스트는
    재시도 상한(``_get_max_retries``)·요청 timeout(``_timeout_order`` vs
    ``_timeout_query``) 선택을 결정하므로, 신세대 0013U 가 set 에 포함되고
    레거시 0803U 가 제거됐는지 직접 lock 한다.
    """
    assert "VTTC0013U" in _ORDER_TR_IDS
    assert "TTTC0013U" in _ORDER_TR_IDS
    # 레거시 취소 tr_id 는 화이트리스트에서 제거됨(회귀 lock).
    assert "VTTC0803U" not in _ORDER_TR_IDS
    assert "TTTC0803U" not in _ORDER_TR_IDS


@pytest.mark.parametrize("is_paper", [True, False])
def test_cancel_tr_id_selects_order_retry_and_timeout(is_paper: bool) -> None:
    """신세대 취소 tr_id 가 order(주문) 재시도 상한·timeout 을 선택하는지 단언 (#2346).

    화이트리스트 동기화가 실제 재시도/timeout 분류로 이어지는지 행동 단언:
    0013U 가 query 가 아닌 order 분류(``_max_retries_order``·``_timeout_order``)를
    타야 한다. ``_ORDER_TR_IDS`` 에서 0013U 가 빠지면 query 분류로 fallback 되어
    이 단언이 FAIL 한다(stub 침묵 통과 갭 차단).
    """
    adapter = _make_adapter(is_paper=is_paper)
    cancel_tr_id = "VTTC0013U" if is_paper else "TTTC0013U"
    url = f"{adapter.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"

    # 재시도 상한: order 분류(query 가 아님).
    assert adapter._get_max_retries(url, cancel_tr_id) == adapter._max_retries_order
    # timeout 선택: order 분류(query 가 아님). order/query 가 동일값이면
    # 분류 회귀를 잡지 못하므로, 화이트리스트 membership 도 함께 단언한다.
    assert cancel_tr_id in _ORDER_TR_IDS
    selected_timeout = (
        adapter._timeout_order
        if cancel_tr_id in _ORDER_TR_IDS
        else adapter._timeout_query
    )
    assert selected_timeout == adapter._timeout_order
