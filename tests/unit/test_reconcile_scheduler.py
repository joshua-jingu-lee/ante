"""ReconcileScheduler 단위 테스트."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.broker.scheduler import ReconcileScheduler

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
def reconciler():
    mock = AsyncMock()
    mock.reconcile = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def broker():
    mock = AsyncMock()
    mock.get_account_positions = AsyncMock(
        return_value=[
            {"symbol": "005930", "quantity": 100, "avg_price": 50000},
        ]
    )
    return mock


@pytest.fixture
def bot_manager():
    mock = MagicMock()
    mock.list_bots = MagicMock(
        return_value=[
            {"bot_id": "bot-1", "status": "running"},
            {"bot_id": "bot-2", "status": "stopped"},
        ]
    )
    return mock


@pytest.fixture
def eventbus():
    from ante.eventbus.bus import EventBus

    return EventBus()


@pytest.fixture
def scheduler(reconciler, broker, bot_manager, eventbus):
    return ReconcileScheduler(
        reconciler=reconciler,
        broker=broker,
        bot_manager=bot_manager,
        eventbus=eventbus,
        interval_seconds=0.1,  # 빠른 테스트용
    )


# ── run_once 테스트 ──────────────────────────────────


class TestRunOnce:
    async def test_reconciles_active_bots_only(self, scheduler, reconciler, broker):
        """running 상태인 봇만 대사한다."""
        await scheduler.run_once()

        # bot-1만 running이므로 1회 호출
        assert reconciler.reconcile.call_count == 1
        call_args = reconciler.reconcile.call_args
        assert call_args.kwargs["bot_id"] == "bot-1"

    async def test_passes_broker_positions(self, scheduler, reconciler, broker):
        """브로커 포지션을 reconciler에 전달한다."""
        await scheduler.run_once()

        call_args = reconciler.reconcile.call_args
        assert call_args.kwargs["broker_positions"] == [
            {"symbol": "005930", "quantity": 100, "avg_price": 50000},
        ]

    async def test_returns_all_corrections(self, scheduler, reconciler):
        """보정 내역을 반환한다."""
        reconciler.reconcile.return_value = [
            {"symbol": "005930", "old_quantity": 50, "new_quantity": 100}
        ]

        result = await scheduler.run_once()

        assert len(result) == 1
        assert result[0]["symbol"] == "005930"

    async def test_no_active_bots(self, scheduler, bot_manager, broker):
        """활성 봇이 없으면 브로커 호출하지 않는다."""
        bot_manager.list_bots.return_value = [
            {"bot_id": "bot-1", "status": "stopped"},
        ]

        result = await scheduler.run_once()

        assert result == []
        broker.get_account_positions.assert_not_called()

    async def test_broker_failure_returns_empty(self, scheduler, broker, reconciler):
        """브로커 조회 실패 시 빈 리스트를 반환한다."""
        broker.get_account_positions.side_effect = ConnectionError("연결 실패")

        result = await scheduler.run_once()

        assert result == []
        reconciler.reconcile.assert_not_called()

    async def test_single_bot_failure_continues(
        self, scheduler, bot_manager, reconciler
    ):
        """한 봇의 대사 실패가 다른 봇에 영향주지 않는다."""
        bot_manager.list_bots.return_value = [
            {"bot_id": "bot-1", "status": "running"},
            {"bot_id": "bot-2", "status": "running"},
        ]
        reconciler.reconcile.side_effect = [
            Exception("bot-1 실패"),
            [{"symbol": "005930", "corrected": True}],
        ]

        result = await scheduler.run_once()

        assert len(result) == 1
        assert reconciler.reconcile.call_count == 2


# ── start/stop 테스트 ────────────────────────────────


class TestStartStop:
    async def test_start_runs_initial_reconcile(self, scheduler, reconciler):
        """start() 시 즉시 1회 대사를 수행한다."""
        await scheduler.start()
        try:
            assert reconciler.reconcile.call_count == 1
        finally:
            await scheduler.stop()

    async def test_stop_cancels_task(self, scheduler):
        """stop() 시 스케줄러 태스크가 취소된다."""
        await scheduler.start()

        assert scheduler._task is not None
        assert not scheduler._task.done()

        await scheduler.stop()

        assert scheduler._task is None

    async def test_periodic_loop(self, scheduler, reconciler):
        """주기적으로 대사가 반복 실행된다."""
        await scheduler.start()

        # 짧은 대기로 주기 실행 확인 (interval=0.1s)
        await asyncio.sleep(0.35)
        await scheduler.stop()

        # 시작 시 1회 + 루프 최소 2~3회
        assert reconciler.reconcile.call_count >= 3

    async def test_double_start_ignored(self, scheduler, reconciler):
        """이미 실행 중인데 다시 start() 하면 무시된다."""
        await scheduler.start()
        initial_count = reconciler.reconcile.call_count

        await scheduler.start()  # 두 번째 호출 — 무시돼야 함

        # run_once()가 다시 호출되지 않아야 한다
        assert reconciler.reconcile.call_count == initial_count
        await scheduler.stop()

    async def test_stop_without_start(self, scheduler):
        """start() 없이 stop() 해도 오류 없음."""
        await scheduler.stop()  # 예외 없이 완료


# ── 설정 테스트 ──────────────────────────────────────


class TestConfiguration:
    def test_default_interval(self, reconciler, broker, bot_manager, eventbus):
        """기본 간격은 1800초(30분)이다."""
        from ante.broker.scheduler import DEFAULT_INTERVAL_SECONDS

        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
        )
        assert sched._interval == DEFAULT_INTERVAL_SECONDS
        assert DEFAULT_INTERVAL_SECONDS == 1800

    def test_custom_interval(self, reconciler, broker, bot_manager, eventbus):
        """interval_seconds로 주기를 변경할 수 있다."""
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            interval_seconds=600,
        )
        assert sched._interval == 600
