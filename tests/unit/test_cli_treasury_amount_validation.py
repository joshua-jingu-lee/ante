"""CLI treasury allocate/deallocate amount finite-positive 검증 매트릭스 (#1517).

이슈 #1517 (oracle A7 cli_treasury_nan_amount_accepted):
``treasury allocate``/``deallocate``의 ``amount`` 인자가 click ``type=float``로
``nan``/``inf``/``-inf``/0/음수를 그대로 통과시키고, IPC 호출 실패 시에도
``except Exception as e: fmt.error(str(e)); return``로 exit 0을 반환하던 ingress
drift를 닫는다.

본 PR은 두 축의 invariant를 함께 단정한다:

1. **CLI ingress (callback)** — ``_validators.validate_positive_finite_amount``를
   ``allocate``/``deallocate``의 amount 인자 ``callback``으로 부착해 NaN/±Inf/0/
   음수 입력에서 ``click.BadParameter`` → click 표준 경로(stderr text + exit 2).
2. **IPC error exit code (#1515 패턴)** — valid amount + IPC 실패(Exception 또는
   ``success=False``) 시 ``fmt.error(...); ctx.exit(1)``로 exit != 0 보장.

분류 / 스펙:
- ``treasury allocate``/``deallocate``는 spec ``docs/specs/cli/03-commands.md``상
  ``runtime IPC`` 분류 (``ipc_send("treasury.allocate"|"treasury.deallocate", ...)``).
- service-layer ``Treasury.allocate``/``deallocate``는 이미 ``not math.isfinite or
  amount <= 0`` guard 보유 — 회귀 안전. 본 PR은 CLI ingress + exit code 정합만 적용
  (Codex Plan Review 노트 반영).
- ``--format json`` 모드에서 ``click.BadParameter``는 click 표준 text stderr 경로를
  탄다. JSON envelope 표준화는 Non-Goals (스펙 부채, #1513/#1514 동일 정책,
  follow-up 후보).

Codex Plan Review v2 패턴:
- ``CliRunner(mix_stderr=False)`` 사용 — text stderr와 JSON stdout을 분리 단정.
- click 정확한 메시지 텍스트 의존 대신 exit != 0 + (``Invalid value`` 또는
  ``finite`` / ``양수`` / 입력값 자체) 키워드 강건 매칭.
- IPC mock은 ``ante.cli.commands.ipc_helpers.ipc_send`` async function patch
  (#1517 IPC handler ``treasury.allocate``/``treasury.deallocate``).
"""

from __future__ import annotations

import inspect
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


def _make_runner() -> CliRunner:
    """``mix_stderr=False`` runner. click 버전 fallback (#1513 패턴)."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증을 mock으로 우회한 CliRunner.

    ``mix_stderr=False``로 stderr/stdout 분리, ``authenticate_member`` patch로
    실제 DB 접근 방지 (#1515 / ``test_cli_missing_resource_exit.py`` 패턴).
    """
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


# ── 공통 헬퍼 ────────────────────────────────────────────


# callback이 직접 거부하는 케이스(NaN/Inf/0).
# 음수(-100, -inf) 토큰은 click argument parser 단계에서 옵션 후보로 처리되어
# "No such option"으로 reject — argv 순서를 ``--account ... --`` 후 amount로
# 전달해 옵션 파싱을 종료한 뒤 callback 경로에 도달시킨다.
_CALLBACK_INVALID_AMOUNTS = [
    ("nan", "finite"),
    ("inf", "finite"),
    ("-inf", "finite"),
    ("0", "양수"),
    ("-100", "양수"),
]


def _assert_invalid_amount_rejected(result, value: str, keyword_hint: str) -> None:
    """invalid amount 거부 invariant 단정.

    - exit code != 0 (click ``BadParameter`` 표준은 exit 2).
    - stderr text에 click 표준 ``Invalid value`` 또는 입력값/도메인 키워드 포함.
    - traceback 미포함 (BadParameter는 click이 표준 경로로 변환).
    """
    assert result.exit_code != 0, (
        f"invalid amount {value!r}가 exit 0으로 통과됨: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr = result.stderr or ""
    stdout = result.stdout or ""
    combined = stderr + stdout
    # click 표준 BadParameter 경로 또는 도메인 키워드 / 입력값 매칭
    assert (
        "Invalid value" in combined
        or "finite" in combined
        or "양수" in combined
        or value in combined
        or keyword_hint in combined
    ), f"기대 키워드 부재: stderr={stderr!r} stdout={stdout!r}"
    # BadParameter는 click 표준 경로 — Python traceback이 노출되어선 안 됨.
    assert "Traceback" not in combined, (
        f"click BadParameter가 traceback으로 누출: {combined!r}"
    )


def _allocate_argv(value: str, *, json_mode: bool = False) -> list[str]:
    """``treasury allocate`` argv. 음수 토큰도 옵션 파싱이 끝난 뒤 amount로
    전달되도록 ``--account ... --`` separator를 amount 앞에 둔다.

    callback이 invalid 값에 도달함을 보장한다 — 음수 토큰을 옵션 위치에 두면
    click이 "No such option"으로 먼저 reject되어 callback 동작이 검증되지 않음.
    """
    argv = ["treasury", "allocate", "bot-1", "--account", "acc-1", "--", value]
    if json_mode:
        argv = ["--format", "json", *argv]
    return argv


def _deallocate_argv(value: str, *, json_mode: bool = False) -> list[str]:
    """``treasury deallocate`` argv. (``_allocate_argv``와 동일 정책)."""
    argv = ["treasury", "deallocate", "bot-1", "--account", "acc-1", "--", value]
    if json_mode:
        argv = ["--format", "json", *argv]
    return argv


# ── treasury allocate ───────────────────────────────────


class TestAllocateAmountIngress:
    """``ante treasury allocate <bot> <amount> --account <acc>`` ingress 매트릭스.

    NaN/±Inf/0/음수는 click ``BadParameter`` 표준 경로(stderr text + exit != 0).
    text/json 두 모드 모두 단정 (json 모드도 BadParameter는 text stderr).
    """

    @pytest.mark.parametrize(("value", "keyword"), _CALLBACK_INVALID_AMOUNTS)
    def test_text_mode_rejects_invalid(
        self, runner: CliRunner, value: str, keyword: str
    ) -> None:
        result = runner.invoke(cli, _allocate_argv(value))
        _assert_invalid_amount_rejected(result, value, keyword)

    @pytest.mark.parametrize(("value", "keyword"), _CALLBACK_INVALID_AMOUNTS)
    def test_json_mode_rejects_invalid(
        self, runner: CliRunner, value: str, keyword: str
    ) -> None:
        """``--format json`` 모드도 BadParameter는 text stderr (Non-Goals)."""
        result = runner.invoke(cli, _allocate_argv(value, json_mode=True))
        _assert_invalid_amount_rejected(result, value, keyword)


class TestAllocateIPCExitCode:
    """valid amount + IPC 경로 exit code 정합 (#1515 패턴)."""

    def test_valid_success_exits_zero(self, runner: CliRunner) -> None:
        """valid amount + IPC success=True → exit 0 (회귀 보존)."""
        mock_ipc = AsyncMock(return_value={"success": True})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "allocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 0, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        mock_ipc.assert_awaited_once()

    def test_ipc_exception_exits_nonzero(self, runner: CliRunner) -> None:
        """valid amount + IPC raises Exception → exit 1 (#1515 패턴)."""
        mock_ipc = AsyncMock(side_effect=RuntimeError("ipc boom"))
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "allocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 1, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "Error:" in result.stderr or "ipc boom" in result.stderr

    def test_ipc_success_false_exits_nonzero_text(self, runner: CliRunner) -> None:
        """valid amount + IPC success=False → exit 1 + fmt.error stderr (text)."""
        mock_ipc = AsyncMock(return_value={"success": False})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "allocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 1, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "예산 할당 실패" in result.stderr

    def test_ipc_success_false_exits_nonzero_json(self, runner: CliRunner) -> None:
        """``--format json`` 모드 IPC success=False → exit 1 + JSON error envelope.

        ``fmt.error``는 JSON 모드에서 ``status=error`` envelope을 stdout에
        ``click.echo``하므로 stdout에서 단정한다.
        """
        mock_ipc = AsyncMock(return_value={"success": False})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "1000",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "예산 할당 실패" in payload["message"]


# ── treasury deallocate ─────────────────────────────────


class TestDeallocateAmountIngress:
    """``ante treasury deallocate <bot> <amount> --account <acc>`` ingress 매트릭스."""

    @pytest.mark.parametrize(("value", "keyword"), _CALLBACK_INVALID_AMOUNTS)
    def test_text_mode_rejects_invalid(
        self, runner: CliRunner, value: str, keyword: str
    ) -> None:
        result = runner.invoke(cli, _deallocate_argv(value))
        _assert_invalid_amount_rejected(result, value, keyword)

    @pytest.mark.parametrize(("value", "keyword"), _CALLBACK_INVALID_AMOUNTS)
    def test_json_mode_rejects_invalid(
        self, runner: CliRunner, value: str, keyword: str
    ) -> None:
        result = runner.invoke(cli, _deallocate_argv(value, json_mode=True))
        _assert_invalid_amount_rejected(result, value, keyword)


class TestDeallocateIPCExitCode:
    """valid amount + IPC 경로 exit code 정합 (#1515 패턴)."""

    def test_valid_success_exits_zero(self, runner: CliRunner) -> None:
        mock_ipc = AsyncMock(return_value={"success": True})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "deallocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 0, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        mock_ipc.assert_awaited_once()

    def test_ipc_exception_exits_nonzero(self, runner: CliRunner) -> None:
        mock_ipc = AsyncMock(side_effect=RuntimeError("ipc boom"))
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "deallocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 1, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "Error:" in result.stderr or "ipc boom" in result.stderr

    def test_ipc_success_false_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_ipc = AsyncMock(return_value={"success": False})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                ["treasury", "deallocate", "bot-1", "1000", "--account", "acc-1"],
            )

        assert result.exit_code == 1, (
            f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "예산 회수 실패" in result.stderr

    def test_ipc_success_false_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_ipc = AsyncMock(return_value={"success": False})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", mock_ipc):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "deallocate",
                    "bot-1",
                    "1000",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "예산 회수 실패" in payload["message"]
