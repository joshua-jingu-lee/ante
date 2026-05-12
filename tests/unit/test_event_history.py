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
    유지된다 (#1437 r2).

    r1은 ``until``을 ``limit`` 앞 위치 인자로 추가해 ``query(type, since, 50)``
    같은 세 번째 위치 인자 ``50``이 ``limit`` 대신 ``until``로 잘못 바인딩되는
    silent failure가 있었다. r2는 ``until``/``offset``/``payload_filter``를
    keyword-only로 옮기고 ``limit``을 세 번째 위치 인자 자리에 유지한다.
    """
    for i in range(3):
        await store.record(OrderRequestEvent(symbol=str(i), account_id="acc"))
    # 세 번째 위치 인자가 ``limit``으로 안전하게 바인딩되는지 (r2 회귀).
    rows_pos = await store.query("OrderRequestEvent", None, 10)
    assert len(rows_pos) == 3
    # Keyword 호출은 그대로 유지.
    rows_kw = await store.query(event_type="OrderRequestEvent", limit=10)
    assert len(rows_kw) == 3


# ── #1437 r2: payload_filter (SQL JSON1) + keyword-only signature 회귀 ─────


async def test_query_payload_filter_bot_id(store):
    """``payload_filter={"bot_id": ...}``가 SQL JSON1 ``json_extract``로
    payload 내부 ``bot_id``를 SQL 단계에서 필터링한다 (#1437 r2).

    r1은 ``bot_id``가 payload JSON 안에 있어 SQL 직접 필터가 어렵다는
    이유로 매칭 가능 범위를 한번에 fetch한 뒤 in-memory에서 ``bot_id``를
    필터링했는데, hard cap을 다른 봇의 로그가 먼저 채우면 특정 봇의
    로그가 누락되는 silent failure가 있었다. r2는 SQL JSON1로 이를 해결.
    """
    await store.record(BotStartedEvent(bot_id="bot-A", account_id="acc"))
    await store.record(BotStartedEvent(bot_id="bot-B", account_id="acc"))
    await store.record(BotStartedEvent(bot_id="bot-A", account_id="acc"))

    rows = await store.query(payload_filter={"bot_id": "bot-A"})
    assert len(rows) == 2
    assert all(r["payload"]["bot_id"] == "bot-A" for r in rows)


async def test_count_payload_filter_bot_id(store):
    """``count(payload_filter=...)``가 ``query``와 동일한 SQL JSON1 필터를
    적용해 페이지네이션과 무관한 total을 반환한다 (#1437 r2).
    """
    await store.record(BotStartedEvent(bot_id="bot-A", account_id="acc"))
    await store.record(BotStartedEvent(bot_id="bot-B", account_id="acc"))
    await store.record(BotStartedEvent(bot_id="bot-A", account_id="acc"))

    assert await store.count(payload_filter={"bot_id": "bot-A"}) == 2
    assert await store.count(payload_filter={"bot_id": "bot-B"}) == 1
    assert await store.count(payload_filter={"bot_id": "bot-X"}) == 0


async def test_query_payload_filter_combines_with_event_type(store):
    """``payload_filter``가 ``event_type``과 AND 결합되어 둘 다 만족하는
    row만 반환한다 (#1437 r2).
    """
    await store.record(BotStartedEvent(bot_id="bot-A", account_id="acc"))
    await store.record(OrderRequestEvent(symbol="bot-A", account_id="acc"))  # 다른 type

    rows = await store.query(
        event_type="BotStartedEvent", payload_filter={"bot_id": "bot-A"}
    )
    assert len(rows) == 1
    assert rows[0]["event_type"] == "BotStartedEvent"


async def test_query_payload_filter_with_large_other_bot_volume(store):
    """다른 봇의 이벤트가 대량으로 있어도 특정 봇의 모든 로그가 반환된다
    (#1437 r2 — hard cap 제거 회귀).

    r1은 fetch hard cap=10000이 다른 봇 로그로 채워지면 특정 봇의 로그가
    누락되는 silent failure였다. r2는 SQL JSON1 ``payload_filter``로
    SQL 단계 필터링하므로 cap 무관하게 정확.
    """
    # bot-X의 로그를 대량으로 기록 (cap 시뮬레이션).
    for i in range(50):
        await store.record(BotStartedEvent(bot_id="bot-X", account_id=f"acc-{i}"))
    # bot-target의 로그를 가장 오래된 시점에 1개만 기록 (역순에서 마지막).
    # 위에서 50개를 먼저 기록했으므로 ``ORDER BY id DESC``에서 target은 51번째.
    # 그러나 SQL 단계에서 bot_id로 필터링하면 target만 정확히 잡힌다.
    await store.record(BotStartedEvent(bot_id="bot-target", account_id="acc-special"))

    # cap 시뮬레이션: limit=10으로 작게 잡아도 target은 정확히 1건 반환.
    rows = await store.query(limit=10, payload_filter={"bot_id": "bot-target"})
    assert len(rows) == 1
    assert rows[0]["payload"]["bot_id"] == "bot-target"
    total = await store.count(payload_filter={"bot_id": "bot-target"})
    assert total == 1


async def test_query_keyword_only_until_offset_payload_filter(store):
    """``until``/``offset``/``payload_filter``가 keyword-only (#1437 r2).

    r1 시그니처는 ``until``이 ``limit`` 앞 위치 인자였다 (silent 오바인딩
    위험). r2는 keyword-only로 강제해 위치 인자 오류를 컴파일 단계에서
    차단한다.
    """
    import inspect

    sig = inspect.signature(store.query)
    until_param = sig.parameters["until"]
    offset_param = sig.parameters["offset"]
    payload_filter_param = sig.parameters["payload_filter"]
    assert until_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert offset_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert payload_filter_param.kind == inspect.Parameter.KEYWORD_ONLY

    count_sig = inspect.signature(store.count)
    assert count_sig.parameters["until"].kind == inspect.Parameter.KEYWORD_ONLY
    assert count_sig.parameters["payload_filter"].kind == inspect.Parameter.KEYWORD_ONLY
