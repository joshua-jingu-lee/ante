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

Refs #2412 (범위 확장):
    ``broker order-history`` 신설과 함께 같은 ``_get_broker`` / IPC-우선 폴백
    구조를 공유하는 인접 회귀를 본 모듈이 이어서 lock 한다. 본 파일이 이미
    ``patch.object(broker_cmd, "_get_broker", ...)`` 로 폴백 어댑터를 주입하는
    유일한 선례이기 때문이다:

    - ``_ipc_broker_command`` 의 ``extra`` 파라미터가 ``None`` 일 때 기존
      호출자 3곳(status/balance/positions) payload 가 **바이트 동일**함
      (multi-consumer 회귀 락), 그리고 ``reconcile`` 은 이 helper 를
      경유하지 않음. 나아가 ``extra`` 가 검증된 ``account_id`` 를 **덮지
      못함**(병합 순서로 구조 보장).
    - ``order-history`` **text 모드 성공 출력** — known-limitation 헤더
      (결정 4 철회의 대체 완화조치) 와 빈 결과 문구 / ``fmt.table``.
    - CLI **직접 연결 폴백** 경로에서 ISO ``YYYY-MM-DD`` 가 어댑터 경계
      ``YYYYMMDD`` 로 변환됨 (IPC 핸들러를 거치지 않는 두 번째 변환 지점).
    - invalid ``account_id`` 가 IPC/``_get_broker`` 이전에 거부됨.
    - 폴백 트리거가 ``IPC_SERVER_NOT_RUNNING`` 단독임 (IPC_TIMEOUT /
      server-error 는 폴백 없이 surface).

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


# ── status 폴백 adapter.disconnect 대칭 (#2373) ─────────────────────────────


class TestStatusFallbackDisconnectsAdapter:
    """``broker status`` 직접 연결 폴백이 connect 성공 이후 ``adapter.disconnect()``
    를 수행해 sibling(balance/positions/reconcile)과 대칭으로 session 을 정리하는지
    검증한다 (#2373).

    회귀 모델:
        status 폴백 ``_run_status()`` 는 connect 성공 후 ``health_check()`` 만 하고
        ``finally`` 에서 ``db.close()`` 만 호출 — ``adapter.disconnect()`` 부재로
        KIS adapter 의 aiohttp session 이 프로세스 종료까지 잔존했다(``Unclosed
        client session`` 경고). #2368 은 connect **실패** 경로를, 본 이슈는
        connect **성공** 경로의 비대칭 누수를 닫는다.

    설계:
        ``_get_broker`` 를 직접 patch 해 ``disconnect = AsyncMock()`` 을 가진 mock
        adapter 를 반환하게 하고, IPC 우선 시도는 ``ClickException`` 으로 막아
        폴백 분기를 강제한다(``_patch_balance_fallback_raises`` 와 동형 하네스).
        성공 경로와 ``health_check`` 예외 경로 양쪽에서 ``disconnect()`` 가 정확히
        한 번 await 됨을 단언한다 — sibling 의 검증된 미러.
    """

    def _run_status_fallback(
        self,
        runner: CliRunner,
        *,
        health_check: AsyncMock,
    ) -> tuple[object, AsyncMock]:
        """IPC 미가용을 강제하고 ``_get_broker`` 를 mock adapter 로 patch 한 뒤
        ``broker status --account acc-1`` 을 호출한다.

        Returns:
            (CliRunner result, disconnect AsyncMock) — disconnect 호출 검증용.
        """
        import click

        from ante.broker.base import BrokerAdapter
        from ante.cli.commands import broker as broker_cmd

        async def _raise_click(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click.ClickException("server unavailable")

        mock_adapter = MagicMock(spec=BrokerAdapter)
        mock_adapter.is_connected = True
        mock_adapter.exchange = "KRX"
        mock_adapter.health_check = health_check
        mock_adapter.disconnect = AsyncMock(return_value=None)

        async def _fake_get_broker(account_id=None):  # noqa: ANN001, ANN202
            return mock_adapter, None

        with (
            patch.object(broker_cmd, "_ipc_broker_command", new=_raise_click),
            patch.object(broker_cmd, "_get_broker", new=_fake_get_broker),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "status",
                    "--account",
                    "acc-1",
                ],
            )
        return result, mock_adapter.disconnect

    def test_status_fallback_success_disconnects_adapter(
        self, runner: CliRunner
    ) -> None:
        """health_check 성공 경로: status 폴백이 ``adapter.disconnect()`` 를 정확히
        한 번 호출한다 (main RED — 현재 disconnect 미호출)."""
        result, disconnect = self._run_status_fallback(
            runner, health_check=AsyncMock(return_value=True)
        )

        assert result.exit_code == 0, (
            f"expected exit 0, got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        assert payload["connected"] is True, payload
        assert payload["healthy"] is True, payload
        disconnect.assert_awaited_once()

    def test_status_fallback_health_check_error_disconnects_adapter(
        self, runner: CliRunner
    ) -> None:
        """health_check 예외 경로: finally 가 disconnect 후 기존 ``except
        Exception`` 분기(``connected:False``)에 도달한다. disconnect 호출 +
        connected:False 변환이 모두 유지되어야 한다."""
        result, disconnect = self._run_status_fallback(
            runner,
            health_check=AsyncMock(side_effect=RuntimeError("health probe failed")),
        )

        assert result.exit_code == 0, (
            f"expected exit 0 (generic 실패 swallow 계약), got {result.exit_code}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        assert payload["connected"] is False, payload
        assert payload["healthy"] is False, payload
        assert "health probe failed" in str(payload["error"]), payload
        disconnect.assert_awaited_once()


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


# ── #2412: order-history 신설에 딸린 broker CLI 인접 회귀 ────────────────────


def _ipc_send_not_running() -> AsyncMock:
    """``ipc_send`` mock — ``IPC_SERVER_NOT_RUNNING`` 부착 ClickException."""
    exc = click.ClickException("서버가 실행 중이 아닙니다.")
    exc.ipc_error_code = "IPC_SERVER_NOT_RUNNING"  # type: ignore[attr-defined]
    exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
    return AsyncMock(side_effect=exc)


def _ipc_send_with_code(code: str, message: str) -> AsyncMock:
    """``ipc_send`` mock — 임의 IPC 코드가 부착된 ClickException."""
    exc = click.ClickException(f"{code}: {message}")
    exc.ipc_error_code = code  # type: ignore[attr-defined]
    exc.ipc_error_message = message  # type: ignore[attr-defined]
    return AsyncMock(side_effect=exc)


class TestIpcBrokerCommandExtraRegressionLock:
    """``_ipc_broker_command(extra=...)`` 확장의 multi-consumer 회귀 락 (#2412)."""

    @pytest.mark.parametrize(
        ("subcommand", "ipc_command"),
        [
            ("status", "broker.status"),
            ("balance", "broker.balance"),
            ("positions", "broker.positions"),
        ],
    )
    def test_existing_callers_payload_is_byte_identical(
        self, runner: CliRunner, subcommand: str, ipc_command: str
    ) -> None:
        """기존 호출자 3곳은 ``{"account_id": ...}`` 정확히 그대로 보낸다.

        ``extra`` 는 순수 additive 확장이므로 ``None`` (미지정) 일 때 payload
        가 종전과 **바이트 동일**해야 한다. 키가 하나라도 늘면 서버 handler
        의 args 계약이 조용히 바뀐다.
        """
        ipc_send = AsyncMock(return_value={})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send):
            runner.invoke(
                cli,
                ["--format", "json", "broker", subcommand, "--account", "acc-a"],
            )

        ipc_send.assert_awaited_once()
        call_args, call_kwargs = ipc_send.await_args
        assert call_args[0] == ipc_command
        assert call_args[1] == {"account_id": "acc-a"}, (
            f"{subcommand}: payload 가 종전과 다르다 — extra=None 은 순수 "
            f"additive 여야 한다. 실제: {call_args[1]!r}"
        )
        assert call_kwargs == {"actor": call_kwargs.get("actor")}

    def test_reconcile_does_not_go_through_helper(self, runner: CliRunner) -> None:
        """``reconcile`` 은 helper 비경유 — payload 에 ``fix`` 가 그대로 있다.

        ``_ipc_broker_command`` 통일은 스코프 크립이자 동작 변경이므로 하지
        않는다. 본 lock 이 그 경계를 명시한다.
        """
        ipc_send = AsyncMock(return_value={})
        helper = AsyncMock(return_value={})
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            patch("ante.cli.commands.broker._ipc_broker_command", helper),
        ):
            runner.invoke(
                cli,
                ["--format", "json", "broker", "reconcile", "--account", "acc-a"],
            )

        helper.assert_not_awaited()
        ipc_send.assert_awaited_once()
        call_args, _ = ipc_send.await_args
        assert call_args[0] == "broker.reconcile"
        assert call_args[1] == {"fix": False, "account_id": "acc-a"}

    def test_order_history_passes_iso_dates_through_extra(
        self, runner: CliRunner
    ) -> None:
        """``order-history`` 는 ISO 날짜를 ``extra`` 로 실어 보낸다.

        IPC 경계 위 어휘는 ISO 다 (변환은 서버 handler 가 어댑터 직전에
        수행). 미지정 옵션은 payload 에 키 자체를 넣지 않는다.
        """
        ipc_send = AsyncMock(return_value={"orders": []})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send):
            runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "order-history",
                    "--account",
                    "acc-a",
                    "--from",
                    "2026-07-01",
                ],
            )

        ipc_send.assert_awaited_once()
        call_args, _ = ipc_send.await_args
        assert call_args[0] == "broker.order_history"
        assert call_args[1] == {"account_id": "acc-a", "from_date": "2026-07-01"}

    async def test_extra_cannot_override_validated_account_id(self) -> None:
        """🔴 ``extra`` 는 검증된 ``account_id`` 를 덮지 못한다.

        docstring 이 주장하는 "순수 additive" 불변을 **dict 병합 순서**로
        구조 보장한다. ``args = {"account_id": ...}; args.update(extra)``
        순서였다면 호출자가 ``account_id`` 키를 넣는 순간 CLI ingress
        검증(``reject_invalid_account_id``)을 통과한 값이 조용히 덮여
        미검증 값이 IPC 로 나간다 — 현재 호출자 3+1 곳은 안전하지만 구조가
        보장하지 않으면 다음 호출자가 재개방한다.
        """
        from ante.cli.commands.broker import _ipc_broker_command

        ipc_send = AsyncMock(return_value={})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send):
            await _ipc_broker_command(
                "broker.order_history",
                "acc-validated",
                "member-1",
                extra={"account_id": "acc-spoofed", "from_date": "2026-07-01"},
            )

        ipc_send.assert_awaited_once()
        call_args, call_kwargs = ipc_send.await_args
        assert call_args[1]["account_id"] == "acc-validated", (
            f"extra 가 검증된 account_id 를 덮었다: {call_args[1]!r}"
        )
        # additive 부분은 그대로 살아있어야 한다 (덮어쓰기 방지가 extra 자체를
        # 무시하는 것으로 퇴화하지 않도록 함께 lock).
        assert call_args[1]["from_date"] == "2026-07-01", call_args[1]
        assert call_kwargs == {"actor": "member-1"}


class TestOrderHistoryFallbackDateConversion:
    """CLI 직접 연결 폴백 경로의 ISO→YYYYMMDD 변환 (#2412 결정 2)."""

    @staticmethod
    def _invoke_fallback(
        runner: CliRunner,
        *,
        extra_args: list[str],
        orders: list[dict] | None = None,
    ) -> tuple[object, AsyncMock]:
        """IPC 미기동을 강제하고 ``_get_broker`` 를 mock adapter 로 주입한다."""
        from ante.broker.base import BrokerAdapter
        from ante.cli.commands import broker as broker_cmd

        mock_adapter = MagicMock(spec=BrokerAdapter)
        mock_adapter.get_order_history = AsyncMock(
            return_value=orders if orders is not None else []
        )
        mock_adapter.disconnect = AsyncMock(return_value=None)

        async def _fake_get_broker(account_id=None):  # noqa: ANN001, ANN202
            return mock_adapter, None

        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", _ipc_send_not_running()),
            patch.object(broker_cmd, "_get_broker", new=_fake_get_broker),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "order-history",
                    "--account",
                    "acc-a",
                    *extra_args,
                ],
            )
        return result, mock_adapter.get_order_history

    def test_fallback_converts_iso_to_compact_date(self, runner: CliRunner) -> None:
        """🔴 폴백 경로도 어댑터에 ``YYYYMMDD`` 를 넘긴다.

        폴백은 IPC 핸들러를 거치지 않으므로, 변환이 IPC 쪽에만 있으면 ISO 가
        그대로 어댑터로 샌다. 그 경우 3개월 경계 판정(문자열 사전순 비교)이
        무조건 before 를 고르고 malformed 값이 KIS 로 전송되는데 **예외도
        경고도 없다**. 어댑터가 실제로 받은 값을 직접 단언한다.
        """
        result, get_order_history = self._invoke_fallback(
            runner,
            extra_args=["--from", "2026-07-01", "--to", "2026-07-31"],
        )

        assert result.exit_code == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        get_order_history.assert_awaited_once_with("20260701", "20260731")
        args, _ = get_order_history.await_args
        for value in args:
            assert "-" not in value, (
                f"폴백 경로에서 ISO 문자열이 어댑터로 샜다: {value!r}"
            )

    def test_fallback_without_dates_passes_none(self, runner: CliRunner) -> None:
        """옵션 미지정은 ``None`` 그대로 — 어댑터 기본 구간 산출에 위임."""
        result, get_order_history = self._invoke_fallback(runner, extra_args=[])

        assert result.exit_code == 0, result.stdout
        get_order_history.assert_awaited_once_with(None, None)

    def test_fallback_empty_result_is_orders_only(self, runner: CliRunner) -> None:
        """폴백 빈 결과도 IPC 경로와 동일한 ``{"orders": []}`` shape.

        ``fmt.output`` 은 ``indent=2`` multi-line dump 라 line 단위
        ``_parse_json_line`` 대신 stdout 전체를 파싱한다.
        """
        result, _ = self._invoke_fallback(runner, extra_args=[])

        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout) == {"orders": []}


class TestOrderHistoryFallbackTrigger:
    """폴백 트리거는 ``IPC_SERVER_NOT_RUNNING`` 단독 (#2412 결정 5)."""

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            ("IPC_TIMEOUT", "서버 응답 시간 초과"),
            ("BROKER_RATE_LIMITED", "요청이 너무 많습니다"),
            ("BROKER_CIRCUIT_OPEN", "차단기가 열려 있습니다"),
            ("VALIDATION_ERROR", "계좌 ID가 올바르지 않습니다"),
        ],
    )
    def test_non_server_down_errors_surface_without_fallback(
        self, runner: CliRunner, code: str, message: str
    ) -> None:
        """server-error / timeout 은 직접 연결 폴백으로 은폐하지 않는다.

        형제 balance/positions 의 통짜 ``except click.ClickException`` 을
        따라하면 credentials / rate limit / circuit breaker 를 우회한다.
        """
        from ante.cli.commands import broker as broker_cmd

        get_broker = AsyncMock()
        with (
            patch(
                "ante.cli.commands.ipc_helpers.ipc_send",
                _ipc_send_with_code(code, message),
            ),
            patch.object(broker_cmd, "_get_broker", new=get_broker),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "order-history",
                    "--account",
                    "acc-a",
                ],
            )

        assert result.exit_code == 1, result.stdout
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == code, payload
        assert payload["message"] == message, payload
        get_broker.assert_not_awaited()


class TestOrderHistoryAccountIdValidation:
    """invalid ``account_id`` 는 IPC/``_get_broker`` 이전에 거부 (#2412)."""

    @pytest.mark.parametrize("bad_account", ["default", "bad id!", " "])
    def test_invalid_account_id_rejected_before_ipc(
        self, runner: CliRunner, bad_account: str
    ) -> None:
        from ante.cli.commands import broker as broker_cmd

        ipc_send = AsyncMock(return_value={"orders": []})
        get_broker = AsyncMock()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            patch.object(broker_cmd, "_get_broker", new=get_broker),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "order-history",
                    "--account",
                    bad_account,
                ],
            )

        assert result.exit_code == 1, result.stdout
        payload = _parse_json_line(result.stdout)
        assert payload["status"] == "error", payload
        assert payload["code"] == "VALIDATION_ERROR", payload
        ipc_send.assert_not_awaited()
        get_broker.assert_not_awaited()

    @pytest.mark.parametrize("bad_date", ["2026-13-01", "20260701", "2026-7-1"])
    def test_invalid_iso_rejected_by_click_callback(
        self, runner: CliRunner, bad_date: str
    ) -> None:
        """CLI ingress 의 invalid ISO 는 click 표준 경로에서 non-zero 종료."""
        ipc_send = AsyncMock(return_value={"orders": []})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "order-history",
                    "--account",
                    "acc-a",
                    "--from",
                    bad_date,
                ],
            )

        assert result.exit_code != 0, result.stdout
        ipc_send.assert_not_awaited()


class TestOrderHistoryTextOutput:
    """``order-history`` **text 모드 성공 출력** 경로 lock (#2412).

    신규 CLI 테스트가 전부 ``--format json`` 이라 text 분기(빈 결과 문구 /
    known-limitation 헤더 / ``fmt.table``)가 한 번도 실행되지 않았다.

    특히 known-limitation 헤더는 "교차 구간 fail-closed 거부"(결정 4) 를
    철회하면서 채택한 **대체 완화조치**다. 락이 없으면 향후 리팩터가 헤더를
    지워도 아무 테스트도 실패하지 않고, 사용자는 취소 주문이 ``pending`` 으로
    보이는 것을 경고 없이 사실로 받아들이게 된다.
    """

    # 헤더 문구의 wording 전체가 아니라 **의미 단위**를 단언한다. 줄바꿈/조사
    # 다듬기는 허용하되 경고 항목 자체가 사라지면 실패하도록 한다.
    LIMITATION_MARKERS = (
        "취소 주문도 pending",
        "체결가/주문가 혼합",
        "영업일",
    )
    EMPTY_MESSAGE = "주문/체결 이력 없음"

    @staticmethod
    def _invoke_text(runner: CliRunner, orders: list[dict]) -> object:
        """text 모드로 ``order-history`` 를 호출한다 (IPC 성공 응답 주입)."""
        ipc_send = AsyncMock(return_value={"orders": orders})
        with patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send):
            return runner.invoke(
                cli,
                [
                    "--format",
                    "text",
                    "broker",
                    "order-history",
                    "--account",
                    "acc-a",
                ],
            )

    def test_text_non_empty_prints_limitation_header_and_table(
        self, runner: CliRunner
    ) -> None:
        """🔴 비어있지 않은 결과: known-limitation 헤더 + 정규화 8키 테이블."""
        result = self._invoke_text(
            runner,
            [
                {
                    "order_id": "0000117057",
                    "symbol": "005930",
                    "side": "buy",
                    "quantity": 10.0,
                    "filled_quantity": 10.0,
                    "price": 70100.0,
                    "status": "filled",
                    "timestamp": "20260701",
                }
            ],
        )

        assert result.exit_code == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        for marker in self.LIMITATION_MARKERS:
            assert marker in result.stdout, (
                f"known-limitation 헤더에서 {marker!r} 가 사라졌다 — 결정 4"
                f"(교차 구간 fail-closed 거부) 철회의 대체 완화조치다. "
                f"stdout={result.stdout!r}"
            )
        # ``fmt.table`` 이 정규화 8키를 컬럼으로 출력한다.
        for column in (
            "order_id",
            "symbol",
            "side",
            "quantity",
            "filled_quantity",
            "price",
            "status",
            "timestamp",
        ):
            assert column in result.stdout, (
                f"text 테이블에 컬럼 {column!r} 가 없다. stdout={result.stdout!r}"
            )
        assert "0000117057" in result.stdout, result.stdout
        assert "005930" in result.stdout, result.stdout
        # text 모드는 JSON envelope 을 그대로 뱉지 않는다 (passthrough 는 json 전용).
        assert '"orders"' not in result.stdout, result.stdout

    def test_text_empty_prints_empty_message_without_header(
        self, runner: CliRunner
    ) -> None:
        """🔴 빈 결과: 전용 문구만 출력하고 헤더/테이블은 내지 않는다.

        빈 결과에 (no data) 테이블만 나오면 사람이 "조회 실패" 와 "이력 없음"
        을 구분할 수 없다. 반대로 헤더까지 붙으면 볼 행이 없는데 경고만
        읽히므로, empty 는 ``return`` 으로 조기 종료하는 것이 계약이다.
        """
        result = self._invoke_text(runner, [])

        assert result.exit_code == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert self.EMPTY_MESSAGE in result.stdout, result.stdout
        for marker in self.LIMITATION_MARKERS:
            assert marker not in result.stdout, (
                f"빈 결과에 known-limitation 헤더가 붙었다 ({marker!r}). "
                f"stdout={result.stdout!r}"
            )
        assert "order_id" not in result.stdout, result.stdout
        assert "(no data)" not in result.stdout, result.stdout
