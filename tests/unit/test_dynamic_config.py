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


# ── #1379 oracle A7: system.log_level 서비스 경계 검증 ────────────────


async def test_set_invalid_log_level_raises_value_error(service, eventbus):
    """invalid system.log_level 값은 ValueError 로 거부된다 (서비스 경계).

    IPC/CLI/web 어느 경로든 서비스 경계를 통과하지 못해야 한다 — oracle
    probe 가 보낸 ``ORACLE_INVALID_LEVEL`` 같은 값이 dynamic_config 와
    history 에 영구 저장되는 경로를 차단한다.
    """
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", "ORACLE_INVALID_LEVEL", category="system")

    # 영속/이벤트 사이드이펙트가 발생하지 않아야 한다.
    assert not await service.exists("system.log_level")
    assert eventbus.published == []


async def test_set_valid_log_level_succeeds(service, eventbus):
    """``_VALID_LOG_LEVELS`` 멤버(대문자) 값은 그대로 통과한다."""
    await service.set("system.log_level", "DEBUG", category="system")
    assert await service.get("system.log_level") == "DEBUG"
    assert len(eventbus.published) == 1


async def test_set_unknown_key_no_validation_succeeds(service):
    """invariant 가 정의되지 않은 키는 generic CRUD 동작 그대로 통과."""
    # 임의 string/dict/list 모두 통과해야 generic 동작이 유지된다.
    await service.set("any.unknown.key", "anything", category="misc")
    assert await service.get("any.unknown.key") == "anything"

    await service.set("another.unknown", {"complex": [1, 2]}, category="misc")
    assert await service.get("another.unknown") == {"complex": [1, 2]}


async def test_set_lowercase_log_level_raises_value_error(service, eventbus):
    """대소문자 정책: 소문자 ``"debug"`` 는 거부 (대소문자 구분, #1379)."""
    with pytest.raises(ValueError, match="대소문자 구분"):
        await service.set("system.log_level", "debug", category="system")

    assert not await service.exists("system.log_level")
    assert eventbus.published == []


async def test_set_non_string_log_level_raises_value_error(service, eventbus):
    """문자열이 아닌 값(숫자/None 등)도 거부."""
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", 10, category="system")
    with pytest.raises(ValueError, match="system.log_level"):
        await service.set("system.log_level", None, category="system")

    assert not await service.exists("system.log_level")
    assert eventbus.published == []
