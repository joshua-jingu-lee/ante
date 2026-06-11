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

from ante.broker.kis import (
    DEFAULT_EXCG_ID_DVSN_CD,
    DEFAULT_MAX_PAGINATION_PAGES,
    KISDomesticAdapter,
)

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

    result = await adapter._request("POST", "url", "TTTC0012U", json_data={"x": "1"})

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


# ── inquire-daily-ccld tr_id 4코드 분기 + EXCG_ID_DVSN_CD (#2349) ──
#
# get_order_history 가 KST 3개월 경계(start-date 단독 기준)로 inner/before 를
# 판정하고, is_paper × inner/before 4코드로 tr_id 를 선택하는지, 그리고
# EXCG_ID_DVSN_CD hygiene 파라미터를 주입하는지 검증한다. 서버측 효과
# (레거시 0행 vs 신 4행)는 #2317 라이브로 닫혀 있으므로 mock 하지 않고,
# 클라이언트 측 tr_id/param 선택 로직만 단언한다.

# 레거시 tr_id — 회귀 lock 대상(더 이상 전송되지 않음).
_LEGACY_CCLD_TR_IDS = frozenset({"VTTC8001R", "TTTC8001R", "VTSC9115R", "CTSC9115R"})


def _make_ccld_adapter(*, is_paper: bool) -> KISDomesticAdapter:
    """inquire-daily-ccld tr_id/param 선택만 검증하기 위한 어댑터."""
    config = dict(_CONFIG)
    config["is_paper"] = is_paper
    return KISDomesticAdapter(config=config)


def _capture_ccld_call(
    adapter: KISDomesticAdapter,
) -> dict[str, Any]:
    """get_order_history 가 _request_paginated 에 넘긴 tr_id/params 를 캡처한다."""
    captured: dict[str, Any] = {}

    async def fake_paginated(method, url, tr_id, params, row_key="output1"):  # type: ignore[no-untyped-def]
        captured["tr_id"] = tr_id
        captured["params"] = dict(params)
        return []

    adapter._request_paginated = fake_paginated  # type: ignore[method-assign]
    return captured


@pytest.mark.parametrize("is_paper", [True, False])
@pytest.mark.parametrize(
    ("from_date", "expected_kind"),
    [
        # cutoff 당일(2026-03-11) 포함 → inner.
        ("20260311", "inner"),
        # cutoff 익일(이내) → inner.
        ("20260312", "inner"),
        # cutoff 전일(3개월보다 더 과거) → before.
        ("20260310", "before"),
    ],
)
async def test_get_order_history_selects_tr_id_by_kst_three_month_boundary(
    monkeypatch: pytest.MonkeyPatch,
    is_paper: bool,
    from_date: str,
    expected_kind: str,
) -> None:
    """KST cutoff 당일/익일/전일 × 모의/실전 4매핑 tr_id 선택을 clock 고정으로 단언.

    KST today=2026-06-11 → cutoff=2026-03-11(달력 3개월 전 동일 일자).
    INQR_STRT_DT >= cutoff → inner(0081R 계열), < cutoff → before(9215R 계열).
    """
    # clock 고정: KST 영업일 = 2026-06-11.
    monkeypatch.setattr("ante.broker.kis.business_date_kst", lambda *a, **k: "20260611")

    expected = {
        ("inner", True): "VTTC0081R",
        ("inner", False): "TTTC0081R",
        ("before", True): "VTSC9215R",
        ("before", False): "CTSC9215R",
    }[(expected_kind, is_paper)]

    adapter = _make_ccld_adapter(is_paper=is_paper)
    captured = _capture_ccld_call(adapter)

    await adapter.get_order_history(from_date=from_date, to_date="20260611")

    assert captured["tr_id"] == expected
    # 레거시 tr_id 회귀 lock.
    assert captured["tr_id"] not in _LEGACY_CCLD_TR_IDS
    # EXCG_ID_DVSN_CD hygiene 파라미터 주입(상수 재사용).
    assert captured["params"]["EXCG_ID_DVSN_CD"] == DEFAULT_EXCG_ID_DVSN_CD == "KRX"


@pytest.mark.parametrize("is_paper", [True, False])
async def test_get_order_history_default_from_date_is_inner(
    monkeypatch: pytest.MonkeyPatch, is_paper: bool
) -> None:
    """기본 from_date(now-7d, UTC 현행 유지)는 항상 inner(0081R 계열) 회귀.

    호출자가 from_date 를 명시하지 않으면 종전과 동일하게 inner 경로로 동작해야
    한다(tr_id 만 0081R 계열로 교체). UTC 기본 날짜 산출은 무변경이다.
    """
    monkeypatch.setattr("ante.broker.kis.business_date_kst", lambda *a, **k: "20260611")
    expected = "VTTC0081R" if is_paper else "TTTC0081R"

    adapter = _make_ccld_adapter(is_paper=is_paper)
    captured = _capture_ccld_call(adapter)

    await adapter.get_order_history()

    assert captured["tr_id"] == expected
    assert captured["params"]["EXCG_ID_DVSN_CD"] == "KRX"


async def test_get_order_history_crossing_window_uses_single_before_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """교차 구간(from<cutoff<=to)은 split 없이 before 단일 쿼리(start-date 기준).

    bounded known-limitation: cutoff 를 가로지르는 창은 start-date 기준으로
    before 단일 코드를 선택하며, split query 를 발행하지 않는다(_request_paginated
    1회 호출).
    """
    monkeypatch.setattr("ante.broker.kis.business_date_kst", lambda *a, **k: "20260611")
    adapter = _make_ccld_adapter(is_paper=True)
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_paginated(method, url, tr_id, params, row_key="output1"):  # type: ignore[no-untyped-def]
        calls.append((tr_id, dict(params)))
        return []

    adapter._request_paginated = fake_paginated  # type: ignore[method-assign]

    # from(03-01) < cutoff(03-11) <= to(06-11) — 교차 구간.
    await adapter.get_order_history(from_date="20260301", to_date="20260611")

    # split 없이 단일 before 쿼리.
    assert len(calls) == 1
    assert calls[0][0] == "VTSC9215R"
    assert calls[0][1]["INQR_STRT_DT"] == "20260301"
    assert calls[0][1]["INQR_END_DT"] == "20260611"


async def test_get_order_history_month_end_boundary_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """말일 보정: 대상 월에 동일 일자가 없으면 그 월 말일을 cutoff 로 쓴다.

    KST today=2026-05-31 → 3개월 전 동일 일자(02-31)는 부재 → 02-28(2026 비윤년)
    말일로 보정. INQR_STRT_DT=20260228 은 cutoff 당일이라 inner.
    """
    monkeypatch.setattr("ante.broker.kis.business_date_kst", lambda *a, **k: "20260531")
    adapter = _make_ccld_adapter(is_paper=True)
    captured = _capture_ccld_call(adapter)

    # cutoff = 2026-02-28(말일 보정). 당일은 inner.
    await adapter.get_order_history(from_date="20260228", to_date="20260531")
    assert captured["tr_id"] == "VTTC0081R"

    # cutoff 전일(02-27)은 before.
    await adapter.get_order_history(from_date="20260227", to_date="20260531")
    assert captured["tr_id"] == "VTSC9215R"
