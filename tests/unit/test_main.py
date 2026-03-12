"""main.py 통합 초기화 테스트."""

from pathlib import Path

from ante.config import Config, DynamicConfigService, SystemState, TradingState
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore
from ante.eventbus.events import OrderRequestEvent


async def test_full_initialization(tmp_path: Path) -> None:
    """Config → Database → EventBus → SystemState → DynamicConfig 초기화."""
    # 1. Config
    toml = tmp_path / "system.toml"
    toml.write_text(
        '[db]\npath = "{}"\n\n[web]\nport = 8000\n'.format(str(tmp_path / "test.db"))
    )
    config = Config.load(config_dir=tmp_path)
    config.validate()

    # 2. Database
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    # 3. EventBus + EventHistoryStore
    eventbus = EventBus(history_size=100)
    history_store = EventHistoryStore(db=db)
    await history_store.initialize()
    eventbus.use(history_store.record)

    # 4. SystemState
    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()
    assert system_state.trading_state == TradingState.ACTIVE

    # 5. DynamicConfigService
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()

    # 검증: 이벤트 발행 → 인메모리 히스토리 + SQLite 영속화
    event = OrderRequestEvent(symbol="005930", side="buy", quantity=10.0)
    await eventbus.publish(event)

    # 인메모리 히스토리
    mem_history = eventbus.get_history()
    assert len(mem_history) == 1
    assert mem_history[0].symbol == "005930"

    # SQLite 영속화
    db_history = await history_store.query()
    assert len(db_history) == 1
    assert db_history[0]["event_type"] == "OrderRequestEvent"

    # SystemState 상태 변경 → 이벤트 발행 + DB 영속화
    await system_state.set_state(TradingState.HALTED, reason="test", changed_by="test")
    assert system_state.trading_state == TradingState.HALTED

    # DynamicConfig CRUD
    await dynamic_config.set("test.key", 42, category="test")
    assert await dynamic_config.get("test.key") == 42

    # 정리
    await db.close()


async def test_eventbus_middleware_records_all_events(
    tmp_path: Path,
) -> None:
    """EventBus 미들웨어가 모든 이벤트를 SQLite에 기록한다."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus()
    store = EventHistoryStore(db=db)
    await store.initialize()
    eventbus.use(store.record)

    # 여러 이벤트 발행
    for i in range(5):
        await eventbus.publish(OrderRequestEvent(symbol=f"sym{i}"))

    rows = await store.query(limit=10)
    assert len(rows) == 5

    await db.close()
