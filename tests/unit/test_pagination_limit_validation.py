"""Pagination limit/offset Query 검증 테스트 (#1356).

목록 API의 `limit`은 양수 범위(1..100)로 제한되어야 한다.
잘못된 쿼리 파라미터(`limit=-1`, `limit=0`, `limit>100`)는
422로 거부되어야 하며, pagination helper 내부 예외가 5xx로
노출되어서는 안 된다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.web.pagination import paginate

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# pagination helper invariant
# ---------------------------------------------------------------------------


class TestPaginateHelperLimitInvariant:
    """`paginate()` helper의 invariant: limit < 1이면 ValueError."""

    def test_paginate_negative_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="limit must be >= 1"):
            paginate([{"id": "1"}], cursor_field="id", limit=-1, cursor=None)

    def test_paginate_zero_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="limit must be >= 1"):
            paginate([{"id": "1"}], cursor_field="id", limit=0, cursor=None)

    def test_paginate_limit_one_ok(self) -> None:
        result = paginate(
            [{"id": "1"}, {"id": "2"}], cursor_field="id", limit=1, cursor=None
        )
        assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# /api/bots
# ---------------------------------------------------------------------------


def _make_bots_app() -> TestClient:
    mock_manager = MagicMock()
    mock_manager.list_bots.return_value = [
        {"bot_id": f"bot-{i}", "status": "running"} for i in range(3)
    ]
    return TestClient(create_app(bot_manager=mock_manager))


class TestBotsLimitValidation:
    def test_negative_limit_returns_422(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=-1")
        assert resp.status_code == 422

    def test_zero_limit_returns_422(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=0")
        assert resp.status_code == 422

    def test_limit_one_returns_200(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=1")
        assert resp.status_code == 200

    def test_limit_default_returns_200(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=20")
        assert resp.status_code == 200

    def test_limit_above_max_returns_422(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=999")
        assert resp.status_code == 422

    def test_limit_at_max_returns_200(self) -> None:
        resp = _make_bots_app().get("/api/bots?limit=100")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /api/reports
# ---------------------------------------------------------------------------


def _make_reports_app() -> TestClient:
    mock_store = AsyncMock()
    r = MagicMock()
    r.report_id = "rpt-0"
    r.strategy_name = "s"
    r.status.value = "submitted"
    r.submitted_at = "2025-01-01"
    mock_store.list_reports = AsyncMock(return_value=[r])
    return TestClient(create_app(report_store=mock_store))


class TestReportsLimitValidation:
    def test_negative_limit_returns_422(self) -> None:
        resp = _make_reports_app().get("/api/reports?limit=-1")
        assert resp.status_code == 422

    def test_above_max_returns_422(self) -> None:
        resp = _make_reports_app().get("/api/reports?limit=999")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/trades
# ---------------------------------------------------------------------------


def _make_trades_app() -> TestClient:
    mock_service = AsyncMock()
    t = MagicMock()
    t.trade_id = "trd-0"
    t.bot_id = "bot-1"
    t.account_id = "acc-test"
    t.symbol = "005930"
    t.side = "buy"
    t.quantity = 10
    t.price = 70000
    t.status.value = "filled"
    t.timestamp = "2025-01-01"
    mock_service.get_trades = AsyncMock(return_value=[t])
    return TestClient(create_app(trade_service=mock_service))


class TestTradesLimitValidation:
    def test_negative_limit_returns_422(self) -> None:
        resp = _make_trades_app().get("/api/trades?limit=-1")
        assert resp.status_code == 422

    def test_above_max_returns_422(self) -> None:
        resp = _make_trades_app().get("/api/trades?limit=999")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/data/datasets
# ---------------------------------------------------------------------------


def _make_data_app() -> TestClient:
    # data_store 미주입 → 빈 결과 반환 (data.py: store is None branch)
    return TestClient(create_app())


class TestDataLimitValidation:
    """`/api/data/datasets`는 dashboard caller (BacktestData.tsx)가
    `limit=10000`으로 호출하므로 ceiling을 10000으로 둔다.

    다른 list endpoints는 `le=100` 유지.
    """

    def test_negative_limit_returns_422(self) -> None:
        resp = _make_data_app().get("/api/data/datasets?limit=-1")
        assert resp.status_code == 422

    def test_limit_999_returns_200(self) -> None:
        """`le=10000` 적용 후 999는 통과 (기존 le=100 시에는 422였음)."""
        resp = _make_data_app().get("/api/data/datasets?limit=999")
        assert resp.status_code == 200

    def test_limit_at_max_returns_200(self) -> None:
        """ceiling 값(10000)은 inclusive로 허용."""
        resp = _make_data_app().get("/api/data/datasets?limit=10000")
        assert resp.status_code == 200

    def test_above_max_returns_422(self) -> None:
        """ceiling 초과(10001)는 422."""
        resp = _make_data_app().get("/api/data/datasets?limit=10001")
        assert resp.status_code == 422

    def test_negative_offset_returns_422(self) -> None:
        resp = _make_data_app().get("/api/data/datasets?offset=-1")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/treasury/transactions
# ---------------------------------------------------------------------------


def _make_treasury_app() -> TestClient:
    mock_treasury = MagicMock()
    mock_treasury._db = None  # service unavailable → 빈 결과
    return TestClient(create_app(treasury=mock_treasury))


class TestTreasuryTxLimitValidation:
    def test_negative_limit_returns_422(self) -> None:
        resp = _make_treasury_app().get("/api/treasury/transactions?limit=-1")
        assert resp.status_code == 422

    def test_above_max_returns_422(self) -> None:
        resp = _make_treasury_app().get("/api/treasury/transactions?limit=999")
        assert resp.status_code == 422

    def test_negative_offset_returns_422(self) -> None:
        resp = _make_treasury_app().get("/api/treasury/transactions?offset=-1")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /api/audit
# ---------------------------------------------------------------------------


def _make_audit_app() -> TestClient:
    mock_logger = AsyncMock()
    mock_logger.query = AsyncMock(return_value=[])
    mock_logger.count = AsyncMock(return_value=0)
    return TestClient(create_app(audit_logger=mock_logger))


class TestAuditLimitValidation:
    def test_negative_limit_returns_422(self) -> None:
        resp = _make_audit_app().get("/api/audit?limit=-1")
        assert resp.status_code == 422

    def test_limit_at_max_returns_200(self) -> None:
        resp = _make_audit_app().get("/api/audit?limit=100")
        assert resp.status_code == 200

    def test_limit_200_returns_422(self) -> None:
        """Contract tightening: 기존 `min(limit, 200)` 제거. 100 초과는 422.

        기존 audit 라우트는 `limit = min(limit, 200)`로 자동 클램프했으나,
        다른 list endpoint와의 일관성 (`le=100`)을 위해 클램프 제거.
        101..200 범위 요청이 새로 422로 거부된다 (breaking change).
        """
        resp = _make_audit_app().get("/api/audit?limit=200")
        assert resp.status_code == 422

    def test_negative_offset_returns_422(self) -> None:
        resp = _make_audit_app().get("/api/audit?offset=-1")
        assert resp.status_code == 422
