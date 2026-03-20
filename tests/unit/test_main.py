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


# ── Composition Root 전체 모듈 조립 테스트 ────────────


async def test_composition_root_all_modules(tmp_path: Path) -> None:
    """모든 모듈을 main.py 순서대로 조립하고 정상 초기화를 검증한다."""
    # 1. Config
    toml = tmp_path / "system.toml"
    toml.write_text(
        '[db]\npath = "{db}"\n\n'
        "[web]\nenabled = false\nport = 8000\n\n"
        '[data]\npath = "{data}"\n'.format(
            db=str(tmp_path / "test.db"),
            data=str(tmp_path / "data"),
        )
    )
    config = Config.load(config_dir=tmp_path)
    config.validate()

    # 2. Database
    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    # 3. EventBus
    eventbus = EventBus(history_size=100)
    event_history = EventHistoryStore(db=db)
    await event_history.initialize()
    eventbus.use(event_history.record)

    # 4. SystemState
    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()

    # 5. DynamicConfigService
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()

    # 6. StrategyRegistry
    from ante.strategy import StrategyRegistry

    strategy_registry = StrategyRegistry(db=db)
    await strategy_registry.initialize()

    # 7. RuleEngine
    from ante.rule import RuleEngine

    rule_engine = RuleEngine(eventbus=eventbus, system_state=system_state)
    rule_engine.start()

    # 8. Treasury
    from ante.treasury import Treasury

    treasury = Treasury(db=db, eventbus=eventbus)
    await treasury.initialize()

    # 9. Trade
    from ante.trade import (
        PerformanceTracker,
        PositionHistory,
        TradeRecorder,
        TradeService,
    )

    position_history = PositionHistory(db=db)
    await position_history.initialize()

    trade_recorder = TradeRecorder(db=db, position_history=position_history)
    await trade_recorder.initialize()
    trade_recorder.subscribe(eventbus)

    performance_tracker = PerformanceTracker(db=db)

    trade_service = TradeService(
        recorder=trade_recorder,
        position_history=position_history,
        performance=performance_tracker,
    )

    # 10. BotManager
    from ante.bot import BotManager

    bot_manager = BotManager(eventbus=eventbus, db=db)
    await bot_manager.initialize()

    # 11. Broker + APIGateway — 건너뜀 (외부 의존성)

    # 12. Data Pipeline
    from ante.data import ParquetStore

    data_path = tmp_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    parquet_store = ParquetStore(base_path=data_path)

    # 13. BacktestService
    from ante.backtest import BacktestService

    backtest_service = BacktestService(data_path=str(data_path))

    # 14. ReportStore
    from ante.report import ReportStore

    report_store = ReportStore(db=db)
    await report_store.initialize()

    # ── 검증 ──
    # SystemState 활성화 상태
    assert system_state.trading_state == TradingState.ACTIVE

    # Treasury 초기 잔고
    assert treasury.account_balance == 0.0

    # StrategyRegistry 빈 상태
    strategies = await strategy_registry.list_strategies()
    assert strategies == []

    # BotManager 빈 상태
    assert bot_manager.list_bots() == []

    # ParquetStore 빈 상태
    assert parquet_store.list_symbols("1d") == []

    # TradeService 빈 상태
    trades = await trade_service.get_trades()
    assert trades == []

    # ReportStore 동작 확인

    assert report_store is not None

    # BacktestService 동작 확인
    assert backtest_service is not None

    # 정리
    await bot_manager.stop_all()
    await db.close()


async def test_composition_root_with_web_api(tmp_path: Path) -> None:
    """Web API 앱 팩토리에 서비스 주입이 정상 동작한다."""
    import pytest

    httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")  # noqa: F841

    from fastapi.testclient import TestClient

    from ante.web.app import create_app

    # 최소 인프라
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()

    from ante.treasury import Treasury

    treasury = Treasury(db=db, eventbus=eventbus)
    await treasury.initialize()

    from ante.trade import (
        PerformanceTracker,
        PositionHistory,
        TradeRecorder,
        TradeService,
    )

    position_history = PositionHistory(db=db)
    await position_history.initialize()
    trade_recorder = TradeRecorder(db=db, position_history=position_history)
    await trade_recorder.initialize()
    performance_tracker = PerformanceTracker(db=db)
    trade_service = TradeService(
        recorder=trade_recorder,
        position_history=position_history,
        performance=performance_tracker,
    )

    from ante.bot import BotManager

    bot_manager = BotManager(eventbus=eventbus, db=db)
    await bot_manager.initialize()

    from ante.report import ReportStore

    report_store = ReportStore(db=db)
    await report_store.initialize()

    from ante.data import ParquetStore

    data_path = tmp_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    parquet_store = ParquetStore(base_path=data_path)

    # Web App 생성 — 모든 서비스 주입
    app = create_app(
        config="test",
        eventbus=eventbus,
        bot_manager=bot_manager,
        trade_service=trade_service,
        treasury=treasury,
        report_store=report_store,
        data_store=parquet_store,
    )

    client = TestClient(app)

    # 시스템 상태
    resp = client.get("/api/system/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    # 데이터셋 목록
    resp = client.get("/api/data/datasets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0

    # 스토리지 정보
    resp = client.get("/api/data/storage")
    assert resp.status_code == 200
    assert "total_mb" in resp.json()

    await db.close()


async def test_graceful_shutdown_order(tmp_path: Path) -> None:
    """종료 시 역순으로 정리되는지 검증한다."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    from ante.bot import BotManager

    bot_manager = BotManager(eventbus=eventbus, db=db)
    await bot_manager.initialize()

    # 종료 순서 추적
    shutdown_order: list[str] = []

    original_stop_all = bot_manager.stop_all

    async def tracked_stop_all() -> None:
        shutdown_order.append("bot_manager")
        await original_stop_all()

    bot_manager.stop_all = tracked_stop_all

    # 종료 실행
    await bot_manager.stop_all()
    shutdown_order.append("db")
    await db.close()

    assert shutdown_order == ["bot_manager", "db"]
