"""DynamicConfigService 단위 테스트."""

import pytest

from ante.config import ConfigError, DynamicConfigService
from ante.core import Database
from ante.eventbus.events import ConfigChangedEvent


class FakeEventBus:
    """테스트용 EventBus 대역."""

    def __init__(self):
        self.published: list = []

    async def publish(self, event):
        self.published.append(event)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return FakeEventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = DynamicConfigService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


async def test_set_and_get(service):
    """동적 설정을 저장하고 조회한다."""
    await service.set("rule.max_daily_loss_rate", 0.03, category="rule")
    value = await service.get("rule.max_daily_loss_rate")
    assert value == 0.03


async def test_get_missing_raises(service):
    """존재하지 않는 키는 ConfigError."""
    with pytest.raises(ConfigError, match="Dynamic config not found"):
        await service.get("nonexistent")


async def test_get_missing_with_default(service):
    """default가 있으면 예외 대신 반환."""
    value = await service.get("nonexistent", default=42)
    assert value == 42


async def test_set_publishes_event(service, eventbus):
    """설정 변경 시 ConfigChangedEvent를 발행한다."""
    await service.set("key", "value", category="test")

    assert len(eventbus.published) == 1
    event = eventbus.published[0]
    assert isinstance(event, ConfigChangedEvent)
    assert event.key == "key"
    assert event.category == "test"


async def test_set_overwrites(service):
    """같은 키에 다시 설정하면 덮어쓴다."""
    await service.set("k", 1, category="c")
    await service.set("k", 2, category="c")
    assert await service.get("k") == 2


async def test_get_by_category(service):
    """카테고리별 조회."""
    await service.set("rule.a", 1, category="rule")
    await service.set("rule.b", 2, category="rule")
    await service.set("fund.c", 3, category="fund")

    rules = await service.get_by_category("rule")
    assert len(rules) == 2
    assert rules["rule.a"] == 1
    assert rules["rule.b"] == 2


async def test_exists(service):
    """존재 여부 확인."""
    assert not await service.exists("x")
    await service.set("x", 1, category="c")
    assert await service.exists("x")


async def test_delete(service):
    """설정 삭제."""
    await service.set("x", 1, category="c")
    assert await service.delete("x")
    assert not await service.exists("x")


async def test_delete_nonexistent(service):
    """존재하지 않는 키 삭제 시 False."""
    assert not await service.delete("nonexistent")


async def test_json_complex_types(service):
    """복합 JSON 타입 저장/복원."""
    await service.set("list_val", [1, 2, 3], category="test")
    assert await service.get("list_val") == [1, 2, 3]

    await service.set("dict_val", {"a": 1}, category="test")
    assert await service.get("dict_val") == {"a": 1}
