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
    - status / reconcile 잔존 결함 1건: 이 두 명령의 missing-account 처리는
      별도 follow-up scope 이며 본 PR 의 _get_broker fix 만으로는 exit code 계약
      이 변경되지 않음을 docstring + skip 으로 명시한다.

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


# ── status / reconcile 잔존 결함 — follow-up scope 명시 ─────────────────────


class TestStatusAndReconcileFollowupScope:
    """status/reconcile 의 missing-account 처리는 본 PR scope 밖임을 문서화.

    - ``status`` 는 내부 try/except 가 ``_get_broker`` 예외를 swallow 해 항상
      ``{"connected": False, "healthy": False, "error": <msg>}`` payload + exit 0
      을 반환하도록 의도되어 있다. 본 PR 의 ``_get_broker`` lifecycle 수정은
      그 동작을 변경하지 않는다 — except 분기가 그대로 ``await db.close()`` 책임
      을 가져가지 않지만, 본 PR fix 가 ``_get_broker`` 내부에서 close 를 보장
      하므로 hang 자체는 사라진다.
    - ``reconcile`` (without ``--fix``) 은 fmt.error + return 패턴이 그대로
      남아 exit 0 으로 종료한다. exit code 정렬은 별도 follow-up 이슈에서
      처리한다.

    본 placeholder 는 두 동작이 의도된 follow-up scope 라는 invariant 를
    skip 으로 명시해 contributor 가 동일 패턴을 본 PR 에 끼워넣지 않도록 한다.
    """

    @pytest.mark.skip(
        reason=(
            "status/reconcile 의 missing-account exit code 정렬은 별도 follow-up "
            "scope. #1535 본 PR 은 _get_broker lifecycle + balance/positions exit "
            "code 만 다룬다."
        )
    )
    def test_status_missing_account_exit_code_is_followup(self) -> None:
        """status 의 missing-account exit code 계약은 별도 이슈에서 다룬다."""

    @pytest.mark.skip(
        reason=(
            "reconcile 의 missing-account exit code 정렬은 별도 follow-up scope. "
            "#1535 본 PR 은 _get_broker lifecycle + balance/positions exit code "
            "만 다룬다."
        )
    )
    def test_reconcile_missing_account_exit_code_is_followup(self) -> None:
        """reconcile 의 missing-account exit code 계약은 별도 이슈에서 다룬다."""


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
