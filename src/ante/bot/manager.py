"""BotManager — 봇 생명주기 중앙 관리."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ante.bot.bot import Bot
from ante.bot.config import BotConfig, BotStatus
from ante.bot.exceptions import BotError

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.bot.context_factory import StrategyContextFactory
    from ante.bot.signal_key import SignalKeyManager  # noqa: F811
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.rule.engine import RuleEngine  # noqa: F811
    from ante.strategy.base import Strategy
    from ante.strategy.context import StrategyContext
    from ante.strategy.snapshot import StrategySnapshot
    from ante.treasury.manager import TreasuryManager  # noqa: F811

logger = logging.getLogger(__name__)

BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    bot_id       TEXT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    strategy_id  TEXT NOT NULL,
    account_id   TEXT NOT NULL DEFAULT 'test',
    config_json  TEXT NOT NULL,
    auto_start   BOOLEAN DEFAULT 0,
    status       TEXT DEFAULT 'created',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bots_account_id ON bots(account_id);
"""


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
        self._bots: dict[str, Bot] = {}
        self._suppress_notification_bot_ids: set[str] = set()
        self._restart_counts: dict[str, int] = {}
        self._restart_tasks: dict[str, asyncio.Task[None]] = {}
        self._restart_reset_tasks: dict[str, asyncio.Task[None]] = {}

    async def initialize(self) -> None:
        """스키마 생성 + 마이그레이션 + EventBus 구독 + 잔존 스냅샷 정리."""
        await self._db.execute_script(BOT_SCHEMA)
        await self._migrate_schema()
        self._subscribe_events()
        if self._snapshot:
            cleaned = self._snapshot.cleanup_all()
            if cleaned:
                logger.info("잔존 전략 스냅샷 %d건 정리", cleaned)
        logger.info("BotManager 초기화 완료")

    async def _migrate_schema(self) -> None:
        """기존 bots 테이블에 account_id 컬럼이 없으면 추가한다."""
        columns = await self._db.fetch_all("PRAGMA table_info(bots)")
        col_names = {col["name"] for col in columns}
        if "account_id" not in col_names:
            await self._db.execute(
                "ALTER TABLE bots ADD COLUMN account_id TEXT NOT NULL DEFAULT 'test'"
            )
            logger.info("bots 테이블에 account_id 컬럼 추가 (마이그레이션)")

    async def load_from_db(self) -> int:
        """DB에서 봇 설정을 읽어 메모리에 로드한다 (테스트용).

        deleted 상태가 아닌 모든 봇을 읽어 stub Bot 인스턴스를 생성한다.
        기존 메모리 상태는 초기화된다. 반환값은 로드된 봇 수.
        """
        from ante.strategy.base import Signal, Strategy, StrategyMeta

        # NullStrategy: 실제 전략 실행 없이 봇 인스턴스만 생성하기 위한 스텁
        class _NullStrategy(Strategy):
            meta = StrategyMeta(name="null", version="0.0.0", description="test stub")

            async def on_step(self, context: dict) -> list[Signal]:  # type: ignore[override]
                return []

        # NullContext: StrategyContext 없이 Bot을 생성하기 위한 스텁
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
            # 마이그레이션: 기존 config에 account_id가 없으면 기본값 사용
            account_id = row.get("account_id") or config_data.get("account_id", "test")
            # bot_type, exchange 키는 무시 (BotConfig에서 제거됨)
            config_data.pop("bot_type", None)
            config_data.pop("exchange", None)
            config = BotConfig(
                bot_id=row["bot_id"],
                strategy_id=row["strategy_id"],
                name=row["name"] or config_data.get("name", row["bot_id"]),
                account_id=account_id,
                interval_seconds=config_data.get("interval_seconds", 60),
            )
            bot = Bot(
                config=config,
                strategy_cls=_NullStrategy,
                ctx=_NullContext(config.bot_id),  # type: ignore[arg-type]
                eventbus=self._eventbus,
            )
            # DB에 저장된 상태로 복원
            status_str = row["status"]
            try:
                bot.status = BotStatus(status_str)
            except ValueError:
                bot.status = BotStatus.CREATED
            self._bots[config.bot_id] = bot

        logger.info("DB에서 봇 %d건 로드", len(self._bots))
        return len(self._bots)

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
        if config.bot_id in self._bots:
            raise BotError(f"Bot already exists: {config.bot_id}")

        # 1전략 1봇 정책: 실행 중인 봇이 사용 중인 전략 중복 차단
        active_statuses = {BotStatus.RUNNING, BotStatus.STOPPING}
        for existing_bot in self._bots.values():
            if (
                existing_bot.config.strategy_id == config.strategy_id
                and existing_bot.status in active_statuses
            ):
                raise BotError(
                    f"전략 '{config.strategy_id}'은(는) 이미 봇 "
                    f"'{existing_bot.bot_id}'에서 사용 중입니다. "
                    f"파라미터가 다른 전략은 별도 파일로 작성하세요."
                )

        # 계좌 상태 검증 (strategy meta 유무와 무관하게 독립 실행)
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

        # exchange 호환성 검증 (strategy meta 필요)
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

        # 전략 파일 스냅샷 생성
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

        bot = Bot(
            config=config,
            strategy_cls=strategy_cls,
            ctx=ctx,
            eventbus=self._eventbus,
            exchange=account.exchange if account else "",
            trading_mode=account.trading_mode.value if account else "",
            currency=account.currency if account else "",
        )

        self._register_bot_events(bot)
        self._bots[config.bot_id] = bot
        await self._save_bot_config(config)

        # accepts_external_signals=True이면 시그널 키 자동 발급
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

    async def assign_strategy(self, bot_id: str, strategy_id: str) -> None:
        """봇에 전략 배정.

        running 상태이면 중지 후 전략을 교체하고 재시작한다.
        stopped/created 상태이면 전략 ID만 교체한다.
        """
        bot = self._get_bot(bot_id)
        was_running = bot.status == BotStatus.RUNNING

        if was_running:
            await bot.stop()
            self._remove_strategy_rules(bot.config.strategy_id)

        bot.config.strategy_id = strategy_id
        await self._update_bot_strategy(bot_id, strategy_id)

        if was_running:
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
        stopped/created/error 상태에서만 전략 ID를 교체한다.
        """
        bot = self._get_bot(bot_id)
        if bot.status == BotStatus.RUNNING:
            raise BotError(
                f"실행 중인 봇의 전략은 변경할 수 없습니다: {bot_id}. "
                f"assign_strategy()를 사용하거나 먼저 봇을 중지하세요."
            )

        bot.config.strategy_id = strategy_id
        await self._update_bot_strategy(bot_id, strategy_id)

        logger.info("전략 교체: bot=%s strategy=%s", bot_id, strategy_id)

    async def resume_bot(self, bot_id: str) -> None:
        """중지/에러 상태 봇 재시작.

        에러 카운터를 리셋하고 봇을 시작한다.
        running 상태이면 예외를 발생시킨다.
        """
        bot = self._get_bot(bot_id)
        if bot.status == BotStatus.RUNNING:
            raise BotError(f"이미 실행 중인 봇입니다: {bot_id}")

        if bot.status not in (BotStatus.STOPPED, BotStatus.ERROR):
            raise BotError(f"재개할 수 없는 상태입니다: {bot_id} (현재: {bot.status})")

        # 에러 카운터 리셋
        self._restart_counts.pop(bot_id, None)
        bot.error_message = None

        self._load_strategy_rules(bot.config.strategy_id)
        await bot.start()
        logger.info("봇 재개: %s", bot_id)

    async def start_bot(self, bot_id: str) -> None:
        """봇 시작. 전략별 룰이 설정되어 있으면 RuleEngine에 로드."""
        bot = self._get_bot(bot_id)
        self._load_strategy_rules(bot.config.strategy_id)
        await bot.start()

    async def stop_bot(
        self, bot_id: str, *, suppress_notification: bool = False
    ) -> None:
        """봇 중지. 전략별 룰을 RuleEngine에서 제거.

        suppress_notification이 True이면 BotStoppedEvent에 의한
        NotificationEvent 발행을 1회 억제한다.
        """
        bot = self._get_bot(bot_id)
        if suppress_notification:
            self._suppress_notification_bot_ids.add(bot_id)
        await bot.stop()
        self._remove_strategy_rules(bot.config.strategy_id)

    async def delete_bot(self, bot_id: str) -> None:
        """봇 소프트 딜리트. 실행 중이면 먼저 중지."""
        bot = self._get_bot(bot_id)
        if bot.status == BotStatus.RUNNING:
            await bot.stop()

        self._unregister_bot_events(bot)

        # PaperExecutor 등록 해제 (봇이 등록되어 있는 경우)
        if self._context_factory and self._context_factory._paper_executor:
            self._context_factory._paper_executor.unregister_bot(bot_id)

        # 시그널 키 폐기
        if self._signal_key_manager:
            await self._signal_key_manager.revoke(bot_id)

        # 전략 스냅샷 정리
        if self._snapshot:
            self._snapshot.cleanup(bot_id)

        # Treasury budget 환수
        if self._treasury_manager:
            try:
                treasury = self._treasury_manager.get(bot.config.account_id)
                released = await treasury.release_budget(bot_id)
                if released > 0:
                    logger.info(
                        "봇 삭제 시 예산 환수: %s -- %s",
                        bot_id,
                        f"{released:,.0f}",
                    )
            except KeyError:
                logger.debug(
                    "봇 삭제 시 Treasury 미존재: account_id=%s",
                    bot.config.account_id,
                )

        bot.status = BotStatus.DELETED
        del self._bots[bot_id]
        await self._db.execute(
            "UPDATE bots SET status = 'deleted', updated_at = datetime('now')"
            " WHERE bot_id = ?",
            (bot_id,),
        )
        logger.info("봇 삭제 (soft delete): %s", bot_id)

    async def remove_bot(self, bot_id: str) -> None:
        """봇 삭제. delete_bot()의 별칭 (하위 호환)."""
        await self.delete_bot(bot_id)

    async def stop_all(self) -> None:
        """모든 봇 중지."""
        # 재시작 태스크 취소
        for task in list(self._restart_tasks.values()):
            task.cancel()
        for task in list(self._restart_reset_tasks.values()):
            task.cancel()
        self._restart_tasks.clear()
        self._restart_reset_tasks.clear()

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
            raise BotError(f"Bot not found: {bot_id}")
        return bot

    # ── 전략별 룰 관리 ─────────────────────────────────

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

    # ── EventBus 핸들러 ──────────────────────────────

    async def _on_bot_stop_request(self, event: object) -> None:
        """BotStopEvent 수신 시 해당 봇 중지."""
        from ante.eventbus.events import BotStopEvent

        if not isinstance(event, BotStopEvent):
            return
        if event.bot_id in self._bots:
            await self.stop_bot(event.bot_id)

    async def _on_account_suspended(self, event: object) -> None:
        """계좌 정지 시 해당 계좌의 봇만 중지."""
        from ante.eventbus.events import AccountSuspendedEvent

        if not isinstance(event, AccountSuspendedEvent):
            return
        account_id = event.account_id
        stopped = []
        for bot in list(self._bots.values()):
            if bot.config.account_id == account_id and bot.status == BotStatus.RUNNING:
                await bot.stop()
                stopped.append(bot.bot_id)
        if stopped:
            logger.warning(
                "계좌 정지 — 봇 %d개 중지: account=%s, bots=%s",
                len(stopped),
                account_id,
                stopped,
            )

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
        """봇 중지 알림 발행. suppress 목록에 있으면 알림 생략."""
        from ante.eventbus.events import BotStoppedEvent, NotificationEvent

        if not isinstance(event, BotStoppedEvent):
            return
        if event.bot_id in self._suppress_notification_bot_ids:
            self._suppress_notification_bot_ids.discard(event.bot_id)
            return
        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="봇 중지",
                message=f"봇 `{event.bot_id}` 중지 완료",
                category="bot",
            )
        )

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 시 알림 발행 + 재시작 정책에 따라 자동 재시작."""
        from ante.eventbus.events import BotErrorEvent, NotificationEvent

        if not isinstance(event, BotErrorEvent):
            return

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
            await self._on_restart_exhausted(event.bot_id, count, event.error_message)
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
            await asyncio.sleep(bot.config.restart_cooldown_seconds)
        except asyncio.CancelledError:
            raise

        if bot.status != BotStatus.ERROR:
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
            await asyncio.sleep(seconds)
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
        self, bot_id: str, attempts: int, last_error: str
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
        """봇의 시그널 키 조회."""
        if not self._signal_key_manager:
            return None
        return await self._signal_key_manager.get_key(bot_id)

    async def rotate_signal_key(self, bot_id: str) -> str:
        """시그널 키 재발급."""
        if not self._signal_key_manager:
            raise BotError("SignalKeyManager가 설정되지 않았습니다")
        self._get_bot(bot_id)  # 존재 확인
        return await self._signal_key_manager.rotate(bot_id)

    def get_restart_count(self, bot_id: str) -> int:
        """봇의 현재 재시작 시도 횟수."""
        return self._restart_counts.get(bot_id, 0)

    # ── 봇 이벤트 구독 관리 ──────────────────────────

    def _register_bot_events(self, bot: Bot) -> None:
        """봇의 이벤트 핸들러 등록."""
        from ante.eventbus.events import (
            ExternalSignalEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.subscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
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
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, bot.on_order_filled)
        self._eventbus.unsubscribe(ExternalSignalEvent, bot.on_external_signal)
        for event_type in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
        ):
            self._eventbus.unsubscribe(event_type, bot.on_order_update)

    # ── DB ───────────────────────────────────────────

    async def _update_bot_strategy(self, bot_id: str, strategy_id: str) -> None:
        """봇의 전략 ID를 DB에 갱신."""
        await self._db.execute(
            "UPDATE bots SET strategy_id = ?, updated_at = datetime('now')"
            " WHERE bot_id = ?",
            (strategy_id, bot_id),
        )

    async def _save_bot_config(self, config: BotConfig) -> None:
        """봇 설정 DB 저장."""
        config_dict = {
            "bot_id": config.bot_id,
            "name": config.name,
            "strategy_id": config.strategy_id,
            "account_id": config.account_id,
            "interval_seconds": config.interval_seconds,
            "paper_initial_balance": config.paper_initial_balance,
        }
        await self._db.execute(
            """INSERT INTO bots
               (bot_id, name, strategy_id, account_id, config_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                 name = excluded.name,
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
