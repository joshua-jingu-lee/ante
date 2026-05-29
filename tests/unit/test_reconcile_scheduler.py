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
            {"bot_id": "bot-1", "status": "running", "account_id": "acc-test"},
            {"bot_id": "bot-2", "status": "stopped", "account_id": "acc-test"},
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
        broker_account_id="acc-test",
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
            {"bot_id": "bot-1", "status": "stopped", "account_id": "acc-test"},
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
            {"bot_id": "bot-1", "status": "running", "account_id": "acc-test"},
            {"bot_id": "bot-2", "status": "running", "account_id": "acc-test"},
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

    async def test_start_passes_skip_external_buy_to_initial_reconcile(
        self, reconciler, broker, bot_manager, eventbus
    ):
        """skip_initial_external_buy=True 면 기동 즉시 대사에 skip_external_buy=True
        를 전달한다 (#1946 Finding 1 barrier).
        """
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            broker_account_id="acc-test",
            interval_seconds=1800,
            skip_initial_external_buy=True,
        )
        await sched.start()
        try:
            assert reconciler.reconcile.call_count == 1
            assert reconciler.reconcile.call_args.kwargs["skip_external_buy"] is True
        finally:
            await sched.stop()

    async def test_start_default_does_not_skip_external_buy(
        self, scheduler, reconciler
    ):
        """기본(skip_initial_external_buy=False)은 기동 대사에서도 skip 안 함."""
        await scheduler.start()
        try:
            assert reconciler.reconcile.call_args.kwargs["skip_external_buy"] is False
        finally:
            await scheduler.stop()

    async def test_periodic_reconcile_does_not_skip_external_buy(
        self, reconciler, broker, bot_manager, eventbus
    ):
        """기동에만 skip — 이후 주기 루프 대사는 skip_external_buy=False (barrier
        는 1회성). fill 폴 루프가 복구를 진행하므로 정상 처리한다.
        """
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            broker_account_id="acc-test",
            interval_seconds=0.05,
            skip_initial_external_buy=True,
        )
        await sched.start()
        await asyncio.sleep(0.18)  # 주기 루프 몇 회 돌게.
        await sched.stop()

        calls = reconciler.reconcile.call_args_list
        assert len(calls) >= 2
        # 첫 호출(기동)만 skip=True, 나머지(주기)는 모두 skip=False.
        assert calls[0].kwargs["skip_external_buy"] is True
        assert all(c.kwargs["skip_external_buy"] is False for c in calls[1:])

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
            broker_account_id="acc-test",
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
            broker_account_id="acc-test",
            interval_seconds=600,
        )
        assert sched._interval == 600

    def test_skip_initial_external_buy_defaults_false(
        self, reconciler, broker, bot_manager, eventbus
    ):
        """skip_initial_external_buy 기본값은 False (#1946)."""
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            broker_account_id="acc-test",
        )
        assert sched._skip_initial_external_buy is False

    def test_requires_broker_account_id(
        self, reconciler, broker, bot_manager, eventbus
    ):
        """broker_account_id가 비어있으면 생성에 실패한다."""
        with pytest.raises(ValueError, match="broker_account_id"):
            ReconcileScheduler(
                reconciler=reconciler,
                broker=broker,
                bot_manager=bot_manager,
                eventbus=eventbus,
                broker_account_id="",
            )


# ── SPLIT-1 multi-account 가드 회귀 테스트 ──────────────


class TestBrokerAccountScoping:
    """ReconcileScheduler가 자기 broker_account_id에 일치하는 봇만
    reconcile하는지 확인한다 (SPLIT-1 가드).
    """

    async def test_scheduler_skips_bot_from_other_account(
        self, reconciler, broker, bot_manager, eventbus, caplog
    ):
        """scheduler가 acc-A 바인딩일 때 acc-B 봇은 reconcile되지 않는다."""
        import logging

        bot_manager.list_bots.return_value = [
            {"bot_id": "bot-a", "status": "running", "account_id": "acc-A"},
            {"bot_id": "bot-b", "status": "running", "account_id": "acc-B"},
        ]
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            broker_account_id="acc-A",
            interval_seconds=0.1,
        )

        with caplog.at_level(logging.WARNING, logger="ante.broker.scheduler"):
            await sched.run_once()

        # acc-A 봇만 reconcile 호출 — acc-B 봇은 스킵
        assert reconciler.reconcile.call_count == 1
        call_args = reconciler.reconcile.call_args
        assert call_args.kwargs["bot_id"] == "bot-a"
        assert call_args.kwargs["account_id"] == "acc-A"

        # 미일치 봇에 대한 WARNING 로그
        skip_logs = [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "bot-b" in rec.getMessage()
            and "acc-B" in rec.getMessage()
        ]
        assert skip_logs, (
            "scheduler가 미일치 봇(bot-b/acc-B)에 대해 WARNING을 남겨야 한다"
        )
        assert any("acc-A" in rec.getMessage() for rec in skip_logs), (
            "WARNING 메시지에 scheduler의 broker_account_id(acc-A)가 포함돼야 한다"
        )

    async def test_scheduler_processes_matching_account_bot(
        self, reconciler, broker, bot_manager, eventbus
    ):
        """일치하는 봇은 정상 reconcile 호출된다."""
        bot_manager.list_bots.return_value = [
            {"bot_id": "bot-a1", "status": "running", "account_id": "acc-A"},
            {"bot_id": "bot-a2", "status": "running", "account_id": "acc-A"},
            {"bot_id": "bot-b", "status": "running", "account_id": "acc-B"},
        ]
        sched = ReconcileScheduler(
            reconciler=reconciler,
            broker=broker,
            bot_manager=bot_manager,
            eventbus=eventbus,
            broker_account_id="acc-A",
            interval_seconds=0.1,
        )

        await sched.run_once()

        # acc-A 봇 두 개 모두 reconcile 호출
        assert reconciler.reconcile.call_count == 2
        called_bot_ids = {
            call.kwargs["bot_id"] for call in reconciler.reconcile.call_args_list
        }
        assert called_bot_ids == {"bot-a1", "bot-a2"}
        for call in reconciler.reconcile.call_args_list:
            assert call.kwargs["account_id"] == "acc-A"
