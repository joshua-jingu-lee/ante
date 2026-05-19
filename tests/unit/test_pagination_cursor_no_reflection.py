"""Cursor decode no-reflection 회귀 테스트 (#1676).

invalid cursor는 raw base64 decode detail(`Incorrect padding` 등)을
노출하지 않고 안정된 ``invalid cursor`` 400 으로 정규화되어야 한다
(by-construction no-reflection — 고정 상수 메시지, str(원예외) 미사용).

OUT-OF-SCOPE (본 매트릭스/구현 범위 아님 — 별 follow-up):
- ``paginate``의 ``if cursor:`` 가드 (cursor=""/None=첫 페이지) 동작
- 빈 ``cursor_field`` 값의 ``next_cursor:""`` emit 정합
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.web.pagination import decode_cursor, encode_cursor

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)

# raw decode 내부 detail / 입력 cursor가 메시지·응답에 절대 노출되면 안 됨.
_FORBIDDEN_SUBSTRINGS = (
    "Incorrect padding",
    "padding",
    "base64",
    "binascii",
    "codec",
)

# 거부되어야 하는 invalid cursor 입력군.
# - not-base64: probe가 관찰한 원 케이스 (Incorrect padding)
# - !!!! / %%% / YWJj!!!! : invalid-alphabet
# - 8J+YgA== : 표준 base64 alias (URL-safe canonical 아님 → canonical 불일치)
# - YWJj== : 잉여 패딩 (non-canonical)
# - urlsafe_b64encode(b"\xff\xfe") : 디코드는 되나 비-UTF8 (UnicodeDecodeError)
_NON_UTF8_CURSOR = base64.urlsafe_b64encode(b"\xff\xfe").decode()
_REJECT_CURSORS = (
    "not-base64",
    "!!!!",
    "YWJj!!!!",
    "%%%",
    "8J+YgA==",
    "YWJj==",
    _NON_UTF8_CURSOR,
)

# 비-empty canonical 라운드트립 수락군 (회귀 고정).
_ACCEPT_VALUES = ("hello", "abc", "😀", "유니코드 문자열")


class TestDecodeCursorNoReflection:
    """`decode_cursor` 유닛: 거부군은 고정 메시지, 수락군은 라운드트립 무손실."""

    def test_empty_cursor_rejected(self) -> None:
        """빈 cursor는 self-consistency를 위해 직접 호출 시 거부."""
        with pytest.raises(ValueError, match="invalid cursor"):
            decode_cursor("")

    @pytest.mark.parametrize("cursor", _REJECT_CURSORS)
    def test_invalid_cursor_rejected_with_stable_message(self, cursor: str) -> None:
        with pytest.raises(ValueError, match="invalid cursor") as exc_info:
            decode_cursor(cursor)
        msg = str(exc_info.value)
        # 메시지는 정확히 고정 상수여야 한다 (raw decode detail/입력 미포함).
        assert msg == "invalid cursor"
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in msg
        # 입력 cursor substring도 메시지에 반사되면 안 된다.
        assert cursor not in msg

    @pytest.mark.parametrize("value", _ACCEPT_VALUES)
    def test_canonical_roundtrip_preserved(self, value: str) -> None:
        """비-empty canonical cursor는 라운드트립 무손실 (정상 회귀)."""
        assert decode_cursor(encode_cursor(value)) == value


def _make_trades_client():
    mock_service = AsyncMock()
    trades = []
    for i in range(3):
        t = MagicMock()
        t.trade_id = f"trd-{i}"
        t.bot_id = "bot-1"
        t.account_id = "acc-test"
        t.symbol = "005930"
        t.side = "buy"
        t.quantity = 10
        t.price = 70000
        t.status.value = "filled"
        t.created_at = "2025-01-01"
        trades.append(t)
    mock_service.get_trades = AsyncMock(return_value=trades)
    return make_authed_client(
        create_app(
            trade_service=mock_service, member_service=make_master_member_service()
        )
    )


def _make_bots_client():
    mock_manager = MagicMock()
    mock_manager.list_bots.return_value = [
        {"bot_id": f"bot-{i}", "status": "running"} for i in range(3)
    ]
    return make_authed_client(
        create_app(
            bot_manager=mock_manager, member_service=make_master_member_service()
        )
    )


def _make_reports_client():
    mock_store = AsyncMock()
    reports = []
    for i in range(3):
        r = MagicMock()
        r.report_id = f"rpt-{i}"
        r.strategy_name = "s"
        r.status.value = "submitted"
        r.submitted_at = "2025-01-01"
        reports.append(r)
    mock_store.list_reports = AsyncMock(return_value=reports)
    return make_authed_client(
        create_app(report_store=mock_store, member_service=make_master_member_service())
    )


def _make_strategies_client():
    """`/api/strategies/{id}/trades` 는 paginate(cursor) 를 쓰는 경로다.

    registry.get 가 truthy 를 반환해 404 를 피하고, trade_service 가
    거래 목록을 반환하도록 stub 한다.
    """
    mock_registry = AsyncMock()
    mock_registry.get = AsyncMock(return_value=MagicMock())
    mock_trade_service = AsyncMock()
    trades = []
    for i in range(3):
        t = MagicMock()
        t.trade_id = f"trd-{i}"
        t.bot_id = "bot-1"
        t.symbol = "005930"
        t.side = "buy"
        t.quantity = 10
        t.price = 70000
        t.status.value = "filled"
        t.timestamp = "2025-01-01"
        trades.append(t)
    mock_trade_service.get_trades = AsyncMock(return_value=trades)
    return make_authed_client(
        create_app(
            strategy_registry=mock_registry,
            trade_service=mock_trade_service,
            member_service=make_master_member_service(),
        )
    )


class TestTradesCursorNoReflection:
    """`GET /api/trades?cursor=<invalid>` → 400 안정 메시지 (수렴점)."""

    @pytest.mark.parametrize("cursor", _REJECT_CURSORS)
    def test_invalid_cursor_returns_clean_400(self, cursor: str) -> None:
        client = _make_trades_client()
        resp = client.get(f"/api/trades?cursor={cursor}&limit=1")
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"] == "invalid cursor"
        # 응답 본문 전체에 raw decode detail/입력 cursor가 반사되면 안 된다.
        body = resp.text
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in body
        assert cursor not in body

    @pytest.mark.parametrize("value", _ACCEPT_VALUES)
    def test_valid_cursor_returns_200(self, value: str) -> None:
        client = _make_trades_client()
        resp = client.get(f"/api/trades?cursor={encode_cursor(value)}&limit=1")
        assert resp.status_code == 200


class TestMultiConsumerCursorNoReflection:
    """수렴점 단일 수정: bots/strategies/reports 라우트도 동일 400."""

    def test_bots_invalid_cursor_returns_clean_400(self) -> None:
        resp = _make_bots_client().get("/api/bots?cursor=not-base64&limit=1")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid cursor"
        assert "padding" not in resp.text

    def test_strategies_invalid_cursor_returns_clean_400(self) -> None:
        resp = _make_strategies_client().get(
            "/api/strategies/strat-1/trades?cursor=not-base64&limit=1"
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid cursor"
        assert "padding" not in resp.text

    def test_reports_invalid_cursor_returns_clean_400(self) -> None:
        resp = _make_reports_client().get("/api/reports?cursor=not-base64&limit=1")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid cursor"
        assert "padding" not in resp.text


class TestPaginateGuardUnchanged:
    """OUT-OF-SCOPE 회귀 가드: paginate의 cursor=""/None 동작 불변.

    paginate는 ``if cursor:`` falsy 가드라 빈 값이 decode_cursor에
    도달하지 않으므로 기존대로 첫 페이지를 반환해야 한다 (paginate 미변경).
    """

    def test_paginate_cursor_none_first_page(self) -> None:
        from ante.web.pagination import paginate

        items = [{"id": str(i)} for i in range(5)]
        result = paginate(items, cursor_field="id", limit=3, cursor=None)
        assert len(result["items"]) == 3
        assert result["next_cursor"] is not None

    def test_paginate_cursor_empty_string_first_page(self) -> None:
        from ante.web.pagination import paginate

        items = [{"id": str(i)} for i in range(5)]
        result = paginate(items, cursor_field="id", limit=3, cursor="")
        assert len(result["items"]) == 3
        assert result["next_cursor"] is not None
