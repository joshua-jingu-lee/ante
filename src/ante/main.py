"""Ante - AI-Native Trading Engine entrypoint.

Composition Root: 모든 모듈을 조립하고 시스템을 부팅한다.
각 _init_*() 함수가 독립적 초기화 단위를 담당하고,
main()은 조율만 수행한다.
"""

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ante.config import Config, DynamicConfigService, SystemState
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore

logger = logging.getLogger(__name__)


@dataclass
class Services:
    """초기화된 서비스 인스턴스를 전달하는 컨테이너."""

    config: Any = None
    db: Database | None = None
    eventbus: EventBus | None = None
    event_history: EventHistoryStore | None = None
    system_state: SystemState | None = None
    dynamic_config: DynamicConfigService | None = None
    audit_logger: Any = None
    member_service: Any = None
    instrument_service: Any = None
    strategy_registry: Any = None
    rule_engine: Any = None
    treasury: Any = None
    trade_recorder: Any = None
    position_history: Any = None
    performance_tracker: Any = None
    trade_service: Any = None
    bot_manager: Any = None
    paper_executor: Any = None
    live_portfolio: Any = None
    live_order_view: Any = None
    strategy_snapshot: Any = None
    broker: Any = None
    api_gateway: Any = None
    data_provider: Any = None
    parquet_store: Any = None
    data_collector: Any = None
    backtest_service: Any = None
    report_store: Any = None
    approval_service: Any = None
    notification_service: Any = None
    telegram_receiver: Any = None
    web_task: asyncio.Task | None = None  # type: ignore[type-arg]
    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0023
    _cleanup_tasks: list[str] = field(default_factory=list)


async def _init_core(s: Services) -> None:
    """Config, Database, EventBus, SystemState, DynamicConfig 초기화."""
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

    # SystemState (킬 스위치)
    s.system_state = SystemState(db=s.db, eventbus=s.eventbus)
    await s.system_state.initialize()
    logger.info("SystemState 초기화 완료: %s", s.system_state.trading_state)

    # DynamicConfigService
    s.dynamic_config = DynamicConfigService(db=s.db, eventbus=s.eventbus)
    await s.dynamic_config.initialize()

    from ante.config.dynamic import _on_log_level_changed
    from ante.eventbus.events import ConfigChangedEvent

    await s.dynamic_config.register_default(
        "system.log_level", log_level, category="system"
    )
    await s.dynamic_config.register_default(
        "display.currency_position", "suffix", category="display"
    )
    s.eventbus.subscribe(ConfigChangedEvent, _on_log_level_changed)
    logger.info("DynamicConfigService 초기화 완료")


async def _init_services(s: Services) -> None:
    """AuditLogger, MemberService, InstrumentService 초기화."""
    from ante.audit import AuditLogger

    s.audit_logger = AuditLogger(db=s.db)
    await s.audit_logger.initialize()
    logger.info("AuditLogger 초기화 완료")

    from ante.member import MemberService

    s.member_service = MemberService(db=s.db, eventbus=s.eventbus)
    await s.member_service.initialize()
    logger.info("MemberService 초기화 완료")

    from ante.instrument import InstrumentService

    s.instrument_service = InstrumentService(db=s.db)
    await s.instrument_service.initialize()


async def _init_trading(s: Services) -> None:
    """StrategyRegistry, RuleEngine, Treasury, Trade, BotManager 초기화."""
    from ante.strategy import StrategyRegistry

    s.strategy_registry = StrategyRegistry(db=s.db)
    await s.strategy_registry.initialize()
    logger.info("StrategyRegistry 초기화 완료")

    # RuleEngine
    from ante.rule import RuleEngine

    s.rule_engine = RuleEngine(eventbus=s.eventbus, system_state=s.system_state)
    await s.rule_engine.start()

    rule_configs = s.config.get("rules.global", [])
    if rule_configs:
        s.rule_engine.load_rules_from_config(rule_configs)
    logger.info("RuleEngine 초기화 완료")

    # Treasury
    from ante.treasury import Treasury

    s.commission_rate = s.config.get("broker.commission_rate", 0.00015)
    s.sell_tax_rate = s.config.get("broker.sell_tax_rate", 0.0023)
    s.treasury = Treasury(
        db=s.db,
        eventbus=s.eventbus,
        commission_rate=s.commission_rate,
        sell_tax_rate=s.sell_tax_rate,
    )
    await s.treasury.initialize()
    logger.info("Treasury 초기화 완료")

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

    # BotManager + StrategyContextFactory
    from ante.bot import BotManager, StrategyContextFactory  # noqa: F401
    from ante.bot.providers.live import LiveOrderView, LivePortfolioView
    from ante.bot.providers.paper import PaperExecutor
    from ante.strategy.snapshot import StrategySnapshot

    s.paper_executor = PaperExecutor(
        eventbus=s.eventbus,
        gateway=None,  # APIGateway 연결 후 설정
        commission_rate=s.commission_rate,
        sell_tax_rate=s.sell_tax_rate,
    )
    s.paper_executor.subscribe()

    s.live_portfolio = LivePortfolioView(
        treasury=s.treasury,
        position_history=s.position_history,
    )
    s.live_order_view = LiveOrderView(order_registry=None)  # Broker 연결 후 설정

    strategies_dir = Path(s.config.get("strategy.dir", "strategies"))
    s.strategy_snapshot = StrategySnapshot(strategies_dir)

    s.bot_manager = BotManager(
        eventbus=s.eventbus,
        db=s.db,
        context_factory=None,  # APIGateway 연결 후 갱신
        snapshot=s.strategy_snapshot,
    )
    await s.bot_manager.initialize()

    # Treasury에 봇 상태 확인 콜백 연결
    def _get_bot_status(bot_id: str) -> str:
        bot = s.bot_manager.get_bot(bot_id)
        return bot.status if bot else ""

    s.treasury.set_bot_status_checker(_get_bot_status)
    logger.info("BotManager 초기화 완료")

    # Broker + APIGateway
    await _init_broker(s)

    # StrategyContextFactory 완성 (Broker 연결 이후)
    await _init_context_factory(s)

    # Treasury 잔고 동기화 (Broker 연결 이후)
    await _init_treasury_sync(s)


async def _init_broker(s: Services) -> None:
    """Broker, APIGateway 연결 및 종목 마스터 동기화."""
    from ante.gateway import APIGateway

    broker_config = s.config.get("broker", {})
    broker_type = (
        broker_config.get("type", "kis") if isinstance(broker_config, dict) else "kis"
    )

    if broker_type == "mock":
        await _connect_mock_broker(s, broker_config)
    else:
        await _connect_kis_broker(s, broker_config)

    if s.broker:
        s.api_gateway = APIGateway(broker=s.broker, eventbus=s.eventbus)
        await s.api_gateway.start()
        logger.info("APIGateway 시작 완료")

    if s.broker:
        await _sync_instruments(s)


async def _connect_mock_broker(s: Services, broker_config: dict) -> None:
    """MockBrokerAdapter 연결."""
    from ante.broker.mock import MockBrokerAdapter

    s.broker = MockBrokerAdapter(
        broker_config if isinstance(broker_config, dict) else {}
    )
    await s.broker.connect()
    logger.info("MockBrokerAdapter 연결 완료")


async def _connect_kis_broker(s: Services, broker_config: dict) -> None:
    """KISAdapter 연결 (비밀값 없으면 건너뜀)."""
    from ante.broker import KISAdapter

    try:
        broker_config["app_key"] = s.config.secret("KIS_APP_KEY")
        broker_config["app_secret"] = s.config.secret("KIS_APP_SECRET")
        broker_config["account_no"] = s.config.secret("KIS_ACCOUNT_NO")
    except Exception:
        return  # 비밀값 없으면 브로커 미사용

    if not broker_config.get("app_key"):
        return

    s.broker = KISAdapter(config=broker_config, eventbus=s.eventbus)
    try:
        await s.broker.connect()
        logger.info(
            "KISAdapter 연결 완료 (paper=%s)",
            broker_config.get("is_paper", True),
        )
    except Exception:
        logger.warning("KISAdapter 연결 실패 — 브로커 없이 시작", exc_info=True)
        s.broker = None


async def _sync_instruments(s: Services) -> None:
    """종목 마스터 동기화."""
    try:
        raw_instruments = await s.broker.get_instruments()
        if not raw_instruments:
            return
        from ante.instrument.models import Instrument

        instruments_to_upsert = [
            Instrument(
                symbol=item["symbol"],
                exchange="KRX",
                name=item.get("name", ""),
                name_en=item.get("name_en", ""),
                instrument_type=item.get("instrument_type", ""),
                listed=item.get("listed", True),
            )
            for item in raw_instruments
        ]
        count = await s.instrument_service.bulk_upsert(instruments_to_upsert)
        logger.info("종목 동기화 완료: %d건 갱신", count)
    except Exception:
        logger.warning("종목 동기화 실패 — 기존 캐시 데이터로 운영", exc_info=True)


async def _init_context_factory(s: Services) -> None:
    """StrategyContextFactory 완성 (Broker/APIGateway 연결 이후)."""
    from ante.bot import StrategyContextFactory
    from ante.bot.providers.live import LiveTradeHistoryView
    from ante.gateway.data_provider import LiveDataProvider

    if s.api_gateway:
        s.data_provider = LiveDataProvider(gateway=s.api_gateway)
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


async def _init_treasury_sync(s: Services) -> None:
    """Treasury 잔고 동기화 시작 (Broker 연결 이후)."""
    if not s.broker:
        return

    account_no = getattr(s.broker, "account_no", "")
    is_paper = getattr(s.broker, "is_paper", False)
    formatted_account = (
        f"{account_no[:8]}-{account_no[8:]}" if len(account_no) >= 10 else account_no
    )
    s.treasury.set_account_info(
        account_number=formatted_account,
        is_demo_trading=is_paper,
    )

    sync_interval = s.config.get("treasury.sync_interval_seconds", 300)
    await s.treasury.start_sync(
        broker=s.broker,
        position_history=s.position_history,
        interval_seconds=sync_interval,
    )
    logger.info("Treasury 잔고 동기화 시작 (주기: %d초)", sync_interval)


async def _init_feed(s: Services) -> None:
    """Data Pipeline, BacktestService, ReportStore, ApprovalService 초기화."""
    from ante.data import DataCollector, ParquetStore

    data_path = s.config.get("data.path", "data/")
    Path(data_path).mkdir(parents=True, exist_ok=True)
    s.parquet_store = ParquetStore(base_path=Path(data_path))

    if s.api_gateway:
        s.data_collector = DataCollector(store=s.parquet_store, eventbus=s.eventbus)
    logger.info("Data Pipeline 초기화 완료: %s", data_path)

    # BacktestService
    from ante.backtest import BacktestService

    s.backtest_service = BacktestService(data_path=data_path)
    logger.info("BacktestService 초기화 완료")

    # ReportStore
    from ante.report import ReportStore

    s.report_store = ReportStore(db=s.db)
    await s.report_store.initialize()
    logger.info("ReportStore 초기화 완료")

    # ApprovalService
    from ante.approval import ApprovalService

    approval_executors: dict = {
        "strategy_adopt": lambda params: s.report_store.update_status(
            params["report_id"], "adopted"
        ),
        "bot_stop": lambda params: s.bot_manager.stop_bot(params["bot_id"]),
    }
    s.approval_service = ApprovalService(
        db=s.db, eventbus=s.eventbus, executors=approval_executors
    )
    await s.approval_service.initialize()
    logger.info("ApprovalService 초기화 완료")


async def _init_notification(s: Services) -> None:
    """NotificationService, TelegramCommandReceiver 초기화."""
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
    s.notification_service = NotificationService(
        adapter=adapter,
        eventbus=s.eventbus,
        min_level=NotificationLevel(min_level_str),
        instrument_service=s.instrument_service,
        db=s.db,
    )
    await s.notification_service.initialize()
    s.notification_service.subscribe()
    logger.info("NotificationService 초기화 완료 (Telegram)")

    # TelegramCommandReceiver
    from ante.notification import TelegramCommandReceiver

    allowed_ids_raw = s.config.get("telegram.command.allowed_user_ids", [])
    allowed_user_ids = [int(uid) for uid in allowed_ids_raw] if allowed_ids_raw else []

    if allowed_user_ids:
        s.telegram_receiver = TelegramCommandReceiver(
            adapter=adapter,
            allowed_user_ids=allowed_user_ids,
            polling_interval=s.config.get("telegram.command.polling_interval", 3.0),
            confirm_timeout=s.config.get("telegram.command.confirm_timeout", 30.0),
            bot_manager=s.bot_manager,
            treasury=s.treasury,
            system_state=s.system_state,
        )
        s.telegram_receiver.start()
        logger.info("TelegramCommandReceiver 시작")
    else:
        logger.info("TelegramCommandReceiver 건너뜀 — allowed_user_ids 비어있음")


async def _init_web(s: Services) -> None:
    """FastAPI 앱 생성 및 uvicorn 서버 시작."""
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
        treasury=s.treasury,
        broker=s.broker,
        report_store=s.report_store,
        data_store=s.parquet_store,
        audit_logger=s.audit_logger,
        member_service=s.member_service,
        session_service=session_service,
        strategy_registry=s.strategy_registry,
        dynamic_config=s.dynamic_config,
        approval_service=s.approval_service,
        system_state=s.system_state,
    )

    import uvicorn

    uv_config = uvicorn.Config(
        app,
        host=s.config.get("web.host", "0.0.0.0"),
        port=s.config.get("web.port", 8000),
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
    await shutdown_event.wait()

    await _shutdown(s)


async def _shutdown(s: Services) -> None:
    """종료 정리 (역순)."""
    logger.info("Ante 종료 시작")

    if s.telegram_receiver:
        await s.telegram_receiver.stop()
        logger.info("TelegramCommandReceiver 종료")

    if s.web_task and not s.web_task.done():
        s.web_task.cancel()
        try:
            await s.web_task
        except asyncio.CancelledError:
            pass
        logger.info("Web API 종료")

    await s.treasury.stop_sync()

    await s.bot_manager.stop_all()
    logger.info("BotManager 종료 — 모든 봇 중지")

    if s.api_gateway:
        await s.api_gateway.stop()
        logger.info("APIGateway 종료")

    if s.broker:
        await s.broker.disconnect()
        logger.info("Broker 연결 해제")

    await s.db.close()
    logger.info("Ante 종료 완료")


async def main() -> None:
    """Main asyncio entrypoint.

    초기화 순서 (architecture.md 참조):
    1. Core: Config, Database, EventBus, SystemState, DynamicConfig
    2. Services: AuditLogger, MemberService, InstrumentService
    3. Trading: Strategy, Rule, Treasury, Trade, Bot, Broker, Gateway
    4. Feed: DataPipeline, Backtest, Report, Approval
    5. Notification: Telegram
    6. Web: FastAPI + uvicorn

    종료 순서: 역순 (상위 소비자부터 정리)
    """
    s = Services()

    await _init_core(s)
    await _init_services(s)
    await _init_trading(s)
    await _init_feed(s)
    await _init_notification(s)
    await _init_web(s)
    await _run(s)


if __name__ == "__main__":
    asyncio.run(main())
