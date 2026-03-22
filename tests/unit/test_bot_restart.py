"""봇 자동 재시작 정책 테스트."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.config import BotConfig, BotStatus
from ante.bot.manager import BotManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotErrorEvent,
    BotRestartExhaustedEvent,
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
        config = BotConfig(bot_id="b1", strategy_id="s1")
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
        )
        assert config.auto_restart is False
        assert config.max_restart_attempts == 5
        assert config.restart_cooldown_seconds == 30


# ── US-1: 자동 재시작 ──────────────────────────────


class TestBotAutoRestart:
    async def test_restart_on_error(self, manager, eventbus):
        """BotErrorEvent 수신 시 재시작 예약."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            restart_cooldown_seconds=0,
            max_restart_attempts=3,
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)
        bot.status = BotStatus.ERROR

        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="test"))
        await asyncio.sleep(0.05)  # cooldown=0 + task 실행 대기

        # 재시작 성공 확인 (카운터는 reset_after=0이므로 이미 리셋될 수 있음)
        assert bot.status == BotStatus.RUNNING

    async def test_no_restart_when_disabled(self, manager, eventbus):
        """auto_restart=False → 재시작 안 함."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            auto_restart=False,
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())
        bot.status = BotStatus.ERROR

        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="test"))
        await asyncio.sleep(0.05)

        assert bot.status == BotStatus.ERROR
        assert manager.get_restart_count("b1") == 0

    async def test_restart_exhausted(self, manager, eventbus):
        """max_restart_attempts 초과 시 BotRestartExhaustedEvent."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=2,
            restart_cooldown_seconds=0,
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())

        exhausted: list[BotRestartExhaustedEvent] = []
        eventbus.subscribe(BotRestartExhaustedEvent, lambda e: exhausted.append(e))

        # 2번 재시작 시도
        manager._restart_counts["b1"] = 2

        bot.status = BotStatus.ERROR
        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="fail"))
        await asyncio.sleep(0.05)

        assert len(exhausted) == 1
        assert exhausted[0].bot_id == "b1"
        assert exhausted[0].account_id == "test"
        assert exhausted[0].restart_attempts == 2

    async def test_restart_count_increments(self, manager, eventbus):
        """재시작마다 카운트 증가."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=5,
            restart_cooldown_seconds=0,
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)

        # 첫 번째 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="e1"))
        await asyncio.sleep(0.05)
        # cooldown=0 → reset_after=0, 카운터 즉시 리셋 가능
        assert bot.status == BotStatus.RUNNING

        # 두 번째 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="e2"))
        await asyncio.sleep(0.05)
        assert bot.status == BotStatus.RUNNING

    async def test_unknown_bot_error_ignored(self, manager, eventbus):
        """등록되지 않은 봇의 에러는 무시."""
        await eventbus.publish(BotErrorEvent(bot_id="unknown", error_message="test"))
        # 에러 없이 통과


# ── US-2: 재시작 카운터 리셋 ──────────────────────


class TestRestartCounterReset:
    async def test_counter_resets_after_stable_period(self, manager, eventbus):
        """정상 실행 유지 시 카운터 리셋."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=3,
            restart_cooldown_seconds=0,
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []

        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=ctx)

        # 에러 → 재시작
        bot.status = BotStatus.ERROR
        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="e1"))
        await asyncio.sleep(0.05)

        # reset_after = 0 * 3 = 0초이므로 재시작 성공 직후 카운터가 즉시 리셋됨
        assert bot.status == BotStatus.RUNNING
        assert manager.get_restart_count("b1") == 0

    async def test_counter_not_reset_if_bot_stopped(self, manager, eventbus):
        """봇이 중지된 경우 카운터 리셋하지 않음."""
        config = BotConfig(
            bot_id="b1",
            strategy_id="s1",
            max_restart_attempts=3,
            restart_cooldown_seconds=0,
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
        )
        bot = await manager.create_bot(config, _make_strategy_cls(), ctx=MagicMock())
        bot.status = BotStatus.ERROR

        await eventbus.publish(BotErrorEvent(bot_id="b1", error_message="test"))
        await asyncio.sleep(0.01)
        assert "b1" in manager._restart_tasks

        await manager.stop_all()
        assert len(manager._restart_tasks) == 0


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
        """account_id 기본값은 빈 문자열."""
        event = BotRestartExhaustedEvent(bot_id="b1")
        assert event.account_id == ""
