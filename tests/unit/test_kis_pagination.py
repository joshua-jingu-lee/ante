"""KIS 조회 메서드 CTX_AREA/tr_cont 연속조회(pagination) 테스트 (#2126).

KISDomesticAdapter 조회 메서드가 2페이지 이후 잔고·미체결·체결이력을 누락하지
않도록, 응답 헤더 ``tr_cont`` 와 body ``ctx_area_fk100/nk100`` cursor 를 따라
전 페이지를 누적하는지 검증한다.

검증 축:
    (a) 단일 페이지(tr_cont="D") → 1회 호출.
    (b) 2페이지(F→D) → cursor 가 다음 요청 params 로 전달 + 2회 호출 + 전행 누적.
    (c) tr_cont="F"/"M" 인데 cursor 비어 있음 → warning + 중단.
    (d) max-page 안전 상한 도달 → warning + 중단.
    (e) 5개 메서드 각각 다중 페이지 누적.
    (f) 비페이지 _request 호출자(주문 등) 회귀 — body-only 보존.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.broker.kis import DEFAULT_MAX_PAGINATION_PAGES, KISDomesticAdapter

_CONFIG = {
    "app_key": "test-key",
    "app_secret": "test-secret",
    "account_no": "1234567890",
    "is_paper": True,
}


def _make_adapter() -> KISDomesticAdapter:
    """네트워크 없이 페이지 루프만 검증하기 위한 어댑터."""
    return KISDomesticAdapter(config=_CONFIG)


def _page(
    rows: list[dict[str, Any]], row_key: str, *, fk: str = "", nk: str = ""
) -> dict[str, Any]:
    """단일 페이지 응답 body 구성."""
    return {
        "rt_cd": "0",
        row_key: rows,
        "ctx_area_fk100": fk,
        "ctx_area_nk100": nk,
    }


# ── _request_paginated 코어 동작 ──────────────────────────────


async def test_single_page_stops_after_one_call() -> None:
    """tr_cont="D" 단일 페이지 → 1회 호출, 그 행만 누적."""
    adapter = _make_adapter()
    body = _page([{"id": "a"}], "output1")
    adapter._request_with_cont = AsyncMock(return_value=(body, "D"))  # type: ignore[method-assign]

    rows = await adapter._request_paginated(
        "GET",
        "url",
        "TR",
        {"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
        row_key="output1",
    )

    assert rows == [{"id": "a"}]
    assert adapter._request_with_cont.call_count == 1
    # 최초 요청 헤더 tr_cont="" (cont_header 미전달 또는 "").
    _, kwargs = adapter._request_with_cont.call_args
    assert kwargs.get("cont_header", "") == ""


async def test_two_pages_passes_cursor_and_accumulates() -> None:
    """F→D 2페이지: cursor 가 다음 요청 params 로 전달 + 2회 + 전행 누적.

    ``_request_paginated`` 가 단일 ``params`` dict 를 재사용·mutate 하므로
    ``call_args_list`` 의 dict 참조는 마지막 상태를 가리킨다. 호출 시점의
    cursor/헤더 값을 side_effect 안에서 스냅샷해 검증한다.
    """
    adapter = _make_adapter()
    page1 = _page([{"id": "a"}], "output1", fk="FK-NEXT", nk="NK-NEXT")
    page2 = _page([{"id": "b"}], "output1")
    responses = iter([(page1, "F"), (page2, "D")])
    snapshots: list[tuple[str, str, str]] = []

    async def fake(method, url, tr_id, params=None, json_data=None, cont_header=""):  # type: ignore[no-untyped-def]
        snapshots.append(
            (
                params["CTX_AREA_FK100"],
                params["CTX_AREA_NK100"],
                cont_header,
            )
        )
        return next(responses)

    adapter._request_with_cont = fake  # type: ignore[method-assign]

    rows = await adapter._request_paginated(
        "GET",
        "url",
        "TR",
        {"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
        row_key="output1",
    )

    assert rows == [{"id": "a"}, {"id": "b"}]
    assert len(snapshots) == 2
    # 1페이지: cursor 빈 값, 헤더 tr_cont="".
    assert snapshots[0] == ("", "", "")
    # 2페이지: 직전 body cursor 가 다음 요청 params 로 + 헤더 tr_cont="N".
    assert snapshots[1] == ("FK-NEXT", "NK-NEXT", "N")


async def test_first_page_params_not_mutated() -> None:
    """호출자가 넘긴 base_params 원본은 변형되지 않는다."""
    adapter = _make_adapter()
    page1 = _page([{"id": "a"}], "output", fk="FK", nk="NK")
    page2 = _page([{"id": "b"}], "output")
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(page1, "M"), (page2, "E")]
    )
    base = {"CTX_AREA_FK100": "", "CTX_AREA_NK100": "", "X": "1"}

    await adapter._request_paginated("GET", "url", "TR", base, row_key="output")

    assert base == {"CTX_AREA_FK100": "", "CTX_AREA_NK100": "", "X": "1"}


async def test_has_next_but_empty_cursor_warns_and_stops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tr_cont="F"/"M" 인데 cursor 비어 있음 → warning + 중단(무한루프 방지)."""
    adapter = _make_adapter()
    body = _page([{"id": "a"}], "output1", fk="", nk="")
    adapter._request_with_cont = AsyncMock(return_value=(body, "F"))  # type: ignore[method-assign]

    with caplog.at_level("WARNING"):
        rows = await adapter._request_paginated(
            "GET",
            "url",
            "TR",
            {"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
            row_key="output1",
        )

    assert rows == [{"id": "a"}]
    assert adapter._request_with_cont.call_count == 1
    assert any("cursor 누락" in r.message for r in caplog.records)


async def test_max_page_cap_warns_and_stops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """매 페이지 tr_cont="F" + cursor 유효 → max-page 상한 도달 시 warning + 중단."""
    adapter = _make_adapter()
    # 항상 다음 페이지가 있다고 응답 (cursor 도 항상 유효) → 상한이 유일한 종료조건.
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        return_value=(_page([{"id": "x"}], "output1", fk="F", nk="N"), "F")
    )

    with caplog.at_level("WARNING"):
        rows = await adapter._request_paginated(
            "GET",
            "url",
            "TR",
            {"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
            row_key="output1",
        )

    assert adapter._request_with_cont.call_count == DEFAULT_MAX_PAGINATION_PAGES
    assert len(rows) == DEFAULT_MAX_PAGINATION_PAGES
    assert any("최대 페이지" in r.message for r in caplog.records)


async def test_only_row_key_accumulated_not_output2() -> None:
    """row_key 행만 누적하고 output2(summary/metadata)는 누적 금지."""
    adapter = _make_adapter()
    body = {
        "rt_cd": "0",
        "output1": [{"id": "a"}],
        "output2": [{"summary": "should-not-accumulate"}],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }
    adapter._request_with_cont = AsyncMock(return_value=(body, "D"))  # type: ignore[method-assign]

    rows = await adapter._request_paginated(
        "GET",
        "url",
        "TR",
        {"CTX_AREA_FK100": "", "CTX_AREA_NK100": ""},
        row_key="output1",
    )

    assert rows == [{"id": "a"}]
    assert all("summary" not in r for r in rows)


async def test_missing_row_key_yields_empty() -> None:
    """row_key 자체가 없거나 None 이면 빈 누적으로 안전 처리."""
    adapter = _make_adapter()
    body = {"rt_cd": "0", "output1": None, "ctx_area_fk100": "", "ctx_area_nk100": ""}
    adapter._request_with_cont = AsyncMock(return_value=(body, "D"))  # type: ignore[method-assign]

    rows = await adapter._request_paginated("GET", "url", "TR", {}, row_key="output1")

    assert rows == []


# ── 5개 메서드 적용: 다중 페이지 누적 ───────────────────────


async def test_get_positions_accumulates_all_pages() -> None:
    """get_positions: output1 2페이지(F→D) → 양 페이지 포지션 모두 반환."""
    adapter = _make_adapter()
    p1 = _page([{"pdno": "005930", "hldg_qty": "10"}], "output1", fk="FK1", nk="NK1")
    p2 = _page([{"pdno": "000660", "hldg_qty": "5"}], "output1")
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(p1, "F"), (p2, "D")]
    )

    positions = await adapter.get_positions()

    symbols = {p["symbol"] for p in positions}
    assert symbols == {"005930", "000660"}
    assert adapter._request_with_cont.call_count == 2


async def test_get_account_positions_accumulates_via_positions() -> None:
    """get_account_positions 는 get_positions 에 위임 → 다중 페이지 자동 커버."""
    adapter = _make_adapter()
    p1 = _page([{"pdno": "005930", "hldg_qty": "10"}], "output1", fk="FK", nk="NK")
    p2 = _page([{"pdno": "000660", "hldg_qty": "5"}], "output1")
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(p1, "M"), (p2, "E")]
    )

    recon = await adapter.get_account_positions()

    assert {r["symbol"] for r in recon} == {"005930", "000660"}
    assert adapter._request_with_cont.call_count == 2


async def test_get_pending_orders_accumulates_all_pages() -> None:
    """get_pending_orders: output 2페이지 → 양 페이지 주문 모두 반환."""
    adapter = _make_adapter()
    o1 = _page(
        [{"odno": "0001", "sll_buy_dvsn_cd": "02", "ord_qty": "10"}],
        "output",
        fk="FK1",
        nk="NK1",
    )
    o2 = _page([{"odno": "0002", "sll_buy_dvsn_cd": "01", "ord_qty": "20"}], "output")
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(o1, "F"), (o2, "D")]
    )

    orders = await adapter.get_pending_orders()

    assert {o["order_id"] for o in orders} == {"0001", "0002"}
    assert adapter._request_with_cont.call_count == 2


async def test_get_order_status_finds_order_on_second_page() -> None:
    """get_order_status: 2페이지에만 있는 주문도 전 페이지 확보 후 검색 성공."""
    adapter = _make_adapter()
    o1 = _page(
        [{"odno": "0001", "sll_buy_dvsn_cd": "02"}], "output", fk="FK1", nk="NK1"
    )
    o2 = _page(
        [
            {
                "odno": "0002",
                "sll_buy_dvsn_cd": "01",
                "ord_qty": "20",
                "tot_ccld_qty": "5",
                "rmn_qty": "15",
                "ord_stat_cd": "20",
            }
        ],
        "output",
    )
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(o1, "F"), (o2, "D")]
    )

    status = await adapter.get_order_status("0002")

    assert status["order_id"] == "0002"
    assert status["status"] == "partial_filled"
    # early-return 대신 전 페이지 확보: 2페이지 모두 조회.
    assert adapter._request_with_cont.call_count == 2


async def test_get_order_history_accumulates_then_folds() -> None:
    """get_order_history: 2페이지 누적 후 _fold_order_history 1회 적용."""
    adapter = _make_adapter()
    h1 = _page(
        [
            {
                "odno": "0001",
                "tot_ccld_qty": "40",
                "tot_ccld_amt": "400000",
                "ord_dt": "20260529",
                "sll_buy_dvsn_cd": "02",
            }
        ],
        "output1",
        fk="FK1",
        nk="NK1",
    )
    # 같은 odno/영업일의 더 큰 누적 행이 다음 페이지에 → fold 가 양쪽을 합산해야.
    h2 = _page(
        [
            {
                "odno": "0001",
                "tot_ccld_qty": "100",
                "tot_ccld_amt": "1020000",
                "ord_dt": "20260529",
                "sll_buy_dvsn_cd": "02",
            },
            {
                "odno": "0002",
                "tot_ccld_qty": "10",
                "tot_ccld_amt": "100000",
                "ord_dt": "20260529",
                "sll_buy_dvsn_cd": "01",
            },
        ],
        "output1",
    )
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(h1, "F"), (h2, "D")]
    )

    history = await adapter.get_order_history()

    by_id = {h["order_id"]: h for h in history}
    assert set(by_id) == {"0001", "0002"}
    # fold 가 2페이지에 걸친 같은 odno 행을 max 누적으로 합산.
    assert by_id["0001"]["filled_quantity"] == 100.0
    assert by_id["0001"]["price"] == 10200.0
    assert adapter._request_with_cont.call_count == 2


async def test_get_order_status_not_found_raises_after_all_pages() -> None:
    """전 페이지 확보 후에도 못 찾으면 OrderNotFoundError."""
    from ante.broker.exceptions import OrderNotFoundError

    adapter = _make_adapter()
    o1 = _page([{"odno": "0001"}], "output", fk="FK1", nk="NK1")
    o2 = _page([{"odno": "0002"}], "output")
    adapter._request_with_cont = AsyncMock(  # type: ignore[method-assign]
        side_effect=[(o1, "F"), (o2, "D")]
    )

    with pytest.raises(OrderNotFoundError):
        await adapter.get_order_status("9999")
    assert adapter._request_with_cont.call_count == 2


# ── _request body-only 회귀 (비페이지 호출자 보존) ──────────


async def test_request_returns_body_only() -> None:
    """_request 는 (body, tr_cont) 가 아닌 body dict 만 반환(주문 등 호출자 보존)."""
    adapter = _make_adapter()
    body = {"rt_cd": "0", "output": {"ODNO": "0001"}}
    adapter._send_http = AsyncMock(return_value=(body, "D"))  # type: ignore[method-assign]
    adapter._circuit_breaker = MagicMock()
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]

    result = await adapter._request("POST", "url", "TTTC0802U", json_data={"x": "1"})

    assert result == body
    assert isinstance(result, dict)


async def test_place_order_unaffected_by_pagination_change() -> None:
    """주문 접수는 _request(body-only) 경로 그대로 — ODNO 추출 회귀."""
    adapter = _make_adapter()
    body = {"rt_cd": "0", "output": {"ODNO": "BROKER-123"}}
    with patch.object(
        adapter, "_request", new=AsyncMock(return_value=body)
    ) as mock_req:
        order_id = await adapter.place_order("005930", "buy", 10, "market")

    assert order_id == "BROKER-123"
    # 주문은 단일 _request 호출 (페이지 루프 없음).
    assert mock_req.call_count == 1
    assert mock_req.call_args.args[0] == "POST"


async def test_request_with_cont_sets_request_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_request_with_cont: cont_header 가 요청 헤더 tr_cont 로 주입된다."""
    adapter = _make_adapter()
    adapter._circuit_breaker = MagicMock()
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    adapter.access_token = "tok"

    captured: dict[str, Any] = {}

    async def fake_send_http(method, url, headers, params, json_data, timeout):  # type: ignore[no-untyped-def]
        captured["headers"] = headers
        return {"rt_cd": "0"}, "D"

    adapter._send_http = fake_send_http  # type: ignore[method-assign]

    body, tr_cont = await adapter._request_with_cont(
        "GET", "url", "TR", params={}, cont_header="N"
    )

    assert body == {"rt_cd": "0"}
    assert tr_cont == "D"
    assert captured["headers"]["tr_cont"] == "N"


async def test_request_with_cont_empty_header_not_injected() -> None:
    """cont_header="" 이면 요청 헤더에 tr_cont 키를 강제로 넣지 않는다(최초 요청)."""
    adapter = _make_adapter()
    adapter._circuit_breaker = MagicMock()
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    adapter.access_token = "tok"

    captured: dict[str, Any] = {}

    async def fake_send_http(method, url, headers, params, json_data, timeout):  # type: ignore[no-untyped-def]
        captured["headers"] = headers
        return {"rt_cd": "0"}, "F"

    adapter._send_http = fake_send_http  # type: ignore[method-assign]

    await adapter._request_with_cont("GET", "url", "TR", params={}, cont_header="")

    # 최초 요청: tr_cont 헤더는 빈 문자열이거나 부재(어느 쪽도 KIS 최초조회로 동작).
    assert captured["headers"].get("tr_cont", "") == ""
