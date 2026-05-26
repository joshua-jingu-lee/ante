"""CLI member admin command master-only 표면 가드 회귀 테스트 (#1543).

#1542 spec 결정에 따라 6 CLI commands (register / set-emoji / suspend /
reactivate / revoke / rotate-token) 는 ``@require_master`` 데코레이터로
표면에서 master-only 검증한다. ``member:admin`` scope 보유 agent 는 이전에는
``@require_scope("member:admin")`` 로 통과했지만 본 패치 이후엔 표면에서
``permission_denied`` 로 거부된다.

회귀 매트릭스 (서브셋 — 핵심 commands 만):
- master HUMAN → service 호출
- ``member:admin`` scope agent → permission_denied + service 미호출
- non-master human (admin role) → permission_denied + service 미호출
- non-master agent without scope → permission_denied + service 미호출
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberStatus, MemberType


def _make_member(
    *,
    member_id: str,
    member_type: MemberType,
    role: MemberRole,
    scopes: list[str] | None = None,
) -> Member:
    return Member(
        member_id=member_id,
        type=member_type,
        role=role,
        org="default",
        name=member_id,
        status=MemberStatus.ACTIVE,
        scopes=scopes or [],
    )


def _master() -> Member:
    return _make_member(
        member_id="master",
        member_type=MemberType.HUMAN,
        role=MemberRole.MASTER,
    )


def _agent_with_admin_scope() -> Member:
    return _make_member(
        member_id="agent-admin",
        member_type=MemberType.AGENT,
        role=MemberRole.DEFAULT,
        scopes=["member:admin"],
    )


def _human_admin() -> Member:
    """non-master human (role=admin) — master 가 아니므로 거부 대상."""
    return _make_member(
        member_id="human-admin",
        member_type=MemberType.HUMAN,
        role=MemberRole.ADMIN,
    )


def _agent_no_scope() -> Member:
    return _make_member(
        member_id="agent-default",
        member_type=MemberType.AGENT,
        role=MemberRole.DEFAULT,
    )


def _invoke_with_member(args: list[str], member: Member):  # noqa: ANN202
    """주어진 member 컨텍스트로 CLI 를 실행한다 (인증 우회)."""
    runner = CliRunner()

    def _mock_auth(ctx) -> None:  # noqa: ANN001
        ctx.obj["member"] = member

    with patch("ante.cli.main.authenticate_member", side_effect=_mock_auth):
        return runner.invoke(
            cli,
            args,
            obj={"member": member},
            env={"ANTE_MEMBER_TOKEN": "any"},
            catch_exceptions=False,
        )


def _patch_service(method_name: str):  # noqa: ANN202
    """member._create_service 를 mock 한 채 service.<method_name> 호출 회수를 추적."""
    service = MagicMock()
    method = AsyncMock(
        return_value=Member(
            member_id="target",
            type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
            org="default",
            name="target",
            status=MemberStatus.ACTIVE,
            scopes=[],
        )
    )
    setattr(service, method_name, method)
    # rotate_token 은 (Member, str) tuple 반환
    if method_name == "rotate_token":
        method.return_value = (
            Member(
                member_id="target",
                type=MemberType.AGENT,
                role=MemberRole.DEFAULT,
                org="default",
                name="target",
                status=MemberStatus.ACTIVE,
                scopes=[],
            ),
            "ante_ak_test",
        )
    # register 는 (Member, str) tuple 반환
    if method_name == "register":
        method.return_value = (
            Member(
                member_id="new-agent",
                type=MemberType.AGENT,
                role=MemberRole.DEFAULT,
                org="default",
                name="new",
                status=MemberStatus.ACTIVE,
                scopes=[],
            ),
            "ante_ak_test",
        )
    # #1856: ``_create_service`` 는 async context manager 로 전환됐다.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_factory(ctx=None):  # noqa: ANN001, ANN202
        yield service

    return (
        patch(
            "ante.cli.commands.member._create_service",
            new=_fake_factory,
        ),
        method,
    )


# (cli_args, service_method_name)
ADMIN_COMMANDS = [
    pytest.param(
        ["member", "register", "--id", "new-agent", "--type", "agent"],
        "register",
        id="register",
    ),
    pytest.param(
        ["member", "set-emoji", "target", "🤖"],
        "update_emoji",
        id="set-emoji",
    ),
    pytest.param(
        ["member", "suspend", "target"],
        "suspend",
        id="suspend",
    ),
    pytest.param(
        ["member", "reactivate", "target"],
        "reactivate",
        id="reactivate",
    ),
    pytest.param(
        ["member", "revoke", "target", "--yes"],
        "revoke",
        id="revoke",
    ),
    pytest.param(
        ["member", "rotate-token", "target"],
        "rotate_token",
        id="rotate-token",
    ),
]


# ── master 성공 회귀 ─────────────────────────────────────────────────────


class TestMasterAllowed:
    @pytest.mark.parametrize("cli_args,method_name", ADMIN_COMMANDS)
    def test_master_invokes_service(
        self, cli_args: list[str], method_name: str
    ) -> None:
        ctx, method = _patch_service(method_name)
        with ctx:
            result = _invoke_with_member(cli_args, _master())
        # set-emoji 도 master 통과 가능 (HUMAN+master).
        assert result.exit_code == 0, (
            f"master 실행이 실패: exit={result.exit_code} output={result.output!r} "
            f"exc={result.exception!r}"
        )
        assert method.await_count >= 1, (
            f"master 통과 시 service.{method_name} 가 호출되어야 한다"
        )


# ── member:admin scope agent → 거부 ─────────────────────────────────────


class TestMemberAdminScopeAgentDenied:
    """``member:admin`` scope 보유 agent 도 master-only 표면 가드에서 거부.

    #1543 핵심 회귀: 이전에는 ``@require_scope("member:admin")`` 가 통과시키고
    service ``_assert_master`` 가 런타임에서 거부했다. 본 패치 이후엔
    ``@require_master`` 가 표면에서 즉시 거부 + service 호출 없음.
    """

    @pytest.mark.parametrize("cli_args,method_name", ADMIN_COMMANDS)
    def test_member_admin_scope_agent_denied(
        self, cli_args: list[str], method_name: str
    ) -> None:
        ctx, method = _patch_service(method_name)
        with ctx:
            result = _invoke_with_member(cli_args, _agent_with_admin_scope())
        assert result.exit_code == 1, (
            f"``member:admin`` agent 실행이 거부되지 않음: exit={result.exit_code} "
            f"output={result.output!r}"
        )
        # 표면 가드가 service 호출 전에 거부해야 한다.
        assert method.await_count == 0, (
            f"``member:admin`` agent 거부 시 service.{method_name} 미호출이어야 한다 "
            f"(awaits={method.await_count})"
        )


class TestNonMasterHumanDenied:
    @pytest.mark.parametrize("cli_args,method_name", ADMIN_COMMANDS)
    def test_human_admin_denied(self, cli_args: list[str], method_name: str) -> None:
        ctx, method = _patch_service(method_name)
        with ctx:
            result = _invoke_with_member(cli_args, _human_admin())
        assert result.exit_code == 1, (
            f"non-master human 실행이 거부되지 않음: exit={result.exit_code} "
            f"output={result.output!r}"
        )
        assert method.await_count == 0


class TestNonMasterAgentDenied:
    @pytest.mark.parametrize("cli_args,method_name", ADMIN_COMMANDS)
    def test_agent_no_scope_denied(self, cli_args: list[str], method_name: str) -> None:
        ctx, method = _patch_service(method_name)
        with ctx:
            result = _invoke_with_member(cli_args, _agent_no_scope())
        assert result.exit_code == 1
        assert method.await_count == 0
