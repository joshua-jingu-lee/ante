"""bot 명령 11개와 ``signal.connect`` 핸드셰이크의 특성 테스트 (#2683 ⑤).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
호출을 기록하는 대역이다. 서비스가 받은 인자는 리터럴로 잠근다(봇은 실자금
주문의 주체다). CLI 경로 테스트는 실제 ``cli.main``의 ``ipc_send``를 이 서버의
``_dispatch``로 잇는다.
"""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.bot.config import BotConfig, BotStatus
from ante.cli.main import cli
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState
from ante.member.models import Member, MemberRole, MemberType

ACTOR = "ops-lead"
CLI_MEMBER = "cli-master-7"
SIGNAL_KEY = "MARKSIGKEY01x"
BOT_INFO = {"bot_id": "b-7", "status": "stopped"}
STRATEGY_CLS = object()
LISTED = [
    {
        "bot_id": "b-7",
        "name": "n-7",
        "strategy_id": "s-9",
        "account_id": "acct-2",
        "status": "stopped",
        "created_at": "2026-01-02",
        "extra": "dropped",
    },
    {
        "bot_id": "b-8",
        "name": "n-8",
        "strategy_id": "s-9",
        "account_id": "acct-3",
        "status": "running",
        "created_at": "2026-01-03",
    },
]


class _Harness:
    def __init__(self) -> None:
        bot = MagicMock()
        bot.bot_id = "b-7"
        bot.config.account_id = "acct-2"
        bot.get_info.return_value = dict(BOT_INFO)
        bot.status = BotStatus.RUNNING
        bot.strategy.meta.accepts_external_signals = True
        self.bot = bot
        manager = MagicMock()
        manager.get_bot = MagicMock(return_value=bot)
        manager.create_bot = AsyncMock(return_value=bot)
        manager.remove_bot = AsyncMock(return_value=None)
        manager.rotate_signal_key = AsyncMock(return_value="rotated-key-1")
        manager.start_bot = AsyncMock(return_value=None)
        manager.stop_bot = AsyncMock(return_value=None)
        manager.update_bot = AsyncMock(return_value=bot)
        manager.list_bots = MagicMock(return_value=[dict(b) for b in LISTED])
        manager.get_signal_key = AsyncMock(return_value="current-key-1")
        manager.validate_signal_key = AsyncMock(return_value="b-7")
        self.bot_manager = manager
        account = MagicMock()
        account.get = AsyncMock(
            return_value=SimpleNamespace(credentials={"app_key": "ak"})
        )
        self.account = account
        strategy_registry = MagicMock()
        strategy_registry.get = AsyncMock(
            return_value=SimpleNamespace(filepath="/strategies/s9.py")
        )
        self.strategy_registry = strategy_registry
        trade = MagicMock()
        trade.get_positions = AsyncMock(
            return_value=[
                SimpleNamespace(
                    symbol="005930",
                    quantity=3,
                    avg_entry_price=1000.0,
                    realized_pnl=5.0,
                )
            ]
        )
        self.trade = trade
        channels = MagicMock()
        channels.current_generation = MagicMock(return_value=4)
        self.channels = channels
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=account,
            bot_manager=manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            strategy_registry=strategy_registry,
            audit_logger=self.audit_logger,
            trade_service=trade,
            signal_channel_registry=channels,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any, actor: str = ACTOR) -> dict:
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "ante.strategy.loader.StrategyLoader.load",
                    return_value=STRATEGY_CLS,
                )
            )
            stack.enter_context(
                patch("uuid.uuid4", return_value=SimpleNamespace(hex="sess-1"))
            )
            return await self.server._dispatch(
                {"id": "req-1", "command": command, "args": args, "actor": actor}
            )

    def assert_audited(self, action: str, detail: str = "") -> None:
        self.audit_logger.log.assert_awaited_once_with(
            member_id=ACTOR, action=action, resource="bot:b-7", detail=detail, ip=""
        )

    def assert_no_service_call(self) -> None:
        for name in (
            "create_bot",
            "remove_bot",
            "rotate_signal_key",
            "start_bot",
            "stop_bot",
            "update_bot",
            "get_signal_key",
            "validate_signal_key",
        ):
            getattr(self.bot_manager, name).assert_not_awaited()
        self.bot_manager.get_bot.assert_not_called()
        self.bot_manager.list_bots.assert_not_called()
        self.strategy_registry.get.assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


def _ok(result: dict) -> dict:
    return {"id": "req-1", "status": "ok", "result": result}


def _error(code: str, message: str) -> dict:
    return {
        "id": "req-1",
        "status": "error",
        "error": {"code": code, "message": message},
    }


CREATE_ARGS = {
    "name": "n-2",
    "strategy_id": "s-9",
    "account_id": "acct-2",
    "interval_seconds": 120,
    "bot_id": "b-7",
}


@pytest.mark.asyncio
async def test_create_passes_every_field_to_the_bot_config() -> None:
    harness = _Harness()
    response = await harness.send("bot.create", dict(CREATE_ARGS))
    assert response == _ok({"bot_id": "b-7"})
    harness.strategy_registry.get.assert_awaited_once_with("s-9")
    harness.bot_manager.create_bot.assert_awaited_once_with(
        config=BotConfig(
            bot_id="b-7",
            strategy_id="s-9",
            name="n-2",
            account_id="acct-2",
            interval_seconds=120,
        ),
        strategy_cls=STRATEGY_CLS,
        source_path=Path("/strategies/s9.py"),
    )
    harness.assert_audited("bot.create")


@pytest.mark.asyncio
async def test_create_defaults() -> None:
    harness = _Harness()
    response = await harness.send(
        "bot.create", {"strategy_id": "s-9", "account_id": "acct-2"}
    )
    assert response == _ok({"bot_id": "b-7"})
    harness.bot_manager.create_bot.assert_awaited_once_with(
        config=BotConfig(
            bot_id="",
            strategy_id="s-9",
            name="",
            account_id="acct-2",
            interval_seconds=60,
        ),
        strategy_cls=STRATEGY_CLS,
        source_path=Path("/strategies/s9.py"),
    )


@pytest.mark.asyncio
async def test_create_unknown_strategy_is_the_handler_error() -> None:
    harness = _Harness()
    harness.strategy_registry.get.return_value = None
    response = await harness.send("bot.create", dict(CREATE_ARGS))
    assert response == _error("EXECUTION_ERROR", "전략을 찾을 수 없습니다: s-9")
    harness.bot_manager.create_bot.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "method", "result", "action"),
    [
        ("bot.remove", "remove_bot", {"bot_id": "b-7", "removed": True}, "bot.delete"),
        (
            "bot.signal_key.rotate",
            "rotate_signal_key",
            {"bot_id": "b-7", "signal_key": "rotated-key-1", "rotated": True},
            "bot.signal_key.rotate",
        ),
        ("bot.start", "start_bot", {"bot": BOT_INFO}, "bot.start"),
        ("bot.stop", "stop_bot", {"bot": BOT_INFO}, "bot.stop"),
    ],
)
async def test_bot_id_commands_pass_the_bot_id_and_audit(
    command: str, method: str, result: dict[str, Any], action: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, {"bot_id": "b-7"})
    assert response == _ok(result)
    getattr(harness.bot_manager, method).assert_awaited_once_with("b-7")
    harness.assert_audited(action)


@pytest.mark.asyncio
async def test_start_reads_the_bot_account_credentials() -> None:
    harness = _Harness()
    await harness.send("bot.start", {"bot_id": "b-7"})
    harness.bot_manager.get_bot.assert_called_once_with("b-7")
    harness.account.get.assert_awaited_once_with("acct-2")


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["bot.start", "bot.stop"])
async def test_start_and_stop_of_a_missing_bot(command: str) -> None:
    harness = _Harness()
    harness.bot_manager.get_bot.return_value = None
    response = await harness.send(command, {"bot_id": "b-0"})
    assert response == _error("BOT_NOT_FOUND", "Bot not found: b-0")
    harness.bot_manager.start_bot.assert_not_awaited()
    harness.bot_manager.stop_bot.assert_not_awaited()


UPDATES = {
    "name": "x",
    "strategy_id": "s2",
    "interval_seconds": 30,
    "budget": 100.0,
    "auto_restart": True,
    "max_restart_attempts": 2,
    "restart_cooldown_seconds": 20,
    "step_timeout_seconds": 6,
    "max_signals_per_step": 3,
}
UPDATE_FIELDS = (
    "fields=['name', 'strategy_id', 'interval_seconds', 'budget', 'auto_restart', "
    "'max_restart_attempts', 'restart_cooldown_seconds', 'step_timeout_seconds', "
    "'max_signals_per_step']"
)


@pytest.mark.asyncio
async def test_update_passes_every_field_and_audits_their_order() -> None:
    harness = _Harness()
    response = await harness.send(
        "bot.update", {"bot_id": "b-7", "updates": dict(UPDATES)}
    )
    assert response == _ok({"bot": BOT_INFO})
    harness.bot_manager.update_bot.assert_awaited_once_with(
        "b-7",
        name="x",
        strategy_id="s2",
        interval_seconds=30,
        budget=100.0,
        auto_restart=True,
        max_restart_attempts=2,
        restart_cooldown_seconds=20,
        step_timeout_seconds=6,
        max_signals_per_step=3,
    )
    harness.assert_audited("bot.update", UPDATE_FIELDS)


@pytest.mark.asyncio
async def test_update_passes_the_account_id_to_the_service() -> None:
    harness = _Harness()
    response = await harness.send(
        "bot.update", {"bot_id": "b-7", "updates": {"account_id": "default"}}
    )
    assert response == _ok({"bot": BOT_INFO})
    harness.bot_manager.update_bot.assert_awaited_once_with("b-7", account_id="default")
    harness.assert_audited("bot.update", "fields=['account_id']")


@pytest.mark.asyncio
async def test_update_passes_an_explicit_null_field() -> None:
    harness = _Harness()
    response = await harness.send(
        "bot.update", {"bot_id": "b-7", "updates": {"name": None, "budget": 5}}
    )
    assert response == _ok({"bot": BOT_INFO})
    harness.bot_manager.update_bot.assert_awaited_once_with("b-7", name=None, budget=5)
    harness.assert_audited("bot.update", "fields=['name', 'budget']")


@pytest.mark.asyncio
async def test_update_without_updates_calls_the_service_with_no_field() -> None:
    harness = _Harness()
    response = await harness.send("bot.update", {"bot_id": "b-7"})
    assert response == _ok({"bot": BOT_INFO})
    harness.bot_manager.update_bot.assert_awaited_once_with("b-7")
    harness.assert_audited("bot.update", "fields=[]")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "bots"),
    [
        (
            {},
            [
                {k: v for k, v in LISTED[0].items() if k != "extra"},
                LISTED[1],
            ],
        ),
        (
            {"account_id": "acct-3"},
            [LISTED[1]],
        ),
    ],
)
async def test_list_filters_by_the_account(
    args: dict[str, Any], bots: list[dict[str, Any]]
) -> None:
    harness = _Harness()
    response = await harness.send("bot.list", args)
    assert response == _ok({"bots": bots})


@pytest.mark.asyncio
async def test_info_and_signal_key_and_positions() -> None:
    harness = _Harness()
    assert await harness.send("bot.info", {"bot_id": "b-7"}) == _ok({"bot": BOT_INFO})
    assert await harness.send("bot.signal_key", {"bot_id": "b-7"}) == _ok(
        {"bot_id": "b-7", "signal_key": "current-key-1"}
    )
    harness.bot_manager.get_signal_key.assert_awaited_once_with("b-7")
    assert await harness.send("bot.positions", {"bot_id": "b-7"}) == _ok(
        {
            "positions": [
                {
                    "symbol": "005930",
                    "quantity": 3,
                    "avg_entry_price": 1000.0,
                    "realized_pnl": 5.0,
                }
            ]
        }
    )
    harness.trade.get_positions.assert_awaited_once_with("b-7", account_id="acct-2")
    assert [c.args for c in harness.bot_manager.get_bot.call_args_list] == [
        ("b-7",),
        ("b-7",),
        ("b-7",),
    ]


@pytest.mark.asyncio
async def test_status_enriches_the_bot_info() -> None:
    harness = _Harness()
    enrich = AsyncMock(return_value={"bot_id": "b-7", "enriched": True})
    with patch("ante.bot.info.enrich_bot_info", enrich):
        response = await harness.send("bot.status", {"bot_id": "b-7"})
    assert response == _ok({"bot": {"bot_id": "b-7", "enriched": True}})
    assert enrich.await_args.args == (harness.bot,)
    assert enrich.await_args.kwargs["account_id"] == "acct-2"
    assert enrich.await_args.kwargs["trade_service"] is harness.trade


# ── signal.connect 핸드셰이크 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_connect_opens_a_session_after_the_four_gates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    harness = _Harness()
    response = await harness.send("signal.connect", {"key": SIGNAL_KEY})
    assert response == _ok(
        {
            "bot_id": "b-7",
            "account_id": "acct-2",
            "session_id": "sess-1",
            "_stream": "signal.connect",
        }
    )
    harness.bot_manager.validate_signal_key.assert_awaited_once_with(SIGNAL_KEY)
    harness.bot_manager.get_bot.assert_called_once_with("b-7")
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ipc", action="signal.connect", resource="bot:b-7", detail="", ip=""
    )
    handle = harness.channels.register.call_args.args[0]
    assert (handle.session_id, handle.bot_id, handle.generation) == ("sess-1", "b-7", 4)
    assert SIGNAL_KEY not in json.dumps(response, ensure_ascii=False)
    assert SIGNAL_KEY not in caplog.text
    assert SIGNAL_KEY not in str(harness.audit_logger.log.await_args_list)


def _gate_invalid_key(harness: _Harness) -> None:
    harness.bot_manager.validate_signal_key.return_value = None


def _gate_missing_bot(harness: _Harness) -> None:
    harness.bot_manager.get_bot.return_value = None


def _gate_not_running(harness: _Harness) -> None:
    harness.bot.status = BotStatus.STOPPED


def _gate_not_accepting(harness: _Harness) -> None:
    harness.bot.strategy.meta.accepts_external_signals = False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setup", "error", "get_bot_calls"),
    [
        (_gate_invalid_key, ("INVALID_SIGNAL_KEY", "Invalid signal key"), 0),
        (_gate_missing_bot, ("BOT_NOT_FOUND", "Bot not found: b-7"), 1),
        (
            _gate_not_running,
            ("BOT_NOT_RUNNING", "Bot is not running: b-7 (status: stopped)"),
            1,
        ),
        (
            _gate_not_accepting,
            ("BOT_NOT_ACCEPTING_SIGNALS", "Bot b-7 does not accept external signals"),
            1,
        ),
    ],
)
async def test_signal_connect_gates_in_order(
    setup: Any,
    error: tuple[str, str],
    get_bot_calls: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    harness = _Harness()
    setup(harness)
    response = await harness.send("signal.connect", {"key": SIGNAL_KEY})
    assert response == _error(*error)
    harness.bot_manager.validate_signal_key.assert_awaited_once_with(SIGNAL_KEY)
    assert harness.bot_manager.get_bot.call_count == get_bot_calls
    harness.audit_logger.log.assert_not_awaited()
    harness.channels.register.assert_not_called()
    assert SIGNAL_KEY not in json.dumps(response, ensure_ascii=False)
    assert SIGNAL_KEY not in caplog.text


@pytest.mark.asyncio
async def test_signal_connect_empty_key_is_an_invalid_key() -> None:
    harness = _Harness()
    harness.bot_manager.validate_signal_key.return_value = None
    response = await harness.send("signal.connect", {"key": ""})
    assert response == _error("INVALID_SIGNAL_KEY", "Invalid signal key")
    harness.bot_manager.validate_signal_key.assert_awaited_once_with("")


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"key": SIGNAL_KEY}, {"key": 7}])
async def test_signal_connect_lifecycle_gate_comes_first(args: dict[str, Any]) -> None:
    harness = _Harness()
    harness.server._state = IPCServerState.DRAINING
    response = await harness.send("signal.connect", args)
    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"key": SIGNAL_KEY}, {"key": 7}])
async def test_signal_connect_required_service_comes_first(
    args: dict[str, Any],
) -> None:
    harness = _Harness()
    harness.server._service_registry.bot_manager = None
    response = await harness.send("signal.connect", args)
    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
    harness.bot_manager.validate_signal_key.assert_not_awaited()


# ── 지금 동작을 적는 테스트(모델 커밋에서 기대값이 바뀐다) ──────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{}, {"key": 7}, {"key": None}])
async def test_signal_connect_key_that_is_not_a_string(args: dict[str, Any]) -> None:
    harness = _Harness()
    response = await harness.send("signal.connect", args)
    assert response == _error("INVALID_SIGNAL_KEY", "Invalid signal key")
    harness.assert_no_service_call()


@pytest.mark.asyncio
async def test_update_unknown_field_reaches_the_service() -> None:
    harness = _Harness()
    response = await harness.send(
        "bot.update", {"bot_id": "b-7", "updates": {"zz_field": 1}}
    )
    assert response == _ok({"bot": BOT_INFO})
    harness.bot_manager.update_bot.assert_awaited_once_with("b-7", zz_field=1)


@pytest.mark.asyncio
async def test_start_without_a_bot_id() -> None:
    harness = _Harness()
    response = await harness.send("bot.start", {})
    assert response == _error("EXECUTION_ERROR", "'bot_id'")
    harness.assert_no_service_call()


@pytest.mark.asyncio
async def test_create_params_are_not_read() -> None:
    harness = _Harness()
    response = await harness.send("bot.create", {**CREATE_ARGS, "params": {"k": "v"}})
    assert response == _ok({"bot_id": "b-7"})
    assert harness.bot_manager.create_bot.await_args.kwargs["config"] == BotConfig(
        bot_id="b-7",
        strategy_id="s-9",
        name="n-2",
        account_id="acct-2",
        interval_seconds=120,
    )


# ── CLI → _dispatch → 서비스 ────────────────────────────────────────────────


_CLI_MEMBER = Member(
    member_id=CLI_MEMBER,
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="CLI Master",
    status="active",
    scopes=[],
)


def _set_member(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _CLI_MEMBER


def _run_cli(
    harness: _Harness, argv: list[str]
) -> tuple[list[tuple[str, Any, str]], str]:
    sent: list[tuple[str, Any, str]] = []

    async def _send(command: str, args: Any, actor: str = "cli", **_: Any) -> dict:
        wire = json.loads(json.dumps(args))
        sent.append((command, wire, actor))
        response = await harness.send(command, wire, actor=actor)
        assert response["status"] == "ok", response
        return response["result"]

    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_member)
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", side_effect=_send)
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=True)
        )
        stack.enter_context(
            patch("ante.cli.commands.bot.is_active_runtime", return_value=True)
        )
        result = CliRunner(mix_stderr=False).invoke(cli, argv)
    assert result.exit_code == 0, (result.output, result.stderr)
    return sent, result.output


def _audited_by_cli(harness: _Harness, action: str, detail: str = "") -> None:
    harness.audit_logger.log.assert_awaited_once_with(
        member_id=CLI_MEMBER, action=action, resource="bot:b-7", detail=detail, ip=""
    )


def test_cli_create_with_a_param_passes_the_same_config() -> None:
    harness = _Harness()
    sent, output = _run_cli(
        harness,
        [
            "bot",
            "create",
            "--name",
            "n-2",
            "--strategy",
            "s-9",
            "--account",
            "acct-2",
            "--interval",
            "120",
            "--id",
            "b-7",
            "--param",
            "threshold=0.5",
        ],
    )
    assert [(command, actor) for command, _, actor in sent] == [
        ("bot.create", CLI_MEMBER)
    ]
    harness.bot_manager.create_bot.assert_awaited_once_with(
        config=BotConfig(
            bot_id="b-7",
            strategy_id="s-9",
            name="n-2",
            account_id="acct-2",
            interval_seconds=120,
        ),
        strategy_cls=STRATEGY_CLS,
        source_path=Path("/strategies/s9.py"),
    )
    _audited_by_cli(harness, "bot.create")
    assert output == "봇 생성 완료: b-7\n"


def test_cli_update_with_every_option_audits_the_cli_order() -> None:
    harness = _Harness()
    sent, _ = _run_cli(
        harness,
        [
            "bot",
            "update",
            "b-7",
            "--name",
            "x",
            "--strategy",
            "s2",
            "--interval",
            "30",
            "--budget",
            "100",
            "--auto-restart",
            "--max-restart-attempts",
            "2",
            "--restart-cooldown-seconds",
            "20",
            "--step-timeout-seconds",
            "6",
            "--max-signals-per-step",
            "3",
        ],
    )
    assert sent == [("bot.update", {"bot_id": "b-7", "updates": UPDATES}, CLI_MEMBER)]
    harness.bot_manager.update_bot.assert_awaited_once_with(
        "b-7",
        name="x",
        strategy_id="s2",
        interval_seconds=30,
        budget=100.0,
        auto_restart=True,
        max_restart_attempts=2,
        restart_cooldown_seconds=20,
        step_timeout_seconds=6,
        max_signals_per_step=3,
    )
    _audited_by_cli(harness, "bot.update", UPDATE_FIELDS)


def test_cli_update_with_one_option() -> None:
    harness = _Harness()
    sent, _ = _run_cli(harness, ["bot", "update", "b-7", "--no-auto-restart"])
    assert sent == [
        (
            "bot.update",
            {"bot_id": "b-7", "updates": {"auto_restart": False}},
            CLI_MEMBER,
        )
    ]
    harness.bot_manager.update_bot.assert_awaited_once_with("b-7", auto_restart=False)
    _audited_by_cli(harness, "bot.update", "fields=['auto_restart']")


@pytest.mark.parametrize(
    ("argv", "method", "action"),
    [
        (["bot", "start", "b-7"], "start_bot", "bot.start"),
        (["bot", "stop", "b-7"], "stop_bot", "bot.stop"),
    ],
)
def test_cli_start_and_stop_pass_the_bot_id(
    argv: list[str], method: str, action: str
) -> None:
    harness = _Harness()
    sent, _ = _run_cli(harness, argv)
    assert sent == [(action, {"bot_id": "b-7"}, CLI_MEMBER)]
    getattr(harness.bot_manager, method).assert_awaited_once_with("b-7")
    _audited_by_cli(harness, action)
