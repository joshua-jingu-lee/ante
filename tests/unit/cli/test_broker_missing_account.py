"""``ante broker {balance,positions}`` missing-account hang 회귀 (#1535).

배경:
    ``ante --format json broker balance --account oracle-missing-account`` 호출이
    stdout 으로 error JSON envelope 를 출력하지만 프로세스가 ~10초 동안 종료되지
    않아 ``subprocess.run(..., timeout=...)`` 호출자가 timeout (returncode 124)
    으로 관찰하는 결함이 있었다.

    원인은 두 가지다:

    1. ``src/ante/cli/commands/broker.py`` 의 ``_get_broker(account_id)`` 가
       ``account_service.get_broker(...)`` 또는 ``adapter.connect()`` 에서 raise
       될 때 ``db.close()`` 를 호출하지 않아 ``aiosqlite`` 백그라운드 스레드가
       살아남고, ``asyncio.run`` 종료 후에도 인터프리터 종료를 차단했다.
    2. ``balance``/``positions`` 의 except 분기가 ``return`` 으로 종료해 exit
       code 가 0 으로 남았다. 자동화 호출자는 process exit code 를 1차 신호로
       사용하므로 stdout JSON 이 ``status: error`` 여도 success 로 오인되었다.

    본 회귀 테스트는 두 결함을 함께 닫는다:

    - ``_get_broker`` 단위 테스트: ``account_service.get_broker`` raise 시
      ``db.close()`` 가 정확히 한 번 호출되고 예외가 전파됨을 확인.
    - ``balance``/``positions`` × {json,text} × CliRunner 4건: missing account
      입력에서 exit code 가 1 이고 envelope/stderr 메시지가 ``AccountNotFoundError``
      포맷("계좌 '<id>'를 찾을 수 없습니다.") 으로 노출됨을 확인.
    - subprocess hang 회귀 1건: ``-m ante --format json broker balance --account
      missing`` 이 timeout 없이 종료하고 stdout 에 JSON envelope 를 남기는지를
      mock 환경에서 검증. CI 시간 영향을 최소화하기 위해 timeout=5 로 짧게 잡는다.
    - status / reconcile missing-account exit code: #1535 에서 follow-up scope
      으로 남겼던 결함을 follow-up(#1556) 이 닫는다. ``status``/``reconcile``
      (without ``--fix``) × {json,text} 가 missing account 에서 exit 1 +
      ``{"status":"error","code":"ACCOUNT_NOT_FOUND",...}`` envelope 로 종료
      하고, ``status`` 의 **유효 계좌 disconnected/unhealthy 는 exit 0 +
      ``{connected:false, healthy:false}`` envelope** 를 유지함(contract-drift
      회귀 가드)을 ``TestStatusAndReconcileFollowupScope`` 에서 검증한다.

SSOT 참조:
    - ``src/ante/cli/commands/broker.py`` (``_get_broker``, ``balance``,
      ``positions`` 의 except 분기).
    - ``src/ante/account/service.py:461`` (``AccountNotFoundError`` 메시지 포맷).
    - ``src/ante/cli/formatter.py`` (``OutputFormatter.error`` 스키마).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.account.errors import AccountNotFoundError
from ante.cli.commands.broker import _get_broker
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MISSING_ACCOUNT_ID = "oracle-missing-account"
_NOT_FOUND_MESSAGE = f"계좌 '{_MISSING_ACCOUNT_ID}'를 찾을 수 없습니다."


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

    JSON envelope 와 stderr 메시지를 분리 검증하기 위해 ``mix_stderr=False`` 로
    구성한다.
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
    """stdout 첫 JSON dict 라인을 파싱한다."""
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise AssertionError(f"stdout 에서 JSON dict 를 찾지 못함: {stdout!r}")


def _build_ipc_unavailable_mock() -> AsyncMock:
    """``_ipc_broker_command`` 를 mock 해 IPC 미가용을 시뮬레이트.

    ``balance``/``positions`` 명령은 IPC 호출이 ``click.ClickException`` 을 raise
    하면 직접 연결 폴백 분기로 들어간다. 이 mock 은 그 분기를 강제한다.
    """
    return AsyncMock(side_effect=click.ClickException("서버가 실행 중이 아닙니다."))


def _patch_account_service_not_found() -> tuple[MagicMock, AsyncMock]:
    """``_create_account_service`` 를 mock 해 missing account 상태를 만든다.

    Returns:
        (mock_db, mock_get_broker) — mock_db 는 ``close()`` 호출 검증용,
        mock_get_broker 는 ``AccountNotFoundError`` raise 동작 검증용.
    """
    mock_db = MagicMock()
    mock_db.close = AsyncMock()
    mock_account_service = MagicMock()
    mock_account_service.get_broker = AsyncMock(
        side_effect=AccountNotFoundError(_NOT_FOUND_MESSAGE)
    )
    return mock_db, mock_account_service


# ── _get_broker 단위 테스트 (lifecycle 회귀) ────────────────────────────────


class TestGetBrokerClosesDbOnError:
    """``_get_broker`` 가 raise 경로에서 ``db.close()`` 를 보장하는지 검증."""

    @pytest.mark.asyncio
    async def test_account_not_found_closes_db_and_propagates(self) -> None:
        """``AccountService.get_broker`` 가 ``AccountNotFoundError`` 를 raise
        하면 ``_get_broker`` 는 (1) DB 핸들을 close 하고 (2) 동일 예외를 그대로
        전파해야 한다. close 누락은 aiosqlite 스레드 누수로 subprocess hang 을
        유발한다 (#1535)."""
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with patch(
            "ante.cli.commands.broker._create_account_service",
            side_effect=_fake_create_service,
        ):
            with pytest.raises(AccountNotFoundError) as exc_info:
                await _get_broker(_MISSING_ACCOUNT_ID)

        assert _NOT_FOUND_MESSAGE in str(exc_info.value)
        mock_db.close.assert_awaited_once()
        mock_account_service.get_broker.assert_awaited_once_with(_MISSING_ACCOUNT_ID)

    @pytest.mark.asyncio
    async def test_adapter_connect_failure_closes_db(self) -> None:
        """``adapter.connect()`` 가 raise 해도 ``db.close()`` 가 호출되어야 한다.

        ``get_broker`` 가 정상 반환한 뒤 adapter.connect() 에서 raise 되는
        경로(예: 자격증명 오류)도 같은 lifecycle 결함을 갖는다. 본 fix 는
        try/except 가 두 호출을 모두 감싸므로 이 경로 역시 닫는다.
        """
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_adapter = MagicMock()
        mock_adapter.connect = AsyncMock(side_effect=RuntimeError("connect failed"))
        mock_account_service = MagicMock()
        mock_account_service.get_broker = AsyncMock(return_value=mock_adapter)

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with patch(
            "ante.cli.commands.broker._create_account_service",
            side_effect=_fake_create_service,
        ):
            with pytest.raises(RuntimeError, match="connect failed"):
                await _get_broker(_MISSING_ACCOUNT_ID)

        mock_db.close.assert_awaited_once()


# ── balance 명령 exit code + 메시지 회귀 ────────────────────────────────────


class TestBrokerBalanceMissingAccount:
    """``broker balance --account <missing>`` 가 exit 1 로 끝나고 메시지가
    노출됨을 검증."""

    def _invoke_balance(
        self,
        runner: CliRunner,
        *,
        fmt: str,
    ) -> object:
        """공통 invoke: IPC 미가용 + AccountService missing 상태를 mock 한 뒤
        ``broker balance`` 를 호출한다."""
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with (
            patch(
                "ante.cli.commands.broker._ipc_broker_command",
                _build_ipc_unavailable_mock(),
            ),
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            return runner.invoke(
                cli,
                [
                    "--format",
                    fmt,
                    "broker",
                    "balance",
                    "--account",
                    _MISSING_ACCOUNT_ID,
                ],
            )

    def test_balance_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout error envelope + exit 1."""
        result = self._invoke_balance(runner, fmt="json")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload
        # text 메시지가 stderr 로 동시에 새지 않아야 한다.
        assert _NOT_FOUND_MESSAGE not in result.stderr, result.stderr

    def test_balance_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: ...`` + exit 1."""
        result = self._invoke_balance(runner, fmt="text")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # text 모드: stdout 에 JSON 이 새지 않아야 한다.
        assert result.stdout.strip() == "", result.stdout
        assert f"Error: {_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr


# ── positions 명령 exit code + 메시지 회귀 ──────────────────────────────────


class TestBrokerPositionsMissingAccount:
    """``broker positions --account <missing>`` 가 exit 1 로 끝나고 메시지가
    노출됨을 검증."""

    def _invoke_positions(
        self,
        runner: CliRunner,
        *,
        fmt: str,
    ) -> object:
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with (
            patch(
                "ante.cli.commands.broker._ipc_broker_command",
                _build_ipc_unavailable_mock(),
            ),
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            return runner.invoke(
                cli,
                [
                    "--format",
                    fmt,
                    "broker",
                    "positions",
                    "--account",
                    _MISSING_ACCOUNT_ID,
                ],
            )

    def test_positions_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """JSON 모드: stdout error envelope + exit 1."""
        result = self._invoke_positions(runner, fmt="json")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload
        assert _NOT_FOUND_MESSAGE not in result.stderr, result.stderr

    def test_positions_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """text 모드: stderr ``Error: ...`` + exit 1."""
        result = self._invoke_positions(runner, fmt="text")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip() == "", result.stdout
        assert f"Error: {_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr


# ── status / reconcile missing-account exit code 회귀 (#1556) ───────────────


class TestStatusAndReconcileFollowupScope:
    """status/reconcile 의 missing-account exit code 정렬 follow-up(#1556) 완료.

    #1535 가 ``balance``/``positions`` 의 missing-account exit code 와
    ``_get_broker`` lifecycle 만 닫고, ``status``/``reconcile`` 는 별도
    follow-up scope 로 남겼던 결함을 본 follow-up(#1556) 이 닫는다.

    - ``status`` 는 ``_get_broker`` 가 ``AccountNotFoundError`` 를 raise 하면
      내부 ``except AccountNotFoundError: raise`` 로 전파하고 호출부가
      ``fmt.error(..., code="ACCOUNT_NOT_FOUND")`` + ``SystemExit(1)`` 으로
      종료한다. **유효 계좌의 disconnect/unhealthy 는 기존 계약(exit 0 +
      ``{connected:false, healthy:false}`` envelope)을 그대로 유지**한다
      (contract-drift 회귀 방지).
    - ``reconcile`` (without ``--fix``) 의 오프라인 폴백 경로는
      missing-account 에서 exit 1 + ``{"status":"error",...}`` envelope 로
      종료한다. ``reconcile --fix`` 경로는 본 이슈 Non-Goal 이므로 다루지
      않는다.
    """

    def _invoke_status(
        self,
        runner: CliRunner,
        *,
        fmt: str,
    ) -> object:
        """공통 invoke: IPC 미가용 + AccountService missing 상태를 mock 한 뒤
        ``broker status`` 를 호출한다."""
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with (
            patch(
                "ante.cli.commands.broker._ipc_broker_command",
                _build_ipc_unavailable_mock(),
            ),
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            return runner.invoke(
                cli,
                [
                    "--format",
                    fmt,
                    "broker",
                    "status",
                    "--account",
                    _MISSING_ACCOUNT_ID,
                ],
            )

    def _invoke_reconcile(
        self,
        runner: CliRunner,
        *,
        fmt: str,
    ) -> object:
        """공통 invoke: IPC 미가용 + AccountService missing 상태를 mock 한 뒤
        ``broker reconcile`` (without ``--fix``) 을 호출한다."""
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        # ``broker reconcile`` (without ``--fix``) 은 ``_ipc_broker_command`` 가 아니라
        # ``_run_ipc_reconcile`` 안의 local import ``from ante.cli.commands.ipc_helpers
        # import ipc_send`` 로 ``ipc_send`` 를 직접 호출한다. local import 는 호출
        # 시점에 ``ante.cli.commands.ipc_helpers`` 모듈 속성을 resolve 하므로, 그 모듈의
        # ``ipc_send`` 를 패치해야 reconcile 경로가 결정적으로
        # ``except click.ClickException`` → 오프라인 폴백 → ``AccountNotFoundError``
        # → exit 1 을 탄다 (#1556).
        with (
            patch(
                "ante.cli.commands.ipc_helpers.ipc_send",
                AsyncMock(
                    side_effect=click.ClickException("서버가 실행 중이 아닙니다.")
                ),
            ),
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            return runner.invoke(
                cli,
                [
                    "--format",
                    fmt,
                    "broker",
                    "reconcile",
                    "--account",
                    _MISSING_ACCOUNT_ID,
                ],
            )

    def test_status_missing_account_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """status JSON 모드: missing account 는 ``ACCOUNT_NOT_FOUND`` envelope
        + exit 1 (#1556)."""
        result = self._invoke_status(runner, fmt="json")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "ACCOUNT_NOT_FOUND", payload
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload
        assert _NOT_FOUND_MESSAGE not in result.stderr, result.stderr

    def test_status_missing_account_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """status text 모드: stderr ``Error: ...`` + exit 1 (#1556)."""
        result = self._invoke_status(runner, fmt="text")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip() == "", result.stdout
        assert f"Error: {_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr

    def test_reconcile_missing_account_json_mode_emits_envelope_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """reconcile (without --fix) JSON 모드: missing account 는 error
        envelope + exit 1 (#1556)."""
        result = self._invoke_reconcile(runner, fmt="json")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "ACCOUNT_NOT_FOUND", payload
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload
        assert _NOT_FOUND_MESSAGE not in result.stderr, result.stderr

    def test_reconcile_missing_account_text_mode_emits_stderr_and_exits_1(
        self, runner: CliRunner
    ) -> None:
        """reconcile (without --fix) text 모드: stderr ``Error: ...`` + exit 1
        (#1556)."""
        result = self._invoke_reconcile(runner, fmt="text")

        assert result.exit_code == 1, (
            f"expected exit 1, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip() == "", result.stdout
        assert f"Error: {_NOT_FOUND_MESSAGE}" in result.stderr, result.stderr

    def test_status_valid_account_disconnected_keeps_exit_0_envelope(
        self, runner: CliRunner
    ) -> None:
        """contract-drift 회귀 방지: **유효 계좌**가 disconnect/unhealthy 인
        경우는 기존 계약대로 exit 0 + ``{connected:false, healthy:false}``
        envelope 를 유지해야 한다. ``AccountNotFoundError`` 만 exit 1 로
        분기되므로, generic 연결 실패는 swallow 되는 것이 정상이다 (#1556)."""
        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_adapter = MagicMock()
        # 유효 계좌이나 연결/헬스 체크 실패 (예: 자격증명/네트워크 오류).
        mock_adapter.connect = AsyncMock(
            side_effect=RuntimeError("broker connection refused")
        )
        mock_account_service = MagicMock()
        mock_account_service.get_broker = AsyncMock(return_value=mock_adapter)

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        with (
            patch(
                "ante.cli.commands.broker._ipc_broker_command",
                _build_ipc_unavailable_mock(),
            ),
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "status",
                    "--account",
                    "oracle-valid-account",
                ],
            )

        assert result.exit_code == 0, (
            f"expected exit 0 (valid-account disconnected contract), "
            f"got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # status 정상 계약은 ``fmt.output`` 으로 indent=2 멀티라인 JSON 을
        # 출력하므로(에러 envelope 의 한 줄 형식이 아님), stdout 전체를 파싱한다.
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict), payload
        assert payload["connected"] is False, payload
        assert payload["healthy"] is False, payload
        assert "broker connection refused" in str(payload["error"]), payload


# ── #1636 / #1623 Split C: invalid account_id ingress → VALIDATION_ERROR ────


class TestBrokerInvalidAccountIdIngress:
    """``broker {status,balance,positions,reconcile}`` 의 invalid ``account_id``
    (``default`` 예약어 / ``bad_id`` 형식 위반 / ``""`` 빈 문자열)가 IPC 호출 /
    ``_get_broker`` fallback **이전**에 ``VALIDATION_ERROR`` envelope + exit≠0
    으로 거부됨을 검증 (#1636 / #1623 Split C).

    회귀 모델:
        이전에는 4 cmd가 bare ``require_account_id(account_id, ...)`` 를 호출했고,
        그것이 raise하는 ``InvalidAccountIdError`` 는 non-Click ``AccountError``
        라 기존 ``except click.ClickException`` fallback이 잡지 못해 **traceback**
        (#1623 ``broker_balance_default``) 으로 누출됐다. #1636이 #1634
        ``reject_invalid_account_id`` helper로 교체해 그 예외를
        ``fmt.error(code="VALIDATION_ERROR")`` + ``SystemExit(1)`` 로 변환한다.

    검증:
        - 4 cmd × {default, bad_id, ""} × {json, text} → exit≠0
        - JSON: ``{"status":"error","code":"VALIDATION_ERROR",...}``
        - traceback 부재 (``result.exception`` 이 ``SystemExit`` 만)
        - IPC / ``_create_account_service`` 가 **호출되지 않음** (ingress 차단)
    """

    _INVALID_IDS = ["default", "bad id!", ""]

    @pytest.fixture
    def _ipc_spy(self):  # noqa: ANN202
        """IPC / account-service mock — invalid ingress면 호출되면 안 된다."""
        ipc_mock = AsyncMock(
            side_effect=AssertionError(
                "invalid account_id가 IPC 호출까지 도달했다 (ingress 차단 실패)"
            )
        )
        create_mock = AsyncMock(
            side_effect=AssertionError(
                "invalid account_id가 _create_account_service까지 도달했다"
            )
        )
        ipc_send_mock = AsyncMock(
            side_effect=AssertionError(
                "invalid account_id가 ipc_send까지 도달했다 (reconcile ingress)"
            )
        )
        return ipc_mock, create_mock, ipc_send_mock

    def _invoke(
        self,
        runner: CliRunner,
        _ipc_spy,  # noqa: ANN001
        *,
        cmd: str,
        account_id: str,
        fmt: str,
    ) -> object:
        ipc_mock, create_mock, ipc_send_mock = _ipc_spy
        with (
            patch("ante.cli.commands.broker._ipc_broker_command", ipc_mock),
            patch("ante.cli.commands.broker._create_account_service", create_mock),
            patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send_mock),
        ):
            return runner.invoke(
                cli,
                ["--format", fmt, "broker", cmd, "--account", account_id],
            )

    @pytest.mark.parametrize("cmd", ["status", "balance", "positions", "reconcile"])
    @pytest.mark.parametrize("account_id", _INVALID_IDS)
    def test_invalid_account_id_json_emits_validation_error_envelope(
        self,
        runner: CliRunner,
        _ipc_spy,  # noqa: ANN001
        cmd: str,
        account_id: str,
    ) -> None:
        """JSON 모드: invalid account_id → exit≠0 +
        ``code=VALIDATION_ERROR`` envelope + traceback 부재."""
        result = self._invoke(
            runner, _ipc_spy, cmd=cmd, account_id=account_id, fmt="json"
        )

        assert result.exit_code != 0, (
            f"[{cmd} --account {account_id!r}] expected exit≠0, "
            f"got {result.exit_code}\nstdout={result.stdout!r}"
        )
        # traceback 부재: 예외가 있다면 SystemExit 만 허용.
        if result.exception is not None:
            assert isinstance(result.exception, SystemExit), (
                f"[{cmd} --account {account_id!r}] 비-SystemExit 예외/traceback: "
                f"{result.exception!r}"
            )
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "VALIDATION_ERROR", payload

    @pytest.mark.parametrize("cmd", ["status", "balance", "positions", "reconcile"])
    @pytest.mark.parametrize("account_id", _INVALID_IDS)
    def test_invalid_account_id_text_emits_stderr_and_nonzero_exit(
        self,
        runner: CliRunner,
        _ipc_spy,  # noqa: ANN001
        cmd: str,
        account_id: str,
    ) -> None:
        """text 모드: invalid account_id → exit≠0 + stderr ``Error: ...`` +
        stdout JSON 누출 없음 + traceback 부재."""
        result = self._invoke(
            runner, _ipc_spy, cmd=cmd, account_id=account_id, fmt="text"
        )

        assert result.exit_code != 0, (
            f"[{cmd} --account {account_id!r}] expected exit≠0, "
            f"got {result.exit_code}\nstderr={result.stderr!r}"
        )
        if result.exception is not None:
            assert isinstance(result.exception, SystemExit), (
                f"[{cmd} --account {account_id!r}] 비-SystemExit 예외/traceback: "
                f"{result.exception!r}"
            )
        assert result.stdout.strip() == "", result.stdout
        assert "Error:" in result.stderr, result.stderr


# ── #1636: valid-absent per-command narrow (Codex r1 [medium]) ──────────────


class TestBrokerValidAbsentPerCommandNarrow:
    """Codex r1 [medium] narrow: helper swap 후 **valid-but-nonexistent**
    account_id 의 기존 동작이 보존되는지 per-command 로 검증 (#1636).

    ``reject_invalid_account_id`` helper는 ``require_account_id`` 계약을 그대로
    재사용하므로 valid 패턴(``oracle-missing-account``)은 거부하지 않는다.
    따라서 valid-but-nonexistent account_id 는 helper를 통과해 기존
    not-found 경로로 흐른다:

    - ``broker status`` = 기존 ``ACCOUNT_NOT_FOUND`` envelope 보존
    - ``broker balance``/``positions``/``reconcile`` = ``VALIDATION_ERROR``
      **오분류 아님** + 기존 동작 불변 (generic ``fmt.error(str(e))`` 등 —
      ACCOUNT_NOT_FOUND 강제·추가 금지; balance/positions parity는 후속 후보).

    이미 위 ``TestBrokerBalanceMissingAccount``/``TestBrokerPositionsMissingAccount``/
    ``TestStatusAndReconcileFollowupScope`` 가 missing-account exit 1 + 메시지를
    검증한다. 본 클래스는 helper swap이 그 경로에 **VALIDATION_ERROR 오분류를
    주입하지 않음**을 추가로 못박는다.
    """

    def _invoke(
        self,
        runner: CliRunner,
        *,
        cmd: str,
    ) -> object:
        mock_db, mock_account_service = _patch_account_service_not_found()

        async def _fake_create_service():  # noqa: ANN202
            return mock_account_service, mock_db

        if cmd == "reconcile":
            ipc_patch = patch(
                "ante.cli.commands.ipc_helpers.ipc_send",
                AsyncMock(
                    side_effect=click.ClickException("서버가 실행 중이 아닙니다.")
                ),
            )
        else:
            ipc_patch = patch(
                "ante.cli.commands.broker._ipc_broker_command",
                _build_ipc_unavailable_mock(),
            )

        with (
            ipc_patch,
            patch(
                "ante.cli.commands.broker._create_account_service",
                side_effect=_fake_create_service,
            ),
        ):
            return runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    cmd,
                    "--account",
                    _MISSING_ACCOUNT_ID,
                ],
            )

    def test_status_valid_absent_keeps_account_not_found(
        self, runner: CliRunner
    ) -> None:
        """``broker status`` valid-absent = ``ACCOUNT_NOT_FOUND`` 보존
        (VALIDATION_ERROR 오분류 아님)."""
        result = self._invoke(runner, cmd="status")

        assert result.exit_code == 1, result.stdout
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "ACCOUNT_NOT_FOUND", payload
        assert payload["code"] != "VALIDATION_ERROR", payload

    @pytest.mark.parametrize("cmd", ["balance", "positions", "reconcile"])
    def test_balance_positions_reconcile_valid_absent_not_validation_error(
        self, runner: CliRunner, cmd: str
    ) -> None:
        """``broker balance``/``positions``/``reconcile`` valid-absent =
        ``VALIDATION_ERROR`` **오분류 아님** + 기존 동작 불변. helper가
        valid 패턴을 거부하지 않아 not-found 경로가 유지됨을 가드한다
        (ACCOUNT_NOT_FOUND 강제 안 함 — balance/positions parity는 후속)."""
        result = self._invoke(runner, cmd=cmd)

        assert result.exit_code == 1, result.stdout
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        # helper swap이 valid-absent를 VALIDATION_ERROR로 오분류하면 안 된다.
        assert payload["code"] != "VALIDATION_ERROR", payload
        # 기존 not-found 메시지가 그대로 노출 (동작 불변).
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload


# ── subprocess hang 회귀 (실제 프로세스 종료 확인) ──────────────────────────


class TestBrokerBalanceSubprocessNoHang:
    """``python -m ante ... broker balance --account missing`` 이 timeout 없이
    종료함을 실제 subprocess 로 확인한다.

    회귀 모델:
        - mock 환경에서 ``AccountService.get_broker`` 가 ``AccountNotFoundError``
          를 raise 하고, ``_get_broker`` 가 db.close() 를 호출하지 않으면
          aiosqlite 백그라운드 스레드가 살아남아 인터프리터 종료가 ~10초간
          지연된다.
        - 본 PR fix 후에는 5초 timeout 안에 종료되고 returncode 1 + stdout JSON
          envelope 가 관찰되어야 한다.

    설계:
        - 실제 ``ante`` CLI 의존성(aiosqlite, config dir, member auth) 을 그대로
          타지 않도록, IPC 미가용을 강제하고 ``AccountService`` 를 stub 으로
          교체하는 짧은 부트스트랩 스크립트를 ``python -c`` 로 실행한다.
        - 시간 영향을 최소화하기 위해 ``timeout=5`` 로 짧게 잡고 ``@slow`` 마커
          로 별도 풀에 둔다 (CI 기본 풀에서도 5초 안에는 종료 가능).
    """

    def test_missing_account_terminates_within_timeout(self, tmp_path: Path) -> None:
        """missing account 호출이 5초 안에 종료되고 returncode 1 + stdout JSON
        envelope 를 남겨야 한다 (hang 회귀)."""
        bootstrap = textwrap.dedent(
            """
            import sys
            from unittest.mock import AsyncMock, MagicMock, patch

            import click

            from ante.account.errors import AccountNotFoundError
            from ante.member.models import Member, MemberRole, MemberType

            _NOT_FOUND = "계좌 'oracle-missing-account'를 찾을 수 없습니다."

            mock_db = MagicMock()
            mock_db.close = AsyncMock()
            mock_service = MagicMock()
            mock_service.get_broker = AsyncMock(
                side_effect=AccountNotFoundError(_NOT_FOUND)
            )

            async def _fake_create_service():
                return mock_service, mock_db

            master = Member(
                member_id="test-master",
                type=MemberType.HUMAN,
                role=MemberRole.MASTER,
                org="default",
                name="Test Master",
                status="active",
                scopes=[],
            )

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = master

            ipc_mock = AsyncMock(
                side_effect=click.ClickException("서버 미실행")
            )

            with (
                patch(
                    "ante.cli.main.authenticate_member",
                    side_effect=_set_member,
                ),
                patch(
                    "ante.cli.commands.broker._ipc_broker_command",
                    ipc_mock,
                ),
                patch(
                    "ante.cli.commands.broker._create_account_service",
                    side_effect=_fake_create_service,
                ),
            ):
                from ante.cli.main import cli

                cli.main(
                    args=[
                        "--format",
                        "json",
                        "broker",
                        "balance",
                        "--account",
                        "oracle-missing-account",
                    ],
                    standalone_mode=True,
                )
            """
        ).strip()

        env = os.environ.copy()
        env["ANTE_CONFIG_DIR"] = str(tmp_path)
        env["PYTHONUNBUFFERED"] = "1"

        try:
            completed = subprocess.run(
                [sys.executable, "-c", bootstrap],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            pytest.fail(
                "broker balance --account missing 이 5초 timeout 안에 종료되지 "
                "않았다. _get_broker 의 db.close() 누락으로 aiosqlite 스레드가 "
                "살아남는 hang 회귀 (#1535).\n"
                f"stdout (partial)={e.stdout!r}\nstderr (partial)={e.stderr!r}"
            )

        assert completed.returncode == 1, (
            f"expected returncode 1, got {completed.returncode}\n"
            f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}"
        )
        # stdout 에 JSON envelope 가 존재해야 한다.
        payload = _parse_json_line(completed.stdout)
        assert payload["status"] == "error", payload
        assert _NOT_FOUND_MESSAGE in str(payload["message"]), payload
