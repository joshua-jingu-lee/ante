"""Ante - AI-Native Trading Engine entrypoint."""

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ante.account.models import TradingMode
from ante.account.readiness import (
    ReadinessFlag,
    RuntimeReadinessRegistry,
    is_flag_exempt,
)
from ante.config import Config, DynamicConfigService
from ante.core import Database, clock
from ante.eventbus import EventBus, EventHistoryStore
from ante.eventbus.events import NotificationEvent

logger = logging.getLogger(__name__)

_LEGACY_PID_FALLBACK = Path("db/ante.pid")


def _write_pid_file(config: Config) -> None:
    """PID 파일을 ``config.runtime_pid_path()`` canonical 위치에 기록한다."""
    path = config.runtime_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    logger.info("PID 파일 기록: %s (pid=%d)", path, os.getpid())


def _starting_marker_path(config: Config) -> Path:
    """booting marker 경로를 반환한다."""
    return config.runtime_pid_path().parent / ".starting"


def _write_starting_marker(config: Config) -> None:
    """booting marker에 현재 PID를 기록한다."""
    path = _starting_marker_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    logger.info("Booting marker 기록: %s (pid=%d)", path, os.getpid())


def _read_starting_marker_pid(config: Config) -> int | None:
    """booting marker의 PID를 반환한다. 부재/파싱 실패 시 ``None``."""
    try:
        return int(_starting_marker_path(config).read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _remove_starting_marker(config: Config) -> None:
    """booting marker를 best-effort로 제거한다."""
    path = _starting_marker_path(config)
    try:
        path.unlink(missing_ok=True)
        logger.info("Booting marker 제거: %s", path)
    except OSError:
        logger.warning("Booting marker 제거 실패: %s", path, exc_info=True)


def _remove_pid_file(config: Config) -> None:
    """canonical + legacy ``db/ante.pid`` 양쪽 PID 파일을 정리한다."""
    canonical = config.runtime_pid_path()
    for path in (canonical, _LEGACY_PID_FALLBACK):
        try:
            path.unlink(missing_ok=True)
            logger.info("PID 파일 삭제: %s", path)
        except OSError:
            logger.warning("PID 파일 삭제 실패: %s", path, exc_info=True)


def read_pid_file(config: Config | None = None) -> int | None:
    """PID 파일에서 PID 읽기. canonical 부재/파싱 실패 시 None.

    docs/specs/config/03-design-decisions.md (1.0 단일 active runtime
    정책). 1.0은 single-canonical resolver 모델을 따르므로 legacy cwd-relative
    ``db/ante.pid`` read-fallback은 두지 않는다. canonical
    ``config.runtime_pid_path()``만 본다.
    """
    if config is None:
        config = Config.load()

    canonical = config.runtime_pid_path()
    try:
        return int(canonical.read_text().strip())
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
    order_tracker: Any = None
    fill_applier: Any = None
    fill_outbox: Any = None
    fill_outbox_publisher: Any = None
    bot_manager: Any = None
    signal_channel_registry: Any = None
    virtual_executor: Any = None
    live_portfolio: Any = None
    strategy_snapshot: Any = None
    api_gateway: Any = None
    stream_integrations: dict[str, Any] = field(default_factory=dict)
    reconcile_schedulers: dict[str, Any] = field(default_factory=dict)
    fill_schedulers: dict[str, Any] = field(default_factory=dict)
    fill_catch_up_failed_accounts: set[str] = field(default_factory=set)
    runtime_readiness: RuntimeReadinessRegistry = field(
        default_factory=RuntimeReadinessRegistry
    )
    readiness_self_healing_task: asyncio.Task | None = None  # type: ignore[type-arg]
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
    approval_expire_task: asyncio.Task | None = None  # type: ignore[type-arg]
    audit_cleanup_task: asyncio.Task | None = None  # type: ignore[type-arg]
    stop_session_expiry_task: asyncio.Task | None = None  # type: ignore[type-arg]
    stop_order_manager: Any = None
    _cleanup_tasks: list[str] = field(default_factory=list)


def _account_trading_mode(account: Any) -> TradingMode:
    """Account 의 trading_mode 를 안전하게 추출(미설정 시 VIRTUAL 디폴트)."""
    return getattr(account, "trading_mode", TradingMode.VIRTUAL)


def _flag_exempt_for_account(flag: ReadinessFlag, account: Any) -> bool:
    """면제 매트릭스 적용 — ``account`` 의 (broker_type, trading_mode) 기준."""
    return is_flag_exempt(
        flag,
        broker_type=getattr(account, "broker_type", "test"),
        trading_mode=_account_trading_mode(account),
    )


def _broker_ready_exempt(account: Any) -> bool:
    """broker_ready 면제 계좌(virtual/test)인지 — connect 시도 전 분기."""
    return _flag_exempt_for_account(ReadinessFlag.BROKER, account)


def _broker_not_ready_live(s: Services, account: Any) -> bool:
    """startup connect 에서 broker not_ready 가 된 **비면제(LIVE)** 계좌인지."""
    if s.runtime_readiness is None:
        return False
    if _broker_ready_exempt(account):
        return False
    return not s.runtime_readiness.is_ready(account.account_id, ReadinessFlag.BROKER)


def _mark_runtime_ready(s: Services, account_id: str, flag: ReadinessFlag) -> None:
    """registry ready mark. registry 미주입 환경(partial wiring)에서는 no-op."""
    if s.runtime_readiness is not None:
        s.runtime_readiness.mark_ready(account_id, flag)


def _mark_runtime_not_ready(
    s: Services, account_id: str, flag: ReadinessFlag, reason: str
) -> None:
    """registry not_ready mark. registry 미주입 환경에서는 no-op."""
    if s.runtime_readiness is not None:
        s.runtime_readiness.mark_not_ready(account_id, flag, reason)


def _mark_fill_reconcile_global_skip(s: Services, accounts: list[Any]) -> None:
    """전역 fill skip(connected_count==0 등) 시 면제 우선 mark (이중 실패모드 a)."""
    for account in accounts:
        if _flag_exempt_for_account(ReadinessFlag.FILL_RECONCILE, account):
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.FILL_RECONCILE)
        else:
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.FILL_RECONCILE,
                "fill_init_skipped_no_broker",
            )


def _mark_reconcile_global_skip(s: Services, accounts: list[Any]) -> None:
    """전역 reconcile skip 시 면제 우선 mark (이중 실패모드 a)."""
    for account in accounts:
        if _flag_exempt_for_account(ReadinessFlag.RECONCILE, account):
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.RECONCILE)
        else:
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.RECONCILE,
                "reconcile_init_skipped_no_broker",
            )


def _broker_ready_init_accounts(s: Services, accounts: list[Any]) -> list[Any]:
    """후속 broker-backed startup init 에 넘길 계좌 — broker not_ready LIVE 제외."""
    kept: list[Any] = []
    for account in accounts:
        if _broker_not_ready_live(s, account):
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.TREASURY_SYNC,
                "broker_not_ready_startup",
            )
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.FILL_RECONCILE,
                "broker_not_ready_startup",
            )
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.RECONCILE,
                "broker_not_ready_startup",
            )
            logger.info(
                "후속 broker-backed init skip: account=%s — broker not_ready"
                "(treasury/fill/reconcile self-healing 위임)",
                account.account_id,
            )
            continue
        kept.append(account)
    return kept


async def _init_core(s: Services) -> None:
    """Config, Database, EventBus, DynamicConfig 초기화."""
    if s.config is None:
        s.config = Config.load()
    s.config.validate()

    from ante.core.log import setup_logging

    setup_logging(s.config)
    log_level = s.config.get("system.log_level", "INFO")
    logger.info("Ante 시작")

    db_path = str(s.config.resolve_path("db.path", "db/ante.db"))
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    s.db = Database(db_path)
    await s.db.connect()
    logger.info("Database 연결 완료: %s", db_path)

    history_size = s.config.get("eventbus.history_size", 1000)
    s.eventbus = EventBus(history_size=history_size)
    s.event_history = EventHistoryStore(db=s.db)
    await s.event_history.initialize()
    s.eventbus.use(s.event_history.record)
    logger.info("EventBus 초기화 완료 (history_size=%d)", history_size)

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

    accounts = await s.account_service.list()
    if not accounts:
        await s.account_service.create_default_test_account()
        logger.info("테스트 계좌 자동 생성: account_id=test")

    logger.info("AccountService 초기화 완료")

    await _migrate_is_paper_to_broker_config(s)

    s.account_service.mark_runtime_started()


async def _migrate_is_paper_to_broker_config(s: Services) -> None:
    """system.toml [broker].is_paper를 Account.broker_config으로 1회성 이관한다."""
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


def _subscribe_order_tracker(eventbus: Any, order_tracker: Any) -> None:
    """OrderTracker 를 주문 lifecycle 이벤트에 구독시킨다."""
    from ante.broker.fill_scheduler import business_date_kst
    from ante.eventbus.events import (
        OrderCancelledEvent,
        OrderFailedEvent,
        OrderRejectedEvent,
        OrderSubmittedEvent,
    )

    async def _on_submitted(event: object) -> None:
        if not isinstance(event, OrderSubmittedEvent):
            return
        if not event.order_id or not event.broker_order_id:
            logger.warning(
                "OrderSubmittedEvent 추적 seed skip — order_id/broker_order_id 누락:"
                " order_id=%s broker_order_id=%s",
                event.order_id,
                event.broker_order_id,
            )
            return
        await order_tracker.open(
            order_id=event.order_id,
            account_id=event.account_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            broker_order_id=event.broker_order_id,
            symbol=event.symbol,
            side=event.side,
            order_type=event.order_type,
            ordered_qty=event.quantity,
            submitted_date=business_date_kst(event.timestamp),
            submitted_at=event.timestamp.isoformat() if event.timestamp else None,
            order_price=event.price,
            exchange=event.exchange,
        )

    async def _on_terminal(event: object) -> None:
        if isinstance(event, OrderCancelledEvent):
            status = "cancelled"
        elif isinstance(event, OrderRejectedEvent):
            status = "rejected"
        elif isinstance(event, OrderFailedEvent):
            status = "failed"
        else:
            return
        if not event.order_id:
            return
        await order_tracker.mark_terminal(event.order_id, status)

    eventbus.subscribe(OrderSubmittedEvent, _on_submitted, priority=5)
    eventbus.subscribe(OrderCancelledEvent, _on_terminal, priority=5)
    eventbus.subscribe(OrderRejectedEvent, _on_terminal, priority=5)
    eventbus.subscribe(OrderFailedEvent, _on_terminal, priority=5)


async def _init_trading(s: Services) -> None:
    """Strategy, Trade, TreasuryManager, RuleEngineManager, BotManager."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.strategy import StrategyRegistry

    s.strategy_registry = StrategyRegistry(db=s.db)
    await s.strategy_registry.initialize()
    logger.info("StrategyRegistry 초기화 완료")

    from ante.trade import (
        PerformanceTracker,
        PositionHistory,
        TradeRecorder,
        TradeService,
    )

    s.position_history = PositionHistory(db=s.db)
    await s.position_history.initialize()

    s.trade_recorder = TradeRecorder(
        db=s.db,
        position_history=s.position_history,
        instrument_service=s.instrument_service,
    )
    await s.trade_recorder.initialize()
    s.trade_recorder.subscribe(s.eventbus)

    from ante.trade import (
        FillApplier,
        FillOutbox,
        FillOutboxPublisher,
        OrderTracker,
    )

    s.order_tracker = OrderTracker(db=s.db)
    await s.order_tracker.initialize()
    s.fill_outbox = FillOutbox(db=s.db)
    await s.fill_outbox.initialize()
    s.fill_outbox_publisher = FillOutboxPublisher(
        outbox=s.fill_outbox,
        eventbus=s.eventbus,
    )
    s.fill_applier = FillApplier(
        db=s.db,
        order_tracker=s.order_tracker,
        position_history=s.position_history,
        eventbus=s.eventbus,
        outbox=s.fill_outbox,
        publisher=s.fill_outbox_publisher,
    )
    _subscribe_order_tracker(s.eventbus, s.order_tracker)
    logger.info("OrderTracker / FillApplier / FillOutbox 초기화 완료")

    s.performance_tracker = PerformanceTracker(db=s.db)

    s.trade_service = TradeService(
        recorder=s.trade_recorder,
        position_history=s.position_history,
        performance=s.performance_tracker,
    )
    logger.info("Trade 모듈 초기화 완료")

    from ante.treasury import TreasuryManager

    s.treasury_manager = TreasuryManager(
        db=s.db,
        eventbus=s.eventbus,
        order_tracker=s.order_tracker,
        runtime_readiness=s.runtime_readiness,
    )
    accounts = await s.account_service.list()
    await s.treasury_manager.initialize_all(accounts)
    logger.info("TreasuryManager 초기화 완료: %d개 계좌", len(accounts))

    from ante.rule import RuleEngineManager

    s.rule_engine_manager = RuleEngineManager(
        eventbus=s.eventbus,
        account_service=s.account_service,
        treasury_manager=s.treasury_manager,
        trade_service=s.trade_service,
        order_tracker=s.order_tracker,
        instrument_service=s.instrument_service,
        runtime_readiness=s.runtime_readiness,
    )
    await s.rule_engine_manager.initialize_all(
        accounts, config=s.config, dynamic_config=s.dynamic_config
    )
    logger.info("RuleEngineManager 초기화 완료: %d개 계좌", len(accounts))

    from ante.bot import BotManager
    from ante.bot.providers.virtual import VirtualExecutor
    from ante.bot.signal_key import SignalKeyManager
    from ante.strategy.snapshot import StrategySnapshot

    s.virtual_executor = VirtualExecutor(
        eventbus=s.eventbus,
        gateway=None,
        runtime_readiness=s.runtime_readiness,
        account_service=s.account_service,
        fill_applier=s.fill_applier,
    )
    s.virtual_executor.subscribe()

    strategies_dir = Path(s.config.get("strategy.dir", "strategies"))
    s.strategy_snapshot = StrategySnapshot(strategies_dir)

    signal_key_manager = SignalKeyManager(db=s.db)
    await signal_key_manager.initialize()

    from ante.bot.signal_channel_registry import SignalChannelRegistry

    s.signal_channel_registry = SignalChannelRegistry()

    s.bot_manager = BotManager(
        eventbus=s.eventbus,
        db=s.db,
        context_factory=None,
        snapshot=s.strategy_snapshot,
        account_service=s.account_service,
        treasury_manager=s.treasury_manager,
        trade_service=s.trade_service,
        signal_key_manager=signal_key_manager,
        signal_channel_registry=s.signal_channel_registry,
        order_tracker=s.order_tracker,
    )
    await s.bot_manager.initialize()

    for treasury in s.treasury_manager.list_all():

        def _get_bot_status(bot_id: str, _treasury: Any = treasury) -> str:
            bot = s.bot_manager.get_bot(bot_id)
            return bot.status if bot else ""

        treasury.set_bot_status_checker(_get_bot_status)

    logger.info("BotManager 초기화 완료")


def _connect_failure_reason(exc: BaseException, default: str) -> str:
    """connect 실패 예외에서 readiness reason 을 구조적으로 도출 (T6)."""
    code = getattr(exc, "error_code", None)
    if code:
        return str(code)
    return default


async def _get_broker_with_auth_retry(account_service: Any, account_id: str) -> Any:
    """get_broker(account_id) 를 EGW00133 흡수용 bounded retry 로 감싼다 (T4 c)."""
    from datetime import UTC

    from ante.broker.exceptions import TokenRateLimitError
    from ante.broker.kis import (
        DEFAULT_MAX_RETRIES_AUTH,
        TOKEN_AUTH_BACKOFF_SECONDS,
    )

    attempt = 0
    while True:
        try:
            return await account_service.get_broker(account_id)
        except TokenRateLimitError as e:
            if attempt >= DEFAULT_MAX_RETRIES_AUTH:
                raise
            attempt += 1
            cooldown_until = getattr(e, "cooldown_until", None)
            if cooldown_until is not None:
                remaining = (cooldown_until - clock.now(UTC)).total_seconds()
                sleep_seconds = max(0.0, remaining)
            else:
                sleep_seconds = TOKEN_AUTH_BACKOFF_SECONDS
            logger.warning(
                "Broker connect EGW00133(토큰 발급 빈도 제한) — %.0f초(잔여 cooldown) "
                "후 재시도 %d/%d",
                sleep_seconds,
                attempt,
                DEFAULT_MAX_RETRIES_AUTH,
            )
            await asyncio.sleep(sleep_seconds)


async def _init_gateway(s: Services) -> None:
    """APIGateway(account_service 주입), StreamIntegration, 종목 동기화."""
    assert s.eventbus is not None

    from ante.gateway import APIGateway
    from ante.gateway.stop_order import StopOrderManager

    stop_order_manager = StopOrderManager(eventbus=s.eventbus)
    stop_order_manager.start()

    s.stop_order_manager = stop_order_manager
    if s.bot_manager is not None:
        s.bot_manager.set_stop_order_manager(stop_order_manager)
    s.stop_session_expiry_task = asyncio.create_task(
        _stop_session_expiry_loop(stop_order_manager),
        name="stop-session-expiry",
    )
    logger.info("스탑 주문 세션 만료 스케줄러 시작 (주기: 60초)")

    s.api_gateway = APIGateway(
        account_service=s.account_service,
        eventbus=s.eventbus,
        stop_order_manager=stop_order_manager,
        order_tracker=s.order_tracker,
        runtime_readiness=s.runtime_readiness,
    )
    s.api_gateway.start()
    logger.info("APIGateway 시작 완료")

    accounts = await s.account_service.list()
    connected_count = 0
    for account in accounts:
        if _broker_ready_exempt(account):
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.BROKER)
            continue
        try:
            await _get_broker_with_auth_retry(s.account_service, account.account_id)
            connected_count += 1
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.BROKER)
            logger.info(
                "Broker 연결: account=%s, type=%s",
                account.account_id,
                account.broker_type,
            )
        except Exception as e:
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.BROKER,
                _connect_failure_reason(e, "connect_failed"),
            )
            logger.warning(
                "Broker 연결 실패: account=%s — 건너뜀",
                account.account_id,
                exc_info=True,
            )
            from ante.eventbus.events import NotificationEvent

            if s.eventbus is not None:
                await s.eventbus.publish(
                    NotificationEvent(
                        level="error",
                        title="Broker 연결 실패",
                        message=(
                            f"계좌 {account.account_id} 브로커 연결에 실패했습니다."
                            " 주문 실행이 불가능할 수 있습니다."
                        ),
                        category="system",
                    )
                )
    if connected_count:
        logger.info("Broker 연결 완료: %d/%d개 계좌", connected_count, len(accounts))

    for account in accounts:
        if account.broker_type == "kis":
            if _broker_not_ready_live(s, account):
                logger.info(
                    "StreamIntegration 초기화 skip: account=%s — broker not_ready"
                    "(self-healing 위임)",
                    account.account_id,
                )
                continue
            try:
                await s.account_service.get_broker(account.account_id)
                broker_config = {**account.credentials, **account.broker_config}
                await _init_stream_integration(
                    s,
                    broker_config,
                    stop_order_manager,
                    account_id=account.account_id,
                )
            except Exception:
                logger.warning(
                    "StreamIntegration 초기화 실패: account=%s",
                    account.account_id,
                    exc_info=True,
                )
                from ante.eventbus.events import NotificationEvent

                if s.eventbus is not None:
                    await s.eventbus.publish(
                        NotificationEvent(
                            level="error",
                            title="실시간 시세 연결 실패",
                            message=(
                                f"계좌 {account.account_id} StreamIntegration 초기화에"
                                " 실패했습니다. 실시간 시세가 수신되지 않습니다."
                            ),
                            category="system",
                        )
                    )

    if connected_count:
        await _sync_instruments(s, accounts)

    _init_context_factory(s)

    if s.treasury_manager is not None and s.api_gateway is not None:
        gateway = s.api_gateway
        for account in accounts:

            def _make_resolver(account_id: str) -> Callable[[str], Awaitable[float]]:
                async def _resolver(symbol: str) -> float:
                    return cast(
                        "float",
                        await gateway.get_current_price(symbol, account_id=account_id),
                    )

                return _resolver

            try:
                s.treasury_manager.set_order_reserve_price_resolver(
                    account.account_id, _make_resolver(account.account_id)
                )
            except KeyError:
                logger.debug(
                    "Treasury 미등록 계좌 — order_reserve_price_resolver 주입 생략: %s",
                    account.account_id,
                )

    broker_init_accounts = _broker_ready_init_accounts(s, accounts)

    await _init_treasury_sync(s, broker_init_accounts)

    if connected_count and s.fill_applier and s.order_tracker:
        await _init_fill_recovery_schedulers(s, broker_init_accounts)
    else:
        _mark_fill_reconcile_global_skip(s, accounts)

    if s.fill_outbox_publisher:
        await _init_fill_outbox_publisher(s)

    if connected_count and s.trade_service:
        await _init_reconcile_scheduler(s)
    else:
        _mark_reconcile_global_skip(s, accounts)

    _start_readiness_self_healing(s, accounts)

    if s.performance_tracker and s.trade_recorder and s.position_history:
        await _init_daily_report_scheduler(s)


async def _init_fill_recovery_schedulers(s: Services, accounts: list[Any]) -> None:
    """FillReconcileScheduler 생성 + 기동 카치업(barrier) + 주기 폴 시작."""
    s.fill_catch_up_failed_accounts.clear()
    for account in accounts:
        if _flag_exempt_for_account(ReadinessFlag.FILL_RECONCILE, account):
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.FILL_RECONCILE)
            continue
        await _register_fill_scheduler_for_account(s, account)

    if s.fill_schedulers:
        logger.info(
            "FillReconcileScheduler 시작 완료: 계좌 %d개 (%s)",
            len(s.fill_schedulers),
            ", ".join(s.fill_schedulers),
        )


async def _register_fill_scheduler_for_account(s: Services, account: Any) -> bool:
    """계좌 하나의 FillReconcileScheduler (재)등록. ``catch_up_once`` 성공 여부 반환."""
    from ante.broker.fill_scheduler import FillReconcileScheduler

    account_id = account.account_id

    fallback_enabled = (
        bool(s.config.get("system.fill_position_fallback_enabled", True))
        if s.config is not None
        else True
    )

    try:
        broker = await s.account_service.get_broker(account_id)
    except Exception:
        _mark_runtime_not_ready(
            s, account_id, ReadinessFlag.FILL_RECONCILE, "get_broker_failed"
        )
        return False

    existing = s.fill_schedulers.pop(account_id, None)
    if existing is not None:
        try:
            await existing.stop()
        except Exception:
            logger.warning(
                "기존 FillReconcileScheduler 정리 실패(재등록): account=%s",
                account_id,
                exc_info=True,
            )

    scheduler = FillReconcileScheduler(
        broker=broker,
        order_tracker=s.order_tracker,
        fill_applier=s.fill_applier,
        account_id=account_id,
        trade_service=s.trade_service,
        eventbus=s.eventbus,
        fallback_enabled=fallback_enabled,
        instrument_service=s.instrument_service,
    )
    result = await scheduler.catch_up_once()
    if not result.succeeded:
        s.fill_catch_up_failed_accounts.add(account_id)
        logger.warning(
            "기동 체결 카치업 미성공: account=%s — reconcile external-buy "
            "분류를 연기한다(barrier 유지)",
            account_id,
        )
    else:
        s.fill_catch_up_failed_accounts.discard(account_id)
        if result.applied:
            logger.info(
                "기동 체결 카치업: account=%s, %d건 반영",
                account_id,
                result.applied,
            )
    await scheduler.start()
    s.fill_schedulers[account_id] = scheduler

    if result.succeeded:
        _mark_runtime_ready(s, account_id, ReadinessFlag.FILL_RECONCILE)
    else:
        _mark_runtime_not_ready(
            s, account_id, ReadinessFlag.FILL_RECONCILE, "catch_up_poll_failed"
        )
    return result.succeeded


async def _init_fill_outbox_publisher(s: Services) -> None:
    """FillOutboxPublisher 기동 재전달(catch_up) + 주기 드레인 루프 시작."""
    publisher = s.fill_outbox_publisher
    if publisher is None:
        return
    redelivered = await publisher.catch_up_once()
    if redelivered:
        logger.info("기동 outbox 재전달: %d건", redelivered)
    await publisher.start()
    logger.info("FillOutboxPublisher 시작 완료")


async def _init_reconcile_scheduler(s: Services) -> None:
    """ReconcileScheduler 생성 및 시작."""
    assert s.eventbus is not None

    from ante.trade.reconciler import PositionReconciler

    reconcile_config = s.config.get("reconcile", {})
    if not isinstance(reconcile_config, dict):
        reconcile_config = {}

    accounts = await s.account_service.list()

    enabled = reconcile_config.get("enabled", True)
    if not enabled:
        logger.info("ReconcileScheduler 비활성화 (reconcile.enabled=false)")
        for account in accounts:
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.RECONCILE)
        return

    interval = reconcile_config.get("interval_seconds", 1800)

    reconciler = PositionReconciler(
        trade_service=s.trade_service,
        eventbus=s.eventbus,
        order_tracker=s.order_tracker,
        instrument_service=s.instrument_service,
    )

    started: list[str] = []
    for account in accounts:
        if _flag_exempt_for_account(ReadinessFlag.RECONCILE, account):
            _mark_runtime_ready(s, account.account_id, ReadinessFlag.RECONCILE)
            continue
        if _broker_not_ready_live(s, account):
            continue
        if await _register_reconcile_scheduler_for_account(
            s, account, reconciler, interval
        ):
            started.append(account.account_id)

    if not started:
        logger.info("ReconcileScheduler 건너뜀 — 연결된 Broker 없음")
        return

    logger.info(
        "ReconcileScheduler 시작 완료: 계좌 %d개 (%s, 주기: %d초)",
        len(started),
        ", ".join(started),
        interval,
    )


def _build_reconciler(s: Services) -> Any:
    """PositionReconciler 1개 생성 (startup + self-healing 공용)."""
    assert s.eventbus is not None
    from ante.trade.reconciler import PositionReconciler

    return PositionReconciler(
        trade_service=s.trade_service,
        eventbus=s.eventbus,
        order_tracker=s.order_tracker,
        instrument_service=s.instrument_service,
    )


async def _register_reconcile_scheduler_for_account(
    s: Services, account: Any, reconciler: Any, interval: int
) -> bool:
    """단일 LIVE 계좌의 ReconcileScheduler 등록 (startup + self-healing 공용)."""
    assert s.eventbus is not None
    from ante.bot.reconcile_scheduler import ReconcileScheduler

    account_id = account.account_id
    try:
        broker = await s.account_service.get_broker(account_id)
    except Exception:
        _mark_runtime_not_ready(
            s, account_id, ReadinessFlag.RECONCILE, "get_broker_failed"
        )
        return False

    skip_initial_external_buy = account_id in s.fill_catch_up_failed_accounts

    existing = s.reconcile_schedulers.pop(account_id, None)
    if existing is not None:
        try:
            await existing.stop()
        except Exception:
            logger.warning(
                "기존 ReconcileScheduler 정리 실패(재등록): account=%s",
                account_id,
                exc_info=True,
            )

    scheduler = ReconcileScheduler(
        reconciler=reconciler,
        broker=broker,
        bot_manager=s.bot_manager,
        eventbus=s.eventbus,
        broker_account_id=account_id,
        interval_seconds=interval,
        skip_initial_external_buy=skip_initial_external_buy,
    )
    try:
        await scheduler.start()
    except Exception:
        logger.warning(
            "ReconcileScheduler 시작 실패: account=%s",
            account_id,
            exc_info=True,
        )
        _mark_runtime_not_ready(
            s, account_id, ReadinessFlag.RECONCILE, "scheduler_start_failed"
        )
        return False
    s.reconcile_schedulers[account_id] = scheduler
    _mark_runtime_ready(s, account_id, ReadinessFlag.RECONCILE)
    return True


def _self_healing_targets(accounts: list[Any]) -> list[Any]:
    """self-healing 대상 — **전 계좌**."""
    return list(accounts)


def _start_readiness_self_healing(s: Services, accounts: list[Any]) -> None:
    """self-healing background retry loop 시작 (startup init 완료 후)."""
    if s.readiness_self_healing_task is not None:
        return
    targets = _self_healing_targets(accounts)
    if not targets:
        return
    s.readiness_self_healing_task = asyncio.create_task(
        _readiness_self_healing_loop(s, targets),
        name="readiness-self-healing",
    )
    logger.info("Readiness self-healing loop 시작: 대상 계좌 %d개", len(targets))


async def _self_healing_recover_account(s: Services, account: Any) -> bool:
    """단일 계좌의 1회 회복 시도. 반환은 active_trading_ready(registry 없으면 True)."""
    account_id = account.account_id

    if s.runtime_readiness is None:
        return True

    broker_exempt = is_flag_exempt(
        ReadinessFlag.BROKER,
        broker_type=account.broker_type,
        trading_mode=account.trading_mode,
    )
    broker_just_recovered = False
    if not broker_exempt and not s.runtime_readiness.is_ready(
        account_id, ReadinessFlag.BROKER
    ):
        try:
            broker = await s.account_service.get_broker(account_id)
            await broker.connect()
        except Exception as e:
            _mark_runtime_not_ready(
                s,
                account_id,
                ReadinessFlag.BROKER,
                _connect_failure_reason(e, "reconnect_failed"),
            )
            from ante.broker.exceptions import TokenRateLimitError

            if isinstance(e, TokenRateLimitError):
                raise
            return False
        broker_just_recovered = True

    fill_exempt = is_flag_exempt(
        ReadinessFlag.FILL_RECONCILE,
        broker_type=account.broker_type,
        trading_mode=account.trading_mode,
    )
    fill_needs_register = broker_just_recovered or not s.runtime_readiness.is_ready(
        account_id, ReadinessFlag.FILL_RECONCILE
    )
    if (
        not fill_exempt
        and fill_needs_register
        and s.fill_applier is not None
        and s.order_tracker is not None
    ):
        await _register_fill_scheduler_for_account(s, account)
    reconcile_exempt = is_flag_exempt(
        ReadinessFlag.RECONCILE,
        broker_type=account.broker_type,
        trading_mode=account.trading_mode,
    )
    reconcile_needs_register = (
        broker_just_recovered
        or not s.runtime_readiness.is_ready(account_id, ReadinessFlag.RECONCILE)
    )
    if (
        not reconcile_exempt
        and reconcile_needs_register
        and s.trade_service is not None
    ):
        reconcile_enabled = True
        interval = 1800
        if s.config is not None:
            reconcile_config = s.config.get("reconcile", {})
            if isinstance(reconcile_config, dict):
                reconcile_enabled = reconcile_config.get("enabled", True)
                interval = reconcile_config.get("interval_seconds", 1800)
        if reconcile_enabled:
            reconciler = _build_reconciler(s)
            await _register_reconcile_scheduler_for_account(
                s, account, reconciler, interval
            )
        else:
            _mark_runtime_ready(s, account_id, ReadinessFlag.RECONCILE)
    if broker_just_recovered or not s.runtime_readiness.is_ready(
        account_id, ReadinessFlag.TREASURY_SYNC
    ):
        await _init_treasury_sync(s, [account])
    if broker_just_recovered:
        _mark_runtime_ready(s, account_id, ReadinessFlag.BROKER)
        logger.info("Readiness self-healing: broker 회복 — account=%s", account_id)
    return s.runtime_readiness.active_trading_ready(
        account_id,
        broker_type=account.broker_type,
        trading_mode=account.trading_mode,
    )


async def _readiness_self_healing_loop(s: Services, targets: list[Any]) -> None:
    """active_trading_ready 가 아닌 대상 계좌를 무기한 재시도하는 background loop."""
    interval = 60
    max_per_burst = 5
    backoff_base = 5
    backoff_max = 60
    if s.config is not None:
        interval = int(s.config.get("readiness.self_healing_interval_seconds", 60))
        max_per_burst = int(
            s.config.get("readiness.self_healing_max_attempts_per_burst", 5)
        )
        backoff_base = int(
            s.config.get("readiness.self_healing_backoff_base_seconds", 5)
        )
        backoff_max = int(
            s.config.get("readiness.self_healing_backoff_max_seconds", 60)
        )

    try:
        while True:
            pending = [
                a
                for a in targets
                if s.runtime_readiness is not None
                and not s.runtime_readiness.active_trading_ready(
                    a.account_id,
                    broker_type=a.broker_type,
                    trading_mode=a.trading_mode,
                )
            ]
            from ante.broker.exceptions import TokenRateLimitError

            for account in pending:
                for attempt in range(max_per_burst):
                    try:
                        recovered = await _self_healing_recover_account(s, account)
                    except asyncio.CancelledError:
                        raise
                    except TokenRateLimitError:
                        logger.info(
                            "Readiness self-healing EGW00133 — account=%s, "
                            "다음 interval(%ds)에 위임(burst break)",
                            account.account_id,
                            interval,
                        )
                        break
                    except Exception:
                        logger.exception(
                            "Readiness self-healing 회복 예외 — account=%s (루프 유지)",
                            account.account_id,
                        )
                        recovered = False
                    if recovered:
                        break
                    if attempt < max_per_burst - 1:
                        await asyncio.sleep(
                            min(backoff_base * (2**attempt), backoff_max)
                        )
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Readiness self-healing loop 취소(shutdown)")
        raise


async def _init_daily_report_scheduler(s: Services) -> None:
    """DailyReportScheduler 생성 및 시작 (Account 기반 실행 시각)."""
    from ante.trade.daily_report import (
        DailyReportScheduler,
        compute_report_time,
    )

    accounts = await s.account_service.list() if s.account_service else []
    account = accounts[0] if accounts else None

    report_time = compute_report_time(account.trading_hours_end) if account else None
    account_id = account.account_id if account else ""
    currency = account.currency if account else "KRW"

    treasury = None
    if s.treasury_manager and account_id:
        try:
            treasury = s.treasury_manager.get(account_id)
        except KeyError:
            logger.warning("Treasury not found for account_id=%s", account_id)

    kwargs: dict[str, Any] = {
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
    broker_config: dict[str, Any],
    stop_order_manager: Any,
    *,
    account_id: str,
) -> None:
    """StreamIntegration 시작. 성공하면 stream_integrations[account_id] 에 등록한다."""
    assert s.eventbus is not None
    from ante.account.scoping import require_account_id

    require_account_id(account_id, context="main._init_stream_integration")

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
        account_id=account_id,
    )

    integration = StreamIntegration(
        stream_client=stream_client,
        cache=s.api_gateway._cache,
        eventbus=s.eventbus,
        account_id=account_id,
        stop_order_manager=stop_order_manager,
        gateway=s.api_gateway,
        bot_manager=s.bot_manager,
        fill_applier=s.fill_applier,
    )

    try:
        await integration.start()
        s.stream_integrations[account_id] = integration
        logger.info(
            "StreamIntegration 시작 완료 (account=%s, paper=%s)",
            account_id,
            is_paper,
        )
    except Exception:
        logger.warning(
            "StreamIntegration 시작 실패 — REST 전용 모드로 운영 (account=%s)",
            account_id,
            exc_info=True,
        )


async def _sync_instruments(s: Services, accounts: list[Any]) -> None:
    """종목 마스터 동기화(면제·not_ready LIVE 계좌와 동기화한 exchange 는 건너뜀)."""
    synced_exchanges: set[str] = set()
    for account in accounts:
        if _broker_ready_exempt(account):
            continue
        if _broker_not_ready_live(s, account):
            logger.info(
                "종목 동기화 skip: account=%s — broker not_ready(self-healing 위임)",
                account.account_id,
            )
            continue
        if account.exchange in synced_exchanges:
            continue
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
            synced_exchanges.add(account.exchange)
            logger.info(
                "종목 동기화 완료: account=%s, exchange=%s, %d건 갱신",
                account.account_id,
                account.exchange,
                count,
            )
        except Exception:
            logger.warning(
                "종목 동기화 실패: account=%s — 다음 계좌 시도",
                account.account_id,
                exc_info=True,
            )
    if not synced_exchanges:
        logger.warning("종목 동기화 실패 — 기존 캐시 데이터로 운영")


def _init_context_factory(s: Services) -> None:
    """StrategyContextFactory 완성 (Gateway 연결 이후)."""
    from ante.bot import StrategyContextFactory

    if s.api_gateway:
        s.virtual_executor._gateway = s.api_gateway

    if not s.data_provider:
        s.data_provider = _NullDataProvider()

    context_factory = StrategyContextFactory(
        data_provider=s.data_provider,
        account_service=s.account_service,
        live_portfolio=s.live_portfolio,
        virtual_executor=s.virtual_executor,
        treasury_manager=s.treasury_manager,
        position_history=s.position_history,
        api_gateway=s.api_gateway,
        parquet_store=s.parquet_store,
        order_tracker=s.order_tracker,
        trade_recorder=s.trade_recorder,
    )
    s.bot_manager._context_factory = context_factory
    logger.info("StrategyContextFactory 설정 완료")


class _NullDataProvider:
    """API gateway 가 없는 환경에서 사용되는 no-op
    DataProvider. strategy 인터페이스 호환을 위해 빈 결과를 반환한다."""

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> Any:
        import polars as pl

        return pl.DataFrame(
            schema={
                "timestamp": pl.Float64,
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Float64,
            }
        )

    async def get_current_price(self, symbol: str) -> float:
        return 0.0

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {}


async def _init_treasury_sync(s: Services, accounts: list[Any]) -> None:
    """각 계좌의 Treasury 잔고 동기화 시작 (Broker 연결 이후)."""
    sync_interval = s.config.get("treasury.sync_interval_seconds", 300)

    for account in accounts:
        try:
            treasury = s.treasury_manager.get(account.account_id)
            await treasury.stop_sync()
            trading_mode = getattr(account, "trading_mode", TradingMode.VIRTUAL)
            is_virtual = trading_mode == TradingMode.VIRTUAL

            if is_virtual:
                price_resolver = None
                if s.api_gateway:
                    gateway = s.api_gateway
                    bound_account_id = account.account_id

                    async def _resolve_price(
                        symbol: str, _account_id: str = bound_account_id
                    ) -> float:
                        return cast(
                            "float",
                            await gateway.get_current_price(
                                symbol, account_id=_account_id
                            ),
                        )

                    price_resolver = _resolve_price

                treasury.start_sync(
                    broker=None,
                    position_history=s.position_history,
                    interval_seconds=sync_interval,
                    trading_mode="virtual",
                    price_resolver=price_resolver,
                )
                _mark_runtime_ready(s, account.account_id, ReadinessFlag.TREASURY_SYNC)
                logger.info(
                    "Treasury Virtual 동기화 시작: account=%s (주기: %d초)",
                    account.account_id,
                    sync_interval,
                )
            else:
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
                _mark_runtime_ready(s, account.account_id, ReadinessFlag.TREASURY_SYNC)
                logger.info(
                    "Treasury Live 동기화 시작: account=%s (주기: %d초)",
                    account.account_id,
                    sync_interval,
                )
        except Exception:
            _mark_runtime_not_ready(
                s,
                account.account_id,
                ReadinessFlag.TREASURY_SYNC,
                "treasury_sync_failed",
            )
            logger.warning(
                "Treasury 동기화 시작 실패: account=%s — 건너뜀",
                account.account_id,
                exc_info=True,
            )
            from ante.eventbus.events import NotificationEvent

            if s.eventbus is not None:
                await s.eventbus.publish(
                    NotificationEvent(
                        level="error",
                        title="Treasury 잔고 동기화 실패",
                        message=(
                            f"계좌 {account.account_id} Treasury 잔고 동기화에"
                            " 실패했습니다. 봇 운영 시 잔고 불일치가"
                            " 발생할 수 있습니다."
                        ),
                        category="system",
                    )
                )


async def _restore_bots(s: Services) -> None:
    """DB의 봇을 시작하지 않은 채 메모리로 복원한다(봇 관리자가 없으면 건너뜀)."""
    if s.bot_manager is None:
        return
    await s.bot_manager.restore_bots()


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

    from ante.backtest import BacktestService

    s.backtest_service = BacktestService(data_path=data_path, eventbus=s.eventbus)
    logger.info("BacktestService 초기화 완료")

    from ante.backtest.run_store import BacktestRunStore

    backtest_run_store = BacktestRunStore(db=s.db)
    await backtest_run_store.initialize()
    logger.info("BacktestRunStore 초기화 완료")

    from ante.report import ReportStore

    s.report_store = ReportStore(db=s.db)
    await s.report_store.initialize()
    logger.info("ReportStore 초기화 완료")

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
    from ante.approval.handlers import build_executors, build_validators

    approval_executors = build_executors(s)
    approval_validators = build_validators(s)

    auto_approve_raw = s.config.get("approval.auto_approve", {})
    auto_approve_config = AutoApproveConfig.from_dict(
        auto_approve_raw if isinstance(auto_approve_raw, dict) else {}
    )

    async def _resolve_auto_approve_account(account_id: str) -> Any:
        """전결 판단용 Account 조회. 없으면 자동승인하지 않는다."""
        from ante.account.errors import AccountNotFoundError

        if s.account_service is None:
            return None
        try:
            return await s.account_service.get(account_id)
        except AccountNotFoundError:
            return None

    auto_approve_evaluator = AutoApproveEvaluator(
        config=auto_approve_config,
        account_resolver=_resolve_auto_approve_account,
    )
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


async def _stop_session_expiry_loop(
    stop_order_manager: Any,
    interval: float = 60.0,
) -> None:
    """거래 세션 종료 시 미트리거 스탑 주문을 주기적으로 만료 처리."""
    while True:
        await asyncio.sleep(interval)
        try:
            await stop_order_manager.check_session_expiry()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("스탑 주문 세션 만료 스케줄러 오류")


async def _init_notification(s: Services) -> None:
    """NotificationService·TelegramCommandReceiver 초기화(시크릿 누락·공란이면 skip)."""
    assert s.eventbus is not None
    assert s.dynamic_config is not None

    from ante.config import ConfigError
    from ante.notification import (
        NotificationLevel,
        NotificationService,
        TelegramAdapter,
    )

    try:
        telegram_token = s.config.secret("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = s.config.secret("TELEGRAM_CHAT_ID")
    except ConfigError as err:
        logger.info("NotificationService 건너뜀 — Telegram 시크릿 없음: %s", err)
        return

    if not (telegram_token and telegram_chat_id):
        logger.info("NotificationService 건너뜀 — Telegram 시크릿이 공란")
        return

    adapter = TelegramAdapter(bot_token=telegram_token, chat_id=telegram_chat_id)
    min_level_raw = await s.dynamic_config.get(
        "notification.min_level",
        default=s.config.get("notification.min_level", "info"),
    )
    min_level_str = str(min_level_raw)
    try:
        min_level = NotificationLevel(min_level_str)
    except ValueError:
        logger.warning(
            "notification.min_level 무시: 유효하지 않은 값 %r",
            min_level_raw,
        )
        min_level = NotificationLevel.INFO

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
        min_level=min_level,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        telegram_enabled=telegram_enabled_bool,
    )
    s.notification_service.subscribe()
    logger.info(
        "NotificationService 초기화 완료 (Telegram, enabled=%s)", telegram_enabled_bool
    )

    from ante.notification import TelegramCommandReceiver

    chat_id_str = telegram_chat_id
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
            treasury_manager=s.treasury_manager,
            account_service=s.account_service,
            approval_service=s.approval_service,
            instrument_service=s.instrument_service,
        )
        s.telegram_receiver.start()
        logger.info("TelegramCommandReceiver 시작 (chat_id=%s)", chat_id)
    elif not telegram_enabled_bool:
        logger.info("TelegramCommandReceiver 건너뜀 — telegram_enabled=false")
    else:
        logger.info("TelegramCommandReceiver 건너뜀 — TELEGRAM_CHAT_ID 미설정")


_RULES_UNAVAILABLE_HISTORY_HINT = (
    " ante config history accounts.{id}.rules 로 이전 값을 확인하고 필요한 규칙을 "
    "모두 다시 저장하세요 — 깨지기 전의 다른 규칙은 복원되지 않습니다."
)

_RULES_UNAVAILABLE_MESSAGES = {
    "not_list": (
        "계좌 {id} 의 거래 규칙 저장값이 규칙 목록 형식이 아니어서 이 계좌의 주문을 "
        "막았습니다. ante rule update <rule_type> --account {id} 로 규칙을 다시 "
        "저장하면 재기동 없이 풀립니다." + _RULES_UNAVAILABLE_HISTORY_HINT
    ),
    "read_error": (
        "계좌 {id} 의 거래 규칙 저장값을 읽는 중 오류가 나 이 계좌의 주문을 "
        "막았습니다. 저장값은 멀쩡할 수 있으며 재기동으로 풀릴 수 있습니다. 풀리지 "
        "않으면 ante rule update <rule_type> --account {id} 로 규칙을 다시 저장하세요."
        + _RULES_UNAVAILABLE_HISTORY_HINT
    ),
    "invalid_item": (
        "계좌 {id} 의 거래 규칙 저장값에 규칙으로 만들 수 없는 항목이 있어 이 계좌의 "
        "주문을 막았습니다. 오류 로그에서 문제의 항목을 확인하세요. 다른 항목은 "
        "저장값에 그대로 남아 있습니다. 규칙이 읽지 않는 키·범위 밖 값·priority 값·"
        "문자열이 아닌 id가 원인이면 그 항목의 규칙 유형으로 "
        "ante rule update <rule_type> --account {id} 를 한 번 하면(그런 유형이 "
        "여럿이면 유형마다 한 번) 재기동 없이 풀립니다. "
        "규칙 객체가 아닌 항목·해시할 수 없는 type의 항목·등록되지 않았거나 없는 "
        "type의 항목·같은 유형의 둘째 이후 깨진 항목은 어느 유형으로든 rule update를 "
        "한 번 하면 저장값에서 버려져 풀립니다."
    ),
}


async def _notify_rules_unavailable(s: Services) -> None:
    """저장된 계좌 룰을 읽지 못해 막힌 계좌마다 운영자 알림을 한 번 낸다."""
    if s.rule_engine_manager is None or s.eventbus is None:
        return
    for account_id, cause in s.rule_engine_manager.rules_unavailable_accounts().items():
        message = _RULES_UNAVAILABLE_MESSAGES[cause]
        await s.eventbus.publish(
            NotificationEvent(
                level="error",
                title="계좌 규칙을 읽지 못함 — 주문 차단",
                message=message.format(id=account_id),
                category="system",
            )
        )


async def _init_ipc(s: Services) -> None:
    """IPC 서버 초기화 — Unix 도메인 소켓 기반 프로세스 간 통신."""
    assert s.eventbus is not None

    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry, register_all_handlers
    from ante.ipc.server import IPCServer
    from ante.trade.reconciler import PositionReconciler

    reconciler = PositionReconciler(
        trade_service=s.trade_service,
        eventbus=s.eventbus,
        order_tracker=s.order_tracker,
        instrument_service=s.instrument_service,
    )

    service_registry = ServiceRegistry(
        account=s.account_service,
        bot_manager=s.bot_manager,
        treasury_manager=s.treasury_manager,
        dynamic_config=s.dynamic_config,
        approval=s.approval_service,
        reconciler=reconciler,
        eventbus=s.eventbus,
        strategy_registry=s.strategy_registry,
        audit_logger=s.audit_logger,
        member_service=s.member_service,
        trade_service=s.trade_service,
        signal_channel_registry=s.signal_channel_registry,
        config=s.config,
    )

    command_registry = CommandRegistry()
    register_all_handlers(command_registry)

    socket_path = str(s.config.runtime_socket_path())
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)
    s.ipc_server = IPCServer(socket_path, service_registry, command_registry)
    await s.ipc_server.start()
    logger.info("IPC 서버 초기화 완료: %s", socket_path)


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

    try:
        await asyncio.wait_for(_shutdown(s), timeout=30.0)
    except TimeoutError:
        logger.error("Shutdown 30초 타임아웃 — 강제 종료")


async def _shutdown(s: Services) -> None:
    """종료 정리 — cold-path race window 를 막는 순서로 서비스를 멈춘다."""
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

    if s.stop_session_expiry_task is not None and not s.stop_session_expiry_task.done():
        s.stop_session_expiry_task.cancel()
        try:
            await s.stop_session_expiry_task
        except asyncio.CancelledError:
            pass
        logger.info("스탑 주문 세션 만료 스케줄러 종료")

    if s.ipc_server:
        await s.ipc_server.stop_accepting()
        logger.info("IPCServer 새 연결 수락 중지")

    if s.stop_order_manager is not None:
        await s.stop_order_manager.stop()
        logger.info("StopOrderManager 종료 — 활성 스탑 주문 manager_stopped 정리")

    if s.signal_channel_registry:
        s.signal_channel_registry.freeze()
        await s.signal_channel_registry.close_all("draining")
        logger.info("SignalChannelRegistry sweep 완료 — 모든 시그널 채널 종료")

    if s.daily_report_scheduler:
        await s.daily_report_scheduler.stop()
        logger.info("DailyReportScheduler 종료")

    if (
        s.readiness_self_healing_task is not None
        and not s.readiness_self_healing_task.done()
    ):
        s.readiness_self_healing_task.cancel()
        try:
            await s.readiness_self_healing_task
        except asyncio.CancelledError:
            pass
        logger.info("Readiness self-healing loop 종료")

    for sched_account_id, scheduler in list(s.reconcile_schedulers.items()):
        try:
            await scheduler.stop()
            logger.info("ReconcileScheduler 종료: account=%s", sched_account_id)
        except Exception:
            logger.warning(
                "ReconcileScheduler 종료 실패: account=%s",
                sched_account_id,
                exc_info=True,
            )
    s.reconcile_schedulers.clear()

    for fill_account_id, fill_scheduler in list(s.fill_schedulers.items()):
        try:
            await fill_scheduler.stop()
            logger.info("FillReconcileScheduler 종료: account=%s", fill_account_id)
        except Exception:
            logger.warning(
                "FillReconcileScheduler 종료 실패: account=%s",
                fill_account_id,
                exc_info=True,
            )
    s.fill_schedulers.clear()

    if s.fill_outbox_publisher:
        try:
            await s.fill_outbox_publisher.stop()
            logger.info("FillOutboxPublisher 종료")
        except Exception:
            logger.warning("FillOutboxPublisher 종료 실패", exc_info=True)

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

    for stream_account_id, integration in list(s.stream_integrations.items()):
        try:
            await integration.stop()
            logger.info("StreamIntegration 종료: account=%s", stream_account_id)
        except Exception:
            logger.warning(
                "StreamIntegration 종료 실패: account=%s",
                stream_account_id,
                exc_info=True,
            )
    s.stream_integrations.clear()

    if s.api_gateway:
        s.api_gateway.stop()
        logger.info("APIGateway 종료")

    if s.ipc_server:
        s.ipc_server.stop_dispatching()
        logger.info("IPCServer dispatch 거부 시작")

    if s.account_service:
        accounts = await s.account_service.list()
        for account in accounts:
            broker = await s.account_service.get_cached_broker(account.account_id)
            if broker is None:
                continue
            try:
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

    if s.ipc_server:
        await s.ipc_server.drain_connections(timeout=5.0)
        s.ipc_server.unlink_socket()
        logger.info("IPCServer 소켓 파일 제거")

    logger.info("Ante 종료 완료")


async def main() -> None:
    """Main asyncio entrypoint."""
    s = Services()
    s.config = Config.load()

    try:
        _write_starting_marker(s.config)
        _write_pid_file(s.config)

        await _init_core(s)

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
        await _restore_bots(s)
        await _init_feed(s)
        await _init_approval(s)
        await _init_notification(s)
        await _notify_rules_unavailable(s)
        await _init_ipc(s)
        _remove_starting_marker(s.config)
        await _run(s)
    finally:
        _remove_starting_marker(s.config)
        _remove_pid_file(s.config)


if __name__ == "__main__":
    asyncio.run(main())
