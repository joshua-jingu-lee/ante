"""main 의 조립 함수(_init_*)가 실제로 만든 배선을 동작으로 확인한다 (#2540 S3).

``assemble`` fixture 를 쓰는 테스트는 실제 ``_init_core`` → ``_init_services`` →
``_init_account`` → ``_init_trading`` → ``_init_gateway`` → ``_init_ipc`` 를 /tmp
아래 임시 config_dir 에서 돌리고 실제 ``_shutdown`` 으로 닫는다. ``_init_core`` 의
경로·Config 재사용을 보는 두 테스트는 ``_init_core`` 만 돈다.

가짜로 두는 것: broker 어댑터(``AccountService._build_broker_adapter``),
``FillReconcileScheduler``(카치업 성공 여부), ``ReconcileScheduler.run_once``(기동
대사 모드 기록), ``FillOutboxPublisher`` 의 주기 드레인 간격(1시간),
``setup_logging``(root 핸들러 보존). kis-domestic 기본 룰(거래시간)은 static
config 로 끈다. 일부 테스트는 그 테스트에서만 조립 함수나 인스턴스 메서드를 원본을
부르는 기록 래퍼로 감싸거나(순서 기록), 세션 판정·현재가 조회·봇 조회를 가짜로
바꾼다.

단언은 조립 결과로 만들어진 객체들의 동작(이벤트, 저장 상태, IPC 응답)과, 제약이
순서일 때 호출 순서로 한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import ante.bot.reconcile_scheduler as scheduler_mod
import ante.broker.fill_scheduler as fill_scheduler_mod
import ante.core.log as core_log_mod
import ante.main as main_module
import ante.trade as trade_mod
from ante.account import Account, AccountService, TradingMode
from ante.account.readiness import ReadinessFlag
from ante.config import Config
from ante.core import clock
from ante.db.migrations import run_migrations
from ante.eventbus.events import (
    BotStoppedEvent,
    NotificationEvent,
    OrderApprovedEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderSubmittedEvent,
    StopOrderExpiredEvent,
)
from ante.ipc.client import IPCClient
from ante.trade.fill_outbox import FillOutboxPublisher
from tests.conftest import ManualClock

_CREDS = {"app_key": "k", "app_secret": "s", "account_no": "1234567890"}


def _kis_account(account_id: str, *, mode: TradingMode = TradingMode.LIVE) -> Account:
    return Account(
        account_id=account_id,
        name=account_id,
        exchange="KRX",
        currency="KRW",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=mode,
        broker_type="kis-domestic",
        credentials=dict(_CREDS),
        broker_config={"is_paper": True},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        market_order_reserve_buffer_rate=Decimal("0"),
    )


class _FakeBroker:
    """BrokerAdapter 더블. 연결·주문·해제를 기록한다."""

    websocket_url: str | None = None

    def __init__(self, account_id: str, factory: _BrokerFactory) -> None:
        self.account_id = account_id
        self.account_no = "1234567890"
        self.is_paper = True
        self._factory = factory
        self.placed: list[dict[str, Any]] = []
        self.disconnected = False

    async def connect(self) -> None:
        self._factory.connects += 1
        if self._factory.connect_error is not None:
            raise self._factory.connect_error

    async def disconnect(self) -> None:
        self.disconnected = True

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        return []

    async def get_account_balance(self) -> dict[str, float]:
        return {"cash": 10_000_000.0}

    async def get_buyable(self, symbol: str, *args: Any, **kwargs: Any) -> Any:
        return {"order_buyable_amount": 10_000_000.0}

    async def get_positions(self) -> list[dict[str, Any]]:
        return []

    async def get_account_positions(self) -> list[dict[str, Any]]:
        return []

    async def get_current_price(self, symbol: str) -> float:
        return 100.0

    async def place_order(self, *args: Any, **kwargs: Any) -> str:
        self.placed.append({"args": args, **kwargs})
        return f"BRK-{self.account_id}-{len(self.placed)}"


@dataclass
class _BrokerFactory:
    """계좌 하나의 broker 생성기. ``connect_error`` 가 있으면 connect 가 실패한다."""

    account_id: str
    connect_error: BaseException | None = None
    connects: int = 0
    built: list[_FakeBroker] = field(default_factory=list)

    async def build(self) -> _FakeBroker:
        broker = _FakeBroker(self.account_id, self)
        self.built.append(broker)
        return broker


@dataclass
class _Assembly:
    s: main_module.Services
    config_dir: Path
    brokers: dict[str, _BrokerFactory]
    log: list[str]
    reconcile_runs: list[tuple[str, bool]]
    shut_down: bool = False


def _fill_scheduler_cls(log: list[str], fill_succeeds: dict[str, bool]) -> type[Any]:
    class _FillScheduler:
        def __init__(self, **kwargs: Any) -> None:
            self.account_id = kwargs["account_id"]

        async def catch_up_once(self) -> Any:
            log.append(f"fill_catch_up:{self.account_id}")
            return fill_scheduler_mod.CatchUpResult(
                succeeded=fill_succeeds.get(self.account_id, True), applied=0
            )

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    return _FillScheduler


def _reconcile_scheduler_cls(log: list[str], runs: list[tuple[str, bool]]) -> type[Any]:
    class _ReconcileScheduler(scheduler_mod.ReconcileScheduler):
        async def start(self) -> None:
            log.append(f"reconcile_start:{self._broker_account_id}")
            await super().start()

        async def run_once(self, *, skip_external_buy: bool = False) -> list[Any]:
            runs.append((self._broker_account_id, skip_external_buy))
            return []

    return _ReconcileScheduler


class _QuietPublisher(FillOutboxPublisher):
    """주기 드레인 간격을 길게 둔 퍼블리셔. 즉시 발행은 ``notify()`` 로만 일어난다."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs["drain_interval"] = 3600.0
        super().__init__(**kwargs)


AssembleFn = Callable[..., Awaitable[_Assembly]]


@pytest.fixture
async def assemble(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AssembleFn]:
    """실제 _init_* 로 데몬을 조립하는 팩토리. 끝나면 실제 ``_shutdown`` 으로 닫는다."""
    monkeypatch.setattr(core_log_mod, "setup_logging", lambda config: None)
    monkeypatch.setattr(trade_mod, "FillOutboxPublisher", _QuietPublisher)
    built: list[_Assembly] = []

    async def _assemble(
        accounts: list[Account],
        *,
        static: dict[str, Any] | None = None,
        connect_errors: dict[str, BaseException] | None = None,
        fill_succeeds: dict[str, bool] | None = None,
        before_gateway: Callable[[_Assembly], Any] | None = None,
        before_seed: Callable[[AccountService], Awaitable[None]] | None = None,
    ) -> _Assembly:
        config_dir = Path(tempfile.mkdtemp(prefix="aw", dir="/tmp"))
        cfg_static: dict[str, Any] = {
            "strategy": {"dir": str(config_dir / "strategies")},
            "data": {"path": str(config_dir / "data")},
            # kis-domestic 기본 룰(거래시간)은 벽시계를 본다. 시간에 기대지 않도록 끈다.
            "accounts": {
                a.account_id: {"rules": [{"type": "trading_hours", "enabled": False}]}
                for a in accounts
            },
        }
        cfg_static.update(static or {})
        config = Config(static=cfg_static, secrets={}, config_dir=config_dir)
        log: list[str] = []
        runs: list[tuple[str, bool]] = []
        succeeds = dict(fill_succeeds or {})
        monkeypatch.setattr(
            fill_scheduler_mod,
            "FillReconcileScheduler",
            _fill_scheduler_cls(log, succeeds),
        )
        monkeypatch.setattr(
            scheduler_mod, "ReconcileScheduler", _reconcile_scheduler_cls(log, runs)
        )
        s = main_module.Services(config=config)
        brokers = {
            a.account_id: _BrokerFactory(
                a.account_id, connect_error=(connect_errors or {}).get(a.account_id)
            )
            for a in accounts
        }
        asm = _Assembly(
            s=s,
            config_dir=config_dir,
            brokers=brokers,
            log=log,
            reconcile_runs=runs,
        )
        built.append(asm)

        await main_module._init_core(s)
        assert s.db is not None and s.eventbus is not None
        await run_migrations(s.db, data_path=config_dir / "data")
        seed = AccountService(db=s.db, eventbus=s.eventbus)
        await seed.initialize()
        if before_seed is not None:
            await before_seed(seed)
        for account in accounts:
            await seed.create(account)
        await main_module._init_services(s)
        await main_module._init_account(s)

        async def _build(account_id: str) -> _FakeBroker:
            return await brokers[account_id].build()

        monkeypatch.setattr(s.account_service, "_build_broker_adapter", _build)
        await main_module._init_trading(s)
        if before_gateway is not None:
            prepared = before_gateway(asm)
            if inspect.isawaitable(prepared):
                await prepared
        await main_module._init_gateway(s)
        await main_module._restore_bots(s)
        await main_module._init_ipc(s)
        return asm

    yield _assemble

    failures: list[BaseException] = []
    for asm in built:
        try:
            if not asm.shut_down and asm.s.db is not None:
                try:
                    await asyncio.wait_for(main_module._shutdown(asm.s), timeout=30.0)
                except Exception as exc:
                    failures.append(exc)
                    await _force_close(asm.s)
        finally:
            shutil.rmtree(asm.config_dir, ignore_errors=True)
    if failures:
        raise failures[0]


async def _shutdown_in_test(asm: _Assembly) -> None:
    """테스트 본문에서 실제 ``_shutdown`` 을 부른다.

    실패하면 남은 자원을 닫고 다시 던진다."""
    asm.shut_down = True
    try:
        await asyncio.wait_for(main_module._shutdown(asm.s), timeout=30.0)
    except BaseException:
        await _force_close(asm.s)
        raise


async def _best_effort(action: Callable[[], Any]) -> None:
    try:
        result = action()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=5.0)
    except BaseException:  # noqa: BLE001 — 정리 실패는 다음 자원 정리를 막지 않는다
        pass


async def _force_close(s: main_module.Services) -> None:
    """``_shutdown`` 이 실패했을 때 남은 태스크·IPC 서버·DB 를 닫는다.

    DB 연결(aiosqlite 스레드)과 IPC 서버가 남으면 pytest 프로세스가 끝나지 않는다.
    """
    for task in (
        s.readiness_self_healing_task,
        s.stop_session_expiry_task,
        s.audit_cleanup_task,
        s.approval_expire_task,
    ):
        if task is not None and not task.done():
            task.cancel()
            await _best_effort(lambda task=task: asyncio.gather(task))
    for scheduler in [*s.reconcile_schedulers.values(), *s.fill_schedulers.values()]:
        await _best_effort(scheduler.stop)
    if s.fill_outbox_publisher is not None:
        await _best_effort(s.fill_outbox_publisher.stop)
    if s.daily_report_scheduler is not None:
        await _best_effort(s.daily_report_scheduler.stop)
    if s.treasury_manager is not None:
        for treasury in s.treasury_manager.list_all():
            await _best_effort(treasury.stop_sync)
    if s.stop_order_manager is not None:
        await _best_effort(s.stop_order_manager.stop)
    if s.ipc_server is not None:
        await _best_effort(s.ipc_server.stop_accepting)
        await _best_effort(lambda: s.ipc_server.drain_connections(timeout=1.0))
        await _best_effort(s.ipc_server.unlink_socket)
    if s.db is not None:
        await _best_effort(s.db.close)


@dataclass
class _Captured:
    events: list[Any] = field(default_factory=list)

    def of(self, cls: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, cls)]


def _capture(s: main_module.Services, *classes: type) -> _Captured:
    cap = _Captured()
    assert s.eventbus is not None
    for cls in classes:
        # 우선순위가 낮을수록 늦게 불린다. 시스템 핸들러가 모두 끝난 뒤에 기록한다.
        s.eventbus.subscribe(cls, cap.events.append, priority=-1000)
    return cap


async def _fund(s: main_module.Services, account_id: str, bot_id: str) -> None:
    treasury = s.treasury_manager.get(account_id)
    await treasury.set_account_balance(10_000_000.0)
    await treasury.allocate(bot_id, 1_000_000.0)


def _request(
    account_id: str,
    *,
    bot_id: str = "bot-1",
    order_type: str = "limit",
    price: float | None = 100.0,
    quantity: float = 10.0,
) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=account_id,
        bot_id=bot_id,
        strategy_id="strategy-1",
        symbol="005930",
        side="buy",
        quantity=quantity,
        order_type=order_type,
        price=price,
        reason="",
    )


async def _wait_for(predicate: Callable[[], bool], *, guard: float = 10.0) -> None:
    """``predicate`` 가 참이 될 때까지 이벤트 루프에 양보한다(행 방지 상한만 둔다)."""

    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(_poll(), timeout=guard)


# ── 같은 인스턴스 주입 ────────────────────────────────────────────────────────


async def test_live_order_passes_every_gate_main_marked_ready(
    assemble: AssembleFn,
) -> None:
    """main 이 ready 로 표시한 LIVE 계좌의 주문은 RuleEngine·Treasury·APIGateway
    게이트를 모두 지나 broker 에 접수된다."""
    asm = await assemble([_kis_account("live-a")])
    s = asm.s
    assert s.runtime_readiness.active_trading_ready(
        "live-a", broker_type="kis-domestic", trading_mode=TradingMode.LIVE
    )
    await _fund(s, "live-a", "bot-1")
    cap = _capture(s, OrderSubmittedEvent, OrderRejectedEvent, OrderFailedEvent)

    await s.eventbus.publish(_request("live-a"))

    assert cap.of(OrderRejectedEvent) == []
    assert cap.of(OrderFailedEvent) == []
    assert [e.account_id for e in cap.of(OrderSubmittedEvent)] == ["live-a"]
    placed = [b for b in asm.brokers["live-a"].built if b.placed]
    assert len(placed) == 1


async def test_virtual_order_fills_when_main_marked_ready(
    assemble: AssembleFn,
) -> None:
    """main 이 ready 로 표시한 가상 계좌의 주문은 VirtualExecutor 의 backstop 을
    지나 가상 체결된다."""
    asm = await assemble([])
    s = asm.s
    assert s.runtime_readiness.active_trading_ready(
        "test", broker_type="test", trading_mode=TradingMode.VIRTUAL
    )
    await _fund(s, "test", "bot-1")
    s.virtual_executor.register_bot("bot-1")
    cap = _capture(s, OrderFilledEvent, OrderRejectedEvent, OrderFailedEvent)

    await s.eventbus.publish(_request("test"))

    assert cap.of(OrderRejectedEvent) == []
    assert cap.of(OrderFailedEvent) == []
    assert [e.account_id for e in cap.of(OrderFilledEvent)] == ["test"]


async def test_virtual_fill_is_recorded_through_main_fill_applier(
    assemble: AssembleFn,
) -> None:
    """main 은 VirtualExecutor 에 같은 FillApplier 를 주입하고, 가상 체결은 발행 전에
    trades 와 positions 에 기록된다(#2611)."""
    asm = await assemble([])
    s = asm.s
    assert s.fill_applier is not None
    assert s.virtual_executor._fill_applier is s.fill_applier
    await _fund(s, "test", "bot-1")
    s.virtual_executor.register_bot("bot-1")
    cap = _capture(s, OrderFilledEvent, OrderFailedEvent)

    await s.eventbus.publish(_request("test"))

    assert cap.of(OrderFailedEvent) == []
    (filled,) = cap.of(OrderFilledEvent)
    trades = await s.db.fetch_all(
        "SELECT order_id, account_id, status FROM trades WHERE bot_id = ?", ("bot-1",)
    )
    assert trades == [
        {"order_id": filled.order_id, "account_id": "test", "status": "filled"}
    ]
    positions = await s.db.fetch_all(
        "SELECT account_id, quantity FROM positions WHERE bot_id = ?", ("bot-1",)
    )
    assert positions == [{"account_id": "test", "quantity": 10.0}]


async def _submit_live_buy(
    asm: _Assembly, account_id: str, *, quantity: float = 10.0
) -> OrderSubmittedEvent:
    """LIVE 계좌에 지정가 매수 1건을 게이트 전 구간으로 흘려 broker 접수까지 보낸다."""
    s = asm.s
    await _fund(s, account_id, "bot-1")
    cap = _capture(s, OrderSubmittedEvent, OrderRejectedEvent, OrderFailedEvent)
    await s.eventbus.publish(_request(account_id, quantity=quantity))
    submitted = cap.of(OrderSubmittedEvent)
    assert len(submitted) == 1, cap.events
    return submitted[0]


async def _apply_fill(
    asm: _Assembly,
    submitted: OrderSubmittedEvent,
    cumulative: float,
    *,
    avg_price: float = 100.0,
) -> float:
    s = asm.s
    record = await s.order_tracker.get(submitted.order_id)
    assert record is not None
    return await s.fill_applier.apply_cumulative(
        account_id=submitted.account_id,
        broker_order_id=submitted.broker_order_id,
        observed_cumulative=cumulative,
        avg_price=avg_price,
        submitted_date=record.submitted_date,
    )


# ── _init_trading 의 배선 ─────────────────────────────────────────────────────


async def test_order_submitted_event_opens_tracked_order(
    assemble: AssembleFn,
) -> None:
    """broker 접수 이벤트가 OrderTracker 에 열린 주문으로 남는다(구독 배선)."""
    asm = await assemble([_kis_account("live-a")])

    submitted = await _submit_live_buy(asm, "live-a")

    open_orders = await asm.s.order_tracker.get_open_orders("live-a")
    assert [o.order_id for o in open_orders] == [submitted.order_id]
    assert open_orders[0].broker_order_id == submitted.broker_order_id


async def test_fill_is_committed_to_outbox(assemble: AssembleFn) -> None:
    """FillApplier 가 적용한 체결은 fill_outbox 에 한 행으로 커밋된다."""
    asm = await assemble([_kis_account("live-a")])
    submitted = await _submit_live_buy(asm, "live-a")
    before = await asm.s.db.fetch_one("SELECT COUNT(*) AS n FROM fill_outbox")
    assert before is not None and before["n"] == 0

    applied = await _apply_fill(asm, submitted, 10.0)

    assert applied == 10.0
    after = await asm.s.db.fetch_one("SELECT COUNT(*) AS n FROM fill_outbox")
    assert after is not None and after["n"] == 1


async def test_fill_event_is_published_on_enqueue_without_waiting_for_drain(
    assemble: AssembleFn,
) -> None:
    """outbox 에 커밋된 체결은 주기 드레인(여기서는 1시간)을 기다리지 않고
    바로 OrderFilledEvent 로 발행된다(퍼블리셔 통지 배선)."""
    asm = await assemble([_kis_account("live-a")])
    submitted = await _submit_live_buy(asm, "live-a")
    cap = _capture(asm.s, OrderFilledEvent)

    await _apply_fill(asm, submitted, 10.0)
    await _wait_for(lambda: bool(cap.of(OrderFilledEvent)), guard=5.0)

    assert {e.order_id for e in cap.of(OrderFilledEvent)} == {submitted.order_id}


async def test_partial_buy_fill_keeps_reservation_for_unfilled_quantity(
    assemble: AssembleFn,
) -> None:
    """부분체결이면 Treasury 는 미체결 수량의 예약을 남겨 둔다(OrderTracker 주입)."""
    asm = await assemble([_kis_account("live-a")])
    submitted = await _submit_live_buy(asm, "live-a", quantity=10.0)
    treasury = asm.s.treasury_manager.get("live-a")
    budget = treasury.get_budget("bot-1")
    assert budget is not None and budget.reserved == 1000.0
    cap = _capture(asm.s, OrderFilledEvent)

    await _apply_fill(asm, submitted, 4.0)
    await _wait_for(lambda: bool(cap.of(OrderFilledEvent)), guard=5.0)

    budget = treasury.get_budget("bot-1")
    assert budget is not None
    assert budget.reserved == 600.0
    assert budget.spent == 400.0

    # 나머지가 예약보다 싸게 체결돼 전량 체결(terminal)이 되면 남은 예약이 회수된다.
    # 발행은 at-least-once 라 같은 체결이 두 번 올 수 있으므로 누적 10주 체결의
    # 도착을 키로 기다린다.
    await _apply_fill(asm, submitted, 10.0, avg_price=90.0)
    await _wait_for(
        lambda: any(
            e.fill_dedup_key.endswith(":10.0") for e in cap.of(OrderFilledEvent)
        ),
        guard=5.0,
    )
    budget = treasury.get_budget("bot-1")
    assert budget is not None
    assert budget.reserved == 0.0
    assert 400.0 < budget.spent < 1000.0


async def test_ipc_bot_positions_reports_filled_position(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IPC bot.positions 는 체결로 생긴 봇 포지션을 돌려준다(ServiceRegistry 의
    trade_service 배선)."""
    asm = await assemble([_kis_account("live-a")])
    submitted = await _submit_live_buy(asm, "live-a")
    cap = _capture(asm.s, OrderFilledEvent)
    await _apply_fill(asm, submitted, 10.0)
    await _wait_for(lambda: bool(cap.of(OrderFilledEvent)), guard=5.0)
    bot = SimpleNamespace(config=SimpleNamespace(account_id="live-a"))
    monkeypatch.setattr(
        asm.s.bot_manager,
        "get_bot",
        lambda bot_id: bot if bot_id == "bot-1" else None,
    )

    client = IPCClient(str(asm.s.config.runtime_socket_path()), timeout=5.0)
    response = await client.send("bot.positions", {"bot_id": "bot-1"})

    assert response["status"] == "ok", response
    positions = response["result"]["positions"]
    assert [(p["symbol"], p["quantity"]) for p in positions] == [("005930", 10.0)]


async def test_ipc_service_registry_carries_the_static_config_loaded_by_main(
    assemble: AssembleFn,
) -> None:
    """IPC rule.update 가 기동이 읽은 같은 정적 설정의 seed 를 읽도록 넘긴다(#3043)."""
    asm = await assemble([])
    assert asm.s.ipc_server is not None
    assert asm.s.ipc_server._service_registry.config is asm.s.config


async def test_ipc_signal_connect_channel_is_closed_by_bot_manager(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IPC signal.connect 로 연 채널은 main 이 보관한 레지스트리에 있고, 같은 봇의
    두 번째 connect 는 거부되며, BotManager 가 봇 중지 이벤트에서 그 채널을 닫는다."""
    asm = await assemble([])
    s = asm.s
    _running_signal_bot(asm, monkeypatch)

    response = await _signal_connect(asm)
    assert response["status"] == "ok", response
    session_id = response["result"]["session_id"]
    handle = s.signal_channel_registry.get("bot-1", session_id)
    assert handle is not None
    assert handle.closed is False
    second = await _signal_connect(asm)
    assert second["status"] == "error"
    assert second["error"]["code"] == "BOT_SIGNAL_CHANNEL_BUSY"

    await s.eventbus.publish(BotStoppedEvent(account_id="test", bot_id="bot-1"))

    assert handle.closed is True
    assert handle.close_reason == "bot_stopped"


async def test_shutdown_sweeps_signal_channel_opened_over_ipc(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """종료 sweep 은 IPC 로 연 시그널 채널을 'draining' 으로 닫는다."""
    asm = await assemble([])
    _running_signal_bot(asm, monkeypatch)
    response = await _signal_connect(asm)
    assert response["status"] == "ok", response
    handle = asm.s.signal_channel_registry.get(
        "bot-1", response["result"]["session_id"]
    )
    assert handle is not None

    await _shutdown_in_test(asm)

    assert handle.closed is True
    assert handle.close_reason == "draining"


def _running_signal_bot(asm: _Assembly, monkeypatch: pytest.MonkeyPatch) -> None:
    """외부 시그널을 받는 RUNNING 봇 하나를 BotManager 조회에 보이게 한다."""
    from ante.bot.config import BotStatus

    bot = SimpleNamespace(
        status=BotStatus.RUNNING,
        strategy=SimpleNamespace(meta=SimpleNamespace(accepts_external_signals=True)),
        config=SimpleNamespace(account_id="test"),
    )

    async def _validate(key: str) -> str | None:
        return "bot-1" if key == "signal-key" else None

    monkeypatch.setattr(asm.s.bot_manager, "validate_signal_key", _validate)
    monkeypatch.setattr(
        asm.s.bot_manager,
        "get_bot",
        lambda bot_id: bot if bot_id == "bot-1" else None,
    )


async def _signal_connect(asm: _Assembly) -> dict[str, Any]:
    response: dict[str, Any] = await asm.s.ipc_server._dispatch(
        {
            "id": "c1",
            "command": "signal.connect",
            "args": {"key": "signal-key"},
            "actor": "agent",
        }
    )
    return response


async def test_stop_order_held_by_gateway_expires_in_session_expiry_loop(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """APIGateway 로 등록된 스탑 주문이 세션 만료 루프의 sweep 에서 만료된다."""
    from ante.gateway.stop_order import StopOrderManager

    session_open = {"value": True}
    monkeypatch.setattr(
        StopOrderManager,
        "_is_session_type_active_now",
        lambda self, session_type, now: session_open["value"],
    )
    real_loop = main_module._stop_session_expiry_loop
    sweeps: list[Any] = []

    async def _loop_without_wait(manager: Any, interval: float = 60.0) -> None:
        sweeps.append(manager)
        await real_loop(manager, interval=0.0)

    monkeypatch.setattr(main_module, "_stop_session_expiry_loop", _loop_without_wait)
    asm = await assemble([_kis_account("live-a")])
    s = asm.s
    cap = _capture(s, StopOrderExpiredEvent)

    await s.eventbus.publish(
        OrderApprovedEvent(
            account_id="live-a",
            order_id="stop-1",
            bot_id="bot-1",
            strategy_id="strategy-1",
            symbol="005930",
            side="buy",
            quantity=1.0,
            order_type="stop",
            stop_price=200.0,
        )
    )
    await s.stop_order_manager.on_price_update(
        "005930", 100.0, account_id="live-a", is_exchange_tick=True
    )
    assert cap.of(StopOrderExpiredEvent) == []
    session_open["value"] = False
    await _wait_for(lambda: bool(cap.of(StopOrderExpiredEvent)), guard=5.0)

    assert len(sweeps) == 1
    expired = cap.of(StopOrderExpiredEvent)
    assert [(e.account_id, e.reason) for e in expired] == [("live-a", "session_ended")]


async def test_market_buy_reserve_uses_price_of_own_account(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시장가 매수의 예약액은 주문 계좌의 현재가로 계산된다(계좌별 resolver 주입)."""
    asm = await assemble(
        [
            _kis_account("kv-a", mode=TradingMode.VIRTUAL),
            _kis_account("kv-b", mode=TradingMode.VIRTUAL),
        ]
    )
    s = asm.s
    quotes = {"kv-a": 100.0, "kv-b": 300.0}
    asked: list[tuple[str, str]] = []

    async def _price(symbol: str, *, account_id: str) -> float:
        asked.append((symbol, account_id))
        return quotes[account_id]

    monkeypatch.setattr(s.api_gateway, "get_current_price", _price)
    await _fund(s, "kv-a", "bot-1")
    cap = _capture(s, OrderApprovedEvent, OrderRejectedEvent)

    await s.eventbus.publish(
        _request("kv-a", order_type="market", price=None, quantity=10.0)
    )

    assert cap.of(OrderRejectedEvent) == []
    approved = cap.of(OrderApprovedEvent)
    assert [e.reserved_amount for e in approved] == [1000.0]
    assert ("005930", "kv-a") in asked
    assert all(account_id == "kv-a" for _, account_id in asked)


# ── 부팅 때 봇 복원 (#2813) ───────────────────────────────────────────────────

_RESTORE_SOURCE = """
from ante.strategy import Strategy, StrategyMeta


class Restored(Strategy):
    meta = StrategyMeta(
        name="restored", version="1.0.0", description="x", exchange="TEST"
    )

    async def on_step(self, context):
        return []
"""


async def _seed_bot_row(asm: _Assembly) -> None:
    from ante.strategy import StrategyMeta
    from ante.strategy.registry import StrategyRegistry

    source = asm.config_dir / "restored.py"
    source.write_text(_RESTORE_SOURCE, encoding="utf-8")
    registry = StrategyRegistry(asm.s.db)
    await registry.initialize()
    record = await registry.register(
        source, StrategyMeta(name="restored", version="1.0.0", description="x")
    )
    await asm.s.db.execute(
        "INSERT INTO bots (bot_id, name, strategy_id, account_id, config_json,"
        " status) VALUES ('b1', 'b1', ?, 'test', '{}', 'running')",
        (record.strategy_id,),
    )


async def test_bots_in_db_are_restored_as_created_before_ipc(
    assemble: AssembleFn,
) -> None:
    """조립 경로가 DB의 봇을 IPC 앞에서 ``created`` 로 복원한다."""
    asm = await assemble([], before_gateway=_seed_bot_row)

    client = IPCClient(str(asm.s.config.runtime_socket_path()), timeout=5.0)
    response = await client.send("bot.info", {"bot_id": "b1"})

    assert response["status"] == "ok", response
    assert response["result"]["bot"]["status"] == "created"
    assert asm.s.bot_manager.get_bot("b1").strategy is None


async def test_restore_step_is_noop_without_bot_manager() -> None:
    """봇 관리자가 없으면 복원 단계는 아무것도 하지 않는다."""
    await main_module._restore_bots(main_module.Services())


# ── _init_core·_init_ipc 의 경로 ─────────────────────────────────────────────


async def test_init_core_places_relative_db_path_under_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """상대 db.path 는 cwd 가 아니라 config_dir 기준으로 풀려, cold-path CLI 가
    보는 DB 와 같은 파일을 연다."""
    import click

    from ante.cli.main import cli, get_db_path

    monkeypatch.setattr(core_log_mod, "setup_logging", lambda config: None)
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    config_dir = tmp_path / "config"
    elsewhere = tmp_path / "cwd"
    config_dir.mkdir()
    elsewhere.mkdir()
    (config_dir / "system.toml").write_text('[db]\npath = "var/ante.db"\n')
    monkeypatch.chdir(elsewhere)
    s = main_module.Services(config=Config.load(config_dir=config_dir))

    await main_module._init_core(s)
    try:
        cli_db = get_db_path(click.Context(cli, obj={"config_dir": config_dir}))
        assert cli_db == str(config_dir / "var" / "ante.db")
        assert Path(cli_db).exists()
        assert not (elsewhere / "var").exists()
    finally:
        assert s.db is not None
        await s.db.close()


async def test_init_core_reuses_config_loaded_by_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """_init_core 는 이미 로드된 Config 를 다시 읽지 않고 그 설정으로 DB 를 연다."""
    monkeypatch.setattr(core_log_mod, "setup_logging", lambda config: None)
    loaded_dir = tmp_path / "loaded"
    env_dir = tmp_path / "env"
    loaded_dir.mkdir()
    env_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_dir))
    db_file = loaded_dir / "custom.db"
    config = Config(
        static={"db": {"path": str(db_file)}}, secrets={}, config_dir=loaded_dir
    )
    s = main_module.Services(config=config)

    await main_module._init_core(s)
    try:
        assert db_file.exists()
        assert not (env_dir / "db").exists()
        assert s.config is config
    finally:
        assert s.db is not None
        await s.db.close()


async def test_ipc_server_listens_on_runtime_socket_path(
    assemble: AssembleFn,
) -> None:
    """IPC 서버는 기본값 ``<config_dir>/run/ante.sock`` 에서 요청을 받고, CLI 의
    소켓 resolver 도 같은 경로를 낸다."""
    from ante.cli.commands.ipc_helpers import get_socket_path

    asm = await assemble([])
    socket_path = get_socket_path(asm.config_dir)
    assert socket_path == str(asm.config_dir / "run" / "ante.sock")

    client = IPCClient(socket_path, timeout=5.0)
    response = await client.send("bot.positions", {"bot_id": "missing"})

    assert response["status"] == "error"
    assert response["error"]["code"] == "BOT_NOT_FOUND"


async def test_ipc_server_listens_on_overridden_socket_path(
    assemble: AssembleFn,
) -> None:
    """``[runtime] socket_path`` override 가 있으면 IPC 서버는 그 경로에서 요청을
    받고, CLI 의 소켓 resolver 도 같은 경로를 낸다."""
    from ante.cli.commands.ipc_helpers import get_socket_path

    asm = await assemble([], static={"runtime": {"socket_path": "sock/alt.sock"}})
    (asm.config_dir / "system.toml").write_text(
        '[runtime]\nsocket_path = "sock/alt.sock"\n'
    )
    socket_path = get_socket_path(asm.config_dir)
    assert socket_path == str(asm.config_dir / "sock" / "alt.sock")
    assert not (asm.config_dir / "run" / "ante.sock").exists()

    client = IPCClient(socket_path, timeout=5.0)
    response = await client.send("bot.positions", {"bot_id": "missing"})

    assert response["error"]["code"] == "BOT_NOT_FOUND"


# ── _init_gateway 의 스트림 연동 (#2804) ──────────────────────────────────────


class _RecordingStreamClient:
    """KISStreamClient 더블. 생성 인자와 해제를 기록하고 외부에 접속하지 않는다."""

    instances: list[_RecordingStreamClient] = []

    def __init__(self, websocket_url: str, *args: Any, **kwargs: Any) -> None:
        self.websocket_url = websocket_url
        self.account_id = kwargs.get("account_id", "")
        self.disconnected = False
        _RecordingStreamClient.instances.append(self)

    is_connected = False
    subscribed_symbols: set[str] = set()

    def on_price(self, callback: Any) -> None:
        return None

    def on_execution(self, callback: Any) -> None:
        return None

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        self.disconnected = True

    async def subscribe_execution(self) -> None:
        return None

    async def subscribe(self, symbol: str) -> bool:
        return True

    async def unsubscribe(self, symbol: str) -> None:
        return None


async def test_live_account_stream_is_registered_and_closed_on_shutdown(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LIVE kis-domestic 계좌는 어댑터의 URL로 스트림이 등록되고 종료가 해제한다.

    가상 계좌에는 스트림이 없다."""
    import ante.broker.kis_stream as kis_stream_mod

    url = "ws://ops.koreainvestment.com:31000"
    _RecordingStreamClient.instances = []
    monkeypatch.setattr(kis_stream_mod, "KISStreamClient", _RecordingStreamClient)
    monkeypatch.setattr(_FakeBroker, "websocket_url", url)
    asm = await assemble(
        [_kis_account("live-a"), _kis_account("virt-a", mode=TradingMode.VIRTUAL)]
    )

    assert list(asm.s.stream_integrations) == ["live-a"]
    clients = _RecordingStreamClient.instances
    assert [(c.account_id, c.websocket_url) for c in clients] == [("live-a", url)]

    await _shutdown_in_test(asm)

    assert _RecordingStreamClient.instances[0].disconnected


async def test_assembled_stream_does_not_poll_gateway_after_disconnect(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """조립된 스트림 연동은 끊김 뒤에도 REST 폴링을 시작하지 않는다 (#2804).

    폴링은 주문과 같은 계좌별 호출 한도를 써서 주문을 늦추므로 켜지 않는다."""
    import ante.broker.kis_stream as kis_stream_mod
    from ante.eventbus.events import StreamDisconnectedEvent

    _RecordingStreamClient.instances = []
    monkeypatch.setattr(kis_stream_mod, "KISStreamClient", _RecordingStreamClient)
    monkeypatch.setattr(
        _FakeBroker, "websocket_url", "ws://ops.koreainvestment.com:31000"
    )
    asm = await assemble([_kis_account("live-a")])
    s = asm.s
    assert s.api_gateway is not None
    price_calls: list[str] = []

    async def _price(symbol: str, *, account_id: str) -> float:
        price_calls.append(symbol)
        return 100.0

    monkeypatch.setattr(s.api_gateway, "get_current_price", _price)
    await s.eventbus.publish(
        OrderApprovedEvent(
            account_id="live-a",
            order_id="stop-1",
            bot_id="bot-1",
            strategy_id="strategy-1",
            symbol="005930",
            side="sell",
            quantity=1.0,
            order_type="stop",
            stop_price=50.0,
        )
    )
    integration = s.stream_integrations["live-a"]

    await s.eventbus.publish(
        StreamDisconnectedEvent(account_id="live-a", broker="kis", reason="test")
    )
    for _ in range(20):
        await asyncio.sleep(0)

    assert price_calls == []
    assert integration._fallback_task is None
    assert not integration.is_fallback_active


# ── _init_gateway 의 기동 순서와 readiness ────────────────────────────────────


async def test_reconcile_starts_only_after_every_fill_catch_up(
    assemble: AssembleFn,
) -> None:
    """모든 계좌의 체결 카치업이 끝난 뒤에야 ReconcileScheduler 가 시작한다."""
    asm = await assemble([_kis_account("live-a"), _kis_account("live-b")])

    catch_ups = [i for i, e in enumerate(asm.log) if e.startswith("fill_catch_up:")]
    starts = [i for i, e in enumerate(asm.log) if e.startswith("reconcile_start:")]
    assert len(catch_ups) == 2 and len(starts) == 2, asm.log
    assert max(catch_ups) < min(starts), asm.log


async def test_startup_reconcile_defers_external_buy_per_failed_catch_up(
    assemble: AssembleFn,
) -> None:
    """체결 카치업에 실패한 계좌마다 기동 대사가 외부 매수 분류를 미루고,
    성공한 계좌는 미루지 않는다(다른 계좌의 실패 표시는 지워지지 않는다)."""
    asm = await assemble(
        [_kis_account("live-a"), _kis_account("live-b"), _kis_account("live-c")],
        fill_succeeds={"live-a": False, "live-b": False, "live-c": True},
    )

    first_runs: dict[str, bool] = {}
    for account_id, skip in asm.reconcile_runs:
        first_runs.setdefault(account_id, skip)
    assert first_runs == {"live-a": True, "live-b": True, "live-c": False}


async def test_global_fill_skip_marks_exempt_ready_and_live_not_ready(
    assemble: AssembleFn,
) -> None:
    """연결된 broker 가 없어 체결 복구를 통째로 건너뛰면, 면제 계좌는 ready 로,
    LIVE 계좌는 사유와 함께 not_ready 로 표시된다."""
    asm = await assemble(
        [_kis_account("live-a"), _kis_account("kv-a", mode=TradingMode.VIRTUAL)],
        connect_errors={"live-a": RuntimeError("connect refused")},
    )
    readiness = asm.s.runtime_readiness

    assert readiness.is_ready("kv-a", ReadinessFlag.FILL_RECONCILE)
    assert not readiness.is_ready("live-a", ReadinessFlag.FILL_RECONCILE)
    assert (
        readiness.get_reason("live-a", ReadinessFlag.FILL_RECONCILE)
        == "fill_init_skipped_no_broker"
    )


async def test_outbox_rows_left_unpublished_are_redelivered_without_broker(
    assemble: AssembleFn,
) -> None:
    """연결된 broker 가 없어도 기동 시 미발행 outbox 행이 재전달되고, 이미 구독된
    시스템 소비자(TradeRecorder 의 체결 알림)가 그 이벤트를 받는다."""
    seen: list[OrderFilledEvent] = []
    notes: list[NotificationEvent] = []

    async def _seed(asm: _Assembly) -> None:
        assert asm.s.eventbus is not None
        asm.s.eventbus.subscribe(OrderFilledEvent, seen.append, priority=-1000)
        asm.s.eventbus.subscribe(NotificationEvent, notes.append, priority=-1000)
        await asm.s.fill_outbox.enqueue(
            fill_dedup_key="seed-order:1.0",
            payload={
                "account_id": "test",
                "order_id": "seed-order",
                "broker_order_id": "BRK-seed",
                "bot_id": "bot-1",
                "strategy_id": "strategy-1",
                "symbol": "005930",
                "side": "buy",
                "quantity": 1.0,
                "price": 100.0,
            },
        )

    await assemble([], before_gateway=_seed)

    assert [e.order_id for e in seen] == ["seed-order"]
    fill_notes = [n for n in notes if n.category == "trade"]
    assert [n.title for n in fill_notes] == ["체결 완료 (매수)"]
    assert "bot-1" in fill_notes[0].message


async def test_outbox_publisher_redelivers_before_starting_drain_loop(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """퍼블리셔는 기동 재전달을 마친 뒤에 주기 드레인 루프를 시작한다."""
    calls: list[str] = []

    def _record(asm: _Assembly) -> None:
        publisher = asm.s.fill_outbox_publisher
        real_catch_up = publisher.catch_up_once
        real_start = publisher.start

        async def _catch_up() -> int:
            calls.append("catch_up_once")
            return await real_catch_up()

        async def _start() -> None:
            calls.append("start")
            await real_start()

        monkeypatch.setattr(publisher, "catch_up_once", _catch_up)
        monkeypatch.setattr(publisher, "start", _start)

    await assemble([], before_gateway=_record)

    assert calls == ["catch_up_once", "start"]


async def test_self_healing_starts_after_every_startup_init_step(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """self-healing 루프는 treasury·체결 복구·outbox·대사 기동이 모두 끝난 뒤에
    시작한다."""
    order: list[str] = []

    def _after(name: str) -> None:
        real = getattr(main_module, name)

        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            result = await real(*args, **kwargs)
            order.append(name)
            return result

        monkeypatch.setattr(main_module, name, _wrapped)

    for name in (
        "_init_treasury_sync",
        "_init_fill_recovery_schedulers",
        "_init_fill_outbox_publisher",
        "_init_reconcile_scheduler",
    ):
        _after(name)
    real_start = main_module._start_readiness_self_healing

    def _start(s: Any, accounts: list[Any]) -> None:
        order.append("_start_readiness_self_healing")
        real_start(s, accounts)

    monkeypatch.setattr(main_module, "_start_readiness_self_healing", _start)

    asm = await assemble([_kis_account("live-a")])

    assert asm.s.readiness_self_healing_task is not None
    assert "_start_readiness_self_healing" in order, order
    started_at = order.index("_start_readiness_self_healing")
    for step in (
        "_init_treasury_sync",
        "_init_fill_recovery_schedulers",
        "_init_fill_outbox_publisher",
        "_init_reconcile_scheduler",
    ):
        assert step in order[:started_at], (step, order)


async def test_account_down_at_startup_recovers_after_broker_returns(
    assemble: AssembleFn,
) -> None:
    """기동 때 연결에 실패한 LIVE 계좌는 broker 가 돌아오면 self-healing 이
    ready 로 되돌린다."""
    asm = await assemble(
        [_kis_account("live-a")],
        static={
            "readiness": {
                "self_healing_interval_seconds": 0,
                "self_healing_backoff_base_seconds": 0,
                "self_healing_backoff_max_seconds": 0,
            }
        },
        connect_errors={"live-a": RuntimeError("connect refused")},
    )
    readiness = asm.s.runtime_readiness
    assert not readiness.is_ready("live-a", ReadinessFlag.BROKER)
    down = asm.brokers["live-a"]
    connects_at_startup = down.connects
    # 내려가 있는 동안 루프가 다시 연결을 시도한다.
    await _wait_for(lambda: down.connects > connects_at_startup)
    assert not readiness.is_ready("live-a", ReadinessFlag.BROKER)

    down.connect_error = None
    await _wait_for(
        lambda: readiness.active_trading_ready(
            "live-a", broker_type="kis-domestic", trading_mode=TradingMode.LIVE
        )
    )

    assert readiness.is_ready("live-a", ReadinessFlag.BROKER)


async def test_reconcile_disabled_lets_orders_through_on_every_account(
    assemble: AssembleFn,
) -> None:
    """reconcile.enabled=false 면 기동이 전 계좌의 reconcile 요구를 면제해, 기동이
    끝난 시점부터 모든 LIVE 계좌의 주문이 게이트를 지난다.

    self-healing 도 not_ready 인 reconcile 을 ready 로 바꾸지만, 앞 계좌(live-a)가
    내려가 있고 backoff 가 1시간이면 루프는 그 계좌에서 기다린다. 그 동안 뒤 계좌
    (live-b, live-c)의 주문은 기동의 표시로만 통과한다.
    """
    asm = await assemble(
        [_kis_account("live-a"), _kis_account("live-b"), _kis_account("live-c")],
        static={
            "reconcile": {"enabled": False},
            "readiness": {
                "self_healing_interval_seconds": 3600,
                "self_healing_backoff_base_seconds": 3600,
                "self_healing_backoff_max_seconds": 3600,
            },
        },
        connect_errors={"live-a": RuntimeError("connect refused")},
    )
    assert [a.account_id for a in await asm.s.account_service.list()] == [
        "live-a",
        "live-b",
        "live-c",
    ]
    # 기동의 connect 1회 뒤 self-healing 이 live-a 를 한 번 더 시도하고 backoff 에
    # 들어갈 때까지 기다린다.
    down = asm.brokers["live-a"]
    await _wait_for(lambda: down.connects >= 2)

    assert asm.reconcile_runs == []
    # 내려간 계좌(live-a)도 reconcile 요구는 면제된다(그 계좌 주문은 broker 로 막힌다).
    readiness = asm.s.runtime_readiness
    assert readiness.is_ready("live-a", ReadinessFlag.RECONCILE)
    assert not readiness.is_ready("live-a", ReadinessFlag.BROKER)
    for account_id in ("live-b", "live-c"):
        submitted = await _submit_live_buy(asm, account_id)
        assert submitted.account_id == account_id


# ── _shutdown 의 정리 순서 ────────────────────────────────────────────────────


async def test_shutdown_stops_stop_order_manager_between_ipc_gate_and_bots(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """종료 때 StopOrderManager.stop() 은 IPC 새 연결 차단 뒤, 봇 전체 중지 앞이다."""
    asm = await assemble([])
    s = asm.s
    order: list[str] = []

    def _track(obj: Any, name: str) -> None:
        real = getattr(obj, name)

        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            order.append(name)
            return await real(*args, **kwargs)

        monkeypatch.setattr(obj, name, _wrapped)

    _track(s.ipc_server, "stop_accepting")
    _track(s.stop_order_manager, "stop")
    _track(s.bot_manager, "stop_all")

    await _shutdown_in_test(asm)

    assert order == ["stop_accepting", "stop", "stop_all"]


async def test_shutdown_disconnects_only_already_connected_brokers(
    assemble: AssembleFn,
) -> None:
    """종료는 이미 연결된 broker 만 끊고, 연결되지 않았던 계좌에는 새로 연결하지
    않는다."""
    asm = await assemble(
        [_kis_account("live-a"), _kis_account("live-b")],
        static={
            "readiness": {
                "self_healing_interval_seconds": 3600,
                "self_healing_backoff_base_seconds": 3600,
                "self_healing_backoff_max_seconds": 3600,
            }
        },
        connect_errors={"live-b": RuntimeError("connect refused")},
    )
    connected = asm.brokers["live-a"].built
    assert len(connected) == 1
    down = asm.brokers["live-b"]
    down.connect_error = None
    connects_before = down.connects

    await _shutdown_in_test(asm)

    assert connected[0].disconnected is True
    assert down.connects == connects_before


async def test_shutdown_stops_fill_outbox_publisher(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """종료는 FillOutboxPublisher 를 멈춘다(graceful stop 을 shutdown 이 맡는다)."""
    asm = await assemble([])
    s = asm.s
    stops: list[bool] = []
    real_stop = s.fill_outbox_publisher.stop

    async def _stop() -> None:
        stops.append(True)
        await real_stop()

    monkeypatch.setattr(s.fill_outbox_publisher, "stop", _stop)

    await _shutdown_in_test(asm)

    assert stops == [True]


async def test_ipc_bot_status_enriches_positions(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IPC bot.status 는 trade_service 로 봇 포지션을 보강한다."""
    asm = await assemble([_kis_account("live-a")])
    submitted = await _submit_live_buy(asm, "live-a")
    cap = _capture(asm.s, OrderFilledEvent)
    await _apply_fill(asm, submitted, 10.0)
    await _wait_for(lambda: bool(cap.of(OrderFilledEvent)), guard=5.0)
    bot = SimpleNamespace(
        bot_id="bot-1",
        config=SimpleNamespace(account_id="live-a"),
        get_info=lambda: {
            "bot_id": "bot-1",
            "strategy_id": "strategy-1",
            "account_id": "live-a",
        },
    )
    monkeypatch.setattr(
        asm.s.bot_manager,
        "get_bot",
        lambda bot_id: bot if bot_id == "bot-1" else None,
    )

    client = IPCClient(str(asm.s.config.runtime_socket_path()), timeout=5.0)
    response = await client.send("bot.status", {"bot_id": "bot-1"})

    assert response["status"] == "ok", response
    positions = response["result"]["bot"]["positions"]
    assert [(p["symbol"], p["quantity"]) for p in positions] == [("005930", 10.0)]


# ── 계좌마다 일일 보고 (#3089) ────────────────────────────────────────────────


async def _seed_test_account(seed: AccountService) -> None:
    await seed.create_default_test_account()


async def _seed_suspended_test_account(seed: AccountService) -> None:
    await seed.create_default_test_account()
    await seed.suspend("test", reason="#3089", suspended_by="test")


async def _snapshot_rows(s: main_module.Services) -> dict[str, int]:
    rows = await s.db.fetch_all(
        "SELECT account_id, COUNT(*) AS n FROM treasury_daily_snapshots"
        " GROUP BY account_id"
    )
    return {r["account_id"]: r["n"] for r in rows}


@pytest.mark.parametrize(
    ("before_seed", "kis_a_suspended", "expected_order"),
    [
        (_seed_suspended_test_account, False, ["test", "kis-a", "kis-b"]),
        (_seed_test_account, False, ["test", "kis-a", "kis-b"]),
        (None, True, ["kis-a", "kis-b"]),
    ],
    ids=["test_first_suspended", "test_first_active", "kis_first_suspended"],
)
async def test_every_account_gets_its_own_daily_report_and_snapshot(
    assemble: AssembleFn,
    before_seed: Callable[[AccountService], Awaitable[None]] | None,
    kis_a_suspended: bool,
    expected_order: list[str],
) -> None:
    """삭제되지 않은 계좌마다 스케줄러가 하나씩 생기고, 보고 한 바퀴 뒤 계좌마다
    스냅샷이 1행 생긴다. 첫 계좌가 test·정지 계좌여도 다른 계좌를 막지 않는다."""

    async def _seed(seed: AccountService) -> None:
        if before_seed is not None:
            await before_seed(seed)

    asm = await assemble(
        [_kis_account("kis-a"), _kis_account("kis-b")], before_seed=_seed
    )
    s = asm.s
    if kis_a_suspended:
        await s.account_service.suspend("kis-a", reason="#3089", suspended_by="t")
    assert [a.account_id for a in await s.account_service.list()] == expected_order

    assert list(s.daily_report_schedulers) == expected_order
    for account_id, scheduler in s.daily_report_schedulers.items():
        assert scheduler._account_id == account_id
        assert scheduler._task.get_name() == f"daily-report-scheduler:{account_id}"
    assert await _snapshot_rows(s) == {}

    for scheduler in s.daily_report_schedulers.values():
        await scheduler.run_once(target_date=date(2026, 3, 19))

    assert await _snapshot_rows(s) == dict.fromkeys(expected_order, 1)


async def test_second_account_daily_loss_limit_judges_with_its_own_snapshot(
    assemble: AssembleFn,
) -> None:
    """둘째 계좌의 일일 손실 한도가 그 계좌의 전일 스냅샷으로 판정해 주문을 거부한다.
    전날은 규칙 엔진과 같은 기준(고정한 시계의 ``now(None)``)으로 잡는다."""
    rules = [
        {"type": "trading_hours", "enabled": False},
        {"type": "daily_loss_limit", "max_daily_loss_percent": 0.05},
    ]
    asm = await assemble(
        [_kis_account("kis-a"), _kis_account("kis-b")],
        static={"accounts": {"kis-a": {"rules": rules}, "kis-b": {"rules": rules}}},
    )
    s = asm.s
    await _fund(s, "kis-b", "bot-1")
    manual = ManualClock(datetime(2026, 3, 20, 3, 0, tzinfo=UTC))
    with clock.use_clock(manual):
        yesterday = clock.now(None).date() - timedelta(days=1)
        for target, eval_amount in (
            (yesterday - timedelta(days=1), 10_000_000.0),
            (yesterday, 8_000_000.0),
        ):
            for treasury in s.treasury_manager.list_all():
                await treasury.sync_balance(
                    {"cash": 2_000_000.0, "eval_amount": eval_amount}
                )
            for scheduler in s.daily_report_schedulers.values():
                await scheduler.run_once(target_date=target)
        cap = _capture(s, OrderRejectedEvent, OrderSubmittedEvent)

        await s.eventbus.publish(_request("kis-b"))

    assert cap.of(OrderSubmittedEvent) == []
    (rejected,) = cap.of(OrderRejectedEvent)
    assert rejected.account_id == "kis-b"
    assert "Daily loss limit" in rejected.reason


async def test_shutdown_stops_every_daily_report_scheduler_even_if_one_fails(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 ``_shutdown`` 이 모든 계좌의 스케줄러를 멈춘다. 한 스케줄러의 종료가
    예외여도 나머지는 멈춘다."""
    asm = await assemble([_kis_account("kis-a"), _kis_account("kis-b")])
    schedulers = dict(asm.s.daily_report_schedulers)
    first = schedulers["kis-a"]
    real_stop = first.stop

    async def _failing_stop() -> None:
        await real_stop()
        raise RuntimeError("stop failed (#3089)")

    monkeypatch.setattr(first, "stop", _failing_stop)

    await _shutdown_in_test(asm)

    assert list(schedulers) == ["kis-a", "kis-b"]
    assert [sch._task for sch in schedulers.values()] == [None, None]
    assert asm.s.daily_report_schedulers == {}


async def test_one_account_report_failure_does_not_block_other_accounts(
    assemble: AssembleFn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """한 계좌의 보고가 예외로 끝나도 다른 계좌의 보고·스냅샷은 생긴다."""
    asm = await assemble([_kis_account("kis-a"), _kis_account("kis-b")])
    s = asm.s

    async def _broken(snapshot_date: str) -> dict[str, Any] | None:
        raise RuntimeError("snapshot read failed (#3089)")

    monkeypatch.setattr(s.treasury_manager.get("kis-a"), "get_daily_snapshot", _broken)
    results: dict[str, Any] = {}
    for account_id, scheduler in s.daily_report_schedulers.items():
        try:
            results[account_id] = await scheduler.run_once(
                target_date=date(2026, 3, 19)
            )
        except RuntimeError as exc:
            results[account_id] = str(exc)

    assert results == {"kis-a": "snapshot read failed (#3089)", "kis-b": False}
    assert await _snapshot_rows(s) == {"kis-b": 1}


async def test_broken_trading_hours_end_skips_only_that_account(
    assemble: AssembleFn, caplog: pytest.LogCaptureFixture
) -> None:
    """한 계좌의 거래 시간 종료가 깨져 있으면 조립은 예외 없이 끝나고, 그 계좌만
    스케줄러 없이 넘어간다. 건너뛴 계좌 ID 는 ERROR 로그에 남는다."""
    broken = _kis_account("kis-a")
    broken.trading_hours_end = "broken"
    with caplog.at_level(logging.ERROR, logger="ante.main"):
        asm = await assemble([broken, _kis_account("kis-b")])

    assert list(asm.s.daily_report_schedulers) == ["kis-b"]
    errors = [
        r
        for r in caplog.records
        if r.name == "ante.main" and r.levelno >= logging.ERROR
    ]
    assert any("kis-a" in r.getMessage() for r in errors), [
        r.getMessage() for r in errors
    ]


async def test_daily_report_scheduler_assembly_with_no_accounts() -> None:
    """삭제되지 않은 계좌가 없으면 스케줄러는 0개이고 예외가 없다(서비스 직접 구성 —
    ``assemble`` 은 첫 부팅 경로가 test 계좌를 만들어 0개를 만들 수 없다)."""
    from ante.core import Database
    from ante.eventbus import EventBus

    with tempfile.TemporaryDirectory(prefix="aw", dir="/tmp") as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        await db.connect()
        try:
            bus = EventBus()
            accounts = AccountService(db=db, eventbus=bus)
            await accounts.initialize()
            s = main_module.Services(
                db=db, eventbus=bus, config=Config(static={}, secrets={})
            )
            s.account_service = accounts

            await main_module._init_daily_report_scheduler(s)

            assert await accounts.list() == []
            assert s.daily_report_schedulers == {}
        finally:
            await db.close()
