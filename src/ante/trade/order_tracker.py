"""OrderTracker — 추적 주문 영속 + 누적 체결 단조 advance."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ante.account.scoping import require_account_id
from ante.core import clock

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)


def _utc_now_text() -> str:
    """시계의 현재 UTC 시각을 ``YYYY-MM-DD HH:MM:SS`` 로."""
    return clock.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class OrderStatus(StrEnum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


ORDER_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.OPEN: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.FAILED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.FILLED: {OrderStatus.FILLED},
    OrderStatus.CANCELLED: {OrderStatus.CANCELLED},
    OrderStatus.REJECTED: {OrderStatus.REJECTED},
    OrderStatus.FAILED: {OrderStatus.FAILED},
    OrderStatus.EXPIRED: {OrderStatus.EXPIRED},
}

OPEN_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED}
)
TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(OrderStatus) - OPEN_STATUSES
LATE_FILL_WATCH_STATUSES: frozenset[OrderStatus] = frozenset(
    {OrderStatus.CANCELLED, OrderStatus.EXPIRED}
)

ORDER_TRACKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_tracker (
    order_id            TEXT PRIMARY KEY,
    account_id          TEXT NOT NULL,
    bot_id              TEXT NOT NULL,
    strategy_id         TEXT NOT NULL,
    broker_order_id     TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    side                TEXT NOT NULL,
    order_type          TEXT NOT NULL DEFAULT '',
    ordered_qty         REAL NOT NULL DEFAULT 0.0,
    order_price         REAL,
    exchange            TEXT,
    recorded_filled_qty REAL NOT NULL DEFAULT 0.0,
    avg_fill_price      REAL NOT NULL DEFAULT 0.0,
    status              TEXT NOT NULL DEFAULT 'open',
    submitted_at        TEXT,
    submitted_date      TEXT NOT NULL,
    last_polled_at      TEXT,
    terminal_at         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_order_tracker_broker
    ON order_tracker(account_id, broker_order_id, submitted_date);
CREATE INDEX IF NOT EXISTS idx_order_tracker_open
    ON order_tracker(account_id, status);
"""


@dataclass(frozen=True, slots=True)
class RecordFillResult:
    """``record_fill`` CAS 결과.

    Attributes:
        delta: 적용된 증분(``new_cumulative - 이전 recorded``). no-op이면 0.
        confirmed_cumulative: **CAS ``RETURNING recorded_filled_qty`` 로 확정된**
            누적 체결량. ``delta>0`` 일 때 advance 된 확정값(= new_cumulative)을
            담고, no-op(``delta<=0``)이면 직전 recorded 값을 그대로 반영한다.
        new_status: advance 후 확정된 주문 상태(``filled``·``partially_filled``,
            종결된 행이면 유지한 그 상태). no-op 이면 직전 status 다.
    """

    delta: float
    confirmed_cumulative: float
    new_status: str = ""


@dataclass(frozen=True, slots=True)
class OrderTrackerRecord:
    """추적 주문 스냅샷."""

    order_id: str
    account_id: str
    bot_id: str
    strategy_id: str
    broker_order_id: str
    symbol: str
    side: str
    order_type: str
    ordered_qty: float
    recorded_filled_qty: float
    avg_fill_price: float
    status: str
    submitted_at: str | None
    submitted_date: str
    order_price: float | None = None
    exchange: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> OrderTrackerRecord:
        raw_price = row.get("order_price")
        return cls(
            order_id=row["order_id"],
            account_id=row["account_id"],
            bot_id=row["bot_id"],
            strategy_id=row["strategy_id"],
            broker_order_id=row["broker_order_id"],
            symbol=row["symbol"],
            side=row["side"],
            order_type=row.get("order_type", "") or "",
            ordered_qty=float(row.get("ordered_qty", 0.0) or 0.0),
            recorded_filled_qty=float(row.get("recorded_filled_qty", 0.0) or 0.0),
            avg_fill_price=float(row.get("avg_fill_price", 0.0) or 0.0),
            status=row["status"],
            submitted_at=row.get("submitted_at"),
            submitted_date=row["submitted_date"],
            order_price=float(raw_price) if raw_price is not None else None,
            exchange=row.get("exchange"),
        )

    def to_open_order_dict(self) -> dict[str, object]:
        """통일 OpenOrder dict 스키마로 매핑.

        OrderView ``get_open_orders`` 의 SSOT 스키마. 전략/telegram/IPC 소비자가
        공통으로 의존한다. ``remaining_qty = ordered_qty - recorded_filled_qty``
        (중복방어 판단용). ``amount`` (예약 금액)는 Treasury 도메인이지
        OrderView 가시성이 아니므로 **제외**한다.

        스키마 SSOT: ``docs/specs/strategy/03-04-provider-and-views.md``.
        """
        remaining = self.ordered_qty - self.recorded_filled_qty
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "ordered_qty": self.ordered_qty,
            "recorded_filled_qty": self.recorded_filled_qty,
            "remaining_qty": remaining if remaining > 0 else 0.0,
            "status": self.status,
            "submitted_at": self.submitted_at,
        }


class OrderTracker:
    """추적 주문 영속 저장소 + 누적 체결 단조 advance.

    ``record_fill`` 은 ``FillApplier`` 의 단일 트랜잭션 + ``asyncio.Lock`` 안에서만
    호출되어야 한다 (멱등·crash 원자성은 FillApplier 가 보장). ``open``/
    ``mark_terminal``/``expire_stale`` 는 자체 commit 을 소유한다 — 외부
    ``Database.transaction()`` 내부에서 호출하지 않는다.

    인메모리 open 캐시: LIVE ``ctx.get_open_orders()`` 의 sync 백엔드.
    캐시는 **commit 된 DB 상태의 미러**일 뿐 진리원이 아니다(DB 가 SSOT).
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._open_cache: dict[tuple[str, str, str], OrderTrackerRecord] = {}

    async def initialize(self) -> None:
        """스키마 생성 + open 캐시 warm.

        DB 의 open/partially_filled row 로 캐시를 적재한다. warm 완료 전 sync
        조회는 빈 결과(cold)일 수 있으며, 이는 best-effort 한계다(DB 가 진리원,
        잔여 안전망은 reconciler).
        """
        await self._db.execute_script(ORDER_TRACKER_SCHEMA)
        await self._warm_open_cache()
        logger.info("OrderTracker 초기화 완료 (open 캐시 %d건)", len(self._open_cache))

    async def _warm_open_cache(self) -> None:
        """DB 의 non-terminal 주문을 인메모리 open 캐시에 적재."""
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        rows = await self._db.fetch_all(
            f"""SELECT * FROM order_tracker
                 WHERE status IN ({placeholders})""",
            tuple(sorted(OPEN_STATUSES)),
        )
        self._open_cache.clear()
        for row in rows:
            record = OrderTrackerRecord.from_row(row)
            self._open_cache[self._cache_key(record)] = record

    @staticmethod
    def _cache_key(record: OrderTrackerRecord) -> tuple[str, str, str]:
        """캐시 키 = (account_id, bot_id, order_id)."""
        return (record.account_id, record.bot_id, record.order_id)

    def _evict_open_cache(self, order_id: str) -> None:
        """terminal 전이 공통 헬퍼 — order_id 의 캐시 엔트리를 제거."""
        for key in [k for k in self._open_cache if k[2] == order_id]:
            del self._open_cache[key]

    async def open(
        self,
        *,
        order_id: str,
        account_id: str,
        bot_id: str,
        strategy_id: str,
        broker_order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        ordered_qty: float,
        submitted_date: str,
        submitted_at: str | None = None,
        order_price: float | None = None,
        exchange: str | None = None,
    ) -> None:
        """``OrderSubmittedEvent`` 로 추적 주문 seed.

        order_id PK 재제출(중복 이벤트)은 무시한다 (``ON CONFLICT DO NOTHING``).
        같은 ``(account_id, broker_order_id, submitted_date)`` UNIQUE 충돌도
        동일하게 무시되어 seed 멱등성을 보장한다.

        **외부 ``Database.transaction()`` 안에서 호출 금지(자체 commit 소유)**.
        """
        validated = require_account_id(account_id, context="order_tracker.open")
        inserted = await self._db.execute_fetch_one(
            """INSERT INTO order_tracker
                   (order_id, account_id, bot_id, strategy_id, broker_order_id,
                    symbol, side, order_type, ordered_qty, order_price, exchange,
                    recorded_filled_qty, avg_fill_price, status, submitted_at,
                    submitted_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?, ?, ?)
               ON CONFLICT DO NOTHING
               RETURNING order_id""",
            (
                order_id,
                validated,
                bot_id,
                strategy_id,
                broker_order_id,
                symbol,
                side,
                order_type,
                ordered_qty,
                order_price,
                exchange,
                OrderStatus.OPEN,
                submitted_at,
                submitted_date,
            ),
        )
        if inserted is not None:
            record = OrderTrackerRecord(
                order_id=order_id,
                account_id=validated,
                bot_id=bot_id,
                strategy_id=strategy_id,
                broker_order_id=broker_order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                ordered_qty=ordered_qty,
                recorded_filled_qty=0.0,
                avg_fill_price=0.0,
                status=OrderStatus.OPEN.value,
                submitted_at=submitted_at,
                submitted_date=submitted_date,
                order_price=order_price,
                exchange=exchange,
            )
            self._open_cache[self._cache_key(record)] = record
        logger.debug(
            "주문 추적 seed: %s / odno=%s %s %s qty=%s (account=%s, inserted=%s)",
            order_id,
            broker_order_id,
            side,
            symbol,
            ordered_qty,
            validated,
            inserted is not None,
        )

    async def record_fill(
        self,
        order_id: str,
        new_cumulative: float,
        avg_price: float,
    ) -> RecordFillResult:
        """원자 CAS advance. ``RecordFillResult(delta, confirmed_cumulative)`` 반환.

        ``delta = new_cumulative - 이전 recorded_filled_qty``.
        ``delta <= 0`` 이면 ``delta=0`` no-op(직전 recorded 를 confirmed 로 반영).
        읽은 상태가 종결이면 상태와 ``terminal_at`` 을 유지한다.

        **반드시 FillApplier 의 ``Database.transaction()`` + Lock 안에서 호출.**

        invariant: 이 메서드는 **인메모리 open 캐시를 절대 건드리지 않는다.**
        """
        row = await self._db.execute_fetch_one(
            """SELECT recorded_filled_qty, ordered_qty, status, terminal_at
                 FROM order_tracker WHERE order_id = ?""",
            (order_id,),
        )
        if row is None:
            return RecordFillResult(delta=0.0, confirmed_cumulative=0.0, new_status="")

        prev = float(row["recorded_filled_qty"] or 0.0)
        ordered = float(row["ordered_qty"] or 0.0)
        delta = new_cumulative - prev
        if delta <= 0:
            return RecordFillResult(
                delta=0.0,
                confirmed_cumulative=prev,
                new_status=str(row["status"]),
            )

        prev_status = str(row["status"])
        now = _utc_now_text()
        keep_terminal = prev_status in TERMINAL_STATUSES
        terminal_at: str | None
        if keep_terminal:
            new_status = prev_status
            terminal_at = row["terminal_at"]
        elif ordered > 0 and new_cumulative >= ordered:
            new_status = OrderStatus.FILLED.value
            terminal_at = now
        else:
            new_status = OrderStatus.PARTIALLY_FILLED.value
            terminal_at = None
        updated = await self._db.execute_fetch_one(
            """UPDATE order_tracker
                  SET recorded_filled_qty = ?,
                      avg_fill_price = ?,
                      status = ?,
                      last_polled_at = ?,
                      terminal_at = ?
                WHERE order_id = ? AND recorded_filled_qty < ? AND status = ?
            RETURNING recorded_filled_qty""",
            (
                new_cumulative,
                avg_price,
                new_status,
                now,
                terminal_at,
                order_id,
                new_cumulative,
                prev_status,
            ),
        )
        if updated is None:
            return RecordFillResult(
                delta=0.0, confirmed_cumulative=prev, new_status=prev_status
            )
        if keep_terminal:
            logger.warning(
                "종결된 주문에 늦은 체결 반영(상태 유지): order=%s status=%s "
                "delta=%s cumulative=%s",
                order_id,
                prev_status,
                delta,
                new_cumulative,
            )
        confirmed = float(updated["recorded_filled_qty"] or 0.0)
        return RecordFillResult(
            delta=delta, confirmed_cumulative=confirmed, new_status=new_status
        )

    def mirror_fill_to_cache(
        self,
        order_id: str,
        confirmed_cumulative: float,
        new_status: str,
    ) -> None:
        """**post-commit 전용** 체결 캐시 미러 (sync).

        FillApplier 가 ``Database.transaction()`` 블록이 **정상 COMMIT 된 직후**에만
        호출한다(rollback 경로에서는 호출되지 않는다). 캐시의
        ``recorded_filled_qty``/``status`` 를 **CAS 확정값**(``confirmed_cumulative``)
        으로 미러링하고, terminal(``filled``)이면 evict 한다. 입력 observed 값이
        아니라 DB 가 RETURNING 으로 확정한 값만 반영해 단조성을 보존한다.
        """
        for key, record in list(self._open_cache.items()):
            if key[2] != order_id:
                continue
            if new_status == OrderStatus.FILLED or new_status in TERMINAL_STATUSES:
                del self._open_cache[key]
                return
            self._open_cache[key] = OrderTrackerRecord(
                order_id=record.order_id,
                account_id=record.account_id,
                bot_id=record.bot_id,
                strategy_id=record.strategy_id,
                broker_order_id=record.broker_order_id,
                symbol=record.symbol,
                side=record.side,
                order_type=record.order_type,
                ordered_qty=record.ordered_qty,
                recorded_filled_qty=confirmed_cumulative,
                avg_fill_price=record.avg_fill_price,
                status=new_status or record.status,
                submitted_at=record.submitted_at,
                submitted_date=record.submitted_date,
                order_price=record.order_price,
                exchange=record.exchange,
            )
            return

    async def mark_terminal(self, order_id: str, status: str) -> None:
        """주문을 종료 상태로 표기 (취소/거부/실패/만료).

        이미 종결된 주문은 덮어쓰지 않는다 (첫 종결이 우선).

        DB write 후 ``_evict_open_cache`` 로 캐시에서 제거(terminal 은 open
        이 아니므로). **외부 ``Database.transaction()`` 안에서 호출 금지(자체 commit
        소유)**. 이미 종결됐던 주문은 캐시에 없으므로 evict 가 no-op 이고,
        non-terminal 이었던 주문만 제거된다.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"비-terminal status: {status!r}")
        await self._db.execute(
            """UPDATE order_tracker
                  SET status = ?, terminal_at = ?
                WHERE order_id = ? AND status IN (?, ?)""",
            (
                status,
                _utc_now_text(),
                order_id,
                OrderStatus.OPEN,
                OrderStatus.PARTIALLY_FILLED,
            ),
        )
        self._evict_open_cache(order_id)

    def get_open_orders_for_bot_sync(
        self, account_id: str, bot_id: str
    ) -> list[OrderTrackerRecord]:
        """``(account_id, bot_id)`` 의 non-terminal 주문 sync 조회.

        LIVE ``ctx.get_open_orders()`` 의 백엔드. 이벤트 루프 스레드 위 await 된
        코루틴 내부에서 전략이 sync 호출하므로 **DB I/O 없이 인메모리 캐시만** 읽는다.
        캐시는 OPEN_STATUSES(open/partially_filled) 만 보관하므로 terminal 은
        자연히 제외된다. ``(account_id, bot_id)`` 스코프로 필터해 단일계좌 다중봇에서
        타-봇 주문 누출을 막는다. cold-cache 시 빈 결과(best-effort) — known-limitation.
        """
        validated = require_account_id(
            account_id, context="order_tracker.get_open_orders_for_bot_sync"
        )
        records = [
            record
            for (acct, bid, _oid), record in self._open_cache.items()
            if acct == validated and bid == bot_id
        ]
        records.sort(key=lambda r: (r.submitted_at or "", r.order_id))
        return records

    async def get_open_orders(self, account_id: str) -> list[OrderTrackerRecord]:
        """계좌의 non-terminal(open/partially_filled) 주문."""
        validated = require_account_id(
            account_id, context="order_tracker.get_open_orders"
        )
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        rows = await self._db.fetch_all(
            f"""SELECT * FROM order_tracker
                 WHERE account_id = ? AND status IN ({placeholders})
                 ORDER BY submitted_at""",
            (validated, *sorted(OPEN_STATUSES)),
        )
        return [OrderTrackerRecord.from_row(r) for r in rows]

    async def get_open_orders_for(
        self,
        account_id: str,
        bot_id: str,
        symbol: str,
        side: str,
    ) -> list[OrderTrackerRecord]:
        """``(account_id, bot_id, symbol, side)`` 의 non-terminal 주문.

        PositionReconciler 의 self-submitted fill 분류(reconciler self-check)에
        쓰인다. ``open``/``partially_filled`` 인 주문만 반환하므로, FillApplier 가
        아직 기록 못 한(``recorded_filled_qty < ordered_qty``) ante 주문이 정확히
        이 범위에 든다. terminal(filled/expired/cancelled/...) 주문은 제외되어,
        주문 해소 후 잔여 broker 초과분이 외부 거래로 재검출되게 한다(R2-1 bounded
        known-limitation). 상세: ``docs/specs/trade/03-07-position-reconciler.md``.
        """
        validated = require_account_id(
            account_id, context="order_tracker.get_open_orders_for"
        )
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        rows = await self._db.fetch_all(
            f"""SELECT * FROM order_tracker
                 WHERE account_id = ? AND bot_id = ? AND symbol = ? AND side = ?
                   AND status IN ({placeholders})
                 ORDER BY submitted_at""",
            (validated, bot_id, symbol, side, *sorted(OPEN_STATUSES)),
        )
        return [OrderTrackerRecord.from_row(r) for r in rows]

    async def lookup_order_id(
        self,
        account_id: str,
        broker_order_id: str,
        submitted_date: str,
    ) -> str | None:
        """관측(account/broker_order_id/observed_date) → 내부 order_id 매핑.

        spec §4.1: 「열린 행이면서 ``submitted_date <= observed_date``」 또는
        「상태와 무관하게 ``submitted_date == observed_date``」인 행 가운데
        ``submitted_date`` 최신(MAX) 1건을 고른다. 종결된 행은 같은 영업일의
        체결만 이어 받는다(odno 일자 재사용 격리).
        """
        validated = require_account_id(
            account_id, context="order_tracker.lookup_order_id"
        )
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        row = await self._db.fetch_one(
            f"""SELECT order_id FROM order_tracker
                 WHERE account_id = ? AND broker_order_id = ?
                   AND ((submitted_date <= ? AND status IN ({placeholders}))
                        OR submitted_date = ?)
                 ORDER BY submitted_date DESC
                 LIMIT 1""",
            (
                validated,
                broker_order_id,
                submitted_date,
                *sorted(OPEN_STATUSES),
                submitted_date,
            ),
        )
        return row["order_id"] if row else None

    async def get_late_fill_watch(
        self, account_id: str, terminal_since: str
    ) -> list[OrderTrackerRecord]:
        """늦은 체결 감시 대상(spec 18 §6.3).

        ``cancelled``·``expired`` 이면서 ``recorded_filled_qty < ordered_qty`` 이고
        ``terminal_at >= terminal_since`` (UTC ``YYYY-MM-DD HH:MM:SS``)인 행이다.
        """
        validated = require_account_id(
            account_id, context="order_tracker.get_late_fill_watch"
        )
        rows = await self._db.fetch_all(
            """SELECT * FROM order_tracker
                 WHERE account_id = ? AND status IN (?, ?)
                   AND recorded_filled_qty < ordered_qty
                   AND terminal_at >= ?
                 ORDER BY submitted_date""",
            (validated, *sorted(LATE_FILL_WATCH_STATUSES), terminal_since),
        )
        return [OrderTrackerRecord.from_row(r) for r in rows]

    async def get(self, order_id: str) -> OrderTrackerRecord | None:
        """order_id 로 추적 주문 단건 조회 (이벤트 정체성 복원용)."""
        row = await self._db.fetch_one(
            "SELECT * FROM order_tracker WHERE order_id = ?",
            (order_id,),
        )
        return OrderTrackerRecord.from_row(row) if row else None

    async def find_by_broker_order(
        self,
        account_id: str,
        broker_order_id: str,
        submitted_date: str,
    ) -> OrderTrackerRecord | None:
        """관측(account/broker_order_id/observed_date) → 추적 레코드 (terminal 포함).

        ``lookup_order_id`` 와 달리 **status 무관**(terminal 포함)으로 매핑한다.

        scope/정렬은 ``submitted_date <= observed_date`` 의 최신(MAX) 1건이다
        (일자 재사용 격리·결정성 유지).
        """
        validated = require_account_id(
            account_id, context="order_tracker.find_by_broker_order"
        )
        row = await self._db.fetch_one(
            """SELECT * FROM order_tracker
                 WHERE account_id = ? AND broker_order_id = ?
                   AND submitted_date <= ?
                 ORDER BY submitted_date DESC
                 LIMIT 1""",
            (validated, broker_order_id, submitted_date),
        )
        return OrderTrackerRecord.from_row(row) if row else None

    async def expire_stale(self, account_id: str, before_date: str) -> int:
        """``submitted_date < before_date`` 인 ``open`` 주문을 ``expired`` 로 표기한다.

        spec §8: 부분 체결(``partially_filled``)은 만료 대상이 **아니다** — ``open``
        상태만 만료한다(I2). fill-recovery 가 poll-first 로 다운타임 체결을 먼저
        복구하면 해당 주문은 ``filled``/``partially_filled`` 로 전이되어 자연히 이
        만료에서 제외된다. 만료 건수를 반환한다.
        """
        validated = require_account_id(account_id, context="order_tracker.expire_stale")
        expired = await self._db.execute_fetch_all(
            """UPDATE order_tracker
                   SET status = ?, terminal_at = ?
                 WHERE account_id = ? AND submitted_date < ?
                   AND status = ?
            RETURNING order_id""",
            (
                OrderStatus.EXPIRED,
                _utc_now_text(),
                validated,
                before_date,
                OrderStatus.OPEN,
            ),
        )
        count = len(expired)
        if count:
            for row in expired:
                self._evict_open_cache(row["order_id"])
            logger.info(
                "OrderTracker EOD 만료: account=%s, %d건 (before=%s)",
                validated,
                count,
                before_date,
            )
        return count
