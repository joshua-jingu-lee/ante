"""``GET /api/audit``의 ``from_date``/``to_date`` ISO 8601 검증 테스트 (issue #1414).

oracle A7 시그니처에서 발견된 contract drift: ``from_date``/``to_date``가
임의 문자열(예: ``oracle-not-a-date``)을 200으로 수락하고 있었다. 본 PR은
파라미터 타입을 ``Annotated[datetime | None, Query(...)]``로 좁혀
FastAPI/Pydantic이 ISO 8601 파싱에 실패하면 422로 거부하도록 한다.

핵심 invariants (Implementation Plan):
- 인증 누락 + 잘못된 날짜 → 401 (auth-first 우선순위, dependency 순서 회귀 방지).
- 인증된 master + 잘못된 날짜 → 422 (``AuditLogger.query`` 미호출).
- 인증된 master + 정상 ISO 8601 datetime → 200 (회귀 보존).
- 인증된 master + 정상 date-only (``YYYY-MM-DD``) → 200 (FastAPI/Pydantic
  이 ISO 8601 date 파싱 허용).
- OpenAPI ``parameters[from_date]``/``parameters[to_date]``는
  ``format: date-time`` 스키마로 노출되어야 한다 (contract-drift fix 검증).

SSOT: ``docs/specs/web-api/05-resource-endpoints.md`` (audit 라우트는
"필터: member_id, action, from_date, to_date, limit, offset" — free-form
허용 명시 없음 → ISO 8601 강제는 spec 위반이 아니다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1359 / #1352 패턴) ─────────────────────────


@dataclass
class FakeMember:
    member_id: str
    type: str = "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class FakeMemberService:
    """``test_audit_routes_auth.py`` 패턴을 그대로 재사용한다."""

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add_member(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        member_type: str = "agent",
        scopes: list[str] | None = None,
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            role=role,
            type=member_type,
            scopes=list(scopes) if scopes else [],
        )
        self._members[member_id] = member
        if token:
            self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)


# ── audit_logger fake ───────────────────────────────────────────────────


def _make_audit_logger() -> AsyncMock:
    """query/count call_args를 추적할 수 있는 mock audit logger."""
    mock = AsyncMock()
    mock.query = AsyncMock(
        return_value=[
            {
                "id": 1,
                "member_id": "agent-01",
                "action": "bot.create",
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "127.0.0.1",
                "created_at": "2026-05-09T00:00:00",
            }
        ]
    )
    mock.count = AsyncMock(return_value=1)
    return mock


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member(
        "master-user",
        token="master-token",
        role="master",
        member_type="human",
    )
    return svc


@pytest.fixture
def audit_logger() -> AsyncMock:
    return _make_audit_logger()


@pytest.fixture
def client(
    member_service: FakeMemberService,
    audit_logger: AsyncMock,
) -> TestClient:
    app = create_app(
        member_service=member_service,
        audit_logger=audit_logger,
    )
    return TestClient(app)


_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


# ── 422: 잘못된 날짜 파라미터 (Issue #1414 본문) ──────────────────────


class TestInvalidDate422:
    """파싱 불가능한 ``from_date``/``to_date`` → 422, AuditLogger 미호출."""

    def test_invalid_from_date_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``GET /api/audit?from_date=oracle-not-a-date`` → 422."""
        resp = client.get(
            "/api/audit?from_date=oracle-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"invalid from_date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0, (
            "422 차단 시 audit_logger.query가 호출되어선 안 된다"
        )
        assert audit_logger.count.await_count == 0

    def test_invalid_to_date_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``GET /api/audit?to_date=also-not-a-date`` → 422."""
        resp = client.get(
            "/api/audit?to_date=also-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"invalid to_date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0

    def test_invalid_both_dates_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``from_date``+``to_date`` 모두 invalid → 422."""
        resp = client.get(
            "/api/audit?from_date=oracle-not-a-date&to_date=also-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"양쪽 invalid date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0


# ── 200: 정상 ISO 8601 회귀 보존 ────────────────────────────────────


class TestValidIsoDate200:
    """정상 ISO 8601 입력은 200으로 통과해야 한다 (회귀)."""

    def test_iso_datetime_returns_200(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """ISO 8601 datetime (``2026-05-10T00:00:00Z``) → 200."""
        resp = client.get(
            "/api/audit?from_date=2026-05-10T00:00:00Z",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"정상 ISO datetime이 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        # ``AuditLogger.query`` 시그니처는 str을 유지한다 — 핸들러는
        # ``datetime.isoformat()``으로 변환해 전달해야 한다.
        call_kwargs = audit_logger.query.await_args.kwargs
        assert isinstance(call_kwargs["from_date"], str), (
            f"from_date가 str로 전달되어야 함: {type(call_kwargs['from_date'])}"
        )
        assert "2026-05-10" in call_kwargs["from_date"]

    def test_date_only_returns_200(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """date-only (``2026-05-10``) → 200 (FastAPI/Pydantic은 date를 datetime
        으로 자동 변환). 기존 ``frontend/src/api/`` caller가 date-only를 보내는
        경우 회귀 보존."""
        resp = client.get(
            "/api/audit?from_date=2026-05-10",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"date-only가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1


# ── 401: auth-first invariant (Issue #1414 본문) ────────────────────


class TestAuthFirstWithInvalidDate:
    """인증 누락 + 잘못된 날짜 → 401 우선 (422 보다 dependency 우선순위 보존).

    FastAPI는 핸들러 매개변수 순서대로 dependency를 해결하므로 ``caller_id``
    (require_audit_read)가 ``from_date``/``to_date`` Query parsing 보다 먼저
    실행된다. 인증 정보가 없으면 401이 먼저 반환되어 "auth-first" invariant
    가 유지된다. 본 테스트는 그 회귀를 막는다.
    """

    def test_unauth_with_invalid_date_returns_401(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """unauth + ``from_date=garbage`` → 401, audit_logger 미호출."""
        resp = client.get("/api/audit?from_date=garbage")
        assert resp.status_code == 401, (
            f"unauth + invalid date가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0


# ── OpenAPI 스키마 회귀 (contract-drift fix 검증) ──────────────────


class TestOpenAPIDateFormat:
    """``/openapi.json``의 ``from_date``/``to_date`` 스키마가 ``date-time``
    포맷으로 노출되어야 한다.

    issue #1414 직전에는 두 파라미터가 free-form ``string``이었다. 본 PR
    이후에는 FastAPI가 ``Annotated[datetime | None, Query(...)]``를
    ``{"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]}``
    로 노출해야 한다. ``frontend/openapi.json`` codegen 산출물이
    contract 변경을 인식할 수 있도록 명시적으로 검증한다.
    """

    @staticmethod
    def _audit_query_params() -> dict[str, dict]:
        """``GET /api/audit`` 의 query parameter 스키마를 name → schema 매핑으로."""
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"]["/api/audit"]["get"]
        return {
            param["name"]: param["schema"]
            for param in operation.get("parameters", [])
            if param.get("in") == "query"
        }

    def test_from_date_param_has_date_time_format(self) -> None:
        params = self._audit_query_params()
        assert "from_date" in params, (
            f"GET /api/audit에 from_date param이 없음: {sorted(params.keys())}"
        )
        from_date_schema = params["from_date"]
        # anyOf 분기 또는 직접 format을 검사한다.
        formats = self._collect_formats(from_date_schema)
        assert "date-time" in formats, (
            f"from_date 스키마에 date-time format이 없음 "
            f"(contract-drift fix 미반영): {from_date_schema}"
        )

    def test_to_date_param_has_date_time_format(self) -> None:
        params = self._audit_query_params()
        assert "to_date" in params, (
            f"GET /api/audit에 to_date param이 없음: {sorted(params.keys())}"
        )
        to_date_schema = params["to_date"]
        formats = self._collect_formats(to_date_schema)
        assert "date-time" in formats, (
            f"to_date 스키마에 date-time format이 없음 "
            f"(contract-drift fix 미반영): {to_date_schema}"
        )

    def test_openapi_lists_422_response(self) -> None:
        """``GET /api/audit`` ``responses``에 422 항목이 있어야 한다.

        ``frontend/openapi.json`` codegen 산출물이 422 분기를 인식할 수 있도록
        contract에 명시한다.
        """
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"]["/api/audit"]["get"]
        responses = operation.get("responses", {})
        assert "422" in responses, (
            f"GET /api/audit 응답에 422 항목이 없음: {sorted(responses.keys())}"
        )

    @staticmethod
    def _collect_formats(schema: dict) -> set[str]:
        """``schema`` 트리에서 모든 ``format`` 값을 모아 반환한다.

        FastAPI는 ``datetime | None``을 ``anyOf: [{type, format}, {null}]``로
        펼치므로 anyOf branch까지 탐색해야 한다.
        """
        formats: set[str] = set()
        if "format" in schema:
            formats.add(schema["format"])
        for branch in schema.get("anyOf", []) or []:
            if isinstance(branch, dict) and "format" in branch:
                formats.add(branch["format"])
        return formats
