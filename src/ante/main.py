"""Ante - AI-Native Trading Engine entrypoint.

Composition Root: 모든 모듈을 조립하고 시스템을 부팅한다.
"""

import asyncio
import logging
import signal
from pathlib import Path

from ante.config import Config, DynamicConfigService, SystemState
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main asyncio entrypoint.

    초기화 순서 (architecture.md 참조):
    1. Config + Logging
    2. Database
    3. EventBus + EventHistoryStore
    4. SystemState (킬 스위치)
    5. DynamicConfigService
    6. StrategyRegistry
    7. RuleEngine
    8. Treasury
    9. Trade (Recorder, PositionHistory, PerformanceTracker, Service)
    10. BotManager
    11. Broker (KISAdapter) + APIGateway
    12. Data Pipeline (ParquetStore, DataCatalog, DataCollector)
    13. BacktestService
    14. ReportStore
    15. NotificationService
    16. Web API (FastAPI)

    종료 순서: 역순 (상위 소비자부터 정리)
    """
    # ── 1. Config ────────────────────────────────────
    config = Config.load(config_dir=Path("config"))
    config.validate()

    log_level = config.get("system.log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Ante 시작")

    # ── 2. Database ──────────────────────────────────
    db_path = config.get("db.path", "db/ante.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    await db.connect()
    logger.info("Database 연결 완료: %s", db_path)

    # ── 3. EventBus ──────────────────────────────────
    history_size = config.get("eventbus.history_size", 1000)
    eventbus = EventBus(history_size=history_size)

    event_history = EventHistoryStore(db=db)
    await event_history.initialize()
    eventbus.use(event_history.record)
    logger.info("EventBus 초기화 완료 (history_size=%d)", history_size)

    # ── 4. SystemState (킬 스위치) ───────────────────
    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()
    logger.info("SystemState 초기화 완료: %s", system_state.trading_state)

    # ── 5. DynamicConfigService ──────────────────────
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()

    # log_level 동적 설정: 기본값 등록 + 변경 구독
    from ante.config.dynamic import _on_log_level_changed
    from ante.eventbus.events import ConfigChangedEvent

    await dynamic_config.register_default(
        "system.log_level", log_level, category="system"
    )
    eventbus.subscribe(ConfigChangedEvent, _on_log_level_changed)
    logger.info("DynamicConfigService 초기화 완료")

    # ── 5.5. MemberService ─────────────────────────────
    from ante.member import MemberService

    member_service = MemberService(db=db, eventbus=eventbus)
    await member_service.initialize()
    logger.info("MemberService 초기화 완료")

    # ── 5.6. InstrumentService ─────────────────────────
    from ante.instrument import InstrumentService

    instrument_service = InstrumentService(db=db)
    await instrument_service.initialize()

    # ── 6. StrategyRegistry ──────────────────────────
    from ante.strategy import StrategyRegistry

    strategy_registry = StrategyRegistry(db=db)
    await strategy_registry.initialize()
    logger.info("StrategyRegistry 초기화 완료")

    # ── 7. RuleEngine ────────────────────────────────
    from ante.rule import RuleEngine

    rule_engine = RuleEngine(eventbus=eventbus, system_state=system_state)
    await rule_engine.start()

    rule_configs = config.get("rules.global", [])
    if rule_configs:
        rule_engine.load_rules_from_config(rule_configs)
    logger.info("RuleEngine 초기화 완료")

    # ── 8. Treasury ──────────────────────────────────
    from ante.treasury import Treasury

    commission_rate = config.get("broker.commission_rate", 0.00015)
    sell_tax_rate = config.get("broker.sell_tax_rate", 0.0023)
    treasury = Treasury(
        db=db,
        eventbus=eventbus,
        commission_rate=commission_rate,
        sell_tax_rate=sell_tax_rate,
    )
    await treasury.initialize()
    logger.info("Treasury 초기화 완료")

    # ── 9. Trade ─────────────────────────────────────
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
    logger.info("Trade 모듈 초기화 완료")

    # ── 10. BotManager + StrategyContextFactory ──────
    from ante.bot import BotManager, StrategyContextFactory
    from ante.bot.providers.live import LiveOrderView, LivePortfolioView
    from ante.bot.providers.paper import PaperExecutor

    # PaperExecutor (paper 봇이 존재할 때 가상 체결 처리)
    paper_executor = PaperExecutor(
        eventbus=eventbus,
        gateway=None,  # APIGateway 연결 후 설정
        commission_rate=commission_rate,
        sell_tax_rate=sell_tax_rate,
    )
    paper_executor.subscribe()

    # Live 프로바이더
    live_portfolio = LivePortfolioView(
        treasury=treasury,
        position_history=position_history,
    )
    live_order_view = LiveOrderView(order_registry=None)  # Broker 연결 후 설정

    # StrategyContextFactory

    # DataProvider는 APIGateway 연결 후 설정 (11단계)
    context_factory: StrategyContextFactory | None = None

    from ante.strategy.snapshot import StrategySnapshot

    strategies_dir = Path(config.get("strategy.dir", "strategies"))
    strategy_snapshot = StrategySnapshot(strategies_dir)

    bot_manager = BotManager(
        eventbus=eventbus,
        db=db,
        context_factory=context_factory,  # APIGateway 연결 후 갱신
        snapshot=strategy_snapshot,
    )
    await bot_manager.initialize()
    logger.info("BotManager 초기화 완료")

    # ── 11. Broker + APIGateway ──────────────────────
    from ante.broker import KISAdapter
    from ante.gateway import APIGateway

    broker = None
    api_gateway = None

    broker_config = config.get("broker", {})
    try:
        broker_config["app_key"] = config.secret("KIS_APP_KEY")
        broker_config["app_secret"] = config.secret("KIS_APP_SECRET")
        broker_config["account_no"] = config.secret("KIS_ACCOUNT_NO")
    except Exception:
        pass  # 비밀값 없으면 브로커 미사용

    if broker_config.get("app_key"):
        broker = KISAdapter(config=broker_config, eventbus=eventbus)
        try:
            await broker.connect()
            logger.info(
                "KISAdapter 연결 완료 (paper=%s)", broker_config.get("is_paper", True)
            )
        except Exception:
            logger.warning("KISAdapter 연결 실패 — 브로커 없이 시작", exc_info=True)
            broker = None

    if broker:
        api_gateway = APIGateway(broker=broker, eventbus=eventbus)
        await api_gateway.start()
        logger.info("APIGateway 시작 완료")

    # ── 11.1. 종목 마스터 동기화 ───────────────────────
    if broker:
        try:
            raw_instruments = await broker.get_instruments()
            if raw_instruments:
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
                count = await instrument_service.bulk_upsert(instruments_to_upsert)
                logger.info("종목 동기화 완료: %d건 갱신", count)
        except Exception:
            logger.warning("종목 동기화 실패 — 기존 캐시 데이터로 운영", exc_info=True)

    # ── 11.5. StrategyContextFactory 완성 ─────────────
    from ante.gateway.data_provider import LiveDataProvider

    data_provider: LiveDataProvider | None = None
    if api_gateway:
        data_provider = LiveDataProvider(gateway=api_gateway)
        paper_executor._gateway = api_gateway

    from ante.bot.providers.live import LiveTradeHistoryView

    live_trade_history = LiveTradeHistoryView(trade_recorder=trade_recorder)

    if data_provider:
        context_factory = StrategyContextFactory(
            data_provider=data_provider,
            live_portfolio=live_portfolio,
            live_order_view=live_order_view,
            paper_executor=paper_executor,
            live_trade_history=live_trade_history,
        )
        bot_manager._context_factory = context_factory
        logger.info("StrategyContextFactory 설정 완료")

    # ── 11.6. Treasury 잔고 동기화 ────────────────────
    if broker:
        sync_interval = config.get("treasury.sync_interval_seconds", 300)
        await treasury.start_sync(
            broker=broker,
            position_history=position_history,
            interval_seconds=sync_interval,
        )
        logger.info("Treasury 잔고 동기화 시작 (주기: %d초)", sync_interval)

    # ── 12. Data Pipeline ────────────────────────────
    from ante.data import DataCatalog, DataCollector, ParquetStore

    data_path = config.get("data.path", "data/")
    Path(data_path).mkdir(parents=True, exist_ok=True)
    parquet_store = ParquetStore(base_path=Path(data_path))
    data_catalog = DataCatalog(store=parquet_store)

    data_collector = None
    if api_gateway:
        data_collector = DataCollector(store=parquet_store, eventbus=eventbus)  # noqa: F841
    logger.info("Data Pipeline 초기화 완료: %s", data_path)

    # ── 13. BacktestService ──────────────────────────
    from ante.backtest import BacktestService

    backtest_service = BacktestService(data_path=data_path)  # noqa: F841
    logger.info("BacktestService 초기화 완료")

    # ── 14. ReportStore ──────────────────────────────
    from ante.report import ReportStore

    report_store = ReportStore(db=db)
    await report_store.initialize()
    logger.info("ReportStore 초기화 완료")

    # ── 14.5. ApprovalService ──────────────────────────
    from ante.approval import ApprovalService

    approval_executors: dict = {
        "strategy_adopt": lambda params: report_store.update_status(
            params["report_id"], "adopted"
        ),
        "bot_stop": lambda params: bot_manager.stop_bot(params["bot_id"]),
    }
    approval_service = ApprovalService(  # noqa: F841
        db=db, eventbus=eventbus, executors=approval_executors
    )
    await approval_service.initialize()
    logger.info("ApprovalService 초기화 완료")

    # ── 15. NotificationService ──────────────────────
    from ante.notification import (
        NotificationLevel,
        NotificationService,
        TelegramAdapter,
    )

    notification_service = None
    telegram_token = config.get_secret("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = config.get_secret("TELEGRAM_CHAT_ID")

    if telegram_token and telegram_chat_id:
        adapter = TelegramAdapter(bot_token=telegram_token, chat_id=telegram_chat_id)
        min_level_str = config.get("notification.min_level", "info")
        notification_service = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            min_level=NotificationLevel(min_level_str),
            instrument_service=instrument_service,
            db=db,
        )
        await notification_service.initialize()
        notification_service.subscribe()
        logger.info("NotificationService 초기화 완료 (Telegram)")
    else:
        logger.info("NotificationService 건너뜀 — Telegram 설정 없음")

    # ── 15.5. TelegramCommandReceiver ─────────────────
    telegram_receiver = None
    if telegram_token and telegram_chat_id:
        from ante.notification import TelegramCommandReceiver

        allowed_ids_raw = config.get("telegram.command.allowed_user_ids", [])
        allowed_user_ids = (
            [int(uid) for uid in allowed_ids_raw] if allowed_ids_raw else []
        )

        if allowed_user_ids:
            telegram_receiver = TelegramCommandReceiver(
                adapter=adapter,
                allowed_user_ids=allowed_user_ids,
                polling_interval=config.get("telegram.command.polling_interval", 3.0),
                confirm_timeout=config.get("telegram.command.confirm_timeout", 30.0),
                bot_manager=bot_manager,
                treasury=treasury,
                system_state=system_state,
            )
            telegram_receiver.start()
            logger.info("TelegramCommandReceiver 시작")
        else:
            logger.info("TelegramCommandReceiver 건너뜀 — allowed_user_ids 비어있음")

    # ── 16. Web API ──────────────────────────────────
    web_task = None
    web_enabled = config.get("web.enabled", False)

    if web_enabled:
        from ante.web.app import create_app

        app = create_app(
            config=config,
            eventbus=eventbus,
            bot_manager=bot_manager,
            trade_service=trade_service,
            treasury=treasury,
            report_store=report_store,
            data_catalog=data_catalog,
            data_store=parquet_store,
        )

        import uvicorn

        uv_config = uvicorn.Config(
            app,
            host=config.get("web.host", "0.0.0.0"),
            port=config.get("web.port", 8000),
            log_level="info",
        )
        server = uvicorn.Server(uv_config)
        web_task = asyncio.create_task(server.serve(), name="web-api")
        logger.info(
            "Web API 시작: http://%s:%d",
            uv_config.host,
            uv_config.port,
        )

    # ── Graceful Shutdown ────────────────────────────
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("종료 시그널 수신")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Ante 준비 완료 — 종료 시그널 대기 중")
    await shutdown_event.wait()

    # ── 종료 정리 (역순) ─────────────────────────────
    logger.info("Ante 종료 시작")

    # 15.5 TelegramCommandReceiver
    if telegram_receiver:
        await telegram_receiver.stop()
        logger.info("TelegramCommandReceiver 종료")

    # 16. Web API
    if web_task and not web_task.done():
        web_task.cancel()
        try:
            await web_task
        except asyncio.CancelledError:
            pass
        logger.info("Web API 종료")

    # 10.5 Treasury 잔고 동기화 중지
    await treasury.stop_sync()

    # 10. BotManager (봇 먼저 중지)
    await bot_manager.stop_all()
    logger.info("BotManager 종료 — 모든 봇 중지")

    # 11. APIGateway
    if api_gateway:
        await api_gateway.stop()
        logger.info("APIGateway 종료")

    # 11. Broker
    if broker:
        await broker.disconnect()
        logger.info("Broker 연결 해제")

    # 2. Database (최종)
    await db.close()
    logger.info("Ante 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
