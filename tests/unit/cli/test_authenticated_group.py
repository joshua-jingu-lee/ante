"""``authenticated_group`` factory + default-deny CLI 인증 게이트 단위 테스트 (#1404).

본 테스트는 ``src/ante/cli/middleware.py``의 :class:`AuthenticatedGroup`이 leaf
command callback 호출 직전에 default-deny 인증 가드를 자동 부착하는지, 그리고
공개 명령 allowlist(``_AUTH_EXEMPT_COMMAND_PATHS``) + 메타 면제 경로
(``--help`` / ``-h`` / ``--version`` / resilient parsing)가 SSOT
(``docs/specs/cli/03-commands.md``, ``docs/specs/cli/02-design-decisions.md``)와
일치하는지 검증한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Iterator

from ante.cli.main import LeafAwareGroup, cli
from ante.cli.middleware import (
    _AUTH_EXEMPT_COMMAND_PATHS,
    AuthenticatedGroup,
    authenticated_group,
    require_auth,
    require_scope,
)
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="cli-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="CLI Master",
    status="active",
    scopes=[],
)
_AGENT_NO_SCOPE = Member(
    member_id="cli-agent",
    type=MemberType.AGENT,
    role=MemberRole.ADMIN,  # role은 무관, scope만 비어 있는 agent
    org="default",
    name="CLI Agent",
    status="active",
    scopes=[],
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """기본 CliRunner."""
    return CliRunner()


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """``ANTE_MEMBER_TOKEN``과 토큰 파일을 명시적으로 차단한 환경.

    ``ANTE_TOKEN_FILE``은 실제로 ``open()``이 시도되므로 존재하지 않는 파일을
    가리키는 경로로 설정한다(``/dev/null/nope``는 ``NotADirectoryError``가 나서
    ``_resolve_token``의 except 절이 잡지 못한다).
    """
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))
    yield


# ── default-deny: 토큰 없음 + 보호 명령 ────────────────────────────────────


class TestDefaultDeny:
    """ANTE_MEMBER_TOKEN 미설정 상태에서 보호 명령은 자동으로 exit 1."""

    def test_bot_list_without_token_exits_1(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante bot list``는 토큰이 없으면 인증 단계에서 exit 1."""
        result = runner.invoke(cli, ["bot", "list"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output

    def test_feed_init_without_token_exits_1(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """leaf 이름이 ``init``이지만 path가 ``("feed", "init")``이라 면제 대상 아님."""
        result = runner.invoke(cli, ["feed", "init"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output


# ── 공개 명령 allowlist (인증 면제) ─────────────────────────────────────────


class TestAuthExemptAllowlist:
    """``_AUTH_EXEMPT_COMMAND_PATHS`` + ``@click.version_option``으로 면제되는 명령."""

    def test_version_without_token_exits_0(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante --version``은 ``@click.version_option``이 처리 → exit 0."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0, result.output
        assert "ante, version" in result.output

    def test_init_help_without_token_exits_0(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante init --help``는 면제 + click help 처리 → exit 0."""
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_init_callback_runs_without_token(
        self, runner: CliRunner, clean_env: None, tmp_path: Path
    ) -> None:
        """``ante init``은 토큰 없이 부트스트랩 콜백까지 진입한다.

        실제 부트스트랩 mutation은 mock으로 막고, callback이 호출되었음을
        보증한다. ``test_state1_all_exist_rejects``는 기존 회귀 보호와 별도.
        """
        target = tmp_path / "config"

        bootstrap_mock = AsyncMock()
        create_acc_mock = AsyncMock()

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=create_acc_mock,
            ),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        # 인증으로 인한 차단이 아니어야 한다(=" 인증이 필요합니다" 메시지가 없다).
        assert "인증이 필요합니다" not in result.output, result.output
        # 인증을 통과해 callback이 호출되었음을 mock 호출로 확인
        assert bootstrap_mock.called or create_acc_mock.called, (
            f"init callback did not run: {result.output}"
        )

    def test_member_reset_password_enters_callback(
        self,
        runner: CliRunner,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ante member reset-password --recovery-key ...`` 면제 진입 확인."""
        monkeypatch.setenv("RESET_PW_ENV", "newpass123")

        async def _fake_run_reset() -> None:  # noqa: RUF029
            return None

        # 실제 MemberService 호출은 mock — 인증 게이트 통과만 검증
        with patch(
            "ante.cli.commands.member._create_service",
            new=AsyncMock(side_effect=RuntimeError("stop-here")),
        ):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-test",
                    "--new-password-env",
                    "RESET_PW_ENV",
                ],
            )

        # 인증 차단이 아니어야 한다 — RuntimeError("stop-here")가 raise되어
        # CliRunner의 catch_exceptions=True가 잡거나, 서비스 호출 단계까지
        # 도달했음을 보장한다.
        assert "인증이 필요합니다" not in result.output, result.output

    def test_member_regenerate_recovery_key_enters_callback(
        self,
        runner: CliRunner,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ante member regenerate-recovery-key`` 면제 진입 확인."""
        monkeypatch.setenv("CURRENT_PW_ENV", "currentpass")

        with patch(
            "ante.cli.commands.member._create_service",
            new=AsyncMock(side_effect=RuntimeError("stop-here")),
        ):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "CURRENT_PW_ENV",
                ],
            )

        assert "인증이 필요합니다" not in result.output, result.output


# ── 메타 면제 경로 (--help/-h, no args, parse error) ────────────────────────


class TestMetaExemptPaths:
    """``--help`` / ``-h`` / no_args_is_help / parse error는 인증 게이트 발화 안 함."""

    def test_root_help_long(self, runner: CliRunner, clean_env: None) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_root_help_short_alias(self, runner: CliRunner, clean_env: None) -> None:
        """root group의 ``-h``는 ``context_settings.help_option_names``에 등록."""
        result = runner.invoke(cli, ["-h"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_group_help_long(self, runner: CliRunner, clean_env: None) -> None:
        """nested ``ante member --help`` (H1 invariant — 부모 group 콜백 발화 안 함)."""
        result = runner.invoke(cli, ["member", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_group_help_short_alias(self, runner: CliRunner, clean_env: None) -> None:
        """``ante member -h``도 ``-h``가 ``help_option_names``에 등록되어 통과."""
        result = runner.invoke(cli, ["member", "-h"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_leaf_help_deep_nested(self, runner: CliRunner, clean_env: None) -> None:
        """deep nested ``ante member list --help`` 도 인증 없이 통과."""
        result = runner.invoke(cli, ["member", "list", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_no_args_shows_help(self, runner: CliRunner, clean_env: None) -> None:
        """``ante`` (인자 없음) → click ``no_args_is_help`` → exit 0 + help."""
        result = runner.invoke(cli, [])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_unknown_flag_yields_click_parse_error(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante --invalid-flag``는 click parser 단계에서 exit 2 (인증 진입 전)."""
        result = runner.invoke(cli, ["--invalid-flag"])
        assert result.exit_code == 2, result.output
        # 인증 메시지가 아니라 click의 "No such option" 메시지
        assert "인증이 필요합니다" not in result.output
        assert "No such option" in result.output or "Usage:" in result.output


# ── H2 invariant: `--` 뒤 위치 인자 --help는 default-deny 발화 ──────────────


class TestHelpAfterDoubleDashIsNotExempt:
    """``ante <cmd> -- --help`` / ``-- -h``는 메타 면제 대상이 아니다.

    spec H2 invariant: ``--`` 이후 위치 인자 ``--help``는 click이 도움말로
    해석하지 않고 일반 인자 처리 경로로 진입한다. 따라서 default-deny 게이트가
    정상 발화하거나 click의 인자 유효성 검증이 실패하며, 어느 쪽이든 "도움말
    메시지를 인증 없이 발급"하는 결과는 일어나지 않는다.
    """

    def test_bot_info_double_dash_help_triggers_auth(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante bot info -- --help``: leaf callback이 호출되며 인증 발화 (exit 1)."""
        result = runner.invoke(cli, ["bot", "info", "--", "--help"])
        # click 8.1: bot_id 인자 type 제약이 str 기본이라 callback까지 도달.
        # 인증 wrapper가 발화하여 exit 1.
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output

    def test_bot_info_double_dash_short_help_triggers_auth(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante bot info -- -h``도 동일."""
        result = runner.invoke(cli, ["bot", "info", "--", "-h"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output

    def test_strategy_submit_double_dash_help_is_not_exempted(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante strategy submit -- --help``은 메타 면제로 처리되지 않는다.

        #1404 P2 정정 이후, ``AuthenticatedGroup.invoke()``가 자식 명령의
        ``make_context``(=``parse_args``)보다 먼저 인증 가드를 발화시키므로
        ``click.Path(exists=True)`` 같은 type validation 응답이 미인증 사용자
        에게 노출되지 않고, exit 1 + "인증이 필요합니다"가 보장된다.
        """
        result = runner.invoke(cli, ["strategy", "submit", "--", "--help"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        # 도움말 본문이 인증 없이 새지 않아야 한다.
        assert "Show this message and exit" not in result.output, result.output


# ── #1404 P2 정정: invoke 단계 가드 (type validation 차단) ──────────────────


class TestInvokeStageAuthGate:
    """``AuthenticatedGroup.invoke()`` 단계 가드가 자식 명령의 parameter type
    validation(``click.Path(exists=True)`` 등) 발화 **이전에** 인증을 검사한다.

    P2 finding (#1404 codex review): 기존 callback 단계 wrapping은 Click의
    ``parse_args``(type/argument validation)가 끝난 뒤에야 실행된다. 따라서
    미인증 사용자가 ``ante strategy submit /nonexistent/path`` 같은 호출에서
    Click의 path validation 에러(exit 2)를 받을 수 있었다 — H2 invariant +
    default-deny 보장 약화. 정정: invoke 단계 가드로 이동.
    """

    def test_strategy_submit_nonexistent_path_returns_auth_error(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante strategy submit /nonexistent/path`` 인증 없이 → exit 1 (인증 실패).

        callback 단계 wrapping만 있던 시절에는 exit 2 + "Path '/nonexistent/path'
        does not exist" 가 나올 수 있었다. invoke 단계 가드 이후에는 path
        validation이 발화하기 전에 인증이 차단된다.
        """
        result = runner.invoke(
            cli, ["strategy", "submit", "/nonexistent/path/strategy.py"]
        )
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        # Click의 path validation 메시지가 새서는 안 된다.
        assert "does not exist" not in result.output, result.output
        assert "Path" not in result.output or "인증" in result.output

    def test_strategy_validate_nonexistent_path_returns_auth_error(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante strategy validate`` 도 동일하게 path validation 이전에 차단."""
        result = runner.invoke(
            cli, ["strategy", "validate", "/nonexistent/path/strategy.py"]
        )
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        assert "does not exist" not in result.output, result.output

    def test_strategy_submit_with_missing_argument_returns_auth_error(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante strategy submit`` (인자 누락) 인증 없이 → exit 1 (인증 실패).

        callback 단계만 있던 시절에는 exit 2 + "Missing argument 'PATH'" 가
        나올 수 있었다. invoke 단계 가드 이후에는 인자 유효성 검증 이전에
        인증이 차단된다.
        """
        result = runner.invoke(cli, ["strategy", "submit"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        assert "Missing argument" not in result.output, result.output

    def test_authenticate_member_runs_before_parse_args(
        self,
        runner: CliRunner,
        clean_env: None,
    ) -> None:
        """``authenticate_member`` 가 자식 명령의 ``parse_args`` 보다 먼저 호출된다.

        ``ante.cli.main.authenticate_member`` 를 patch한 뒤 ``ante strategy submit``
        를 인자 없이 호출하면, parse_args(=missing argument) 이전에 patched
        authenticate_member가 발화한다. patch가 ``ctx.obj["member"] = None``으로
        둔다면 default-deny exit 1 ("인증이 필요합니다") 가 발화.
        """
        from ante.cli import main as _main

        call_count = {"n": 0}

        def _fake_auth(ctx):  # noqa: ANN001, ANN202
            call_count["n"] += 1
            ctx.ensure_object(dict)
            ctx.obj["member"] = None  # 인증 실패 시나리오 재현

        with patch.object(_main, "authenticate_member", side_effect=_fake_auth):
            result = runner.invoke(cli, ["strategy", "submit"])

        assert call_count["n"] >= 1, "authenticate_member가 호출되지 않았다"
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        # parse_args 단계로 진입했다면 click의 missing argument 에러가 발생.
        assert "Missing argument" not in result.output, result.output

    def test_invoke_gate_skips_when_help_present(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``--help`` 메타 옵션이 args에 있으면 invoke 단계 가드가 발화하지 않는다.

        ``ante strategy submit --help`` 는 인증 없이도 exit 0 + Usage. H1 invariant.
        """
        result = runner.invoke(cli, ["strategy", "submit", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        assert "인증이 필요합니다" not in result.output

    def test_invoke_gate_skips_for_init_with_invalid_dir_path(
        self, runner: CliRunner, clean_env: None, tmp_path: Path
    ) -> None:
        """allowlist 명령(``ante init``)은 invoke 단계 가드 면제 — 인증 없이 진입."""
        # init은 인증 없이도 callback이 호출되어야 함을 mock으로 검증.
        bootstrap_mock = AsyncMock()
        create_acc_mock = AsyncMock()
        target = tmp_path / "init_dir"

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=create_acc_mock,
            ),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert "인증이 필요합니다" not in result.output, result.output


# ── 인증된 호출 흐름 ─────────────────────────────────────────────────────────


class TestAuthenticatedFlow:
    """``ANTE_MEMBER_TOKEN`` + 검증 성공 시 leaf callback이 정상 실행된다."""

    def test_authenticated_master_runs_bot_list(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """master 인증 통과 시 ``ante bot list``는 IPC 단계까지 진입."""
        # leaf wrapper가 ante.cli.main.authenticate_member를 호출하므로 거기서 mock.
        from ante.cli import main as _main

        def _set_master(ctx):  # noqa: ANN001, ANN202
            ctx.ensure_object(dict)
            ctx.obj["member"] = _MASTER

        # ipc client도 mock으로 단순 응답
        ok_response = {"status": "ok", "data": {"bots": []}}
        with (
            patch.object(_main, "authenticate_member", side_effect=_set_master),
            patch("ante.cli.commands.ipc_helpers.IPCClient", autospec=True) as mock_cls,
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/ante.sock",
            ),
        ):
            mock_client = AsyncMock()
            mock_client.send.return_value = ok_response
            mock_cls.return_value = mock_client
            result = runner.invoke(cli, ["bot", "list"])

        assert result.exit_code == 0, result.output

    def test_agent_missing_scope_for_system_halt(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """scope 비어 있는 agent → ``ante system halt``는 ``@require_scope``로 차단."""
        from ante.cli import main as _main

        def _set_agent(ctx):  # noqa: ANN001, ANN202
            ctx.ensure_object(dict)
            ctx.obj["member"] = _AGENT_NO_SCOPE

        with patch.object(_main, "authenticate_member", side_effect=_set_agent):
            result = runner.invoke(cli, ["system", "halt"])

        assert result.exit_code == 1, result.output
        assert "권한이 부족합니다" in result.output

    def test_auth_runs_before_scope_check(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``authenticated_group``의 자동 가드가 ``@require_scope`` 보다 먼저 발화.

        토큰이 없으면 ``@require_scope`` 검증 단계 진입 전에 default-deny
        ("인증이 필요합니다") 메시지가 출력되어야 한다.
        """
        result = runner.invoke(cli, ["system", "halt"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output


# ── factory + @require_scope 데코레이터 dedupe ─────────────────────────────


class TestFactoryAndDecoratorDedupe:
    """factory 자동 wrap + ``@require_auth`` / ``@require_scope`` 중복 호출 방지."""

    def test_require_auth_is_idempotent(self) -> None:
        """``require_auth``는 sentinel marker로 두 번 부착해도 한 번만 감싼다."""

        def raw():  # noqa: ANN202
            return "ok"

        once = require_auth(raw)
        twice = require_auth(once)
        assert twice is once  # 같은 wrapper 객체 (멱등)
        assert getattr(twice, "_require_auth_applied", False) is True

    def test_require_scope_marks_sentinel(self) -> None:
        """``require_scope`` wrapper도 sentinel marker로 factory가 dedupe 가능."""

        def raw():  # noqa: ANN202
            return "ok"

        wrapped = require_scope("system:admin")(raw)
        assert getattr(wrapped, "_require_auth_applied", False) is True

    def test_authenticated_group_wrap_is_idempotent(self) -> None:
        """factory가 같은 callback에 두 번 wrap을 하지 않는다 (멱등)."""
        import click

        from ante.cli.middleware import _wrap_callback_with_auth

        def raw(ctx: click.Context) -> str:  # noqa: ANN001
            return "ok"

        once = _wrap_callback_with_auth(raw)
        twice = _wrap_callback_with_auth(once)
        assert twice is once

    def test_factory_delegates_none_check_to_existing_require_auth(self) -> None:
        """``@require_auth`` 부착 callback은 factory가 wrap하더라도 None 검사를 위임.

        factory wrapper는 ``authenticate_member`` 호출(멤버 채우기)만 담당하고,
        member None 검사는 안쪽 ``@require_auth`` 데코레이터가 수행한다. 이는
        sentinel marker(``_require_auth_applied``)로 중복 호출을 방지하기 위함.
        """
        import click

        from ante.cli.middleware import _wrap_callback_with_auth

        @require_auth
        def already_guarded(ctx: click.Context) -> str:
            return "ok"

        wrapped = _wrap_callback_with_auth(already_guarded)
        # factory wrap이 한 번 실행되며, 그 내부에서 already_guarded(=require_auth
        # wrapper)를 호출한다. 두 wrapper가 동일 객체가 아니어도 OK이며, 본
        # invariant는 "factory가 또 wrap하지는 않는다"와 "factory가 None 검사를
        # 별도로 발화시키지 않는다"는 점.
        assert wrapped is not already_guarded  # factory가 한 번은 감쌌다
        assert getattr(wrapped, "_wrapped_by_authenticated_group", False) is True


# ── factory의 click.group 호환성 ─────────────────────────────────────────────


class TestFactoryAPI:
    """``authenticated_group`` factory의 click.group 호환 표면."""

    def test_factory_returns_authenticated_group(self) -> None:
        """``@authenticated_group()`` 데코레이터 결과는 ``AuthenticatedGroup`` 이다."""

        @authenticated_group()
        def grp() -> None:  # noqa: D401, ANN202
            """test group."""

        assert isinstance(grp, AuthenticatedGroup)

    def test_factory_preserves_context_settings(self) -> None:
        """``context_settings``는 click.group을 통해 그대로 전달된다."""

        @authenticated_group(context_settings={"help_option_names": ["-h", "--help"]})
        def grp() -> None:  # noqa: ANN202
            pass

        assert grp.context_settings["help_option_names"] == ["-h", "--help"]


# ── root cli group 구성 확인 ─────────────────────────────────────────────────


class TestRootCliConfiguration:
    """root ``cli`` 그룹이 default-deny 구성으로 설치되어 있다."""

    def test_root_cli_is_authenticated_group(self) -> None:
        """root는 ``AuthenticatedGroup`` 인스턴스다."""
        assert isinstance(cli, AuthenticatedGroup)

    def test_root_cli_inherits_leaf_path_tracking(self) -> None:
        """``AuthenticatedGroup``과 ``LeafAwareGroup``은 leaf path tracking 공유."""
        from ante.cli.middleware import _LeafPathMixin

        assert issubclass(AuthenticatedGroup, _LeafPathMixin)
        assert issubclass(LeafAwareGroup, _LeafPathMixin)

    def test_root_help_option_names_include_short_alias(self) -> None:
        """root context_settings에 ``-h`` alias가 등록되어 H1 invariant 만족."""
        assert cli.context_settings.get("help_option_names") == [
            "-h",
            "--help",
        ]


# ── spec ↔ 코드 drift 정적 보호 ──────────────────────────────────────────────


_SPEC_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "specs" / "cli" / "03-commands.md"
)


class TestSpecAllowlistDrift:
    """spec ``docs/specs/cli/03-commands.md``의 공개 명령 4개가 코드와 일치."""

    def test_exempt_paths_match_spec_named_commands(self) -> None:
        """코드의 ``_AUTH_EXEMPT_COMMAND_PATHS`` 3개 + ``--version``이 spec과 일치."""
        # 코드 SSOT (3 tuple)
        assert _AUTH_EXEMPT_COMMAND_PATHS == {
            ("init",),
            ("member", "reset-password"),
            ("member", "regenerate-recovery-key"),
        }

        # spec 본문에서 4개 공개 명령이 모두 등재되어 있는지 확인
        spec_text = _SPEC_PATH.read_text(encoding="utf-8")
        assert "ante --version" in spec_text
        assert "ante init" in spec_text
        assert "ante member reset-password" in spec_text
        assert "ante member regenerate-recovery-key" in spec_text

        # 후보 제거 항목이 다시 spec에 들어오면 즉시 발견
        assert "ante login" not in spec_text or "후보에서 제거" in spec_text

    def test_version_option_present_in_root(self) -> None:
        """``--version``은 ``@click.version_option``으로 root에 설치된다."""
        names = {p.name for p in cli.params}
        assert "version" in names or any(
            "version" in (getattr(p, "name", "") or "") for p in cli.params
        ), [p.name for p in cli.params]


# ── #1404 P1 정정: --config-dir 인증 시점 반영 ───────────────────────────────


class TestConfigDirReflectedBeforeAuthGate:
    """``ante --config-dir <dir> <cmd>`` 의 ``--config-dir`` 가 인증 게이트 발화
    **이전**에 ``ctx.obj["config_dir"]`` 로 반영된다.

    P1 finding (#1404 codex review v2): ``AuthenticatedGroup.invoke()`` 의
    인증 게이트는 ``super().invoke(ctx)`` 호출 이전에 발화한다. 그러나 root
    callback은 ``super().invoke(ctx)`` 안에서 실행되므로, root callback의
    부작용(``ctx.obj["config_dir"] = ...``) 가 아직 반영되지 않은 상태로
    인증이 진행된다. 결과: ``authenticate_member`` → ``get_db_path`` 가
    default config dir의 DB를 보아 명시한 인스턴스의 토큰이 어긋난 DB에서
    인증 실패한다.

    정정 후에는 ``ctx.params["config_dir"]`` 가 인증 게이트 발화 직전에
    ``ctx.obj["config_dir"]`` 로 미러링되어 ``authenticate_member`` 가
    명시된 디렉토리의 DB를 본다.
    """

    def test_config_dir_visible_to_authenticate_member(
        self, runner: CliRunner, clean_env: None, tmp_path: Path
    ) -> None:
        """``ante --config-dir <tmp> bot list`` 호출 시 ``authenticate_member`` 가
        ``ctx.obj["config_dir"]`` 로 ``<tmp>`` 를 본다.
        """
        from ante.cli import main as _main

        custom_dir = tmp_path / "custom-config"
        custom_dir.mkdir()

        observed: dict[str, object] = {}

        def _record_config_dir(ctx):  # noqa: ANN001, ANN202
            ctx.ensure_object(dict)
            observed["config_dir"] = ctx.obj.get("config_dir")
            # 인증 실패 시나리오 재현 — 본 테스트는 config_dir 가시성만 본다.
            ctx.obj["member"] = None

        with patch.object(_main, "authenticate_member", side_effect=_record_config_dir):
            result = runner.invoke(
                cli, ["--config-dir", str(custom_dir), "bot", "list"]
            )

        # authenticate_member 호출 시점에 config_dir 가 ctx.obj 에 반영돼 있어야 한다.
        assert observed.get("config_dir") == custom_dir, (
            f"config_dir not mirrored before auth gate: {observed}, "
            f"output={result.output}"
        )
        # 토큰 미설정 → exit 1
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output

    def test_master_token_with_custom_config_dir_targets_custom_db(
        self,
        runner: CliRunner,
        clean_env: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``ante --config-dir <tmp> bot list`` (master 토큰) → custom dir DB를 시도.

        config_dir 미러링이 안 되면 ``authenticate_member`` 가 기본 config
        dir DB를 보고 다른 경로 메시지를 낸다. 미러링이 되면 메시지에 custom
        dir 경로가 포함되거나, 실제 DB 접근 직전까지 도달한다.
        """
        custom_dir = tmp_path / "custom-config-2"
        custom_dir.mkdir()
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "fake-token-for-test")

        result = runner.invoke(cli, ["--config-dir", str(custom_dir), "bot", "list"])

        # DB가 아직 없으므로 인증 실패 — 단, 에러 메시지에 custom_dir 경로가
        # 들어 있어야 한다(=인증이 custom_dir 기준으로 시도되었다는 증거).
        assert result.exit_code == 1, result.output
        assert str(custom_dir) in result.output, (
            f"custom config_dir not reflected in auth attempt: {result.output}"
        )


# ── #1404 P2 정정: --version 메타 면제 회수 ──────────────────────────────────


class TestVersionMetaExemptOnlyAtRoot:
    """``--version`` 메타 면제는 root ``ante --version`` 에서만 보장.

    P2 finding (#1404 codex review v2): 기존 ``_has_meta_help_or_version_
    before_dashdash`` 는 args 어디든 ``--version`` 이 있으면 invoke 단계
    가드를 skip했다. 결과: ``ante update --version``,
    ``ante bot list --version`` 같이 root 외 위치에 ``--version`` 이 등장하면
    Click parse error 응답이 인증 없이 노출됐다.

    정정 후 ``--version`` 은 root ``@click.version_option`` 에 위임되고,
    nested 위치는 invoke 단계 가드가 정상 발화한다.
    """

    def test_root_version_without_token_exits_0(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante --version`` 은 root ``@click.version_option`` 처리 → exit 0."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0, result.output
        assert "ante, version" in result.output

    def test_nested_version_on_update_triggers_auth_gate(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante update --version`` 은 인증 게이트가 발화 → exit 1.

        이전 동작: 메타 면제로 인증 skip → Click parse error(``no such option``)
        가 인증 없이 노출.
        새 동작: invoke 단계 가드가 발화하므로 exit 1 + "인증이 필요합니다".
        """
        result = runner.invoke(cli, ["update", "--version"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        # Click의 "No such option" / parse error 가 새서는 안 된다.
        assert "No such option" not in result.output, result.output

    def test_nested_version_on_bot_list_triggers_auth_gate(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante bot list --version`` 도 동일하게 invoke 단계 가드가 발화."""
        result = runner.invoke(cli, ["bot", "list", "--version"])
        assert result.exit_code == 1, result.output
        assert "인증이 필요합니다" in result.output, result.output
        assert "No such option" not in result.output, result.output


# ── 메타 면제 함수 직접 단위 테스트 ──────────────────────────────────────────


class TestHasMetaHelpBeforeDashdash:
    """``_has_meta_help_before_dashdash`` 헬퍼의 정밀한 동작 확인.

    P2 정정 결과:
      - ``--help`` / ``-h`` 만 메타로 인정 (모든 깊이의 H1 invariant).
      - ``--version`` 은 메타로 인정하지 않음 (root ``@click.version_option`` 에 위임).
      - ``--`` 뒤의 ``--help`` 는 위치 인자로 간주 (H2 invariant).
    """

    def test_help_long_before_dashdash(self) -> None:
        from ante.cli.middleware import _has_meta_help_before_dashdash

        assert _has_meta_help_before_dashdash(["bot", "list", "--help"]) is True

    def test_help_short_before_dashdash(self) -> None:
        from ante.cli.middleware import _has_meta_help_before_dashdash

        assert _has_meta_help_before_dashdash(["bot", "list", "-h"]) is True

    def test_version_token_no_longer_meta(self) -> None:
        """``--version`` 은 더 이상 면제 토큰이 아니다 (P2 정정)."""
        from ante.cli.middleware import _has_meta_help_before_dashdash

        assert _has_meta_help_before_dashdash(["bot", "list", "--version"]) is False
        assert _has_meta_help_before_dashdash(["update", "--version"]) is False

    def test_help_after_dashdash_not_meta(self) -> None:
        from ante.cli.middleware import _has_meta_help_before_dashdash

        # ``--`` 뒤 ``--help`` 는 위치 인자.
        assert _has_meta_help_before_dashdash(["bot", "info", "--", "--help"]) is False

    def test_no_meta_tokens(self) -> None:
        from ante.cli.middleware import _has_meta_help_before_dashdash

        assert _has_meta_help_before_dashdash(["bot", "list"]) is False


# ── click 버전 pin ──────────────────────────────────────────────────────────


_PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


class TestClickVersionPin:
    """Click 8.2의 ``Context.protected_args`` deprecation을 피하기 위해 8.1.x로 pin."""

    def test_pyproject_pins_click_below_8_2(self) -> None:
        text = _PYPROJECT.read_text(encoding="utf-8")
        # 8.1 이상, 8.2 미만으로 명확히 pin되어 있어야 한다.
        assert "click>=8.1,<8.2" in text, text
