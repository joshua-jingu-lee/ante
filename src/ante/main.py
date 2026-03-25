"""Ante - AI-Native Trading Engine entrypoint.

Composition Root: 모든 모듈을 조립하고 시스템을 부팅한다.
각 _init_*() 함수가 독립적 초기화 단위를 담당하고,
main()은 조율만 수행한다.

초기화 순서 (Account 중심):
1. Core: Config, Database, EventBus
2. Services: AuditLogger, MemberService, InstrumentService
3. Account: AccountService, 테스트 계좌 자동 생성
4. Trading: StrategyRegistry, Trade, TreasuryManager, RuleEngineManager, BotManager
5. Gateway: APIGateway(account_service 주입)
6. Feed: DataPipeline, Backtest, Report
7. Approval: ApprovalService
8. Notification: Telegram(account_service 주입)
9. Web: FastAPI(account_service 주입)
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ante.config import Config, DynamicConfigService
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore

logger = logging.getLogger(__name__)

PID_FILE = Path("db/ante.pid")


def _write_pid_file() -> None:
    """PID 파일 기록."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    logger.info("PID 파일 기록: %s (pid=%d)", PID_FILE, os.getpid())


def _remove_pid_file() -> None:
    """PID 파일 삭제."""
    try:
        PID_FILE.unlink(missing_ok=True)
        logger.info("PID 파일 삭제: %s", PID_FILE)
    except OSError:
        logger.warning("PID 파일 삭제 실패: %s", PID_FILE, exc_info=True)


def read_pid_file() -> int | None:
    """PID 파일에서 PID 읽기. 파일이 없거나 파싱 실패 시 None."""
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


@dataclass
class Services:
    """초기화된 서비스 인스턴스를 전달하는 컨테이너.

    Account 중심 구조:
    - account_service: 계좌 CRUD 및 BrokerAdapter 관리
    - treasury_manager: 계좌별 Treasury 인스턴스 관리
    - rule_engine_manager: 계좌별 RuleEngine 인스턴스 관리
    """

    config: Any = None
    db: Database | None = None
    eventbus: EventBus | None = None
    event_history: EventHistoryStore | None = None
    dynamic_config: DynamicConfigService | None = None
    audit_logger: Any = None
    member_service: Any = None
    instrument_service: Any = None
    account_service: Any = None
    strategy_registry: Any = None
    treasury_manager: Any = None
    rule_engine_manager: Any = None
    trade_recorder: Any = None
    position_history: Any = None
    performance_tracker: Any = None
    trade_service: Any = None
    bot_manager: Any = None
    paper_executor: Any = None
    live_portfolio: Any = None
    live_order_view: Any = None
    strategy_snapshot: Any = None
    api_gateway: Any = None
    stream_integration: Any = None
    reconcile_scheduler: Any = None
    daily_report_scheduler: Any = None
    data_provider: Any = None
    parquet_store: Any = None
    data_collector: Any = None
    backtest_service: Any = None
    report_store: Any = None
    approval_service: Any = None
    notification_service: Any = None
    telegram_receiver: Any = None
    ipc_server: Any = None
    web_task: asyncio.Task | None = None  # type: ignore[type-arg]
    approval_expire_task: asyncio.Task | None = None  # type: ignore[type-arg]
    audit_cleanup_task: asyncio.Task | None = None  # type: ignore[type-arg]
    _cleanup_tasks: list[str] = field(default_factory=list)


async def _init_core(s: Services) -> None:
    """Config, Database, EventBus, DynamicConfig 초기화."""
    # Config
    s.config = Config.load()
    s.config.validate()

    log_level = s.config.get("system.log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Ante 시작")

    # Database
    db_path = s.config.get("db.path", "db/ante.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    s.db = Database(db_path)
    await s.db.connect()
    logger.info("Database 연결 완료: %s", db_path)

    # EventBus + EventHistoryStore
    history_size = s.config.get("eventbus.history_size", 1000)
    s.eventbus = EventBus(history_size=history_size)
    s.event_history = EventHistoryStore(db=s.db)
    await s.event_history.initialize()
    s.eventbus.use(s.event_history.record)
    logger.info("EventBus 초기화 완료 (history_size=%d)", history_size)

    # DynamicConfigService
    s.dynamic_config = DynamicConfigService(db=s.db, eventbus=s.eventbus)
    await s.dynamic_config.initialize()

    from ante.config.defaults import DEFAULTS
    from ante.config.dynamic import _on_log_level_changed
    from ante.eventbus.events import ConfigChangedEvent

    category_map = {
        "rule": "trading",
        "risk": "trading",
        "bot": "trading",
        "broker": "trading",
        "notification": "notification",
        "display": "display",
        "system": "system",
    }

    # system.log_level은 CLI 인자 우선이므로 DEFAULTS보다 먼저 등록
    await s.dynamic_config.register_default(
        "system.log_level", log_level, category="system"
    )
    await s.dynamic_config.register_default(
        "display.currency_position", "suffix", category="display"
    )

    for key, value in DEFAULTS.items():
        prefix = key.split(".")[0]
        category = category_map.get(prefix, "system")
        await s.dynamic_config.register_default(key, str(value), category=category)

    s.eventbus.subscribe(ConfigChangedEvent, _on_log_level_changed)
    logger.info("DynamicConfigService 초기화 완료")


async def _init_services(s: Services) -> None:
    """AuditLogger, MemberService, InstrumentService 초기화."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.audit import AuditLogger

    s.audit_logger = AuditLogger(db=s.db)
    await s.audit_logger.initialize()

    # 감사 로그 보존 기간 정리 태스크
    retention_days = s.config.get("audit.retention_days", 90)
    if retention_days > 0:
        s.audit_cleanup_task = asyncio.create_task(
            _audit_cleanup_loop(s.audit_logger, retention_days),
            name="audit-cleanup",
        )
        logger.info(
            "감사 로그 정리 스케줄러 시작 (보존: %d일, 주기: 24시간)", retention_days
        )
    else:
        logger.info("감사 로그 자동 정리 비활성화 (retention_days=0)")

    logger.info("AuditLogger 초기화 완료")

    from ante.member import MemberService

    s.member_service = MemberService(db=s.db, eventbus=s.eventbus)
    await s.member_service.initialize()
    logger.info("MemberService 초기화 완료")

    from ante.instrument import InstrumentService

    s.instrument_service = InstrumentService(db=s.db)
    await s.instrument_service.initialize()


async def _init_account(s: Services) -> None:
    """AccountService 초기화. 계좌 없으면 테스트 계좌 자동 생성."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.account import AccountService

    s.account_service = AccountService(db=s.db, eventbus=s.eventbus)
    await s.account_service.initialize()

    # 계좌가 하나도 없으면 테스트 계좌 자동 생성
    accounts = await s.account_service.list()
    if not accounts:
        await s.account_service.create_default_test_account()
        logger.info("테스트 계좌 자동 생성: account_id=test")

    logger.info("AccountService 초기화 완료")

    # 레거시 system.toml [broker].is_paper → Account.broker_config 마이그레이션
    await _migrate_is_paper_to_broker_config(s)


async def _migrate_is_paper_to_broker_config(s: Services) -> None:
    """system.toml [broker].is_paper를 Account.broker_config으로 1회성 이관한다.

    조건: system.toml에 broker.is_paper가 존재하고,
    KIS 계좌의 broker_config에 is_paper가 아직 없는 경우에만 이관한다.
    """
    legacy_is_paper = s.config.get("broker.is_paper")
    if legacy_is_paper is None:
        return

    accounts = await s.account_service.list()
    migrated: list[str] = []
    for account in accounts:
        if account.broker_type not in ("kis", "kis-domestic"):
            continue
        if "is_paper" in account.broker_config:
            continue
        new_broker_config = {**account.broker_config, "is_paper": legacy_is_paper}
        await s.account_service.update(
            account.account_id, broker_config=new_broker_config
        )
        migrated.append(account.account_id)

    if migrated:
        logger.info(
            "[마이그레이션] system.toml [broker].is_paper=%s → "
            "Account.broker_config으로 이관 완료: %s\n"
            "  system.toml의 [broker].is_paper 설정은 더 이상 사용되지 않습니다. "
            "제거해도 안전합니다.",
            legacy_is_paper,
            ", ".join(migrated),
        )


async def _init_trading(s: Services) -> None:
    """Strategy, Trade, TreasuryManager, RuleEngineManager, BotManager."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.strategy import StrategyRegistry

    s.strategy_registry = StrategyRegistry(db=s.db)
    await s.strategy_registry.initialize()
    logger.info("StrategyRegistry 초기화 완료")

    # Trade
    from ante.trade import (
        PerformanceTracker,
        PositionHistory,
        TradeRecorder,
        TradeService,
    )

    s.position_history = PositionHistory(db=s.db)
    await s.position_history.initialize()

    s.trade_recorder = TradeRecorder(db=s.db, position_history=s.position_history)
    await s.trade_recorder.initialize()
    s.trade_recorder.subscribe(s.eventbus)

    s.performance_tracker = PerformanceTracker(db=s.db)

    s.trade_service = TradeService(
        recorder=s.trade_recorder,
        position_history=s.position_history,
        performance=s.performance_tracker,
    )
    logger.info("Trade 모듈 초기화 완료")

    # TreasuryManager — 계좌별 Treasury 인스턴스 관리
    from ante.treasury import TreasuryManager

    s.treasury_manager = TreasuryManager(db=s.db, eventbus=s.eventbus)
    accounts = await s.account_service.list()
    await s.treasury_manager.initialize_all(accounts)
    logger.info("TreasuryManager 초기화 완료: %d개 계좌", len(accounts))

    # RuleEngineManager — 계좌별 RuleEngine 인스턴스 관리
    from ante.rule import RuleEngineManager

    s.rule_engine_manager = RuleEngineManager(
        eventbus=s.eventbus,
        account_service=s.account_service,
        treasury_manager=s.treasury_manager,
        trade_service=s.trade_service,
    )
    await s.rule_engine_manager.initialize_all(accounts, config=s.config)
    logger.info("RuleEngineManager 초기화 완료: %d개 계좌", len(accounts))

    # BotManager
    from ante.bot import BotManager  # noqa: F401
    from ante.bot.providers.paper import PaperExecutor
    from ante.strategy.snapshot import StrategySnapshot

    s.paper_executor = PaperExecutor(
        eventbus=s.eventbus,
        gateway=None,  # APIGateway 연결 후 설정
    )
    s.paper_executor.subscribe()

    from ante.bot.providers.live import LiveOrderView

    s.live_order_view = LiveOrderView(order_registry=None)  # type: ignore[arg-type]  # Broker 연결 후 설정

    strategies_dir = Path(s.config.get("strategy.dir", "strategies"))
    s.strategy_snapshot = StrategySnapshot(strategies_dir)

    s.bot_manager = BotManager(
        eventbus=s.eventbus,
        db=s.db,
        context_factory=None,  # APIGateway 연결 후 갱신
        snapshot=s.strategy_snapshot,
        account_service=s.account_service,
        treasury_manager=s.treasury_manager,
        trade_service=s.trade_service,
    )
    await s.bot_manager.initialize()

    # 각 계좌의 Treasury에 봇 상태 확인 콜백 연결
    for treasury in s.treasury_manager.list_all():

        def _get_bot_status(bot_id: str, _treasury: Any = treasury) -> str:
            bot = s.bot_manager.get_bot(bot_id)
            return bot.status if bot else ""

        treasury.set_bot_status_checker(_get_bot_status)

    logger.info("BotManager 초기화 완료")


async def _init_gateway(s: Services) -> None:
    """APIGateway(account_service 주입), StreamIntegration, 종목 동기화."""
    assert s.eventbus is not None

    from ante.gateway import APIGateway
    from ante.gateway.stop_order import StopOrderManager

    # StopOrderManager 초기화
    stop_order_manager = StopOrderManager(eventbus=s.eventbus)
    stop_order_manager.start()

    # APIGateway — AccountService 기반 계좌별 라우팅
    s.api_gateway = APIGateway(
        account_service=s.account_service,
        eventbus=s.eventbus,
        stop_order_manager=stop_order_manager,
    )
    s.api_gateway.start()
    logger.info("APIGateway 시작 완료")

    # 각 계좌의 Broker 연결 시도
    accounts = await s.account_service.list()
    connected_count = 0
    for account in accounts:
        try:
            broker = await s.account_service.get_broker(account.account_id)
            await broker.connect()
            connected_count += 1
            logger.info(
                "Broker 연결: account=%s, type=%s",
                account.account_id,
                account.broker_type,
            )
        except Exception:
            logger.warning(
                "Broker 연결 실패: account=%s — 건너뜀",
                account.account_id,
                exc_info=True,
            )
    if connected_count:
        logger.info("Broker 연결 완료: %d/%d개 계좌", connected_count, len(accounts))

    # KIS 브로커 계좌의 StreamIntegration 초기화
    for account in accounts:
        if account.broker_type == "kis":
            try:
                broker = await s.account_service.get_broker(account.account_id)
                broker_config = {**account.credentials, **account.broker_config}
                await _init_stream_integration(s, broker_config, stop_order_manager)
            except Exception:
                logger.warning(
                    "StreamIntegration 초기화 실패: account=%s",
                    account.account_id,
                    exc_info=True,
                )

    # 종목 마스터 동기화 (연결된 첫 번째 Broker 사용)
    if connected_count:
        await _sync_instruments(s, accounts)

    # StrategyContextFactory 완성 (Gateway 연결 이후)
    _init_context_factory(s)

    # Treasury 잔고 동기화 (Broker 연결 이후)
    await _init_treasury_sync(s, accounts)

    # ReconcileScheduler 초기화
    if connected_count and s.trade_service:
        await _init_reconcile_scheduler(s)

    # DailyReportScheduler 초기화
    if s.performance_tracker and s.trade_recorder and s.position_history:
        await _init_daily_report_scheduler(s)


async def _init_reconcile_scheduler(s: Services) -> None:
    """ReconcileScheduler 생성 및 시작."""
    assert s.eventbus is not None

    from ante.broker.scheduler import ReconcileScheduler
    from ante.trade.reconciler import PositionReconciler

    reconcile_config = s.config.get("reconcile", {})
    if not isinstance(reconcile_config, dict):
        reconcile_config = {}

    enabled = reconcile_config.get("enabled", True)
    if not enabled:
        logger.info("ReconcileScheduler 비활성화 (reconcile.enabled=false)")
        return

    interval = reconcile_config.get("interval_seconds", 1800)

    reconciler = PositionReconciler(
        trade_service=s.trade_service,
        eventbus=s.eventbus,
    )

    # 첫 번째 연결된 Broker를 ReconcileScheduler에 사용
    broker = None
    accounts = await s.account_service.list()
    for account in accounts:
        try:
            broker = await s.account_service.get_broker(account.account_id)
            break
        except Exception:
            continue

    if not broker:
        logger.info("ReconcileScheduler 건너뜀 — 연결된 Broker 없음")
        return

    s.reconcile_scheduler = ReconcileScheduler(
        reconciler=reconciler,
        broker=broker,
        bot_manager=s.bot_manager,
        eventbus=s.eventbus,
        interval_seconds=interval,
    )
    await s.reconcile_scheduler.start()
    logger.info("ReconcileScheduler 시작 완료 (주기: %d초)", interval)


async def _init_daily_report_scheduler(s: Services) -> None:
    """DailyReportScheduler 생성 및 시작 (Account 기반 실행 시각)."""
    from ante.trade.daily_report import (
        DailyReportScheduler,
        compute_report_time,
    )

    # 첫 번째 활성 계좌 기반으로 report_time, account_id, currency 결정
    accounts = await s.account_service.list() if s.account_service else []
    account = accounts[0] if accounts else None

    report_time = compute_report_time(account.trading_hours_end) if account else None
    account_id = account.account_id if account else ""
    currency = account.currency if account else "KRW"

    # Treasury 인스턴스 조회
    treasury = None
    if s.treasury_manager and account_id:
        try:
            treasury = s.treasury_manager.get(account_id)
        except KeyError:
            logger.warning("Treasury not found for account_id=%s", account_id)

    kwargs: dict = {
        "performance_tracker": s.performance_tracker,
        "trade_recorder": s.trade_recorder,
        "position_history": s.position_history,
        "eventbus": s.eventbus,
        "account_id": account_id,
        "currency": currency,
        "treasury": treasury,
    }
    if report_time is not None:
        kwargs["report_time"] = report_time

    s.daily_report_scheduler = DailyReportScheduler(**kwargs)
    await s.daily_report_scheduler.start()
    logger.info(
        "DailyReportScheduler 시작 완료 (account=%s, currency=%s)",
        account_id,
        currency,
    )


async def _init_stream_integration(
    s: Services,
    broker_config: dict,
    stop_order_manager: Any,
) -> None:
    """KISStreamClient + StreamIntegration 초기화."""
    assert s.eventbus is not None

    from ante.broker.kis_stream import KISStreamClient
    from ante.gateway.stream_integration import StreamIntegration

    is_paper = broker_config.get("is_paper", True)
    ws_url = (
        "ws://ops.koreainvestment.com:21000"
        if is_paper
        else "ws://ops.koreainvestment.com:31000"
    )

    stream_client = KISStreamClient(
        websocket_url=ws_url,
        app_key=broker_config.get("app_key", ""),
        app_secret=broker_config.get("app_secret", ""),
        eventbus=s.eventbus,
    )

    s.stream_integration = StreamIntegration(
        stream_client=stream_client,
        cache=s.api_gateway._cache,
        eventbus=s.eventbus,
        stop_order_manager=stop_order_manager,
        gateway=s.api_gateway,
        bot_manager=s.bot_manager,
    )

    try:
        await s.stream_integration.start()
        logger.info("StreamIntegration 시작 완료 (paper=%s)", is_paper)
    except Exception:
        logger.warning(
            "StreamIntegration 시작 실패 — REST 전용 모드로 운영", exc_info=True
        )
        s.stream_integration = None


async def _sync_instruments(s: Services, accounts: list) -> None:
    """종목 마스터 동기화 (연결된 첫 번째 Broker 사용)."""
    for account in accounts:
        try:
            broker = await s.account_service.get_broker(account.account_id)
            raw_instruments = await broker.get_instruments()
            if not raw_instruments:
                continue
            from ante.instrument.models import Instrument

            instruments_to_upsert = [
                Instrument(
                    symbol=item["symbol"],
                    exchange=account.exchange,
                    name=item.get("name", ""),
                    name_en=item.get("name_en", ""),
                    instrument_type=item.get("instrument_type", ""),
                    listed=item.get("listed", True),
                )
                for item in raw_instruments
            ]
            count = await s.instrument_service.bulk_upsert(instruments_to_upsert)
            logger.info(
                "종목 동기화 완료: account=%s, %d건 갱신",
                account.account_id,
                count,
            )
            return  # 첫 번째 성공한 Broker로 동기화
        except Exception:
            logger.warning(
                "종목 동기화 실패: account=%s — 다음 계좌 시도",
                account.account_id,
                exc_info=True,
            )
    logger.warning("종목 동기화 실패 — 기존 캐시 데이터로 운영")


def _init_context_factory(s: Services) -> None:
    """StrategyContextFactory 완성 (Gateway 연결 이후)."""
    from ante.bot import StrategyContextFactory
    from ante.bot.providers.live import LiveTradeHistoryView
    from ante.gateway.data_provider import LiveDataProvider

    if s.api_gateway:
        s.data_provider = LiveDataProvider(
            gateway=s.api_gateway,
            parquet_store=s.parquet_store,
        )
        s.paper_executor._gateway = s.api_gateway

    live_trade_history = LiveTradeHistoryView(trade_recorder=s.trade_recorder)

    if s.data_provider:
        context_factory = StrategyContextFactory(
            data_provider=s.data_provider,
            live_portfolio=s.live_portfolio,
            live_order_view=s.live_order_view,
            paper_executor=s.paper_executor,
            live_trade_history=live_trade_history,
        )
        s.bot_manager._context_factory = context_factory
        logger.info("StrategyContextFactory 설정 완료")


async def _init_treasury_sync(s: Services, accounts: list) -> None:
    """각 계좌의 Treasury 잔고 동기화 시작 (Broker 연결 이후)."""
    from ante.account.models import TradingMode

    sync_interval = s.config.get("treasury.sync_interval_seconds", 300)

    for account in accounts:
        try:
            treasury = s.treasury_manager.get(account.account_id)
            trading_mode = getattr(account, "trading_mode", TradingMode.VIRTUAL)
            is_virtual = trading_mode == TradingMode.VIRTUAL

            if is_virtual:
                # Virtual 모드: 브로커 없이 Trade DB 기반 동기화
                price_resolver = None
                if s.api_gateway:
                    gateway = s.api_gateway

                    async def _resolve_price(symbol: str) -> float:
                        return await gateway.get_current_price(symbol)

                    price_resolver = _resolve_price

                treasury.start_sync(
                    broker=None,
                    position_history=s.position_history,
                    interval_seconds=sync_interval,
                    trading_mode="virtual",
                    price_resolver=price_resolver,
                )
                logger.info(
                    "Treasury Virtual 동기화 시작: account=%s (주기: %d초)",
                    account.account_id,
                    sync_interval,
                )
            else:
                # Live 모드: 브로커 기반 동기화
                broker = await s.account_service.get_broker(account.account_id)

                account_no = getattr(broker, "account_no", "")
                is_paper = getattr(broker, "is_paper", False)
                formatted_account = (
                    f"{account_no[:8]}-{account_no[8:]}"
                    if len(account_no) >= 10
                    else account_no
                )
                treasury.set_account_info(
                    account_number=formatted_account,
                    is_demo_trading=is_paper,
                )

                treasury.start_sync(
                    broker=broker,
                    position_history=s.position_history,
                    interval_seconds=sync_interval,
                    trading_mode="live",
                )
                logger.info(
                    "Treasury Live 동기화 시작: account=%s (주기: %d초)",
                    account.account_id,
                    sync_interval,
                )
        except Exception:
            logger.warning(
                "Treasury 동기화 시작 실패: account=%s — 건너뜀",
                account.account_id,
                exc_info=True,
            )


async def _init_feed(s: Services) -> None:
    """Data Pipeline, BacktestService, ReportStore 초기화."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.data import DataCollector, ParquetStore

    data_path = s.config.get("data.path", "data/")
    Path(data_path).mkdir(parents=True, exist_ok=True)
    s.parquet_store = ParquetStore(base_path=Path(data_path))

    if s.api_gateway:
        s.data_collector = DataCollector(store=s.parquet_store, eventbus=s.eventbus)
    logger.info("Data Pipeline 초기화 완료: %s", data_path)

    # BacktestService (EventBus 주입)
    from ante.backtest import BacktestService

    s.backtest_service = BacktestService(data_path=data_path, eventbus=s.eventbus)
    logger.info("BacktestService 초기화 완료")

    # BacktestRunStore
    from ante.backtest.run_store import BacktestRunStore

    backtest_run_store = BacktestRunStore(db=s.db)
    await backtest_run_store.initialize()
    logger.info("BacktestRunStore 초기화 완료")

    # ReportStore
    from ante.report import ReportStore

    s.report_store = ReportStore(db=s.db)
    await s.report_store.initialize()
    logger.info("ReportStore 초기화 완료")

    # ReportDraftGenerator — BacktestCompleteEvent 구독
    from ante.report import ReportDraftGenerator

    draft_generator = ReportDraftGenerator(
        report_store=s.report_store,
        eventbus=s.eventbus,
    )
    draft_generator.initialize()
    logger.info("ReportDraftGenerator 초기화 완료")


async def _init_approval(s: Services) -> None:
    """ApprovalService 초기화: Executor, Validator, 전결 설정, 만료 스케줄러."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.approval import ApprovalService
    from ante.approval.auto_approve import AutoApproveConfig, AutoApproveEvaluator
    from ante.approval.models import ValidationResult
    from ante.report.models import ReportStatus

    async def _exec_rule_change(params: dict) -> None:
        account_id = params.get("account_id", "test")
        engine = s.rule_engine_manager.get(account_id)
        engine.update_rules(params["bot_id"], params["rules"])

    approval_executors: dict = {
        # 전략 관련
        "strategy_adopt": lambda params: s.report_store.update_status(
            params["report_id"], ReportStatus.ADOPTED
        ),
        "strategy_retire": lambda params: s.report_store.update_status(
            params["report_id"], ReportStatus.ARCHIVED
        ),
        # 봇 생명주기
        "bot_create": lambda params: s.bot_manager.create_bot(**params),
        "bot_assign_strategy": lambda params: s.bot_manager.assign_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_change_strategy": lambda params: s.bot_manager.change_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_stop": lambda params: s.bot_manager.stop_bot(params["bot_id"]),
        "bot_resume": lambda params: s.bot_manager.resume_bot(params["bot_id"]),
        "bot_delete": lambda params: s.bot_manager.delete_bot(params["bot_id"]),
        # 자금·규칙
        "budget_change": lambda params: s.treasury_manager.get(
            params.get("account_id", "test")
        ).update_budget(params["bot_id"], params["amount"]),
        "rule_change": _exec_rule_change,
    }

    # 사전 검증 validator 정의
    from ante.bot.config import BotStatus

    def _validate_strategy_retire(params: dict) -> list[ValidationResult]:
        """전략 폐기 사전 검증: 사용 중인 봇 존재 여부."""
        strategy_id = params.get("strategy_id", "")
        bots = [
            b for b in s.bot_manager.list_bots() if b.get("strategy_id") == strategy_id
        ]
        if bots:
            return [
                ValidationResult(
                    "fail",
                    f"전략을 사용 중인 봇 {len(bots)}개 존재",
                    "system:bot_manager",
                )
            ]
        return [ValidationResult("pass", "", "system:bot_manager")]

    def _validate_bot_create(params: dict) -> list[ValidationResult]:
        """봇 생성 사전 검증: 전략 adopted 상태, 동일 봇 미존재."""
        results: list[ValidationResult] = []
        bot_id = params.get("bot_id", "")
        if bot_id and s.bot_manager.get_bot(bot_id):
            results.append(
                ValidationResult(
                    "fail",
                    f"동일 ID의 봇이 이미 존재: {bot_id}",
                    "system:bot_manager",
                )
            )
        strategy_id = params.get("strategy_id", "")
        if strategy_id:
            # strategy_id로 리포트 확인은 비동기 — 동기 호출 불가이므로
            # 이 검증은 executor 2단계 검증에 위임
            pass
        return results or [ValidationResult("pass", "", "system:bot_manager")]

    def _validate_bot_delete(params: dict) -> list[ValidationResult]:
        """봇 삭제 사전 검증: stopped 상태, 보유 포지션 없음."""
        results: list[ValidationResult] = []
        bot_id = params.get("bot_id", "")
        bot = s.bot_manager.get_bot(bot_id)
        if not bot:
            return [
                ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")
            ]
        if bot.status != BotStatus.STOPPED:
            results.append(
                ValidationResult(
                    "fail",
                    f"봇이 {bot.status} 상태 (stopped 필요)",
                    "system:bot_manager",
                )
            )
        positions = s.position_history.get_positions_sync(bot_id)
        if positions:
            results.append(
                ValidationResult(
                    "fail",
                    f"보유 포지션 {len(positions)}건 존재",
                    "system:trade",
                )
            )
        return results or [ValidationResult("pass", "", "system:bot_manager")]

    def _validate_bot_change_strategy(params: dict) -> list[ValidationResult]:
        """봇 전략 변경 사전 검증: stopped 상태 확인."""
        bot_id = params.get("bot_id", "")
        bot = s.bot_manager.get_bot(bot_id)
        if not bot:
            return [
                ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")
            ]
        if bot.status != BotStatus.STOPPED:
            return [
                ValidationResult(
                    "fail",
                    f"봇이 {bot.status} 상태 (stopped 필요)",
                    "system:bot_manager",
                )
            ]
        return [ValidationResult("pass", "", "system:bot_manager")]

    def _validate_bot_assign_strategy(params: dict) -> list[ValidationResult]:
        """봇 전략 배정 사전 검증: 전략 adopted 상태 확인."""
        # 전략 상태 확인은 비동기 조회가 필요하므로 executor 2단계에 위임
        return [ValidationResult("pass", "", "system:report_store")]

    def _validate_bot_resume(params: dict) -> list[ValidationResult]:
        """봇 재개 사전 검증: stopped/error 상태 확인."""
        bot_id = params.get("bot_id", "")
        bot = s.bot_manager.get_bot(bot_id)
        if not bot:
            return [
                ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")
            ]
        if bot.status not in (BotStatus.STOPPED, BotStatus.ERROR):
            return [
                ValidationResult(
                    "fail",
                    f"봇이 {bot.status} 상태 (stopped/error 필요)",
                    "system:bot_manager",
                )
            ]
        return [ValidationResult("pass", "", "system:bot_manager")]

    def _validate_budget_change(params: dict) -> list[ValidationResult]:
        """예산 변경 사전 검증: 미할당 잔액 충분 여부 (warn)."""
        account_id = params.get("account_id", "test")
        try:
            treasury = s.treasury_manager.get(account_id)
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
        if amount_diff > 0 and amount_diff > treasury.unallocated:
            return [
                ValidationResult(
                    "warn",
                    f"미할당 잔액({treasury.unallocated:,.0f}원) "
                    f"< 증액분({amount_diff:,.0f}원)",
                    "system:treasury",
                )
            ]
        return [ValidationResult("pass", "", "system:treasury")]

    approval_validators: dict = {
        "strategy_retire": _validate_strategy_retire,
        "bot_create": _validate_bot_create,
        "bot_delete": _validate_bot_delete,
        "bot_change_strategy": _validate_bot_change_strategy,
        "bot_assign_strategy": _validate_bot_assign_strategy,
        "bot_resume": _validate_bot_resume,
        "budget_change": _validate_budget_change,
    }

    # 전결 설정 로딩
    auto_approve_raw = s.config.get("approval.auto_approve", {})
    auto_approve_config = AutoApproveConfig.from_dict(
        auto_approve_raw if isinstance(auto_approve_raw, dict) else {}
    )
    auto_approve_evaluator = AutoApproveEvaluator(config=auto_approve_config)
    if auto_approve_config.enabled:
        logger.info("전결 기능 활성화")

    s.approval_service = ApprovalService(
        db=s.db,
        eventbus=s.eventbus,
        executors=approval_executors,
        validators=approval_validators,
        auto_approve_evaluator=auto_approve_evaluator,
    )
    await s.approval_service.initialize()
    logger.info("ApprovalService 초기화 완료")

    # 결재 만료 스케줄러 등록
    s.approval_expire_task = asyncio.create_task(
        _approval_expire_loop(s.approval_service),
        name="approval-expire",
    )
    logger.info("결재 만료 스케줄러 시작 (주기: 300초)")


async def _audit_cleanup_loop(
    audit_logger: Any,
    retention_days: int,
    interval: float = 86400.0,
) -> None:
    """보존 기간 초과 감사 로그를 주기적으로 삭제."""
    while True:
        await asyncio.sleep(interval)
        try:
            deleted = await audit_logger.cleanup(retention_days)
            if deleted:
                logger.info("감사 로그 정리 완료: %d건 삭제", deleted)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("감사 로그 정리 스케줄러 오류")


async def _approval_expire_loop(
    approval_service: Any,
    interval: float = 300.0,
) -> None:
    """만료 기한이 지난 결재 요청을 주기적으로 expired 처리."""
    while True:
        await asyncio.sleep(interval)
        try:
            expired = await approval_service.expire_stale()
            if expired:
                logger.info("결재 만료 처리: %d건", expired)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("결재 만료 스케줄러 오류")


async def _init_notification(s: Services) -> None:
    """NotificationService, TelegramCommandReceiver 초기화."""
    assert s.eventbus is not None
    assert s.dynamic_config is not None

    from ante.notification import (
        NotificationLevel,
        NotificationService,
        TelegramAdapter,
    )

    telegram_token = s.config.secret("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = s.config.secret("TELEGRAM_CHAT_ID")

    if not (telegram_token and telegram_chat_id):
        logger.info("NotificationService 건너뜀 — Telegram 설정 없음")
        return

    adapter = TelegramAdapter(bot_token=telegram_token, chat_id=telegram_chat_id)
    min_level_str = s.config.get("notification.min_level", "info")

    # quiet_hours 파싱
    quiet_start = None
    quiet_end = None
    if s.dynamic_config:
        from ante.notification.service import parse_quiet_hours

        raw = await s.dynamic_config.get("notification.quiet_hours", default=None)
        if raw:
            parsed = parse_quiet_hours(str(raw))
            if parsed:
                quiet_start, quiet_end = parsed

    telegram_enabled = await s.dynamic_config.get(
        "notification.telegram_enabled", default="true"
    )
    telegram_enabled_bool = str(telegram_enabled) == "true"

    s.notification_service = NotificationService(
        adapter=adapter,
        eventbus=s.eventbus,
        min_level=NotificationLevel(min_level_str),
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        telegram_enabled=telegram_enabled_bool,
    )
    s.notification_service.subscribe()
    logger.info("NotificationService 초기화 완료 (Telegram)")

    # TelegramCommandReceiver
    from ante.notification import TelegramCommandReceiver

    chat_id_str = os.environ.get("TELEGRAM_CHAT_ID", "")
    chat_id: int | None = None
    if chat_id_str:
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            logger.warning(
                "TELEGRAM_CHAT_ID 값이 올바른 정수가 아닙니다: %r — 무시합니다",
                chat_id_str,
            )
    if telegram_enabled_bool and chat_id is not None:
        s.telegram_receiver = TelegramCommandReceiver(
            adapter=adapter,
            allowed_user_ids=[chat_id],
            polling_interval=3.0,
            confirm_timeout=30.0,
            bot_manager=s.bot_manager,
            account_service=s.account_service,
            approval_service=s.approval_service,
        )
        s.telegram_receiver.start()
        logger.info("TelegramCommandReceiver 시작 (chat_id=%s)", chat_id)
    elif not telegram_enabled_bool:
        logger.info("TelegramCommandReceiver 건너뜀 — telegram_enabled=false")
    else:
        logger.info("TelegramCommandReceiver 건너뜀 — TELEGRAM_CHAT_ID 미설정")


async def _init_ipc(s: Services) -> None:
    """IPC 서버 초기화 — Unix 도메인 소켓 기반 프로세스 간 통신."""
    assert s.eventbus is not None

    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry, register_all_handlers
    from ante.ipc.server import IPCServer
    from ante.trade.reconciler import PositionReconciler

    # PositionReconciler 인스턴스 생성
    reconciler = PositionReconciler(
        trade_service=s.trade_service,
        eventbus=s.eventbus,
    )

    service_registry = ServiceRegistry(
        account=s.account_service,
        bot_manager=s.bot_manager,
        treasury_manager=s.treasury_manager,
        dynamic_config=s.dynamic_config,
        approval=s.approval_service,
        reconciler=reconciler,
        eventbus=s.eventbus,
    )

    command_registry = CommandRegistry()
    register_all_handlers(command_registry)

    db_path = s.config.get("db.path", "db/ante.db")
    socket_path = str(Path(db_path).parent / "ante.sock")
    s.ipc_server = IPCServer(socket_path, service_registry, command_registry)
    await s.ipc_server.start()
    logger.info("IPC 서버 초기화 완료: %s", socket_path)


async def _init_web(s: Services) -> None:
    """FastAPI 앱 생성 및 uvicorn 서버 시작."""
    assert s.db is not None
    assert s.eventbus is not None

    web_enabled = s.config.get("web.enabled", False)
    if not web_enabled:
        return

    from ante.web.app import create_app
    from ante.web.session import SessionService

    session_service = SessionService(db=s.db)
    await session_service.initialize()

    app = create_app(
        config=s.config,
        db=s.db,
        eventbus=s.eventbus,
        bot_manager=s.bot_manager,
        trade_service=s.trade_service,
        treasury_manager=s.treasury_manager,
        report_store=s.report_store,
        data_store=s.parquet_store,
        audit_logger=s.audit_logger,
        member_service=s.member_service,
        session_service=session_service,
        strategy_registry=s.strategy_registry,
        dynamic_config=s.dynamic_config,
        approval_service=s.approval_service,
        account_service=s.account_service,
    )

    import uvicorn

    uv_config = uvicorn.Config(
        app,
        host=s.config.get("web.host", "0.0.0.0"),
        port=s.config.get("web.port", 3982),
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    s.web_task = asyncio.create_task(server.serve(), name="web-api")
    logger.info(
        "Web API 시작: http://%s:%d",
        uv_config.host,
        uv_config.port,
    )


async def _run(s: Services) -> None:
    """시그널 대기 및 Graceful Shutdown."""
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("종료 시그널 수신")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Ante 준비 완료 — 종료 시그널 대기 중")

    from ante.eventbus.events import NotificationEvent, SystemStartedEvent

    if s.eventbus:
        await s.eventbus.publish(
            NotificationEvent(
                level="info",
                title="시스템 시작",
                message="Ante 시스템이 시작되었습니다.",
                category="system",
            )
        )
        await s.eventbus.publish(SystemStartedEvent())

    await shutdown_event.wait()

    await _shutdown(s)


async def _shutdown(s: Services) -> None:
    """종료 정리 (역순).

    종료 순서:
    1. Telegram, 스케줄러 태스크 취소
    2. Web API 종료
    3. DailyReportScheduler, ReconcileScheduler 종료
    4. 각 계좌의 Treasury sync 중지
    5. BotManager 전체 봇 중지
    6. StreamIntegration 종료
    7. APIGateway 종료
    8. 각 계좌의 BrokerAdapter disconnect
    9. Database 종료
    """
    logger.info("Ante 종료 시작")

    from ante.eventbus.events import NotificationEvent

    if s.eventbus:
        await s.eventbus.publish(
            NotificationEvent(
                level="info",
                title="시스템 종료",
                message="Ante 시스템이 종료됩니다.",
                category="system",
            )
        )

    if s.telegram_receiver:
        await s.telegram_receiver.stop()
        logger.info("TelegramCommandReceiver 종료")

    if s.audit_cleanup_task and not s.audit_cleanup_task.done():
        s.audit_cleanup_task.cancel()
        try:
            await s.audit_cleanup_task
        except asyncio.CancelledError:
            pass
        logger.info("감사 로그 정리 스케줄러 종료")

    if s.approval_expire_task and not s.approval_expire_task.done():
        s.approval_expire_task.cancel()
        try:
            await s.approval_expire_task
        except asyncio.CancelledError:
            pass
        logger.info("결재 만료 스케줄러 종료")

    if s.web_task and not s.web_task.done():
        s.web_task.cancel()
        try:
            await s.web_task
        except asyncio.CancelledError:
            pass
        logger.info("Web API 종료")

    if s.ipc_server:
        await s.ipc_server.stop()
        logger.info("IPCServer 종료")

    if s.daily_report_scheduler:
        await s.daily_report_scheduler.stop()
        logger.info("DailyReportScheduler 종료")

    if s.reconcile_scheduler:
        await s.reconcile_scheduler.stop()
        logger.info("ReconcileScheduler 종료")

    # 각 계좌의 Treasury sync 중지
    if s.treasury_manager:
        for treasury in s.treasury_manager.list_all():
            try:
                await treasury.stop_sync()
            except Exception:
                logger.warning(
                    "Treasury sync 중지 실패: account=%s",
                    treasury.account_id,
                    exc_info=True,
                )
        logger.info("Treasury 잔고 동기화 종료")

    if s.bot_manager:
        await s.bot_manager.stop_all()
        logger.info("BotManager 종료 — 모든 봇 중지")

    if s.stream_integration:
        await s.stream_integration.stop()
        logger.info("StreamIntegration 종료")

    if s.api_gateway:
        s.api_gateway.stop()
        logger.info("APIGateway 종료")

    # 각 계좌의 BrokerAdapter disconnect
    if s.account_service:
        accounts = await s.account_service.list()
        for account in accounts:
            try:
                broker = await s.account_service.get_broker(account.account_id)
                await broker.disconnect()
                logger.info("Broker 연결 해제: account=%s", account.account_id)
            except Exception:
                logger.warning(
                    "Broker 연결 해제 실패: account=%s",
                    account.account_id,
                    exc_info=True,
                )

    if s.db:
        await s.db.close()
    logger.info("Ante 종료 완료")


async def main() -> None:
    """Main asyncio entrypoint.

    초기화 순서 (Account 중심):
    1. Core: Config, Database, EventBus, DynamicConfig
    2. Services: AuditLogger, MemberService, InstrumentService
    3. Account: AccountService, 테스트 계좌 자동 생성
    4. Trading: StrategyRegistry, Trade, TreasuryManager, RuleEngineManager, BotManager
    5. Gateway: APIGateway(account_service 주입)
    6. Feed: DataPipeline, Backtest, Report
    7. Approval: ApprovalService
    8. Notification: Telegram(account_service 주입)
    9. IPC: Unix 도메인 소켓 서버
    10. Web: FastAPI(account_service 주입)

    종료 순서: 역순 (상위 소비자부터 정리)
    """
    s = Services()
    _write_pid_file()

    try:
        await _init_core(s)

        # 서버 시작 시 최신 버전 확인 (non-blocking, fire-and-forget)
        from ante.update.checker import check_update_on_startup

        asyncio.create_task(check_update_on_startup())

        from ante.db.migrations import run_migrations

        assert s.db is not None
        data_path = Path(s.config.get("data.path", "data/"))
        applied = await run_migrations(s.db, data_path=data_path)
        if applied:
            logger.info("DB 마이그레이션 적용: %s", ", ".join(applied))

        await _init_services(s)
        await _init_account(s)
        await _init_trading(s)
        await _init_gateway(s)
        await _init_feed(s)
        await _init_approval(s)
        await _init_notification(s)
        await _init_ipc(s)
        await _init_web(s)
        await _run(s)
    finally:
        _remove_pid_file()


if __name__ == "__main__":
    asyncio.run(main())
