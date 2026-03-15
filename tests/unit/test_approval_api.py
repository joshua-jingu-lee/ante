"""결재 API 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ante.web.app import create_app


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
async def sample_approval(approval_service):
    """테스트용 결재 요청 생성."""
    return await approval_service.create(
        type="strategy_adopt",
        requester="agent-01",
        title="전략 채택 요청",
        body="테스트 전략",
        reference_id="report-001",
    )


class TestListApprovals:
    def test_empty_list(self, client):
        """결재 없을 때 빈 목록."""
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approvals"] == []
        assert data["total"] == 0

    async def test_list_with_data(self, client, sample_approval):
        """결재 데이터가 있으면 목록 반환."""
        resp = client.get("/api/approvals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["approvals"][0]["id"] == sample_approval.id
        assert data["approvals"][0]["type"] == "strategy_adopt"

    async def test_filter_by_status(self, client, sample_approval):
        """상태 필터."""
        resp = client.get("/api/approvals?status=pending")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/api/approvals?status=approved")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_filter_by_type(self, client, sample_approval):
        """유형 필터."""
        resp = client.get("/api/approvals?type=strategy_adopt")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/api/approvals?type=budget_change")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetApproval:
    async def test_get_existing(self, client, sample_approval):
        """존재하는 결재 상세 조회."""
        resp = client.get(f"/api/approvals/{sample_approval.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval"]["id"] == sample_approval.id
        assert data["approval"]["title"] == "전략 채택 요청"

    def test_get_nonexistent(self, client):
        """존재하지 않는 결재 → 404."""
        resp = client.get("/api/approvals/nonexistent-id")
        assert resp.status_code == 404


class TestUpdateApprovalStatus:
    async def test_approve(self, client, sample_approval):
        """승인 처리."""
        resp = client.patch(
            f"/api/approvals/{sample_approval.id}/status",
            json={"status": "approved"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval"]["status"] == "approved"

    async def test_reject_with_memo(self, client, sample_approval):
        """거부 처리 + 사유."""
        resp = client.patch(
            f"/api/approvals/{sample_approval.id}/status",
            json={"status": "rejected", "memo": "리스크 과다"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval"]["status"] == "rejected"
        assert data["approval"]["reject_reason"] == "리스크 과다"

    async def test_invalid_status(self, client, sample_approval):
        """잘못된 상태값 → 400."""
        resp = client.patch(
            f"/api/approvals/{sample_approval.id}/status",
            json={"status": "invalid"},
        )
        assert resp.status_code == 400

    def test_nonexistent_approval(self, client):
        """존재하지 않는 결재 → 404."""
        resp = client.patch(
            "/api/approvals/nonexistent/status",
            json={"status": "approved"},
        )
        assert resp.status_code == 404
