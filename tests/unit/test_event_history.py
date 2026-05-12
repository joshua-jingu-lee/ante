"""EventHistoryStore 단위 테스트."""

from datetime import UTC, datetime, timedelta

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
    event = OrderRequestEvent(symbol="005930", side="buy", account_id="acc-test")
    await store.record(event)

    rows = await store.query()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "OrderRequestEvent"
    assert rows[0]["payload"]["symbol"] == "005930"


async def test_query_by_type(store):
    """이벤트 타입으로 필터링 조회."""
    await store.record(OrderRequestEvent(symbol="A", account_id="acc-test"))
    await store.record(BotStartedEvent(bot_id="b", account_id="acc-test"))
    await store.record(OrderRequestEvent(symbol="B", account_id="acc-test"))

    rows = await store.query(event_type="OrderRequestEvent")
    assert len(rows) == 2
    assert all(r["event_type"] == "OrderRequestEvent" for r in rows)


async def test_query_limit(store):
    """limit으로 반환 건수를 제한한다."""
    for i in range(10):
        await store.record(OrderRequestEvent(symbol=str(i), account_id="acc-test"))

    rows = await store.query(limit=3)
    assert len(rows) == 3


async def test_query_order(store):
    """최신순으로 반환한다."""
    await store.record(OrderRequestEvent(symbol="first", account_id="acc-test"))
    await store.record(OrderRequestEvent(symbol="second", account_id="acc-test"))

    rows = await store.query()
    assert rows[0]["payload"]["symbol"] == "second"
    assert rows[1]["payload"]["symbol"] == "first"


# ── #1437 r1: query(offset, until) + count() 시그니처 확장 회귀 ─────


async def test_query_offset_skips_rows(store):
    """``offset`` 파라미터가 SQL OFFSET으로 row를 건너뛴다.

    Codex P2 (#1437 r1): r0의 ``store.query(limit=limit)`` + in-memory 슬라이스
    패턴은 store가 처음부터 ``LIMIT limit``만 fetch해 페이지네이션 2페이지가
    비거나 짧았다. r1은 store에 ``offset``을 추가했다.
    """
    for i in range(5):
        await store.record(OrderRequestEvent(symbol=str(i), account_id="acc-test"))
    # 최신순(``ORDER BY id DESC``)으로 reversed: [4, 3, 2, 1, 0]
    page1 = await store.query(limit=2, offset=0)
    page2 = await store.query(limit=2, offset=2)
    page3 = await store.query(limit=2, offset=4)
    assert [r["payload"]["symbol"] for r in page1] == ["4", "3"]
    assert [r["payload"]["symbol"] for r in page2] == ["2", "1"]
    assert [r["payload"]["symbol"] for r in page3] == ["0"]


async def test_query_until_inclusive_upper_bound(store):
    """``until`` 파라미터가 ``timestamp <= until`` inclusive upper bound.

    Codex P2 (#1437 r1): r0 시그니처는 ``since``만 있었다. ``until`` 추가로
    날짜 범위 윈도우 검색이 가능해졌다.
    """
    # OrderRequestEvent는 기본 ``timestamp=datetime.now(UTC)``. 임의 timestamp
    # 주입을 위해 dataclass 키워드 인자로 명시.
    t0 = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC)
    for ts, sym in [(t0, "a"), (t1, "b"), (t2, "c")]:
        await store.record(
            OrderRequestEvent(symbol=sym, account_id="acc", timestamp=ts)
        )

    rows = await store.query(until=t1)
    symbols = sorted(r["payload"]["symbol"] for r in rows)
    assert symbols == ["a", "b"]


async def test_query_since_and_until_combine(store):
    """``since`` + ``until`` 조합으로 윈도우 검색."""
    t0 = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC)
    for ts, sym in [(t0, "a"), (t1, "b"), (t2, "c")]:
        await store.record(
            OrderRequestEvent(symbol=sym, account_id="acc", timestamp=ts)
        )

    rows = await store.query(since=t1, until=t1 + timedelta(hours=1))
    assert [r["payload"]["symbol"] for r in rows] == ["b"]


async def test_count_matches_query_total(store):
    """``count()``가 ``query()`` 매칭 row 수와 일치 (페이지네이션 무관).

    Codex P2 (#1437 r1): r0 핸들러는 ``len(filtered)``로 in-memory total을
    계산했는데, store가 ``limit``개만 fetch했으므로 total이 limit 범위로
    잘렸다. r1은 store에 ``count()`` 메서드를 추가해 ``offset``/``limit``과
    무관한 정확한 총 개수를 SQL COUNT로 얻는다.
    """
    for i in range(7):
        await store.record(OrderRequestEvent(symbol=str(i), account_id="acc"))
    assert await store.count() == 7
    assert await store.count(event_type="OrderRequestEvent") == 7
    assert await store.count(event_type="NoSuchEvent") == 0


async def test_count_respects_since_until(store):
    """``count(since, until)``이 ``query`` 와 동일한 윈도우 필터를 적용한다."""
    t0 = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 5, 11, 0, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC)
    for ts, sym in [(t0, "a"), (t1, "b"), (t2, "c")]:
        await store.record(
            OrderRequestEvent(symbol=sym, account_id="acc", timestamp=ts)
        )

    assert await store.count(since=t1) == 2
    assert await store.count(until=t1) == 2
    assert await store.count(since=t1, until=t1 + timedelta(hours=1)) == 1


async def test_query_signature_backwards_compatible(store):
    """기존 ``query(event_type, since, limit)`` 호출이 새 파라미터 default로
    유지된다 (#1437 r1).

    ``until``/``offset``은 keyword-only가 아니지만, 모두 기본값을 가지므로
    위치 인자만 쓰던 기존 호출자에 영향이 없다.
    """
    for i in range(3):
        await store.record(OrderRequestEvent(symbol=str(i), account_id="acc"))
    rows = await store.query(event_type="OrderRequestEvent", limit=10)
    assert len(rows) == 3
