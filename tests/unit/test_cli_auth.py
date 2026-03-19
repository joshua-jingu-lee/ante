"""CLI 인증 미들웨어 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_MOCK_AGENT = Member(
    member_id="test-agent",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Test Agent",
    status="active",
    scopes=["strategy:read", "data:read"],
)

_MOCK_AGENT_NO_SCOPES = Member(
    member_id="test-agent-empty",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Test Agent Empty",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def auth_runner():
    """인증된 master로 실행하는 runner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


@pytest.fixture
def agent_runner():
    """인증된 agent로 실행하는 runner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_agent(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_AGENT

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_agent
    return r


@pytest.fixture
def agent_no_scopes_runner():
    """scope 없는 agent로 실행하는 runner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_agent(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_AGENT_NO_SCOPES

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_agent
    return r


def _mock_strategy_registry():
    """strategy list가 DB 접속 없이 동작하도록 mock."""
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    registry = MagicMock()
    registry.list_strategies = AsyncMock(return_value=[])
    return patch(
        "ante.cli.commands.strategy._create_registry",
        new_callable=AsyncMock,
        return_value=(registry, db),
    )


class TestAuthRequired:
    """@require_auth 데코레이터 테스트."""

    def test_unauthenticated_command_fails(self, runner):
        """토큰 없이 인증 필수 커맨드 실행 시 실패."""
        with _mock_strategy_registry():
            result = runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code != 0
            assert "인증이 필요합니다" in result.output or "인증이 필요합니다" in (
                result.output + (result.stderr_bytes or b"").decode()
            )

    def test_authenticated_help_works(self, runner):
        """--help는 인증 없이도 동작."""
        result = runner.invoke(cli, ["strategy", "--help"])
        assert result.exit_code == 0

    def test_authenticated_command_succeeds(self, auth_runner):
        """인증된 상태에서 커맨드 정상 실행."""
        with _mock_strategy_registry():
            result = auth_runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0


class TestRequireScope:
    """@require_scope 데코레이터 테스트."""

    def test_human_bypasses_scope_check(self, auth_runner):
        """Human(master) 멤버는 scope 검증 없이 통과."""
        with _mock_strategy_registry():
            result = auth_runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0

    def test_agent_with_matching_scope_passes(self, agent_runner):
        """Agent가 필요 scope를 보유하면 통과."""
        with _mock_strategy_registry():
            result = agent_runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0

    def test_agent_without_scope_fails(self, agent_no_scopes_runner):
        """Agent가 필요 scope가 없으면 실패."""
        with _mock_strategy_registry():
            result = agent_no_scopes_runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code != 0


class TestAuthExemptCommands:
    """인증 면제 커맨드 테스트."""

    def test_help_no_auth(self, runner):
        """--help는 인증 없이 동작."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Ante" in result.output

    def test_version_no_auth(self, runner):
        """--version은 인증 없이 동작."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0


class TestGetMemberId:
    """get_member_id 유틸리티 테스트."""

    def test_returns_member_id_when_authenticated(self, auth_runner, tmp_path):
        """인증 상태에서 멤버 ID 반환 확인 (strategy validate를 통해 간접 확인)."""
        code = """
from ante.strategy.base import Strategy, StrategyMeta, Signal


class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test_auth",
        version="1.0",
        description="Auth test strategy",
    )

    async def on_step(self, context):
        return []
"""
        path = tmp_path / "test_strategy.py"
        path.write_text(code)
        result = auth_runner.invoke(cli, ["strategy", "validate", str(path)])
        assert result.exit_code == 0
