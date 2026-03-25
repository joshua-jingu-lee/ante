"""Treasury -- 계좌별 중앙 자금(예산) 관리."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ante.treasury.models import BotBudget

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.position import PositionHistory

logger = logging.getLogger(__name__)

TREASURY_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_budgets (
    bot_id       TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL DEFAULT '',
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
"""

# 기존 key-value 테이블에서 계좌별 행 구조로 마이그레이션
TREASURY_MIGRATION_V2 = """
-- bot_budgets에 account_id 컬럼 추가 (이미 존재하면 무시)
ALTER TABLE bot_budgets ADD COLUMN account_id TEXT NOT NULL DEFAULT '';
"""

TREASURY_MIGRATION_V2_STATE = """
-- treasury_state 재생성: key-value -> 계좌별 행 구조
CREATE TABLE IF NOT EXISTS treasury_state_new (
    account_id         TEXT PRIMARY KEY,
    account_balance    REAL NOT NULL DEFAULT 0,
    purchasable_amount REAL NOT NULL DEFAULT 0,
    total_evaluation   REAL NOT NULL DEFAULT 0,
    currency           TEXT NOT NULL DEFAULT 'KRW',
    last_synced_at     TEXT
);

-- 기존 데이터 마이그레이션
INSERT OR IGNORE INTO treasury_state_new (
    account_id, account_balance,
    purchasable_amount, total_evaluation
)
SELECT 'default',
    COALESCE(
        (SELECT value FROM treasury_state
         WHERE key = 'account_balance'), 0),
    COALESCE(
        (SELECT value FROM treasury_state
         WHERE key = 'purchasable_amount'), 0),
    COALESCE(
        (SELECT value FROM treasury_state
         WHERE key = 'total_evaluation'), 0);

DROP TABLE IF EXISTS treasury_state;
ALTER TABLE treasury_state_new RENAME TO treasury_state;
"""

TREASURY_TRANSACTIONS_MIGRATION = """
ALTER TABLE treasury_transactions ADD COLUMN account_id TEXT DEFAULT '';
"""

# treasury_state에 평가액/매입액 필드 추가 마이그레이션
_STATE_MIGRATION_COLUMNS = [
    ("purchase_amount", "REAL NOT NULL DEFAULT 0"),
    ("eval_amount", "REAL NOT NULL DEFAULT 0"),
    ("total_profit_loss", "REAL NOT NULL DEFAULT 0"),
    ("external_purchase_amount", "REAL NOT NULL DEFAULT 0"),
    ("external_eval_amount", "REAL NOT NULL DEFAULT 0"),
]

# daily_snapshots 성과 필드 추가 마이그레이션
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

# 5년 초과 스냅샷 자동 삭제 기준
_SNAPSHOT_RETENTION_DAYS = 365 * 5


class Treasury:
    """계좌별 중앙 자금(예산) 관리자.

    각 계좌(Account)에 대해 하나의 인스턴스가 생성되며,
    해당 계좌의 잔고를 소유하고, 봇별로 예산을 배분한다.
    """

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        account_id: str = "default",
        currency: str = "KRW",
        buy_commission_rate: float = 0.00015,
        sell_commission_rate: float = 0.00195,
        bot_status_checker: Callable[[str], str] | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._account_id = account_id
        self._currency = currency
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        self._bot_status_checker = bot_status_checker

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
        self._reservations: dict[
            str, tuple[str, float]
        ] = {}  # order_id -> (bot_id, amount)
        self._sync_task: asyncio.Task[None] | None = None

        # KIS 계좌 메타 정보 (broker 연결 후 set_account_info로 설정)
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

        # 마이그레이션: bot_budgets에 account_id 컬럼 추가
        try:
            await self._db.execute_script(TREASURY_MIGRATION_V2)
        except Exception:
            pass  # 이미 컬럼이 존재하면 무시

        # 마이그레이션: treasury_transactions에 account_id 컬럼 추가
        try:
            await self._db.execute_script(TREASURY_TRANSACTIONS_MIGRATION)
        except Exception:
            pass  # 이미 컬럼이 존재하면 무시

        # 마이그레이션: treasury_state 평가액/매입액 필드 추가
        for col_name, col_def in _STATE_MIGRATION_COLUMNS:
            try:
                await self._db.execute_script(
                    f"ALTER TABLE treasury_state ADD COLUMN {col_name} {col_def};"
                )
            except Exception:
                pass  # 이미 컬럼이 존재하면 무시

        # 마이그레이션: daily_snapshots 성과 필드 추가
        for col_name, col_def in _SNAPSHOT_MIGRATION_COLUMNS:
            try:
                await self._db.execute_script(
                    f"ALTER TABLE treasury_daily_snapshots "
                    f"ADD COLUMN {col_name} {col_def};"
                )
            except Exception:
                pass  # 이미 컬럼이 존재하면 무시

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

    # -- 계좌 잔고 -----------------------------------------------

    async def set_account_balance(self, balance: float) -> None:
        """계좌 잔고 설정. 미할당 자금을 자동 재계산."""
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

    def update_commission_rates(
        self, buy_commission_rate: float, sell_commission_rate: float
    ) -> None:
        """수수료율 업데이트 (DynamicConfig 변경 시 호출)."""
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        logger.info(
            "수수료율 갱신: buy=%s, sell=%s",
            buy_commission_rate,
            sell_commission_rate,
        )

    # -- 예산 조회 -----------------------------------------------

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

    # -- 예산 할당/회수 ------------------------------------------

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

    async def allocate(self, bot_id: str, amount: float) -> bool:
        """봇에 예산 할당. 미할당 자금에서 차감."""
        self._check_bot_stopped(bot_id)
        if amount <= 0 or self._unallocated < amount:
            return False

        if bot_id not in self._budgets:
            self._budgets[bot_id] = BotBudget(
                bot_id=bot_id, account_id=self._account_id
            )

        budget = self._budgets[bot_id]
        budget.allocated += amount
        budget.available += amount
        budget.last_updated = datetime.now(UTC)
        self._unallocated -= amount

        await self._save_budget(budget)
        await self._save_state()
        await self._log_transaction(bot_id, "allocate", amount)
        logger.info(
            "예산 할당: %s -> %s (account=%s)", bot_id, amount, self._account_id
        )
        return True

    async def deallocate(self, bot_id: str, amount: float) -> bool:
        """봇에서 예산 회수. 가용 예산 범위 내에서만 가능."""
        self._check_bot_stopped(bot_id)
        budget = self._budgets.get(bot_id)
        if not budget or amount <= 0 or budget.available < amount:
            return False

        budget.allocated -= amount
        budget.available -= amount
        budget.last_updated = datetime.now(UTC)
        self._unallocated += amount

        await self._save_budget(budget)
        await self._save_state()
        await self._log_transaction(bot_id, "deallocate", amount)
        logger.info(
            "예산 회수: %s <- %s (account=%s)", bot_id, amount, self._account_id
        )
        return True

    async def release_budget(self, bot_id: str) -> float:
        """봇의 할당액 전액을 미할당으로 환수하고 budget 레코드를 삭제한다.

        봇 삭제 시 호출된다. bot_status_checker를 우회하여 어떤 상태에서든
        환수가 가능하다 (delete_bot에서 이미 봇을 중지한 뒤 호출하므로).

        Args:
            bot_id: 대상 봇 ID.

        Returns:
            환수된 금액. budget이 없으면 0.0.
        """
        budget = self._budgets.pop(bot_id, None)
        if not budget:
            # 인메모리에 없으면 DB에서 직접 조회 (서버 재시작 후 또는
            # 봇 account_id와 Treasury account_id가 달라 로드되지 않은 경우)
            # WAL 모드에서는 writer commit 후 reader가 즉시 볼 수 있으므로
            # public API인 fetch_one(reader 커넥션)을 사용한다.
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

        # DB에서 budget 레코드 삭제
        await self._db.execute(
            "DELETE FROM bot_budgets WHERE bot_id = ?",
            (bot_id,),
        )
        await self._save_state()
        await self._log_transaction(
            bot_id, "release", released, "봇 삭제에 의한 예산 전액 환수"
        )

        # 해당 봇의 미체결 예약도 정리
        pending_orders = [
            oid for oid, (bid, _) in self._reservations.items() if bid == bot_id
        ]
        for oid in pending_orders:
            self._reservations.pop(oid, None)

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
        미할당 잔액이 부족하면 InsufficientFundsError를 발생시킨다.

        Args:
            bot_id: 대상 봇 ID.
            target_amount: 목표 할당 금액.

        Raises:
            InsufficientFundsError: 증액 시 미할당 잔액 부족.
            BotNotStoppedError: 봇이 운용 중인 경우.
            ValueError: 목표 금액이 음수인 경우.
        """
        from ante.treasury.exceptions import InsufficientFundsError

        if target_amount < 0:
            raise ValueError(f"목표 금액은 0 이상이어야 합니다: {target_amount}")

        budget = self._budgets.get(bot_id)
        current = budget.allocated if budget else 0.0
        diff = target_amount - current

        if diff == 0:
            return

        if diff > 0:
            # 증액
            if self._unallocated < diff:
                raise InsufficientFundsError(
                    f"미할당 잔액 부족: 필요 {diff:,.0f}, 가용 {self._unallocated:,.0f}"
                )
            result = await self.allocate(bot_id, diff)
            if not result:
                raise InsufficientFundsError(
                    f"예산 할당 실패: bot_id={bot_id}, amount={diff}"
                )
        else:
            # 감액
            decrease = abs(diff)
            result = await self.deallocate(bot_id, decrease)
            if not result:
                available = budget.available if budget else 0.0
                raise InsufficientFundsError(
                    f"예산 회수 실패: 회수 요청 {decrease:,.0f}, "
                    f"가용 예산 {available:,.0f}"
                )

        logger.info(
            "예산 변경: %s -- %s -> %s (차이: %s%s)",
            bot_id,
            f"{current:,.0f}",
            f"{target_amount:,.0f}",
            "+" if diff > 0 else "",
            f"{diff:,.0f}",
        )

    # -- 주문 자금 예약/해제 -------------------------------------

    async def reserve_for_order(
        self, bot_id: str, order_id: str, amount: float
    ) -> bool:
        """주문 제출 시 자금 예약."""
        if amount <= 0:
            raise ValueError("amount must be positive")

        budget = self._budgets.get(bot_id)
        if not budget or budget.available < amount:
            return False

        budget.available -= amount
        budget.reserved += amount
        budget.last_updated = datetime.now(UTC)
        self._reservations[order_id] = (bot_id, amount)

        await self._save_budget(budget)
        return True

    async def release_reservation(self, bot_id: str, order_id: str) -> None:
        """주문 취소/실패 시 예약 해제."""
        budget = self._budgets.get(bot_id)
        entry = self._reservations.pop(order_id, None)
        amount = entry[1] if entry else 0.0
        if not budget or amount <= 0:
            return

        budget.reserved = max(0.0, budget.reserved - amount)
        budget.available += amount
        budget.last_updated = datetime.now(UTC)

        await self._save_budget(budget)

    def get_reservations(self, bot_id: str) -> dict[str, float]:
        """특정 봇의 미체결 예약 내역 조회.

        Returns:
            {order_id: amount, ...}
        """
        return {
            oid: amt for oid, (bid, amt) in self._reservations.items() if bid == bot_id
        }

    # -- 이벤트 핸들러 -------------------------------------------

    def _is_my_event(self, event: object) -> bool:
        """이벤트가 이 Treasury의 계좌에 해당하는지 확인."""
        account_id = getattr(event, "account_id", "")
        # account_id가 비어있으면 (하위 호환) 처리
        if not account_id:
            return True
        return account_id == self._account_id

    async def _on_order_validated(self, event: object) -> None:
        """룰 검증 통과 후 자금 예약 -> 승인/거부 발행."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderRejectedEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderValidatedEvent):
            return

        if not self._is_my_event(event):
            return

        price = event.price or 0.0
        estimated_cost = event.quantity * price
        commission_estimate = estimated_cost * self._buy_commission_rate
        total_reserve = estimated_cost + commission_estimate

        if event.side == "buy":
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
                reserved_amount=(total_reserve if event.side == "buy" else 0.0),
                account_id=self._account_id,
            )
        )

    async def _on_order_filled(self, event: object) -> None:
        """체결 이벤트 처리 -- 예약 자금 정산."""
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return

        if not self._is_my_event(event):
            return

        budget = self._budgets.get(event.bot_id)
        if not budget:
            return

        fill_value = event.quantity * event.price
        commission = event.commission

        if event.side == "buy":
            entry = self._reservations.pop(event.order_id, None)
            reserved_amount = entry[1] if entry else 0.0
            actual_cost = fill_value + commission
            budget.reserved = max(0.0, budget.reserved - reserved_amount)
            budget.spent += actual_cost
            surplus = reserved_amount - actual_cost
            if surplus > 0:
                budget.available += surplus
        else:
            actual_proceeds = fill_value - commission
            budget.returned += actual_proceeds
            budget.available += actual_proceeds

        budget.last_updated = datetime.now(UTC)
        await self._save_budget(budget)
        await self._log_transaction(
            bot_id=event.bot_id,
            tx_type="fill",
            amount=fill_value,
            description=(
                f"{event.side} {event.symbol} {event.quantity} @ {event.price:,.0f}"
            ),
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
        """봇 중지 시 해당 봇의 모든 예약 자금 일괄 해제."""
        from ante.eventbus.events import BotStoppedEvent

        if not isinstance(event, BotStoppedEvent):
            return

        if not self._is_my_event(event):
            return

        bot_id = event.bot_id
        pending = self.get_reservations(bot_id)
        if not pending:
            return

        total_released = 0.0
        for order_id, amount in pending.items():
            self._reservations.pop(order_id, None)
            total_released += amount

        budget = self._budgets.get(bot_id)
        if budget:
            budget.reserved = max(0.0, budget.reserved - total_released)
            budget.available += total_released
            budget.last_updated = datetime.now(UTC)
            await self._save_budget(budget)

        await self._log_transaction(
            bot_id=bot_id,
            tx_type="bot_stopped_release",
            amount=total_released,
            description=f"{len(pending)}건 예약 해제",
        )
        logger.info(
            "봇 중지 예약 해제: %s -- %d건, %s원",
            bot_id,
            len(pending),
            f"{total_released:,.0f}",
        )

    # -- 잔고 동기화 ---------------------------------------------

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

    async def _do_sync(
        self,
        broker: BrokerAdapter,
        position_history: PositionHistory,
    ) -> None:
        """한 번의 잔고 동기화 수행 (Live 모드)."""
        from ante.eventbus.events import BalanceSyncedEvent

        # 1) KIS 계좌 잔고 (output2)
        balance_data = await broker.get_account_balance()
        await self.sync_balance(balance_data)

        # 2) KIS 보유종목 (output1) + Trade 내부 포지션 대조
        broker_positions = await broker.get_positions()
        internal_positions = await position_history.get_all_positions()
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
        await self._save_state()

        self._last_synced_at = datetime.now(UTC)

        # 3) 이벤트 발행
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
        """한 번의 잔고 동기화 수행 (Virtual 모드).

        Trade DB의 포지션 데이터로 purchase/eval 금액을 직접 계산한다.
        브로커 연결 없이 동작하므로 외부 종목은 항상 0이다.
        """
        from ante.eventbus.events import BalanceSyncedEvent

        positions = await position_history.get_all_positions()

        purchase_amount = 0.0
        eval_amount = 0.0
        for pos in positions:
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
                current_price = pos.avg_entry_price
            eval_amount += current_price * pos.quantity

        self._purchase_amount = purchase_amount
        self._eval_amount = eval_amount
        self._external_purchase_amount = 0.0
        self._external_eval_amount = 0.0
        await self._save_state()

        self._last_synced_at = datetime.now(UTC)

        # 이벤트 발행
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
        logger.info(
            "Virtual 잔고 동기화 완료: 매수금=%s, 평가금=%s, 포지션=%d건 (account=%s)",
            f"{purchase_amount:,.0f}",
            f"{eval_amount:,.0f}",
            len(positions),
            self._account_id,
        )

    async def sync_balance(self, balance_data: dict[str, float]) -> None:
        """KIS 잔고 데이터로 Treasury 상태 동기화."""
        self._account_balance = balance_data.get("cash", self._account_balance)
        self._purchasable_amount = balance_data.get(
            "purchasable_amount", self._purchasable_amount
        )
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

        # 미할당 재계산
        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = self._account_balance - total_allocated

        await self._save_state()

    # -- 모니터링 -------------------------------------------------

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

    # -- DB 영속화 -----------------------------------------------

    async def load_from_db(self) -> None:
        """DB에서 자금 상태 복원 (테스트용 리로드 포함).

        기존 메모리 상태를 초기화한 뒤 DB에서 다시 로드한다.
        """
        self._budgets.clear()
        self._reservations.clear()
        await self._load_from_db()

    async def _load_from_db(self) -> None:
        """DB에서 자금 상태 복원."""
        # 계좌별 상태 로드
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

        # 봇 예산 (계좌별 필터링)
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

        # 미할당 재계산
        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = self._account_balance - total_allocated

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
                budget.account_id,
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

        # 오래된 스냅샷 자동 삭제
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
        cutoff = (
            datetime.now(UTC) - timedelta(days=_SNAPSHOT_RETENTION_DAYS)
        ).strftime("%Y-%m-%d")
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
        tx_type: str,
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
