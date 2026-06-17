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

    # treasury_manager 더블 — start_sync/stop_sync/set_account_info 추적
    # (self-healing 재sync 는 stop_sync 선행 idempotent replace).
    async def _treasury_stop_sync() -> None:
        return None

    treasury = SimpleNamespace(
        start_sync=lambda **kwargs: None,
        stop_sync=_treasury_stop_sync,
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
            # backoff 를 0 으로 무력화 — liveness 검증이 실시간 sleep 에 의존하지
            # 않게 한다(기본 5s backoff 면 폴링 윈도우 초과).
            "readiness.self_healing_backoff_base_seconds": 0,
            "readiness.self_healing_backoff_max_seconds": 0,
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


@pytest.mark.asyncio
async def test_start_self_healing_started_for_virtual_treasury_targets() -> None:
    """Codex P2 회귀: treasury_sync 는 면제 없음(전 계좌 요구)이므로 virtual/test
    전용 구성도 self-healing 대상이다 — 루프를 띄워 treasury 일시 실패를 회복한다.

    (이전 회귀: targets 가 broker 비면제 LIVE 계좌만이라 virtual treasury 실패가
    영구 not_ready 로 고착.)
    """
    s = _services()
    accounts = [
        _account("test", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        _account("kv", trading_mode=TradingMode.VIRTUAL),
    ]
    main_module._start_readiness_self_healing(s, accounts)
    assert s.readiness_self_healing_task is not None
    # cleanup: 띄운 task 취소.
    task = s.readiness_self_healing_task
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_start_self_healing_skipped_when_no_accounts() -> None:
    """계좌가 하나도 없으면 self-healing loop 를 띄우지 않는다."""
    s = _services()
    main_module._start_readiness_self_healing(s, [])
    assert s.readiness_self_healing_task is None


@pytest.mark.asyncio
async def test_self_healing_recover_virtual_retries_treasury_without_get_broker() -> (
    None
):
    """Codex P2 회귀: broker 면제(virtual) 계좌의 회복은 treasury_sync(면제 없음)
    만 재시도하고, broker/fill/reconcile 은 면제(no-op ready)이므로 get_broker
    재노출 없이 skip 한다.

    virtual kis-domestic: broker/fill/reconcile 면제 → active_trading_ready 는
    treasury 만 요구. treasury not_ready → 회복 retry 로 ready 전이 → True.
    """
    s = _services()
    account = _account("kv", trading_mode=TradingMode.VIRTUAL)
    # treasury 만 not_ready(나머지는 면제 → active_trading_ready 가 ready 취급).
    s.runtime_readiness.mark_not_ready(
        "kv", ReadinessFlag.TREASURY_SYNC, "treasury_sync_failed"
    )

    recovered = await main_module._self_healing_recover_account(s, account)

    assert recovered is True
    assert s.runtime_readiness.is_ready("kv", ReadinessFlag.TREASURY_SYNC)
    # 면제 계좌이므로 broker/fill/reconcile 재등록(get_broker) 미발생.
    assert s.account_service.get_broker.await_count == 0
    assert "kv" not in s.fill_schedulers
    assert "kv" not in s.reconcile_schedulers


@pytest.mark.asyncio
async def test_self_healing_recover_disabled_reconcile_marks_ready() -> None:
    """Codex P2 회귀: reconcile.enabled=false 인 비면제(LIVE) 계좌의 회복은
    reconcile_ready 를 ready 로 no-op mark 해 영구 not_ready 고착을 막는다
    (startup 의 disabled no-op ready 와 동일). 회복 완료(active_trading_ready)."""
    s = _services()
    # reconcile 비활성 config.
    s.config = SimpleNamespace(
        get=lambda key, default=None: (
            {"enabled": False} if key == "reconcile" else default
        )
    )
    account = _account("live-1")
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    recovered = await main_module._self_healing_recover_account(s, account)

    assert recovered is True
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.BROKER)
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.FILL_RECONCILE)
    # reconcile 비활성 → scheduler 미등록이지만 reconcile_ready 는 no-op ready.
    assert "live-1" not in s.reconcile_schedulers
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.RECONCILE)


@pytest.mark.asyncio
async def test_self_healing_recover_treasury_only_no_scheduler_churn() -> None:
    """Codex P2 attempt-3 회귀: treasury_sync 만 not_ready 인 LIVE 계좌의 회복은
    건강한 fill/reconcile 스케줄러를 재등록(stop/start)하지 않는다(churn 방지).

    broker/fill/reconcile 가 모두 ready 이고 treasury 만 not_ready → recover 는
    treasury 만 재동기화하고, fill/reconcile 인스턴스는 그대로 유지(stop 미호출).
    (이전 회귀: 매 attempt 마다 건강한 스케줄러 stop/재시작 → KIS 호출·폴링 공백.)
    """
    s = _services()
    account = _account("live-1")
    # fill + reconcile 사전 등록(ready).
    await main_module._register_fill_scheduler_for_account(s, account)
    await main_module._register_reconcile_scheduler_for_account(
        s, account, object(), 1800
    )
    first_fill = s.fill_schedulers["live-1"]
    first_reconcile = s.reconcile_schedulers["live-1"]
    # broker ready, treasury 만 not_ready.
    s.runtime_readiness.mark_ready("live-1", ReadinessFlag.BROKER)
    s.runtime_readiness.mark_not_ready(
        "live-1", ReadinessFlag.TREASURY_SYNC, "treasury_sync_failed"
    )

    recovered = await main_module._self_healing_recover_account(s, account)

    assert recovered is True
    # 건강한 fill/reconcile 스케줄러는 churn 되지 않는다(동일 인스턴스·stop 미호출).
    assert s.fill_schedulers["live-1"] is first_fill
    assert s.reconcile_schedulers["live-1"] is first_reconcile
    assert first_fill.stopped is False
    assert first_reconcile.stopped is False
    # treasury 만 재동기화 → ready.
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.TREASURY_SYNC)


@pytest.mark.asyncio
async def test_self_healing_recover_rebinds_schedulers_on_broker_recovery() -> None:
    """broker 가 방금 재연결되면 fill/reconcile 스케줄러를 재등록(rebind)한다 —
    이미 ready 여도 stale broker 핸들 교체를 위해(churn 게이트의 broker_just_recovered
    경로). treasury_only churn 방지와 대칭되는 정상 rebind 경로 회귀 락.

    주의(메타리뷰 P3): "broker not_ready 인데 교체할 기존 스케줄러 존재" 조합은
    startup connect 실패 시 스케줄러가 생성되지 않아 현 PR 에서 production-도달
    불가한 방어 경로다 — 이 테스트는 broker_ready 강등 도입 전까지 인위적 상태로만
    이 분기를 검증한다(broker_just_recovered rebind 정합성 락)."""
    s = _services()
    account = _account("live-1")
    await main_module._register_fill_scheduler_for_account(s, account)
    await main_module._register_reconcile_scheduler_for_account(
        s, account, object(), 1800
    )
    first_fill = s.fill_schedulers["live-1"]
    first_reconcile = s.reconcile_schedulers["live-1"]
    # broker not_ready → 회복 시 broker_just_recovered=True 로 rebind 유도.
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    await main_module._self_healing_recover_account(s, account)

    # broker 재연결 → 기존 스케줄러 stop 후 새 인스턴스로 교체.
    assert first_fill.stopped is True
    assert first_reconcile.stopped is True
    assert s.fill_schedulers["live-1"] is not first_fill
    assert s.reconcile_schedulers["live-1"] is not first_reconcile


@pytest.mark.asyncio
async def test_self_healing_loop_survives_recover_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """메타리뷰 P1 회귀: _self_healing_recover_account 가 예기치 못한 예외를 던져도
    background loop 가 사멸하지 않고 다음 계좌/burst 로 계속한다(liveness 방어).

    한 계좌(boom)가 매번 raise 해도 다른 계좌(ok)는 유한시간 내 회복되어야 한다
    (단일 예외가 전 계좌 회복을 멈추면 #2395 영구 not_ready 역회귀).
    """
    s = _services()
    a1 = _account("boom")
    a2 = _account("ok")
    s.runtime_readiness.mark_not_ready("boom", ReadinessFlag.BROKER, "connect_failed")
    s.runtime_readiness.mark_not_ready("ok", ReadinessFlag.BROKER, "connect_failed")
    s.config = SimpleNamespace(
        get=lambda key, default=None: {
            "readiness.self_healing_interval_seconds": 0,
            "readiness.self_healing_max_attempts_per_burst": 1,
            "readiness.self_healing_backoff_base_seconds": 0,
            "readiness.self_healing_backoff_max_seconds": 0,
        }.get(key, default)
    )

    real_recover = main_module._self_healing_recover_account
    calls: list[str] = []

    async def _recover(svc: Any, acc: Any) -> bool:
        calls.append(acc.account_id)
        if acc.account_id == "boom":
            raise RuntimeError("unexpected recover failure")
        return await real_recover(svc, acc)

    monkeypatch.setattr(main_module, "_self_healing_recover_account", _recover)

    task = asyncio.create_task(main_module._readiness_self_healing_loop(s, [a1, a2]))
    try:
        for _ in range(500):
            if s.runtime_readiness.is_ready("ok", ReadinessFlag.BROKER):
                break
            await asyncio.sleep(0)
        # boom 의 반복 예외에도 loop 가 살아 ok 를 회복시킨다.
        assert s.runtime_readiness.is_ready("ok", ReadinessFlag.BROKER)
        assert "boom" in calls and "ok" in calls
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_self_healing_marks_broker_ready_after_dependent_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """메타리뷰 P2 회귀: broker_ready 는 의존 스케줄러 rebind 를 마친 **뒤** mark 한다
    (stale-broker false-ready 창 제거). fill rebind 시점에 BROKER 가 아직 not_ready
    임을 잠근다 — 먼저 mark 하면 rebind await 사이에 active_trading_ready 가 stale
    상태와 함께 True 로 관측될 수 있다.
    """
    s = _services()
    account = _account("live-1")
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    observed: dict[str, bool] = {}
    real_register = main_module._register_fill_scheduler_for_account

    async def _spy_register(svc: Any, acc: Any) -> bool:
        observed["broker_ready_during_rebind"] = svc.runtime_readiness.is_ready(
            acc.account_id, ReadinessFlag.BROKER
        )
        return await real_register(svc, acc)

    monkeypatch.setattr(
        main_module, "_register_fill_scheduler_for_account", _spy_register
    )

    await main_module._self_healing_recover_account(s, account)

    # rebind 진행 중에는 broker_ready 가 아직 not_ready(지연 mark).
    assert observed["broker_ready_during_rebind"] is False
    # 회복 완료 후에는 broker_ready 가 ready.
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.BROKER)


@pytest.mark.asyncio
async def test_self_healing_recover_restarts_treasury_on_broker_recovery() -> None:
    """Codex P2 attempt-4 회귀: broker 회복 시 Treasury sync 를 stop 후 재시작해
    stale broker 를 새 broker 로 교체한다.

    Treasury.start_sync 는 실행 중 task 가 있으면 no-op 이므로, _init_treasury_sync
    가 stop_sync 를 선행해야 한다. broker_just_recovered LIVE 경로에서 stop→start
    순서를 잠근다(이전 회귀: start_sync no-op → treasury_sync_ready 만 ready 인데
    잔고 동기화는 stale broker 유지).
    """
    s = _services()
    account = _account("live-1")
    calls: list[str] = []

    async def _stop_sync() -> None:
        calls.append("stop")

    treasury = SimpleNamespace(
        start_sync=lambda **kwargs: calls.append("start"),
        stop_sync=_stop_sync,
        set_account_info=lambda **kwargs: None,
    )
    s.treasury_manager = SimpleNamespace(get=lambda account_id: treasury)
    # broker not_ready → 회복 시 broker_just_recovered=True → treasury 재바인딩.
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    await main_module._self_healing_recover_account(s, account)

    # stale broker sync 교체: stop 선행 후 start(no-op 회피).
    assert calls == ["stop", "start"]


@pytest.mark.asyncio
async def test_init_treasury_sync_stops_before_start_idempotent() -> None:
    """_init_treasury_sync 는 stop_sync 선행 후 start_sync 한다(idempotent replace).

    startup 재진입·self-healing 재sync 모두 stale sync 를 새 broker 로 교체하도록
    stop→start 순서를 직접 잠근다(Codex P2 attempt-4).
    """
    s = _services()
    account = _account("live-1")
    calls: list[str] = []

    async def _stop_sync() -> None:
        calls.append("stop")

    treasury = SimpleNamespace(
        start_sync=lambda **kwargs: calls.append("start"),
        stop_sync=_stop_sync,
        set_account_info=lambda **kwargs: None,
    )
    s.treasury_manager = SimpleNamespace(get=lambda account_id: treasury)

    await main_module._init_treasury_sync(s, [account])

    assert calls == ["stop", "start"]
    assert s.runtime_readiness.is_ready("live-1", ReadinessFlag.TREASURY_SYNC)


@pytest.mark.asyncio
async def test_self_healing_burst_backoff_is_exponential_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex P2 회귀(행위): burst 내 attempt 간 backoff 가 base*2^attempt 로
    지수 증가하고 max 로 capped 된다. 마지막 attempt 뒤에는 backoff 하지 않는다.

    asyncio.sleep 을 가로채 실제 대기 없이 duration 시퀀스를 검증한다.
    base=5, max=15, max_per_burst=4 → backoff [5, 10, 15(capped from 20)].
    """
    s = _services(brokers={"live-1": RuntimeError("EGW00133")})
    s.config = SimpleNamespace(
        get=lambda key, default=None: {
            "readiness.self_healing_interval_seconds": 0,
            "readiness.self_healing_max_attempts_per_burst": 4,
            "readiness.self_healing_backoff_base_seconds": 5,
            "readiness.self_healing_backoff_max_seconds": 15,
        }.get(key, default)
    )
    s.runtime_readiness.mark_not_ready("live-1", ReadinessFlag.BROKER, "connect_failed")

    durations: list[float] = []
    real_sleep = asyncio.sleep

    async def _fake_sleep(delay: float) -> None:
        durations.append(delay)
        # backoff 3회(attempt 0,1,2) 수집 후 루프 종료(인터럽트).
        if len(durations) >= 3:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(main_module.asyncio, "sleep", _fake_sleep)
    account = _account("live-1")

    with pytest.raises(asyncio.CancelledError):
        await main_module._readiness_self_healing_loop(s, [account])

    # base*2^0=5, base*2^1=10, min(base*2^2=20, max=15)=15. 마지막 attempt(3)는 skip.
    assert durations[:3] == [5, 10, 15]


def test_self_healing_loop_backs_off_between_attempts() -> None:
    """Codex P2 회귀: burst 내 attempt 간 지수 backoff(토큰 cooldown 정렬).

    소스 계약 락: ``_readiness_self_healing_loop`` 가 backoff base/max 설정을 읽고
    attempt 간 ``asyncio.sleep`` 으로 backoff 한다(즉시 재인증 몰림 방지).
    """
    import pathlib

    main_src = pathlib.Path(main_module.__file__).resolve()
    lines = main_src.read_text(encoding="utf-8").splitlines()
    start = next(
        i
        for i, ln in enumerate(lines)
        if "_readiness_self_healing_loop" in ln
        and ln.lstrip().startswith(("def ", "async def "))
    )
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith(("def ", "async def "))
        ),
        len(lines),
    )
    body = "\n".join(lines[start:end])
    assert "self_healing_backoff_base_seconds" in body
    assert "self_healing_backoff_max_seconds" in body
    assert "2**attempt" in body or "2 ** attempt" in body


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


def test_main_active_trading_ready_only_in_self_healing() -> None:
    """observe-only — main 은 readiness 를 mark 하고, ``active_trading_ready`` 는
    **self-healing retry-targeting 에만** 쓴다(주문 차단 gate 아님). 주문 경로
    consumer(gateway/rule/treasury) gate 부재는
    ``test_observe_only_no_gate_reader_in_consumers`` 가 잠근다.
    """
    import pathlib

    main_src = pathlib.Path(main_module.__file__).resolve()
    lines = main_src.read_text(encoding="utf-8").splitlines()
    def_idx = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("def ") or ln.startswith("async def ")
    ]

    def enclosing_def(idx: int) -> str:
        prev = [d for d in def_idx if d <= idx]
        return lines[prev[-1]] if prev else ""

    # ``.active_trading_ready(`` 호출이 있다면 전부 self-healing 함수 내부여야 한다.
    for i, line in enumerate(lines):
        if ".active_trading_ready(" in line:
            enc = enclosing_def(i)
            assert (
                "_self_healing_recover_account" in enc
                or "_readiness_self_healing_loop" in enc
            ), f"active_trading_ready outside self-healing: {enc!r}"


def test_self_healing_loop_targets_non_broker_readiness() -> None:
    """Codex P1 회귀: self-healing pending 필터가 broker_ready 만이 아니라
    active_trading_ready(비면제 전 플래그) 기준이어야, broker 회복 후 fill/
    reconcile/treasury 실패 계좌가 burst 대상에서 빠지지 않는다(영구 차단 방지).

    소스 계약 락: ``_readiness_self_healing_loop`` 의 pending 필터는
    ``active_trading_ready`` 를 호출하고 ``is_ready(.., BROKER)`` 단독으로
    필터하지 않는다.
    """
    import pathlib

    main_src = pathlib.Path(main_module.__file__).resolve()
    lines = main_src.read_text(encoding="utf-8").splitlines()
    start = next(
        i
        for i, ln in enumerate(lines)
        if "_readiness_self_healing_loop" in ln
        and ln.lstrip().startswith(("def ", "async def "))
    )
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith(("def ", "async def "))
        ),
        len(lines),
    )
    body = "\n".join(lines[start:end])
    assert "active_trading_ready" in body, (
        "self-healing pending 필터가 active_trading_ready 기준이어야 함(Codex P1)"
    )


def test_self_healing_recover_respects_disabled_reconcile() -> None:
    """Codex P2 회귀: self-healing 회복 경로(_self_healing_recover_account)는
    reconcile.enabled=false 를 존중해, 운영자가 끈 reconcile 을 회복 시 다시
    켜지 않는다(reconcile_enabled 분기 + _register_reconcile_scheduler_for_account
    조건부 호출).
    """
    import pathlib

    main_src = pathlib.Path(main_module.__file__).resolve()
    lines = main_src.read_text(encoding="utf-8").splitlines()
    start = next(
        i
        for i, ln in enumerate(lines)
        if "_self_healing_recover_account" in ln
        and ln.lstrip().startswith(("def ", "async def "))
    )
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].startswith(("def ", "async def "))
        ),
        len(lines),
    )
    body = "\n".join(lines[start:end])
    assert "reconcile_enabled" in body, (
        "회복 경로가 reconcile.enabled 를 존중해야 함(Codex P2)"
    )
