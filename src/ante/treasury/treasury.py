"""Treasury -- 계좌별 중앙 자금(예산) 관리."""

from __future__ import annotations

import asyncio
import logging
import math
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, TypeGuard

from ante.account.scoping import require_account_id
from ante.core import clock
from ante.treasury.exceptions import DuplicateReservationError
from ante.treasury.models import BotBudget

if TYPE_CHECKING:
    from ante.account.models import TradingMode
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.broker.base import BrokerAdapter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.position import PositionHistory

logger = logging.getLogger(__name__)

TransactionType = Literal[
    "allocate",
    "deallocate",
    "release",
    "fill",
    "bot_stopped_release",
]

TRANSACTION_TYPE_VOCABULARY: frozenset[str] = frozenset(
    {"allocate", "deallocate", "release", "fill", "bot_stopped_release"}
)

TREASURY_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_budgets (
    bot_id       TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL,
    allocated    REAL NOT NULL DEFAULT 0.0,
    available    REAL NOT NULL DEFAULT 0.0,
    reserved     REAL NOT NULL DEFAULT 0.0,
    spent        REAL NOT NULL DEFAULT 0.0,
    returned     REAL NOT NULL DEFAULT 0.0,
    last_updated TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS treasury_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id           TEXT,
    account_id       TEXT NOT NULL,
    transaction_type TEXT NOT NULL,
    amount           REAL NOT NULL,
    description      TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS treasury_fill_dedup (
    fill_dedup_key TEXT PRIMARY KEY,
    bot_id         TEXT,
    account_id     TEXT,
    processed_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS treasury_state (
    account_id         TEXT PRIMARY KEY,
    account_balance    REAL NOT NULL DEFAULT 0,
    purchasable_amount REAL NOT NULL DEFAULT 0,
    total_evaluation   REAL NOT NULL DEFAULT 0,
    currency           TEXT NOT NULL DEFAULT 'KRW',
    last_synced_at     TEXT
);

CREATE TABLE IF NOT EXISTS treasury_daily_snapshots (
    account_id           TEXT    NOT NULL,
    snapshot_date        TEXT    NOT NULL,
    total_asset          REAL    NOT NULL DEFAULT 0,
    ante_eval_amount     REAL    NOT NULL DEFAULT 0,
    ante_purchase_amount REAL    NOT NULL DEFAULT 0,
    unallocated          REAL    NOT NULL DEFAULT 0,
    account_balance      REAL    NOT NULL DEFAULT 0,
    total_allocated      REAL    NOT NULL DEFAULT 0,
    bot_count            INTEGER NOT NULL DEFAULT 0,
    daily_pnl            REAL    DEFAULT 0.0,
    daily_return         REAL    DEFAULT 0.0,
    net_trade_amount     REAL    DEFAULT 0.0,
    unrealized_pnl       REAL    DEFAULT 0.0,
    created_at           TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, snapshot_date)
);
CREATE TABLE IF NOT EXISTS treasury_reservations (
    order_id     TEXT PRIMARY KEY,
    bot_id       TEXT NOT NULL,
    account_id   TEXT NOT NULL,
    remaining    REAL NOT NULL,
    updated_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bot_budgets_account
    ON bot_budgets(account_id);
CREATE INDEX IF NOT EXISTS idx_treasury_reservations_account
    ON treasury_reservations(account_id);
CREATE INDEX IF NOT EXISTS idx_treasury_transactions_account
    ON treasury_transactions(account_id);
"""

TREASURY_MIGRATION_V2 = """
ALTER TABLE bot_budgets ADD COLUMN account_id TEXT;
"""

TREASURY_TRANSACTIONS_MIGRATION = """
ALTER TABLE treasury_transactions ADD COLUMN account_id TEXT;
"""

_STATE_MIGRATION_COLUMNS = [
    ("purchase_amount", "REAL NOT NULL DEFAULT 0"),
    ("eval_amount", "REAL NOT NULL DEFAULT 0"),
    ("total_profit_loss", "REAL NOT NULL DEFAULT 0"),
    ("external_purchase_amount", "REAL NOT NULL DEFAULT 0"),
    ("external_eval_amount", "REAL NOT NULL DEFAULT 0"),
]

_SNAPSHOT_MIGRATION_COLUMNS = [
    ("total_asset", "REAL NOT NULL DEFAULT 0"),
    ("unallocated", "REAL NOT NULL DEFAULT 0"),
    ("account_balance", "REAL NOT NULL DEFAULT 0"),
    ("total_allocated", "REAL NOT NULL DEFAULT 0"),
    ("bot_count", "INTEGER NOT NULL DEFAULT 0"),
    ("daily_pnl", "REAL DEFAULT 0.0"),
    ("daily_return", "REAL DEFAULT 0.0"),
    ("net_trade_amount", "REAL DEFAULT 0.0"),
    ("unrealized_pnl", "REAL DEFAULT 0.0"),
]

_SNAPSHOT_RETENTION_DAYS = 365 * 5

_PURCHASABLE_PROBE_SYMBOL = "005930"

SYNCED_PRICE_MISSING = "no synced price"
SYNCED_PRICE_STALE = "synced price stale"


def _is_positive_finite(value: object) -> TypeGuard[int | float]:
    """bool이 아닌 int·float이고 유한한 양수인지 예외 없이 판정한다."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= sys.float_info.max
    return math.isfinite(value) and value > 0


_OPEN_ORDER_STATUSES: frozenset[str] = frozenset({"open", "partially_filled"})


class Treasury:
    """계좌별 중앙 자금(예산) 관리자.

    각 계좌(Account)에 대해 하나의 인스턴스가 생성되며,
    해당 계좌의 잔고를 소유하고, 봇별로 예산을 배분한다.
    """

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        *,
        account_id: str,
        currency: str = "KRW",
        buy_commission_rate: float = 0.00015,
        sell_commission_rate: float = 0.00195,
        market_order_reserve_buffer_rate: Decimal = Decimal("0"),
        order_reserve_price_resolver: Callable[[str], Awaitable[float]] | None = None,
        bot_status_checker: Callable[[str], str] | None = None,
        order_tracker: OrderTracker | None = None,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
        broker_type: str = "test",
        trading_mode: TradingMode | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._account_id = require_account_id(account_id, context="treasury.__init__")
        self._currency = currency
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        self._market_order_reserve_buffer_rate = market_order_reserve_buffer_rate
        self._order_reserve_price_resolver = order_reserve_price_resolver
        self._bot_status_checker = bot_status_checker
        self._order_tracker = order_tracker
        self._runtime_readiness = runtime_readiness
        self._gate_broker_type = broker_type
        if trading_mode is None:
            from ante.account.models import TradingMode as _TradingMode

            trading_mode = _TradingMode.VIRTUAL
        self._gate_trading_mode = trading_mode

        self._account_balance: float = 0.0
        self._purchasable_amount: float = 0.0
        self._total_evaluation: float = 0.0
        self._purchase_amount: float = 0.0
        self._eval_amount: float = 0.0
        self._total_profit_loss: float = 0.0
        self._external_purchase_amount: float = 0.0
        self._external_eval_amount: float = 0.0
        self._budgets: dict[str, BotBudget] = {}
        self._unallocated: float = 0.0
        self._reservations: dict[str, tuple[str, float]] = {}
        self._sync_task: asyncio.Task[None] | None = None
        self._sync_interval_seconds: object = None
        self._synced_prices: dict[str, tuple[float, float]] = {}

        self._account_number: str = ""
        self._is_demo_trading: bool = False
        self._last_synced_at: datetime | None = None

    @property
    def account_id(self) -> str:
        """이 Treasury가 관리하는 계좌 ID."""
        return self._account_id

    async def initialize(self) -> None:
        """스키마 생성 + DB 복원 + EventBus 구독."""
        await self._ensure_schema()
        await self._load_from_db()
        self._subscribe_events()
        logger.info(
            "Treasury 초기화 완료: account_id=%s, currency=%s",
            self._account_id,
            self._currency,
        )

    async def _ensure_schema(self) -> None:
        """DB 스키마 생성 및 마이그레이션."""
        await self._db.execute_script(TREASURY_SCHEMA)

        try:
            await self._db.execute_script(TREASURY_MIGRATION_V2)
        except Exception:
            pass

        try:
            await self._db.execute_script(TREASURY_TRANSACTIONS_MIGRATION)
        except Exception:
            pass

        for col_name, col_def in _STATE_MIGRATION_COLUMNS:
            try:
                await self._db.execute_script(
                    f"ALTER TABLE treasury_state ADD COLUMN {col_name} {col_def};"
                )
            except Exception:
                pass

        for col_name, col_def in _SNAPSHOT_MIGRATION_COLUMNS:
            try:
                await self._db.execute_script(
                    f"ALTER TABLE treasury_daily_snapshots "
                    f"ADD COLUMN {col_name} {col_def};"
                )
            except Exception:
                pass

    def _subscribe_events(self) -> None:
        """EventBus 이벤트 구독."""
        from ante.eventbus.events import (
            BotStoppedEvent,
            DailyReportEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderValidatedEvent,
        )

        self._eventbus.subscribe(
            OrderValidatedEvent, self._on_order_validated, priority=80
        )
        self._eventbus.subscribe(OrderFilledEvent, self._on_order_filled, priority=80)
        self._eventbus.subscribe(
            OrderCancelledEvent, self._on_order_cancelled, priority=80
        )
        self._eventbus.subscribe(OrderFailedEvent, self._on_order_failed, priority=80)
        self._eventbus.subscribe(BotStoppedEvent, self._on_bot_stopped, priority=80)
        self._eventbus.subscribe(DailyReportEvent, self._on_daily_report, priority=80)

    async def set_account_balance(self, balance: float) -> None:
        """계좌 잔고 설정. 미할당 자금을 자동 재계산.

        Raises:
            ValueError: balance가 finite가 아니거나 음수인 경우.
        """
        if not (math.isfinite(balance) and balance >= 0):
            raise ValueError(
                f"account balance must be finite and >= 0, got {balance!r}"
            )
        self._account_balance = balance
        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = balance - total_allocated
        await self._save_state()
        logger.info("계좌 잔고 설정: %s (account=%s)", balance, self._account_id)

    @property
    def account_balance(self) -> float:
        return self._account_balance

    @property
    def unallocated(self) -> float:
        return self._unallocated

    @property
    def buy_commission_rate(self) -> float:
        return self._buy_commission_rate

    @property
    def sell_commission_rate(self) -> float:
        return self._sell_commission_rate

    @property
    def currency(self) -> str:
        return self._currency

    @property
    def last_synced_at(self) -> datetime | None:
        return self._last_synced_at

    @property
    def account_number(self) -> str:
        return self._account_number

    @property
    def is_demo_trading(self) -> bool:
        return self._is_demo_trading

    @property
    def last_sync_time(self) -> str | None:
        """마지막 동기화 시각 (ISO 8601 문자열)."""
        if self._last_synced_at is None:
            return None
        return self._last_synced_at.isoformat()

    def set_account_info(self, account_number: str, is_demo_trading: bool) -> None:
        """KIS 계좌 메타 정보 설정 (broker 연결 후 호출)."""
        self._account_number = account_number
        self._is_demo_trading = is_demo_trading
        logger.info(
            "계좌 정보 설정: %s (모의투자: %s)", account_number, is_demo_trading
        )

    def set_bot_status_checker(self, checker: Callable[[str], str]) -> None:
        """봇 상태 확인 콜백 설정 (초기화 후 BotManager 연결 시 호출)."""
        self._bot_status_checker = checker

    def set_order_tracker(self, order_tracker: OrderTracker) -> None:
        """부분체결 비례 정산용 OrderTracker 참조 주입.

        생성자 주입 대신 부팅 순서상 OrderTracker 가 Treasury 보다 먼저
        준비될 수 없는 partial wiring 경로(테스트 등)를 위한 후속 주입 경로다.
        미주입(``None``) 시 buy 정산은 full-fill pop-once semantics 로 fallback
        한다 (R1-2 — VirtualProvider 직접 full-fill 보존).
        """
        self._order_tracker = order_tracker

    def set_order_reserve_price_resolver(
        self, resolver: Callable[[str], Awaitable[float]]
    ) -> None:
        """시장가 매수 reserve estimate 용 현재가 resolver 주입.

        ``_init_gateway()`` 끝에서 account-scoped wrapper로 주입한다. 기존
        ``start_sync(price_resolver=...)``의 자산 평가 sync resolver와는
        별도다. resolver는 ``await resolver(symbol) -> float`` 시그니처를
        만족해야 하며, 실패 시 예외를 raise하면 Treasury가 terminal
        ``OrderRejectedEvent(reason="market_buy_quote_unavailable: ...")``로
        변환한다.
        """
        self._order_reserve_price_resolver = resolver

    def update_commission_rates(
        self, buy_commission_rate: float, sell_commission_rate: float
    ) -> None:
        """수수료율 재주입.

        1.0 런타임 DynamicConfig 경로가 아니라, Account cold-path 재초기화나
        테스트 보조 경로에서만 사용한다.
        """
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        logger.info(
            "수수료율 갱신: buy=%s, sell=%s",
            buy_commission_rate,
            sell_commission_rate,
        )

    def get_available(self, bot_id: str) -> float:
        """봇의 가용 예산 조회."""
        budget = self._budgets.get(bot_id)
        return budget.available if budget else 0.0

    def get_budget(self, bot_id: str) -> BotBudget | None:
        """봇의 예산 상태 조회."""
        return self._budgets.get(bot_id)

    def get_budget_sync(self, bot_id: str) -> BotBudget | None:
        """봇의 예산 상태 동기 조회 (인메모리). PortfolioView용."""
        return self._budgets.get(bot_id)

    def _check_bot_stopped(self, bot_id: str) -> None:
        """봇이 중지 상태인지 확인. 운용 중이면 BotNotStoppedError."""
        from ante.treasury.exceptions import BotNotStoppedError

        if not self._bot_status_checker:
            return
        status = self._bot_status_checker(bot_id)
        if status and status not in ("stopped", "created", "error"):
            raise BotNotStoppedError(
                f"봇 '{bot_id}'이(가) {status} 상태입니다. "
                f"예산 변경은 봇 중지 후 가능합니다."
            )

    async def allocate(self, bot_id: str, amount: float) -> None:
        """봇에 예산 할당. 미할당 자금에서 차감.

        Raises:
            TreasuryInvalidAmountError: ``amount`` 가 NaN/±Inf/<=0.
            TreasuryInsufficientUnallocatedError: 미할당 잔액 부족.
            BotNotStoppedError: 봇이 운용 중.
        """
        from ante.treasury.exceptions import (
            TreasuryInsufficientUnallocatedError,
            TreasuryInvalidAmountError,
        )

        self._check_bot_stopped(bot_id)
        if not math.isfinite(amount) or amount <= 0:
            raise TreasuryInvalidAmountError(amount, operation="allocate")
        if self._unallocated < amount:
            raise TreasuryInsufficientUnallocatedError(
                bot_id, amount, self._unallocated
            )

        if bot_id not in self._budgets:
            self._budgets[bot_id] = BotBudget(
                bot_id=bot_id, account_id=self._account_id
            )

        budget = self._budgets[bot_id]
        budget.allocated += amount
        budget.available += amount
        budget.last_updated = clock.now(UTC)
        self._unallocated -= amount

        await self._save_budget(budget)
        await self._save_state()
        await self._log_transaction(bot_id, "allocate", amount)
        logger.info(
            "예산 할당: %s -> %s (account=%s)", bot_id, amount, self._account_id
        )

    async def deallocate(self, bot_id: str, amount: float) -> None:
        """봇에서 예산 회수. 가용 예산 범위 내에서만 가능.

        Raises:
            TreasuryInvalidAmountError: ``amount`` 가 NaN/±Inf/<=0.
            TreasuryBudgetNotFoundError: ``bot_id`` budget record 부재.
            TreasuryDeallocateExceedsAvailableError: 가용 예산 초과.
            BotNotStoppedError: 봇이 운용 중.
        """
        from ante.treasury.exceptions import (
            TreasuryBudgetNotFoundError,
            TreasuryDeallocateExceedsAvailableError,
            TreasuryInvalidAmountError,
        )

        self._check_bot_stopped(bot_id)
        if not math.isfinite(amount) or amount <= 0:
            raise TreasuryInvalidAmountError(amount, operation="deallocate")
        budget = self._budgets.get(bot_id)
        if budget is None:
            raise TreasuryBudgetNotFoundError(bot_id)
        if budget.available < amount:
            raise TreasuryDeallocateExceedsAvailableError(
                bot_id, amount, budget.available
            )

        budget.allocated -= amount
        budget.available -= amount
        budget.last_updated = clock.now(UTC)
        self._unallocated += amount

        await self._save_budget(budget)
        await self._save_state()
        await self._log_transaction(bot_id, "deallocate", amount)
        logger.info(
            "예산 회수: %s <- %s (account=%s)", bot_id, amount, self._account_id
        )

    async def release_budget(self, bot_id: str) -> float:
        """봇의 할당액 전액을 미할당으로 환수하고 budget 레코드를 삭제한다.

        봇 삭제 시 호출된다. bot_status_checker를 우회하여 어떤 상태에서든
        환수가 가능하다 (delete_bot에서 이미 봇을 중지한 뒤 호출하므로).

        Returns:
            환수된 금액. budget이 없으면 0.0.
        """
        budget = self._budgets.pop(bot_id, None)
        from_memory = budget is not None
        if not budget:
            row = await self._db.fetch_one(
                "SELECT * FROM bot_budgets WHERE bot_id = ? AND account_id = ?",
                (bot_id, self._account_id),
            )
            if row:
                budget = BotBudget(
                    bot_id=row["bot_id"],
                    account_id=row["account_id"],
                    allocated=float(row["allocated"]),
                    available=float(row["available"]),
                    reserved=float(row["reserved"]),
                    spent=float(row["spent"]),
                    returned=float(row["returned"]),
                    last_updated=datetime.fromisoformat(row["last_updated"]),
                )
            else:
                return 0.0

        released = budget.allocated
        self._unallocated += released

        try:
            async with self._db.transaction():
                await self._db.execute(
                    "DELETE FROM bot_budgets WHERE bot_id = ?",
                    (bot_id,),
                )
                await self._db.execute(
                    "DELETE FROM treasury_reservations "
                    "WHERE bot_id = ? AND account_id = ?",
                    (bot_id, self._account_id),
                )
        except BaseException:
            self._unallocated -= released
            if from_memory and bot_id not in self._budgets:
                self._budgets[bot_id] = budget
            raise

        pending_orders = [
            oid for oid, (bid, _) in self._reservations.items() if bid == bot_id
        ]
        for oid in pending_orders:
            self._reservations.pop(oid, None)

        await self._save_state()
        await self._log_transaction(
            bot_id, "release", released, "봇 삭제에 의한 예산 전액 환수"
        )

        logger.info(
            "예산 전액 환수: %s -- %s (account=%s)",
            bot_id,
            f"{released:,.0f}",
            self._account_id,
        )
        return released

    async def update_budget(self, bot_id: str, target_amount: float) -> None:
        """봇의 예산을 목표 금액으로 변경.

        현재 할당액과 목표 금액의 차이를 계산하여 allocate/deallocate를 호출한다.

        Raises:
            TreasuryInvalidAmountError: 목표 금액이 NaN/±Inf.
            ValueError: 목표 금액이 음수인 경우.
            InsufficientFundsError: 증액 시 미할당 잔액 부족, 감액 시 가용 예산 초과.
            BotNotStoppedError: 봇이 운용 중.
        """
        from ante.treasury.exceptions import (
            InsufficientFundsError,
            TreasuryDeallocateExceedsAvailableError,
            TreasuryInsufficientUnallocatedError,
            TreasuryInvalidAmountError,
        )

        if not math.isfinite(target_amount):
            raise TreasuryInvalidAmountError(target_amount, operation="update_budget")
        if target_amount < 0:
            raise ValueError(f"목표 금액은 0 이상이어야 합니다: {target_amount}")

        budget = self._budgets.get(bot_id)
        current = budget.allocated if budget else 0.0
        diff = target_amount - current

        if diff == 0:
            return

        if diff > 0:
            if self._unallocated < diff:
                raise InsufficientFundsError(
                    f"미할당 잔액 부족: 필요 {diff:,.0f}, 가용 {self._unallocated:,.0f}"
                )
            try:
                await self.allocate(bot_id, diff)
            except TreasuryInsufficientUnallocatedError as exc:
                raise InsufficientFundsError(
                    f"예산 할당 실패: bot_id={bot_id}, amount={diff} ({exc})"
                ) from exc
        else:
            decrease = abs(diff)
            try:
                await self.deallocate(bot_id, decrease)
            except TreasuryDeallocateExceedsAvailableError as exc:
                available = budget.available if budget else 0.0
                raise InsufficientFundsError(
                    f"예산 회수 실패: 회수 요청 {decrease:,.0f}, "
                    f"가용 예산 {available:,.0f} ({exc})"
                ) from exc

        logger.info(
            "예산 변경: %s -- %s -> %s (차이: %s%s)",
            bot_id,
            f"{current:,.0f}",
            f"{target_amount:,.0f}",
            "+" if diff > 0 else "",
            f"{diff:,.0f}",
        )

    async def reserve_for_order(
        self, bot_id: str, order_id: str, amount: float
    ) -> bool:
        """주문 제출 시 자금 예약."""
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("amount must be positive")
        if order_id in self._reservations:
            raise DuplicateReservationError(order_id)

        budget = self._budgets.get(bot_id)
        if not budget or budget.available < amount:
            return False

        before = replace(budget)
        previous = self._reservations.get(order_id)
        budget.available -= amount
        budget.reserved += amount
        budget.last_updated = clock.now(UTC)
        after = replace(budget)
        self._reservations[order_id] = (bot_id, amount)

        try:
            async with self._db.transaction():
                await self._save_budget(budget)
                await self._persist_reservation(order_id)
        except BaseException:
            if self._entry_kept(order_id, previous, (bot_id, amount)):
                self._revert_budget(budget, before, after)
                self._restore_reservation(order_id, previous)
            raise
        return True

    async def release_reservation(self, bot_id: str, order_id: str) -> None:
        """주문 취소/실패 시 **잔여 예약**만 해제.

        ``self._reservations[order_id][1]`` 은 잔여 예약(``remaining_reserved``)
        이다. 부분체결 후 취소/실패라면 이미 체결된 분은 ``_on_order_filled`` 에서
        ``spent`` 로 정산되며 ``reserved`` 에서 차감되었으므로, 여기서는 아직
        정산되지 않은 잔여 예약만 회수해 기체결분을 보존한다.
        """
        budget = self._budgets.get(bot_id)
        entry = self._reservations.pop(order_id, None)
        remaining = entry[1] if entry else 0.0
        settle = budget if budget is not None and remaining > 0 else None
        changes: tuple[BotBudget, BotBudget] | None = None
        if settle is not None:
            before = replace(settle)
            settle.reserved = max(0.0, settle.reserved - remaining)
            settle.available += remaining
            settle.last_updated = clock.now(UTC)
            changes = (before, replace(settle))

        try:
            async with self._db.transaction():
                if settle is not None:
                    await self._save_budget(settle)
                await self._persist_reservation(order_id)
        except BaseException:
            if self._entry_kept(order_id, entry, None):
                if settle is not None and changes is not None:
                    self._revert_budget(settle, *changes)
                self._restore_reservation(order_id, entry)
            raise

    def get_reservations(self, bot_id: str) -> dict[str, float]:
        """특정 봇의 미체결 예약 내역 조회.

        Returns:
            ``{order_id: remaining_reserved, ...}`` — 두번째 항은
            주문의 **잔여 예약**(아직 정산되지 않은 예약 자금)이다. 부분체결된
            주문이면 이미 체결된 분을 제외한 잔여만 반영한다.
        """
        return {
            oid: amt for oid, (bid, amt) in self._reservations.items() if bid == bot_id
        }

    async def _persist_reservation(self, order_id: str) -> None:
        """예약 표의 그 주문 항목을 행에 upsert하고, 항목이 없으면 행을 지운다."""
        entry = self._reservations.get(order_id)
        if entry is None:
            await self._db.execute(
                "DELETE FROM treasury_reservations "
                "WHERE order_id = ? AND account_id = ?",
                (order_id, self._account_id),
            )
            return
        await self._db.execute(
            """INSERT INTO treasury_reservations
               (order_id, bot_id, account_id, remaining)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(order_id) DO UPDATE SET
                 bot_id = excluded.bot_id,
                 remaining = excluded.remaining,
                 updated_at = datetime('now')""",
            (order_id, entry[0], self._account_id, entry[1]),
        )

    def _restore_reservation(
        self, order_id: str, entry: tuple[str, float] | None
    ) -> None:
        """rollback 시 예약 표의 그 주문 항목을 연산 전 값(없었으면 부재)으로."""
        if entry is None:
            self._reservations.pop(order_id, None)
        else:
            self._reservations[order_id] = entry

    def _entry_kept(
        self,
        order_id: str,
        before: tuple[str, float] | None,
        left: tuple[str, float] | None,
    ) -> bool:
        """이 연산이 바꾼 예약 항목이 남긴 그대로인지 보고, 아니면 경고를 남긴다."""
        if before == left or self._reservations.get(order_id) == left:
            return True
        logger.warning(
            "다른 연산이 예약을 이어받아 되돌리지 않는다: order_id=%s", order_id
        )
        return False

    def _log_duplicate_validated(self, order_id: str, bot_id: str) -> None:
        """같은 id의 예약이 있는 검증 이벤트를 발행 없이 버리며 오류 로그를 남긴다."""
        logger.error(
            "같은 order_id의 예약이 이미 있어 검증 이벤트를 버린다: "
            "order_id=%s, bot_id=%s",
            order_id,
            bot_id,
        )

    def _is_my_event(self, event: object) -> bool:
        """이벤트가 이 Treasury의 계좌에 해당하는지 확인."""
        account_id: object = getattr(event, "account_id", None)
        if account_id is None:
            return False
        return account_id == self._account_id

    async def _on_order_validated(self, event: object) -> None:
        """승인/거부 발행 — 매수 실패는 예외 대신 terminal ``OrderRejectedEvent`` 로."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderRejectedEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderValidatedEvent):
            return

        if not self._is_my_event(event):
            return

        if event.order_id in self._reservations:
            self._log_duplicate_validated(event.order_id, event.bot_id)
            return

        from ante.account.gate import (
            active_trading_blocked,
            build_not_ready_notification,
            is_liquidation_reason,
            not_ready_reason,
        )

        if active_trading_blocked(
            self._runtime_readiness,
            self._account_id,
            broker_type=self._gate_broker_type,
            trading_mode=self._gate_trading_mode,
        ):
            reason = not_ready_reason(
                self._runtime_readiness,
                self._account_id,
                broker_type=self._gate_broker_type,
                trading_mode=self._gate_trading_mode,
            )
            await self._eventbus.publish(
                OrderRejectedEvent(
                    account_id=self._account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=event.order_type,
                    reason=reason,
                    exchange=event.exchange,
                )
            )
            await self._eventbus.publish(
                build_not_ready_notification(
                    account_id=self._account_id,
                    reason=reason,
                    side=event.side,
                    is_liquidation=is_liquidation_reason(getattr(event, "reason", "")),
                )
            )
            return

        if event.side == "buy" and event.order_type in ("stop", "stop_limit"):
            await self._eventbus.publish(
                OrderApprovedEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price,
                    order_type=event.order_type,
                    stop_price=event.stop_price,
                    reserved_amount=0.0,
                    exchange=event.exchange,
                )
            )
            return

        if event.side == "buy" and event.order_type == "market" and event.price is None:
            resolver = self._order_reserve_price_resolver
            if resolver is None:
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=(
                            "market_buy_quote_unavailable: resolver not configured"
                        ),
                        exchange=event.exchange,
                    )
                )
                return
            try:
                quote = await resolver(event.symbol)
            except Exception as exc:
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=f"market_buy_quote_unavailable: {exc!s}",
                        exchange=event.exchange,
                    )
                )
                return

            if not (
                isinstance(quote, int | float) and math.isfinite(quote) and quote > 0
            ):
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=(
                            f"market_buy_quote_unavailable: "
                            f"non-finite or non-positive quote {quote!r}"
                        ),
                        exchange=event.exchange,
                    )
                )
                return
            try:
                quote_d = Decimal(str(quote))
            except Exception as exc:
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=(
                            f"market_buy_quote_unavailable: "
                            f"invalid quote {quote!r}: {exc!s}"
                        ),
                        exchange=event.exchange,
                    )
                )
                return

            quantity_d = Decimal(str(event.quantity))
            buffer = self._market_order_reserve_buffer_rate
            reserve_basis = quantity_d * quote_d * (Decimal("1") + buffer)
            commission_d = reserve_basis * Decimal(str(self._buy_commission_rate))
            total_reserve_d = reserve_basis + commission_d
            total_reserve_market_buy = float(total_reserve_d)

            if (
                not math.isfinite(total_reserve_market_buy)
                or total_reserve_market_buy <= 0
            ):
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=(
                            f"reserve_amount_invalid: "
                            f"total_reserve={total_reserve_market_buy}, "
                            f"quote={quote}, "
                            f"quantity={event.quantity}"
                        ),
                        exchange=event.exchange,
                    )
                )
                return

            try:
                success = await self.reserve_for_order(
                    event.bot_id, event.order_id, total_reserve_market_buy
                )
                if not success:
                    available = self.get_available(event.bot_id)
                    await self._eventbus.publish(
                        OrderRejectedEvent(
                            order_id=event.order_id,
                            bot_id=event.bot_id,
                            strategy_id=event.strategy_id,
                            symbol=event.symbol,
                            side=event.side,
                            quantity=event.quantity,
                            price=event.price,
                            order_type=event.order_type,
                            account_id=self._account_id,
                            reason=(
                                f"insufficient_budget: "
                                f"need {total_reserve_market_buy:,.0f}, "
                                f"available {available:,.0f}"
                            ),
                            exchange=event.exchange,
                        )
                    )
                    return

                await self._eventbus.publish(
                    OrderApprovedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=None,
                        order_type=event.order_type,
                        stop_price=event.stop_price,
                        reserved_amount=total_reserve_market_buy,
                        account_id=self._account_id,
                        exchange=event.exchange,
                    )
                )
                return
            except DuplicateReservationError:
                self._log_duplicate_validated(event.order_id, event.bot_id)
                return
            except Exception as exc:
                logger.exception(
                    "Treasury reserve_for_order 실패 (market buy): "
                    "order_id=%s, bot_id=%s",
                    event.order_id,
                    event.bot_id,
                )
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=f"reserve_failed: {exc!s}",
                        exchange=event.exchange,
                    )
                )
                return

        price = event.price or 0.0
        estimated_cost = event.quantity * price
        commission_estimate = estimated_cost * self._buy_commission_rate
        total_reserve = estimated_cost + commission_estimate

        if event.side == "buy":
            if not math.isfinite(total_reserve) or total_reserve <= 0:
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=(
                            f"reserve_amount_invalid: "
                            f"total_reserve={total_reserve}, "
                            f"price={event.price}, "
                            f"quantity={event.quantity}"
                        ),
                        exchange=event.exchange,
                    )
                )
                return

            try:
                success = await self.reserve_for_order(
                    event.bot_id, event.order_id, total_reserve
                )
                if not success:
                    available = self.get_available(event.bot_id)
                    await self._eventbus.publish(
                        OrderRejectedEvent(
                            order_id=event.order_id,
                            bot_id=event.bot_id,
                            strategy_id=event.strategy_id,
                            symbol=event.symbol,
                            side=event.side,
                            quantity=event.quantity,
                            price=event.price,
                            order_type=event.order_type,
                            account_id=self._account_id,
                            reason=(
                                f"insufficient_budget: need {total_reserve:,.0f}, "
                                f"available {available:,.0f}"
                            ),
                            exchange=event.exchange,
                        )
                    )
                    return

                await self._eventbus.publish(
                    OrderApprovedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        stop_price=event.stop_price,
                        reserved_amount=total_reserve,
                        account_id=self._account_id,
                        exchange=event.exchange,
                    )
                )
                return
            except DuplicateReservationError:
                self._log_duplicate_validated(event.order_id, event.bot_id)
                return
            except Exception as exc:
                logger.exception(
                    "Treasury reserve_for_order 실패: order_id=%s, bot_id=%s",
                    event.order_id,
                    event.bot_id,
                )
                await self._eventbus.publish(
                    OrderRejectedEvent(
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price,
                        order_type=event.order_type,
                        account_id=self._account_id,
                        reason=f"reserve_failed: {exc!s}",
                        exchange=event.exchange,
                    )
                )
                return

        await self._eventbus.publish(
            OrderApprovedEvent(
                order_id=event.order_id,
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                symbol=event.symbol,
                side=event.side,
                quantity=event.quantity,
                price=event.price,
                order_type=event.order_type,
                stop_price=event.stop_price,
                reserved_amount=0.0,
                account_id=self._account_id,
                exchange=event.exchange,
            )
        )

    async def _on_order_filled(self, event: object) -> None:
        """체결 이벤트 처리 — 매수는 예약 자금 정산, 매도는 대금을 예산에 더한다."""
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return

        if not self._is_my_event(event):
            return

        budget = self._budgets.get(event.bot_id)
        if not budget:
            return

        bot_id = event.bot_id
        order_id = event.order_id
        before: BotBudget | None = None
        after: BotBudget | None = None
        reservation_snapshot: tuple[str, float] | None = None
        left: tuple[str, float] | None = None

        try:
            async with self._db.transaction():
                if event.fill_dedup_key:
                    inserted = await self._db.execute_fetch_one(
                        """INSERT OR IGNORE INTO treasury_fill_dedup
                           (fill_dedup_key, bot_id, account_id)
                           VALUES (?, ?, ?)
                           RETURNING fill_dedup_key""",
                        (event.fill_dedup_key, bot_id, self._account_id),
                    )
                    if inserted is None:
                        return
                record = None
                if event.side == "buy" and self._order_tracker is not None:
                    record = await self._order_tracker.get(order_id)
                before = replace(budget)
                reservation_snapshot = self._reservations.get(order_id)
                fill_value = self._apply_fill_settlement(event, budget, record)
                after = replace(budget)
                left = self._reservations.get(order_id)
                await self._persist_fill_settlement(event, budget, fill_value)
        except BaseException:
            if before is not None and after is None:
                after = replace(budget)
                left = self._reservations.get(order_id)
            if (
                before is not None
                and after is not None
                and self._entry_kept(order_id, reservation_snapshot, left)
            ):
                self._revert_budget(budget, before, after)
                self._restore_reservation(order_id, reservation_snapshot)
            raise

    def _apply_fill_settlement(
        self, event: Any, budget: BotBudget, record: Any
    ) -> float:
        """체결 정산의 메모리 갱신(await 없음)을 하고 체결 금액을 돌려준다."""
        fill_value: float = event.quantity * event.price
        commission = event.commission

        if event.side == "buy":
            self._settle_buy_fill(event, budget, record, fill_value, commission)
        else:
            actual_proceeds = fill_value - commission
            budget.returned += actual_proceeds
            budget.available += actual_proceeds

        budget.last_updated = clock.now(UTC)
        return fill_value

    async def _persist_fill_settlement(
        self, event: Any, budget: BotBudget, fill_value: float
    ) -> None:
        """체결 정산의 예산·예약 행 저장과 거래 기록."""
        await self._save_budget(budget)
        if event.side == "buy":
            await self._persist_reservation(event.order_id)
        await self._log_transaction(
            bot_id=event.bot_id,
            tx_type="fill",
            amount=fill_value,
            description=(
                f"{event.side} {event.symbol} {event.quantity} @ {event.price:,.0f}"
            ),
        )

    @staticmethod
    def _revert_budget(target: BotBudget, before: BotBudget, after: BotBudget) -> None:
        """실패한 연산의 증감만 되돌린다(필드가 직후 값 그대로면 직전 값으로)."""
        for name in ("allocated", "available", "reserved", "spent", "returned"):
            current = getattr(target, name)
            old = getattr(before, name)
            new = getattr(after, name)
            setattr(target, name, old if current == new else current - (new - old))
        if target.last_updated == after.last_updated:
            target.last_updated = before.last_updated

    def _settle_buy_fill(
        self,
        event: Any,
        budget: BotBudget,
        record: Any,
        fill_value: float,
        commission: float,
    ) -> None:
        """매수 체결 비례 정산 + terminal 잔여 회수(tracker 기록이 없으면 일괄 정산)."""
        order_id = event.order_id
        actual_cost = fill_value + commission

        if record is None:
            self._settle_buy_full_fill(event, budget, actual_cost)
            return

        entry = self._reservations.get(order_id)
        remaining = entry[1] if entry else 0.0

        covered = min(remaining, actual_cost)
        budget.reserved = max(0.0, budget.reserved - covered)
        budget.spent += actual_cost
        remaining -= covered

        shortfall = actual_cost - covered
        if shortfall > 0:
            budget.available -= shortfall
            logger.warning(
                "market_order_reserve_shortfall: bot=%s order=%s "
                "shortfall=%s actual=%s (available may be negative)",
                event.bot_id,
                order_id,
                f"{shortfall:,.2f}",
                f"{actual_cost:,.2f}",
            )

        terminal = record.ordered_qty > 0 and (
            record.recorded_filled_qty >= record.ordered_qty
        )
        if terminal:
            if remaining > 0:
                budget.reserved = max(0.0, budget.reserved - remaining)
                budget.available += remaining
            self._reservations.pop(order_id, None)
        elif entry is not None:
            self._reservations[order_id] = (entry[0], remaining)

    def _settle_buy_full_fill(
        self, event: Any, budget: BotBudget, actual_cost: float
    ) -> None:
        """tracker 부재 매수 full-fill pop-once 정산 (R1-2 fallback)."""
        entry = self._reservations.pop(event.order_id, None)
        reserved_amount = entry[1] if entry else 0.0
        budget.reserved = max(0.0, budget.reserved - reserved_amount)
        budget.spent += actual_cost
        surplus = reserved_amount - actual_cost
        if surplus > 0:
            budget.available += surplus
        elif surplus < 0:
            extra_cost = -surplus
            budget.available -= extra_cost
            logger.warning(
                "market_order_reserve_shortfall: bot=%s order=%s "
                "extra_cost=%s reserved=%s actual=%s "
                "(available may be negative)",
                event.bot_id,
                event.order_id,
                f"{extra_cost:,.2f}",
                f"{reserved_amount:,.2f}",
                f"{actual_cost:,.2f}",
            )

    async def _on_order_cancelled(self, event: object) -> None:
        """주문 취소 시 예약 해제."""
        from ante.eventbus.events import OrderCancelledEvent

        if not isinstance(event, OrderCancelledEvent):
            return

        if not self._is_my_event(event):
            return

        await self.release_reservation(event.bot_id, event.order_id)

    async def _on_order_failed(self, event: object) -> None:
        """주문 실패 시 예약 해제."""
        from ante.eventbus.events import OrderFailedEvent

        if not isinstance(event, OrderFailedEvent):
            return

        if not self._is_my_event(event):
            return

        await self.release_reservation(event.bot_id, event.order_id)

    async def _on_bot_stopped(self, event: object) -> None:
        """봇 정지 시 열린 주문을 뺀 그 봇의 **잔여 예약**을 회수한다."""
        from ante.eventbus.events import BotStoppedEvent

        if not isinstance(event, BotStoppedEvent):
            return

        if not self._is_my_event(event):
            return

        bot_id = event.bot_id
        looked_up = list(self.get_reservations(bot_id))
        if not looked_up:
            return

        closed = [oid for oid in looked_up if not await self._order_still_open(oid)]
        current = self.get_reservations(bot_id)
        pending = {oid: current[oid] for oid in closed if oid in current}
        if not pending:
            return
        held = len(current) - len(pending)

        total_released = await self._release_bot_reservations(bot_id, pending)

        await self._log_transaction(
            bot_id=bot_id,
            tx_type="bot_stopped_release",
            amount=total_released,
            description=f"{len(pending)}건 예약 해제, {held}건 유지(열린 주문)",
        )
        logger.info(
            "봇 정지 예약 해제: %s -- %d건, %s원, 유지 %d건",
            bot_id,
            len(pending),
            f"{total_released:,.0f}",
            held,
        )

    async def _order_still_open(self, order_id: str) -> bool:
        """추적기에서 열린 주문이거나 조회가 실패한 주문이면 참이다."""
        if self._order_tracker is None:
            return False
        try:
            record = await self._order_tracker.get(order_id)
        except Exception:
            logger.warning(
                "봇 정지: 주문 %s 의 추적 조회 실패 -- 예약 유지",
                order_id,
                exc_info=True,
            )
            return True
        return record is not None and record.status in _OPEN_ORDER_STATUSES

    async def _release_bot_reservations(
        self, bot_id: str, pending: dict[str, float]
    ) -> float:
        """봇의 잔여 예약을 표·행·예산에서 한 트랜잭션으로 회수하고 그 합을 돌려준다."""
        total_released = 0.0
        for order_id, amount in pending.items():
            self._reservations.pop(order_id, None)
            total_released += amount

        budget = self._budgets.get(bot_id)
        changes: tuple[BotBudget, BotBudget] | None = None
        if budget:
            before = replace(budget)
            budget.reserved = max(0.0, budget.reserved - total_released)
            budget.available += total_released
            budget.last_updated = clock.now(UTC)
            changes = (before, replace(budget))

        try:
            async with self._db.transaction():
                if budget:
                    await self._save_budget(budget)
                for order_id in pending:
                    await self._persist_reservation(order_id)
        except BaseException:
            kept = [
                oid
                for oid, amount in pending.items()
                if self._entry_kept(oid, (bot_id, amount), None)
            ]
            if budget and changes is not None:
                self._revert_budget(budget, *self._kept_share(changes, pending, kept))
            for order_id in kept:
                self._restore_reservation(order_id, (bot_id, pending[order_id]))
            raise
        return total_released

    @staticmethod
    def _kept_share(
        changes: tuple[BotBudget, BotBudget],
        pending: dict[str, float],
        kept: list[str],
    ) -> tuple[BotBudget, BotBudget]:
        """일괄 회수의 직전·직후 값을 되돌릴 주문들의 몫만 담은 쌍으로 좁힌다."""
        before, after = changes
        if len(kept) == len(pending):
            return changes
        room = before.reserved - after.reserved
        reserved = 0.0
        available = 0.0
        for order_id, amount in pending.items():
            share = min(amount, room)
            room -= share
            if order_id in kept:
                reserved += share
                available += amount
        narrowed = replace(
            after,
            reserved=after.reserved + reserved,
            available=after.available - available,
        )
        return narrowed, after

    def start_sync(
        self,
        broker: BrokerAdapter | None,
        position_history: PositionHistory,
        interval_seconds: int = 300,
        trading_mode: str = "live",
        price_resolver: Callable[[str], Awaitable[float]] | None = None,
    ) -> None:
        """계좌 잔고 주기적 동기화 시작.

        Args:
            broker: 브로커 어댑터. Virtual 모드에서는 None 허용.
            position_history: 포지션 이력 관리자.
            interval_seconds: 동기화 주기 (초).
            trading_mode: "live" 또는 "virtual".
            price_resolver: Virtual 모드에서 종목 현재가를 조회하는 콜백.
                None이면 avg_entry_price를 fallback으로 사용.
        """
        if self._sync_task and not self._sync_task.done():
            logger.warning("이미 동기화 루프가 실행 중입니다")
            return

        self._sync_interval_seconds = interval_seconds
        self._sync_task = asyncio.create_task(
            self._sync_loop(
                broker,
                position_history,
                interval_seconds,
                trading_mode=trading_mode,
                price_resolver=price_resolver,
            ),
            name=f"treasury-balance-sync-{self._account_id}",
        )
        logger.info(
            "잔고 동기화 시작 (주기: %d초, account=%s, mode=%s)",
            interval_seconds,
            self._account_id,
            trading_mode,
        )

    async def stop_sync(self) -> None:
        """잔고 동기화 중지."""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None
            logger.info("잔고 동기화 중지")

    async def _sync_loop(
        self,
        broker: BrokerAdapter | None,
        position_history: PositionHistory,
        interval_seconds: int,
        trading_mode: str = "live",
        price_resolver: Callable[[str], Awaitable[float]] | None = None,
    ) -> None:
        """주기적 잔고 동기화 루프."""
        try:
            while True:
                try:
                    if trading_mode == "virtual":
                        await self._do_sync_virtual(position_history, price_resolver)
                    else:
                        assert broker is not None, "Live 모드에서는 broker가 필수입니다"
                        await self._do_sync(broker, position_history)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("잔고 동기화 실패 -- 이전 값 유지", exc_info=True)
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise

    def get_synced_price(self, symbol: str) -> tuple[float | None, str | None]:
        """잔고 동기화가 받은 그 종목의 현재가를 동기 조회한다 (#3103).

        신선하면 ``(현재가, None)``, 아니면 ``(None, 상세)``다. 상세는
        ``SYNCED_PRICE_MISSING`` 또는 ``SYNCED_PRICE_STALE``이다. 받은 뒤
        ``2 × interval_seconds``를 넘으면 낡았다. ``start_sync`` 전이거나
        보관한 주기가 유한한 양수가 아니면 늘 ``SYNCED_PRICE_MISSING``이다.
        """
        interval = self._sync_interval_seconds
        if not _is_positive_finite(interval):
            return None, SYNCED_PRICE_MISSING
        entry = self._synced_prices.get(symbol)
        if entry is None:
            return None, SYNCED_PRICE_MISSING
        price, received_at = entry
        if clock.monotonic() - received_at > 2 * float(interval):
            return None, SYNCED_PRICE_STALE
        return price, None

    def _record_synced_price(self, symbol: str, value: object) -> None:
        """검사를 지난 값만 받은 시각과 함께 동기화 시세 표에 덮어쓴다."""
        if _is_positive_finite(value):
            self._synced_prices[symbol] = (float(value), clock.monotonic())

    def _prune_synced_prices(self, handled_symbols: set[str]) -> None:
        """이번 동기화가 다루지 않은 종목을 동기화 시세 표에서 지운다."""
        for symbol in list(self._synced_prices):
            if symbol not in handled_symbols:
                del self._synced_prices[symbol]

    async def _do_sync(
        self,
        broker: BrokerAdapter,
        position_history: PositionHistory,
    ) -> None:
        """한 번의 잔고 동기화 수행 (Live 모드)."""
        from ante.eventbus.events import BalanceSyncedEvent

        balance_data = await broker.get_account_balance()
        await self.sync_balance(balance_data)

        buyable = await broker.get_buyable(_PURCHASABLE_PROBE_SYMBOL)
        self._purchasable_amount = buyable.get(
            "order_buyable_amount", self._purchasable_amount
        )

        broker_positions = await broker.get_positions()
        handled_symbols: set[str] = set()
        for pos in broker_positions:
            handled_symbols.add(pos["symbol"])
            self._record_synced_price(pos["symbol"], pos.get("current_price"))
        internal_positions = await position_history.get_all_positions(
            account_id=self._account_id
        )
        internal_symbols = {p.symbol for p in internal_positions}

        external_purchase = 0.0
        external_eval = 0.0
        for pos in broker_positions:
            if pos["symbol"] not in internal_symbols:
                external_purchase += float(pos.get("avg_price", 0)) * float(
                    pos.get("quantity", 0)
                )
                external_eval += float(pos.get("eval_amount", 0))

        self._external_purchase_amount = external_purchase
        self._external_eval_amount = external_eval
        self._last_synced_at = clock.now(UTC)
        await self._save_state()

        await self._eventbus.publish(
            BalanceSyncedEvent(
                account_id=self._account_id,
                account_balance=self._account_balance,
                purchasable_amount=self._purchasable_amount,
                total_evaluation=self._total_evaluation,
                external_purchase_amount=self._external_purchase_amount,
                external_eval_amount=self._external_eval_amount,
            )
        )
        self._prune_synced_prices(handled_symbols)
        logger.info(
            "잔고 동기화 완료: 예수금=%s, 매수가능=%s, 외부종목=%d건 (account=%s)",
            f"{self._account_balance:,.0f}",
            f"{self._purchasable_amount:,.0f}",
            sum(1 for pos in broker_positions if pos["symbol"] not in internal_symbols),
            self._account_id,
        )

    async def _do_sync_virtual(
        self,
        position_history: PositionHistory,
        price_resolver: Callable[[str], Awaitable[float]] | None = None,
    ) -> None:
        """한 번의 잔고 동기화 수행 (Virtual 모드)."""
        from ante.eventbus.events import BalanceSyncedEvent

        positions = await position_history.get_all_positions(
            account_id=self._account_id
        )

        purchase_amount = 0.0
        eval_amount = 0.0
        handled_symbols: set[str] = set()
        for pos in positions:
            handled_symbols.add(pos.symbol)
            purchase_amount += pos.avg_entry_price * pos.quantity
            if price_resolver:
                try:
                    current_price = await price_resolver(pos.symbol)
                except Exception:
                    logger.debug(
                        "Virtual 시세 조회 실패: %s — avg_entry_price 사용",
                        pos.symbol,
                    )
                    current_price = pos.avg_entry_price
                else:
                    self._record_synced_price(pos.symbol, current_price)
            else:
                current_price = pos.avg_entry_price
            eval_amount += current_price * pos.quantity

        self._purchase_amount = purchase_amount
        self._eval_amount = eval_amount
        self._external_purchase_amount = 0.0
        self._external_eval_amount = 0.0
        self._last_synced_at = clock.now(UTC)
        await self._save_state()

        await self._eventbus.publish(
            BalanceSyncedEvent(
                account_id=self._account_id,
                account_balance=self._account_balance,
                purchasable_amount=self._purchasable_amount,
                total_evaluation=self._total_evaluation,
                external_purchase_amount=0.0,
                external_eval_amount=0.0,
            )
        )
        self._prune_synced_prices(handled_symbols)
        logger.info(
            "Virtual 잔고 동기화 완료: 매수금=%s, 평가금=%s, 포지션=%d건 (account=%s)",
            f"{purchase_amount:,.0f}",
            f"{eval_amount:,.0f}",
            len(positions),
            self._account_id,
        )

    async def sync_balance(self, balance_data: dict[str, float]) -> None:
        """KIS 잔고 데이터로 Treasury 상태 동기화.

        ``purchasable_amount``(주문가능액)는 무인자 ``get_account_balance``
        (``inquire-balance``)가 산출할 수 없어 반환 dict에 없으므로,
        ``sync_balance``는 이를 **읽지 않는다**. 주문가능액은 ``_do_sync``가
        ``BrokerAdapter.get_buyable`` 결과로 별도 주입한다(매수가능액 동기화 규약,
        treasury/04-treasury-interface 참조).
        """
        self._account_balance = balance_data.get("cash", self._account_balance)
        self._total_evaluation = balance_data.get(
            "total_assets", self._total_evaluation
        )
        self._purchase_amount = balance_data.get(
            "purchase_amount", self._purchase_amount
        )
        self._eval_amount = balance_data.get("eval_amount", self._eval_amount)
        self._total_profit_loss = balance_data.get(
            "total_profit_loss", self._total_profit_loss
        )

        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = self._account_balance - total_allocated

        await self._save_state()

    def list_budgets(self) -> list[BotBudget]:
        """전체 봇 예산 목록 반환."""
        return list(self._budgets.values())

    def get_summary(self) -> dict[str, Any]:
        """자금 현황 요약."""
        total_allocated = sum(b.allocated for b in self._budgets.values())
        total_reserved = sum(b.reserved for b in self._budgets.values())

        ante_purchase = self._purchase_amount - self._external_purchase_amount
        ante_eval = self._eval_amount - self._external_eval_amount
        ante_profit_loss = ante_eval - ante_purchase

        total_available = sum(b.available for b in self._budgets.values())
        budget_exceeds_purchasable = (
            self._purchasable_amount > 0 and total_available > self._purchasable_amount
        )

        return {
            "currency": self._currency,
            "account_balance": self._account_balance,
            "purchasable_amount": self._purchasable_amount,
            "total_evaluation": self._total_evaluation,
            "purchase_amount": self._purchase_amount,
            "eval_amount": self._eval_amount,
            "total_profit_loss": self._total_profit_loss,
            "total_allocated": total_allocated,
            "total_reserved": total_reserved,
            "total_available": total_available,
            "unallocated": self._unallocated,
            "bot_count": len(self._budgets),
            "external_purchase_amount": self._external_purchase_amount,
            "external_eval_amount": self._external_eval_amount,
            "ante_purchase_amount": ante_purchase,
            "ante_eval_amount": ante_eval,
            "ante_profit_loss": ante_profit_loss,
            "budget_exceeds_purchasable": budget_exceeds_purchasable,
            "account_number": self._account_number,
            "is_demo_trading": self._is_demo_trading,
            "last_sync_time": self.last_sync_time,
        }

    async def load_from_db(self) -> None:
        """DB에서 자금 상태 복원 (테스트용 리로드 포함).

        기존 메모리 상태를 초기화한 뒤 DB에서 다시 로드한다.
        """
        self._budgets.clear()
        self._reservations.clear()
        await self._load_from_db()

    async def _load_from_db(self) -> None:
        """DB에서 자금 상태 복원."""
        rows = await self._db.fetch_all(
            "SELECT * FROM treasury_state WHERE account_id = ?",
            (self._account_id,),
        )
        if rows:
            r = rows[0]
            self._account_balance = float(r["account_balance"])
            self._purchasable_amount = float(r["purchasable_amount"])
            self._total_evaluation = float(r["total_evaluation"])
            self._purchase_amount = float(r["purchase_amount"])
            self._eval_amount = float(r["eval_amount"])
            self._total_profit_loss = float(r["total_profit_loss"])
            self._external_purchase_amount = float(r["external_purchase_amount"])
            self._external_eval_amount = float(r["external_eval_amount"])
            last_synced = r["last_synced_at"]
            self._last_synced_at = (
                datetime.fromisoformat(last_synced) if last_synced else None
            )

        rows = await self._db.fetch_all(
            "SELECT * FROM bot_budgets WHERE account_id = ?",
            (self._account_id,),
        )
        for r in rows:
            self._budgets[r["bot_id"]] = BotBudget(
                bot_id=r["bot_id"],
                account_id=r["account_id"],
                allocated=float(r["allocated"]),
                available=float(r["available"]),
                reserved=float(r["reserved"]),
                spent=float(r["spent"]),
                returned=float(r["returned"]),
                last_updated=datetime.fromisoformat(r["last_updated"]),
            )

        rows = await self._db.fetch_all(
            "SELECT order_id, bot_id, remaining FROM treasury_reservations "
            "WHERE account_id = ?",
            (self._account_id,),
        )
        for r in rows:
            self._reservations[r["order_id"]] = (r["bot_id"], float(r["remaining"]))
        self._warn_unattributed_reserved()

        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = self._account_balance - total_allocated

    def _warn_unattributed_reserved(self) -> None:
        """봇의 ``reserved``와 그 봇 잔여 예약 합의 차이를 경고만 한다(값은 그대로)."""
        for bot_id, budget in self._budgets.items():
            gap = budget.reserved - sum(self.get_reservations(bot_id).values())
            if abs(gap) > 1e-6:
                logger.warning(
                    "unattributed_reserved: bot=%s account=%s gap=%s",
                    bot_id,
                    self._account_id,
                    f"{gap:,.2f}",
                )

    async def _save_state(self) -> None:
        """계좌 상태 저장."""
        await self._db.execute(
            """INSERT INTO treasury_state
               (account_id, account_balance, purchasable_amount,
                total_evaluation, currency,
                purchase_amount, eval_amount, total_profit_loss,
                external_purchase_amount, external_eval_amount,
                last_synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                 account_balance = excluded.account_balance,
                 purchasable_amount = excluded.purchasable_amount,
                 total_evaluation = excluded.total_evaluation,
                 currency = excluded.currency,
                 purchase_amount = excluded.purchase_amount,
                 eval_amount = excluded.eval_amount,
                 total_profit_loss = excluded.total_profit_loss,
                 external_purchase_amount = excluded.external_purchase_amount,
                 external_eval_amount = excluded.external_eval_amount,
                 last_synced_at = excluded.last_synced_at""",
            (
                self._account_id,
                self._account_balance,
                self._purchasable_amount,
                self._total_evaluation,
                self._currency,
                self._purchase_amount,
                self._eval_amount,
                self._total_profit_loss,
                self._external_purchase_amount,
                self._external_eval_amount,
                self._last_synced_at.isoformat() if self._last_synced_at else None,
            ),
        )

    async def _save_budget(self, budget: BotBudget) -> None:
        """봇 예산 저장."""
        account_id = require_account_id(
            budget.account_id, context="treasury._save_budget"
        )
        await self._db.execute(
            """INSERT INTO bot_budgets
               (bot_id, account_id, allocated, available, reserved,
                spent, returned, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                 account_id = excluded.account_id,
                 allocated = excluded.allocated,
                 available = excluded.available,
                 reserved = excluded.reserved,
                 spent = excluded.spent,
                 returned = excluded.returned,
                 last_updated = excluded.last_updated""",
            (
                budget.bot_id,
                account_id,
                budget.allocated,
                budget.available,
                budget.reserved,
                budget.spent,
                budget.returned,
                budget.last_updated.isoformat(),
            ),
        )

    async def save_daily_snapshot(self, snapshot_date: str) -> None:
        """당일 자산 현황만 스냅샷에 저장 (하위 호환).

        DailyReportEvent 기반의 take_snapshot()이 주 진입점이며,
        이 메서드는 이벤트 발행 전 자산 현황만 먼저 기록할 때 사용한다.

        Args:
            snapshot_date: YYYY-MM-DD 형식의 날짜 문자열.
        """
        summary = self.get_summary()
        await self._db.execute(
            """INSERT INTO treasury_daily_snapshots
               (account_id, snapshot_date, total_asset,
                ante_eval_amount, ante_purchase_amount,
                unallocated, account_balance, total_allocated, bot_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                 total_asset = excluded.total_asset,
                 ante_eval_amount = excluded.ante_eval_amount,
                 ante_purchase_amount = excluded.ante_purchase_amount,
                 unallocated = excluded.unallocated,
                 account_balance = excluded.account_balance,
                 total_allocated = excluded.total_allocated,
                 bot_count = excluded.bot_count""",
            (
                self._account_id,
                snapshot_date,
                summary.get("ante_eval_amount", 0.0) + summary.get("unallocated", 0.0),
                summary.get("ante_eval_amount", 0.0),
                summary.get("ante_purchase_amount", 0.0),
                summary.get("unallocated", 0.0),
                summary.get("account_balance", 0.0),
                summary.get("total_allocated", 0.0),
                summary.get("bot_count", 0),
            ),
        )

    async def take_snapshot(self, event: object) -> dict[str, Any] | None:
        """DailyReportEvent 수신 시 자산 현황 + 성과 필드를 합쳐 스냅샷 저장.

        Args:
            event: DailyReportEvent 인스턴스.

        Returns:
            저장된 스냅샷 dict. DailyReportEvent가 아닌 경우 None.
        """
        from ante.eventbus.events import DailyReportEvent

        if not isinstance(event, DailyReportEvent):
            return None

        snapshot_date = event.report_date
        summary = self.get_summary()

        snapshot_data: dict[str, Any] = {
            "account_id": self._account_id,
            "snapshot_date": snapshot_date,
            "total_asset": summary.get("ante_eval_amount", 0.0)
            + summary.get("unallocated", 0.0),
            "ante_eval_amount": summary.get("ante_eval_amount", 0.0),
            "ante_purchase_amount": summary.get("ante_purchase_amount", 0.0),
            "unallocated": summary.get("unallocated", 0.0),
            "account_balance": summary.get("account_balance", 0.0),
            "total_allocated": summary.get("total_allocated", 0.0),
            "bot_count": summary.get("bot_count", 0),
            "daily_pnl": event.daily_pnl,
            "daily_return": event.daily_return,
            "net_trade_amount": event.net_trade_amount,
            "unrealized_pnl": event.unrealized_pnl,
        }

        await self._db.execute(
            """INSERT INTO treasury_daily_snapshots
               (account_id, snapshot_date, total_asset,
                ante_eval_amount, ante_purchase_amount,
                unallocated, account_balance, total_allocated, bot_count,
                daily_pnl, daily_return, net_trade_amount, unrealized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                 total_asset = excluded.total_asset,
                 ante_eval_amount = excluded.ante_eval_amount,
                 ante_purchase_amount = excluded.ante_purchase_amount,
                 unallocated = excluded.unallocated,
                 account_balance = excluded.account_balance,
                 total_allocated = excluded.total_allocated,
                 bot_count = excluded.bot_count,
                 daily_pnl = excluded.daily_pnl,
                 daily_return = excluded.daily_return,
                 net_trade_amount = excluded.net_trade_amount,
                 unrealized_pnl = excluded.unrealized_pnl""",
            (
                snapshot_data["account_id"],
                snapshot_data["snapshot_date"],
                snapshot_data["total_asset"],
                snapshot_data["ante_eval_amount"],
                snapshot_data["ante_purchase_amount"],
                snapshot_data["unallocated"],
                snapshot_data["account_balance"],
                snapshot_data["total_allocated"],
                snapshot_data["bot_count"],
                snapshot_data["daily_pnl"],
                snapshot_data["daily_return"],
                snapshot_data["net_trade_amount"],
                snapshot_data["unrealized_pnl"],
            ),
        )

        await self._cleanup_old_snapshots()

        logger.info(
            "일별 스냅샷 저장: account=%s, date=%s, pnl=%.0f",
            self._account_id,
            snapshot_date,
            event.daily_pnl,
        )

        return snapshot_data

    async def get_daily_snapshot(self, snapshot_date: str) -> dict[str, Any] | None:
        """특정 날짜의 스냅샷 조회.

        Args:
            snapshot_date: YYYY-MM-DD 형식의 날짜 문자열.

        Returns:
            스냅샷 딕셔너리 또는 None.
        """
        rows = await self._db.fetch_all(
            """SELECT * FROM treasury_daily_snapshots
               WHERE account_id = ? AND snapshot_date = ?""",
            (self._account_id, snapshot_date),
        )
        if not rows:
            return None
        return self._row_to_snapshot(rows[0])

    async def get_prev_day_snapshot(self, before_date: str) -> dict[str, Any] | None:
        """``snapshot_date < before_date``인 가장 최근 스냅샷. 없으면 None."""
        rows = await self._db.fetch_all(
            """SELECT * FROM treasury_daily_snapshots
               WHERE account_id = ? AND snapshot_date < ?
               ORDER BY snapshot_date DESC LIMIT 1""",
            (self._account_id, before_date),
        )
        if not rows:
            return None
        return self._row_to_snapshot(rows[0])

    async def get_latest_snapshot(self) -> dict[str, Any] | None:
        """가장 최근 일별 스냅샷 조회.

        Returns:
            최신 스냅샷 딕셔너리 또는 None.
        """
        rows = await self._db.fetch_all(
            """SELECT * FROM treasury_daily_snapshots
               WHERE account_id = ?
               ORDER BY snapshot_date DESC LIMIT 1""",
            (self._account_id,),
        )
        if not rows:
            return None
        return self._row_to_snapshot(rows[0])

    async def get_snapshots(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """날짜 범위의 스냅샷 조회.

        Args:
            start_date: 시작 날짜 (YYYY-MM-DD, 포함).
            end_date: 종료 날짜 (YYYY-MM-DD, 포함).

        Returns:
            스냅샷 딕셔너리 리스트 (날짜순 정렬).
        """
        rows = await self._db.fetch_all(
            """SELECT * FROM treasury_daily_snapshots
               WHERE account_id = ? AND snapshot_date >= ? AND snapshot_date <= ?
               ORDER BY snapshot_date ASC""",
            (self._account_id, start_date, end_date),
        )
        return [self._row_to_snapshot(r) for r in rows]

    async def _cleanup_old_snapshots(self) -> None:
        """5년 초과 스냅샷 자동 삭제."""
        cutoff = (clock.now(UTC) - timedelta(days=_SNAPSHOT_RETENTION_DAYS)).strftime(
            "%Y-%m-%d"
        )
        await self._db.execute(
            """DELETE FROM treasury_daily_snapshots
               WHERE account_id = ? AND snapshot_date < ?""",
            (self._account_id, cutoff),
        )

    @staticmethod
    def _row_to_snapshot(row: Any) -> dict[str, Any]:
        """DB 행을 스냅샷 딕셔너리로 변환."""
        return {
            "account_id": row["account_id"],
            "snapshot_date": row["snapshot_date"],
            "total_asset": float(row["total_asset"]),
            "ante_eval_amount": float(row["ante_eval_amount"]),
            "ante_purchase_amount": float(row["ante_purchase_amount"]),
            "unallocated": float(row["unallocated"]),
            "account_balance": float(row["account_balance"]),
            "total_allocated": float(row["total_allocated"]),
            "bot_count": int(row["bot_count"]),
            "daily_pnl": float(row["daily_pnl"]),
            "daily_return": float(row["daily_return"]),
            "net_trade_amount": float(row["net_trade_amount"]),
            "unrealized_pnl": float(row["unrealized_pnl"]),
            "created_at": row["created_at"],
        }

    async def _on_daily_report(self, event: object) -> None:
        """DailyReportEvent 핸들러 -- 일별 스냅샷 저장."""
        from ante.eventbus.events import DailyReportEvent

        if not isinstance(event, DailyReportEvent):
            return

        if not self._is_my_event(event):
            return

        await self.take_snapshot(event)

    async def _log_transaction(
        self,
        bot_id: str,
        tx_type: TransactionType,
        amount: float,
        description: str = "",
    ) -> None:
        """자금 거래 이력 기록."""
        await self._db.execute(
            """INSERT INTO treasury_transactions
               (bot_id, account_id, transaction_type, amount, description)
               VALUES (?, ?, ?, ?, ?)""",
            (bot_id, self._account_id, tx_type, amount, description),
        )
