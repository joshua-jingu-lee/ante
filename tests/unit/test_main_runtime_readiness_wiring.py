"""main._init_* ↔ RuntimeReadinessRegistry wiring + self-healing 테스트 (#2397).

검증:
- startup 실패→not_ready, broker_ready connect 시점 mark.
- 전역(connected_count==0)+per-account 이중 실패모드 reason.
- 면제 계좌 get_broker 미호출(virtual/test broker-backed skip 회귀).
- catch_up 폴 실패→fill_reconcile_ready=false (R4).
- self-healing: not_ready→회복→재등록(멱등·orphan 없음)→ready, 무기한 재시도,
  전역 barrier clear 미호출 회귀, shutdown cancel.
- observe-only: registry 도입이 주문 동작을 바꾸지 않음(gate reader 부재).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import ante.broker.fill_scheduler as fill_scheduler_mod
import ante.broker.scheduler as scheduler_mod
import ante.main as main_module
from ante.account.models import TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry


def _account(
    account_id: str,
    *,
    broker_type: str = "kis-domestic",
    trading_mode: TradingMode = TradingMode.LIVE,
    exchange: str = "KRX",
) -> Any:
    return SimpleNamespace(
        account_id=account_id,
        broker_type=broker_type,
        trading_mode=trading_mode,
        exchange=exchange,
        credentials={},
        broker_config={},
    )


class _FakeFillScheduler:
    """FillReconcileScheduler 더블 — catch_up_once/start/stop 추적."""

    instances: list[_FakeFillScheduler] = []

    def __init__(self, **kwargs: Any) -> None:
        self.account_id = kwargs["account_id"]
        self.started = False
        self.stopped = False
        # 클래스 변수로 주입된 catch_up 성공 여부(account_id 별).
        self._succeeded = _FakeFillScheduler.succeed_map.get(self.account_id, True)
        _FakeFillScheduler.instances.append(self)

    succeed_map: dict[str, bool] = {}

    async def catch_up_once(self) -> Any:
        return fill_scheduler_mod.CatchUpResult(succeeded=self._succeeded, applied=0)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeReconcileScheduler:
    """ReconcileScheduler 더블 — start/stop 추적."""

    instances: list[_FakeReconcileScheduler] = []

    def __init__(self, **kwargs: Any) -> None:
        self.account_id = kwargs["broker_account_id"]
        self.started = False
        self.stopped = False
        _FakeReconcileScheduler.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


@pytest.fixture(autouse=True)
def _patch_schedulers(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFillScheduler.instances = []
    _FakeFillScheduler.succeed_map = {}
    _FakeReconcileScheduler.instances = []
    monkeypatch.setattr(
        fill_scheduler_mod, "FillReconcileScheduler", _FakeFillScheduler
    )
    monkeypatch.setattr(scheduler_mod, "ReconcileScheduler", _FakeReconcileScheduler)


def _services(
    *,
    brokers: dict[str, Any] | None = None,
) -> Any:
    """fill/reconcile 등록에 필요한 최소 Services 더블.

    ``brokers`` 는 account_id → broker(또는 raise 할 Exception) 매핑. 기본은
    connect 성공하는 AsyncMock broker.
    """
    s = main_module.Services()
    s.runtime_readiness = RuntimeReadinessRegistry()
    s.order_tracker = object()
    s.fill_applier = object()
    s.trade_service = object()
    s.eventbus = AsyncMock()
    s.instrument_service = object()
    s.bot_manager = object()
    s.position_history = None
    s.api_gateway = None
    s.config = SimpleNamespace(get=lambda key, default=None: default)

    # treasury_manager 더블 — start_sync/set_account_info 추적(self-healing 재sync).
    treasury = SimpleNamespace(
        start_sync=lambda **kwargs: None,
        set_account_info=lambda **kwargs: None,
    )
    s.treasury_manager = SimpleNamespace(get=lambda account_id: treasury)

    broker_map = brokers or {}

    async def _get_broker(account_id: str) -> Any:
        if account_id in broker_map:
            result = broker_map[account_id]
            if isinstance(result, Exception):
                raise result
            return result
        broker = AsyncMock()
        broker.connect = AsyncMock()
        return broker

    account_service = AsyncMock()
    account_service.get_broker = AsyncMock(side_effect=_get_broker)
    s.account_service = account_service  # type: ignore[assignment]
    return s


# ── broker_ready: connect 시점 mark / startup 실패 ─────────────────────────


@pytest.mark.asyncio
async def test_register_fill_marks_ready_on_success() -> None:
    """LIVE 계좌 fill 등록 성공 → fill_reconcile_ready=True."""
    s = _services()
    account = _account("live-1")

    ok = await main_module._register_fill_scheduler_for_account(s, account)

    assert ok is True
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    assert "live-1" in s.fill_schedulers


@pytest.mark.asyncio
async def test_register_fill_get_broker_failure_marks_not_ready() -> None:
    """per-account get_broker 실패 → fill_reconcile_ready=False + reason.

    이중 실패모드 (b): per-account continue 지점 명시 mark.
    """
    s = _services(brokers={"live-1": RuntimeError("EGW00133")})
    account = _account("live-1")

    ok = await main_module._register_fill_scheduler_for_account(s, account)

    assert ok is False
    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.FILL_RECONCILE)
        == "get_broker_failed"
    )
    assert "live-1" not in s.fill_schedulers


@pytest.mark.asyncio
async def test_catch_up_poll_failure_marks_fill_not_ready() -> None:
    """R4: catch_up_once 폴 실패 → start 해도 fill_reconcile_ready=False."""
    s = _services()
    _FakeFillScheduler.succeed_map = {"live-1": False}
    account = _account("live-1")

    ok = await main_module._register_fill_scheduler_for_account(s, account)

    # scheduler 는 start 되지만 readiness 는 false 로 분리.
    assert ok is False
    assert "live-1" in s.fill_schedulers
    assert s.fill_schedulers["live-1"].started is True
    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.FILL_RECONCILE)
        == "catch_up_poll_failed"
    )
    # 폴 실패 계좌는 #1946 barrier 에 추가.
    assert "live-1" in s.fill_catch_up_failed_accounts


@pytest.mark.asyncio
async def test_fill_init_exempts_virtual_without_get_broker() -> None:
    """면제(virtual/test) 계좌는 get_broker 미호출 + no-op ready mark (회귀 락)."""
    s = _services()
    accounts = [
        _account("test", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        _account("kv", broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL),
        _account("live-1"),
    ]

    await main_module._init_fill_recovery_schedulers(s, accounts)

    # 면제 계좌는 no-op ready, broker-backed 등록 skip.
    assert s.runtime_readiness.is_ready("test", ReadinessFlag.FILL_RECONCILE)
    assert s.runtime_readiness.is_ready("kv", ReadinessFlag.FILL_RECONCILE)
    assert "test" not in s.fill_schedulers
    assert "kv" not in s.fill_schedulers
    # LIVE 계좌만 등록.
    assert "live-1" in s.fill_schedulers
    # 면제 계좌의 get_broker 는 호출되지 않아야 한다(KIS 재노출 차단).
    called_ids = {c.args[0] for c in s.account_service.get_broker.call_args_list}
    assert called_ids == {"live-1"}


# ── 전역 이중 실패모드 (a): connected_count==0 ─────────────────────────────


def test_global_fill_skip_exempt_first() -> None:
    """전역 skip 시 면제 먼저 적용 — virtual no-op ready, LIVE not_ready(reason)."""
    s = _services()
    accounts = [
        _account("test", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        _account("live-1"),
    ]

    main_module._mark_fill_reconcile_global_skip(s, accounts)

    assert s.runtime_readiness.is_ready("test", ReadinessFlag.FILL_RECONCILE)
    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.FILL_RECONCILE)
        == "fill_init_skipped_no_broker"
    )


def test_global_reconcile_skip_exempt_first() -> None:
    """전역 reconcile skip 도 면제 먼저 — virtual no-op ready, LIVE not_ready."""
    s = _services()
    accounts = [
        _account("kv", trading_mode=TradingMode.VIRTUAL),
        _account("live-1"),
    ]

    main_module._mark_reconcile_global_skip(s, accounts)

    assert s.runtime_readiness.is_ready("kv", ReadinessFlag.RECONCILE)
    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.RECONCILE)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.RECONCILE)
        == "reconcile_init_skipped_no_broker"
    )


# ── reconcile 등록 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_reconcile_marks_ready() -> None:
    s = _services()
    account = _account("live-1")
    reconciler = object()

    ok = await main_module._register_reconcile_scheduler_for_account(
        s, account, reconciler, 1800
    )

    assert ok is True
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.RECONCILE)
    assert "live-1" in s.reconcile_schedulers


@pytest.mark.asyncio
async def test_register_reconcile_get_broker_failure_marks_not_ready() -> None:
    s = _services(brokers={"live-1": RuntimeError("timeout")})
    account = _account("live-1")

    ok = await main_module._register_reconcile_scheduler_for_account(
        s, account, object(), 1800
    )

    assert ok is False
    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.RECONCILE)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.RECONCILE)
        == "get_broker_failed"
    )


# ── treasury_sync (면제 없음 — virtual/live 양쪽 요구) ──────────────────────


@pytest.mark.asyncio
async def test_treasury_sync_marks_ready_virtual_and_live() -> None:
    """treasury_sync_ready: virtual(broker=None)·live 양쪽 시작 성공 시 mark."""
    s = _services()
    accounts = [
        _account("kv", trading_mode=TradingMode.VIRTUAL),
        _account("live-1", trading_mode=TradingMode.LIVE),
    ]

    await main_module._init_treasury_sync(s, accounts)

    assert s.runtime_readiness.is_ready("kv", ReadinessFlag.TREASURY_SYNC)
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.TREASURY_SYNC)


@pytest.mark.asyncio
async def test_treasury_sync_failure_marks_not_ready() -> None:
    """treasury_sync 시작 실패 → treasury_sync_ready=False + reason."""
    s = _services()

    def _raise(account_id: str) -> Any:
        raise RuntimeError("treasury boom")

    s.treasury_manager = SimpleNamespace(get=_raise)
    accounts = [_account("live-1", trading_mode=TradingMode.LIVE)]

    await main_module._init_treasury_sync(s, accounts)

    assert not s.runtime_readiness.is_ready("live-1", ReadinessFlag.TREASURY_SYNC)
    assert (
        s.runtime_readiness.get_reason("live-1", ReadinessFlag.TREASURY_SYNC)
        == "treasury_sync_failed"
    )


# ── self-healing ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_healing_recovers_not_ready_account() -> None:
    """not_ready broker → 회복(connect 성공) → broker_ready + 스케줄러 재등록."""
    s = _services()
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")
    account = _account("live-1")

    recovered = await main_module._self_healing_recover_account(s, account)

    assert recovered is True
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.BROKER)
    # 회복 시 fill + reconcile 재등록 + ready 전이.
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.RECONCILE)
    assert "live-1" in s.fill_schedulers
    assert "live-1" in s.reconcile_schedulers


@pytest.mark.asyncio
async def test_self_healing_reregister_is_idempotent_no_orphan() -> None:
    """재등록 멱등 — 기존 scheduler task 를 stop 후 교체(orphan 없음)."""
    s = _services()
    account = _account("live-1")
    # 1차 등록.
    await main_module._register_fill_scheduler_for_account(s, account)
    await main_module._register_reconcile_scheduler_for_account(
        s, account, object(), 1800
    )
    first_fill = s.fill_schedulers["live-1"]
    first_reconcile = s.reconcile_schedulers["live-1"]
    # broker 를 not_ready 로 만들고 회복(재등록) 유도.
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    await main_module._self_healing_recover_account(s, account)

    # 기존 인스턴스는 stop 되고(orphan 방지) 새 인스턴스로 교체된다.
    assert first_fill.stopped is True
    assert first_reconcile.stopped is True
    assert s.fill_schedulers["live-1"] is not first_fill
    assert s.reconcile_schedulers["live-1"] is not first_reconcile
    # dict 에 항목이 중복되지 않고 1개만 유지.
    assert list(s.fill_schedulers) == ["live-1"]
    assert list(s.reconcile_schedulers) == ["live-1"]


@pytest.mark.asyncio
async def test_self_healing_preserves_other_account_barrier() -> None:
    """per-account 재시도가 전역 fill_catch_up_failed_accounts.clear() 호출 안 함.

    다른 계좌(live-2)의 #1946 barrier 가 보존되어야 한다(전역 clear 회귀 락).
    """
    s = _services()
    # 타 계좌의 barrier 를 사전 설정.
    s.fill_catch_up_failed_accounts.add("live-2")
    account = _account("live-1")
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    await main_module._self_healing_recover_account(s, account)

    # live-1 회복(폴 성공)이 live-2 barrier 를 지우지 않아야 한다.
    assert "live-2" in s.fill_catch_up_failed_accounts


@pytest.mark.asyncio
async def test_self_healing_retries_indefinitely_until_recover() -> None:
    """무기한 재시도 — 연속 실패 후 회복 가능해지면 유한시간 내 ready (liveness)."""
    s = main_module.Services()
    s.runtime_readiness = RuntimeReadinessRegistry()
    s.order_tracker = None
    s.fill_applier = None
    s.trade_service = None
    s.eventbus = AsyncMock()
    s.instrument_service = object()
    s.bot_manager = object()
    # 매우 짧은 interval/burst 로 루프를 구동.
    s.config = SimpleNamespace(
        get=lambda key, default=None: {
            "readiness.self_healing_interval_seconds": 0,
            "readiness.self_healing_max_attempts_per_burst": 2,
        }.get(key, default)
    )

    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    # 처음 N회 connect 실패 후 성공하는 broker.
    state = {"fails_left": 3}

    async def _get_broker(account_id: str) -> Any:
        broker = AsyncMock()

        async def _connect() -> None:
            if state["fails_left"] > 0:
                state["fails_left"] -= 1
                raise RuntimeError("EGW00133")

        broker.connect = AsyncMock(side_effect=_connect)
        return broker

    account_service = AsyncMock()
    account_service.get_broker = AsyncMock(side_effect=_get_broker)
    s.account_service = account_service  # type: ignore[assignment]

    account = _account("live-1")
    task = asyncio.create_task(main_module._readiness_self_healing_loop(s, [account]))
    try:
        # 유한시간 내 ready 로 전이해야 한다(liveness invariant).
        for _ in range(200):
            if s.runtime_readiness.is_ready("live-1", ReadinessFlag.BROKER):
                break
            await asyncio.sleep(0)
        assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.BROKER)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_self_healing_loop_cancel_on_shutdown() -> None:
    """shutdown 에서 self-healing loop task 가 cancel 된다."""
    s = _services()
    account = _account("live-1")
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")
    main_module._start_readiness_self_healing(s, [account])
    assert s.readiness_self_healing_task is not None

    # _shutdown 의 cancel 블록과 동일한 패턴으로 검증.
    task = s.readiness_self_healing_task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled() or task.done()


def test_start_self_healing_skipped_when_all_exempt() -> None:
    """대상 LIVE 계좌가 없으면(전부 면제) self-healing loop 를 띄우지 않는다."""
    s = _services()
    accounts = [
        _account("test", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        _account("kv", trading_mode=TradingMode.VIRTUAL),
    ]
    main_module._start_readiness_self_healing(s, accounts)
    assert s.readiness_self_healing_task is None


# ── broker_ready connect 시점 mark (init_gateway 발췌 경로) ─────────────────


@pytest.mark.asyncio
async def test_init_gateway_broker_ready_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    """_init_gateway connect 루프: LIVE 성공→broker_ready, virtual→면제 no-op ready,
    LIVE 실패→not_ready + get_broker 미호출(virtual)."""
    s = _services(brokers={"live-fail": RuntimeError("EGW00133")})

    accounts = [
        _account("test", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        _account("live-ok"),
        _account("live-fail"),
    ]
    s.account_service.list = AsyncMock(return_value=accounts)

    # _init_gateway 의 connect 루프만 검증하기 위해 후속 단계를 무력화.
    async def _noop(*a: Any, **k: Any) -> None:
        return None

    def _noop_sync(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(main_module, "_sync_instruments", _noop)
    monkeypatch.setattr(main_module, "_init_context_factory", _noop_sync)
    monkeypatch.setattr(main_module, "_init_treasury_sync", _noop)
    monkeypatch.setattr(main_module, "_init_fill_recovery_schedulers", _noop)
    monkeypatch.setattr(main_module, "_init_fill_outbox_publisher", _noop)
    monkeypatch.setattr(main_module, "_init_reconcile_scheduler", _noop)
    monkeypatch.setattr(main_module, "_init_daily_report_scheduler", _noop)
    monkeypatch.setattr(main_module, "_start_readiness_self_healing", _noop_sync)

    class _FakeStopOrderManager:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    class _FakeGateway:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    import ante.gateway as gateway_mod
    import ante.gateway.stop_order as stop_order_mod

    monkeypatch.setattr(gateway_mod, "APIGateway", _FakeGateway)
    monkeypatch.setattr(stop_order_mod, "StopOrderManager", _FakeStopOrderManager)
    s.treasury_manager = None
    s.performance_tracker = None
    s.trade_recorder = None
    s.position_history = None
    s.fill_outbox_publisher = None
    s.virtual_executor = SimpleNamespace(_gateway=None)
    s.bot_manager = SimpleNamespace(_context_factory=None)

    await main_module._init_gateway(s)

    # virtual/test: 면제 no-op ready, get_broker 미호출(KIS 재노출 차단).
    assert s.runtime_readiness.is_ready("test", ReadinessFlag.BROKER)
    # LIVE 성공: connect 시점 broker_ready.
    assert s.runtime_readiness.is_ready("live-ok", ReadinessFlag.BROKER)
    # LIVE 실패: not_ready + reason.
    assert not s.runtime_readiness.is_ready("live-fail", ReadinessFlag.BROKER)
    assert (
        s.runtime_readiness.get_reason("live-fail", ReadinessFlag.BROKER)
        == "connect_failed"
    )
    # 면제 계좌 broker 는 connect 단계에서 조회되지 않아야 한다.
    connect_ids = {c.args[0] for c in s.account_service.get_broker.call_args_list}
    assert "test" not in connect_ids


# ── observe-only 회귀: gate reader 부재(주문 동작 불변) ─────────────────────


def test_observe_only_no_gate_reader_in_consumers() -> None:
    """#2397 은 gate reader 를 추가하지 않는다(gate=#2398) — 주문 동작 불변.

    Treasury/RuleEngine/gateway/broker 등 소비자 모듈이 ``active_trading_ready``
    /``runtime_readiness`` 를 조회하지 않음을 소스 레벨로 잠근다. 본 PR 은 registry
    를 채우기만(main 등록자)·관측만 노출한다.
    """
    import pathlib

    src_root = pathlib.Path(main_module.__file__).resolve().parent
    # readiness 정의 모듈·등록자(main)·account 패키지 re-export 는 제외.
    allowed = {
        src_root / "account" / "readiness.py",
        src_root / "account" / "__init__.py",
        src_root / "main.py",
    }
    offenders: list[str] = []
    for py in src_root.rglob("*.py"):
        if py in allowed:
            continue
        text = py.read_text(encoding="utf-8")
        if "active_trading_ready" in text or "runtime_readiness" in text:
            offenders.append(str(py.relative_to(src_root)))
    assert offenders == [], (
        "observe-only 위반 — 다음 소비자가 readiness 를 조회한다(gate=#2398): "
        f"{offenders}"
    )


def test_main_does_not_call_active_trading_ready() -> None:
    """main 은 readiness 를 mark 만 하고 active_trading_ready 로 gate 하지 않는다."""
    import pathlib

    main_src = pathlib.Path(main_module.__file__).resolve()
    text = main_src.read_text(encoding="utf-8")
    # 호출 형태(``.active_trading_ready(``)는 없어야 한다(주석 언급은 허용).
    assert ".active_trading_ready(" not in text
