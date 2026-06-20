"""#2405: stop 주문 세션 만료 자동 처리 배선 + manager_stopped 복구 회귀 테스트.

`StopOrderManager.check_session_expiry()` 의 production caller 가 0개였던
배선 부재(이슈 #2405) 를 회귀로 잠근다. 단위가 아닌 **배선/lifecycle** 레벨:

- (a) `_init_gateway` 가 `stop_session_expiry_task` 를 생성하고, 그 루프가
  manager.check_session_expiry() 를 호출한다.
- (b) `_stop_session_expiry_loop` 가 예외를 삼키고 CancelledError 는 전파한다.
- (c) `_shutdown` 이 task cancel → manager.stop() 순서로 정리한다(orphan 없음,
  활성 주문 manager_stopped 만료).
- (d) `StopOrderExpiredEvent(reason="session_ended")` 가 consumer
  (SignalChannel) 에서 reason-agnostic 으로 정상 처리된다(이 경로 첫 실발행).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante import main as main_module
from ante.eventbus.events import StopOrderExpiredEvent
from ante.main import Services, _shutdown, _stop_session_expiry_loop

# ── (a) _init_gateway 배선 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_init_gateway_creates_session_expiry_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_init_gateway 후 stop_session_expiry_task 가 생성되고 manager 참조가
    api_gateway 와 **동일 인스턴스**로 보관된다.

    배선 부재 회귀 락 — 수정 전에는 task 가 None 이었다.
    """
    captured: dict[str, Any] = {}

    class _FakeAPIGateway:
        def __init__(self, *, stop_order_manager: Any, **kwargs: Any) -> None:
            captured["gateway_manager"] = stop_order_manager

        def start(self) -> None:
            captured["started"] = True

    # _init_gateway 내부 무거운 의존 제거: APIGateway / context factory /
    # treasury sync / self-healing stub. account 목록은 빈 리스트로 connect/
    # stream/reconcile 루프 skip.
    import ante.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "APIGateway", _FakeAPIGateway)
    monkeypatch.setattr(main_module, "_init_context_factory", lambda s: None)
    monkeypatch.setattr(
        main_module, "_init_treasury_sync", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        main_module, "_start_readiness_self_healing", lambda s, accounts: None
    )

    s = Services()
    s.eventbus = AsyncMock()
    s.order_tracker = object()
    s.account_service = AsyncMock()
    s.account_service.list = AsyncMock(return_value=[])
    s.treasury_manager = None

    await main_module._init_gateway(s)

    # task 가 생성되었고 살아 있다(배선 부재였다면 None).
    assert s.stop_session_expiry_task is not None
    assert not s.stop_session_expiry_task.done()
    # manager 참조가 APIGateway 에 주입된 것과 동일 인스턴스.
    assert s.stop_order_manager is captured["gateway_manager"]

    # 정리: task cancel.
    s.stop_session_expiry_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await s.stop_session_expiry_task


@pytest.mark.asyncio
async def test_session_expiry_task_loop_calls_check_session_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_init_gateway 가 만든 task 의 루프가 실제로 check_session_expiry 를 호출한다."""
    called = asyncio.Event()

    class _StubManager:
        def __init__(self, *, eventbus: Any) -> None:
            self._running = False

        def start(self) -> None:
            self._running = True

        async def check_session_expiry(self) -> None:
            called.set()

    # StopOrderManager 를 stub 으로 치환 + 루프 interval 단축.
    monkeypatch.setattr("ante.gateway.stop_order.StopOrderManager", _StubManager)

    class _FakeAPIGateway:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def start(self) -> None:
            pass

    import ante.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "APIGateway", _FakeAPIGateway)
    monkeypatch.setattr(main_module, "_init_context_factory", lambda s: None)
    monkeypatch.setattr(
        main_module, "_init_treasury_sync", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        main_module, "_start_readiness_self_healing", lambda s, accounts: None
    )

    # 실제 루프 함수를 interval 0 으로 감싼 wrapper 로 치환해 즉시 1회 호출.
    orig_loop = _stop_session_expiry_loop

    async def _fast_loop(manager: Any, interval: float = 60.0) -> None:
        await orig_loop(manager, interval=0.0)

    monkeypatch.setattr(main_module, "_stop_session_expiry_loop", _fast_loop)

    s = Services()
    s.eventbus = AsyncMock()
    s.order_tracker = object()
    s.account_service = AsyncMock()
    s.account_service.list = AsyncMock(return_value=[])
    s.treasury_manager = None

    await main_module._init_gateway(s)
    assert s.stop_session_expiry_task is not None

    await asyncio.wait_for(called.wait(), timeout=1.0)

    s.stop_session_expiry_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await s.stop_session_expiry_task


# ── (b) loop 예외/취소 시맨틱 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_propagates_cancelled_error() -> None:
    """루프는 CancelledError 를 삼키지 않고 전파한다(orphan 방지)."""
    manager = MagicMock()
    manager.check_session_expiry = AsyncMock()

    task = asyncio.create_task(_stop_session_expiry_loop(manager, interval=10.0))
    await asyncio.sleep(0)  # task 진입
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_loop_swallows_check_session_expiry_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """check_session_expiry 예외는 로깅 후 루프가 생존한다."""
    manager = MagicMock()
    calls = {"n": 0}

    async def _raise_once() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    manager.check_session_expiry = _raise_once

    task = asyncio.create_task(_stop_session_expiry_loop(manager, interval=0.0))
    # 두 번 이상 호출될 때까지 양보(첫 호출 raise → 루프 생존 → 두 번째 호출).
    for _ in range(100):
        await asyncio.sleep(0)
        if calls["n"] >= 2:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert calls["n"] >= 2  # 예외 후에도 루프가 살아 다시 호출됨


# ── (c) shutdown 순서: task cancel → manager.stop() ───────────────────────


@pytest.mark.asyncio
async def test_shutdown_cancels_task_then_stops_manager() -> None:
    """_shutdown 이 ① task cancel → ② manager.stop() 순서로 정리한다.

    ipc_server 가 없는(None) 환경: IPC gate 가 끼어들지 않으므로 순수
    task cancel → manager.stop() 순서만 본다.
    """
    events: list[str] = []

    async def _loop() -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("task_cancelled")
            raise

    class _FakeManager:
        async def stop(self) -> None:
            events.append("manager_stop")

    s = Services(
        stop_session_expiry_task=asyncio.create_task(_loop()),
        stop_order_manager=_FakeManager(),
    )
    await asyncio.sleep(0)  # loop 진입

    await _shutdown(s)

    assert events == ["task_cancelled", "manager_stop"], f"events={events}"
    # orphan 없음 — task done.
    assert s.stop_session_expiry_task is not None
    assert s.stop_session_expiry_task.done()


@pytest.mark.asyncio
async def test_shutdown_ipc_gate_before_manager_stop() -> None:
    """#2405 attempt4 P2: IPC gate(stop_accepting)가 manager.stop() **앞**에서
    호출된다.

    활성 stop 주문이 많거나 StopOrderExpiredEvent 핸들러가 느려 manager.stop()
    이 오래 걸려도, IPC 가 RUNNING 으로 남아 mutating IPC 가 SHUTTING_DOWN →
    SERVICE_UNAVAILABLE 계약을 우회하지 못하도록, stop_accepting() 이 먼저
    SHUTTING_DOWN 으로 전환되어야 한다.
    """
    events: list[str] = []

    async def _loop() -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("task_cancelled")
            raise

    class _FakeManager:
        async def stop(self) -> None:
            events.append("manager_stop")

    class _FakeIPCServer:
        async def stop_accepting(self) -> None:
            events.append("ipc_stop_accepting")

        def stop_dispatching(self) -> None:
            events.append("ipc_stop_dispatching")

        async def drain_connections(self, timeout: float = 5.0) -> None:
            events.append("ipc_drain")

        def unlink_socket(self) -> None:
            events.append("ipc_unlink_socket")

    s = Services(
        stop_session_expiry_task=asyncio.create_task(_loop()),
        stop_order_manager=_FakeManager(),
        ipc_server=_FakeIPCServer(),
    )
    await asyncio.sleep(0)  # loop 진입

    await _shutdown(s)

    # 순서: ① task cancel → ② ipc gate(stop_accepting) → ③ manager.stop().
    assert "ipc_stop_accepting" in events, f"events={events}"
    assert "manager_stop" in events, f"events={events}"
    idx_task = events.index("task_cancelled")
    idx_gate = events.index("ipc_stop_accepting")
    idx_manager = events.index("manager_stop")
    assert idx_task < idx_gate, f"task cancel 이 IPC gate 앞; events={events}"
    assert idx_gate < idx_manager, (
        f"IPC gate(stop_accepting)가 manager.stop() 앞이어야 한다; events={events}"
    )
    # IPC drain/unlink 은 manager.stop() 보다 뒤(lifecycle 마지막).
    idx_unlink = events.index("ipc_unlink_socket")
    assert idx_manager < idx_unlink, f"manager.stop()<unlink; events={events}"
    assert s.stop_session_expiry_task is not None
    assert s.stop_session_expiry_task.done()


@pytest.mark.asyncio
async def test_shutdown_manager_stop_expires_active_orders() -> None:
    """shutdown 의 manager.stop() 이 활성 stop 주문을 manager_stopped 로 만료한다."""
    from ante.gateway.stop_order import StopOrderManager

    eventbus = MagicMock()
    eventbus.publish = AsyncMock()
    manager = StopOrderManager(eventbus)
    manager.start()
    await manager.register(
        order_id="ord-1",
        bot_id="bot-1",
        strategy_id="stg-1",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=49000.0,
        account_id="acc-test",
    )
    eventbus.publish.reset_mock()

    async def _noop_loop() -> None:
        while True:
            await asyncio.sleep(3600)

    s = Services(
        stop_session_expiry_task=asyncio.create_task(_noop_loop()),
        stop_order_manager=manager,
    )
    await asyncio.sleep(0)

    await _shutdown(s)

    assert len(manager.active_orders) == 0
    assert eventbus.publish.call_count == 1
    event = eventbus.publish.call_args[0][0]
    assert isinstance(event, StopOrderExpiredEvent)
    assert event.reason == "manager_stopped"


@pytest.mark.asyncio
async def test_shutdown_safe_when_session_expiry_unwired() -> None:
    """배선 안 된 환경(task/manager None)에서도 _shutdown 이 안전하다."""
    s = Services()  # stop_session_expiry_task=None, stop_order_manager=None
    await _shutdown(s)  # 예외 없이 통과


# ── (d) session_ended consumer 회귀 (SignalChannel reason-agnostic) ────────


@pytest.mark.asyncio
async def test_session_ended_event_consumed_by_signal_channel() -> None:
    """StopOrderExpiredEvent(reason="session_ended") 가 SignalChannel 에서
    reason-agnostic 으로 stop_expired 로 정상 처리된다(이 경로 첫 실발행).
    """
    from ante.bot.signal_channel import SignalChannel

    emitted: list[dict[str, Any]] = []

    # _on_order_update 가 사용하는 최소 멤버만 갖춘 SignalChannel 더블.
    channel = SignalChannel.__new__(SignalChannel)
    channel._closed = False
    channel._bot = SimpleNamespace(bot_id="bot-1")
    channel._is_full = None
    channel._sink = emitted.append
    channel._output = None  # sink 경로라 미사용

    event = StopOrderExpiredEvent(
        account_id="acc-test",
        stop_order_id="stop-abc",
        bot_id="bot-1",
        strategy_id="stg-1",
        symbol="005930",
        reason="session_ended",
    )

    await channel._on_order_update(event)

    assert len(emitted) == 1
    update = emitted[0]
    assert update["type"] == "order_update"
    assert update["status"] == "stop_expired"
    assert update["order_id"] == "stop-abc"
    assert update["reason"] == "session_ended"
