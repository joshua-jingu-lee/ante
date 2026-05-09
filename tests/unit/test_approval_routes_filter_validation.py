"""GET /api/approvals?status=&type= 쿼리 파라미터 검증 테스트 (#1357).

SSOT:
- ``src/ante/approval/models.py::ApprovalStatus`` (StrEnum:
  pending/approved/execution_failed/rejected/on_hold/expired/cancelled).
- ``src/ante/approval/models.py::ApprovalType`` (StrEnum) — 본 PR scope 외.
- ``src/ante/web/routes/approvals.py::list_approvals``.

검증 대상 (본 PR scope):
- 알려진 ``ApprovalStatus`` 값(pending/approved/rejected/execution_failed)은 200.
- 미정의 status 값은 422.
- ``status``+``type`` 둘 다 invalid면 status 우선 422.
- ``type``만 invalid (현재 frontend mismatch로 deferred)면 200 + 빈 결과.
- 둘 다 생략은 200 (전체 목록).
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def approval_service(db):
    from ante.approval.service import ApprovalService
    from ante.eventbus.bus import EventBus

    eventbus = EventBus()
    svc = ApprovalService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


@pytest.fixture
def app(approval_service):
    return create_app(approval_service=approval_service)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
async def seeded_approval(approval_service):
    """pending 상태의 strategy_adopt 결재 1건 시드."""
    return await approval_service.create(
        type="strategy_adopt",
        requester="agent-01",
        title="전략 채택 요청",
        body="테스트 전략",
        reference_id="report-001",
    )


class TestListApprovalsStatusFilter:
    """GET /api/approvals?status= 쿼리 파라미터 검증 (#1357)."""

    def test_status_pending_returns_200(self, client, seeded_approval):
        """valid status='pending'은 200을 반환한다."""
        res = client.get("/api/approvals?status=pending")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total"] == 1
        ids = [a["id"] for a in data["approvals"]]
        assert seeded_approval.id in ids

    def test_status_approved_returns_200(self, client, seeded_approval):
        """valid status='approved'는 200 (시드는 pending이라 결과 0건)."""
        res = client.get("/api/approvals?status=approved")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0

    def test_status_rejected_returns_200(self, client, seeded_approval):
        """valid status='rejected'는 200."""
        res = client.get("/api/approvals?status=rejected")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0

    def test_status_execution_failed_returns_200(self, client, seeded_approval):
        """valid status='execution_failed'는 200."""
        res = client.get("/api/approvals?status=execution_failed")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0

    def test_status_unknown_value_returns_422(self, client, seeded_approval):
        """알 수 없는 status는 422 (200 빈 목록 아님)."""
        res = client.get("/api/approvals?status=oracle_invalid")
        assert res.status_code == 422, res.text

    def test_status_and_type_both_invalid_returns_422(self, client, seeded_approval):
        """status+type 둘 다 invalid면 status enum 검증이 우선 422를 반환한다."""
        res = client.get("/api/approvals?status=oracle_invalid&type=oracle_invalid")
        assert res.status_code == 422, res.text

    def test_type_only_invalid_returns_200(self, client, seeded_approval):
        """type만 invalid는 본 PR scope 외 (frontend ApprovalType mismatch로
        follow-up). 현재는 type=str 그대로라 200 + 빈 결과를 반환한다.
        """
        res = client.get("/api/approvals?type=oracle_invalid")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 0

    def test_filters_omitted_returns_all(self, client, seeded_approval):
        """status/type 미제공은 전체 목록 200."""
        res = client.get("/api/approvals")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 1
