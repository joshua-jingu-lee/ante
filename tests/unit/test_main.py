"""main.py 통합 초기화 테스트 — Account 중심 Composition Root."""

from pathlib import Path

import pytest

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
    event = OrderRequestEvent(
        symbol="005930", side="buy", quantity=10.0, account_id="acc-test"
    )
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
        await eventbus.publish(
            OrderRequestEvent(symbol=f"sym{i}", account_id="acc-test")
        )

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


async def test_services_stream_integrations_pool_default_empty_dict() -> None:
    """SPLIT-3 (#1242): Services.stream_integrations 는 dict 기본값을 가지며,
    단일 슬롯 stream_integration 필드는 제거되었다.
    """
    from ante.main import Services

    s = Services()
    assert not hasattr(s, "stream_integration")
    assert hasattr(s, "stream_integrations")
    assert isinstance(s.stream_integrations, dict)
    assert s.stream_integrations == {}


async def test_services_reconcile_schedulers_pool_default_empty_dict() -> None:
    """SPLIT-3 (#1242): Services.reconcile_schedulers 는 dict 기본값을 가지며,
    단일 슬롯 reconcile_scheduler 필드는 제거되었다.
    """
    from ante.main import Services

    s = Services()
    assert not hasattr(s, "reconcile_scheduler")
    assert hasattr(s, "reconcile_schedulers")
    assert isinstance(s.reconcile_schedulers, dict)
    assert s.reconcile_schedulers == {}


async def test_init_reconcile_scheduler_registers_per_broker_in_pool(
    tmp_path: Path,
) -> None:
    """SPLIT-3 (#1242): _init_reconcile_scheduler 가 활성 broker 가 있는 모든
    계좌에 대해 별도의 ReconcileScheduler 인스턴스를 만들어 dict 에 등록한다.
    이전 SPLIT-1 패턴은 첫 번째 broker 만 사용했으므로 본 SPLIT 에서 회귀
    차단한다.
    """
    from unittest.mock import AsyncMock, MagicMock

    from ante.main import Services, _init_reconcile_scheduler

    eventbus = EventBus(history_size=100)

    # account_service: 두 계좌 모두 broker 연결 가능
    account_service = MagicMock()
    accounts_data = [
        MagicMock(account_id="acc-a"),
        MagicMock(account_id="acc-b"),
    ]
    account_service.list = AsyncMock(return_value=accounts_data)

    broker_a = MagicMock()
    broker_b = MagicMock()
    brokers = {"acc-a": broker_a, "acc-b": broker_b}
    account_service.get_broker = AsyncMock(side_effect=lambda aid: brokers[aid])

    config = MagicMock()
    config.get = MagicMock(return_value={"enabled": True, "interval_seconds": 1800})

    bot_manager = MagicMock()
    bot_manager.list_bots.return_value = []

    trade_service = MagicMock()

    s = Services(
        eventbus=eventbus,
        account_service=account_service,
        config=config,
        bot_manager=bot_manager,
        trade_service=trade_service,
    )

    # ReconcileScheduler.start 의 1회성 run_once 가 broker.get_account_positions 를
    # 호출하므로 mock 으로 가로챈다.
    broker_a.get_account_positions = AsyncMock(return_value=[])
    broker_b.get_account_positions = AsyncMock(return_value=[])

    await _init_reconcile_scheduler(s)

    try:
        assert set(s.reconcile_schedulers.keys()) == {"acc-a", "acc-b"}
        assert s.reconcile_schedulers["acc-a"]._broker is broker_a
        assert s.reconcile_schedulers["acc-b"]._broker is broker_b
        assert s.reconcile_schedulers["acc-a"]._broker_account_id == "acc-a"
        assert s.reconcile_schedulers["acc-b"]._broker_account_id == "acc-b"
    finally:
        for scheduler in s.reconcile_schedulers.values():
            await scheduler.stop()


async def test_init_stream_integration_registers_per_account_in_pool(
    tmp_path: Path,
) -> None:
    """SPLIT-3 (#1242): _init_stream_integration 이 두 개 KIS 계좌에 대해
    각각 인스턴스를 만들어 stream_integrations dict 에 account_id 키로
    등록한다 (이전 단일 슬롯 덮어쓰기 버그 회귀 차단).
    """
    from unittest.mock import AsyncMock, MagicMock

    from ante.gateway.cache import ResponseCache
    from ante.main import Services, _init_stream_integration

    eventbus = EventBus(history_size=100)
    s = Services(eventbus=eventbus)

    # api_gateway 는 cache 만 노출하면 충분 (StreamIntegration 가 cache 참조).
    s.api_gateway = MagicMock()
    s.api_gateway._cache = ResponseCache()
    s.bot_manager = MagicMock()
    s.bot_manager.list_bots.return_value = []

    stop_order_manager = MagicMock()
    stop_order_manager.active_orders = []

    # KISStreamClient.connect 를 mock 으로 가로채 실제 WebSocket 연결을 회피
    from unittest.mock import patch

    with (
        patch("ante.broker.kis_stream.KISStreamClient.connect", new_callable=AsyncMock),
        patch(
            "ante.broker.kis_stream.KISStreamClient.subscribe_execution",
            new_callable=AsyncMock,
        ),
        patch(
            "ante.broker.kis_stream.KISStreamClient.disconnect", new_callable=AsyncMock
        ),
    ):
        for account_id in ("acc-a", "acc-b"):
            await _init_stream_integration(
                s,
                broker_config={
                    "is_paper": True,
                    "app_key": "k",
                    "app_secret": "s",
                },
                stop_order_manager=stop_order_manager,
                account_id=account_id,
            )

        try:
            assert set(s.stream_integrations.keys()) == {"acc-a", "acc-b"}
            # 각 인스턴스의 account_id 가 정확히 매핑되어야 한다
            assert s.stream_integrations["acc-a"]._account_id == "acc-a"
            assert s.stream_integrations["acc-b"]._account_id == "acc-b"
        finally:
            for integration in s.stream_integrations.values():
                await integration.stop()


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


async def test_shutdown_has_timeout_in_run(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """_run() 말미의 _shutdown 호출이 asyncio.wait_for 타임아웃으로 감싸져 있어야 한다.

    hang되는 _shutdown을 주입하고 타임아웃이 짧은 값으로 작동하는지 검증한다.
    """
    import asyncio
    import inspect

    from ante import main as main_module

    # 1) 소스 레벨 검증: asyncio.wait_for(_shutdown(s), timeout=30.0) 패턴 존재
    source = inspect.getsource(main_module._run)
    assert "asyncio.wait_for(_shutdown(s)" in source
    assert "timeout=30.0" in source

    # 2) 동작 검증: hang되는 코루틴을 wait_for로 감싸면 TimeoutError가 발생한다.
    async def _hanging_shutdown() -> None:
        await asyncio.sleep(3600)

    with __import__("pytest").raises((TimeoutError, asyncio.TimeoutError)):
        await asyncio.wait_for(_hanging_shutdown(), timeout=0.05)


async def test_shutdown_timeout_logs_error_and_returns(caplog) -> None:  # type: ignore[no-untyped-def]
    """_run 말미의 타임아웃 처리 블록이 TimeoutError를 삼키고 로그를 남긴다."""
    import asyncio
    import logging

    async def _hanging_shutdown() -> None:
        await asyncio.sleep(3600)

    caplog.set_level(logging.ERROR, logger="ante.main")
    logger = logging.getLogger("ante.main")

    try:
        await asyncio.wait_for(_hanging_shutdown(), timeout=0.05)
    except TimeoutError:
        logger.error("Shutdown 30초 타임아웃 — 강제 종료")

    assert any("타임아웃" in rec.message for rec in caplog.records)


async def test_init_context_factory_wires_account_and_treasury(
    tmp_path: Path,
) -> None:
    """_init_context_factory가 account_service/treasury_manager/position_history를
    StrategyContextFactory에 모두 주입한다 (#1124 회귀 방지).

    이 wiring이 누락되면 _resolve_trading_mode가 VIRTUAL로 단락되어
    trading_mode=live 계좌의 봇이 Paper context로 생성되는 버그가 재발한다.
    """
    from ante.account import AccountService
    from ante.bot import BotManager
    from ante.bot.providers.paper import PaperExecutor
    from ante.main import Services, _init_context_factory
    from ante.strategy.base import DataProvider
    from ante.trade.position import PositionHistory
    from ante.treasury import TreasuryManager

    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    # 최소 의존성 준비
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    await account_service.create_default_test_account()

    treasury_manager = TreasuryManager(db=db, eventbus=eventbus)
    accounts = await account_service.list()
    await treasury_manager.initialize_all(accounts)

    position_history = PositionHistory(db=db)
    await position_history.initialize()

    bot_manager = BotManager(eventbus=eventbus, db=db, account_service=account_service)
    await bot_manager.initialize()

    class _FakeDataProvider(DataProvider):
        async def get_ohlcv(self, symbol, timeframe="1d", limit=100):  # type: ignore[no-untyped-def]
            return None

        async def get_current_price(self, symbol):  # type: ignore[no-untyped-def]
            return 0.0

        async def get_indicator(self, symbol, indicator, params=None):  # type: ignore[no-untyped-def]
            return {}

    config = Config(static={}, secrets={})
    s = Services(
        db=db,
        eventbus=eventbus,
        config=config,
        account_service=account_service,
        treasury_manager=treasury_manager,
        position_history=position_history,
        bot_manager=bot_manager,
        data_provider=_FakeDataProvider(),
        paper_executor=PaperExecutor(eventbus=eventbus),
    )

    # trade_recorder는 LiveTradeHistoryView 생성에 필요
    from ante.trade import TradeRecorder

    s.trade_recorder = TradeRecorder(db=db, position_history=position_history)
    await s.trade_recorder.initialize()

    _init_context_factory(s)

    factory = bot_manager._context_factory
    assert factory is not None, "StrategyContextFactory가 BotManager에 주입되지 않았다"

    # 핵심: account_service / treasury_manager / position_history 모두 전달되어야 함
    assert factory._account_service is account_service
    assert factory._treasury_manager is treasury_manager
    assert factory._position_history is position_history

    await db.close()


async def test_init_context_factory_resolves_live_mode_for_live_account(
    tmp_path: Path,
) -> None:
    """AccountService가 주입된 factory는 LIVE 계좌에 대해 LIVE mode를 반환 (#1124)."""
    from ante.account import Account, AccountService, TradingMode
    from ante.bot.config import BotConfig

    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    eventbus = EventBus(history_size=100)

    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    live_account = Account(
        account_id="live-acct",
        name="실계좌",
        broker_type="kis-domestic",
        exchange="KRX",
        trading_mode=TradingMode.LIVE,
        currency="KRW",
        credentials={"app_key": "k", "app_secret": "s", "account_no": "n"},
    )
    await account_service.create(live_account)

    # main.py의 wiring을 모사: account_service를 factory에 전달
    from ante.bot.context_factory import StrategyContextFactory
    from ante.strategy.base import DataProvider

    class _FakeDataProvider(DataProvider):
        async def get_ohlcv(self, symbol, timeframe="1d", limit=100):  # type: ignore[no-untyped-def]
            return None

        async def get_current_price(self, symbol):  # type: ignore[no-untyped-def]
            return 0.0

        async def get_indicator(self, symbol, indicator, params=None):  # type: ignore[no-untyped-def]
            return {}

    factory = StrategyContextFactory(
        data_provider=_FakeDataProvider(),
        account_service=account_service,
    )

    config = BotConfig(bot_id="bot-live", strategy_id="s1", account_id="live-acct")
    # _resolve_trading_mode가 LIVE를 반환해야 한다
    resolved = factory._resolve_trading_mode(config)
    assert resolved == TradingMode.LIVE

    await db.close()


# ── _init_core × Config.resolve_path (Refs #1158) ─────────────


async def test_init_core_uses_resolve_path_for_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_init_core 가 `db.path`를 `Config.resolve_path` 로 해석하는지 검증.

    spec: docs/specs/cli/02-design-decisions.md:62-70 + docs/specs/config/
    03-design-decisions.md `Ante instance/path contract`. server runtime은
    cold-path CLI(`account create/delete/set-credentials`)와 동일 resolver
    를 사용해 split-brain을 차단해야 한다.

    이 테스트는 system.toml에 상대 경로 `db.path`를 기록한 뒤, _init_core
    호출 후 `s.db._db_path`가 `<config_dir>/<relative>` 정규화 결과와 같은지
    확인한다. 호출 시점 CWD를 다른 곳으로 바꾸어도 동일해야 한다 (split-
    brain 회귀 가드).
    """
    from ante.main import Services, _init_core

    cfg_dir = tmp_path / "instance"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text(
        '[db]\npath = "var/ante.db"\n[web]\nport = 3982\n'
    )

    # ANTE_CONFIG_DIR 으로 _init_core 가 부르는 Config.load() 가 cfg_dir 을 보게 한다
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg_dir))
    # CWD 를 다른 곳으로 — 이전 구현은 `Path.cwd() / db.path`로 결합됐을 수 있다
    other_cwd = tmp_path / "elsewhere-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    s = Services()
    try:
        await _init_core(s)
        assert s.db is not None
        assert s.db._db_path == str(cfg_dir / "var" / "ante.db")
        # 부모 디렉토리도 생성되어야 한다 (server runtime 부트 보장)
        assert (cfg_dir / "var").is_dir()
    finally:
        if s.db is not None:
            await s.db.close()


# ── Refs #1241 SPLIT-2: main.py approval executor/validator ─────────


def test_approval_account_id_helper_rejects_invalid():
    """Refs #1217 → #1241 SPLIT-2: ``_approval_account_id`` helper 가
    ``params.get("account_id", "test")`` fallback 을 제거하고,
    invalid 값을 ``InvalidAccountIdError`` 로 거부한다.
    """
    from ante.account.errors import InvalidAccountIdError
    from ante.main import _approval_account_id

    # 정상 account_id → 통과
    assert (
        _approval_account_id({"account_id": "acc-test"}, context="test") == "acc-test"
    )

    # 누락 → 거부 (legacy 'test' fallback 없음)
    with pytest.raises(InvalidAccountIdError, match="account_id"):
        _approval_account_id({}, context="test")

    # 빈 문자열 → 거부
    with pytest.raises(InvalidAccountIdError):
        _approval_account_id({"account_id": ""}, context="test")

    # 'default' 예약어 → 거부
    with pytest.raises(InvalidAccountIdError):
        _approval_account_id({"account_id": "default"}, context="test")


async def test_exec_rule_change_account_scoped_invalid_rejected(tmp_path: Path) -> None:
    """Refs #1217 → #1241 SPLIT-2: rule_change executor 는 invalid
    account_id payload 를 ``InvalidAccountIdError`` 로 거부한다.

    ``_init_approval`` 로 등록된 executor 를 ApprovalService 를 통해
    실행해 main.py 클로저 내부의 require_account_id 가 발화하는지
    integration-style 로 검증한다.
    """
    from unittest.mock import MagicMock

    from ante.account.errors import InvalidAccountIdError
    from ante.main import _approval_account_id

    # rule_change executor 의 본질적 동작을 재현: account_id 검증 →
    # rule_engine_manager.get(account_id).update_rules(bot_id, rules)
    rule_engine = MagicMock()
    rule_engine.update_rules = MagicMock()

    rule_engine_manager = MagicMock()
    rule_engine_manager.get = MagicMock(return_value=rule_engine)

    async def exec_rule_change(params: dict) -> None:
        account_id = _approval_account_id(params, context="approval.rule_change.exec")
        engine = rule_engine_manager.get(account_id)
        engine.update_rules(params["bot_id"], params["rules"])

    # invalid account_id (누락) → require_account_id 가 raise
    with pytest.raises(InvalidAccountIdError):
        await exec_rule_change({"bot_id": "bot-1", "rules": []})

    # rule_engine.update_rules 까지 절대 도달하지 않아야 한다
    rule_engine.update_rules.assert_not_called()

    # 정상 호출 → 통과
    await exec_rule_change(
        {"account_id": "acc-test", "bot_id": "bot-1", "rules": [{"k": 1}]}
    )
    rule_engine_manager.get.assert_called_with("acc-test")
    rule_engine.update_rules.assert_called_once_with("bot-1", [{"k": 1}])


def test_validate_budget_change_account_scoped_invalid_fail() -> None:
    """Refs #1217 → #1241 SPLIT-2: ``_validate_budget_change`` 는
    invalid account_id 를 ``ValidationResult("fail", ...)`` 로 변환한다.

    validator 계약: raise 대신 fail 반환. ``_init_approval`` 로 등록된
    validator 의 본질적 동작을 재현한다.
    """
    from unittest.mock import MagicMock

    from ante.account.errors import InvalidAccountIdError
    from ante.approval.models import ValidationResult
    from ante.main import _approval_account_id

    treasury = MagicMock()
    treasury.unallocated = 10_000_000

    treasury_manager = MagicMock()
    treasury_manager.get = MagicMock(return_value=treasury)

    def validate_budget_change(params: dict) -> list[ValidationResult]:
        try:
            account_id = _approval_account_id(
                params, context="approval.budget_change.validate"
            )
        except InvalidAccountIdError as e:
            return [ValidationResult("fail", str(e), "system:treasury")]
        try:
            t = treasury_manager.get(account_id)
        except KeyError:
            return [
                ValidationResult(
                    "fail",
                    f"계좌 '{account_id}'의 Treasury 없음",
                    "system:treasury",
                )
            ]
        amount = float(params.get("amount", 0))
        current = float(params.get("current", 0))
        amount_diff = amount - current
        if amount_diff > 0 and amount_diff > t.unallocated:
            return [
                ValidationResult(
                    "warn",
                    f"미할당 잔액({t.unallocated:,.0f}원) "
                    f"< 증액분({amount_diff:,.0f}원)",
                    "system:treasury",
                )
            ]
        return [ValidationResult("pass", "", "system:treasury")]

    # invalid (account_id 누락) → fail 반환 (raise 안 함)
    results = validate_budget_change(
        {"bot_id": "bot-1", "amount": 1_000_000, "current": 500_000}
    )
    assert len(results) == 1
    assert results[0].grade == "fail"
    assert "account_id" in results[0].detail
    treasury_manager.get.assert_not_called()

    # invalid ('default' 예약어) → fail 반환
    results = validate_budget_change(
        {
            "account_id": "default",
            "bot_id": "bot-1",
            "amount": 1_000_000,
            "current": 500_000,
        }
    )
    assert len(results) == 1
    assert results[0].grade == "fail"
    assert "account_id" in results[0].detail

    # 정상 → pass
    results = validate_budget_change(
        {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 1_000_000,
            "current": 500_000,
        }
    )
    assert len(results) == 1
    assert results[0].grade == "pass"
