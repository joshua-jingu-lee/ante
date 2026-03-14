"""DynamicConfigService 변경 이력(audit trail) 테스트."""

import pytest

from ante.config import DynamicConfigService
from ante.core import Database


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


async def test_set_records_history(service):
    """set() 호출 시 이력이 기록된다."""
    await service.set("rule.loss", 0.03, category="rule", changed_by="cli:master-1")

    history = await service.get_history("rule.loss")
    assert len(history) == 1
    row = history[0]
    assert row["key"] == "rule.loss"
    assert row["old_value"] is None
    assert row["new_value"] == "0.03"
    assert row["changed_by"] == "cli:master-1"
    assert row["changed_at"] is not None


async def test_set_records_old_value(service):
    """기존 값이 있으면 old_value에 기록된다."""
    await service.set("k", 1, category="c", changed_by="system")
    await service.set("k", 2, category="c", changed_by="web:agent-1")

    history = await service.get_history("k")
    assert len(history) == 2
    # 최신순이므로 첫 번째가 두 번째 변경
    latest = history[0]
    assert latest["old_value"] == "1"
    assert latest["new_value"] == "2"
    assert latest["changed_by"] == "web:agent-1"


async def test_set_default_changed_by(service):
    """changed_by 미지정 시 기본값은 'system'."""
    await service.set("k", 1, category="c")

    history = await service.get_history("k")
    assert history[0]["changed_by"] == "system"


async def test_get_history_limit(service):
    """limit 파라미터가 반환 건수를 제한한다."""
    for i in range(10):
        await service.set("k", i, category="c", changed_by="test")

    history = await service.get_history("k", limit=3)
    assert len(history) == 3
    # 최신순: 9, 8, 7
    assert history[0]["new_value"] == "9"
    assert history[2]["new_value"] == "7"


async def test_get_history_empty(service):
    """이력이 없으면 빈 리스트."""
    history = await service.get_history("nonexistent")
    assert history == []


async def test_cleanup_history(service, db):
    """retention 기간보다 오래된 이력이 삭제된다."""
    await service.set("k", 1, category="c", changed_by="test")

    # 이력을 과거로 조작
    await db.execute(
        "UPDATE dynamic_config_history SET changed_at = datetime('now', '-100 days')"
    )

    deleted = await service.cleanup_history(retention_days=90)
    assert deleted == 1

    history = await service.get_history("k")
    assert len(history) == 0


async def test_cleanup_history_keeps_recent(service):
    """retention 기간 내의 이력은 보존된다."""
    await service.set("k", 1, category="c", changed_by="test")

    deleted = await service.cleanup_history(retention_days=90)
    assert deleted == 0

    history = await service.get_history("k")
    assert len(history) == 1


async def test_history_isolated_by_key(service):
    """다른 키의 이력은 섞이지 않는다."""
    await service.set("a", 1, category="c", changed_by="test")
    await service.set("b", 2, category="c", changed_by="test")

    assert len(await service.get_history("a")) == 1
    assert len(await service.get_history("b")) == 1
