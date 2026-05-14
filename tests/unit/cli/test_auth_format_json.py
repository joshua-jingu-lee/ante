"""CLI 인증/권한 실패 시 ``--format json`` 모드의 구조화 에러 출력 회귀 (#1533).

배경:
    ``ante --format json`` 모드에서 CLI 인증/권한 실패가 stderr 텍스트만
    내고 stdout JSON error를 발급하지 않는 contract drift가 있었다. 자동화
    호출자(특히 ante-oracle host probe)는 JSON 파서를 사용할 수 없어
    동기화에 실패한다.

본 테스트는 4개의 emit site(``_authenticate_member`` /
``_enforce_invoke_auth_gate`` / ``_wrap_callback_with_auth`` /
``require_scope``) 모두 ``OutputFormatter.error`` 경유로 통일되어 JSON 모드에서
``{"status":"error","code":<code>,"message":<message>}`` JSON을 stdout으로
출력함을 회귀 보장한다. 텍스트 모드의 한국어 메시지는 그대로 stderr로
유지된다(기존 회귀 보호).

SSOT 참조:
    - ``src/ante/cli/middleware.py`` (``_emit_auth_error``,
      ``_mirror_root_globals_to_obj`` 의 ``output_format`` 미러링)
    - ``src/ante/cli/formatter.py`` (``OutputFormatter.error`` 스키마)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Iterator

from ante.cli.main import cli
from ante.cli.middleware import _emit_auth_error
from ante.member.models import Member, MemberRole, MemberType

_AGENT_NO_SCOPE = Member(
    member_id="cli-agent-noscope",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="CLI Agent (no scope)",
    status="active",
    scopes=[],
)


@pytest.fixture()
def runner() -> CliRunner:
    """JSON 응답을 stdout/stderr 분리 캡처하기 위해 mix_stderr=False."""
    return CliRunner(mix_stderr=False)


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """``ANTE_MEMBER_TOKEN`` / 토큰 파일을 차단한 환경.

    ``ANTE_TOKEN_FILE`` 은 실제로 ``open()`` 이 시도되므로 존재하지 않는 파일을
    가리키는 경로로 설정한다.
    """
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))
    yield


def _parse_json_line(stdout: str) -> dict[str, object]:
    """stdout 첫 JSON 라인을 파싱해서 dict 로 반환."""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"stdout 에서 JSON dict 를 찾지 못함: {stdout!r}")


# ── invoke 게이트 분기 (no-token + --format json) ───────────────────────────


class TestInvokeAuthGateJsonFormat:
    """``_enforce_invoke_auth_gate`` 분기에서 ``--format json`` 일 때 JSON stdout."""

    def test_bot_list_no_token_emits_json_error(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``ante --format json bot list`` (no token) → stdout JSON error, exit 1."""
        result = runner.invoke(cli, ["--format", "json", "bot", "list"])

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # JSON 은 stdout 으로 흘러야 한다 (stderr 텍스트가 아니라).
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "auth_required", payload
        assert "인증이 필요합니다" in str(payload["message"]), payload
        # 텍스트 fallback 메시지가 stderr 에 동시에 새지 않아야 한다.
        assert "인증이 필요합니다" not in result.stderr, result.stderr

    def test_bot_list_no_token_text_mode_keeps_stderr_message(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """텍스트 모드 회귀: 기존 한국어 stderr 메시지 + exit 1."""
        result = runner.invoke(cli, ["--format", "text", "bot", "list"])

        assert result.exit_code == 1, result.stderr
        # JSON 이 stdout 으로 새지 않아야 한다.
        assert result.stdout.strip() == "", (
            f"text 모드인데 stdout 이 비어 있지 않음: {result.stdout!r}"
        )
        assert "인증이 필요합니다" in result.stderr, result.stderr

    def test_bot_list_no_token_default_mode_is_text(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """``--format`` 미지정(기본 text) 도 stderr 텍스트 회귀."""
        result = runner.invoke(cli, ["bot", "list"])

        assert result.exit_code == 1, result.stderr
        assert result.stdout.strip() == "", result.stdout
        assert "인증이 필요합니다" in result.stderr, result.stderr


# ── invalid token 분기 (PermissionError + --format json) ────────────────────


class TestInvalidTokenJsonFormat:
    """``_authenticate_member`` 의 ``PermissionError`` → ``auth_failed`` JSON."""

    def test_invalid_token_emits_json_auth_failed(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """stale 토큰 + 없는 DB → ``auth_failed`` JSON, exit 1."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        # config_dir 을 빈 tmp_path 로 강제해서 ``ante init`` 이 안 돌아간 상태를
        # 재현. ``_run_authenticate`` 가 DB 접근 불가로 ``PermissionError`` 를
        # 발생시킨다.
        custom_dir = tmp_path / "custom-config"
        custom_dir.mkdir()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "--config-dir",
                str(custom_dir),
                "bot",
                "list",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "auth_failed", payload
        assert "인증 실패" in str(payload["message"]), payload
        assert "인증 실패" not in result.stderr, result.stderr

    def test_invalid_token_text_mode_keeps_stderr_message(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """텍스트 모드: 기존 한국어 stderr 메시지 + exit 1 회귀 보호."""
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "sk_stale_invalid")
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "no-such-token"))
        custom_dir = tmp_path / "custom-config-text"
        custom_dir.mkdir()

        result = runner.invoke(
            cli,
            ["--format", "text", "--config-dir", str(custom_dir), "bot", "list"],
        )

        assert result.exit_code == 1, result.stderr
        assert result.stdout.strip() == "", result.stdout
        assert "인증 실패" in result.stderr, result.stderr


# ── scope 부족 분기 (agent + --format json) ─────────────────────────────────


class TestPermissionDeniedJsonFormat:
    """``require_scope`` 의 missing scope → ``permission_denied`` JSON."""

    def test_agent_missing_scope_emits_json_permission_denied(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """scope 비어 있는 agent → ``ante --format json system halt`` JSON error."""
        from ante.cli import main as _main

        def _set_agent(ctx):  # noqa: ANN001, ANN202
            ctx.ensure_object(dict)
            ctx.obj["member"] = _AGENT_NO_SCOPE

        with patch.object(_main, "authenticate_member", side_effect=_set_agent):
            result = runner.invoke(cli, ["--format", "json", "system", "halt"])

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "permission_denied", payload
        assert "권한이 부족합니다" in str(payload["message"]), payload
        assert "권한이 부족합니다" not in result.stderr, result.stderr

    def test_agent_missing_scope_text_mode_keeps_stderr_message(
        self, runner: CliRunner, clean_env: None
    ) -> None:
        """텍스트 모드 회귀: 기존 한국어 stderr 메시지 + exit 1."""
        from ante.cli import main as _main

        def _set_agent(ctx):  # noqa: ANN001, ANN202
            ctx.ensure_object(dict)
            ctx.obj["member"] = _AGENT_NO_SCOPE

        with patch.object(_main, "authenticate_member", side_effect=_set_agent):
            result = runner.invoke(cli, ["--format", "text", "system", "halt"])

        assert result.exit_code == 1, result.stderr
        assert result.stdout.strip() == "", result.stdout
        assert "권한이 부족합니다" in result.stderr, result.stderr


# ── formatter 미설정 fallback (직접 단위 테스트) ────────────────────────────


class TestEmitAuthErrorFallback:
    """``_emit_auth_error`` 가 ``ctx.obj["formatter"]`` 미설정 시 stderr 텍스트로
    fallback함을 직접 단위 테스트로 검증.

    JSON 모드 미러링이 어떤 이유로든 발화하지 않은 경로에서도 helper가
    ``KeyError`` / ``AttributeError`` 없이 stderr 텍스트로 떨어진다.
    """

    def test_formatter_missing_falls_back_to_stderr_text(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``ctx.obj`` 가 비어 있을 때 helper 가 stderr 로 텍스트를 출력한다."""

        @click.command()
        @click.pass_context
        def _stub(ctx: click.Context) -> None:
            # formatter 키가 비어 있는 ctx.obj 를 명시적으로 구성.
            ctx.obj = {}
            _emit_auth_error(ctx, "auth_required", "fallback message")

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(_stub, [])

        # SystemExit 은 호출자 책임이므로 helper 자체는 exit 0 으로 돌아온다.
        assert result.exit_code == 0, result.stderr
        # JSON 이 stdout 으로 출력되어서는 안 된다.
        assert result.stdout.strip() == "", result.stdout
        assert "fallback message" in result.stderr, result.stderr

    def test_formatter_text_mode_falls_back_to_stderr_text(
        self,
    ) -> None:
        """text 모드 formatter 가 설정돼 있어도 stderr 텍스트 분기로 간다."""
        from ante.cli.formatter import OutputFormatter

        @click.command()
        @click.pass_context
        def _stub(ctx: click.Context) -> None:
            ctx.obj = {"formatter": OutputFormatter("text")}
            _emit_auth_error(ctx, "auth_required", "text-mode message")

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(_stub, [])

        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip() == "", result.stdout
        assert "text-mode message" in result.stderr, result.stderr

    def test_formatter_json_mode_emits_structured_stdout(self) -> None:
        """json 모드 formatter 가 설정돼 있으면 stdout JSON 으로 출력."""
        from ante.cli.formatter import OutputFormatter

        @click.command()
        @click.pass_context
        def _stub(ctx: click.Context) -> None:
            ctx.obj = {"formatter": OutputFormatter("json")}
            _emit_auth_error(ctx, "auth_required", "json-mode message")

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(_stub, [])

        assert result.exit_code == 0, result.stderr
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "auth_required", payload
        assert payload["message"] == "json-mode message", payload


# ── _mirror_root_globals_to_obj 의 output_format 미러링 단위 테스트 ────────


class TestMirrorOutputFormat:
    """``_mirror_root_globals_to_obj`` 가 ``output_format`` 을 미러링한다."""

    def test_mirrors_output_format_into_formatter(self) -> None:
        """``ctx.params["output_format"] = "json"`` → ``ctx.obj["formatter"]`` JSON."""
        from ante.cli.formatter import OutputFormatter
        from ante.cli.middleware import _mirror_root_globals_to_obj

        ctx = click.Context(click.Command("noop"))
        ctx.obj = {}
        ctx.params = {"output_format": "json"}
        _mirror_root_globals_to_obj(ctx)

        assert ctx.obj["format"] == "json"
        formatter = ctx.obj["formatter"]
        assert isinstance(formatter, OutputFormatter)
        assert formatter.is_json is True

    def test_defaults_to_text_when_output_format_missing(self) -> None:
        """``output_format`` 이 비어도 text formatter 가 기본 미러링된다."""
        from ante.cli.formatter import OutputFormatter
        from ante.cli.middleware import _mirror_root_globals_to_obj

        ctx = click.Context(click.Command("noop"))
        ctx.obj = {}
        ctx.params = {}
        _mirror_root_globals_to_obj(ctx)

        assert ctx.obj["format"] == "text"
        formatter = ctx.obj["formatter"]
        assert isinstance(formatter, OutputFormatter)
        assert formatter.is_json is False

    def test_does_not_overwrite_existing_formatter(self) -> None:
        """root callback 이 먼저 채운 formatter 는 덮어쓰지 않는다 (멱등)."""
        from ante.cli.formatter import OutputFormatter
        from ante.cli.middleware import _mirror_root_globals_to_obj

        existing = OutputFormatter("json")
        ctx = click.Context(click.Command("noop"))
        ctx.obj = {"formatter": existing, "format": "json"}
        ctx.params = {"output_format": "text"}
        _mirror_root_globals_to_obj(ctx)

        # 기존 formatter 가 그대로 유지된다.
        assert ctx.obj["formatter"] is existing
        assert ctx.obj["format"] == "json"
