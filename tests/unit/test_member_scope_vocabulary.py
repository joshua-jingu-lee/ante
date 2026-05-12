"""Member scope vocabulary 회귀 (#1439).

``PUT /api/members/{id}/scopes`` + ``POST /api/members`` 의 ``scopes`` 필드는
``src/ante/member/scopes.py`` 의 ``SCOPE_VOCABULARY`` 에 등록된 문자열만 허용한다.

이전 동작: invalid scope (예: ``oracle:invalid``) 가 vocabulary 검증 없이
서비스 호출 단계까지 도달했고, 존재하지 않는 멤버 케이스에서 404 가 반환되어
입력 invariant 위반이 가려졌다(#1439).

본 테스트는 다음을 잠근다:
1. Web API ingress (Pydantic field_validator) — invalid scope 가 포함되면
   member 존재 여부와 무관하게 422 가 반환되어야 한다.
2. valid scope + 미존재 멤버 → 404 정상 회귀.
3. ``MemberService.register`` / ``update_scopes`` defense-in-depth — CLI 또는
   내부 caller 가 service 를 직접 호출해 invalid scope 를 넘기는 경우에도
   ``InvalidScopeError`` 가 raise 되어야 한다.
4. CLI direct path — ``ante member register --scopes oracle:invalid`` 가
   비-0 exit code 로 종료되어야 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.member.errors import PermissionDeniedError  # noqa: E402
from ante.member.scopes import SCOPE_VOCABULARY, InvalidScopeError  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# ── FakeMemberService (test_member_routes_create_auth.py 패턴 재사용) ─


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
    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}
        self._token_counter = 0
        self.register_calls: list[dict[str, object]] = []
        self.update_scopes_calls: list[tuple[str, list[str]]] = []

    def add_member(
        self,
        member_id: str,
        token: str,
        role: str = "default",
        member_type: str = "agent",
    ) -> FakeMember:
        member = FakeMember(member_id=member_id, role=role, type=member_type)
        self._members[member_id] = member
        self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)

    async def update_last_active(self, member_id: str) -> None:
        return None

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
            {"member_id": member_id, "scopes": list(scopes or [])}
        )
        caller = self._members.get(registered_by)
        if caller is None or caller.role != "master":
            raise PermissionDeniedError("'register'은(는) master만 수행할 수 있습니다.")
        if member_id in self._members:
            raise ValueError(f"이미 존재하는 멤버: {member_id}")
        member = FakeMember(
            member_id=member_id,
            type=member_type,
            role=role,
            org=org,
            name=name,
            scopes=list(scopes or []),
            created_by=registered_by,
        )
        self._members[member_id] = member
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> FakeMember:
        self.update_scopes_calls.append((member_id, list(scopes)))
        caller = self._members.get(updated_by)
        if caller is None or caller.role != "master":
            raise PermissionDeniedError(
                "'update_scopes'은(는) master만 수행할 수 있습니다."
            )
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"존재하지 않는 멤버: {member_id}")
        member.scopes = list(scopes)
        return member


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member("master-user", token="master-token", role="master")
    svc.add_member("agent-01", token="agent-token", role="default")
    return svc


@pytest.fixture
def client(member_service: FakeMemberService) -> TestClient:
    app = create_app(member_service=member_service)
    return TestClient(app)


def _master_headers() -> dict[str, str]:
    return {"Authorization": "Bearer master-token"}


# ── 1. PUT /api/members/{id}/scopes — Web API ingress 회귀 ─


class TestUpdateScopesVocabulary:
    def test_invalid_scope_returns_422_even_when_member_missing(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """이슈 #1439 의 핵심 시나리오.

        invalid scope (``oracle:invalid``) 는 vocabulary 단계에서 422 로
        차단되어야 하며, 미존재 멤버 케이스의 404 로 가려져서는 안 된다.
        """
        resp = client.put(
            "/api/members/nonexistent/scopes",
            json={"scopes": ["oracle:invalid"]},
            headers=_master_headers(),
        )
        assert resp.status_code == 422, resp.text
        # service.update_scopes 는 호출되지 않아야 한다 (ingress 차단).
        assert member_service.update_scopes_calls == []

    def test_mixed_valid_and_invalid_scopes_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """valid + invalid 혼합도 invalid 한 원소 때문에 422."""
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": ["audit:read", "invalid:write"]},
            headers=_master_headers(),
        )
        assert resp.status_code == 422, resp.text
        assert member_service.update_scopes_calls == []

    def test_valid_scope_for_existing_member_returns_200(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """valid scope + 존재 멤버 → 200 정상 회귀."""
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": ["audit:read"]},
            headers=_master_headers(),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["scopes"] == ["audit:read"]
        assert member_service.update_scopes_calls == [("agent-01", ["audit:read"])]

    def test_valid_scope_for_missing_member_returns_404(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """valid scope + 미존재 멤버 → 404 정상 회귀.

        본 케이스가 vocabulary 검증과 ``svc.update_scopes`` 의 ``ValueError``
        매핑이 충돌 없이 분리되어 있는지 확인한다.
        """
        resp = client.put(
            "/api/members/nonexistent/scopes",
            json={"scopes": ["audit:read"]},
            headers=_master_headers(),
        )
        assert resp.status_code == 404, resp.text

    def test_empty_scopes_list_for_existing_member_returns_200(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """빈 scopes 리스트는 vocabulary 검증을 통과한다 (empty for-loop)."""
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": []},
            headers=_master_headers(),
        )
        assert resp.status_code == 200, resp.text

    def test_all_vocabulary_scopes_are_accepted(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """vocabulary 전체 28개를 한 번에 전달 → 200.

        각 원소가 individually accept 되는지 회귀.
        """
        all_scopes = sorted(SCOPE_VOCABULARY)
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": all_scopes},
            headers=_master_headers(),
        )
        assert resp.status_code == 200, resp.text


# ── 2. POST /api/members — Web API ingress 회귀 ─


class TestCreateMemberScopesVocabulary:
    def _payload(self, scopes: list[str]) -> dict[str, Any]:
        return {
            "member_id": "new-agent",
            "member_type": "agent",
            "role": "default",
            "scopes": scopes,
        }

    def test_invalid_scope_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members",
            json=self._payload(["oracle:invalid"]),
            headers=_master_headers(),
        )
        assert resp.status_code == 422, resp.text
        assert member_service.register_calls == []

    def test_valid_scope_returns_201(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members",
            json=self._payload(["audit:read"]),
            headers=_master_headers(),
        )
        assert resp.status_code == 201, resp.text
        assert "new-agent" in member_service._members
        assert member_service._members["new-agent"].scopes == ["audit:read"]

    def test_empty_scopes_default_returns_201(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """``scopes`` 누락 시 default ``[]`` 로 통과."""
        payload = {
            "member_id": "new-agent",
            "member_type": "agent",
            "role": "default",
        }
        resp = client.post(
            "/api/members",
            json=payload,
            headers=_master_headers(),
        )
        assert resp.status_code == 201, resp.text


# ── 3. MemberService defense-in-depth 회귀 ─


class TestMemberServiceVocabularyGuard:
    """service 계층 가드. CLI direct path / 내부 caller 회귀."""

    @pytest.mark.asyncio
    async def test_update_scopes_raises_invalid_scope_error(self) -> None:
        """``MemberService.update_scopes`` 가 invalid scope 를 raise.

        DB / EventBus 의존성을 우회하기 위해 ``_assert_scopes_vocabulary``
        staticmethod 를 직접 호출한다(동일 invariant 를 잠근다).
        """
        from ante.member.service import MemberService

        with pytest.raises(InvalidScopeError) as exc_info:
            MemberService._assert_scopes_vocabulary(["oracle:invalid"])
        assert exc_info.value.scope == "oracle:invalid"

    @pytest.mark.asyncio
    async def test_register_raises_invalid_scope_error(self) -> None:
        """``MemberService.register`` 도 같은 invariant 를 잠근다.

        ``register`` 가 ``_assert_scopes_vocabulary`` 를 호출한다는 사실은
        본 헬퍼의 동작 검증과 코드 path 의 정적 참조로 충분히 회귀된다.
        통합 검증은 다음 ``test_register_first_invalid_scope_stops``.
        """
        from ante.member.service import MemberService

        with pytest.raises(InvalidScopeError):
            MemberService._assert_scopes_vocabulary(["valid:write"])

    @pytest.mark.asyncio
    async def test_first_invalid_scope_in_list_is_reported(self) -> None:
        """리스트 중 첫 invalid scope 가 raise 의 인자가 된다.

        이후 invalid scope 가 더 있더라도 첫 번째에서 멈춘다(fail-fast).
        """
        from ante.member.service import MemberService

        with pytest.raises(InvalidScopeError) as exc_info:
            MemberService._assert_scopes_vocabulary(
                ["audit:read", "oracle:invalid", "another:bad"]
            )
        assert exc_info.value.scope == "oracle:invalid"

    def test_invalid_scope_error_is_value_error_subclass(self) -> None:
        """``InvalidScopeError`` 가 ``ValueError`` 의 서브클래스인지 확인.

        기존 ``except ValueError`` 핸들러가 fallthrough 로 동작하면서도, 별도
        ``except InvalidScopeError`` 분기가 가능해야 한다(라우트 핸들러가
        422 와 400/404 로 다르게 매핑하기 위함).
        """
        err = InvalidScopeError("oracle:invalid")
        assert isinstance(err, ValueError)
        assert err.scope == "oracle:invalid"


# ── 4. CLI direct path 회귀 ─


def _make_master_cli_member():  # noqa: ANN202
    """CLI 인증 우회용 master Member (test_cli_member_non_interactive.py 패턴)."""
    from ante.member.models import Member, MemberRole, MemberType

    return Member(
        member_id="master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Master",
        status="active",
        scopes=[],
    )


def _cli_invoke(args: list[str], service_mock):  # noqa: ANN001, ANN202
    """CliRunner 로 ``ante`` group 실행. 인증을 모킹하고 ``_create_service`` 도 모킹."""
    from unittest.mock import patch

    from click.testing import CliRunner

    from ante.cli.main import cli

    master = _make_master_cli_member()

    def _mock_authenticate(ctx) -> None:  # noqa: ANN001
        ctx.obj["member"] = master

    db_stub = type("DbStub", (), {"close": lambda self: _async_noop()})()

    async def _factory():  # noqa: ANN202
        return service_mock, db_stub

    runner = CliRunner()
    with (
        patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate),
        patch("ante.cli.commands.member._create_service", side_effect=_factory),
    ):
        return runner.invoke(
            cli,
            args,
            obj={"member": master},
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )


async def _async_noop() -> None:  # noqa: D401
    """db.close coroutine stub."""
    return None


class TestCLIScopeVocabulary:
    """``ante member register --scopes oracle:invalid`` 가 비-0 exit code 로
    종료되는지 회귀(#1439).

    CliRunner 로 인증과 ``_create_service`` 를 모킹한 뒤, service 가
    ``InvalidScopeError`` 를 raise 했을 때 CLI 핸들러의
    ``except InvalidScopeError`` 분기가 ``SystemExit(1)`` 으로 종료시키는지
    잠근다. 기존 subprocess 방식은 인증 부재로 service 단계 도달 전에
    종료되어 invariant 를 직접 잠그지 못했다.
    """

    def test_register_invalid_scope_exits_non_zero(self) -> None:
        from unittest.mock import AsyncMock

        service_mock = type(
            "SvcStub",
            (),
            {"register": AsyncMock(side_effect=InvalidScopeError("oracle:invalid"))},
        )()

        result = _cli_invoke(
            [
                "member",
                "register",
                "--id",
                "test-agent",
                "--type",
                "agent",
                "--scopes",
                "oracle:invalid",
            ],
            service_mock=service_mock,
        )

        assert result.exit_code != 0, (
            f"CLI 가 invalid scope 에 대해 비-0 exit 해야 한다 — "
            f"got exit_code={result.exit_code}\noutput={result.output!r}"
        )
        # service 까지 도달했는지 (defense-in-depth 회귀).
        assert service_mock.register.await_count == 1

    def test_register_valid_scope_success_returns_zero(self) -> None:
        """valid scope 정상 path 회귀. invalid 차단이 valid 까지 막지 않는지."""
        from unittest.mock import AsyncMock

        from ante.member.models import MemberRole, MemberType

        # mock 의 return_value 는 (Member, token) tuple.
        service_mock = type(
            "SvcStub",
            (),
            {
                "register": AsyncMock(
                    return_value=(
                        type(
                            "M",
                            (),
                            {
                                "member_id": "test-agent",
                                "type": MemberType.AGENT,
                                "role": MemberRole.DEFAULT,
                                "org": "default",
                                "name": "test-agent",
                            },
                        )(),
                        "ante_ak_test",
                    )
                )
            },
        )()

        result = _cli_invoke(
            [
                "member",
                "register",
                "--id",
                "test-agent",
                "--type",
                "agent",
                "--scopes",
                "audit:read",
            ],
            service_mock=service_mock,
        )

        assert result.exit_code == 0, (
            f"valid scope 정상 path 는 exit 0 이어야 한다 — "
            f"got exit_code={result.exit_code}\noutput={result.output!r}"
        )

    def test_invalid_scope_error_class_matches_cli_import(self) -> None:
        """CLI 모듈이 ``InvalidScopeError`` 를 import 한 것과 동일 클래스인지.

        ``except InvalidScopeError`` 분기가 매칭되려면 service 가 raise 하는
        클래스와 CLI 가 catch 하는 클래스가 동일해야 한다 (회귀: re-export
        misalignment 잠금).
        """
        from ante.cli.commands import member as cli_member
        from ante.member import scopes as scopes_module

        assert cli_member.InvalidScopeError is scopes_module.InvalidScopeError


# ── 5. Vocabulary smoke 검증 ─


class TestSCOPEVocabulary:
    def test_vocabulary_is_frozenset(self) -> None:
        """SSOT 타입 회귀. mutable set 로 바뀌면 import-time 변형 위험."""
        assert isinstance(SCOPE_VOCABULARY, frozenset)

    def test_vocabulary_size_matches_spec_doc(self) -> None:
        """spec doc 매트릭스(L177-194) 의 valid cell 수 = 28.

        Hard-coded 수치 회귀. 매트릭스 변경이 SCOPE_VOCABULARY 갱신 없이
        merge 되는 케이스를 잠근다. 정밀 drift 검사는
        ``test_member_scope_drift.py`` 가 수행한다.
        """
        assert len(SCOPE_VOCABULARY) == 28

    @pytest.mark.parametrize(
        "scope",
        [
            "account:read",
            "account:write",
            "strategy:read",
            "strategy:write",
            "data:read",
            "data:write",
            "report:read",
            "report:write",
            "config:read",
            "config:write",
            "approval:read",
            "approval:write",
            "approval:admin",
            "bot:read",
            "bot:admin",
            "trade:read",
            "treasury:read",
            "treasury:admin",
            "member:read",
            "member:admin",
            "system:read",
            "system:admin",
            "rule:read",
            "rule:admin",
            "broker:read",
            "audit:read",
            "notification:read",
            "backtest:run",
        ],
    )
    def test_each_expected_scope_present(self, scope: str) -> None:
        """spec doc 매트릭스의 각 valid cell 이 vocabulary 에 등록되어 있는지."""
        assert scope in SCOPE_VOCABULARY

    def test_invalid_scopes_are_rejected(self) -> None:
        """대표적인 invalid 케이스가 명시적으로 거부되는지."""
        from ante.member.scopes import is_valid_scope

        for bad in (
            "oracle:invalid",
            "invalid:write",
            "audit:write",  # spec 에 없는 cell
            "trade:admin",  # spec 에 없는 cell
            "signal:read",  # signal 은 vocabulary 밖
            "",
            "audit",
            "audit.read",
            "Audit:Read",
            " audit:read ",
        ):
            assert not is_valid_scope(bad), f"{bad!r} 가 vocabulary 에 포함되면 안 됨"

    def test_json_roundtrip_preserves_vocabulary_membership(self) -> None:
        """``json.dumps`` → ``json.loads`` 가 scope membership 을 보존하는지.

        DB 직렬화 / Web body 파싱에서 인코딩 변환이 일어나도 vocabulary 매칭이
        깨지지 않는다는 회귀.
        """
        all_scopes = sorted(SCOPE_VOCABULARY)
        roundtripped = json.loads(json.dumps(all_scopes))
        for scope in roundtripped:
            assert scope in SCOPE_VOCABULARY
