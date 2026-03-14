"""동적 log_level 변경 단위 테스트."""

import json
import logging

import pytest

from ante.config.dynamic import DynamicConfigService, _on_log_level_changed
from ante.core import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ConfigChangedEvent


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
async def service(db, eventbus):
    svc = DynamicConfigService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


# ── register_default 테스트 ────────────────────────


async def test_register_default_inserts_when_missing(service):
    """키가 없으면 기본값을 등록한다."""
    await service.register_default("system.log_level", "INFO", category="system")
    assert await service.get("system.log_level") == "INFO"


async def test_register_default_skips_when_existing(service):
    """이미 값이 있으면 기본값을 무시한다."""
    await service.set("system.log_level", "DEBUG", category="system")
    await service.register_default("system.log_level", "INFO", category="system")
    assert await service.get("system.log_level") == "DEBUG"


# ── _on_log_level_changed 핸들러 테스트 ────────────


def test_log_level_changed_updates_root_logger():
    """system.log_level 변경 시 루트 로거 레벨이 갱신된다."""
    original = logging.getLogger().level

    event = ConfigChangedEvent(
        category="system",
        key="system.log_level",
        old_value=json.dumps("INFO"),
        new_value=json.dumps("DEBUG"),
    )
    _on_log_level_changed(event)

    assert logging.getLogger().level == logging.DEBUG

    # 원복
    logging.getLogger().setLevel(original)


def test_log_level_changed_ignores_other_keys():
    """system.log_level이 아닌 키 변경은 무시한다."""
    original = logging.getLogger().level

    event = ConfigChangedEvent(
        category="system",
        key="system.other_setting",
        old_value=json.dumps("old"),
        new_value=json.dumps("new"),
    )
    _on_log_level_changed(event)

    assert logging.getLogger().level == original


def test_log_level_changed_ignores_invalid_level():
    """유효하지 않은 로그 레벨은 무시한다."""
    logging.getLogger().setLevel(logging.INFO)

    event = ConfigChangedEvent(
        category="system",
        key="system.log_level",
        old_value=json.dumps("INFO"),
        new_value=json.dumps("INVALID_LEVEL"),
    )
    _on_log_level_changed(event)

    assert logging.getLogger().level == logging.INFO


# ── EventBus 통합 테스트 ───────────────────────────


async def test_eventbus_integration(service, eventbus):
    """DynamicConfigService.set()으로 log_level 변경 시 루트 로거가 갱신된다."""
    original = logging.getLogger().level
    eventbus.subscribe(ConfigChangedEvent, _on_log_level_changed)

    await service.set("system.log_level", "WARNING", category="system")

    assert logging.getLogger().level == logging.WARNING

    # 원복
    logging.getLogger().setLevel(original)
