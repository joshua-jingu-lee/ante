"""BotManager 전략 배정/변경/재개 메서드 단위 테스트.

Refs #444
"""

import asyncio

import pytest

from ante.bot import BotConfig, BotError, BotManager, BotStatus
from ante.core import Database
from ante.eventbus import EventBus
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

# ── Fake 구현체 ──────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class SimpleStrategy(Strategy):
    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def ctx():
    return StrategyContext(
        bot_id="bot1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolioView(),
        order_view=FakeOrderView(),
    )


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    try:
        await asyncio.wait_for(database.close(), timeout=5.0)
    except TimeoutError:
        pass


@pytest.fixture
async def manager(eventbus, db):
    m = BotManager(eventbus=eventbus, db=db)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


# ── assign_strategy ──────────────────────────────


class TestAssignStrategy:
    async def test_assign_to_stopped_bot(self, manager, ctx):
        """중지 상태 봇에 전략 배정."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.assign_strategy("bot1", "s2")

        bot = manager.get_bot("bot1")
        assert bot.config.strategy_id == "s2"

    async def test_assign_to_running_bot_restarts(self, manager, ctx):
        """running 봇에 전략 배정 시 중지 후 재시작."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.assign_strategy("bot1", "s2")

        bot = manager.get_bot("bot1")
        assert bot.config.strategy_id == "s2"
        assert bot.status == BotStatus.RUNNING

    async def test_assign_updates_db(self, manager, ctx, db):
        """전략 배정 시 DB에 strategy_id가 갱신된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.assign_strategy("bot1", "s2")

        row = await db.fetch_one("SELECT strategy_id FROM bots WHERE bot_id = 'bot1'")
        assert row["strategy_id"] == "s2"

    async def test_assign_not_found_raises(self, manager):
        """존재하지 않는 봇이면 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.assign_strategy("nonexistent", "s1")

    async def test_assign_to_created_bot(self, manager, ctx):
        """created 상태 봇에 전략 배정."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1").status == BotStatus.CREATED

        await manager.assign_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"


# ── change_strategy ──────────────────────────────


class TestChangeStrategy:
    async def test_change_stopped_bot(self, manager, ctx):
        """중지 상태 봇의 전략 교체."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"

    async def test_change_running_raises(self, manager, ctx):
        """running 봇 전략 변경 시 예외."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="실행 중인 봇"):
            await manager.change_strategy("bot1", "s2")

    async def test_change_updates_db(self, manager, ctx, db):
        """전략 교체 시 DB에 strategy_id가 갱신된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.change_strategy("bot1", "s2")

        row = await db.fetch_one("SELECT strategy_id FROM bots WHERE bot_id = 'bot1'")
        assert row["strategy_id"] == "s2"

    async def test_change_not_found_raises(self, manager):
        """존재하지 않는 봇이면 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.change_strategy("nonexistent", "s1")

    async def test_change_created_bot(self, manager, ctx):
        """created 상태 봇의 전략 교체 가능."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"

    async def test_change_error_bot(self, manager, ctx):
        """error 상태 봇의 전략 교체 가능."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        # 수동으로 error 상태 설정
        manager.get_bot("bot1").status = BotStatus.ERROR

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"


# ── resume_bot ───────────────────────────────────


class TestResumeBot:
    async def test_resume_stopped_bot(self, manager, ctx):
        """stopped 봇 재시작."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

        await manager.resume_bot("bot1")

        assert manager.get_bot("bot1").status == BotStatus.RUNNING

    async def test_resume_error_bot(self, manager, ctx):
        """error 봇 재시작."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        # 수동으로 error 상태 설정
        bot = manager.get_bot("bot1")
        bot.status = BotStatus.ERROR
        bot.error_message = "some error"

        await manager.resume_bot("bot1")

        assert bot.status == BotStatus.RUNNING
        assert bot.error_message is None

    async def test_resume_resets_error_counter(self, manager, ctx):
        """재개 시 에러 카운터가 리셋된다."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        bot = manager.get_bot("bot1")
        bot.status = BotStatus.ERROR
        manager._restart_counts["bot1"] = 3

        await manager.resume_bot("bot1")

        assert manager.get_restart_count("bot1") == 0

    async def test_resume_running_raises(self, manager, ctx):
        """running 봇 재개 시 예외."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="이미 실행 중"):
            await manager.resume_bot("bot1")

    async def test_resume_created_raises(self, manager, ctx):
        """created 상태 봇 재개 시 예외."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1").status == BotStatus.CREATED

        with pytest.raises(BotError, match="재개할 수 없는 상태"):
            await manager.resume_bot("bot1")

    async def test_resume_not_found_raises(self, manager):
        """존재하지 않는 봇 재개 시 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.resume_bot("nonexistent")


# ── stop_bot suppress_notification ──────────────


class TestStopBotSuppressNotification:
    async def test_suppress_false_publishes_notification(self, manager, eventbus, ctx):
        """suppress_notification=False(기본값)이면 NotificationEvent가 발행된다."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")

        stop_notifs = [n for n in notifications if n.title == "봇 중지"]
        assert len(stop_notifs) == 1

    async def test_suppress_true_skips_notification(self, manager, eventbus, ctx):
        """suppress_notification=True이면 NotificationEvent가 발행되지 않는다."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1", suppress_notification=True)

        stop_notifs = [n for n in notifications if n.title == "봇 중지"]
        assert len(stop_notifs) == 0

    async def test_suppress_is_one_shot(self, manager, eventbus, ctx):
        """suppress는 1회성이다. 두 번째 stop에서는 알림이 발행된다."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 1회차: suppress
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1", suppress_notification=True)
        stop_notifs_1 = [n for n in notifications if n.title == "봇 중지"]
        assert len(stop_notifs_1) == 0

        # 2회차: 기본값 (알림 발행)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")
        stop_notifs_2 = [n for n in notifications if n.title == "봇 중지"]
        assert len(stop_notifs_2) == 1

    async def test_suppress_preserves_bot_stopped_event(self, manager, eventbus, ctx):
        """suppress_notification=True여도 BotStoppedEvent는 정상 발행된다."""
        from ante.eventbus.events import BotStoppedEvent

        stopped_events: list[BotStoppedEvent] = []
        eventbus.subscribe(BotStoppedEvent, lambda e: stopped_events.append(e))

        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1", suppress_notification=True)

        assert len(stopped_events) == 1
        assert stopped_events[0].bot_id == "bot1"


# ── update_bot ──────────────────────────────────


class TestUpdateBot:
    async def test_update_name(self, manager, ctx):
        """중지 상태 봇의 이름 변경."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        bot = await manager.update_bot("bot1", name="new-name")

        assert bot.config.name == "new-name"

    async def test_update_interval(self, manager, ctx):
        """실행 간격 변경."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=60, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        bot = await manager.update_bot("bot1", interval_seconds=120)

        assert bot.config.interval_seconds == 120

    async def test_update_multiple_fields(self, manager, ctx):
        """여러 필드 동시 변경."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        bot = await manager.update_bot(
            "bot1",
            name="updated",
            interval_seconds=300,
            auto_restart=False,
            max_restart_attempts=5,
        )

        assert bot.config.name == "updated"
        assert bot.config.interval_seconds == 300
        assert bot.config.auto_restart is False
        assert bot.config.max_restart_attempts == 5

    async def test_update_preserves_unchanged_fields(self, manager, ctx):
        """변경하지 않은 필드는 기존 값 유지."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            name="original",
            interval_seconds=60,
            auto_restart=True,
            account_id="acc-test",
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.update_bot("bot1", name="updated")

        bot = manager.get_bot("bot1")
        assert bot.config.name == "updated"
        assert bot.config.interval_seconds == 60
        assert bot.config.auto_restart is True
        assert bot.config.strategy_id == "s1"

    async def test_update_running_raises(self, manager, ctx):
        """running 상태에서 수정 시 예외."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="중지 상태"):
            await manager.update_bot("bot1", name="x")

    async def test_update_created_allowed(self, manager, ctx):
        """created 상태에서 수정 허용."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1").status == BotStatus.CREATED

        bot = await manager.update_bot("bot1", name="updated")
        assert bot.config.name == "updated"

    async def test_update_error_allowed(self, manager, ctx):
        """error 상태에서 수정 허용."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        manager.get_bot("bot1").status = BotStatus.ERROR

        bot = await manager.update_bot("bot1", name="fixed")
        assert bot.config.name == "fixed"

    async def test_update_saves_to_db(self, manager, ctx, db):
        """수정 결과가 DB에 반영된다."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", name="old", account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.update_bot("bot1", name="new")

        row = await db.fetch_one("SELECT config_json FROM bots WHERE bot_id = 'bot1'")
        import json

        saved = json.loads(row["config_json"])
        assert saved["name"] == "new"

    async def test_update_not_found_raises(self, manager):
        """존재하지 않는 봇 수정 시 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.update_bot("nonexistent", name="x")

    async def test_update_no_changes_returns_bot(self, manager, ctx):
        """변경 사항 없으면 그대로 반환."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        bot = await manager.update_bot("bot1")
        assert bot.config.bot_id == "bot1"


# ── Refs #1457: BotConfig DB 라운드트립 보존 ──────────────────────────────


def _bot_config_default(name: str):
    """``BotConfig`` dataclass field default 를 직접 조회한다 (테스트 SSOT).

    Refs #1457 task 7: 테스트도 default 값을 하드코딩하지 않고 dataclass
    field default 에서 가져온다. manager helper 와 동일한 SSOT 를 사용해
    SSOT 불일치 회귀를 방지한다.
    """

    import dataclasses

    for field in dataclasses.fields(BotConfig):
        if field.name == name:
            if field.default is not dataclasses.MISSING:
                return field.default
            raise KeyError(f"BotConfig field {name!r} has no default")
    raise KeyError(f"BotConfig has no field {name!r}")


class TestBotConfigDBRoundtrip:
    """``_save_bot_config`` 와 ``load_from_db`` 의 runtime control 라운드트립.

    Refs #1457 — Implementation Plan v2 의 case A/B1/B2/C1/C2/C3/D 를 커버한다.
    """

    @pytest.mark.parametrize("auto_restart", [True, False])
    async def test_full_roundtrip_runtime_controls(
        self, manager, eventbus, ctx, db, auto_restart
    ):
        """case A: 5필드 + auto_restart 가 라운드트립 후 보존된다.

        ``auto_restart`` 는 True/False 모두 보존되어야 한다.
        """
        config = BotConfig(
            bot_id="bot-roundtrip",
            strategy_id="s1",
            account_id="acc-test",
            interval_seconds=120,
            auto_restart=auto_restart,
            max_restart_attempts=5,
            restart_cooldown_seconds=180,
            step_timeout_seconds=45,
            max_signals_per_step=80,
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 새 매니저로 DB 에서 다시 로드 — 프로세스 재시작 시뮬레이션
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        loaded = manager2.get_bot("bot-roundtrip")
        assert loaded is not None
        assert loaded.config.interval_seconds == 120
        assert loaded.config.auto_restart is auto_restart
        assert loaded.config.max_restart_attempts == 5
        assert loaded.config.restart_cooldown_seconds == 180
        assert loaded.config.step_timeout_seconds == 45
        assert loaded.config.max_signals_per_step == 80

    async def test_save_persists_all_runtime_control_keys(self, manager, ctx, db):
        """``_save_bot_config`` 가 5 runtime control 키를 ``config_json`` 에 직렬화한다.

        Refs #1457: 누락 시 ``load_from_db`` 가 default 로 복원해버려 silent
        값 회귀가 발생한다.
        """
        import json as _json

        config = BotConfig(
            bot_id="bot-save",
            strategy_id="s1",
            account_id="acc-test",
            interval_seconds=90,
            auto_restart=False,
            max_restart_attempts=4,
            restart_cooldown_seconds=120,
            step_timeout_seconds=60,
            max_signals_per_step=42,
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        row = await db.fetch_one(
            "SELECT config_json FROM bots WHERE bot_id = 'bot-save'"
        )
        saved = _json.loads(row["config_json"])

        assert saved["interval_seconds"] == 90
        assert saved["auto_restart"] is False
        assert saved["max_restart_attempts"] == 4
        assert saved["restart_cooldown_seconds"] == 120
        assert saved["step_timeout_seconds"] == 60
        assert saved["max_signals_per_step"] == 42

    async def test_missing_legacy_row_restores_dataclass_defaults(
        self, manager, eventbus, db
    ):
        """case B1: 5필드가 모두 누락된 legacy row 는 dataclass default 로 복원된다."""
        import json as _json

        legacy_config = _json.dumps({"interval_seconds": 60})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("legacy-bot", "legacy", "s1", "acc-test", legacy_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        bot = manager2.get_bot("legacy-bot")
        assert bot is not None
        # SSOT: BotConfig dataclass field default
        assert bot.config.interval_seconds == 60
        assert bot.config.auto_restart == _bot_config_default("auto_restart")
        assert bot.config.max_restart_attempts == _bot_config_default(
            "max_restart_attempts"
        )
        assert bot.config.restart_cooldown_seconds == _bot_config_default(
            "restart_cooldown_seconds"
        )
        assert bot.config.step_timeout_seconds == _bot_config_default(
            "step_timeout_seconds"
        )
        assert bot.config.max_signals_per_step == _bot_config_default(
            "max_signals_per_step"
        )

    async def test_partial_legacy_row_preserves_present_fields(
        self, manager, eventbus, db
    ):
        """case B2: 일부 필드만 있는 partial row — 있는 값 보존 + 나머지 default."""
        import json as _json

        partial = _json.dumps(
            {
                "interval_seconds": 60,
                "auto_restart": False,
                "max_restart_attempts": 5,
            }
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("partial-bot", "partial", "s1", "acc-test", partial, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        bot = manager2.get_bot("partial-bot")
        assert bot is not None
        # present fields are preserved
        assert bot.config.interval_seconds == 60
        assert bot.config.auto_restart is False
        assert bot.config.max_restart_attempts == 5
        # missing fields fall back to dataclass default
        assert bot.config.restart_cooldown_seconds == _bot_config_default(
            "restart_cooldown_seconds"
        )
        assert bot.config.step_timeout_seconds == _bot_config_default(
            "step_timeout_seconds"
        )
        assert bot.config.max_signals_per_step == _bot_config_default(
            "max_signals_per_step"
        )

    async def test_invalid_runtime_control_row_is_skipped_with_warning(
        self, manager, eventbus, db, caplog
    ):
        """case C1: ``validate_runtime_controls`` 위반 row 는 skip + warning."""
        import json as _json
        import logging

        # valid row 1건
        valid_config = _json.dumps({"interval_seconds": 60})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("good-bot", "good", "s1", "acc-test", valid_config, "created"),
        )
        # invalid: restart_cooldown_seconds=0 (MIN_RESTART_COOLDOWN_SECONDS=10)
        invalid_config = _json.dumps(
            {
                "interval_seconds": 60,
                "restart_cooldown_seconds": 0,
            }
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("bad-cooldown", "bad", "s1", "acc-test", invalid_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        # invalid row 만 skip — valid row 는 정상 load
        assert count == 1
        assert manager2.get_bot("good-bot") is not None
        assert manager2.get_bot("bad-cooldown") is None
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any(
            "bad-cooldown" in m and "invalid bot config row skip" in m
            for m in warn_messages
        )

    async def test_explicit_null_auto_restart_row_is_skipped_with_warning(
        self, manager, eventbus, db, caplog
    ):
        """case C2 (auto_restart=null): explicit null row 는 skip + warning."""
        import json as _json
        import logging

        valid_config = _json.dumps({"interval_seconds": 60})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("good-bot", "good", "s1", "acc-test", valid_config, "created"),
        )
        null_config = _json.dumps({"interval_seconds": 60, "auto_restart": None})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("null-auto", "null", "s1", "acc-test", null_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        # null row 만 skip — 다른 정상 row 는 계속 load
        assert count == 1
        assert manager2.get_bot("good-bot") is not None
        assert manager2.get_bot("null-auto") is None
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any(
            "null-auto" in m and "invalid bot config row skip" in m
            for m in warn_messages
        )

    async def test_explicit_null_numeric_field_row_is_skipped_with_warning(
        self, manager, eventbus, db, caplog
    ):
        """case C2 (max_restart_attempts=null): 숫자 필드 explicit null 도 skip."""
        import json as _json
        import logging

        null_config = _json.dumps(
            {"interval_seconds": 60, "max_restart_attempts": None}
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("null-num", "null", "s1", "acc-test", null_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        assert count == 0
        assert manager2.get_bot("null-num") is None
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any(
            "null-num" in m and "invalid bot config row skip" in m
            for m in warn_messages
        )

    async def test_invalid_interval_seconds_row_is_skipped_with_warning(
        self, manager, eventbus, db, caplog
    ):
        """case C3: invalid ``interval_seconds`` 도 새 except 분기로 skip."""
        import json as _json
        import logging

        invalid_config = _json.dumps({"interval_seconds": -1})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("bad-interval", "bad", "s1", "acc-test", invalid_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        assert count == 0
        assert manager2.get_bot("bad-interval") is None
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any(
            "bad-interval" in m and "invalid bot config row skip" in m
            for m in warn_messages
        )

    async def test_invalid_account_id_row_not_absorbed_by_value_error_branch(
        self, manager, eventbus, db, caplog
    ):
        """case D: InvalidAccountIdError 회귀 — 새 ValueError 분기로 흡수되지 않는다.

        Refs #1241 SPLIT-2 의 기존 skip 분기는 그대로 동작해야 하고, log
        message 는 invalid runtime control 분기와 구분되어야 한다.
        """
        import json as _json
        import logging

        valid_config = _json.dumps({"interval_seconds": 60})
        # account_id="" 는 ``require_account_id`` 가 InvalidAccountIdError raise
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("blank-acc", "blank", "s1", "", valid_config, "created"),
        )

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        with caplog.at_level(logging.WARNING):
            count = await manager2.load_from_db()

        assert count == 0
        assert manager2.get_bot("blank-acc") is None
        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        # 기존 SPLIT-2 분기의 메시지 형식이 유지된다 (별도 분기로 라우팅).
        assert any(
            "blank-acc" in m and "invalid account_id row skip" in m
            for m in warn_messages
        )
        # 새 ValueError 분기 메시지로 잘못 흡수되지 않는다.
        assert not any(
            "blank-acc" in m and "invalid bot config row skip" in m
            for m in warn_messages
        )
