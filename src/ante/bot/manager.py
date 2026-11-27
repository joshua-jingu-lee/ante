"""BotManager — 봇 생명주기 중앙 관리."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ante.account.errors import AccountDeletedError
from ante.account.models import AccountStatus
from ante.account.scoping import require_account_id
from ante.bot.bot import Bot, _transition_status
from ante.bot.config import (
    BotConfig,
    BotStatus,
    validate_interval,
    validate_runtime_controls,
)
from ante.bot.exceptions import (
    BotAlreadyExistsError,
    BotError,
    BotImmutableFieldError,
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotStateConflict,
    BotStrategyAlreadyRunningError,
    SignalKeyManagerNotConfigured,
)
from ante.core.account_id import AccountError
from ante.eventbus.events import NotificationEvent, OrderCancelEvent
from ante.strategy.exceptions import StrategyError

if TYPE_CHECKING:
    from collections.abc import Callable

    from ante.account.service import AccountService
    from ante.bot.context_factory import StrategyContextFactory
    from ante.bot.signal_channel_registry import SignalChannelRegistry
    from ante.bot.signal_key import SignalKeyManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.gateway.stop_order import StopOrder, StopOrderManager
    from ante.rule.engine import RuleEngine
    from ante.strategy.base import Strategy
    from ante.strategy.context import StrategyContext
    from ante.strategy.snapshot import StrategySnapshot
    from ante.trade.order_tracker import OrderTracker, OrderTrackerRecord
    from ante.trade.service import TradeService
    from ante.treasury.manager import TreasuryManager

logger = logging.getLogger(__name__)

BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    bot_id       TEXT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    strategy_id  TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    config_json  TEXT NOT NULL,
    auto_start   BOOLEAN DEFAULT 0,
    status       TEXT DEFAULT 'created',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bots_account_id ON bots(account_id);
"""

_PERSISTED_BOT_CONFIG_FIELDS: tuple[str, ...] = (
    "interval_seconds",
    "auto_restart",
    "max_restart_attempts",
    "restart_cooldown_seconds",
    "step_timeout_seconds",
    "max_signals_per_step",
)


def _runtime_control_default(name: str) -> Any:
    """``BotConfig`` dataclass field default 를 조회한다."""

    for field in dataclasses.fields(BotConfig):
        if field.name != name:
            continue
        if field.default is not dataclasses.MISSING:
            return field.default
        if field.default_factory is not dataclasses.MISSING:
            return field.default_factory()
        raise KeyError(
            f"BotConfig field {name!r} has no default — manager 가 default 를 "
            "독립적으로 정의할 수 없다 (SSOT: BotConfig dataclass)"
        )
    raise KeyError(f"BotConfig has no field {name!r}")


def _pick_persisted_runtime_control(config_data: dict[str, Any], name: str) -> Any:
    """``config_json`` runtime control 값(key 없으면 default, null이면 ValueError)."""

    if name not in config_data:
        return _runtime_control_default(name)
    value = config_data[name]
    if value is None:
        raise ValueError(f"invalid persisted runtime control: {name} is null")
    return value


def _bot_config_from_row(row: Any, config_data: dict[str, Any]) -> BotConfig:
    """``bots`` 행과 해석한 ``config_json`` 으로 ``BotConfig`` 를 만든다."""
    config_data.pop("bot_type", None)
    config_data.pop("exchange", None)
    return BotConfig(
        bot_id=row["bot_id"],
        strategy_id=row["strategy_id"],
        name=row["name"] or config_data.get("name", row["bot_id"]),
        account_id=row.get("account_id") or "",
        **{
            name: _pick_persisted_runtime_control(config_data, name)
            for name in _PERSISTED_BOT_CONFIG_FIELDS
        },
    )


_OPEN_ORDER_STATUSES: frozenset[str] = frozenset({"open", "partially_filled"})

_RESTORE_SKIP_ERRORS = (ValueError, AccountError, StrategyError, OSError)


async def _cooldown_sleep(seconds: float) -> None:
    """BotManager 재시작/리셋 cooldown 전용 sleep."""

    await asyncio.sleep(seconds)


@dataclasses.dataclass(frozen=True)
class StopCleanup:
    """정지가 정리한 주문: 취소·실패·건너뜀 건수, 만료한 스탑 주문, 조회 실패."""

    cancelled: int = 0
    failed: int = 0
    stop_orders: tuple[StopOrder, ...] = ()
    lookup_failed: bool = False
    skipped: int = 0

    def summary_lines(self) -> list[str]:
        """「봇 중지」·계좌 정지 정리 결과 알림과 텔레그램 응답에 쓰는 줄."""
        lines = [f"미체결 주문 취소: {self.cancelled}건 (실패 {self.failed}건)"]
        if self.skipped:
            lines.append(
                f"취소하지 않고 남긴 열린 주문: {self.skipped}건 "
                "(다른 정리가 취소 중이거나 실행·삭제 중인 봇)"
            )
        if self.lookup_failed:
            lines.append("열린 주문 조회 실패 — 직접 확인 필요")
        lines.append(f"스탑 주문 만료: {len(self.stop_orders)}건")
        lines.extend(
            f"- {o.symbol} {o.side} stop {_format_price(o.stop_price)}"
            for o in self.stop_orders
        )
        return lines


def _format_price(price: float) -> str:
    """천 단위 구분 가격(소수는 끝의 0을 지운다, 지수 표기 없음)."""
    return f"{price:,.4f}".rstrip("0").rstrip(".")


def _tally(cleanup: StopCleanup, outcome: str) -> StopCleanup:
    """취소 요청 하나의 결과(cancelled·failed·skipped·closed)를 더한다."""
    if outcome == "cancelled":
        return dataclasses.replace(cleanup, cancelled=cleanup.cancelled + 1)
    if outcome == "failed":
        return dataclasses.replace(cleanup, failed=cleanup.failed + 1)
    if outcome == "skipped":
        return dataclasses.replace(cleanup, skipped=cleanup.skipped + 1)
    return cleanup


def _cleanup_interrupted(bot: Bot, mark: tuple[BotStatus, int]) -> bool:
    """정리를 시작할 때와 봇의 상태·세대가 다르면(재시작) 경고하고 참."""
    if (bot.status, bot._generation) == mark:
        return False
    logger.warning(
        "봇 정지 주문 정리 중단: %s 정리 도중 재시작 (상태 %s)",
        bot.bot_id,
        bot.status.value,
    )
    return True


class BotManager:
    """봇들의 생명주기를 중앙 관리."""

    def __init__(
        self,
        eventbus: EventBus,
        db: Database,
        context_factory: StrategyContextFactory | None = None,
        signal_key_manager: SignalKeyManager | None = None,
        snapshot: StrategySnapshot | None = None,
        rule_engine: RuleEngine | None = None,
        strategy_rule_configs: dict[str, list[dict[str, Any]]] | None = None,
        account_service: AccountService | None = None,
        treasury_manager: TreasuryManager | None = None,
        trade_service: TradeService | None = None,
        signal_channel_registry: SignalChannelRegistry | None = None,
        order_tracker: OrderTracker | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._db = db
        self._context_factory = context_factory
        self._signal_key_manager = signal_key_manager
        self._snapshot = snapshot
        self._rule_engine = rule_engine
        self._strategy_rule_configs = strategy_rule_configs or {}
        self._account_service = account_service
        self._treasury_manager = treasury_manager
        self._trade_service = trade_service
        self._signal_channel_registry = signal_channel_registry
        self._bots: dict[str, Bot] = {}
        self._suppress_notification_bot_ids: set[str] = set()
        self._restart_counts: dict[str, int] = {}
        self._restart_tasks: dict[str, asyncio.Task[None]] = {}
        self._restart_reset_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_update_locks: dict[str, asyncio.Lock] = {}
        self._bot_signal_locks: dict[str, asyncio.Lock] = {}
        self._deleting_bots: set[Bot] = set()
        self._order_tracker = order_tracker
        self._stop_order_manager: StopOrderManager | None = None
        self._shutting_down = False
        self._last_cleanup: dict[str, StopCleanup] = {}
        self._cancelling_order_ids: dict[str, asyncio.Event] = {}
        self._suspending_bot_ids: set[str] = set()
        self._suspension_cleanups: dict[str, asyncio.Task[None]] = {}
        self._suspension_rerun: dict[str, list[StopOrder]] = {}

    def set_stop_order_manager(self, manager: StopOrderManager) -> None:
        """봇 정지 때 스탑 주문을 만료시킬 ``StopOrderManager`` 를 주입한다."""
        self._stop_order_manager = manager

    def _get_signal_lock(self, bot_id: str) -> asyncio.Lock:
        """``on_step`` ↔ ``on_external_signal`` 직렬화용 per-bot lock(lazy)."""
        return self._bot_signal_locks.setdefault(bot_id, asyncio.Lock())

    def _get_update_lock(self, bot_id: str) -> asyncio.Lock:
        """``update_bot`` 직렬화용 per-bot lock 을 lazy 로 발급한다."""

        return self._bot_update_locks.setdefault(bot_id, asyncio.Lock())

    async def initialize(self) -> None:
        """스키마 생성 + EventBus 구독 + 잔존 스냅샷 정리."""
        await self._db.execute_script(BOT_SCHEMA)
        self._subscribe_events()
        if self._snapshot:
            cleaned = self._snapshot.cleanup_all()
            if cleaned:
                logger.info("잔존 전략 스냅샷 %d건 정리", cleaned)
        logger.info("BotManager 초기화 완료")

    async def load_from_db(self) -> int:
        """DB에서 봇 설정을 읽어 메모리에 로드한다 (테스트용).

        deleted 상태가 아닌 모든 봇을 읽어 stub Bot 인스턴스를 생성한다.
        기존 메모리 상태는 초기화된다. 반환값은 로드된 봇 수.

        ``account_id`` 가 invalid (``""``, ``"default"``, 형식 위반) 인 row
        는 warning 후 skip 한다. ``BotConfig.__post_init__`` 의
        ``require_account_id`` 가 :class:`InvalidAccountIdError` 를 raise
        하므로 read 경로가 실패하지 않도록 본 단계에서 가지치기한다.
        """
        from ante.account.errors import InvalidAccountIdError
        from ante.strategy.base import Signal, Strategy, StrategyMeta

        class _NullStrategy(Strategy):
            meta = StrategyMeta(name="null", version="0.0.0", description="test stub")

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                return []

        class _NullContext:
            def __init__(self, bot_id: str) -> None:
                self.bot_id = bot_id

        self._bots.clear()

        rows = await self._db.fetch_all(
            "SELECT bot_id, name, strategy_id, account_id, config_json, status"
            " FROM bots WHERE status != 'deleted'"
        )

        for row in rows:
            config_data = json.loads(row["config_json"]) if row["config_json"] else {}
            account_id = row.get("account_id") or ""
            try:
                config = _bot_config_from_row(row, config_data)
            except InvalidAccountIdError as e:
                logger.warning(
                    "BotManager.load_from_db: invalid account_id row skip"
                    " (legacy migration 필요): bot_id=%s account_id=%r — %s",
                    row.get("bot_id"),
                    account_id,
                    e,
                )
                continue
            except ValueError as e:
                logger.warning(
                    "BotManager.load_from_db: invalid bot config row skip"
                    " (legacy migration 필요): bot_id=%s config=%r — %s",
                    row.get("bot_id"),
                    config_data,
                    e,
                )
                continue
            bot = Bot(
                config=config,
                strategy_cls=_NullStrategy,
                ctx=_NullContext(config.bot_id),  # type: ignore[arg-type]
                eventbus=self._eventbus,
            )
            status_str = row["status"]
            try:
                bot.status = BotStatus(status_str)
            except ValueError:
                bot.status = BotStatus.CREATED
            self._bots[config.bot_id] = bot

        logger.info("DB에서 봇 %d건 로드", len(self._bots))
        return len(self._bots)

    async def restore_bots(self) -> int:
        """서버 부팅 때 삭제되지 않은 봇을 시작 전 상태(``created``)로 복원한다.

        전략은 ``create_bot`` 과 같은 길로 준비한다. 한 행의 준비가 실패하면
        그 행만 경고 뒤 건너뛰고, 그 밖의 예외는 올린다. 봇을 시작하지 않고
        룰·시그널 키·예산·``bots`` 행을 건드리지 않는다. 반환값은 복원 수.
        """
        factory = self._context_factory
        if factory is None:
            raise BotError("봇 복원에는 context_factory가 필요합니다")
        rows = await self._db.fetch_all(
            "SELECT bot_id, name, strategy_id, account_id, config_json"
            " FROM bots WHERE status != 'deleted' ORDER BY bot_id"
        )
        restored = skipped = 0
        for row in rows:
            if row["bot_id"] in self._bots:
                continue
            try:
                await self._restore_bot(row, factory)
            except _RESTORE_SKIP_ERRORS as e:
                skipped += 1
                logger.warning(
                    "봇 복원 건너뜀: bot_id=%s strategy_id=%s — %s: %s",
                    row["bot_id"],
                    row["strategy_id"],
                    type(e).__name__,
                    e,
                )
                continue
            restored += 1
        logger.info("DB에서 봇 %d건 복원(건너뜀 %d건)", restored, skipped)
        return restored

    async def _restore_bot(self, row: Any, factory: StrategyContextFactory) -> None:
        """``bots`` 행 하나를 ``created`` 봇으로 등록한다(실패하면 흔적 없음)."""
        config_data = json.loads(row["config_json"] or "{}")
        if not isinstance(config_data, dict):
            raise ValueError(f"config_json is not an object: {config_data!r}")
        try:
            config = _bot_config_from_row(row, config_data)
        except TypeError as e:
            raise ValueError(f"invalid bot config: {e}") from e
        account = None
        if self._account_service is not None:
            account = await self._account_service.get(config.account_id)
            if account.status == AccountStatus.DELETED:
                raise AccountDeletedError(f"삭제된 계좌: {config.account_id}")
        try:
            strategy_cls = await self._prepare_strategy(
                config.bot_id,
                account_id=config.account_id,
                strategy_id=config.strategy_id,
            )
            ctx = factory.create(config)
        except _RESTORE_SKIP_ERRORS:
            if self._snapshot is not None:
                self._snapshot.cleanup(config.bot_id)
            raise
        self._register_new_bot(config, strategy_cls, ctx, account)
        logger.info("봇 복원: %s (전략: %s)", config.bot_id, config.strategy_id)

    def _register_new_bot(
        self,
        config: BotConfig,
        strategy_cls: type[Strategy],
        ctx: StrategyContext,
        account: Any,
    ) -> Bot:
        """시작 전 ``Bot`` 을 만들어 이벤트 구독과 봇 목록에 등록한다."""
        bot = Bot(
            config=config,
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=self._eventbus,
            exchange=account.exchange if account else "",
            trading_mode=account.trading_mode.value if account else "",
            currency=account.currency if account else "",
            signal_lock=self._get_signal_lock(config.bot_id),
        )
        self._register_bot_events(bot)
        self._bots[config.bot_id] = bot
        return bot

    def _subscribe_events(self) -> None:
        """시스템 이벤트 구독."""
        from ante.eventbus.events import (
            AccountActivatedEvent,
            AccountSuspendedEvent,
            BotErrorEvent,
            BotStartedEvent,
            BotStopEvent,
            BotStoppedEvent,
        )

        self._eventbus.subscribe(BotStopEvent, self._on_bot_stop_request)
        self._eventbus.subscribe(AccountSuspendedEvent, self._on_account_suspended)
        self._eventbus.subscribe(AccountActivatedEvent, self._on_account_activated)
        self._eventbus.subscribe(BotErrorEvent, self._on_bot_error)
        self._eventbus.subscribe(BotStartedEvent, self._on_bot_started)
        self._eventbus.subscribe(BotStoppedEvent, self._on_bot_stopped)

    async def is_bot_id_taken(self, bot_id: str) -> bool:
        """봇 생성이 이 id 를 거부하는가.

        메모리에 있거나 ``deleted`` 행으로 남은 id 면 참이다.
        """
        return bot_id in self._bots or await self._is_deleted_bot_id(bot_id)

    async def _is_deleted_bot_id(self, bot_id: str) -> bool:
        """``bots`` 에 이 id 의 ``deleted`` 행이 있는가."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM bots WHERE bot_id = ? AND status = 'deleted'",
            (bot_id,),
        )
        return row is not None

    async def create_bot(
        self,
        config: BotConfig,
        strategy_cls: type[Strategy],
        ctx: StrategyContext | None = None,
        source_path: Path | None = None,
    ) -> Bot:
        """봇 생성.

        ctx가 주입되면 그대로 사용하고, None이면 context_factory로 자동 생성한다.
        source_path가 주어지면 전략 파일을 스냅샷으로 복사하여 보호한다.
        """
        config.account_id = require_account_id(
            config.account_id, context="BotManager.create_bot"
        )
        validate_interval(config.interval_seconds)
        validate_runtime_controls(
            max_restart_attempts=config.max_restart_attempts,
            restart_cooldown_seconds=config.restart_cooldown_seconds,
            step_timeout_seconds=config.step_timeout_seconds,
            max_signals_per_step=config.max_signals_per_step,
        )

        if config.bot_id in self._bots:
            raise BotAlreadyExistsError(f"Bot already exists: {config.bot_id}")
        if await self._is_deleted_bot_id(config.bot_id):
            raise BotAlreadyExistsError(
                f"Bot already exists (deleted): {config.bot_id}"
            )

        active_statuses = {BotStatus.RUNNING, BotStatus.STOPPING}
        for existing_bot in self._bots.values():
            if (
                existing_bot.config.strategy_id == config.strategy_id
                and existing_bot.status in active_statuses
            ):
                raise BotStrategyAlreadyRunningError(
                    f"전략 '{config.strategy_id}'은(는) 이미 봇 "
                    f"'{existing_bot.bot_id}'에서 사용 중입니다. "
                    f"파라미터가 다른 전략은 별도 파일로 작성하세요."
                )

        account = None
        if self._account_service:
            from ante.account.errors import (
                AccountDeletedException,
                AccountSuspendedError,
            )
            from ante.account.models import AccountStatus

            account = await self._account_service.get(config.account_id)

            if account.status == AccountStatus.DELETED:
                raise AccountDeletedException(
                    f"삭제된 계좌 '{config.account_id}'에는 봇을 생성할 수 없습니다."
                )
            if account.status == AccountStatus.SUSPENDED:
                raise AccountSuspendedError(
                    f"정지된 계좌 '{config.account_id}'에는 봇을 생성할 수 없습니다."
                )

        if account and hasattr(strategy_cls, "meta"):
            strategy_exchange = getattr(strategy_cls.meta, "exchange", "KRX")
            strategy_name = getattr(strategy_cls.meta, "name", config.strategy_id)

            from ante.strategy.validator import validate_exchange

            validate_exchange(
                strategy_exchange=strategy_exchange,
                account_exchange=account.exchange,
                strategy_name=strategy_name,
                account_name=account.name,
            )

        if self._snapshot and source_path:
            from ante.strategy.loader import StrategyLoader

            snapshot_path = self._snapshot.create(config.bot_id, source_path)
            strategy_cls = StrategyLoader.load(snapshot_path)
            logger.info(
                "스냅샷에서 전략 로드: %s → %s",
                source_path,
                snapshot_path,
            )

        if ctx is None:
            if self._context_factory is None:
                msg = "ctx 또는 context_factory 중 하나는 필수입니다"
                raise BotError(msg)
            ctx = self._context_factory.create(config)

        bot = self._register_new_bot(config, strategy_cls, ctx, account)
        await self._save_bot_config(config)

        if (
            self._signal_key_manager
            and hasattr(strategy_cls, "meta")
            and getattr(strategy_cls.meta, "accepts_external_signals", False)
        ):
            signal_key = await self._signal_key_manager.generate(config.bot_id)
            logger.info(
                "시그널 키 자동 발급: bot=%s key=%s...",
                config.bot_id,
                signal_key[:8],
            )

        logger.info("봇 생성: %s (전략: %s)", config.bot_id, config.strategy_id)
        return bot

    async def update_bot(self, bot_id: str, **kwargs: Any) -> Bot:
        """봇 설정 수정. 중지 상태에서만 허용.

        budget이 변경되면 TreasuryManager를 통해 예산을 조정한다.

        Args:
            **kwargs: 변경할 설정 필드 (None 값은 무시).

        Raises:
            BotError: 봇이 중지 상태가 아닌 경우.
        """
        async with self._get_update_lock(bot_id):
            bot = self._get_bot(bot_id)
            allowed_statuses = {
                BotStatus.CREATED,
                BotStatus.STOPPED,
                BotStatus.ERROR,
            }
            if bot.status not in allowed_statuses:
                raise BotError(
                    f"봇 설정은 중지 상태에서만 수정할 수 있습니다: {bot_id} "
                    f"(현재: {bot.status})"
                )

            new_budget = kwargs.pop("budget", None)

            updates = {k: v for k, v in kwargs.items() if v is not None}

            if not updates and new_budget is None:
                return bot

            new_account_id = updates.get("account_id")
            if new_account_id is not None and new_account_id != bot.config.account_id:
                raise BotImmutableFieldError(
                    "account_id 는 생성 후 변경할 수 없습니다 (treasury 예산·"
                    "broker credential·포지션이 account-bound). 변경하려면 봇을 "
                    f"삭제한 뒤 새 bot_id로 다시 만드세요: {bot_id} "
                    f"(현재: {bot.config.account_id}, 요청: {new_account_id})"
                )

            old_config = bot.config
            effective_account_id = updates.get("account_id", old_config.account_id)
            new_strategy_id = updates.get("strategy_id")
            new_strategy_cls = None
            if (
                new_strategy_id is not None
                and new_strategy_id != old_config.strategy_id
            ):
                new_strategy_cls = await self._prepare_strategy(
                    bot_id,
                    account_id=effective_account_id,
                    strategy_id=new_strategy_id,
                )

            config_fields = {
                "bot_id": old_config.bot_id,
                "strategy_id": old_config.strategy_id,
                "name": old_config.name,
                "account_id": old_config.account_id,
                "interval_seconds": old_config.interval_seconds,
                "auto_restart": old_config.auto_restart,
                "max_restart_attempts": old_config.max_restart_attempts,
                "restart_cooldown_seconds": old_config.restart_cooldown_seconds,
                "step_timeout_seconds": old_config.step_timeout_seconds,
                "max_signals_per_step": old_config.max_signals_per_step,
            }
            config_fields.update(updates)
            new_config = BotConfig(**config_fields)  # type: ignore[arg-type]
            self._require_registered(bot)
            old_strategy_cls = bot._strategy_cls
            if new_strategy_cls is not None:
                bot.rebind_strategy(new_config.strategy_id, new_strategy_cls)
            bot.config = new_config

            committed_snapshot = dataclasses.replace(new_config)

            try:
                await self._save_bot_config(new_config)
            except (Exception, asyncio.CancelledError):
                if (
                    new_strategy_cls is not None
                    and bot.config is new_config
                    and self._restore_strategy(
                        bot, old_config.strategy_id, old_strategy_cls
                    )
                ):
                    bot.config = old_config
                raise

            if new_budget is not None:
                self._require_registered(bot)
                try:
                    from ante.treasury.exceptions import TreasuryNotConfiguredError

                    if self._treasury_manager is None:
                        raise TreasuryNotConfiguredError(
                            "treasury manager not configured"
                        )
                    try:
                        treasury = self._treasury_manager.get(new_config.account_id)
                    except KeyError as ke:
                        raise TreasuryNotConfiguredError(
                            f"treasury not configured for account "
                            f"{new_config.account_id}"
                        ) from ke
                    await treasury.update_budget(bot_id, new_budget)
                except (Exception, asyncio.CancelledError):
                    if bot.config is new_config and bot.config == committed_snapshot:
                        if new_strategy_cls is None or self._restore_strategy(
                            bot, old_config.strategy_id, old_strategy_cls
                        ):
                            await self._rollback_update(bot, old_config)
                    elif bot.config is not new_config:
                        logger.warning(
                            "update_bot rollback skipped for bot_id=%s: "
                            "concurrent update detected (bot.config is not "
                            "this request's new_config).",
                            bot_id,
                        )
                    else:
                        logger.warning(
                            "rollback skipped: bot.config mutated in-place "
                            "after commit (bot_id=%s).",
                            bot_id,
                        )
                    raise

            logger.info("봇 설정 수정: %s (변경: %s)", bot_id, list(updates.keys()))
            return bot

    async def assign_strategy(self, bot_id: str, strategy_id: str) -> None:
        """봇에 전략 배정.

        running 상태이면 중지 후 전략을 교체하고 재시작한다.

        전략 ID 를 ``bot.config`` (런타임) 와 DB 에 동시에 반영한다. DB
        저장은 ``_save_bot_config(bot.config)`` 로 수행하여 ``bots.strategy_id``
        컬럼과 ``config_json.strategy_id`` 를 항상 일관되게 갱신한다.
        running 봇의 lifecycle 순서 (stop → old rule unload →
        persist → new rule load → start) 는 그대로 보존한다.
        """
        bot = self._get_bot(bot_id)
        strategy_cls = await self._prepare_strategy(
            bot_id, account_id=bot.config.account_id, strategy_id=strategy_id
        )
        was_running = bot.status == BotStatus.RUNNING

        if was_running:
            await self._stop_and_remove_rules(bot)

        await self._rebind_and_save(bot, strategy_id, strategy_cls)

        if was_running:
            self._require_registered(bot)
            self._load_strategy_rules(strategy_id)
            await bot.start()

        logger.info(
            "전략 배정: bot=%s strategy=%s (재시작=%s)",
            bot_id,
            strategy_id,
            was_running,
        )

    async def change_strategy(self, bot_id: str, strategy_id: str) -> None:
        """중지 상태 봇의 전략 교체.

        running 상태이면 예외를 발생시킨다.
        stopped/created/error 상태에서만 전략 ID와 실행 코드를 교체한다.
        """
        bot = self._get_bot(bot_id)
        if bot.status == BotStatus.RUNNING:
            raise BotError(
                f"실행 중인 봇의 전략은 변경할 수 없습니다: {bot_id}. "
                f"assign_strategy()를 사용하거나 먼저 봇을 중지하세요."
            )

        strategy_cls = await self._prepare_strategy(
            bot_id, account_id=bot.config.account_id, strategy_id=strategy_id
        )
        await self._rebind_and_save(bot, strategy_id, strategy_cls)

        logger.info("전략 교체: bot=%s strategy=%s", bot_id, strategy_id)

    async def resume_bot(self, bot_id: str) -> None:
        """중지/에러 상태 봇 재시작.

        에러 카운터를 리셋하고 봇을 시작한다.
        running 상태이면 예외를 발생시킨다.
        """
        bot = self._get_bot(bot_id)
        self._require_registered(bot)
        if bot.status == BotStatus.RUNNING:
            raise BotError(f"이미 실행 중인 봇입니다: {bot_id}")

        if bot.status not in (BotStatus.STOPPED, BotStatus.ERROR):
            raise BotError(f"재개할 수 없는 상태입니다: {bot_id} (현재: {bot.status})")

        self._restart_counts.pop(bot_id, None)
        bot.error_message = None

        self._load_strategy_rules(bot.config.strategy_id)
        await bot.start()
        logger.info("봇 재개: %s", bot_id)

    async def start_bot(self, bot_id: str) -> None:
        """봇 시작. 전략별 룰이 설정되어 있으면 RuleEngine에 로드.

        이미 ``RUNNING`` 상태인 봇에 대한 중복 호출은 ``BotStateConflict`` 로
        거부한다 (IPC envelope: ``BOT_STATE_CONFLICT``). ``resume_bot`` 의
        status 체크 + raise 패턴과 동형이며, ``BotStateConflict`` 는
        ``BotError`` 서브클래스이므로 기존 ``except BotError`` 호출자 (IPC
        handler) 는 자연스럽게 ``BOT_STATE_CONFLICT`` envelope 으로 매핑
        된다.
        """
        bot = self._get_bot(bot_id)
        self._require_registered(bot)
        if bot.status == BotStatus.RUNNING:
            raise BotStateConflict(
                f"이미 실행 중인 봇입니다: {bot_id} (상태: {bot.status.value})"
            )
        self._load_strategy_rules(bot.config.strategy_id)
        await bot.start()

    async def stop_bot(
        self, bot_id: str, *, suppress_notification: bool = False
    ) -> StopCleanup | None:
        """봇 중지. 전략별 룰을 RuleEngine에서 제거하고 주문 정리 결과를 돌려준다.

        suppress_notification이 True이면 BotStoppedEvent에 의한
        NotificationEvent 발행을 1회 억제한다(주문 정리는 그대로 한다).
        ``RUNNING`` / ``ERROR`` 가 아닌 상태에서의 중복 호출은
        ``BotStateConflict`` 로 거부한다. 정리를 건너뛰었으면 ``None``.
        """
        bot = self._get_bot(bot_id)
        if bot.status not in (BotStatus.RUNNING, BotStatus.ERROR):
            raise BotStateConflict(
                f"중지할 수 없는 상태입니다: {bot_id} (현재: {bot.status.value})"
            )
        if suppress_notification:
            self._suppress_notification_bot_ids.add(bot_id)
        self._last_cleanup.pop(bot_id, None)
        await self._stop_and_remove_rules(bot)
        return self._last_cleanup.pop(bot_id, None)

    async def delete_bot(
        self,
        bot_id: str,
        handle_positions: str = "keep",
        hard: bool = False,
    ) -> None:
        """봇 삭제. 실행 중이면 먼저 중지.

        Args:
            handle_positions: 포지션 처리 방식.
                - ``keep`` (기본): 포지션을 유지한 채 봇만 삭제.
                - ``liquidate``: 보유 종목 시장가 매도 주문 발행 후 삭제.
            hard: ``True`` 이면 ``DELETE FROM bots`` 로 row 자체를 삭제한다.
                기본 ``False`` 는 기존 soft delete 거동 (``status='deleted'``)
                을 유지한다.
        """
        if handle_positions not in ("keep", "liquidate"):
            raise BotError(
                f"잘못된 handle_positions 값: {handle_positions!r} "
                f"(허용: keep, liquidate)"
            )

        bot = self._get_bot(bot_id)
        self._deleting_bots.add(bot)
        try:
            reg = self._signal_channel_registry
            if reg is not None:
                reg.close_bot(bot_id, "deleted")
            if bot.status == BotStatus.RUNNING:
                await bot.stop()
            elif bot.status in (BotStatus.CREATED, BotStatus.STOPPED, BotStatus.ERROR):
                await self._cancel_bot_orders(bot)
            self._last_cleanup.pop(bot_id, None)

            if handle_positions == "liquidate":
                await self._liquidate_positions(bot)

            self._unregister_bot_events(bot)

            if self._context_factory and self._context_factory._virtual_executor:
                self._context_factory._virtual_executor.unregister_bot(bot_id)

            if self._signal_key_manager:
                await self._signal_key_manager.revoke(bot_id)

            if self._snapshot:
                self._snapshot.cleanup(bot_id)

            if self._treasury_manager:
                released = 0.0
                try:
                    treasury = self._treasury_manager.get(bot.config.account_id)
                    released = await treasury.release_budget(bot_id)
                except KeyError:
                    pass
                if released == 0.0:
                    for t in self._treasury_manager.list_all():
                        released = await t.release_budget(bot_id)
                        if released > 0:
                            break
                if released > 0:
                    logger.info(
                        "봇 삭제 시 예산 환수: %s -- %s",
                        bot_id,
                        f"{released:,.0f}",
                    )

            deleted = _transition_status(bot, BotStatus.DELETED)
            del self._bots[bot_id]
            if hard:
                await self._db.execute(
                    "DELETE FROM bots WHERE bot_id = ?",
                    (bot_id,),
                )
                logger.info("봇 삭제 (hard delete): %s", bot_id)
            else:
                await self._db.execute(
                    "UPDATE bots SET status = ?, updated_at = datetime('now')"
                    " WHERE bot_id = ?",
                    (deleted.value, bot_id),
                )
                logger.info("봇 삭제 (soft delete): %s", bot_id)
            self._cancel_restart_tasks(bot_id)
            self._restart_counts.pop(bot_id, None)
        finally:
            self._deleting_bots.discard(bot)

    async def remove_bot(
        self,
        bot_id: str,
        handle_positions: str = "keep",
        hard: bool = False,
    ) -> None:
        """봇 삭제. delete_bot()의 별칭 (하위 호환)."""
        await self.delete_bot(bot_id, handle_positions=handle_positions, hard=hard)

    async def _liquidate_positions(self, bot: Bot) -> None:
        """봇의 보유 포지션에 대해 시장가 매도 주문을 발행한다."""
        if not self._trade_service:
            logger.warning(
                "TradeService 미설정 — 포지션 청산 건너뜀: bot=%s",
                bot.bot_id,
            )
            return

        from ante.account.gate import LIQUIDATION_REASON_PREFIX
        from ante.eventbus.events import OrderRequestEvent

        account_id = bot.config.account_id
        positions = await self._trade_service.get_positions(
            bot_id=bot.bot_id, account_id=account_id
        )

        open_positions: list[Any] = []
        for p in positions:
            if p.quantity <= 0:
                continue
            pos_account_id = getattr(p, "account_id", None)
            if pos_account_id != account_id:
                logger.warning(
                    "청산 대상 제외 (계좌 불일치): bot=%s symbol=%s "
                    "pos_account_id=%r bot_account_id=%r",
                    bot.bot_id,
                    getattr(p, "symbol", None),
                    pos_account_id,
                    account_id,
                )
                continue
            open_positions.append(p)

        if not open_positions:
            logger.info("청산 대상 포지션 없음: bot=%s", bot.bot_id)
            return

        for pos in open_positions:
            event = OrderRequestEvent(
                account_id=account_id,
                bot_id=bot.bot_id,
                strategy_id=bot.config.strategy_id,
                symbol=pos.symbol,
                side="sell",
                quantity=pos.quantity,
                order_type="market",
                reason=f"{LIQUIDATION_REASON_PREFIX} 봇 삭제 청산 (bot={bot.bot_id})",
                exchange=getattr(pos, "exchange", "KRX"),
            )
            await self._eventbus.publish(event)
            logger.info(
                "청산 주문 발행: bot=%s symbol=%s qty=%.4f",
                bot.bot_id,
                pos.symbol,
                pos.quantity,
            )

        logger.info(
            "봇 삭제 청산 주문 %d건 발행 완료: bot=%s",
            len(open_positions),
            bot.bot_id,
        )

    async def stop_all(self) -> None:
        """모든 봇 중지. 서버 종료이므로 미체결 주문을 취소하지 않는다.

        진행 중인 계좌 정지의 주문 정리는 취소하고 끝나기를 기다린다.
        """
        self._shutting_down = True
        cleanups = list(self._suspension_cleanups.values())
        for task in [*cleanups, *self._restart_tasks.values()]:
            task.cancel()
        for task in list(self._restart_reset_tasks.values()):
            task.cancel()
        self._restart_tasks.clear()
        self._restart_reset_tasks.clear()
        if cleanups:
            await asyncio.gather(*cleanups, return_exceptions=True)

        tasks = [
            bot.stop() for bot in self._bots.values() if bot.status == BotStatus.RUNNING
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("전체 봇 중지 완료")

    def list_bots(self) -> list[dict[str, Any]]:
        """봇 목록 조회."""
        return [bot.get_info() for bot in self._bots.values()]

    def get_bot(self, bot_id: str) -> Bot | None:
        """봇 조회. 없으면 None."""
        return self._bots.get(bot_id)

    def _get_bot(self, bot_id: str) -> Bot:
        """봇 조회. 없으면 예외."""
        bot = self._bots.get(bot_id)
        if bot is None:
            raise BotNotFoundError(bot_id)
        return bot

    def _is_registered(self, bot: Bot) -> bool:
        """삭제 중이 아니고 목록에 그대로 있는 봇인지 돌려준다."""
        return bot not in self._deleting_bots and self._bots.get(bot.bot_id) is bot

    def _require_registered(self, bot: Bot) -> None:
        """삭제 중이거나 목록에서 빠진 봇이면 ``BotNotFoundError``를 올린다."""
        if not self._is_registered(bot):
            raise BotNotFoundError(bot.bot_id)

    def _cancel_restart_tasks(self, bot_id: str) -> None:
        """봇의 예약된 재시작·카운터 리셋 태스크를 취소하고 목록에서 뺀다."""
        for tasks in (self._restart_tasks, self._restart_reset_tasks):
            task = tasks.pop(bot_id, None)
            if task is not None:
                task.cancel()

    async def _prepare_strategy(
        self, bot_id: str, *, account_id: str, strategy_id: str
    ) -> type[Strategy]:
        """전략을 조회·로드·거래소 검사한 뒤 스냅샷에서 로드한 클래스를 돌려준다."""
        from ante.strategy.registry import StrategyRegistry

        registry = StrategyRegistry(self._db)
        await registry.initialize()
        record = await registry.get(strategy_id)
        if record is None:
            from ante.strategy.exceptions import StrategyNotFoundError

            raise StrategyNotFoundError(f"전략 미발견: {strategy_id}")

        from ante.strategy.loader import StrategyLoader
        from ante.strategy.validator import validate_exchange

        source_path = Path(record.filepath)
        strategy_cls = StrategyLoader.load(source_path)

        if self._account_service is not None:
            account = await self._account_service.get(account_id)
            strategy_exchange = getattr(
                getattr(strategy_cls, "meta", None), "exchange", "KRX"
            )
            strategy_name = getattr(
                getattr(strategy_cls, "meta", None), "name", strategy_id
            )
            validate_exchange(
                strategy_exchange=strategy_exchange,
                account_exchange=account.exchange,
                strategy_name=strategy_name,
                account_name=account.name,
            )

        if self._snapshot is None:
            return strategy_cls
        return StrategyLoader.load(self._snapshot.create(bot_id, source_path))

    async def _rebind_and_save(
        self, bot: Bot, strategy_id: str, strategy_cls: type[Strategy]
    ) -> None:
        """봇에 전략을 묶고 저장한다. 저장이 실패하면 옛 전략으로 되돌린다."""
        self._require_registered(bot)
        old_strategy_id = bot.config.strategy_id
        old_strategy_cls = bot._strategy_cls
        bot.rebind_strategy(strategy_id, strategy_cls)
        bot.config.strategy_id = strategy_id
        try:
            await self._save_bot_config(bot.config)
        except (Exception, asyncio.CancelledError):
            if self._restore_strategy(bot, old_strategy_id, old_strategy_cls):
                bot.config.strategy_id = old_strategy_id
            raise

    async def _rollback_update(self, bot: Bot, old_config: BotConfig) -> None:
        """``update_bot``의 메모리 설정을 되돌리고 DB에도 옛 설정을 저장한다."""
        bot.config = old_config
        if self._bots.get(bot.bot_id) is not bot:
            logger.warning(
                "update_bot rollback DB save skipped for "
                "bot_id=%s: bot instance no longer in manager "
                "(delete/recreate race).",
                bot.bot_id,
            )
            return
        try:
            await self._save_bot_config(old_config)
        except Exception:
            logger.exception(
                "update_bot rollback DB save failed for "
                "bot_id=%s; memory was rolled back but DB "
                "may diverge.",
                bot.bot_id,
            )

    def _restore_strategy(
        self, bot: Bot, strategy_id: str, strategy_cls: type[Strategy]
    ) -> bool:
        """옛 전략으로 되돌린다. 그 사이 봇이 시작됐으면 되돌리지 않고 False."""
        try:
            bot.rebind_strategy(strategy_id, strategy_cls)
        except BotStateConflict:
            logger.warning(
                "전략 되돌림 생략: 봇 %s가 그 사이 시작됨 (설정·실행 코드는 %s)",
                bot.bot_id,
                bot.config.strategy_id,
            )
            return False
        return True

    def _load_strategy_rules(self, strategy_id: str) -> None:
        """설정에서 전략별 룰을 RuleEngine에 로드."""
        if not self._rule_engine:
            return
        rule_configs = self._strategy_rule_configs.get(strategy_id)
        if rule_configs:
            self._rule_engine.load_strategy_rules_from_config(strategy_id, rule_configs)
            logger.info(
                "전략별 룰 로드: strategy=%s (%d건)", strategy_id, len(rule_configs)
            )

    def _remove_strategy_rules(self, strategy_id: str) -> None:
        """RuleEngine에서 전략별 룰 제거."""
        if not self._rule_engine:
            return
        self._rule_engine.remove_strategy_rules(strategy_id)

    async def _stop_and_remove_rules(self, bot: Bot) -> None:
        """봇을 중지하고, 중지가 예외를 내도 전략별 룰을 제거한다."""
        try:
            await bot.stop()
        finally:
            self._remove_strategy_rules(bot.config.strategy_id)

    async def _on_bot_stop_request(self, event: object) -> None:
        """BotStopEvent 수신 시 해당 봇 중지."""
        from ante.eventbus.events import BotStopEvent

        if not isinstance(event, BotStopEvent):
            return
        if event.bot_id in self._bots:
            try:
                await self.stop_bot(event.bot_id)
            except BotStateConflict:
                return

    async def _on_account_suspended(self, event: object) -> None:
        """계좌 정지: 봇 중지·스탑 만료 뒤 열린 주문의 정리를 백그라운드로 띄운다."""
        from ante.eventbus.events import AccountSuspendedEvent

        if not isinstance(event, AccountSuspendedEvent):
            return
        account_id = event.account_id
        expired: list[StopOrder] = []
        try:
            stopped = []
            for bot in list(self._bots.values()):
                if bot.config.account_id != account_id:
                    continue
                try:
                    if await self._suspend_bot(bot, expired):
                        stopped.append(bot.bot_id)
                except Exception:
                    logger.exception(
                        "계좌 정지 — 봇 처리 중 예외: account=%s, bot=%s",
                        account_id,
                        bot.bot_id,
                    )
            if stopped:
                logger.warning(
                    "계좌 정지 — 봇 %d개 중지: account=%s, bots=%s",
                    len(stopped),
                    account_id,
                    stopped,
                )
        finally:
            self._schedule_suspension_cleanup(account_id, expired)

    async def _suspend_bot(self, bot: Bot, expired: list[StopOrder]) -> bool:
        """재시작 취소 → 실행 중이면 표시를 붙여 정지 → 스탑 만료. 정지했으면 참."""
        restart = self._restart_tasks.pop(bot.bot_id, None)
        if restart is not None:
            restart.cancel()
        was_running = bot.status == BotStatus.RUNNING
        if was_running:
            self._last_cleanup.pop(bot.bot_id, None)
            self._suspending_bot_ids.add(bot.bot_id)
            try:
                await bot.stop()
            except Exception:
                logger.exception(
                    "계좌 정지 — 봇 중지 중 예외: account=%s, bot=%s",
                    bot.config.account_id,
                    bot.bot_id,
                )
            finally:
                self._suspending_bot_ids.discard(bot.bot_id)
            marked = self._last_cleanup.pop(bot.bot_id, None)
            if marked is not None:
                expired.extend(marked.stop_orders)
        if bot.status != BotStatus.RUNNING and bot not in self._deleting_bots:
            expired.extend(await self._expire_bot_orders(bot, "account_suspended"))
        return was_running

    def _schedule_suspension_cleanup(
        self, account_id: str, expired: list[StopOrder]
    ) -> None:
        """계좌의 정리 태스크를 띄운다(살아 있으면 끝난 뒤 한 번 더 돌게 한다)."""
        if self._shutting_down:
            return
        task = self._suspension_cleanups.get(account_id)
        if task is not None and not task.done():
            self._suspension_rerun.setdefault(account_id, []).extend(expired)
            return
        self._suspension_cleanups[account_id] = asyncio.create_task(
            self._run_suspension_cleanup(account_id, expired),
            name=f"suspension-cleanup-{account_id}",
        )

    async def _run_suspension_cleanup(
        self, account_id: str, expired: list[StopOrder]
    ) -> None:
        """정리 태스크 본문: 회차마다 돌고, 그 사이 정지가 예약한 재실행만 더 돈다."""
        task = asyncio.current_task()
        try:
            while True:
                await self._sweep_round(account_id, expired)
                if self._shutting_down or account_id not in self._suspension_rerun:
                    return
                expired = self._suspension_rerun.pop(account_id)
        finally:
            if self._suspension_cleanups.get(account_id) is task:
                del self._suspension_cleanups[account_id]
            self._suspension_rerun.pop(account_id, None)

    async def _sweep_round(self, account_id: str, expired: list[StopOrder]) -> None:
        """정리 한 회차와 결과 알림. 예외는 로그와 critical 알림(취소는 다시 올린다)."""
        try:
            cleanup = await self._sweep_account(account_id, tuple(expired))
            await self._notify_sweep(account_id, cleanup)
        except asyncio.CancelledError:
            logger.warning("계좌 정지 — 주문 정리 취소: account=%s", account_id)
            raise
        except Exception:
            logger.exception("계좌 정지 — 주문 정리 실패: account=%s", account_id)
            await self._notify_cleanup_failure(account_id)

    async def _sweep_account(
        self, account_id: str, expired: tuple[StopOrder, ...]
    ) -> StopCleanup:
        """계좌의 열린 주문마다 취소를 요청한다(실행·삭제 중인 봇의 주문은 건너뛴다)."""
        cleanup = StopCleanup(stop_orders=expired)
        tracker = self._order_tracker
        if tracker is None:
            return cleanup
        try:
            records = await tracker.get_open_orders(account_id)
        except Exception:
            logger.exception("계좌 정지 — 열린 주문 조회 실패: account=%s", account_id)
            return dataclasses.replace(cleanup, lookup_failed=True)
        for record in records:
            if self._sweep_skips(record):
                cleanup = _tally(cleanup, "skipped")
                continue
            outcome = await self._request_cancel(
                record, "account_suspended", skip=self._sweep_skips
            )
            cleanup = _tally(cleanup, outcome)
        logger.info(
            "계좌 정지 주문 정리: account=%s 취소 %d건, 실패 %d건, 건너뜀 %d건",
            account_id,
            cleanup.cancelled,
            cleanup.failed,
            cleanup.skipped,
        )
        return cleanup

    def _sweep_skips(self, record: OrderTrackerRecord) -> bool:
        """계좌 정지 정리가 건너뛰는 주문(봇이 실행 중이거나 삭제 중)인지."""
        bot = self._bots.get(record.bot_id)
        return bot is not None and (
            bot.status == BotStatus.RUNNING or bot in self._deleting_bots
        )

    async def _notify_sweep(self, account_id: str, cleanup: StopCleanup) -> None:
        """계좌 정지 정리 결과 알림 한 건(정리할 것이 없었으면 내지 않는다)."""
        if cleanup == StopCleanup():
            return
        warn = cleanup.failed or cleanup.skipped or cleanup.lookup_failed
        await self._eventbus.publish(
            NotificationEvent(
                level="warning" if warn else "info",
                title="계좌 정지 — 주문 정리 결과",
                message="\n".join([f"계좌 `{account_id}`", *cleanup.summary_lines()]),
                category="system",
            )
        )

    async def _notify_cleanup_failure(self, account_id: str) -> None:
        """정리 실패의 critical 알림(발행이 실패하면 로그만 남긴다)."""
        try:
            await self._eventbus.publish(
                NotificationEvent(
                    level="critical",
                    title="계좌 정지 — 주문 정리 실패, 직접 확인 필요",
                    message=(
                        f"계좌 `{account_id}`\n"
                        "열린 주문 정리가 예외로 끝났습니다. "
                        "남은 미체결 주문을 직접 확인하세요."
                    ),
                    category="system",
                )
            )
        except Exception:
            logger.exception("계좌 정지 — 정리 실패 알림 발행 실패: %s", account_id)

    async def _on_account_activated(self, event: object) -> None:
        """계좌 활성화 시 로깅만 수행 (자동 재시작 안 함)."""
        from ante.eventbus.events import AccountActivatedEvent

        if not isinstance(event, AccountActivatedEvent):
            return
        logger.info("계좌 활성화: account=%s", event.account_id)

    async def _on_bot_started(self, event: object) -> None:
        """봇 시작 알림 발행."""
        from ante.eventbus.events import BotStartedEvent, NotificationEvent

        if not isinstance(event, BotStartedEvent):
            return
        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="봇 시작",
                message=f"봇 `{event.bot_id}` 실행 시작",
                category="bot",
            )
        )

    async def _on_bot_stopped(self, event: object) -> None:
        """주문 정리 → 시그널 채널 닫기 → 봇 중지 알림(억제 시 알림만 생략)."""
        from ante.eventbus.events import BotStoppedEvent, NotificationEvent

        if not isinstance(event, BotStoppedEvent):
            return
        cleanup = None
        try:
            if not self._shutting_down:
                cleanup = await self._cleanup_stopped(event)
        finally:
            reg = self._signal_channel_registry
            if reg is not None:
                reg.close_bot(event.bot_id, "bot_stopped")
            suppressed = event.bot_id in self._suppress_notification_bot_ids
            self._suppress_notification_bot_ids.discard(event.bot_id)
        if suppressed:
            return
        lines = [f"봇 `{event.bot_id}` 중지 완료"]
        if cleanup is not None:
            lines.extend(cleanup.summary_lines())
        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="봇 중지",
                message="\n".join(lines),
                category="bot",
            )
        )

    async def _cleanup_stopped(self, event: Any) -> StopCleanup | None:
        """STOPPED 인 봇의 주문을 정리하고 결과를 남긴다(재시작됐으면 건너뛴다)."""
        bot = self._bots.get(event.bot_id)
        if bot is None:
            return None
        if bot.status != BotStatus.STOPPED:
            logger.warning(
                "봇 정지 주문 정리 건너뜀: %s 상태 %s (정리 전 재시작)",
                bot.bot_id,
                bot.status.value,
            )
            return None
        if bot.bot_id in self._suspending_bot_ids:
            expired = await self._expire_bot_orders(bot, "account_suspended")
            self._last_cleanup[bot.bot_id] = StopCleanup(stop_orders=tuple(expired))
            return None
        cleanup = await self._cancel_bot_orders(bot)
        self._last_cleanup[bot.bot_id] = cleanup
        return cleanup

    async def _cancel_bot_orders(self, bot: Bot) -> StopCleanup:
        """대기 액션 폐기 → 스탑 주문 만료 → 열린 주문 취소(재시작되면 멈춘다)."""
        mark = (bot.status, bot._generation)
        expired = await self._expire_bot_orders(bot, "bot_stopped")
        cleanup = StopCleanup(stop_orders=tuple(expired))
        if self._stop_order_manager is not None and _cleanup_interrupted(bot, mark):
            return cleanup
        if self._order_tracker is not None:
            cleanup = await self._cancel_open_orders(bot, mark, cleanup)
        logger.info(
            "봇 정지 주문 정리: %s 취소 %d건, 실패 %d건, 스탑 만료 %d건",
            bot.bot_id,
            cleanup.cancelled,
            cleanup.failed,
            len(cleanup.stop_orders),
        )
        return cleanup

    async def _expire_bot_orders(self, bot: Bot, reason: str) -> list[StopOrder]:
        """봇의 대기 액션을 버리고 활성 스탑 주문을 만료시킨다."""
        dropped = bot._ctx._drain_actions()
        if dropped:
            logger.warning(
                "봇 정지 — 대기 액션 %d건 버림: %s", len(dropped), bot.bot_id
            )
        if self._stop_order_manager is None:
            return []
        return await self._stop_order_manager.expire_for_bot(bot.bot_id, reason)

    async def _cancel_open_orders(
        self, bot: Bot, mark: tuple[BotStatus, int], cleanup: StopCleanup
    ) -> StopCleanup:
        """추적기의 그 봇 열린 주문마다 취소를 요청하고 결과를 센다."""
        tracker = self._order_tracker
        assert tracker is not None
        try:
            records = await tracker.get_open_orders(bot.config.account_id)
        except Exception:
            logger.exception("봇 정지 — 열린 주문 조회 실패: %s", bot.bot_id)
            return dataclasses.replace(cleanup, lookup_failed=True)
        for record in [r for r in records if r.bot_id == bot.bot_id]:
            if _cleanup_interrupted(bot, mark):
                break
            outcome = await self._request_cancel(
                record, "bot_stopped", wait=bot in self._deleting_bots
            )
            cleanup = _tally(cleanup, outcome)
        return cleanup

    async def _request_cancel(
        self,
        record: OrderTrackerRecord,
        reason: str,
        skip: Callable[[OrderTrackerRecord], bool] | None = None,
        *,
        wait: bool = False,
    ) -> str:
        """취소 요청의 유일한 출구: 진행 중(wait면 한 번 기다린 뒤)·skip이면 skipped."""
        order_id = record.order_id
        in_flight = self._cancelling_order_ids.get(order_id)
        if in_flight is not None and wait:
            await in_flight.wait()
            in_flight = self._cancelling_order_ids.get(order_id)
        if in_flight is not None:
            return "skipped"
        done = asyncio.Event()
        self._cancelling_order_ids[order_id] = done
        try:
            if not await self._still_open(order_id):
                return "closed"
            if skip is not None and skip(record):
                return "skipped"
            await self._eventbus.publish(
                OrderCancelEvent(
                    account_id=record.account_id,
                    bot_id=record.bot_id,
                    strategy_id=record.strategy_id,
                    order_id=order_id,
                    reason=reason,
                )
            )
            return await self._cancel_outcome(order_id)
        finally:
            self._cancelling_order_ids.pop(order_id, None)
            done.set()

    async def _still_open(self, order_id: str) -> bool:
        """추적기의 열린 주문 정의로 다시 확인한다(조회가 실패하면 열린 것으로 본다)."""
        tracker = self._order_tracker
        assert tracker is not None
        try:
            current = await tracker.get(order_id)
        except Exception:
            logger.exception("취소 전 주문 조회 실패: %s", order_id)
            return True
        return current is not None and current.status in _OPEN_ORDER_STATUSES

    async def _cancel_outcome(self, order_id: str) -> str:
        """취소 요청 뒤 추적기의 상태가 cancelled면 cancelled, 아니면 failed."""
        tracker = self._order_tracker
        assert tracker is not None
        try:
            after = await tracker.get(order_id)
        except Exception:
            logger.exception("봇 정지 — 취소 결과 조회 실패: %s", order_id)
            return "failed"
        if after is not None and after.status == "cancelled":
            return "cancelled"
        return "failed"

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 시 알림 발행 + 재시작 정책에 따라 자동 재시작."""
        from ante.eventbus.events import BotErrorEvent, NotificationEvent

        if not isinstance(event, BotErrorEvent):
            return

        reg = self._signal_channel_registry
        if reg is not None:
            reg.close_bot(event.bot_id, "bot_stopped")

        await self._eventbus.publish(
            NotificationEvent(
                level="error",
                title="봇 에러",
                message=f"봇 `{event.bot_id}`\n{event.error_message}",
                category="bot",
            )
        )

        bot = self._bots.get(event.bot_id)
        if not bot or not bot.config.auto_restart:
            return

        config = bot.config
        count = self._restart_counts.get(event.bot_id, 0)

        if count >= config.max_restart_attempts:
            await self._on_restart_exhausted(
                event.bot_id, config.account_id, count, event.error_message
            )
            return

        if not self._is_registered(bot):
            return

        self._restart_counts[event.bot_id] = count + 1
        logger.warning(
            "봇 재시작 예약: %s (시도 %d/%d, %d초 후)",
            event.bot_id,
            count + 1,
            config.max_restart_attempts,
            config.restart_cooldown_seconds,
        )

        task = asyncio.create_task(
            self._restart_after_cooldown(event.bot_id),
            name=f"restart-{event.bot_id}",
        )
        self._restart_tasks[event.bot_id] = task

    async def _restart_after_cooldown(self, bot_id: str) -> None:
        """쿨다운 대기 후 봇 재시작."""
        bot = self._bots.get(bot_id)
        if not bot:
            return

        try:
            await _cooldown_sleep(bot.config.restart_cooldown_seconds)
        except asyncio.CancelledError:
            raise

        if not await self._account_allows_restart(bot):
            return
        if bot.status != BotStatus.ERROR or not self._is_registered(bot):
            return

        try:
            self._load_strategy_rules(bot.config.strategy_id)
            await bot.start()
            logger.info("봇 재시작 성공: %s", bot_id)
            self._schedule_restart_reset(bot_id)
        except Exception as e:
            logger.error("봇 재시작 실패: %s — %s", bot_id, e)
        finally:
            self._restart_tasks.pop(bot_id, None)

    async def _account_allows_restart(self, bot: Bot) -> bool:
        """봇의 계좌가 ACTIVE인지 다시 본다. 조회가 실패하면 False."""
        if self._account_service is None:
            return True
        account_id = bot.config.account_id
        try:
            account = await self._account_service.get(account_id)
        except Exception:
            logger.warning(
                "봇 재시작 생략 — 계좌 조회 실패: bot=%s, account=%s",
                bot.bot_id,
                account_id,
                exc_info=True,
            )
            if bot.status == BotStatus.ERROR and self._is_registered(bot):
                await self._eventbus.publish(
                    NotificationEvent(
                        level="error",
                        title="봇 자동 재시작 중단",
                        message=(
                            f"봇 `{bot.bot_id}` · 계좌 `{account_id}`\n"
                            "계좌를 확인하지 못해 자동 재시작을 하지 않았습니다. "
                            "봇은 에러 상태로 남습니다. "
                            "원인 확인 후 수동으로 다시 시작하세요."
                        ),
                        category="bot",
                    )
                )
            return False
        if account.status != AccountStatus.ACTIVE:
            logger.warning(
                "봇 재시작 생략 — 계좌가 활성 상태가 아님: bot=%s, account=%s (%s)",
                bot.bot_id,
                account_id,
                account.status,
            )
            return False
        return True

    def _schedule_restart_reset(self, bot_id: str) -> None:
        """정상 실행 유지 시 재시작 카운터 리셋 스케줄링."""
        old_task = self._restart_reset_tasks.pop(bot_id, None)
        if old_task and not old_task.done():
            old_task.cancel()

        bot = self._bots.get(bot_id)
        if not bot:
            return

        config = bot.config
        reset_after = config.restart_cooldown_seconds * config.max_restart_attempts

        task = asyncio.create_task(
            self._reset_restart_count_after(bot_id, reset_after),
            name=f"restart-reset-{bot_id}",
        )
        self._restart_reset_tasks[bot_id] = task

    async def _reset_restart_count_after(self, bot_id: str, seconds: float) -> None:
        """일정 시간 정상 실행 후 재시작 카운터 초기화."""
        try:
            await _cooldown_sleep(seconds)
        except asyncio.CancelledError:
            raise

        bot = self._bots.get(bot_id)
        if bot and bot.status == BotStatus.RUNNING:
            old_count = self._restart_counts.pop(bot_id, 0)
            if old_count > 0:
                logger.info(
                    "봇 재시작 카운터 리셋: %s (정상 %d초 유지)",
                    bot_id,
                    seconds,
                )
        self._restart_reset_tasks.pop(bot_id, None)

    async def _on_restart_exhausted(
        self, bot_id: str, account_id: str, attempts: int, last_error: str
    ) -> None:
        """재시작 한도 소진 시 이벤트 + 알림 발행."""
        from ante.eventbus.events import BotRestartExhaustedEvent, NotificationEvent

        logger.error(
            "봇 재시작 한도 소진: %s (%d회 시도)",
            bot_id,
            attempts,
        )
        await self._eventbus.publish(
            BotRestartExhaustedEvent(
                bot_id=bot_id,
                account_id=account_id,
                restart_attempts=attempts,
                last_error=last_error,
            )
        )
        await self._eventbus.publish(
            NotificationEvent(
                level="error",
                title="봇 재시작 한도 소진",
                message=(f"봇 `{bot_id}` · {attempts}회 시도\n{last_error}"),
                category="bot",
            )
        )

    async def get_signal_key(self, bot_id: str) -> str | None:
        """봇의 시그널 키 조회. 현재 전략이 외부 시그널을 받지 않으면 ``None``."""
        if not self._signal_key_manager:
            return None
        bot = self._get_bot(bot_id)
        meta = await self._strategy_meta(bot)
        if not getattr(meta, "accepts_external_signals", False):
            return None
        return await self._signal_key_manager.get_key(bot_id)

    async def validate_signal_key(self, key: str) -> str | None:
        """``signal.connect`` 핸드셰이크 게이트① — signal key → bot_id 검증.

        * manager 구성 + key hit → ``bot_id``.
        * manager 구성 + key miss → ``None`` (핸들러가 ``InvalidSignalKey``
          로 변환; 본 메서드는 raise 하지 않음).
        * manager 미구성(``_signal_key_manager is None``) →
          ``SignalKeyManagerNotConfigured`` (generic ``BotError`` /
          EXECUTION_ERROR fold 회피). 키는 로깅/메시지에 노출하지 않는다.
        """
        if self._signal_key_manager is None:
            raise SignalKeyManagerNotConfigured()
        return await self._signal_key_manager.validate_key(key)

    async def rotate_signal_key(self, bot_id: str) -> str:
        """시그널 키 재발급.

        ``accepts_external_signals=False`` 전략의 봇에 rotate 가 새 키를
        발급해 orphan credential 이 생기지 않도록 막는다. ``create_bot`` 의
        자동 발급 분기 (``manager.py`` 의 ``getattr(strategy_cls.meta,
        "accepts_external_signals", False)``) 와 동일한 조건을 사용해
        일관성을 유지한다.
        """
        if not self._signal_key_manager:
            raise BotError("SignalKeyManager가 설정되지 않았습니다")
        bot = self._get_bot(bot_id)
        meta = await self._strategy_meta(bot)
        if not getattr(meta, "accepts_external_signals", False):
            raise BotNotAcceptingSignals(
                f"이 봇의 전략은 외부 시그널을 받지 않습니다: "
                f"bot_id={bot_id}, strategy_id={bot.config.strategy_id}"
            )

        new_key = await self._signal_key_manager.rotate(bot_id)
        reg = self._signal_channel_registry
        if reg is not None:
            reg.bump_generation(bot_id)
            reg.close_bot(bot_id, "rotated")
        return new_key

    async def _strategy_meta(self, bot: Bot) -> Any:
        """봇에 지금 묶인 전략의 meta(인스턴스 → 클래스 → 레지스트리 로드 순)."""
        strategy = getattr(bot, "strategy", None)
        if strategy is not None:
            meta = getattr(strategy, "meta", None)
            if meta is not None:
                return meta
        strategy_cls = getattr(bot, "_strategy_cls", None)
        if strategy_cls is not None:
            meta = getattr(strategy_cls, "meta", None)
            if meta is not None:
                return meta
        from ante.strategy.loader import StrategyLoader
        from ante.strategy.registry import StrategyRegistry

        registry = StrategyRegistry(self._db)
        await registry.initialize()
        record = await registry.get(bot.config.strategy_id)
        if record is None:
            raise BotError(f"전략 미발견: {bot.config.strategy_id}")
        loaded_cls = StrategyLoader.load(Path(record.filepath))
        return getattr(loaded_cls, "meta", None)

    def get_restart_count(self, bot_id: str) -> int:
        """봇의 현재 재시작 시도 횟수."""
        return self._restart_counts.get(bot_id, 0)

    def _register_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 등록."""
        from ante.eventbus.events import (
            ExternalSignalEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.subscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
            StopOrderExpiredEvent,
        ):
            self._eventbus.subscribe(event_type, bot.on_order_update)

    def _unregister_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 해제."""
        from ante.eventbus.events import (
            ExternalSignalEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.unsubscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
            StopOrderExpiredEvent,
        ):
            self._eventbus.unsubscribe(event_type, bot.on_order_update)

    async def _save_bot_config(self, config: BotConfig) -> None:
        """봇 설정 DB 저장."""
        config_dict = {
            "bot_id": config.bot_id,
            "name": config.name,
            "strategy_id": config.strategy_id,
            "account_id": config.account_id,
            "interval_seconds": config.interval_seconds,
            "auto_restart": config.auto_restart,
            "max_restart_attempts": config.max_restart_attempts,
            "restart_cooldown_seconds": config.restart_cooldown_seconds,
            "step_timeout_seconds": config.step_timeout_seconds,
            "max_signals_per_step": config.max_signals_per_step,
        }
        await self._db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                 name = excluded.name,
                 strategy_id = excluded.strategy_id,
                 account_id = excluded.account_id,
                 config_json = excluded.config_json,
                 updated_at = datetime('now')""",
            (
                config.bot_id,
                config.name,
                config.strategy_id,
                config.account_id,
                json.dumps(config_dict),
            ),
        )
