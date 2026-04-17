"""main.py 통합 초기화 테스트 — Account 중심 Composition Root."""

from pathlib import Path

from ante.config import Config, DynamicConfigService
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore
from ante.eventbus.events import OrderRequestEvent


async def test_full_initialization(tmp_path: Path) -> None:
    """Config → Database → EventBus → AccountService → DynamicConfig 초기화."""
    # 1. Config
    toml = tmp_path / "system.toml"
    toml.write_text(
        '[db]\npath = "{}"\n\n[web]\nport = 3982\n'.format(str(tmp_path / "test.db"))
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

    # 4. AccountService
    from ante.account.service import AccountService

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

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

    # AccountService 기본 동작
    accounts = await account_service.list()
    assert isinstance(accounts, list)

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


# ── Composition Root 전체 모듈 조립 테스트 (Account 중심) ────────────


async def _create_test_account(db: Database, eventbus: EventBus):
    """테스트용 AccountService + 기본 테스트 계좌 생성 헬퍼."""
    from ante.account import AccountService

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    await account_service.create_default_test_account()
    return account_service


async def test_composition_root_account_based(tmp_path: Path) -> None:
    """Account 중심 Composition Root: TreasuryManager, RuleEngineManager 초기화."""
    # 1. Config
    toml = tmp_path / "system.toml"
    toml.write_text(
        '[db]\npath = "{db}"\n\n'
        "[web]\nenabled = false\nport = 3982\n\n"
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

    # 4. AccountService + 테스트 계좌
    account_service = await _create_test_account(db, eventbus)

    accounts = await account_service.list()
    assert len(accounts) == 1
    assert accounts[0].account_id == "test"

    # 5. DynamicConfigService
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()

    # 6. StrategyRegistry
    from ante.strategy import StrategyRegistry

    strategy_registry = StrategyRegistry(db=db)
    await strategy_registry.initialize()

    # 7. Trade
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

    # 8. TreasuryManager — 계좌별 Treasury 관리
    from ante.treasury import TreasuryManager

    treasury_manager = TreasuryManager(db=db, eventbus=eventbus)
    await treasury_manager.initialize_all(accounts)

    # 각 계좌의 Treasury가 생성되었는지 확인
    test_treasury = treasury_manager.get("test")
    assert test_treasury.account_balance == 0.0

    # 9. RuleEngineManager — 계좌별 RuleEngine 관리
    from ante.rule import RuleEngineManager

    rule_engine_manager = RuleEngineManager(
        eventbus=eventbus,
        account_service=account_service,
    )
    await rule_engine_manager.initialize_all(accounts, config=config)

    # 각 계좌의 RuleEngine이 생성되었는지 확인
    test_engine = rule_engine_manager.get("test")
    assert test_engine.account_id == "test"

    # 10. BotManager
    from ante.bot import BotManager

    bot_manager = BotManager(
        eventbus=eventbus,
        db=db,
        account_service=account_service,
    )
    await bot_manager.initialize()

    # 11. Data Pipeline
    from ante.data import ParquetStore

    data_path = tmp_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    parquet_store = ParquetStore(base_path=data_path)

    # 12. BacktestService
    from ante.backtest import BacktestService

    backtest_service = BacktestService(data_path=str(data_path))

    # 13. ReportStore
    from ante.report import ReportStore

    report_store = ReportStore(db=db)
    await report_store.initialize()

    # ── 검증 ──
    assert treasury_manager.list_all() != []
    assert rule_engine_manager.engines != {}
    assert bot_manager.list_bots() == []
    assert parquet_store.list_symbols("1d") == []

    trades = await trade_service.get_trades()
    assert trades == []

    strategies = await strategy_registry.list_strategies()
    assert strategies == []

    assert report_store is not None
    assert backtest_service is not None

    # 정리
    await bot_manager.stop_all()
    await db.close()


async def test_services_dataclass_no_single_broker_treasury_rule(
    tmp_path: Path,
) -> None:
    """Services 데이터클래스에 단일 broker/treasury/rule_engine 필드가 없다."""
    from ante.main import Services

    s = Services()
    # 제거된 필드
    assert not hasattr(s, "broker")
    assert not hasattr(s, "treasury")
    assert not hasattr(s, "rule_engine")

    # 추가된 필드
    assert hasattr(s, "treasury_manager")
    assert hasattr(s, "rule_engine_manager")
    assert hasattr(s, "account_service")

    # 기본값은 None
    assert s.treasury_manager is None
    assert s.rule_engine_manager is None
    assert s.account_service is None


async def test_init_account_creates_test_account(tmp_path: Path) -> None:
    """계좌가 없을 때 _init_account가 테스트 계좌를 자동 생성한다."""
    from ante.main import Services, _init_account

    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus(history_size=100)
    config = Config(static={}, secrets={})
    s = Services(db=db, eventbus=eventbus, config=config)

    await _init_account(s)

    # 테스트 계좌가 자동 생성되었는지 확인
    accounts = await s.account_service.list()
    assert len(accounts) == 1
    assert accounts[0].account_id == "test"
    assert accounts[0].broker_type == "test"

    await db.close()


async def test_init_account_skips_when_accounts_exist(tmp_path: Path) -> None:
    """이미 계좌가 있으면 테스트 계좌를 자동 생성하지 않는다."""
    from ante.account import Account, AccountService, TradingMode
    from ante.main import Services, _init_account

    db = Database(str(tmp_path / "test.db"))
    await db.connect()

    eventbus = EventBus(history_size=100)

    # 미리 계좌 생성
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    existing = Account(
        account_id="my-account",
        name="내 계좌",
        broker_type="kis-domestic",
        exchange="KRX",
        trading_mode=TradingMode.LIVE,
        currency="KRW",
        credentials={"app_key": "test", "app_secret": "test", "account_no": "test"},
    )
    await account_service.create(existing)

    # _init_account 재실행
    config = Config(static={}, secrets={})
    s = Services(db=db, eventbus=eventbus, config=config)
    await _init_account(s)

    accounts = await s.account_service.list()
    assert len(accounts) == 1
    assert accounts[0].account_id == "my-account"

    await db.close()


async def test_composition_root_with_web_api(tmp_path: Path) -> None:
    """Web API 앱 팩토리에 Account 기반 서비스 주입이 정상 동작한다."""
    import pytest

    httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")  # noqa: F841

    from fastapi.testclient import TestClient

    from ante.web.app import create_app

    # 최소 인프라
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    account_service = await _create_test_account(db, eventbus)
    accounts = await account_service.list()

    from ante.treasury import TreasuryManager

    treasury_manager = TreasuryManager(db=db, eventbus=eventbus)
    await treasury_manager.initialize_all(accounts)

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

    bot_manager = BotManager(
        eventbus=eventbus,
        db=db,
        account_service=account_service,
    )
    await bot_manager.initialize()

    from ante.report import ReportStore

    report_store = ReportStore(db=db)
    await report_store.initialize()

    from ante.data import ParquetStore

    data_path = tmp_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    parquet_store = ParquetStore(base_path=data_path)

    # Web App 생성 — Account 기반 서비스 주입
    app = create_app(
        config="test",
        eventbus=eventbus,
        bot_manager=bot_manager,
        trade_service=trade_service,
        treasury_manager=treasury_manager,
        report_store=report_store,
        data_store=parquet_store,
        account_service=account_service,
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
    """종료 시 계좌별 리소스가 역순으로 정리되는지 검증한다."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    account_service = await _create_test_account(db, eventbus)
    accounts = await account_service.list()

    from ante.treasury import TreasuryManager

    treasury_manager = TreasuryManager(db=db, eventbus=eventbus)
    await treasury_manager.initialize_all(accounts)

    from ante.bot import BotManager

    bot_manager = BotManager(
        eventbus=eventbus,
        db=db,
        account_service=account_service,
    )
    await bot_manager.initialize()

    # 종료 순서 추적
    shutdown_order: list[str] = []

    # Treasury sync 중지 추적
    test_treasury = treasury_manager.get("test")
    original_stop_sync = test_treasury.stop_sync

    async def tracked_stop_sync() -> None:
        shutdown_order.append("treasury_sync")
        await original_stop_sync()

    test_treasury.stop_sync = tracked_stop_sync

    # BotManager 중지 추적
    original_stop_all = bot_manager.stop_all

    async def tracked_stop_all() -> None:
        shutdown_order.append("bot_manager")
        await original_stop_all()

    bot_manager.stop_all = tracked_stop_all

    # 종료 실행 — main.py _shutdown 순서를 시뮬레이션
    # 1. Treasury sync 중지
    for treasury in treasury_manager.list_all():
        await treasury.stop_sync()

    # 2. BotManager 중지
    await bot_manager.stop_all()

    # 3. DB 종료
    shutdown_order.append("db")
    await db.close()

    # Treasury sync → BotManager → DB 순서 검증
    assert shutdown_order == ["treasury_sync", "bot_manager", "db"]


async def test_treasury_manager_multi_account(tmp_path: Path) -> None:
    """여러 계좌에 대해 TreasuryManager가 각각 Treasury를 생성한다."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    from ante.account import AccountService

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    # 두 개의 계좌 생성 (test 프리셋 사용)
    from ante.account import Account, TradingMode

    for aid, name in [("acc1", "계좌1"), ("acc2", "계좌2")]:
        account = Account(
            account_id=aid,
            name=name,
            broker_type="test",
            exchange="TEST",
            trading_mode=TradingMode.VIRTUAL,
            currency="KRW",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)

    from ante.treasury import TreasuryManager

    treasury_manager = TreasuryManager(db=db, eventbus=eventbus)
    accounts = await account_service.list()
    await treasury_manager.initialize_all(accounts)

    # 각 계좌별 Treasury 독립 확인
    t1 = treasury_manager.get("acc1")
    t2 = treasury_manager.get("acc2")
    assert t1 is not t2
    assert t1.account_id == "acc1"
    assert t2.account_id == "acc2"
    assert len(treasury_manager.list_all()) == 2

    await db.close()


async def test_rule_engine_manager_multi_account(tmp_path: Path) -> None:
    """여러 계좌에 대해 RuleEngineManager가 각각 RuleEngine을 생성한다."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    from ante.account import Account, AccountService, TradingMode

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    for aid, name in [("acc1", "계좌1"), ("acc2", "계좌2")]:
        account = Account(
            account_id=aid,
            name=name,
            broker_type="test",
            exchange="TEST",
            trading_mode=TradingMode.VIRTUAL,
            currency="KRW",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)

    from ante.rule import RuleEngineManager

    rule_engine_manager = RuleEngineManager(
        eventbus=eventbus,
        account_service=account_service,
    )
    accounts = await account_service.list()
    await rule_engine_manager.initialize_all(accounts)

    # 각 계좌별 RuleEngine 독립 확인
    e1 = rule_engine_manager.get("acc1")
    e2 = rule_engine_manager.get("acc2")
    assert e1 is not e2
    assert e1.account_id == "acc1"
    assert e2.account_id == "acc2"
    assert len(rule_engine_manager.engines) == 2

    await db.close()


async def test_init_treasury_sync_publishes_notification_on_failure(
    tmp_path: Path,
) -> None:
    """Treasury 동기화 실패 시 NotificationEvent(level=error)를 발행한다."""
    from ante.eventbus.events import NotificationEvent
    from ante.main import Services, _init_treasury_sync

    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    from ante.account import AccountService

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    await account_service.create_default_test_account()
    accounts = await account_service.list()

    # treasury_manager.get()가 실패하도록 빈 manager 준비
    class _FailingTreasuryManager:
        def get(self, account_id: str):
            raise RuntimeError("treasury not initialized")

    config = Config(static={}, secrets={})
    s = Services(
        db=db,
        eventbus=eventbus,
        config=config,
        account_service=account_service,
        treasury_manager=_FailingTreasuryManager(),
    )

    # 알림 수집
    captured: list[NotificationEvent] = []

    async def _collect(event: NotificationEvent) -> None:
        captured.append(event)

    eventbus.subscribe(NotificationEvent, _collect)

    await _init_treasury_sync(s, accounts)

    assert len(captured) == 1
    assert captured[0].level == "error"
    assert captured[0].category == "system"
    assert "Treasury" in captured[0].title
    assert accounts[0].account_id in captured[0].message

    await db.close()
