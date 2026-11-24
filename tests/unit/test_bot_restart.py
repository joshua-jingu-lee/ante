"""봇 자동 재시작 정책 테스트."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot import manager as bot_manager_module
from ante.bot.config import BotConfig, BotStatus
from ante.bot.manager import BotManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotErrorEvent,
    BotRestartExhaustedEvent,
    BotStartedEvent,
    NotificationEvent,
)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def manager(eventbus, db):
    mgr = BotManager(eventbus=eventbus, db=db)
    await mgr.initialize()
    return mgr


@pytest.fixture
def _fast_restart_cooldown(monkeypatch):
    """``BotManager`` 내부 cooldown / reset_after sleep 만 0 으로 압축.

    #1456 이전에는 테스트 헬퍼가 ``restart_cooldown_seconds=0`` 으로
    BotConfig 를 만들어 sleep 시간을 0초로 압축했다. 1456 에서 spec 범위
    (10~600초) 외 값을 ``ValueError`` 로 막으면서 sleep 회피 책임이 테스트
    인프라로 옮겨졌다.

    ``manager._cooldown_sleep`` 만 0초 sleep 으로 교체한다. 이 helper 는
    ``_restart_after_cooldown`` 과 ``_reset_restart_count_after`` 두 곳에서만
    사용하므로 ``Bot._run_loop`` 의 ``asyncio.sleep(interval_seconds)`` 등
    다른 sleep 경로에는 영향이 없다. (#1456 codex review P2)
    """

    async def _no_sleep(seconds):  # noqa: ARG001 — 의도적 매개변수 무시
        # cooldown 자체를 즉시 종료. task scheduling 대기는 테스트 본문의
        # ``await asyncio.sleep(0.05)`` 가 담당한다.
        await asyncio.sleep(0)

    monkeypatch.setattr(bot_manager_module, "_cooldown_sleep", _no_sleep)
    return _no_sleep


def _make_strategy_cls():
    """테스트용 전략 클래스."""
    cls = MagicMock()
    instance = MagicMock()
    instance.on_step = AsyncMock(return_value=[])
    instance.on_fill = AsyncMock(return_value=[])
    instance.on_order_update = AsyncMock()
    cls.return_value = instance
    return cls


# ── US-1: BotConfig 재시작 정책 필드 ──────────────


class TestBotConfigRestartPolicy:
    def test_default_auto_restart(self):
        """기본값 auto_restart=True."""
        config = BotConfig(bot_id="b1", strategy_id="s1", account_id="acc-test")
        assert config.auto_restart is True
        assert config.max_restart_attempts == 3
        assert config.restart_cooldown_seconds == 60

    def test_custom_restart_policy(self):
        """커스텀 재시작 정책."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            auto_restart=False,
            max_restart_attempts=5,
            restart_cooldown_seconds=30,
            account_id="acc-test",
        )
        assert config.auto_restart is False
        assert config.max_restart_attempts == 5
        assert config.restart_cooldown_seconds == 30


# ── US-1: 자동 재시작 ──────────────────────────────


class TestBotAutoRestart:
    async def test_restart_on_error(self, manager, eventbus, _fast_restart_cooldown):
        """BotErrorEvent 수신 시 재시작 예약.

        #1456 이전에는 ``restart_cooldown_seconds=0`` 으로 sleep 시간을
        압축했지만, spec 범위(10~600) 외 값은 ``BotConfig`` 단에서
        ``ValueError`` 가 된다. spec 통과값 10 을 쓰면서 sleep 자체는
        ``_fast_restart_cooldown`` fixture 가 0 으로 교체한다.
        """
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            restart_cooldown_seconds=10,
            max_restart_attempts=3,
            account_id="acc-test",
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)
        bot.status = BotStatus.ERROR

        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        await asyncio.sleep(0.05)  # monkeypatched sleep + task 스케줄 대기

        # 재시작 성공 확인 (sleep 0초 → 즉시 reset_restart_count 도 0초로 수렴)
        assert bot.status == BotStatus.RUNNING

    async def test_no_restart_when_disabled(self, manager, eventbus):
        """auto_restart=False → 재시작 안 함."""
        config = BotConfig(
            bot_id="b1", strategy_id="s1", auto_restart=False, account_id="acc-test"
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())
        bot.status = BotStatus.ERROR

        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        await asyncio.sleep(0.05)

        assert bot.status == BotStatus.ERROR
        assert manager.get_restart_count("b1") == 0

    async def test_restart_exhausted(self, manager, eventbus, _fast_restart_cooldown):
        """max_restart_attempts 초과 시 BotRestartExhaustedEvent."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=2,
            restart_cooldown_seconds=10,
            account_id="acc-test",
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())

        exhausted: list[BotRestartExhaustedEvent] = []
        eventbus.subscribe(BotRestartExhaustedEvent, lambda e: exhausted.append(e))

        # 2번 재시작 시도
        manager._restart_counts["b1"] = 2

        bot.status = BotStatus.ERROR
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="fail", account_id="acc-test")
        )
        await asyncio.sleep(0.05)

        assert len(exhausted) == 1
        assert exhausted[0].bot_id == "b1"
        assert exhausted[0].account_id == "acc-test"
        assert exhausted[0].restart_attempts == 2

    async def test_restart_count_increments(
        self, manager, eventbus, _fast_restart_cooldown
    ):
        """재시작마다 카운트 증가."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=5,
            restart_cooldown_seconds=10,
            account_id="acc-test",
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)

        # 첫 번째 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="e1", account_id="acc-test")
        )
        await asyncio.sleep(0.05)
        # _fast_restart_cooldown 으로 sleep 0초 → reset_after 도 0초 분기 즉시 리셋
        assert bot.status == BotStatus.RUNNING

        # 두 번째 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="e2", account_id="acc-test")
        )
        await asyncio.sleep(0.05)
        assert bot.status == BotStatus.RUNNING

    async def test_unknown_bot_error_ignored(self, manager, eventbus):
        """등록되지 않은 봇의 에러는 무시."""
        await eventbus.publish(
            BotErrorEvent(bot_id="unknown", error_message="test", account_id="acc-test")
        )
        # 에러 없이 통과


# ── US-2: 재시작 카운터 리셋 ──────────────────────


class TestRestartCounterReset:
    async def test_counter_resets_after_stable_period(
        self, manager, eventbus, _fast_restart_cooldown
    ):
        """정상 실행 유지 시 카운터 리셋."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=3,
            restart_cooldown_seconds=10,
            account_id="acc-test",
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)

        # 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="e1", account_id="acc-test")
        )
        await asyncio.sleep(0.05)

        # _fast_restart_cooldown → reset_after 도 0초 분기 → 재시작 후 카운터 리셋
        assert bot.status == BotStatus.RUNNING
        assert manager.get_restart_count("b1") == 0

    async def test_counter_not_reset_if_bot_stopped(
        self, manager, eventbus, _fast_restart_cooldown
    ):
        """봇이 중지된 경우 카운터 리셋하지 않음."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=3,
            restart_cooldown_seconds=10,
            account_id="acc-test",
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)
        manager._restart_counts["b1"] = 2

        # 봇이 중지 상태
        bot.status = BotStatus.STOPPED
        manager._schedule_restart_reset("b1")
        await asyncio.sleep(0.05)

        # 중지 상태이므로 리셋하지 않음
        assert manager.get_restart_count("b1") == 2


# ── 봇 중지 시 재시작 태스크 취소 ──────────────────


class TestStopCancelsRestart:
    async def test_stop_all_cancels_restart_tasks(self, manager, eventbus):
        """stop_all이 재시작 태스크를 취소."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            restart_cooldown_seconds=10,
            account_id="acc-test",
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())
        bot.status = BotStatus.ERROR

        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        await asyncio.sleep(0.01)
        assert "b1" in manager._restart_tasks

        await manager.stop_all()
        assert len(manager._restart_tasks) == 0


class TestDeleteStopsRestart:
    """삭제가 진행되는 사이에 자동 재시작이 봇을 다시 띄우지 않는다 (#2883)."""

    @staticmethod
    async def _error_bot(manager):
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            restart_cooldown_seconds=10,
            max_restart_attempts=3,
            account_id="acc-test",
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)
        bot.status = BotStatus.ERROR
        return bot

    @staticmethod
    def _gate_cooldown(monkeypatch) -> tuple[asyncio.Event, asyncio.Semaphore]:
        wake = asyncio.Event()
        entered = asyncio.Semaphore(0)

        async def _wait_for_wake(seconds):  # noqa: ARG001
            entered.release()
            await wake.wait()

        monkeypatch.setattr(bot_manager_module, "_cooldown_sleep", _wait_for_wake)
        return wake, entered

    @staticmethod
    def _started(eventbus) -> list[BotStartedEvent]:
        seen: list[BotStartedEvent] = []
        eventbus.subscribe(BotStartedEvent, seen.append)
        return seen

    async def test_restart_called_during_delete_does_not_start(
        self, manager, eventbus, monkeypatch, _fast_restart_cooldown
    ):
        bot = await self._error_bot(manager)
        started = self._started(eventbus)

        async def _restart_during_delete(target):
            await manager._restart_after_cooldown("b1")

        monkeypatch.setattr(manager, "_liquidate_positions", _restart_during_delete)
        await manager.delete_bot("b1", handle_positions="liquidate")

        assert started == []
        assert bot.status == BotStatus.DELETED
        assert bot._task is None or bot._task.done()

    async def test_restart_scheduled_before_delete_waking_during_delete_does_not_start(
        self, manager, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager)
        wake, entered = self._gate_cooldown(monkeypatch)
        started = self._started(eventbus)
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        task = manager._restart_tasks["b1"]
        await entered.acquire()

        async def _wake_restart_during_delete(target):
            wake.set()
            await asyncio.wait([task], timeout=5.0)

        monkeypatch.setattr(
            manager, "_liquidate_positions", _wake_restart_during_delete
        )
        try:
            await manager.delete_bot("b1", handle_positions="liquidate")
        finally:
            await manager.stop_all()
            if bot._task and not bot._task.done():
                bot._task.cancel()

        assert task.done() and not task.cancelled()
        assert task.exception() is None
        assert started == []
        assert bot.status == BotStatus.DELETED
        assert bot._task is None or bot._task.done()
        assert "b1" not in manager._restart_tasks

    async def test_delete_cancels_scheduled_restart_and_reset_tasks(
        self, manager, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager)
        _, entered = self._gate_cooldown(monkeypatch)
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        manager._schedule_restart_reset("b1")
        restart = manager._restart_tasks["b1"]
        reset = manager._restart_reset_tasks["b1"]
        await entered.acquire()
        await entered.acquire()

        await manager.delete_bot("b1")
        await asyncio.wait([restart, reset], timeout=5.0)

        assert restart.cancelled()
        assert reset.cancelled()
        assert "b1" not in manager._restart_tasks
        assert "b1" not in manager._restart_reset_tasks
        assert bot.status == BotStatus.DELETED

    async def test_failed_delete_keeps_scheduled_restart(
        self, manager, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager)
        _, entered = self._gate_cooldown(monkeypatch)
        await eventbus.publish(
            BotErrorEvent(bot_id="b1", error_message="test", account_id="acc-test")
        )
        restart = manager._restart_tasks["b1"]
        await entered.acquire()

        async def _fail_liquidate(target):
            raise RuntimeError("liquidate down")

        monkeypatch.setattr(manager, "_liquidate_positions", _fail_liquidate)
        try:
            with pytest.raises(RuntimeError, match="liquidate down"):
                await manager.delete_bot("b1", handle_positions="liquidate")

            assert manager._restart_tasks.get("b1") is restart
            assert not restart.done()
            assert manager.get_restart_count("b1") == 1
            assert manager.get_bot("b1") is bot
            assert bot.status == BotStatus.ERROR
        finally:
            await manager.stop_all()

    async def test_error_during_failed_delete_schedules_no_restart(
        self, manager, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager)
        self._gate_cooldown(monkeypatch)
        notified: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, notified.append)

        async def _error_then_fail(target):
            await eventbus.publish(
                BotErrorEvent(bot_id="b1", error_message="boom", account_id="acc-test")
            )
            raise RuntimeError("liquidate down")

        monkeypatch.setattr(manager, "_liquidate_positions", _error_then_fail)
        try:
            with pytest.raises(RuntimeError, match="liquidate down"):
                await manager.delete_bot("b1", handle_positions="liquidate")

            assert "b1" not in manager._restart_tasks
            assert manager.get_restart_count("b1") == 0
            assert bot.status == BotStatus.ERROR
            assert [n.title for n in notified if n.title == "봇 에러"] == ["봇 에러"]
        finally:
            await manager.stop_all()

    async def test_error_during_delete_with_exhausted_count_still_reports(
        self, manager, eventbus, monkeypatch
    ):
        await self._error_bot(manager)
        self._gate_cooldown(monkeypatch)
        manager._restart_counts["b1"] = 3
        exhausted: list[BotRestartExhaustedEvent] = []
        eventbus.subscribe(BotRestartExhaustedEvent, exhausted.append)

        async def _error_during_delete(target):
            await eventbus.publish(
                BotErrorEvent(bot_id="b1", error_message="boom", account_id="acc-test")
            )
            assert "b1" not in manager._restart_tasks
            assert manager.get_restart_count("b1") == 3

        monkeypatch.setattr(manager, "_liquidate_positions", _error_during_delete)
        try:
            await manager.delete_bot("b1", handle_positions="liquidate")
        finally:
            await manager.stop_all()

        assert len(exhausted) == 1
        assert exhausted[0].bot_id == "b1"
        assert exhausted[0].restart_attempts == 3
        assert "b1" not in manager._restart_tasks

    async def test_delete_clears_restart_count(self, manager):
        await self._error_bot(manager)
        manager._restart_counts["b1"] = 2

        await manager.delete_bot("b1")
        assert manager.get_restart_count("b1") == 0

        await self._error_bot(manager)
        assert manager.get_restart_count("b1") == 0


# ── BotRestartExhaustedEvent 필드 ──────────────────


class TestBotRestartExhaustedEvent:
    def test_event_fields(self):
        """이벤트 필드 확인."""
        event = BotRestartExhaustedEvent(
            bot_id="b1",
            account_id="acc-1",
            restart_attempts=3,
            last_error="connection lost",
        )
        assert event.bot_id == "b1"
        assert event.account_id == "acc-1"
        assert event.restart_attempts == 3
        assert event.last_error == "connection lost"

    def test_account_id_default_empty(self):
        """account_id 명시값은 보존된다."""
        event = BotRestartExhaustedEvent(bot_id="b1", account_id="acc-test")
        assert event.account_id == "acc-test"
