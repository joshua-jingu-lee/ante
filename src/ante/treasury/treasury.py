"""Treasury — 중앙 자금(예산) 관리."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
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
    transaction_type TEXT NOT NULL,
    amount           REAL NOT NULL,
    description      TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS treasury_state (
    key   TEXT PRIMARY KEY,
    value REAL NOT NULL
);
"""


class Treasury:
    """중앙 자금(예산) 관리자.

    전체 계좌 잔고를 소유하고, 봇별로 예산을 배분하며,
    예산 범위 내에서 거래가 이루어지도록 관리한다.
    """

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        commission_rate: float = 0.00015,
        sell_tax_rate: float = 0.0023,
        bot_status_checker: Callable[[str], str] | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._commission_rate = commission_rate
        self._sell_tax_rate = sell_tax_rate
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
        ] = {}  # order_id → (bot_id, amount)
        self._sync_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """스키마 생성 + DB 복원 + EventBus 구독."""
        await self._db.execute_script(TREASURY_SCHEMA)
        await self._load_from_db()
        self._subscribe_events()
        logger.info("Treasury 초기화 완료")

    def _subscribe_events(self) -> None:
        """EventBus 이벤트 구독."""
        from ante.eventbus.events import (
            BotStoppedEvent,
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

    # ── 계좌 잔고 ───────────────────────────────────

    async def set_account_balance(self, balance: float) -> None:
        """계좌 잔고 설정. 미할당 자금을 자동 재계산."""
        self._account_balance = balance
        total_allocated = sum(b.allocated for b in self._budgets.values())
        self._unallocated = balance - total_allocated
        await self._save_state()
        logger.info("계좌 잔고 설정: %s", balance)

    @property
    def account_balance(self) -> float:
        return self._account_balance

    @property
    def unallocated(self) -> float:
        return self._unallocated

    @property
    def commission_rate(self) -> float:
        return self._commission_rate

    @property
    def sell_tax_rate(self) -> float:
        return self._sell_tax_rate

    def set_bot_status_checker(self, checker: Callable[[str], str]) -> None:
        """봇 상태 확인 콜백 설정 (초기화 후 BotManager 연결 시 호출)."""
        self._bot_status_checker = checker

    def update_commission_rates(
        self, commission_rate: float, sell_tax_rate: float
    ) -> None:
        """수수료율 업데이트 (DynamicConfig 변경 시 호출)."""
        self._commission_rate = commission_rate
        self._sell_tax_rate = sell_tax_rate
        logger.info(
            "수수료율 갱신: commission=%s, sell_tax=%s",
            commission_rate,
            sell_tax_rate,
        )

    # ── 예산 조회 ───────────────────────────────────

    async def get_available(self, bot_id: str) -> float:
        """봇의 가용 예산 조회."""
        budget = self._budgets.get(bot_id)
        return budget.available if budget else 0.0

    async def get_budget(self, bot_id: str) -> BotBudget | None:
        """봇의 예산 상태 조회."""
        return self._budgets.get(bot_id)

    def get_budget_sync(self, bot_id: str) -> BotBudget | None:
        """봇의 예산 상태 동기 조회 (인메모리). PortfolioView용."""
        return self._budgets.get(bot_id)

    # ── 예산 할당/회수 ──────────────────────────────

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
            self._budgets[bot_id] = BotBudget(bot_id=bot_id)

        budget = self._budgets[bot_id]
        budget.allocated += amount
        budget.available += amount
        budget.last_updated = datetime.now(UTC)
        self._unallocated -= amount

        await self._save_budget(budget)
        await self._save_state()
        await self._log_transaction(bot_id, "allocate", amount)
        logger.info("예산 할당: %s → %s", bot_id, amount)
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
        logger.info("예산 회수: %s ← %s", bot_id, amount)
        return True

    # ── 주문 자금 예약/해제 ─────────────────────────

    async def reserve_for_order(
        self, bot_id: str, order_id: str, amount: float
    ) -> bool:
        """주문 제출 시 자금 예약."""
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

    # ── 이벤트 핸들러 ───────────────────────────────

    async def _on_order_validated(self, event: object) -> None:
        """룰 검증 통과 후 자금 예약 → 승인/거부 발행."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderRejectedEvent,
            OrderValidatedEvent,
        )

        if not isinstance(event, OrderValidatedEvent):
            return

        price = event.price or 0.0
        estimated_cost = event.quantity * price
        commission_estimate = estimated_cost * self._commission_rate
        total_reserve = estimated_cost + commission_estimate

        if event.side == "buy":
            success = await self.reserve_for_order(
                event.bot_id, event.order_id, total_reserve
            )
            if not success:
                available = await self.get_available(event.bot_id)
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
            )
        )

    async def _on_order_filled(self, event: object) -> None:
        """체결 이벤트 처리 — 예약 자금 정산."""
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
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
        await self.release_reservation(event.bot_id, event.order_id)

    async def _on_order_failed(self, event: object) -> None:
        """주문 실패 시 예약 해제."""
        from ante.eventbus.events import OrderFailedEvent

        if not isinstance(event, OrderFailedEvent):
            return
        await self.release_reservation(event.bot_id, event.order_id)

    async def _on_bot_stopped(self, event: object) -> None:
        """봇 중지 시 해당 봇의 모든 예약 자금 일괄 해제."""
        from ante.eventbus.events import BotStoppedEvent

        if not isinstance(event, BotStoppedEvent):
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
            "봇 중지 예약 해제: %s — %d건, %s원",
            bot_id,
            len(pending),
            f"{total_released:,.0f}",
        )

    # ── 잔고 동기화 ────────────────────────────────

    async def start_sync(
        self,
        broker: BrokerAdapter,
        position_history: PositionHistory,
        interval_seconds: int = 300,
    ) -> None:
        """KIS 계좌 잔고 주기적 동기화 시작."""
        if self._sync_task and not self._sync_task.done():
            logger.warning("이미 동기화 루프가 실행 중입니다")
            return

        self._sync_task = asyncio.create_task(
            self._sync_loop(broker, position_history, interval_seconds),
            name="treasury-balance-sync",
        )
        logger.info("잔고 동기화 시작 (주기: %d초)", interval_seconds)

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
        broker: BrokerAdapter,
        position_history: PositionHistory,
        interval_seconds: int,
    ) -> None:
        """주기적 잔고 동기화 루프."""
        try:
            while True:
                try:
                    await self._do_sync(broker, position_history)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning("잔고 동기화 실패 — 이전 값 유지", exc_info=True)
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise

    async def _do_sync(
        self,
        broker: BrokerAdapter,
        position_history: PositionHistory,
    ) -> None:
        """한 번의 잔고 동기화 수행."""
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

        # 3) 이벤트 발행
        await self._eventbus.publish(
            BalanceSyncedEvent(
                account_balance=self._account_balance,
                purchasable_amount=self._purchasable_amount,
                total_evaluation=self._total_evaluation,
                external_purchase_amount=self._external_purchase_amount,
                external_eval_amount=self._external_eval_amount,
            )
        )
        logger.info(
            "잔고 동기화 완료: 예수금=%s, 매수가능=%s, 외부종목=%d건",
            f"{self._account_balance:,.0f}",
            f"{self._purchasable_amount:,.0f}",
            sum(1 for pos in broker_positions if pos["symbol"] not in internal_symbols),
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

    # ── 모니터링 ────────────────────────────────────

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
        }

    # ── DB 영속화 ───────────────────────────────────

    _STATE_FIELDS = (
        "account_balance",
        "unallocated",
        "purchasable_amount",
        "total_evaluation",
        "purchase_amount",
        "eval_amount",
        "total_profit_loss",
        "external_purchase_amount",
        "external_eval_amount",
    )

    async def _load_from_db(self) -> None:
        """DB에서 자금 상태 복원."""
        rows = await self._db.fetch_all("SELECT key, value FROM treasury_state")
        state = {r["key"]: float(r["value"]) for r in rows}

        self._account_balance = state.get("account_balance", 0.0)
        self._unallocated = state.get("unallocated", 0.0)
        self._purchasable_amount = state.get("purchasable_amount", 0.0)
        self._total_evaluation = state.get("total_evaluation", 0.0)
        self._purchase_amount = state.get("purchase_amount", 0.0)
        self._eval_amount = state.get("eval_amount", 0.0)
        self._total_profit_loss = state.get("total_profit_loss", 0.0)
        self._external_purchase_amount = state.get("external_purchase_amount", 0.0)
        self._external_eval_amount = state.get("external_eval_amount", 0.0)

        # 봇 예산
        rows = await self._db.fetch_all("SELECT * FROM bot_budgets")
        for r in rows:
            self._budgets[r["bot_id"]] = BotBudget(
                bot_id=r["bot_id"],
                allocated=float(r["allocated"]),
                available=float(r["available"]),
                reserved=float(r["reserved"]),
                spent=float(r["spent"]),
                returned=float(r["returned"]),
                last_updated=datetime.fromisoformat(r["last_updated"]),
            )

    async def _save_state(self) -> None:
        """계좌 상태 저장."""
        field_map = {
            "account_balance": self._account_balance,
            "unallocated": self._unallocated,
            "purchasable_amount": self._purchasable_amount,
            "total_evaluation": self._total_evaluation,
            "purchase_amount": self._purchase_amount,
            "eval_amount": self._eval_amount,
            "total_profit_loss": self._total_profit_loss,
            "external_purchase_amount": self._external_purchase_amount,
            "external_eval_amount": self._external_eval_amount,
        }
        for key, value in field_map.items():
            await self._db.execute(
                """INSERT INTO treasury_state (key, value)
                   VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )

    async def _save_budget(self, budget: BotBudget) -> None:
        """봇 예산 저장."""
        await self._db.execute(
            """INSERT INTO bot_budgets
               (bot_id, allocated, available, reserved,
                spent, returned, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(bot_id) DO UPDATE SET
                 allocated = excluded.allocated,
                 available = excluded.available,
                 reserved = excluded.reserved,
                 spent = excluded.spent,
                 returned = excluded.returned,
                 last_updated = excluded.last_updated""",
            (
                budget.bot_id,
                budget.allocated,
                budget.available,
                budget.reserved,
                budget.spent,
                budget.returned,
                budget.last_updated.isoformat(),
            ),
        )

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
               (bot_id, transaction_type, amount, description)
               VALUES (?, ?, ?, ?)""",
            (bot_id, tx_type, amount, description),
        )
