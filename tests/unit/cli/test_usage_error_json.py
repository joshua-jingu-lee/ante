"""``--format json`` 모드의 click parsing-stage 에러 envelope 회귀 (#1539).

배경:
    ``ante --format json feed config set ANTE_DART_API_KEY`` 같은 호출은
    Click 의 ``UsageError`` (subclass: ``MissingParameter``, ``BadParameter``,
    ``BadArgumentUsage``, ``NoSuchOption``) 를 발화하는데, click 기본 동작은
    stderr 에 ``Usage: ... Error: Missing argument 'VALUE'.`` 텍스트를 출력하고
    exit 2 로 종료한다. 이는 비대화형 CLI 입력 계약 (스펙
    ``docs/specs/cli/02-design-decisions.md:78-81``) 의 JSON envelope + exit 1
    요구와 어긋난다.

    fix: :meth:`AuthenticatedGroup.main` 오버라이드가 raw args 토큰열에서
    ``--format`` 마지막 값을 sniff 해 json 일 때 ``standalone_mode=False`` 로
    click 을 호출, ``UsageError`` 를 직접 catch 해 envelope 출력 + ``sys.exit(1)``.

Coverage map:
    - missing argument JSON 모드: ``feed config set ANTE_DART_API_KEY`` (value 누락)
      → stdout JSON envelope + exit 1.
    - missing argument text 모드 (회귀): 동일 입력 → click 기본 stderr + exit 2.
    - unknown option JSON 모드: ``bot list --unknown-flag`` → JSON envelope + exit 1.
    - bad argument type JSON 모드: ``bot create --interval not-a-number`` →
      JSON envelope + exit 1.
    - sniff 우선순위: 마지막 ``--format`` 토큰이 효과적인 모드를 결정.
    - gate-exempt 보존: ``--help`` / ``--version`` / nested ``--help`` 모두
      ``--format json`` 이 함께 와도 click 기본 동작 (exit 0) 유지.
    - Abort 보존: ``standalone_mode=True`` 호출에서 ``Abort`` 발생 시
      ``Aborted!`` stderr + exit 1.

SSOT 참조:
    - ``src/ante/cli/middleware.py`` (:class:`AuthenticatedGroup`,
      ``main`` override + ``_sniff_output_format``)
    - ``src/ante/cli/formatter.py`` (:meth:`OutputFormatter.error`)
    - ``docs/specs/cli/02-design-decisions.md:78-81`` (JSON envelope + exit 1 계약)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.cli.middleware import AuthenticatedGroup
from ante.member.models import Member, MemberRole, MemberType

if TYPE_CHECKING:
    from collections.abc import Iterator

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """``authenticate_member`` 를 패치해 master member 를 주입하는 runner.

    JSON envelope 가 stdout 으로 가는지 확인해야 하므로 ``mix_stderr=False`` 로
    stdout/stderr 를 분리한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001, ANN202
                ctx.ensure_object(dict)
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """``ANTE_MEMBER_TOKEN`` / 토큰 파일 차단 + ``ANTE_CONFIG_DIR`` 격리."""
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path / "config"))
    yield


def _parse_json_line(stdout: str) -> dict[str, object]:
    """stdout 첫 JSON dict 라인을 파싱해 반환."""
    for line in stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"stdout 에서 JSON dict 를 찾지 못함: {stdout!r}")


# ── missing argument: spec primary case (#1539 본문 시나리오) ───────────────


class TestMissingArgument:
    """``ante feed config set ANTE_DART_API_KEY`` (value 누락) 시나리오."""

    def test_missing_argument_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1 (스펙 02-design-decisions.md:78)."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "feed",
                "config",
                "set",
                "ANTE_DART_API_KEY",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "CLI_USAGE_ERROR", payload
        # click 의 기본 메시지 본문 ("Missing argument 'VALUE'.") 그대로 보존.
        assert "Missing argument" in str(payload["message"]), payload
        assert "VALUE" in str(payload["message"]), payload
        # 텍스트 fallback 이 stderr 로 동시에 새지 않아야 한다 (JSON 모드 단일 표면).
        assert "Usage:" not in result.stderr, result.stderr

    def test_missing_argument_text_mode_preserves_click_default(
        self, runner: CliRunner
    ) -> None:
        """text 모드 (회귀): click 기본 ``Usage: ... Error: ...`` stderr + exit 2."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "text",
                "feed",
                "config",
                "set",
                "ANTE_DART_API_KEY",
            ],
        )

        assert result.exit_code == 2, (
            f"expected exit 2 (click default), got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # 텍스트 모드는 stdout 으로 JSON envelope 를 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        # click 기본 텍스트 에러 메시지는 stderr 로 출력된다.
        assert "Usage:" in result.stderr, result.stderr
        assert "Missing argument" in result.stderr, result.stderr


# ── unknown option (UsageError 다른 subclass) ───────────────────────────────


class TestUnknownOption:
    """``--unknown-flag`` 같이 정의되지 않은 옵션 → ``NoSuchOption``."""

    def test_unknown_option_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1."""
        result = runner.invoke(
            cli,
            ["--format", "json", "bot", "list", "--unknown-flag"],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "CLI_USAGE_ERROR", payload
        assert "no such option" in str(payload["message"]).lower(), payload


# ── bad argument type (BadParameter via type=click.IntRange) ────────────────


class TestBadArgumentType:
    """``bot create --interval not-a-number`` → ``BadParameter`` (UsageError)."""

    def test_bad_int_value_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "stg-1",
                "--account",
                "test",
                "--interval",
                "not-a-number",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "CLI_USAGE_ERROR", payload
        # click 의 IntRange 타입 변환 실패 메시지 본문이 포함된다.
        assert (
            "not-a-number" in str(payload["message"])
            or "interval" in str(payload["message"]).lower()
        ), payload


# ── sniff 우선순위 (서브커맨드 --format 이 root 를 오버라이드) ───────────────


class TestSniffPriority:
    """``_sniff_output_format`` 은 args 의 **마지막** ``--format`` 값을 우선한다.

    :func:`ante.cli.formatter.format_option` 의 서브커맨드 ``--format`` 오버라이드
    패턴을 따른다. 이 우선순위는 정상 명령에서도 동일하므로 parsing-stage 에러
    경로도 같은 순서를 따라야 한다.
    """

    def test_sniff_static_helper_prefers_last_format_token(self) -> None:
        """raw args 에서 마지막 ``--format`` 값이 결과를 결정한다."""
        # root json + subcommand text → text (서브커맨드 override).
        assert (
            AuthenticatedGroup._sniff_output_format(
                ["--format", "json", "bot", "list", "--format", "text"]
            )
            == "text"
        )
        # root text + subcommand json → json.
        assert (
            AuthenticatedGroup._sniff_output_format(
                ["--format", "text", "bot", "list", "--format", "json"]
            )
            == "json"
        )
        # 단일 --format json → json.
        assert (
            AuthenticatedGroup._sniff_output_format(["--format", "json", "bot", "list"])
            == "json"
        )
        # --format=value (등호 형태) 도 지원.
        assert (
            AuthenticatedGroup._sniff_output_format(
                ["--format=json", "bot", "list", "--format=text"]
            )
            == "text"
        )
        # --format 없음 → 기본 "text".
        assert AuthenticatedGroup._sniff_output_format(["bot", "list"]) == "text"
        # None args → ``sys.argv[1:]`` fallback (간접 검증: 빈 list 와 동일 결과 보장).
        assert AuthenticatedGroup._sniff_output_format([]) == "text"

    def test_subcommand_format_text_overrides_root_format_json(
        self, runner: CliRunner
    ) -> None:
        """``ante --format json bot list --format text`` → text 모드 → click 기본 동작.

        sniff 가 마지막 토큰 (text) 을 우선하므로, ``--unknown-flag`` 같은
        UsageError 가 함께 발생해도 click 기본 stderr + exit 2 가 보존된다.
        """
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "bot",
                "list",
                "--unknown-flag",
                "--format",
                "text",
            ],
        )

        # 마지막 --format 이 text → 우리 catch 진입 안 함 → click 기본 exit 2.
        assert result.exit_code == 2, (
            f"expected exit 2 (text mode click default), got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # JSON envelope 가 stdout 으로 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout

    def test_subcommand_format_json_overrides_root_format_text(
        self, runner: CliRunner
    ) -> None:
        """``ante --format text ... --format json`` → json 모드 → JSON envelope."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "text",
                "bot",
                "list",
                "--unknown-flag",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1 (json mode), got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "CLI_USAGE_ERROR", payload


# ── gate-exempt 보존 (--help / --version) ────────────────────────────────────


class TestGateExemptPreserved:
    """``--help`` / ``--version`` 은 click 이 ``ctx.exit()`` 으로 자체 종료한다.

    우리 main override 의 try/except 블록은 ``UsageError`` / ``Abort`` 만
    catch 하므로 ``Exit`` 예외는 정상 통과한다. ``--format json`` 이 함께 주어져도
    click 기본 ``--help`` / ``--version`` 출력과 exit 0 동작이 그대로 유지된다.
    """

    def test_root_help_with_format_json_exits_0(self, runner: CliRunner) -> None:
        """``ante --format json --help`` → click 기본 help, exit 0."""
        result = runner.invoke(cli, ["--format", "json", "--help"])
        assert result.exit_code == 0, (
            f"expected exit 0, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Usage:" in result.stdout, result.stdout

    def test_root_version_with_format_json_exits_0(self, runner: CliRunner) -> None:
        """``ante --format json --version`` → click 기본 version, exit 0."""
        result = runner.invoke(cli, ["--format", "json", "--version"])
        assert result.exit_code == 0, (
            f"expected exit 0, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "ante" in result.stdout.lower(), result.stdout

    def test_subcommand_help_with_format_json_exits_0(self, runner: CliRunner) -> None:
        """``ante --format json bot list --help`` → click 기본 help, exit 0."""
        result = runner.invoke(cli, ["--format", "json", "bot", "list", "--help"])
        assert result.exit_code == 0, (
            f"expected exit 0, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Usage:" in result.stdout, result.stdout

    def test_root_help_text_mode_unchanged(self, runner: CliRunner) -> None:
        """``ante --help`` (text 기본) → click 기본 help, exit 0."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0, (
            f"expected exit 0, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Usage:" in result.stdout, result.stdout


# ── Abort 보존 (KeyboardInterrupt 시뮬레이션) ────────────────────────────────


class TestAbortPreserved:
    """``click.exceptions.Abort`` 발생 시 ``Aborted!`` stderr + exit 1 보존.

    ``standalone_mode=False`` 로 호출한 click 은 Abort 를 re-raise 한다
    (click core.py:1121-1125). 우리 main override 가 이를 catch 해
    standalone_mode=True 호출자에 한해 ``Aborted!`` 출력 + ``sys.exit(1)``.
    """

    def test_abort_in_json_mode_emits_aborted_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """``raise click.exceptions.Abort()`` 시 stderr ``Aborted!`` + exit 1.

        click ``BaseCommand.main`` 은 ``standalone_mode=False`` 일 때 ``Abort``
        를 re-raise 한다 (click core.py:1121-1125). 우리 main override 가
        이를 catch 해 ``standalone_mode=True`` 호출자에게 click 기본 Abort
        동작 (``Aborted!`` stderr + ``sys.exit(1)``) 을 그대로 보존해야 한다.

        ``BaseCommand.invoke`` 를 patch 해 직접 Abort 를 발화시킨다 — 이
        지점은 우리 main override 의 ``super().main()`` 호출 내부이므로
        click 이 standalone_mode=False 분기에서 re-raise 한다.
        """

        def _raise_abort(self, ctx):  # noqa: ANN001, ANN202, ARG001
            raise click.exceptions.Abort()

        with patch.object(AuthenticatedGroup, "invoke", _raise_abort):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "list"],
            )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Aborted!" in result.stderr, result.stderr


# ── 회귀: 정상 명령은 영향 없음 ──────────────────────────────────────────────


class TestNormalCommandUnaffected:
    """JSON 모드 정상 명령은 우리 catch 블록을 통과해 click 정상 흐름 그대로."""

    def test_json_mode_help_returns_normally(self, runner: CliRunner) -> None:
        """``--format json --help`` 은 정상 종료 + click help 출력."""
        result = runner.invoke(cli, ["--format", "json", "--help"])
        assert result.exit_code == 0, result.output
        # Click 의 ``Show this message and exit.`` 같은 help 본문이 포함된다.
        assert "Show this" in result.stdout or "--help" in result.stdout, result.stdout
