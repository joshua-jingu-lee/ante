"""BotConfig DB 라운드트립 보존 회귀 테스트.

Refs #1457 (Epic #1413 split-C): ``update_bot`` 으로 변경한 runtime control
4개 필드와 ``auto_restart`` 가 ``_save_bot_config`` 직렬화 → ``load_from_db``
역직렬화 후에도 보존되어야 한다. ``BotConfig`` 기본값 SSOT 는
``src/ante/bot/config.py`` 의 ``@dataclass`` default, runtime control 범위
SSOT 는 ``docs/dashboard/user-stories/bots.md`` B-5 line 197-200 이다.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from ante.bot import BotConfig, BotManager
from ante.core import Database
from ante.eventbus import EventBus


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


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
async def manager(eventbus: EventBus, db: Database):
    m = BotManager(eventbus=eventbus, db=db)
    await m.initialize()
    yield m
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


class _NullStrategy:
    """create_bot fallback 용 stub. ``manager.create_bot`` 은
    ``_save_bot_config`` 만 검증하므로 실제 실행 경로는 사용하지 않는다.
    """


def _new_config(**overrides) -> BotConfig:
    base = {
        "bot_id": "bot-roundtrip",
        "strategy_id": "s-roundtrip",
        "name": "round trip",
        "account_id": "acc-test",
        "interval_seconds": 30,
        "auto_restart": True,
        "max_restart_attempts": 3,
        "restart_cooldown_seconds": 60,
        "step_timeout_seconds": 30,
        "max_signals_per_step": 50,
    }
    base.update(overrides)
    return BotConfig(**base)


class TestRuntimeControlRoundTrip:
    """save → load 사이클에서 runtime control 4개 필드 + auto_restart 보존."""

    async def test_runtime_controls_persisted_through_round_trip(
        self, manager: BotManager, eventbus: EventBus, db: Database
    ) -> None:
        """non-default runtime control 값이 라운드트립 후에도 유지된다."""
        config = _new_config(
            max_restart_attempts=7,
            restart_cooldown_seconds=120,
            step_timeout_seconds=90,
            max_signals_per_step=25,
            auto_restart=False,
        )
        # ``create_bot`` 은 실제 strategy_cls 가 필요하므로 직접
        # ``_save_bot_config`` 를 통해 영속화한다 (이 테스트의 검증 범위).
        await manager._save_bot_config(config)

        # 새 매니저 인스턴스로 DB 로드 → in-memory 캐시 영향 배제
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        loaded = manager2.get_bot("bot-roundtrip")
        assert loaded is not None
        assert loaded.config.max_restart_attempts == 7
        assert loaded.config.restart_cooldown_seconds == 120
        assert loaded.config.step_timeout_seconds == 90
        assert loaded.config.max_signals_per_step == 25
        assert loaded.config.auto_restart is False

    async def test_boundary_min_values_persist(
        self, manager: BotManager, eventbus: EventBus, db: Database
    ) -> None:
        """SSOT 최소 경계값이 라운드트립 후 그대로 유지된다."""
        config = _new_config(
            max_restart_attempts=1,
            restart_cooldown_seconds=10,
            step_timeout_seconds=5,
            max_signals_per_step=1,
        )
        await manager._save_bot_config(config)

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        await manager2.load_from_db()

        loaded = manager2.get_bot("bot-roundtrip")
        assert loaded is not None
        assert loaded.config.max_restart_attempts == 1
        assert loaded.config.restart_cooldown_seconds == 10
        assert loaded.config.step_timeout_seconds == 5
        assert loaded.config.max_signals_per_step == 1

    async def test_boundary_max_values_persist(
        self, manager: BotManager, eventbus: EventBus, db: Database
    ) -> None:
        """SSOT 최대 경계값이 라운드트립 후 그대로 유지된다."""
        config = _new_config(
            max_restart_attempts=10,
            restart_cooldown_seconds=600,
            step_timeout_seconds=120,
            max_signals_per_step=200,
        )
        await manager._save_bot_config(config)

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        await manager2.load_from_db()

        loaded = manager2.get_bot("bot-roundtrip")
        assert loaded is not None
        assert loaded.config.max_restart_attempts == 10
        assert loaded.config.restart_cooldown_seconds == 600
        assert loaded.config.step_timeout_seconds == 120
        assert loaded.config.max_signals_per_step == 200


class TestLegacyRowFallback:
    """config_json 에 runtime control 필드가 없는 legacy row 처리."""

    async def test_legacy_row_without_runtime_controls_uses_defaults(
        self, eventbus: EventBus, db: Database
    ) -> None:
        """4개 필드 + ``auto_restart`` 가 없는 legacy row 는 dataclass default
        로 복원된다. 회귀가 발생하면 default 값이 변경된 것이므로 SSOT
        (``BotConfig`` dataclass) 와 함께 갱신해야 한다.
        """
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        # config_json 에 interval_seconds 만 포함된 legacy 형식
        legacy_config_json = json.dumps({"interval_seconds": 45})
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "legacy-bot",
                "legacy",
                "s1",
                "acc-test",
                legacy_config_json,
                "created",
            ),
        )

        count = await manager.load_from_db()
        assert count == 1

        loaded = manager.get_bot("legacy-bot")
        assert loaded is not None
        # interval_seconds 는 legacy 값 유지
        assert loaded.config.interval_seconds == 45
        # runtime control 4개 + auto_restart 는 BotConfig dataclass default 로 복원
        defaults = BotConfig.__dataclass_fields__
        assert loaded.config.auto_restart is defaults["auto_restart"].default
        assert (
            loaded.config.max_restart_attempts
            == defaults["max_restart_attempts"].default
        )
        assert (
            loaded.config.restart_cooldown_seconds
            == defaults["restart_cooldown_seconds"].default
        )
        assert (
            loaded.config.step_timeout_seconds
            == defaults["step_timeout_seconds"].default
        )
        assert (
            loaded.config.max_signals_per_step
            == defaults["max_signals_per_step"].default
        )

    async def test_legacy_row_partial_runtime_controls_uses_defaults_for_missing(
        self, eventbus: EventBus, db: Database
    ) -> None:
        """일부 필드만 있는 legacy row 는 나머지를 default 로 채운다."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        # max_restart_attempts 만 저장된 부분 legacy row
        partial_config_json = json.dumps(
            {"interval_seconds": 60, "max_restart_attempts": 5}
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "partial-bot",
                "partial",
                "s1",
                "acc-test",
                partial_config_json,
                "created",
            ),
        )

        await manager.load_from_db()

        loaded = manager.get_bot("partial-bot")
        assert loaded is not None
        # 저장된 필드는 보존
        assert loaded.config.max_restart_attempts == 5
        # 나머지는 default
        defaults = BotConfig.__dataclass_fields__
        assert (
            loaded.config.restart_cooldown_seconds
            == defaults["restart_cooldown_seconds"].default
        )
        assert (
            loaded.config.step_timeout_seconds
            == defaults["step_timeout_seconds"].default
        )
        assert (
            loaded.config.max_signals_per_step
            == defaults["max_signals_per_step"].default
        )
        assert loaded.config.auto_restart is defaults["auto_restart"].default


class TestInvalidPersistedRowSkipped:
    """range 위반 값을 직접 저장한 row 는 load 단계에서 skip + warning."""

    async def test_invalid_runtime_control_row_skipped_with_warning(
        self, eventbus: EventBus, db: Database, caplog: pytest.LogCaptureFixture
    ) -> None:
        """invalid persisted row 가 단일 row 단위로 격리되고 전체 load 를
        깨뜨리지 않는다. 정상 row 는 그대로 로드된다.
        """
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()

        # 정상 row 1건
        valid_config = json.dumps(
            {
                "interval_seconds": 30,
                "max_restart_attempts": 3,
                "restart_cooldown_seconds": 60,
                "step_timeout_seconds": 30,
                "max_signals_per_step": 50,
            }
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("ok-bot", "ok", "s1", "acc-test", valid_config, "created"),
        )

        # invalid row: max_restart_attempts 범위 밖 (#1456 SSOT: 1~10)
        invalid_config = json.dumps(
            {
                "interval_seconds": 30,
                "max_restart_attempts": 999,
                "restart_cooldown_seconds": 60,
                "step_timeout_seconds": 30,
                "max_signals_per_step": 50,
            }
        )
        await db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("bad-bot", "bad", "s1", "acc-test", invalid_config, "created"),
        )

        with caplog.at_level(logging.WARNING):
            count = await manager.load_from_db()

        assert count == 1
        assert manager.get_bot("ok-bot") is not None
        assert manager.get_bot("bad-bot") is None

        warn_messages = [r.message for r in caplog.records if r.levelno >= 30]
        assert any("bad-bot" in m for m in warn_messages)
