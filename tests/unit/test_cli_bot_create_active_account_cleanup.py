"""``ante bot create`` aiosqlite cleanup hang 회귀 (#1799).

oracle A7 probe ``cli_bot_create_missing_required_account_contract`` 가
발견한 회귀 모델: ``--account`` 미지정 + active account count != 1 시
``_resolve_account_non_interactive`` 가 ``BOT_MISSING_REQUIRED_ACCOUNT``
envelope 을 정상 출력한 뒤 ``SystemExit(1)`` 을 raise 하지만,
``_create_services()`` 가 연 aiosqlite db 연결이 close 되지 않아
asyncio event loop 가 dangling 상태로 남고 CLI 프로세스가 종료되지 않은
채 외부 timeout (probe exit 124, wall-clock 8s) 으로만 죽는 hang 이었다.

#1799 fix: ``_list_accounts()`` 내부에 ``try/finally + await db.close()``
cleanup 을 추가 — ``bot_list`` (L107-122) / ``bot_info`` (L149-154) /
``account.py`` (#1722) 와 동형 패턴. resolver SystemExit 은
``_run(_list_accounts())`` 완료 후 (close 이후) 발생하므로 cleanup 이
항상 보장된다.

검증축:

1. active=0 → ``BOT_MISSING_REQUIRED_ACCOUNT`` envelope + ``db.close()`` 호출
2. active=2+ → 동형 + ``db.close()`` 호출 + ``ipc_send`` 미호출
3. active=1 → resolver 통과 → ``db.close()`` 호출 후 ``ipc_send`` 도달
"""

from __future__ import annotations

import json
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


@pytest.fixture
def runner() -> CliRunner:
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


def _build_create_services_mock(
    *,
    active_accounts: list,
) -> tuple[AsyncMock, MagicMock, AsyncMock]:
    """``_create_services`` mock + close 호출 spy 를 함께 반환.

    Returns: (create_services_async_fn, db_mock, account_service_mock)
    """
    db = MagicMock()
    db.close = AsyncMock()
    account_service = AsyncMock()
    account_service.list = AsyncMock(return_value=active_accounts)

    # #1857: ``bot._create_services`` 는 async context manager 로 변환됨.
    # fake factory 는 open_cli_db lifecycle 을 그대로 재현하기 위해 __aexit__
    # 시 ``db.close()`` 를 호출한다 (#1799 회귀 lock invariant 보존).
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _create_services_mock(*args, **kwargs):
        try:
            yield db, MagicMock(), MagicMock(), account_service
        finally:
            await db.close()

    return _create_services_mock, db, account_service


def _patch_ipc_send() -> tuple[object, AsyncMock]:
    spy = AsyncMock(return_value={"bot_id": "bot-x"})
    return patch("ante.cli.commands.ipc_helpers.ipc_send", new=spy), spy


def _make_active_account(account_id: str) -> MagicMock:
    acc = MagicMock()
    acc.account_id = account_id
    return acc


# ── 축 1: active=0 → BOT_MISSING_REQUIRED_ACCOUNT + db.close ────────────


class TestBotCreateActiveZeroCleanup:
    """active account 0 → envelope 정상 + db.close 호출 (hang 차단)."""

    def test_active_zero_envelope_and_db_close(self, runner: CliRunner) -> None:
        create_services_mock, db_mock, account_service = _build_create_services_mock(
            active_accounts=[]
        )
        ipc_patch, ipc_spy = _patch_ipc_send()

        with (
            ipc_patch,
            patch("ante.cli.commands.bot._create_services", new=create_services_mock),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                ],
            )
        # envelope code 종전 동작 보존 (#1799 핵심은 process termination).
        assert result.exit_code != 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["status"] == "error", payload
        assert payload["code"] == "BOT_MISSING_REQUIRED_ACCOUNT", payload
        # cleanup 보증: db.close 가 SystemExit 이전(=_run 완료 시점)에 호출됨.
        db_mock.close.assert_awaited_once()
        # resolver 단계에서 차단 → ipc_send 미호출.
        ipc_spy.assert_not_called()


# ── 축 2: active=2+ → 동형 + cleanup ─────────────────────────────────────


class TestBotCreateActiveMultipleCleanup:
    """active account 2+ → envelope 정상 + db.close 호출."""

    def test_active_multiple_envelope_and_db_close(self, runner: CliRunner) -> None:
        accounts = [
            _make_active_account("domestic"),
            _make_active_account("overseas"),
        ]
        create_services_mock, db_mock, _ = _build_create_services_mock(
            active_accounts=accounts
        )
        ipc_patch, ipc_spy = _patch_ipc_send()

        with (
            ipc_patch,
            patch("ante.cli.commands.bot._create_services", new=create_services_mock),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                ],
            )
        assert result.exit_code != 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["status"] == "error", payload
        assert payload["code"] == "BOT_MISSING_REQUIRED_ACCOUNT", payload
        db_mock.close.assert_awaited_once()
        ipc_spy.assert_not_called()


# ── 축 3: active=1 → 정상 통과 + cleanup + ipc_send 도달 ────────────────


class TestBotCreateActiveOneCleanup:
    """active account 1 → resolver 통과, db.close 호출 후 ipc_send 도달."""

    def test_active_one_cleanup_then_ipc_send(self, runner: CliRunner) -> None:
        accounts = [_make_active_account("domestic")]
        create_services_mock, db_mock, _ = _build_create_services_mock(
            active_accounts=accounts
        )
        ipc_patch, ipc_spy = _patch_ipc_send()
        ipc_spy.return_value = {"bot_id": "bot-x"}

        with (
            ipc_patch,
            patch("ante.cli.commands.bot._create_services", new=create_services_mock),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                ],
            )
        assert result.exit_code == 0, result.output
        # 정상 경로에서도 cleanup 호출 (resolver 통과 후 close 보증).
        db_mock.close.assert_awaited_once()
        ipc_spy.assert_awaited_once()
        sent_args = ipc_spy.await_args[0][1]
        assert sent_args["account_id"] == "domestic", sent_args


# ── 축 4: account_service.list 가 raise → db.close 보장 (try/finally) ────


class TestBotCreateAccountListRaisesCleanup:
    """``account_service.list`` 가 예외 raise 해도 try/finally 로 close 보증."""

    def test_account_list_raise_still_closes_db(self, runner: CliRunner) -> None:
        db = MagicMock()
        db.close = AsyncMock()
        account_service = AsyncMock()
        account_service.list = AsyncMock(side_effect=RuntimeError("boom"))

        # #1857: ``bot._create_services`` async context manager 전환.
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _create_services_mock(*args, **kwargs):
            try:
                yield db, MagicMock(), MagicMock(), account_service
            finally:
                await db.close()

        ipc_patch, ipc_spy = _patch_ipc_send()
        with (
            ipc_patch,
            patch("ante.cli.commands.bot._create_services", new=_create_services_mock),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                ],
            )
        # account_service.list 예외 → CLI 가 종료(JSON envelope 또는 traceback).
        # 회귀 핵심: try/finally 의 db.close 가 호출되어 aiosqlite 누수 없음.
        assert result.exit_code != 0, result.output
        db.close.assert_awaited_once()
        ipc_spy.assert_not_called()
