"""GET /api/reports?status= 쿼리 파라미터 검증 테스트 (#1355).

SSOT:
- ``src/ante/report/models.py::ReportStatus`` (StrEnum:
  draft/submitted/reviewed/adopted/rejected/archived).
- ``src/ante/web/routes/reports.py::list_reports``.

검증 대상:
- 알려진 ``ReportStatus`` 값은 200 (valid pass-through 회귀 포함).
- 미정의 status 값, 빈 문자열은 422.
- ``status`` 미제공은 200 (전체 목록).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.report.models import ReportStatus, StrategyReport  # noqa: E402
from ante.web.app import create_app  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def report_store(db):
    from ante.report.store import ReportStore

    store = ReportStore(db)
    await store.initialize()
    return store


@pytest.fixture
def app(report_store):
    return create_app(report_store=report_store)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
async def seeded_reports(report_store):
    """submitted 1건 + adopted 1건을 시드한다."""
    await report_store.submit(
        StrategyReport(
            report_id="rpt-submitted-001",
            strategy_name="alpha",
            strategy_version="1.0",
            strategy_path="strategies/alpha.py",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    await report_store.submit(
        StrategyReport(
            report_id="rpt-adopted-001",
            strategy_name="beta",
            strategy_version="1.0",
            strategy_path="strategies/beta.py",
            status=ReportStatus.ADOPTED,
            submitted_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
    )


class TestListReportsStatusFilter:
    """GET /api/reports?status= 쿼리 파라미터 검증."""

    def test_status_submitted_returns_200(self, client, seeded_reports):
        """valid status='submitted'는 200을 반환한다 (현재는 store가
        str.value를 호출하다 AttributeError → 500 발생, 본 PR이 수정).
        """
        res = client.get("/api/reports?status=submitted")
        assert res.status_code == 200, res.text
        data = res.json()
        ids = [r["report_id"] for r in data["reports"]]
        assert "rpt-submitted-001" in ids
        assert "rpt-adopted-001" not in ids

    def test_status_adopted_returns_200(self, client, seeded_reports):
        """valid status='adopted'는 200을 반환한다."""
        res = client.get("/api/reports?status=adopted")
        assert res.status_code == 200, res.text
        data = res.json()
        ids = [r["report_id"] for r in data["reports"]]
        assert "rpt-adopted-001" in ids
        assert "rpt-submitted-001" not in ids

    def test_status_unknown_value_returns_422(self, client, seeded_reports):
        """알 수 없는 status는 422 (5xx 아님)."""
        res = client.get("/api/reports?status=oracle_invalid_status")
        assert res.status_code == 422, res.text

    def test_status_empty_string_returns_422(self, client, seeded_reports):
        """빈 문자열 status도 enum value가 아니므로 422."""
        res = client.get("/api/reports?status=")
        assert res.status_code == 422, res.text

    def test_status_omitted_returns_all(self, client, seeded_reports):
        """status 미제공은 전체 목록을 반환한다."""
        res = client.get("/api/reports")
        assert res.status_code == 200, res.text
        data = res.json()
        ids = {r["report_id"] for r in data["reports"]}
        assert {"rpt-submitted-001", "rpt-adopted-001"}.issubset(ids)
