"""결재 API 테스트."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def approval_service(db):
    from ante.approval.models import ApprovalType
    from ante.approval.service import ApprovalService
    from ante.eventbus.bus import EventBus

    eventbus = EventBus()

    # Refs #1418 → #1470 SPLIT-B: executor 미등록 valid type 의 approve 가
    # 더 이상 silent success 가 아니므로, API 회귀 테스트가 의도한
    # ``approved`` 종료 상태를 유지하려면 no-op executor 가 필요하다.
    async def _noop_executor(params: dict) -> None:
        return None

    executors = {t.value: _noop_executor for t in ApprovalType}
    svc = ApprovalService(db=db, eventbus=eventbus, executors=executors)
    await svc.initialize()
    return svc


@pytest.fixture
def app(approval_service):
    return create_app(
        approval_service=approval_service, member_service=make_master_member_service()
    )


@pytest.fixture
def client(app):
    return make_authed_client(app)


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

    async def test_total_is_full_count_not_page_size(self, client, approval_service):
        """total은 페이지 크기가 아닌 전체 건수를 반환해야 한다."""
        for i in range(5):
            await approval_service.create(
                type="strategy_adopt",
                requester="agent-01",
                title=f"전략 채택 요청 {i}",
                body="테스트",
                reference_id=f"report-{i:03d}",
            )
        resp = client.get("/api/approvals?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["approvals"]) == 2
        assert data["total"] == 5

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

    async def test_search_by_title(self, client, sample_approval):
        """search 파라미터로 title 검색."""
        resp = client.get("/api/approvals?search=전략 채택")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_search_by_requester(self, client, sample_approval):
        """search 파라미터로 requester 검색."""
        resp = client.get("/api/approvals?search=agent-01")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_search_no_match(self, client, sample_approval):
        """search 매치 없으면 빈 목록."""
        resp = client.get("/api/approvals?search=존재하지않는키워드")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_search_without_data(self, client):
        """데이터 없을 때 search 파라미터."""
        resp = client.get("/api/approvals?search=anything")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_search_combined_with_status(self, client, sample_approval):
        """search와 status 필터 조합."""
        resp = client.get("/api/approvals?search=전략&status=pending")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        resp = client.get("/api/approvals?search=전략&status=approved")
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
        """잘못된 상태값 → 422 (#1434).

        ``ApprovalStatusUpdate.status`` 가 ``Literal["approved", "rejected"]``
        SSOT 로 강화되어 Pydantic 이 schema 단계에서 invalid 값을 422 로
        사전 차단한다. 기존 handler 400 분기는 제거됐다.
        """
        resp = client.patch(
            f"/api/approvals/{sample_approval.id}/status",
            json={"status": "invalid"},
        )
        assert resp.status_code == 422

    async def test_lifecycle_status_rejected_by_schema(self, client, sample_approval):
        """lifecycle status (``pending`` 등) 는 PATCH 로 변경 불가 → 422 (#1434).

        ``ApprovalStatus`` enum 에는 ``pending`` / ``cancelled`` /
        ``execution_failed`` 등이 존재하지만 PATCH 로는 ``approved`` /
        ``rejected`` 만 허용한다. Pydantic Literal SSOT 가 schema 단계에서
        차단함을 회귀 보호한다.
        """
        for forbidden in ("pending", "cancelled", "expired", "on_hold"):
            resp = client.patch(
                f"/api/approvals/{sample_approval.id}/status",
                json={"status": forbidden},
            )
            assert resp.status_code == 422, (
                f"status={forbidden!r} 가 schema 단계에서 422 로 차단되지 않음 "
                f"(actual: {resp.status_code})"
            )

    def test_nonexistent_approval(self, client):
        """존재하지 않는 결재 → 404."""
        resp = client.patch(
            "/api/approvals/nonexistent/status",
            json={"status": "approved"},
        )
        assert resp.status_code == 404


class TestApprovalStatusUpdateRequestBodySchema:
    """PATCH /api/approvals/{id}/status requestBody OpenAPI schema 노출 (#1429).

    PR #1428 (#1407 머지) 이후 raw-body 패턴으로 전환되며 ``body:
    ApprovalStatusUpdate`` 인자가 시그니처에서 사라져 OpenAPI requestBody +
    ``components.schemas.ApprovalStatusUpdate`` 가 누락됐다.
    ``frontend/src/api/approvals.ts`` 는 여전히 ``ApprovalStatusUpdate as
    ApiApprovalStatusUpdate`` 를 import 하므로 codegen 재생성 시 frontend
    빌드가 깨진다. ``openapi_extra`` + ``_install_openapi_customizer`` 보강을
    회귀 보호한다.
    """

    def test_openapi_request_body_ref_to_approval_status_update(self, client):
        """``requestBody.required == True`` + schema ``$ref`` 매핑 노출."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        spec = (
            openapi.get("paths", {})
            .get("/api/approvals/{approval_id}/status", {})
            .get("patch", {})
        )
        request_body = spec.get("requestBody")
        assert request_body is not None, (
            "PATCH /api/approvals/{approval_id}/status requestBody 가 OpenAPI "
            "에 노출되지 않음"
        )
        assert request_body.get("required") is True, (
            f"requestBody.required 가 True 가 아님: {request_body!r}"
        )
        ref = (
            request_body.get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref")
        )
        assert ref == "#/components/schemas/ApprovalStatusUpdate", (
            f"requestBody schema $ref 가 ApprovalStatusUpdate 가 아님: {ref!r}"
        )

    def test_components_approval_status_update_status_string(self, client):
        """``components.schemas.ApprovalStatusUpdate`` 에 ``status: string`` +
        ``required: [status]`` 노출."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        schemas = openapi.get("components", {}).get("schemas", {})
        component = schemas.get("ApprovalStatusUpdate")
        assert component is not None, (
            "components.schemas.ApprovalStatusUpdate 가 OpenAPI 에 노출되지 "
            "않음 (frontend codegen 이 ApprovalStatusUpdate 를 발견할 수 없음)"
        )
        properties = component.get("properties", {})
        assert properties.get("status", {}).get("type") == "string", (
            f"properties.status.type 이 string 이 아님: {properties.get('status')!r}"
        )
        assert "status" in component.get("required", []), (
            f"required 에 'status' 없음: {component.get('required')!r}"
        )

    def test_components_approval_status_update_status_enum(self, client):
        """``components.schemas.ApprovalStatusUpdate.properties.status.enum``
        에 ``["approved", "rejected"]`` 노출 (#1434).

        ``Literal["approved", "rejected"]`` SSOT 가 OpenAPI enum 으로 노출되어
        frontend / SDK 가 타입 단계에서 invalid 값을 차단한다.
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        schemas = openapi.get("components", {}).get("schemas", {})
        component = schemas.get("ApprovalStatusUpdate", {})
        status_schema = component.get("properties", {}).get("status", {})
        enum_values = status_schema.get("enum")
        assert enum_values == ["approved", "rejected"], (
            "ApprovalStatusUpdate.status.enum 이 "
            f"['approved', 'rejected'] 가 아님: {enum_values!r}"
        )
