"""브로커를 기다리는 텔레그램 처리 중에도 킬 스위치가 처리된다 (#3111).

실제 ``TelegramCommandReceiver``(``start()``의 폴링 루프)·``ApprovalService``·
``BotManager``·``AccountService``·``APIGateway``·``OrderTracker``·``RuleEngine``
위에서 돌린다. 텔레그램 API(수신·회신·콜백 응답)와 브로커(취소를 막는다)만 가짜다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ante.account.errors import AccountSuspendAllFailedError
from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.approval.service import ApprovalService
from ante.bot import BotConfig, BotManager, BotStatus
from ante.broker.fill_scheduler import business_date_kst
from ante.core import Database, clock
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.gateway import APIGateway
from ante.main import _subscribe_order_tracker
from ante.notification.telegram_receiver import TelegramCommandReceiver
from ante.rule import RuleEngine
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)
from ante.trade.order_tracker import OrderTracker
from tests.unit._readiness_gate_helpers import ready_registry
from tests.unit._rule_engine_helpers import StubTreasury

ACCT = "acc-tg"
BOT = "bot-a"
OTHER = "bot-b"
USER = 12345
CHAT_A = 100
CHAT_B = 200
HALTED = "전체 거래가 중지되었습니다"
DROPPED_APPROVAL = (
    "ℹ️ 전체 거래 중지 요청으로 실행하지 않았습니다 — 결재는 대기 상태입니다"
)
WAIT = 5.0


class _Data(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class _Portfolio(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class _Orders(OrderView):
    def get_open_orders(self, bot_id):
        return []


class Idle(Strategy):
    meta = StrategyMeta(name="idle", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class GatedBroker:
    """``gate``가 열릴 때까지 취소 응답을 막는 가짜 브로커."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.calls: list[str] = []
        self.completed: list[str] = []

    async def cancel_order(self, broker_order_id: str) -> bool:
        self.calls.append(broker_order_id)
        self.entered.set()
        await self.gate.wait()
        self.completed.append(broker_order_id)
        return True


class Script:
    """수신 묶음을 대본대로 내고, 대본이 끝나면 정지될 때까지 기다린다.

    ``free``번째 뒤의 묶음은 ``hold``가 설정된 뒤에 낸다(브로커가 막힌 뒤의 명령).
    """

    def __init__(
        self, batches: list[list[dict]], hold: asyncio.Event, free: int
    ) -> None:
        self._batches = list(batches)
        self._hold = hold
        self._free = free
        self.calls = 0
        self._reached: defaultdict[int, asyncio.Event] = defaultdict(asyncio.Event)

    async def __call__(self) -> list[dict]:
        self.calls += 1
        self._reached[self.calls].set()
        if self.calls > self._free:
            await self._hold.wait()
        if self._batches:
            return self._batches.pop(0)
        await asyncio.Event().wait()
        return []

    async def reach(self, n: int) -> None:
        await asyncio.wait_for(self._reached[n].wait(), timeout=WAIT)


def _cmd(update_id: int, text: str, chat_id: int = CHAT_A) -> dict:
    return {
        "update_id": update_id,
        "message": {"text": text, "from": {"id": USER}, "chat": {"id": chat_id}},
    }


def _tap(update_id: int, data: str, chat_id: int = CHAT_A) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": {"id": USER},
            "message": {"chat": {"id": chat_id}},
            "data": data,
        },
    }


def _buy() -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCT,
        bot_id=OTHER,
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=1.0,
        order_type="limit",
        price=50000.0,
    )


class Stack:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.broker = GatedBroker()
        self.replies: list[tuple[int | None, str]] = []
        self.adapter = SimpleNamespace(
            _api_base="https://api.telegram.org/botTEST",
            answer_callback_query=AsyncMock(return_value=True),
        )

    async def setup(self) -> None:
        self.tracker = OrderTracker(db=self.db)
        await self.tracker.initialize()
        _subscribe_order_tracker(self.bus, self.tracker)
        self.accounts = AccountService(self.db, self.bus)
        await self.accounts.initialize()
        await self.accounts.create(
            Account(
                account_id=ACCT,
                name="테스트",
                exchange="TEST",
                currency="KRW",
                broker_type="test",
                credentials={"app_key": "test", "app_secret": "test"},
            )
        )
        self.gateway = APIGateway(
            account_service=SimpleNamespace(  # type: ignore[arg-type]
                get_broker=AsyncMock(return_value=self.broker)
            ),
            eventbus=self.bus,
            order_tracker=self.tracker,
        )
        self.gateway.start()
        self.manager = BotManager(
            eventbus=self.bus,
            db=self.db,
            order_tracker=self.tracker,
            trade_service=SimpleNamespace(  # type: ignore[arg-type]
                get_positions=AsyncMock(return_value=[])
            ),
        )
        await self.manager.initialize()
        self.executed: list[tuple[str, str]] = []
        self.approvals = ApprovalService(
            db=self.db,
            eventbus=self.bus,
            executors={
                "bot_delete": self._run("bot_delete", self.manager.delete_bot),
                "bot_resume": self._run("bot_resume", self.manager.resume_bot),
            },
        )
        await self.approvals.initialize()
        self.receiver = TelegramCommandReceiver(
            adapter=self.adapter,  # type: ignore[arg-type]
            allowed_user_ids=[USER],
            polling_interval=0,
            confirm_timeout=30.0,
            bot_manager=self.manager,
            account_service=self.accounts,
            approval_service=self.approvals,
        )
        self.receiver._reply = self._record_reply  # type: ignore[method-assign]
        self.rule_bus = EventBus()
        self.rejected: list[OrderRejectedEvent] = []
        self.validated: list[OrderValidatedEvent] = []
        self.rule_bus.subscribe(OrderRejectedEvent, self.rejected.append)
        self.rule_bus.subscribe(OrderValidatedEvent, self.validated.append)
        account = await self.accounts.get(ACCT)
        self.engine = RuleEngine(
            eventbus=self.rule_bus,
            account_id=ACCT,
            account_service=self.accounts,
            treasury=StubTreasury(),
            account=account,
            runtime_readiness=ready_registry(
                ACCT, broker_type=account.broker_type, trading_mode=account.trading_mode
            ),
        )

    def _run(self, name: str, method: Any):
        async def _execute(params: dict[str, Any]) -> Any:
            self.executed.append((name, params["bot_id"]))
            return await method(params["bot_id"])

        return _execute

    async def _record_reply(self, chat_id: int | None, text: str) -> None:
        self.replies.append((chat_id, text))

    def texts(self, chat_id: int) -> list[str]:
        return [text for cid, text in self.replies if cid == chat_id]

    def index_of(self, fragment: str) -> int:
        for i, (_, text) in enumerate(self.replies):
            if fragment in text:
                return i
        raise AssertionError(f"회신에 없다: {fragment!r} / {self.replies!r}")

    async def make_bot(self, bot_id: str) -> Any:
        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=_Data(),
            portfolio=_Portfolio(),
            order_view=_Orders(),
        )
        config = BotConfig(
            bot_id=bot_id, strategy_id="s1", account_id=ACCT, auto_restart=False
        )
        return await self.manager.create_bot(config, Idle, ctx)

    async def seed(self, order_id: str, bot_id: str = BOT) -> None:
        await self.tracker.open(
            order_id=order_id,
            account_id=ACCT,
            bot_id=bot_id,
            strategy_id="s1",
            broker_order_id=f"bk-{order_id}",
            symbol="005930",
            side="buy",
            order_type="limit",
            ordered_qty=10,
            submitted_date=business_date_kst(clock.now(UTC)),
            order_price=10_000.0,
        )

    async def approval(self, type_: str, bot_id: str) -> str:
        request = await self.approvals.create(
            type=type_,
            requester="agent",
            title=f"{type_} {bot_id}",
            params={"bot_id": bot_id},
        )
        return request.id

    async def approval_status(self, approval_id: str) -> str:
        request = await self.approvals.get(approval_id)
        assert request is not None
        return str(request.status)

    async def order_status(self, order_id: str) -> str:
        record = await self.tracker.get(order_id)
        assert record is not None
        return record.status

    async def run(self, batches: list[list[dict]], free: int = 1) -> Script:
        script = Script(batches, self.broker.entered, free)
        self.receiver._get_updates = script  # type: ignore[method-assign]
        self.receiver.start()
        return script

    async def assert_halted_while_blocked(self) -> None:
        assert not self.broker.gate.is_set()
        account = await self.accounts.get(ACCT)
        assert account.status == AccountStatus.SUSPENDED
        await self.engine._on_order_request(_buy())
        assert [e.reason for e in self.rejected] == ["account_suspended"]
        assert self.validated == []

    async def release(self) -> None:
        self.broker.gate.set()
        await asyncio.wait_for(self.receiver._jobs.join(), timeout=WAIT)

    async def teardown(self) -> None:
        self.broker.gate.set()
        await asyncio.wait_for(self.receiver.stop(), timeout=WAIT)
        for task in list(self.manager._suspension_cleanups.values()):
            await asyncio.wait_for(asyncio.shield(task), timeout=WAIT)
        for bot in list(self.manager._bots.values()):
            if bot._task and not bot._task.done():
                bot._task.cancel()
        try:
            await asyncio.wait_for(self.manager.stop_all(), timeout=WAIT)
        except TimeoutError:
            pass


@pytest.fixture
async def stack(tmp_path: Path):
    database = Database(str(tmp_path / "tg.db"))
    await database.connect()
    s = Stack(database)
    await s.setup()
    yield s
    await s.teardown()
    try:
        await asyncio.wait_for(database.close(), timeout=WAIT)
    except TimeoutError:
        pass


async def _stopped_bot(stack: Stack, bot_id: str) -> Any:
    bot = await stack.make_bot(bot_id)
    await stack.manager.start_bot(bot_id)
    await stack.manager.stop_bot(bot_id)
    assert bot.status == BotStatus.STOPPED
    return bot


# ── 재현 ─────────────────────────────────────────


async def test_halt_runs_while_approved_delete_waits_for_broker(stack: Stack) -> None:
    """재현 ①: 막힌 봇 삭제 승인 동안 /halt·/confirm이 계좌를 정지시킨다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    delete_id = await stack.approval("bot_delete", BOT)

    script = await stack.run(
        [
            [_tap(1, f"approve:{delete_id}")],
            [_cmd(2, "/halt 긴급")],
            [_cmd(3, "/confirm")],
        ]
    )
    await script.reach(4)

    await stack.assert_halted_while_blocked()
    assert stack.broker.calls == ["bk-ord-1"]
    assert stack.adapter.answer_callback_query.await_args_list[0].args == (
        "cb1",
        "⏳ 처리 중입니다",
    )
    assert any(HALTED in text for text in stack.texts(CHAT_A))
    assert not any("결재 승인 완료" in text for text in stack.texts(CHAT_A))

    await stack.release()

    assert stack.index_of(HALTED) < stack.index_of("✅ 결재 승인 완료")
    assert stack.executed == [("bot_delete", BOT)]
    assert BOT not in stack.manager._bots
    row = await stack.db.fetch_one("SELECT status FROM bots WHERE bot_id = ?", (BOT,))
    assert row is not None
    assert row["status"] == "deleted"
    assert stack.broker.calls == ["bk-ord-1"]
    assert stack.broker.completed == ["bk-ord-1"]
    assert await stack.order_status("ord-1") == "cancelled"
    assert stack.adapter.answer_callback_query.await_count == 1


async def test_halt_runs_while_stop_confirm_waits_for_broker(stack: Stack) -> None:
    """재현 ②: /stop의 확인이 브로커를 기다리는 동안 /halt·/confirm이 처리된다."""
    await stack.make_bot(BOT)
    await stack.manager.start_bot(BOT)
    await stack.seed("ord-1")

    script = await stack.run(
        [
            [_cmd(1, f"/stop {BOT}")],
            [_cmd(2, "/confirm")],
            [_cmd(3, "/halt")],
            [_cmd(4, "/confirm")],
        ],
        free=2,
    )
    await script.reach(5)

    await stack.assert_halted_while_blocked()
    assert not any("봇 중지" in text for text in stack.texts(CHAT_A))

    await stack.release()

    assert stack.index_of(HALTED) < stack.index_of("봇 중지")
    assert stack.manager.get_bot(BOT).status == BotStatus.STOPPED
    assert stack.broker.calls == ["bk-ord-1"]
    assert await stack.order_status("ord-1") == "cancelled"


# ── 전체 정지의 줄 비우기 ────────────────────────


async def test_halt_drops_queued_resume_behind_blocked_delete(stack: Stack) -> None:
    """막힌 삭제 뒤에 줄 선 봇 재개 승인은 전체 정지로 실행되지 않는다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    other = await _stopped_bot(stack, OTHER)
    delete_id = await stack.approval("bot_delete", BOT)
    resume_id = await stack.approval("bot_resume", OTHER)

    script = await stack.run(
        [
            [_tap(1, f"approve:{delete_id}")],
            [_tap(2, f"approve:{resume_id}", CHAT_B)],
            [_cmd(3, "/halt")],
            [_cmd(4, "/confirm")],
        ]
    )
    await script.reach(5)
    await stack.assert_halted_while_blocked()
    await stack.release()

    assert stack.executed == [("bot_delete", BOT)]
    assert other.status == BotStatus.STOPPED
    assert await stack.approval_status(resume_id) == "pending"
    assert stack.texts(CHAT_B) == [f"{DROPPED_APPROVAL}\nID: {resume_id}"]
    assert stack.index_of(DROPPED_APPROVAL) < stack.index_of(HALTED)
    assert any("✅ 결재 승인 완료" in text for text in stack.texts(CHAT_A))


THIRD = "bot-c"
CHAT_C = 300
PARTIAL = "전체 거래 중지가 일부 계좌에서 실패했습니다"


def _failing_suspend_all(kind: str):
    async def _suspend_all(reason: str, suspended_by: str) -> list[dict[str, Any]]:
        if kind == "partial":
            raise AccountSuspendAllFailedError((ACCT,), 0)
        raise RuntimeError("SECRET-3111")

    return _suspend_all


@pytest.mark.parametrize("kind", ["partial", "error"])
async def test_failed_halt_drops_approvals_and_runs_queued_stop(
    stack: Stack, kind: str
) -> None:
    """전체 정지가 실패해도 결재는 버리고, 줄의 /stop 확인은 정지 뒤에 실행한다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    other = await _stopped_bot(stack, OTHER)
    third = await stack.make_bot(THIRD)
    await stack.manager.start_bot(THIRD)
    delete_id = await stack.approval("bot_delete", BOT)
    resume_id = await stack.approval("bot_resume", OTHER)
    stack.accounts.suspend_all = _failing_suspend_all(kind)  # type: ignore[method-assign]

    script = await stack.run(
        [
            [_tap(1, f"approve:{delete_id}")],
            [_tap(2, f"approve:{resume_id}", CHAT_B)],
            [_cmd(3, f"/stop {THIRD}", CHAT_C)],
            [_cmd(4, "/confirm", CHAT_C)],
            [_cmd(5, "/halt")],
            [_cmd(6, "/confirm")],
        ]
    )
    await script.reach(7)
    assert third.status == BotStatus.RUNNING
    await stack.release()

    assert stack.executed == [("bot_delete", BOT)]
    assert other.status == BotStatus.STOPPED
    assert await stack.approval_status(resume_id) == "pending"
    assert stack.texts(CHAT_B) == [f"{DROPPED_APPROVAL}\nID: {resume_id}"]
    assert third.status == BotStatus.STOPPED
    stop_replies = [t for t in stack.texts(CHAT_C) if "봇 중지" in t]
    assert len(stop_replies) == 1
    halt_reply = PARTIAL if kind == "partial" else "처리 중 오류가 발생했습니다"
    assert stack.index_of(DROPPED_APPROVAL) < stack.index_of(halt_reply)
    assert stack.index_of(halt_reply) < stack.index_of("봇 중지")
    assert all("SECRET-3111" not in text for _, text in stack.replies)


async def test_dropped_notice_failure_does_not_skip_others(stack: Stack) -> None:
    """버린 결재 한 건의 안내가 실패해도 나머지 안내는 간다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    await _stopped_bot(stack, OTHER)
    delete_id = await stack.approval("bot_delete", BOT)
    first = await stack.approval("bot_resume", OTHER)
    second = await stack.approval("bot_resume", OTHER)
    recorded = stack._record_reply

    async def _reply(chat_id: int | None, text: str) -> None:
        if chat_id == CHAT_B and text.startswith(DROPPED_APPROVAL):
            raise RuntimeError("reply failed")
        await recorded(chat_id, text)

    stack.receiver._reply = _reply  # type: ignore[method-assign]

    script = await stack.run(
        [
            [_tap(1, f"approve:{delete_id}")],
            [_tap(2, f"approve:{first}", CHAT_B), _tap(3, f"approve:{second}", CHAT_C)],
            [_cmd(4, "/halt"), _cmd(5, "/confirm")],
        ]
    )
    await script.reach(4)
    await stack.release()

    assert stack.texts(CHAT_C) == [f"{DROPPED_APPROVAL}\nID: {second}"]
    assert any(HALTED in text for text in stack.texts(CHAT_A))
    assert await stack.approval_status(first) == "pending"
    assert await stack.approval_status(second) == "pending"
    assert stack.executed == [("bot_delete", BOT)]


async def test_already_halted_keeps_queued_jobs(stack: Stack) -> None:
    """「이미 중지됨」이면 줄을 건드리지 않고 대기 작업이 그대로 실행된다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    await _stopped_bot(stack, OTHER)
    delete_id = await stack.approval("bot_delete", BOT)
    resume_id = await stack.approval("bot_resume", OTHER)
    await stack.accounts.suspend_all(reason="cli", suspended_by="admin")
    stack.receiver._pending_confirm[USER] = ("halt", [], clock.monotonic())

    script = await stack.run(
        [
            [_tap(1, f"approve:{delete_id}")],
            [_tap(2, f"approve:{resume_id}", CHAT_B)],
            [_cmd(3, "/confirm")],
        ]
    )
    await script.reach(4)
    assert "이미 거래가 중지된 상태입니다." in stack.texts(CHAT_A)
    await stack.release()

    assert stack.executed == [("bot_delete", BOT), ("bot_resume", OTHER)]
    assert await stack.approval_status(resume_id) == "approved"
    assert not any(DROPPED_APPROVAL in text for _, text in stack.replies)


async def test_halt_and_confirm_in_one_batch(stack: Stack) -> None:
    """/halt와 /confirm이 같은 묶음으로 와도 차례로 처리된다."""
    script = await stack.run([[_cmd(1, "/halt"), _cmd(2, "/confirm")]], free=9)
    await script.reach(2)

    account = await stack.accounts.get(ACCT)
    assert account.status == AccountStatus.SUSPENDED
    texts = stack.texts(CHAT_A)
    assert "/confirm" in texts[0]
    assert HALTED in texts[1]


# ── 작업자의 순서·실패·정지 ───────────────────────


async def test_double_tap_runs_executor_once(stack: Stack) -> None:
    """같은 결재의 승인이 두 번 와도 실행기는 한 번만 돈다."""
    await _stopped_bot(stack, OTHER)
    resume_id = await stack.approval("bot_resume", OTHER)

    script = await stack.run(
        [[_tap(1, f"approve:{resume_id}"), _tap(2, f"approve:{resume_id}")]], free=9
    )
    await script.reach(2)
    await stack.release()

    assert stack.executed == [("bot_resume", OTHER)]
    texts = stack.texts(CHAT_A)
    assert len(texts) == 2
    assert "✅ 결재 승인 완료" in texts[0]
    assert "ℹ️ 이미 처리된 결재입니다" in texts[1]


async def test_approve_then_reject_keeps_approval(stack: Stack) -> None:
    """승인 뒤에 온 거절은 충돌로 끝나고 실행기는 한 번만 돈다."""
    await _stopped_bot(stack, OTHER)
    resume_id = await stack.approval("bot_resume", OTHER)

    script = await stack.run(
        [[_tap(1, f"approve:{resume_id}"), _tap(2, f"reject:{resume_id}")]], free=9
    )
    await script.reach(2)
    await stack.release()

    assert stack.executed == [("bot_resume", OTHER)]
    assert await stack.approval_status(resume_id) == "approved"
    texts = stack.texts(CHAT_A)
    assert "✅ 결재 승인 완료" in texts[0]
    assert "ℹ️ 이미 처리된 결재입니다" in texts[1]


async def test_same_bot_approvals_run_in_arrival_order(stack: Stack) -> None:
    """같은 봇에 대한 결재 둘은 도착 순서대로 실행된다."""
    other = await _stopped_bot(stack, OTHER)
    resume_id = await stack.approval("bot_resume", OTHER)
    delete_id = await stack.approval("bot_delete", OTHER)

    script = await stack.run(
        [[_tap(1, f"approve:{resume_id}"), _tap(2, f"approve:{delete_id}")]], free=9
    )
    await script.reach(2)
    await stack.release()

    assert stack.executed == [("bot_resume", OTHER), ("bot_delete", OTHER)]
    assert OTHER not in stack.manager._bots
    assert other.status != BotStatus.RUNNING
    assert all("✅ 결재 승인 완료" in text for text in stack.texts(CHAT_A))


async def test_executor_error_replies_and_next_job_runs(stack: Stack) -> None:
    """실행기가 예외로 끝나도 그 chat에 실패 문구가 가고 다음 작업이 실행된다."""
    await _stopped_bot(stack, OTHER)
    resume_id = await stack.approval("bot_resume", OTHER)
    real = ApprovalService.approve

    async def _approve(*args: Any, **kwargs: Any) -> Any:
        if not calls:
            calls.append(1)
            raise RuntimeError("SECRET-3111")
        return await real(stack.approvals, *args, **kwargs)

    calls: list[int] = []
    stack.approvals.approve = _approve  # type: ignore[method-assign]

    script = await stack.run(
        [[_tap(1, f"approve:{resume_id}"), _tap(2, f"approve:{resume_id}", CHAT_B)]],
        free=9,
    )
    await script.reach(2)
    await stack.release()

    assert stack.texts(CHAT_A) == ["처리 중 오류가 발생했습니다."]
    assert len(stack.texts(CHAT_B)) == 1
    assert "✅ 결재 승인 완료" in stack.texts(CHAT_B)[0]
    assert stack.executed == [("bot_resume", OTHER)]


async def test_stop_cancels_worker_and_logs_dropped(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    """수신기 정지는 작업자를 끝내고, 시작하지 않은 작업은 버리고 건수를 남긴다."""
    await stack.make_bot(BOT)
    await stack.seed("ord-1")
    await _stopped_bot(stack, OTHER)
    delete_id = await stack.approval("bot_delete", BOT)
    resume_id = await stack.approval("bot_resume", OTHER)

    script = await stack.run(
        [[_tap(1, f"approve:{delete_id}")], [_tap(2, f"approve:{resume_id}")]]
    )
    await script.reach(3)
    worker = stack.receiver._worker
    assert worker is not None
    with caplog.at_level(logging.WARNING, logger="ante.notification.telegram_receiver"):
        await asyncio.wait_for(stack.receiver.stop(), timeout=WAIT)

    assert worker.done()
    assert stack.receiver._worker is None
    assert stack.receiver._jobs.empty()
    assert stack.executed == [("bot_delete", BOT)]
    assert await stack.approval_status(resume_id) == "pending"
    assert any("1건" in r.getMessage() for r in caplog.records)
