"""POST /api/members + MemberService.register 의 ``member_type`` enum 강제
회귀 (issue #1628 — #1465 ``role`` 패턴 1:1 미러).

검증 대상:

- Web API: 인증 master caller + body ``member_type`` 이 ``MemberType`` enum
  SSOT (``human`` / ``agent``) 외 값이면 422 로 거부되고 service register 가
  호출되지 않는다.
- Web API: 인증 master caller + 정상 member_type 값 (``human`` / ``agent``)
  은 201 회귀.
- Web API: **미인증** + invalid member_type 조합은 body validation 보다 401
  이 우선되어야 한다 (#1339 auth-first invariant 회귀).
- Service: ``MemberService.register`` 가 enum 외 member_type 을
  ``ValueError`` 로 거부한다 (defense-in-depth, CLI direct path 회귀).
- Service: ``MemberType`` enum 멤버 (``HUMAN`` / ``AGENT``) 와 동등 문자열은
  통과한다.
- Service: ``agent + master`` 조합은 기존대로 ``PermissionError`` 로 거부된다
  (``_assert_type_role`` 호환 회귀 — ``member_type`` enum 가드와 공존).
- OpenAPI sync: ``/openapi.json`` 의 ``components.schemas.MemberCreateRequest``
  ``member_type`` 이 ``enum: [human, agent]`` 를 노출한다 (인라인 schema 불변).

본 모듈은 `tests/unit/test_member_create_invalid_role.py` (#1465) 를 1:1
미러하며, `tests/unit/test_member_api.py` 의 FakeMemberService 패턴을
재사용해 Web API 회귀를 잠그고, ``test_member_service_master_guard.py``
패턴을 재사용해 service 회귀를 잠근다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.core.database import Database  # noqa: E402
from ante.eventbus import EventBus  # noqa: E402
from ante.member.models import MemberRole, MemberType  # noqa: E402
from ante.member.service import MemberService  # noqa: E402

from ante.web.app import create_app  # noqa: E402  # isort: skip


# ── Web API fixtures (test_member_api.py 패턴 재사용) ─────────────────────


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
    token_hash: str = ""
    password_hash: str = ""
    recovery_key_hash: str = ""
    created_at: str = ""
    created_by: str = ""
    last_active_at: str = ""
    suspended_at: str = ""
    revoked_at: str = ""
    token_expires_at: str = ""


class FakeMemberService:
    """테스트용 MemberService stub.

    ``register`` 가 호출되는지 추적해 ingress (Pydantic enum validation) 가
    실제로 service 도달 전에 차단했는지 검증한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._token_counter = 0
        self.register_calls: list[dict[str, object]] = []

    async def list_members(self, **kwargs: object) -> list[FakeMember]:
        return []

    async def count(self, **kwargs: object) -> int:
        return 0

    async def register(
        self,
        member_id: str,
        member_type: str,
        role: str = "default",
        org: str = "default",
        name: str = "",
        scopes: list[str] | None = None,
        registered_by: str = "",
        **kwargs: object,
    ) -> tuple[FakeMember, str]:
        self.register_calls.append(
            {
                "member_id": member_id,
                "member_type": member_type,
                "role": role,
                "registered_by": registered_by,
            }
        )
        if member_id in self._members:
            raise ValueError(f"이미 존재하는 멤버: {member_id}")
        member = FakeMember(
            member_id=member_id,
            type=member_type,
            role=role,
            org=org,
            name=name,
            scopes=scopes or [],
            created_by=registered_by,
        )
        self._members[member_id] = member
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)


@pytest.fixture
def member_service() -> FakeMemberService:
    return FakeMemberService()


@pytest.fixture
def client(member_service: FakeMemberService) -> TestClient:
    """인증 컨텍스트가 미리 주입된 클라이언트 (master-user, role=master).

    ``test_member_api.py::client`` 와 동일한 synthetic master 패턴을 따른다.
    """
    app = create_app(member_service=member_service)

    _master_synthetic = FakeMember(member_id="master-user", role="master")
    _original_get = member_service.get

    async def _get_with_synthetic_master(member_id: str) -> FakeMember | None:
        if member_id == "master-user":
            return _master_synthetic
        return await _original_get(member_id)

    member_service.get = _get_with_synthetic_master  # type: ignore[assignment]

    @app.middleware("http")
    async def inject_master_caller(request, call_next):  # type: ignore[no-untyped-def]
        request.state.member_id = "master-user"
        return await call_next(request)

    return TestClient(app)


@pytest.fixture
def client_unauthenticated(member_service: FakeMemberService) -> TestClient:
    """인증 컨텍스트가 주입되지 않은 클라이언트."""
    app = create_app(member_service=member_service)
    return TestClient(app)


# ── Web API: invalid member_type → 422 ───────────────────────────────────


class TestCreateMemberInvalidTypeWebAPI:
    """POST /api/members 가 알 수 없는 member_type 을 422 로 거부 (#1628)."""

    def test_unknown_member_type_oracle_string_rejected_with_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """``oracle_invalid_member_type`` 같은 임의 문자열은 422 + service 미호출.

        oracle A7 reproduction 시그니처. 과거에는 400 (service ValueError) 로
        새던 경로 (#1628) 를 잠근다 — ingress 422 로 정렬.
        """
        resp = client.post(
            "/api/members",
            json={
                "member_id": "oracle-invalid-type-member",
                "member_type": "oracle_invalid_member_type",
                "role": "default",
            },
        )
        assert resp.status_code == 422, resp.text
        # ingress 가 차단했으므로 service 까지 도달하지 않는다.
        assert member_service.register_calls == [], (
            "ingress validation 이 service 호출을 막아야 한다 — "
            f"현재 register_calls: {member_service.register_calls!r}"
        )

    def test_invalid_member_type_empty_string_rejected_with_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """빈 문자열도 enum 멤버가 아니므로 422."""
        resp = client.post(
            "/api/members",
            json={
                "member_id": "agent-empty-type",
                "member_type": "",
                "role": "default",
            },
        )
        assert resp.status_code == 422, resp.text
        assert member_service.register_calls == []

    def test_invalid_member_type_bot_rejected_with_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """``bot`` 같은 그럴듯한 오타도 API enum 밖이므로 422.

        ``MemberType`` SSOT 는 ``human`` / ``agent`` 만 허용한다. 다른
        클라이언트가 보낼 가능성을 차단한다 (#1628 narrow-scope).
        """
        resp = client.post(
            "/api/members",
            json={
                "member_id": "bot-member",
                "member_type": "bot",
                "role": "default",
            },
        )
        assert resp.status_code == 422, resp.text
        assert member_service.register_calls == []


# ── Web API: valid member_type 회귀 ─────────────────────────────────────


class TestCreateMemberValidTypeWebAPI:
    """정상 member_type 값은 회귀 없이 201 로 통과 (#1628)."""

    @pytest.mark.parametrize(
        ("member_type", "role"),
        [
            ("human", "master"),
            ("human", "admin"),
            ("human", "default"),
            ("agent", "default"),
        ],
    )
    def test_valid_member_type_returns_201(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        member_type: str,
        role: str,
    ) -> None:
        resp = client.post(
            "/api/members",
            json={
                "member_id": f"target-{member_type}-{role}",
                "member_type": member_type,
                "role": role,
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["member"]["type"] == member_type

    def test_valid_member_type_reaches_service_as_str(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """``MemberType`` (StrEnum) 인스턴스가 service 에 str 동등으로 전달.

        라우터가 ``body.member_type`` (MemberType) 을 그대로 넘겨도
        StrEnum=str 이라 기존 service 시그니처와 호환된다 (#1628 StrEnum 회귀).
        """
        resp = client.post(
            "/api/members",
            json={
                "member_id": "agent-strenum-check",
                "member_type": "agent",
            },
        )
        assert resp.status_code == 201, resp.text
        assert len(member_service.register_calls) == 1
        assert member_service.register_calls[0]["member_type"] == "agent"


# ── Web API: auth-first invariant ───────────────────────────────────────


class TestCreateMemberAuthFirstWithInvalidType:
    """미인증 + invalid member_type → 401 우선 (#1339 + #1628)."""

    def test_unauth_with_invalid_member_type_returns_401_not_422(
        self,
        client_unauthenticated: TestClient,
        member_service: FakeMemberService,
    ) -> None:
        """인증 가드는 body validation 보다 항상 먼저 실행되어야 한다.

        invalid member_type 이라도 인증 컨텍스트가 없으면 401 로 응답되고
        service register 는 호출되지 않는다 (#1339 P2 auth-first 회귀).
        """
        resp = client_unauthenticated.post(
            "/api/members",
            json={
                "member_id": "agent-bad",
                "member_type": "oracle_invalid_member_type",
                "role": "default",
            },
        )
        assert resp.status_code == 401, resp.text
        assert member_service.register_calls == []


# ── OpenAPI components schema sync ──────────────────────────────────────


class TestMemberCreateRequestOpenAPISchema:
    """``components.schemas.MemberCreateRequest.member_type`` enum SSOT (#1628).

    인라인 ``MEMBER_CREATE_REQUEST_SCHEMA`` 는 이미 ``enum:[human,agent]`` 를
    선언하고 있었다 — 본 회귀는 그 불변을 잠근다 (모델 enforcement 정렬
    이후에도 OpenAPI 계약이 흔들리지 않음).
    """

    def test_member_type_property_exposes_enum_human_agent(self) -> None:
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "MemberCreateRequest" in schemas, (
            "MemberCreateRequest schema 가 components 에 등록되지 않음 — "
            "#1339 P1 회귀 가능성"
        )
        member_type_prop = schemas["MemberCreateRequest"]["properties"]["member_type"]
        assert member_type_prop.get("enum") == ["human", "agent"], (
            "MemberCreateRequest.member_type.enum 이 MemberType SSOT 와 "
            f"불일치: {member_type_prop!r}"
        )


# ── Service-layer: invalid member_type direct path ──────────────────────


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def service(db, eventbus) -> MemberService:
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


@pytest.fixture
async def populated_service(service: MemberService) -> MemberService:
    """master(``owner``) 만 bootstrap. register 호출자가 ``owner`` 가 된다."""
    await service.bootstrap_master("owner", "pass123")
    return service


class TestServiceRegisterInvalidType:
    """``MemberService.register`` 가 enum 외 member_type 을 ValueError 로
    거부 (#1628).

    CLI direct path (``src/ante/cli/commands/member.py`` ``register``) 와 내부
    caller 는 Pydantic 검증을 거치지 않으므로 service 단 방어가 필요하다
    (defense-in-depth — #1465 ``role`` 패턴 1:1 미러).
    """

    async def test_unknown_member_type_raises_value_error(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(ValueError, match="invalid member_type"):
            await populated_service.register(
                member_id="oracle-invalid-type",
                member_type="oracle_invalid_member_type",
                role="default",
                registered_by="owner",
            )

    async def test_empty_member_type_raises_value_error(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(ValueError, match="invalid member_type"):
            await populated_service.register(
                member_id="agent-empty-type",
                member_type="",
                role="default",
                registered_by="owner",
            )

    async def test_bot_member_type_raises_value_error(
        self, populated_service: MemberService
    ) -> None:
        """``bot`` 같은 그럴듯한 오타도 service 에서 거부."""
        with pytest.raises(ValueError, match="invalid member_type"):
            await populated_service.register(
                member_id="bot-member",
                member_type="bot",
                role="default",
                registered_by="owner",
            )

    async def test_value_error_raised_before_token_creation(
        self, populated_service: MemberService
    ) -> None:
        """invalid member_type 거부 시 DB INSERT/토큰 발급이 발생하지 않는다."""
        with pytest.raises(ValueError, match="invalid member_type"):
            await populated_service.register(
                member_id="agent-no-token",
                member_type="oracle_invalid_member_type",
                role="default",
                registered_by="owner",
            )
        # 새 멤버가 DB 에 추가되지 않았어야 한다.
        assert await populated_service.get("agent-no-token") is None


class TestServiceRegisterValidType:
    """정상 member_type 은 회귀 없이 통과 (#1628)."""

    async def test_register_with_member_type_enum_human(
        self, populated_service: MemberService
    ) -> None:
        """enum 인스턴스 (``MemberType.HUMAN``) 도 통과 (StrEnum=str)."""
        member, _ = await populated_service.register(
            member_id="human-second-master",
            member_type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            registered_by="owner",
        )
        assert member.type == "human"

    async def test_register_with_string_human(
        self, populated_service: MemberService
    ) -> None:
        member, _ = await populated_service.register(
            member_id="human-string",
            member_type="human",
            role="default",
            registered_by="owner",
        )
        assert member.type == "human"

    async def test_register_with_string_agent(
        self, populated_service: MemberService
    ) -> None:
        member, _ = await populated_service.register(
            member_id="agent-string",
            member_type="agent",
            role="default",
            registered_by="owner",
        )
        assert member.type == "agent"

    async def test_register_with_member_type_enum_agent(
        self, populated_service: MemberService
    ) -> None:
        """``MemberType.AGENT`` enum 인스턴스가 token/Member/DB 경로 통과.

        StrEnum=str 이므로 ``create_token``/``Member(type=...)``/DB INSERT 가
        깨지지 않는다 (#1628 StrEnum 회귀).
        """
        member, token = await populated_service.register(
            member_id="agent-enum",
            member_type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
            registered_by="owner",
        )
        assert member.type == "agent"
        assert token.startswith("ante_ak_")
        fetched = await populated_service.get("agent-enum")
        assert fetched is not None
        assert fetched.type == "agent"


class TestServiceRegisterTypeRoleCompatRegression:
    """``_assert_type_role`` 기존 행동이 새 enum 가드와 함께 보존된다 (#1628).

    ``_assert_type_enum`` 추가가 type-role 조합 검증을 가리지 않아야 한다.
    """

    async def test_agent_with_master_role_raises_permission_error(
        self, populated_service: MemberService
    ) -> None:
        """member_type enum 통과 + type/role 위반은 여전히 PermissionError.

        ``_assert_type_enum`` 이 ``agent`` 를 통과시킨 뒤 ``_assert_type_role``
        이 agent+master 조합을 거부한다 (ValueError 가 아님).
        """
        with pytest.raises(PermissionError, match="agent 타입"):
            await populated_service.register(
                member_id="agent-bad-master",
                member_type="agent",
                role="master",
                registered_by="owner",
            )

    async def test_agent_with_admin_role_raises_permission_error(
        self, populated_service: MemberService
    ) -> None:
        with pytest.raises(PermissionError, match="agent 타입"):
            await populated_service.register(
                member_id="agent-bad-admin",
                member_type="agent",
                role="admin",
                registered_by="owner",
            )
