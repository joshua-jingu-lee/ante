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

# Legacy cwd-relative PID 경로. Refs #1157: 1.0 single-canonical resolver 모델로
# cutover된 이후 새 read는 canonical만 본다. 이 상수는 transitional cleanup 용도로
# `_remove_pid_file`이 양쪽 unlink할 때만 사용된다 (legacy 환경에서 stale loop를
# 차단하기 위한 best-effort 정리).
_LEGACY_PID_FALLBACK = Path("db/ante.pid")


def _write_pid_file(config: Config) -> None:
    """PID 파일을 ``config.runtime_pid_path()`` canonical 위치에 기록한다.

    Refs #1157, docs/specs/config/03-design-decisions.md 200-202.
    Server runtime, cold-path CLI guard, IPC client가 같은 ``config_dir``을
    쓰면 같은 PID 파일을 본다.
    """
    path = config.runtime_pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    logger.info("PID 파일 기록: %s (pid=%d)", path, os.getpid())


def _starting_marker_path(config: Config) -> Path:
    """booting marker 경로를 반환한다.

    Refs #1160: PID 파일과 같은 디렉토리의 ``.starting`` 파일을 사용한다.
    ``runtime.pid_path`` resolver에서 파생하므로 #1157의 single-canonical
    runtime path 정책과 자동으로 정합된다.
    """
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
    """canonical + legacy ``db/ante.pid`` 양쪽 PID 파일을 정리한다.

    Refs #1157: ``read_pid_file``은 canonical만 보지만, legacy cwd-relative
    ``db/ante.pid``가 과거 환경에서 남아 있을 수 있으므로 cleanup은 양쪽을
    ``unlink(missing_ok=True)`` 처리해 transitional 환경에서 stale 잔여를
    제거한다 (best-effort). 이 책임은 ``read_pid_file``의 single-canonical
    정책과 분리되며, 단지 호환 cleanup만 수행한다.
    """
    canonical = config.runtime_pid_path()
    for path in (canonical, _LEGACY_PID_FALLBACK):
        try:
            path.unlink(missing_ok=True)
            logger.info("PID 파일 삭제: %s", path)
        except OSError:
            logger.warning("PID 파일 삭제 실패: %s", path, exc_info=True)


def read_pid_file(config: Config | None = None) -> int | None:
    """PID 파일에서 PID 읽기. canonical 부재/파싱 실패 시 None.

    Refs #1157, docs/specs/config/03-design-decisions.md (1.0 단일 active runtime
    정책). 1.0은 single-canonical resolver 모델을 따르므로 legacy cwd-relative
    ``db/ante.pid`` read-fallback은 두지 않는다. canonical
    ``config.runtime_pid_path()``만 본다.

    ``config``이 ``None``이면 ``Config.load()``로 env/디폴트 기준 canonical을
    산출한다. 0-arg 호환을 유지해 기존 ``patch("ante.main.read_pid_file", ...)``
    monkeypatch 사용처(test_account_cli, test_cli_update 등)가 그대로 동작한다.
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
    # Config — `main()`이 PID 기록 직전에 미리 로드해 둘 수 있다 (Refs #1157).
    if s.config is None:
        s.config = Config.load()
    s.config.validate()

    from ante.core.log import setup_logging

    setup_logging(s.config)
    log_level = s.config.get("system.log_level", "INFO")
    logger.info("Ante 시작")

    # Database
    # `db.path` 는 cold-path CLI(`account create/delete/set-credentials`) 와
    # 동일한 resolver 를 거쳐야 한다 — 절대 경로면 그대로, 상대 경로면
    # `config_dir` 기준으로 정규화. 이로써 server runtime 과 CLI 가 같은
    # DB 를 본다 (Refs #1158).
    db_path = str(s.config.resolve_path("db.path", "db/ante.db"))
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

    # 부팅 mutation(create_default_test_account, is_paper migration)이 모두 끝난
    # 뒤에야 runtime 플래그를 활성화한다 (#1144 invariant S3).
    # 이 호출 이후 cold-path 메서드/필드 변경은
    # ``AccountStructuralChangeRequiresStoppedServerError``로 차단된다.
    s.account_service.mark_runtime_started()


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

    # KIS 브로커 계좌의 StreamIntegration 초기화
    for account in accounts:
        if account.broker_type == "kis":
            try:
                broker = await s.account_service.get_broker(account.account_id)
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
    # SPLIT-1: 단일 broker만 주입되므로 해당 broker의 account_id로 scheduler를
    # 바인딩해, 다른 계좌의 봇에 이 broker의 positions가 잘못 적용되지 않도록
    # 가드한다. multi-broker pool은 SPLIT-3에서 도입한다.
    broker = None
    broker_account_id: str | None = None
    accounts = await s.account_service.list()
    for account in accounts:
        try:
            broker = await s.account_service.get_broker(account.account_id)
            broker_account_id = account.account_id
            break
        except Exception:
            continue

    if not broker or not broker_account_id:
        logger.info("ReconcileScheduler 건너뜀 — 연결된 Broker 없음")
        return

    s.reconcile_scheduler = ReconcileScheduler(
        reconciler=reconciler,
        broker=broker,
        bot_manager=s.bot_manager,
        eventbus=s.eventbus,
        broker_account_id=broker_account_id,
        interval_seconds=interval,
    )
    await s.reconcile_scheduler.start()
    logger.info(
        "ReconcileScheduler 시작 완료 (account=%s, 주기: %d초)",
        broker_account_id,
        interval,
    )


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
    *,
    account_id: str = "",
) -> None:
    """KISStreamClient + StreamIntegration 초기화.

    SPLIT-1 (#1240): ``OrderFilledEvent``는 strict ``_requires_account_id``
    marker를 가진다. 본 SPLIT 범위에서는 multi-account StreamIntegration
    pool화는 하지 않고(SPLIT-3 #1242 영역 보존), 단일 인스턴스에 활성
    KIS 계좌의 ``account_id``를 보강하여 broker payload fallback 시에도
    체결 이벤트가 정상 발행되도록 한다.
    """
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
        account_id=account_id,
    )

    s.stream_integration = StreamIntegration(
        stream_client=stream_client,
        cache=s.api_gateway._cache,
        eventbus=s.eventbus,
        account_id=account_id,
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
            account_service=s.account_service,
            live_portfolio=s.live_portfolio,
            live_order_view=s.live_order_view,
            paper_executor=s.paper_executor,
            live_trade_history=live_trade_history,
            treasury_manager=s.treasury_manager,
            position_history=s.position_history,
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
                    # SPLIT-3 (#1242): APIGateway.get_current_price 가
                    # account_id 를 required 로 받으므로, 봇 계좌의
                    # account_id 를 closure 에 명시 binding 한다 (late
                    # binding 차단을 위해 default 인자 사용).
                    bound_account_id = account.account_id

                    async def _resolve_price(
                        symbol: str, _account_id: str = bound_account_id
                    ) -> float:
                        return await gateway.get_current_price(
                            symbol, account_id=_account_id
                        )

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


def _approval_account_id(params: dict, *, context: str) -> str:
    """approval params 에서 검증된 account_id 를 추출.

    Refs #1217 → #1241 SPLIT-2: ``params.get("account_id", "test")`` fallback
    제거. ``ApprovalService`` 가 create()/reopen() 진입점에서 이미 동일한
    검증을 수행하지만, executor / validator 가 main.py 외부에서도 호출될 수
    있으므로 진입점 단위로 한 번 더 명시 검증한다.
    """
    from ante.account.scoping import require_account_id

    return require_account_id(params.get("account_id"), context=context)


async def _init_approval(s: Services) -> None:
    """ApprovalService 초기화: Executor, Validator, 전결 설정, 만료 스케줄러."""
    assert s.db is not None
    assert s.eventbus is not None

    from ante.approval import ApprovalService
    from ante.approval.auto_approve import AutoApproveConfig, AutoApproveEvaluator
    from ante.approval.models import ValidationResult
    from ante.report.models import ReportStatus

    async def _exec_rule_change(params: dict) -> None:
        account_id = _approval_account_id(params, context="approval.rule_change.exec")
        engine = s.rule_engine_manager.get(account_id)
        engine.update_rules(params["bot_id"], params["rules"])

    async def _exec_budget_change(params: dict) -> None:
        # Refs #1217 → #1241 SPLIT-2: lambda 내부 fallback 제거. named func 으로
        # 추출하여 require_account_id 진입점을 lambda 안으로 가져온다.
        account_id = _approval_account_id(params, context="approval.budget_change.exec")
        treasury = s.treasury_manager.get(account_id)
        await treasury.update_budget(params["bot_id"], params["amount"])

    from ante.strategy.registry import StrategyStatus

    async def _exec_strategy_adopt(params: dict) -> None:
        await s.report_store.update_status(params["report_id"], ReportStatus.ADOPTED)
        await s.strategy_registry.update_status(
            params["strategy_id"], StrategyStatus.ADOPTED
        )
        from ante.eventbus.events import NotificationEvent

        rec = await s.strategy_registry.get(params["strategy_id"])
        name = rec.name if rec else params["strategy_id"]
        ver = rec.version if rec else "unknown"
        if s.eventbus is not None:
            await s.eventbus.publish(
                NotificationEvent(
                    level="info",
                    title="전략 채택",
                    message=(
                        f"전략 '{name}' (v{ver})이 채택되었습니다."
                        " 봇에 배정할 수 있습니다."
                    ),
                    category="strategy",
                )
            )

    async def _exec_strategy_retire(params: dict) -> None:
        await s.report_store.update_status(params["report_id"], ReportStatus.ARCHIVED)
        await s.strategy_registry.update_status(
            params["strategy_id"], StrategyStatus.ARCHIVED
        )
        from ante.eventbus.events import NotificationEvent

        rec = await s.strategy_registry.get(params["strategy_id"])
        name = rec.name if rec else params["strategy_id"]
        ver = rec.version if rec else "unknown"
        if s.eventbus is not None:
            await s.eventbus.publish(
                NotificationEvent(
                    level="info",
                    title="전략 폐기",
                    message=f"전략 '{name}' (v{ver})이 보관 처리되었습니다.",
                    category="strategy",
                )
            )

    approval_executors: dict = {
        # 전략 관련
        "strategy_adopt": _exec_strategy_adopt,
        "strategy_retire": _exec_strategy_retire,
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
        "budget_change": _exec_budget_change,
        "rule_change": _exec_rule_change,
    }

    # 사전 검증 validator 정의
    from ante.bot.config import BotStatus

    async def _validate_strategy_adopt(params: dict) -> list[ValidationResult]:
        """전략 채택 사전 검증: report_id·strategy_id 존재 확인."""
        strategy_id = params.get("strategy_id", "")
        if not strategy_id:
            return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
        report_id = params.get("report_id", "")
        if not report_id:
            return [ValidationResult("fail", "report_id가 누락되었습니다", "system")]
        record = await s.strategy_registry.get(strategy_id)
        if record is None:
            return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
        return [ValidationResult("pass", "", "system")]

    async def _validate_strategy_retire(params: dict) -> list[ValidationResult]:
        """전략 폐기 사전 검증: 전략 상태 확인."""
        strategy_id = params.get("strategy_id", "")
        if not strategy_id:
            return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
        record = await s.strategy_registry.get(strategy_id)
        if record is None:
            return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
        if record.status == StrategyStatus.ARCHIVED:
            return [ValidationResult("fail", "이미 보관된 전략입니다", "system")]
        return [ValidationResult("pass", "", "system")]

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
        """예산 변경 사전 검증: 미할당 잔액 충분 여부 (warn).

        Refs #1217 → #1241 SPLIT-2: ``params.get("account_id", "test")``
        fallback 제거. invalid account_id 는 ``ValidationResult("fail", ...)``
        으로 변환해 ``ApprovalService`` 가 ``ApprovalValidationError`` 로
        변환하도록 한다 (validator 계약: raise 대신 fail 반환).
        """
        from ante.account.errors import InvalidAccountIdError

        try:
            account_id = _approval_account_id(
                params, context="approval.budget_change.validate"
            )
        except InvalidAccountIdError as e:
            return [ValidationResult("fail", str(e), "system:treasury")]
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
        "strategy_adopt": _validate_strategy_adopt,
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
    """NotificationService, TelegramCommandReceiver 초기화.

    부팅 계약 (#1118):

    - ``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` 시크릿이 누락(``ConfigError``)
      되거나 공란이면 NotificationService 를 생성하지 않고 부팅을 계속한다.
      과거에는 시크릿이 아예 없을 때 ``Config.secret()`` 이 raise 하여 부팅이
      막혔다 — ``notification.telegram_enabled=false`` 로 Telegram 을 끈 stage
      환경에서도 우회가 필요했던 원인이다.
    - 시크릿이 존재하면 ``notification.telegram_enabled`` 플래그와 무관하게
      ``NotificationService`` 를 항상 생성한다. 플래그는 서비스 내부의 필터링
      (CRITICAL 이외 차단) 과 ``ConfigChangedEvent`` 기반 런타임 재활성화
      계약에만 사용된다 — `docs/specs/notification/notification.md` §_should_send
      참조. 서비스 자체를 지워 버리면 disabled 상태에서도 보장되어야 할
      CRITICAL 알림 경로와 동적 토글이 함께 무력화된다.
    - 공란 시크릿(``TELEGRAM_BOT_TOKEN=`` 등) 역시 비활성화 신호로 취급한다
      (`docs/superpowers/specs/2026-04-17-staging-environment-design.md` 참고).
      ``Config.secret()`` 은 이 경우 raise 하지 않고 빈 문자열을 반환하므로
      별도 가드가 필요하다.
    """
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
        min_level=min_level,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        telegram_enabled=telegram_enabled_bool,
    )
    s.notification_service.subscribe()
    logger.info(
        "NotificationService 초기화 완료 (Telegram, enabled=%s)", telegram_enabled_bool
    )

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
        strategy_registry=s.strategy_registry,
    )

    command_registry = CommandRegistry()
    register_all_handlers(command_registry)

    # Refs #1157: socket 경로는 `runtime.socket_path` resolver로 통일한다.
    # default `<config_dir>/run/ante.sock` (또는 `[runtime] socket_path` override).
    # cold-path CLI guard / IPCClient가 같은 resolver를 쓰므로 같은 socket을 본다.
    socket_path = str(s.config.runtime_socket_path())
    Path(socket_path).parent.mkdir(parents=True, exist_ok=True)
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

    try:
        await asyncio.wait_for(_shutdown(s), timeout=30.0)
    except TimeoutError:
        logger.error("Shutdown 30초 타임아웃 — 강제 종료")


async def _shutdown(s: Services) -> None:
    """종료 정리 (역순).

    종료 순서 (Refs #1159 — cold-path race window 차단):
    1. 종료 알림(NotificationEvent), Telegram, 스케줄러 태스크 취소
    2. **IPCServer.stop_accepting()** — 새 IPC 연결 차단, **소켓 파일은 유지**.
       이 호출 시작 시 IPCServer state는 `SHUTTING_DOWN`으로 전환되어 이후
       active connection의 mutating command를 `SERVICE_UNAVAILABLE`로 거부한다.
    3. Web API 종료
    4. DailyReportScheduler, ReconcileScheduler 종료
    5. 각 계좌의 Treasury sync 중지
    6. BotManager 전체 봇 중지
    7. StreamIntegration 종료
    8. APIGateway 종료
    9. BrokerAdapter/DB 종료 직전 **IPCServer.stop_dispatching()** — active
        connection의 read-only dispatch까지 `SERVICE_UNAVAILABLE`로 거부.
    10. 각 계좌의 BrokerAdapter disconnect
    11. Database 종료
    12. **IPCServer.drain_connections() + unlink_socket()** — 소켓 파일 제거.
        cold-path guard(`PID alive AND socket exists`)가 이 시점부터 'active 아님'
        판정.
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

    # Refs #1159/#1184: 새 IPC 연결만 차단하고 소켓 파일은 유지한다.
    # stop_accepting() 시작 시 IPCServer state가 SHUTTING_DOWN으로 바뀌어
    # 이후 active connection의 mutating command는 SERVICE_UNAVAILABLE로 거부된다.
    # cold-path guard(`PID alive AND socket exists`)가 BotManager/DB 종료 전까지
    # 'active runtime'으로 판정하도록 unlink_socket()은 lifecycle 마지막에서 호출.
    if s.ipc_server:
        await s.ipc_server.stop_accepting()
        logger.info("IPCServer 새 연결 수락 중지")

    if s.web_task and not s.web_task.done():
        s.web_task.cancel()
        try:
            await s.web_task
        except asyncio.CancelledError:
            pass
        logger.info("Web API 종료")

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

    # Refs #1184: BrokerAdapter disconnect/DB close 직전에는 read-only도 더는
    # 안전하지 않다. 기존 active IPC connection의 추가 dispatch를 모두 거부한다.
    if s.ipc_server:
        s.ipc_server.stop_dispatching()
        logger.info("IPCServer dispatch 거부 시작")

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

    # Refs #1159: BotManager/DB 종료 후에야 소켓 파일을 제거한다.
    # 이로써 cold-path guard는 'PID alive AND socket exists' 동안에는 항상
    # 봇/DB가 살아있는 active runtime을 정확히 가리킨다.
    if s.ipc_server:
        await s.ipc_server.drain_connections(timeout=5.0)
        s.ipc_server.unlink_socket()
        logger.info("IPCServer 소켓 파일 제거")

    logger.info("Ante 종료 완료")


async def main() -> None:
    """Main asyncio entrypoint.

    초기화 순서 (Account 중심):
    0. Booting marker + PID 기록 (starting도 active runtime으로 표시)
    1. Core: Config, Database, EventBus, DynamicConfig
    2. Services: AuditLogger, MemberService, InstrumentService
    3. Account: AccountService, 테스트 계좌 자동 생성
    4. Trading: StrategyRegistry, Trade, TreasuryManager, RuleEngineManager, BotManager
    5. Gateway: APIGateway(account_service 주입)
    6. Feed: DataPipeline, Backtest, Report
    7. Approval: ApprovalService
    8. Notification: Telegram(account_service 주입)
    9. IPC: Unix 도메인 소켓 서버 (성공 후 booting marker 제거)
    10. Web: FastAPI(account_service 주입)

    종료 순서: 역순 (상위 소비자부터 정리)
    """
    s = Services()
    # Refs #1157: PID 기록 전에 Config를 미리 로드해 canonical
    # `<config_dir>/run/ante.pid` 위치에 기록한다. `_init_core`는 동일
    # 인스턴스를 그대로 재사용한다.
    s.config = Config.load()

    try:
        # Refs #1160: starting 단계도 active runtime으로 판정되도록 marker를
        # PID보다 먼저 기록한다. marker만 있고 PID가 없는 극소 구간은
        # cold-path guard가 PID 부재로 통과하므로 mutation race를 만들지 않는다.
        _write_starting_marker(s.config)
        _write_pid_file(s.config)

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
        _remove_starting_marker(s.config)
        await _init_web(s)
        await _run(s)
    finally:
        _remove_starting_marker(s.config)
        _remove_pid_file(s.config)


if __name__ == "__main__":
    asyncio.run(main())
