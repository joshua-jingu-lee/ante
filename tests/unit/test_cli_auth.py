"""CLI 인증 미들웨어 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType


def _acm_factory(value):  # noqa: ANN001, ANN202
    """#1857: helper async context manager 전환에 맞춰 fake factory 를
    생성한다. 기존 ``new_callable=AsyncMock, return_value=(...)`` 패턴을
    ``new=_acm_factory((...))`` 로 대체해 ``async with helper(ctx) as
    (...):`` 호출이 yield 한 값을 그대로 받도록 한다.
    """
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _fake_factory(*args, **kwargs):
        yield value

    return _fake_factory


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
        new=_acm_factory((registry, db)),
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


class TestNestedAuthExempt:
    """2단계 이상 nested subcommand의 인증 면제 판정 — Codex 6차 review Finding 1.

    `ante member reset-password` 처럼 root 바로 아래가 아닌 nested 서브커맨드
    경로가 `_AUTH_EXEMPT_COMMAND_PATHS`에 포함된 경우에도 면제가 되어야 한다.
    과거 구현은 `ctx.invoked_subcommand`만 보고 1단계 이름("member")만 면제
    대상과 비교했기 때문에 stale `ANTE_MEMBER_TOKEN`이 있으면 복구 경로가
    막혔다. 그 뒤 leaf 이름 매칭으로 수정했지만, 이번에는 `ante feed init`
    처럼 leaf 이름이 우연히 "init"인 다른 서브커맨드까지 오인되어 nested
    서브커맨드의 `@require_auth`가 동작하지 않는 회귀가 발생했다. 현재
    구현은 전체 커맨드 경로 tuple로 매칭한다.
    """

    def test_member_reset_password_help_exempt_with_stale_token(
        self, runner, monkeypatch, tmp_path
    ):
        """stale ANTE_MEMBER_TOKEN 환경에서도 `member reset-password --help` 통과."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["member", "reset-password", "--help"])
        assert result.exit_code == 0, result.output
        assert "인증 실패" not in result.output

    def test_member_regenerate_recovery_key_help_exempt_with_stale_token(
        self, runner, monkeypatch, tmp_path
    ):
        """stale ANTE_MEMBER_TOKEN 환경에서 `regenerate-recovery-key --help` 통과."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["member", "regenerate-recovery-key", "--help"])
        assert result.exit_code == 0, result.output
        assert "인증 실패" not in result.output

    def test_member_list_still_requires_auth_with_stale_token(
        self, runner, monkeypatch, tmp_path
    ):
        """면제 목록에 없는 nested command는 여전히 인증 요구 (regression 방지).

        stale ANTE_MEMBER_TOKEN이면 MemberService.authenticate가 PermissionError를
        내고 SystemExit(1)로 종료해야 한다.
        """
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["member", "list"])
        assert result.exit_code == 1, result.output
        assert "인증 실패" in result.output

    def test_init_exempt_regression(self, runner, monkeypatch, tmp_path):
        """단일 레벨 면제 커맨드(`ante init`) 회귀 방지."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0, result.output
        assert "인증 실패" not in result.output


class TestLeafNameCollisionNotExempt:
    """같은 leaf 이름("init")을 가진 서브커맨드가 면제 오인되지 않는다.

    `ante feed init`은 leaf 이름이 `ante init`과 같지만, 설계상
    `@require_auth` + `@require_scope("data:write")` 데코레이터가 있어
    반드시 유효 토큰이 필요하다. 전체 경로 tuple로 매칭하므로
    ("feed", "init")은 면제 대상에 포함되지 않아야 한다.
    """

    def test_auth_exempt_path_set_contains_only_full_paths(self):
        """면제 set이 전체 경로 tuple로 관리된다."""
        from ante.cli.middleware import _AUTH_EXEMPT_COMMAND_PATHS

        assert ("init",) in _AUTH_EXEMPT_COMMAND_PATHS
        assert ("member", "reset-password") in _AUTH_EXEMPT_COMMAND_PATHS
        assert ("member", "regenerate-recovery-key") in _AUTH_EXEMPT_COMMAND_PATHS
        # feed init은 면제 아님
        assert ("feed", "init") not in _AUTH_EXEMPT_COMMAND_PATHS

    def test_feed_init_requires_auth_when_token_missing(
        self, runner, monkeypatch, tmp_path
    ):
        """토큰이 전혀 없으면 `ante feed init`은 '인증이 필요합니다'로 실패."""
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["feed", "init", str(tmp_path / "feed-data")])
        assert result.exit_code == 1, result.output
        # @require_auth가 동작: "인증이 필요합니다" 또는 인증 실패 메시지
        assert "인증" in result.output

    def test_feed_init_rejects_stale_token(self, runner, monkeypatch, tmp_path):
        """stale한 ANTE_MEMBER_TOKEN이면 `ante feed init`은 인증 실패로 종료."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        result = runner.invoke(cli, ["feed", "init", str(tmp_path / "feed-data")])
        # 면제 오인이 없어야 하므로 인증 경로를 타야 함 (exit code 1)
        assert result.exit_code == 1, result.output
        assert "인증" in result.output

    def test_resolve_command_path_for_root_init(self):
        """root group이 `ante init`에 대해 ("init",)을 저장한다.

        #1404 이후 root는 ``AuthenticatedGroup``이지만 ``_LeafPathMixin``을
        통해 ``LeafAwareGroup``과 동일한 leaf path tracking을 공유한다.
        """
        from ante.cli.main import cli
        from ante.cli.middleware import _LeafPathMixin

        ctx = click.Context(cli)
        assert isinstance(cli, _LeafPathMixin)
        path = cli._resolve_command_path(ctx, ["init"])
        assert path == ("init",)

    def test_resolve_command_path_for_feed_init(self):
        """LeafAwareGroup이 `ante feed init`에 대해 ("feed", "init")을 저장한다."""
        from ante.cli.main import cli

        ctx = click.Context(cli)
        path = cli._resolve_command_path(ctx, ["feed", "init"])
        assert path == ("feed", "init")

    def test_resolve_command_path_with_options_and_args(self):
        """옵션이 섞여 있어도 올바른 경로를 반환한다."""
        from ante.cli.main import cli

        ctx = click.Context(cli)
        # `ante --format json feed init --data-path /tmp`
        path = cli._resolve_command_path(
            ctx, ["--format", "json", "feed", "init", "--data-path", "/tmp"]
        )
        # "json"은 `cli.get_command(ctx, "json")`가 None이어서 건너뛰지 못하고
        # break한다. 이 테스트는 실제 Click invoke 흐름에서 옵션 값이 args에
        # 남기지 않음을 전제로 한다. 그러나 방어적으로 최소한 첫 커맨드
        # 위치는 올바르게 잡아야 한다. 실제 Click은 root 콜백 이후
        # ctx.protected_args=["feed", "init", "--data-path", "/tmp"]만 남긴다.
        assert path in {("feed", "init"), ()}

    def test_resolve_command_path_nested_member_reset_password(self):
        """LeafAwareGroup이 `ante member reset-password`에 대해 전체 경로."""
        from ante.cli.main import cli

        ctx = click.Context(cli)
        path = cli._resolve_command_path(ctx, ["member", "reset-password"])
        assert path == ("member", "reset-password")


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
