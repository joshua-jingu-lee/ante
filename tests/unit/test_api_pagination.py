"""Web API 페이지네이션 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from ante.web.app import create_app
from ante.web.pagination import decode_cursor, encode_cursor, paginate


class TestPaginationUtil:
    def test_encode_decode_roundtrip(self):
        """cursor 인코딩/디코딩 왕복."""
        original = "report-123"
        cursor = encode_cursor(original)
        assert decode_cursor(cursor) == original

    def test_paginate_first_page(self):
        """첫 페이지 반환."""
        items = [{"id": str(i)} for i in range(5)]
        result = paginate(items, cursor_field="id", limit=3)
        assert len(result["items"]) == 3
        assert result["next_cursor"] is not None

    def test_paginate_last_page(self):
        """마지막 페이지면 next_cursor=None."""
        items = [{"id": str(i)} for i in range(3)]
        result = paginate(items, cursor_field="id", limit=5)
        assert len(result["items"]) == 3
        assert result["next_cursor"] is None

    def test_paginate_with_cursor(self):
        """cursor 이후 항목 반환."""
        items = [{"id": str(i)} for i in range(5)]
        cursor = encode_cursor("1")
        result = paginate(items, cursor_field="id", limit=2, cursor=cursor)
        assert len(result["items"]) == 2
        assert result["items"][0]["id"] == "2"
        assert result["items"][1]["id"] == "3"
        assert result["next_cursor"] is not None

    def test_paginate_cursor_at_end(self):
        """cursor가 마지막 항목이면 빈 결과."""
        items = [{"id": str(i)} for i in range(3)]
        cursor = encode_cursor("2")
        result = paginate(items, cursor_field="id", limit=10, cursor=cursor)
        assert len(result["items"]) == 0
        assert result["next_cursor"] is None

    def test_paginate_empty_list(self):
        """빈 리스트."""
        result = paginate([], cursor_field="id", limit=10)
        assert len(result["items"]) == 0
        assert result["next_cursor"] is None


class TestReportsEndpointPagination:
    def test_reports_returns_next_cursor(self):
        """리포트 목록에 next_cursor 포함."""
        mock_store = AsyncMock()
        reports = []
        for i in range(5):
            r = MagicMock()
            r.report_id = f"rpt-{i}"
            r.strategy_name = "test"
            r.status.value = "submitted"
            r.submitted_at = "2025-01-01"
            reports.append(r)
        mock_store.list_reports = AsyncMock(return_value=reports)

        app = create_app(report_store=mock_store)
        client = TestClient(app)
        resp = client.get("/api/reports?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reports"]) == 3
        assert data["next_cursor"] is not None

    def test_reports_no_cursor_when_all_fit(self):
        """전체 결과가 limit 이내면 next_cursor=null."""
        mock_store = AsyncMock()
        r = MagicMock()
        r.report_id = "rpt-0"
        r.strategy_name = "test"
        r.status.value = "submitted"
        r.submitted_at = "2025-01-01"
        mock_store.list_reports = AsyncMock(return_value=[r])

        app = create_app(report_store=mock_store)
        client = TestClient(app)
        resp = client.get("/api/reports?limit=20")
        data = resp.json()
        assert data["next_cursor"] is None


class TestBotsEndpointPagination:
    def test_bots_pagination(self):
        """봇 목록 페이지네이션."""
        mock_manager = MagicMock()
        bots = [{"bot_id": f"bot-{i}", "status": "running"} for i in range(5)]
        mock_manager.list_bots.return_value = bots

        app = create_app(bot_manager=mock_manager)
        client = TestClient(app)
        resp = client.get("/api/bots?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["bots"]) == 3
        assert data["next_cursor"] is not None

    def test_bots_service_unavailable(self):
        """봇 매니저 없으면 503."""
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/bots")
        assert resp.status_code == 503


class TestTradesEndpointPagination:
    def test_trades_pagination(self):
        """거래 기록 페이지네이션."""
        mock_service = AsyncMock()
        trades = []
        for i in range(5):
            t = MagicMock()
            t.trade_id = f"trd-{i}"
            t.bot_id = "bot-1"
            t.symbol = "005930"
            t.side = "buy"
            t.quantity = 10
            t.price = 70000
            t.status.value = "filled"
            t.created_at = "2025-01-01"
            trades.append(t)
        mock_service.get_trades = AsyncMock(return_value=trades)

        app = create_app(trade_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/trades?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) == 3
        assert data["next_cursor"] is not None


class TestNotificationsEndpointPagination:
    def test_notifications_pagination(self):
        """알림 이력 페이지네이션."""
        mock_service = AsyncMock()
        rows = [
            {
                "id": i,
                "level": "INFO",
                "title": "",
                "message": f"msg-{i}",
                "success": 1,
                "created_at": "2025-01-01",
            }
            for i in range(5)
        ]
        mock_service.get_history = AsyncMock(return_value=rows)

        app = create_app(notification_service=mock_service)
        client = TestClient(app)
        resp = client.get("/api/notifications?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["notifications"]) == 3
        assert data["next_cursor"] is not None
