"""EventHistoryStore 단위 테스트."""

import pytest

from ante.core import Database
from ante.eventbus.events import BotStartedEvent, OrderRequestEvent
from ante.eventbus.history import EventHistoryStore


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def store(db):
    s = EventHistoryStore(db=db)
    await s.initialize()
    return s


async def test_record_and_query(store):
    """이벤트를 기록하고 조회한다."""
    event = OrderRequestEvent(symbol="005930", side="buy")
    await store.record(event)

    rows = await store.query()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "OrderRequestEvent"
    assert rows[0]["payload"]["symbol"] == "005930"


async def test_query_by_type(store):
    """이벤트 타입으로 필터링 조회."""
    await store.record(OrderRequestEvent(symbol="A"))
    await store.record(BotStartedEvent(bot_id="b"))
    await store.record(OrderRequestEvent(symbol="B"))

    rows = await store.query(event_type="OrderRequestEvent")
    assert len(rows) == 2
    assert all(r["event_type"] == "OrderRequestEvent" for r in rows)


async def test_query_limit(store):
    """limit으로 반환 건수를 제한한다."""
    for i in range(10):
        await store.record(OrderRequestEvent(symbol=str(i)))

    rows = await store.query(limit=3)
    assert len(rows) == 3


async def test_query_order(store):
    """최신순으로 반환한다."""
    await store.record(OrderRequestEvent(symbol="first"))
    await store.record(OrderRequestEvent(symbol="second"))

    rows = await store.query()
    assert rows[0]["payload"]["symbol"] == "second"
    assert rows[1]["payload"]["symbol"] == "first"
