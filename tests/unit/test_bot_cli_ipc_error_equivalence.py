"""Bot CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 3).

본 모듈은 #1816 의 4차 migration domain (bot) 의 대표 fault 6 건이 CLI path
와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을 lock 한다.
#1842 (account) / #1843 sub-PR 1 (member) / sub-PR 2 (approval) 의 1:1 동형
패턴.

검증 대상 fault:

- ``BotNotFoundError`` → ``BOT_NOT_FOUND`` (not_found; ``bot remove`` /
  ``bot start`` 표면, IPC envelope helper)
- ``BotAccountCredentialsNotConfigured`` → ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``
  (validation; ``bot start`` 표면 ``app_key`` preflight 거부)
- ``BotStateConflict`` → ``BOT_STATE_CONFLICT`` (state_conflict; ``bot start``
  / ``bot stop`` 표면 상태머신 거부)
- ``BotNotAcceptingSignals`` → ``BOT_NOT_ACCEPTING_SIGNALS`` (state_conflict;
  ``accepts_external_signals=False`` 전략 거부)
- ``BotAlreadyExistsError`` → ``BOT_ALREADY_EXISTS`` (state_conflict;
  ``bot create`` 표면 중복 등록 거부, 실제 ``bot.create`` IPC handler 회귀)
- ``BotStrategyAlreadyRunningError`` → ``BOT_STRATEGY_ALREADY_RUNNING``
  (state_conflict; ``bot create`` 표면 "1전략 1봇" 정책 거부)
- ``BotImmutableFieldError`` → ``BOT_IMMUTABLE_FIELD`` (validation; #2282
  ``bot.update`` 표면 ``account_id`` 변경 거부 — treasury 예산·broker
  credential·포지션이 account-bound 라 생성 후 불변. 실제 ``bot.update`` IPC
  handler 회귀로 envelope code surface 확인)

bot CLI 의 mutating 표면 (``create``/``remove``/``start``/``stop``/``status``)
은 모두 ``ipc_send`` 경유이므로 CLI direct path equivalence 는 ``ipc_send``
mock 으로 server-side envelope (``ipc_error_code``/``ipc_error_message``) 을
주입한 뒤 CLI middleware ClickException 분기가 동일 코드를 surface 함을 확인
한다. ``signal-key --rotate`` 는 CLI 안에서 직접 sentinel (``code`` 키) 을
반환하므로 별도 분기.

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화하거나,
``BotAlreadyExistsError`` 의 경우 실제 ``bot.create`` IPC handler 를
``IPCServer`` 위에서 실행해 envelope code 를 확인한다 (#1842 ``account.suspend``
1:1 동형 회귀 lock).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.bot.exceptions import (
    BotAccountCredentialsNotConfigured,
    BotAlreadyExistsError,
    BotImmutableFieldError,
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotStateConflict,
    BotStrategyAlreadyRunningError,
)
from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.core.registry import ServiceRegistry
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=["bot:read", "bot:write", "bot:admin"],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json bot ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (#1865 ``member`` /
    #1866 ``approval`` equivalence test fixture 동형). ``require_scope``
    decorator 는 그대로 동작하므로 모든 bot scope 를 부여한다.
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx) -> None:  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    본 helper 는 helper 경로를 그대로 사용해 contract 동등성을 단언한다.
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


def _cli_envelope_payload(result_output: str) -> dict:
    """``CliRunner.result.output`` 에서 JSON envelope 첫 객체를 추출."""
    payload_line = next(
        (line for line in result_output.splitlines() if line.startswith("{")),
        None,
    )
    assert payload_line is not None, f"JSON envelope 발견 실패: {result_output!r}"
    return json.loads(payload_line)


def _make_click_exc(code: str, message: str) -> click.ClickException:
    """``ipc_send`` 가 server error envelope 을 변환할 때 부착하는
    ``ipc_error_code``/``ipc_error_message`` 속성을 가진 ClickException 을
    구성한다. CLI command 의 ``except click.ClickException`` 분기에서 동일한
    형태로 message/code 를 복원한다.
    """

    exc = click.ClickException(f"{code}: {message}")
    exc.ipc_error_code = code  # type: ignore[attr-defined]
    exc.ipc_error_message = message  # type: ignore[attr-defined]
    return exc


# ── (1) BotNotFoundError ↔ BOT_NOT_FOUND ────────────────────────────────────


class TestBotNotFoundEquivalence:
    """``BotNotFoundError`` 는 양쪽에서 ``BOT_NOT_FOUND``.

    CLI direct path: ``bot remove`` 표면 — ``ipc_send`` 가 server error
    envelope (code=``BOT_NOT_FOUND``) 을 ClickException 으로 변환하고,
    ``except Exception: emit_cli_error(fmt, e)`` 분기가 동일 코드로 CLI
    envelope 을 surface 한다. ``BotNotFoundError`` 는 #1840 에서 이미 registry
    등록되어 있으므로 helper resolver 가 ``BOT_NOT_FOUND`` 로 resolve 한다.
    """

    def test_cli_direct_not_found_via_remove(self, runner: CliRunner) -> None:
        click_exc = _make_click_exc("BOT_NOT_FOUND", "Bot not found: missing")

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        # #2309: ``bot remove`` 는 ``if is_active_runtime(): ipc_send(...) else:
        # cold-path`` 분기(bot.py:492)를 가진다. ``is_active_runtime`` 은
        # ``get_config_dir()`` 의 PID/socket 파일 존재로 판정하므로, mock 하지
        # 않으면 xdist 워커에서 선행 테스트가 남긴 runtime-state 에 따라 분기가
        # 비결정적이 된다(False → cold-path → 미설정 DB → code 없는 예외 →
        # ``EXECUTION_ERROR`` 오분류). IPC-path equivalence 를 검증하는 본
        # 테스트는 ``is_active_runtime`` 을 ``True`` 로 고정해 결정적으로
        # ipc_send 경로를 타게 한다(``test_bot_success_output_drift.py`` /
        # ``test_cli_bot_treasury_ipc.py`` 의 bot_remove IPC 테스트 미러).
        with (
            patch("ante.cli.commands.bot.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "remove", "missing", "--yes"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_NOT_FOUND"

    def test_ipc_envelope_not_found(self) -> None:
        exc = BotNotFoundError("missing")
        assert _ipc_envelope_code(exc) == "BOT_NOT_FOUND"


# ── (2) BotAccountCredentialsNotConfigured ↔ BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED


class TestBotAccountCredentialsNotConfiguredEquivalence:
    """``BotAccountCredentialsNotConfigured`` 는 양쪽에서
    ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` (validation; ``app_key`` 부재
    preflight 거부).

    CLI direct path: ``bot start`` 표면 — ``ipc_send`` 가 server preflight
    envelope (code=``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``) 을
    ClickException 으로 변환하고, ``except click.ClickException`` 분기가
    JSON 모드에서 동일 코드로 CLI envelope 을 surface 한다.
    """

    def test_cli_direct_credentials_not_configured_via_start(
        self, runner: CliRunner
    ) -> None:
        click_exc = _make_click_exc(
            "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED",
            "계좌에 인증정보(app_key)가 설정되지 않았습니다",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "start", "bot-1"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"

    def test_ipc_envelope_credentials_not_configured(self) -> None:
        exc = BotAccountCredentialsNotConfigured(
            "계좌에 인증정보(app_key)가 설정되지 않았습니다"
        )
        assert _ipc_envelope_code(exc) == "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"


# ── (3) BotStateConflict ↔ BOT_STATE_CONFLICT (start/stop) ──────────────────


class TestBotStateConflictEquivalence:
    """``BotStateConflict`` 는 양쪽에서 ``BOT_STATE_CONFLICT``.

    CLI direct path: ``bot start`` / ``bot stop`` 양쪽 표면 모두 IPC envelope
    을 ClickException 으로 받아 surface 한다. middleware 분기는 ``bot
    start``/``bot stop`` 가 공유하는 동일 패턴 (#1673 미러).
    """

    def test_cli_direct_state_conflict_via_start(self, runner: CliRunner) -> None:
        click_exc = _make_click_exc(
            "BOT_STATE_CONFLICT", "이미 실행 중인 봇입니다: bot-1"
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "start", "bot-1"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_STATE_CONFLICT"

    def test_cli_direct_state_conflict_via_stop(self, runner: CliRunner) -> None:
        click_exc = _make_click_exc(
            "BOT_STATE_CONFLICT", "중지된 봇은 중지할 수 없습니다: bot-1"
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "stop", "bot-1"],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_STATE_CONFLICT"

    def test_ipc_envelope_state_conflict(self) -> None:
        exc = BotStateConflict("이미 실행 중인 봇입니다")
        assert _ipc_envelope_code(exc) == "BOT_STATE_CONFLICT"


# ── (4) BotNotAcceptingSignals ↔ BOT_NOT_ACCEPTING_SIGNALS ──────────────────


class TestBotNotAcceptingSignalsEquivalence:
    """``BotNotAcceptingSignals`` 는 양쪽에서ApprovalStatusConflict
    안정 코드 ``BOT_NOT_ACCEPTING_SIGNALS`` (state_conflict 카테고리;
    ``accepts_external_signals=False`` 전략 거부).

    CLI direct path 는 IPC envelope helper-direct path 와 동일 코드를
    surface 한다는 contract 동등성을 lock 한다. CLI 실제 surface 는
    ``signal connect``/``bot signal-key --rotate`` 가 cold-path sentinel
    분기에서 동일 코드를 발급하지만, 본 test 는 contract level (registry
    helper) 동등성만 단언한다 — 회귀 lock 은 별도 `test_bot_signal_key*`/
    `signal connect` 표면 test (#1761) 가 책임진다.
    """

    def test_ipc_envelope_not_accepting_signals(self) -> None:
        exc = BotNotAcceptingSignals(
            "이 봇의 전략은 외부 시그널을 받지 않습니다: bot_id=bot-1"
        )
        assert _ipc_envelope_code(exc) == "BOT_NOT_ACCEPTING_SIGNALS"


# ── (5) BotAlreadyExistsError ↔ BOT_ALREADY_EXISTS (create) ─────────────────


class TestBotAlreadyExistsEquivalence:
    """``BotAlreadyExistsError`` 는 양쪽에서 ``BOT_ALREADY_EXISTS``.

    CLI direct path: ``bot create`` 표면 — ``ipc_send`` 가 server error
    envelope 을 ClickException 으로 변환하고, ``except Exception:
    emit_cli_error(fmt, e)`` 가 동일 코드를 surface 한다. registry MRO
    lookup 으로 ``BotAlreadyExistsError`` → ``BOT_ALREADY_EXISTS`` resolve.

    IPC path: 실제 ``bot.create`` IPC handler 를 ``IPCServer`` 위에서
    실행해 envelope code 를 확인한다 (#1842 ``account.suspend`` 1:1 동형
    회귀 lock).
    """

    def test_cli_direct_already_exists_via_create(self, runner: CliRunner) -> None:
        click_exc = _make_click_exc("BOT_ALREADY_EXISTS", "Bot already exists: bot-dup")

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "test",
                    "--strategy",
                    "s1",
                    "--account",
                    "acc1",
                    "--id",
                    "bot-dup",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_ALREADY_EXISTS"

    def test_ipc_envelope_already_exists(self) -> None:
        exc = BotAlreadyExistsError("Bot already exists: bot-dup")
        assert _ipc_envelope_code(exc) == "BOT_ALREADY_EXISTS"

    @pytest.mark.asyncio
    async def test_ipc_envelope_already_exists_via_real_handler(self) -> None:
        """실제 ``bot.create`` IPC handler 가 typed code 를 envelope 으로
        surface 한다 (#1842 ``account.suspend`` 1:1 동형 회귀 lock).

        ``BotManager.create_bot`` 가 ``BotAlreadyExistsError`` 를 raise 하는
        시나리오를 mock 으로 재현하고, ``StrategyRegistry.get`` 도 mock 으로
        valid record 를 돌려준 뒤 ``StrategyLoader.load`` 를 patch 해 cold-path
        파일 IO 를 피한다 (handler 가 strategy lookup 이후에 ``create_bot`` 을
        호출하므로 둘 다 필요).
        """

        td = tempfile.mkdtemp(prefix="ipc_bot_equiv", dir="/tmp")
        socket_path = str(Path(td) / "t.sock")

        bot_manager = MagicMock()
        bot_manager.create_bot = AsyncMock(
            side_effect=BotAlreadyExistsError("Bot already exists: bot-dup")
        )

        strategy_record = MagicMock()
        strategy_record.filepath = "/tmp/_fake_strategy.py"
        strategy_registry = MagicMock()
        strategy_registry.get = AsyncMock(return_value=strategy_record)

        # Refs #2110: bot.create 가 audit 대상이 되어 required_services 에
        # audit_logger 가 추가됐다 — preflight 통과를 위해 주입한다
        # (account.suspend 동형). 실패 경로(BotAlreadyExistsError)라 audit
        # 발화는 일어나지 않지만 preflight 는 audit_logger 존재를 요구한다.
        audit_logger = MagicMock()
        audit_logger.log = AsyncMock(return_value=None)
        svc_registry = ServiceRegistry(
            account=MagicMock(),
            bot_manager=bot_manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            member_service=MagicMock(),
            strategy_registry=strategy_registry,
            audit_logger=audit_logger,
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)

        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            client = IPCClient(socket_path, timeout=5.0)
            with patch("ante.strategy.loader.StrategyLoader.load") as mock_load:
                mock_load.return_value = MagicMock()
                response = await client.send(
                    "bot.create",
                    {
                        "account_id": "acc1",
                        "strategy_id": "s1",
                        "name": "test",
                        "bot_id": "bot-dup",
                    },
                    actor="tester",
                )
            assert response["status"] == "error"
            assert response["error"]["code"] == "BOT_ALREADY_EXISTS"
        finally:
            await server.stop()


# ── (6) BotStrategyAlreadyRunningError ↔ BOT_STRATEGY_ALREADY_RUNNING ──────


class TestBotStrategyAlreadyRunningEquivalence:
    """``BotStrategyAlreadyRunningError`` 는 양쪽에서
    ``BOT_STRATEGY_ALREADY_RUNNING`` ("1전략 1봇" 정책 거부).

    CLI direct path: ``bot create`` 표면 — ``ipc_send`` 가 server error
    envelope 을 ClickException 으로 변환하고, ``except Exception:
    emit_cli_error(fmt, e)`` 가 동일 코드를 surface 한다. registry MRO
    lookup 으로 ``BotStrategyAlreadyRunningError`` →
    ``BOT_STRATEGY_ALREADY_RUNNING`` resolve.
    """

    def test_cli_direct_strategy_already_running_via_create(
        self, runner: CliRunner
    ) -> None:
        click_exc = _make_click_exc(
            "BOT_STRATEGY_ALREADY_RUNNING",
            "전략 s1 은 이미 실행 중인 다른 봇이 사용 중입니다",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "test",
                    "--strategy",
                    "s1",
                    "--account",
                    "acc1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "BOT_STRATEGY_ALREADY_RUNNING"

    def test_ipc_envelope_strategy_already_running(self) -> None:
        exc = BotStrategyAlreadyRunningError(
            "전략 s1 은 이미 실행 중인 다른 봇이 사용 중입니다"
        )
        assert _ipc_envelope_code(exc) == "BOT_STRATEGY_ALREADY_RUNNING"


# ── (7) BotImmutableFieldError ↔ BOT_IMMUTABLE_FIELD (update) ───────────────


class TestBotImmutableFieldEquivalence:
    """``BotImmutableFieldError`` 는 양쪽에서 ``BOT_IMMUTABLE_FIELD`` (#2282).

    CLI direct path: ``bot update`` 표면 — ``ipc_send`` 가 server error
    envelope (code=``BOT_IMMUTABLE_FIELD``) 을 ClickException 으로 변환하고
    CLI middleware 분기가 동일 코드를 surface 한다. registry MRO lookup 으로
    ``BotImmutableFieldError`` → ``BOT_IMMUTABLE_FIELD`` resolve.

    IPC path: 실제 ``bot.update`` IPC handler 를 ``IPCServer`` 위에서 실행해
    ``account_id`` 변경 요청이 envelope code 로 거부됨을 확인한다 (#1842
    ``account.suspend`` / ``bot.create`` 1:1 동형 회귀 lock).
    """

    def test_ipc_envelope_immutable_field(self) -> None:
        exc = BotImmutableFieldError("account_id 는 생성 후 변경할 수 없습니다")
        assert _ipc_envelope_code(exc) == "BOT_IMMUTABLE_FIELD"

    @pytest.mark.asyncio
    async def test_ipc_envelope_immutable_field_via_real_handler(self) -> None:
        """실제 ``bot.update`` IPC handler 가 ``account_id`` 변경 거부 코드를
        envelope 으로 surface 한다 (#2282; ``bot.create`` 1:1 동형 회귀 lock).

        handler 는 ``svc.bot_manager.get_bot`` 으로 봇 존재를 먼저 확인한 뒤
        ``update_bot`` 을 호출하므로, ``get_bot`` 은 봇을 돌려주고 ``update_bot``
        이 ``BotImmutableFieldError`` 를 raise 하도록 mock 한다. handler 의
        ``except BotError: raise`` 가 typed 예외를 그대로 propagate 하고 IPC
        server 가 ``getattr(e, "code", ...)`` 로 ``BOT_IMMUTABLE_FIELD`` envelope
        을 생성한다.
        """

        td = tempfile.mkdtemp(prefix="ipc_bot_immutable", dir="/tmp")
        socket_path = str(Path(td) / "t.sock")

        bot_manager = MagicMock()
        bot_manager.get_bot = MagicMock(return_value=MagicMock())
        bot_manager.update_bot = AsyncMock(
            side_effect=BotImmutableFieldError(
                "account_id 는 생성 후 변경할 수 없습니다: bot-1"
            )
        )

        audit_logger = MagicMock()
        audit_logger.log = AsyncMock(return_value=None)
        svc_registry = ServiceRegistry(
            account=MagicMock(),
            bot_manager=bot_manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            member_service=MagicMock(),
            strategy_registry=MagicMock(),
            audit_logger=audit_logger,
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)

        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            client = IPCClient(socket_path, timeout=5.0)
            response = await client.send(
                "bot.update",
                {
                    "bot_id": "bot-1",
                    "updates": {"account_id": "acc-new"},
                },
                actor="tester",
            )
            assert response["status"] == "error"
            assert response["error"]["code"] == "BOT_IMMUTABLE_FIELD"
        finally:
            await server.stop()
