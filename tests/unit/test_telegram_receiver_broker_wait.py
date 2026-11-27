"""브로커를 기다리는 텔레그램 처리 중에도 킬 스위치가 처리된다 (#3111).

실제 ``TelegramCommandReceiver``(``start()``의 폴링 루프)·``ApprovalService``·
``BotManager``·``AccountService``·``APIGateway``·``OrderTracker``·``RuleEngine``
위에서 돌린다. 텔레그램 API(수신·회신·콜백 응답)와 브로커(취소를 막는다)만 가짜다.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

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
    """수신 묶음을 대본대로 내고, 대본이 끝나면 정지될 때까지 기다린다."""

    def __init__(self, batches: list[list[dict]]) -> None:
        self._batches = list(batches)
        self.calls = 0
        self._reached: defaultdict[int, asyncio.Event] = defaultdict(asyncio.Event)

    async def __call__(self) -> list[dict]:
        self.calls += 1
        self._reached[self.calls].set()
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

    async def run(self, batches: list[list[dict]]) -> Script:
        script = Script(batches)
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
    assert stack.broker.completed.count("bk-ord-1") >= 1
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
        ]
    )
    await asyncio.wait_for(stack.broker.entered.wait(), timeout=WAIT)
    await script.reach(5)

    await stack.assert_halted_while_blocked()
    assert not any("봇 중지" in text for text in stack.texts(CHAT_A))

    await stack.release()

    assert stack.index_of(HALTED) < stack.index_of("봇 중지")
    assert stack.manager.get_bot(BOT).status == BotStatus.STOPPED


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
