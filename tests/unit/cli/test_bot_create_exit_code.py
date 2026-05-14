"""``ante bot create`` 로컬 검증 실패의 exit code 회귀 (#1534).

배경:
    ``ante --format json bot create --param invalid_no_equals_sign`` 같은
    호출은 stdout 으로 error JSON envelope 를 출력하지만 exit code 가 0 으로
    끝나는 결함이 있었다 (``src/ante/cli/commands/bot.py:237-239`` 의
    BadParameter 분기, ``:272-276`` 의 generic Exception 분기 모두 ``return``
    으로 끝나서 SystemExit 가 발화하지 않음).

    자동화 호출자(특히 CI / agent 파이프라인)는 stdout JSON 만으로 분기하지
    않고 process exit code 를 1차 신호로 사용한다. 본 테스트는 두 분기 모두에서
    JSON / text 모드 양쪽이 exit 1 로 종료되며, stdout/stderr 에 기존 메시지가
    정상 출력됨을 회귀 보장한다.

Coverage map:
    - BadParameter 분기 (``--param invalidformat``)
      - JSON 모드: stdout JSON envelope ``{"status":"error","code":"",
        "message":"잘못된 파라미터 형식: ..."}`` + exit 1.
      - text 모드: stderr ``Error: 잘못된 파라미터 형식: ...`` + exit 1.
    - generic Exception 분기 (``ipc_send`` mock 으로 ``RuntimeError`` raise)
      - JSON 모드: stdout JSON envelope + exit 1.
      - text 모드: stderr ``Error: ...`` + exit 1.

SSOT 참조:
    - ``src/ante/cli/commands/bot.py`` (``bot_create``, ``_parse_param``)
    - ``src/ante/cli/formatter.py`` (``OutputFormatter.error`` 스키마)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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


@pytest.fixture
def runner() -> CliRunner:
    """authenticate_member 를 패치해 master member 를 주입하는 runner.

    JSON / stderr 검증을 위해 ``mix_stderr=False`` 로 stdout/stderr 를 분리한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001, ANN202
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


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


# ── BadParameter 분기 (``--param invalidformat``) ───────────────────────────


class TestBotCreateBadParamExitCode:
    """``--param`` 로컬 파싱 실패 분기에서 exit 1 회귀."""

    def test_bad_param_json_mode_emits_json_envelope_and_exits_1(
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
                "--param",
                "invalidformat",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "", payload
        assert "잘못된 파라미터 형식" in str(payload["message"]), payload
        # text 메시지가 stderr 로 동시에 새지 않아야 한다.
        assert "잘못된 파라미터 형식" not in result.stderr, result.stderr

    def test_bad_param_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: 잘못된 파라미터 형식 ...`` + exit 1."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "text",
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "stg-1",
                "--account",
                "test",
                "--param",
                "invalidformat",
            ],
        )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 JSON 이 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        assert "Error: 잘못된 파라미터 형식" in result.stderr, result.stderr


# ── generic Exception 분기 (``ipc_send`` raise) ─────────────────────────────


class TestBotCreateIPCExceptionExitCode:
    """``ipc_send`` 가 generic Exception 을 raise 했을 때 exit 1 회귀."""

    @staticmethod
    def _build_ipc_mock_failing(message: str) -> AsyncMock:
        """``ipc_send`` 를 mock 해서 ``RuntimeError(message)`` 를 raise."""
        mock = AsyncMock(side_effect=RuntimeError(message))
        return mock

    def test_ipc_exception_json_mode_emits_json_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout JSON envelope + exit 1."""
        ipc_mock = self._build_ipc_mock_failing("IPC 연결 실패")

        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_mock):
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
                ],
            )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "", payload
        assert "IPC 연결 실패" in str(payload["message"]), payload
        # text fallback 이 stderr 로 동시에 새지 않아야 한다.
        assert "IPC 연결 실패" not in result.stderr, result.stderr

    def test_ipc_exception_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: IPC 연결 실패`` + exit 1."""
        ipc_mock = self._build_ipc_mock_failing("IPC 연결 실패")

        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_mock):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "text",
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                ],
            )

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 JSON 이 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        assert "Error: IPC 연결 실패" in result.stderr, result.stderr
