"""OrderTracker — 추적 주문 영속 + 누적 체결 단조 advance (#1946).

체결 반영(fill-recovery) 경로의 권위 있는 추적 저장소.
``OrderSubmittedEvent`` 로 추적 주문을 seed하고, 스트림/폴이 관측한 누적 체결량을
단조(monotonic) advance한다.

identity (구조적 종결):
- PK = 내부 ``order_id`` (``OrderSubmittedEvent`` 의 ante uuid4 — 생성상 전역 유일).
- ``(account_id, broker_order_id, submitted_date)`` = UNIQUE 인덱스 + 조회 키.
  KIS ``odno`` (broker_order_id) 는 계좌 간/paper·live/영업일 재사용으로 충돌
  가능하므로 broker_order_id 단독 키는 쓰지 않는다.

상세 설계: ``docs/specs/trade/03-08-fill-recovery.md``,
``docs/specs/broker-adapter/18-fill-recovery.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ante.account.scoping import require_account_id

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

# non-terminal status — 폴/스트림 매핑 및 EOD 만료 대상.
OPEN_STATUSES: frozenset[str] = frozenset({"open", "partially_filled"})
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"filled", "cancelled", "rejected", "failed", "expired"}
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
    """``record_fill`` CAS 결과 (#1949).

    Attributes:
        delta: 적용된 증분(``new_cumulative - 이전 recorded``). no-op이면 0.
        confirmed_cumulative: **CAS ``RETURNING recorded_filled_qty`` 로 확정된**
            누적 체결량. ``delta>0`` 일 때 advance 된 확정값(= new_cumulative)을
            담고, no-op(``delta<=0``)이면 직전 recorded 값을 그대로 반영한다.

            outbox/이벤트의 결정적 ``fill_dedup_key`` 는 **이 확정값**으로 생성해야
            한다(입력 ``observed_cumulative`` 가 아니다). 동일 advance 경계는 항상
            같은 확정값을 내므로, 재전달 시 키가 결정적이다.
    """

    delta: float
    confirmed_cumulative: float


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

    @classmethod
    def from_row(cls, row: dict) -> OrderTrackerRecord:
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
        )


class OrderTracker:
    """추적 주문 영속 저장소 + 누적 체결 단조 advance.

    ``record_fill`` 은 ``FillApplier`` 의 단일 트랜잭션 + ``asyncio.Lock`` 안에서만
    호출되어야 한다 (멱등·crash 원자성은 FillApplier 가 보장).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(ORDER_TRACKER_SCHEMA)
        logger.info("OrderTracker 초기화 완료")

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
    ) -> None:
        """``OrderSubmittedEvent`` 로 추적 주문 seed.

        order_id PK 재제출(중복 이벤트)은 무시한다 (``ON CONFLICT DO NOTHING``).
        같은 ``(account_id, broker_order_id, submitted_date)`` UNIQUE 충돌도
        동일하게 무시되어 seed 멱등성을 보장한다.
        """
        validated = require_account_id(account_id, context="order_tracker.open")
        await self._db.execute(
            """INSERT INTO order_tracker
                   (order_id, account_id, bot_id, strategy_id, broker_order_id,
                    symbol, side, order_type, ordered_qty, recorded_filled_qty,
                    avg_fill_price, status, submitted_at, submitted_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 'open', ?, ?)
               ON CONFLICT DO NOTHING""",
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
                submitted_at,
                submitted_date,
            ),
        )
        logger.debug(
            "주문 추적 seed: %s / odno=%s %s %s qty=%s (account=%s)",
            order_id,
            broker_order_id,
            side,
            symbol,
            ordered_qty,
            validated,
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
        ``delta > 0`` 이면 recorded 를 new_cumulative 로 갱신하고 status 를
        부분/완료로 전이한 뒤, **CAS ``RETURNING recorded_filled_qty`` 로 확정된
        누적값**을 ``confirmed_cumulative`` 로 반환한다(#1949).

        ``confirmed_cumulative`` 는 outbox/이벤트의 결정적 ``fill_dedup_key`` 산출
        기준이다. 입력 ``new_cumulative`` 가 아니라 DB 가 RETURNING 으로 돌려준
        값을 노출해, 재전달 시 키 비결정성을 없앤다.

        **반드시 FillApplier 의 ``Database.transaction()`` + Lock 안에서 호출.**
        writer 연결에서 현재값을 읽고(``execute_fetch_one``) 진행 중인 트랜잭션의
        일관된 상태를 본 뒤 CAS UPDATE 하므로, 단일 writer + Lock 으로 read↔update
        사이 race 가 없다.
        """
        row = await self._db.execute_fetch_one(
            """SELECT recorded_filled_qty, ordered_qty, status
                 FROM order_tracker WHERE order_id = ?""",
            (order_id,),
        )
        if row is None:
            return RecordFillResult(delta=0.0, confirmed_cumulative=0.0)

        prev = float(row["recorded_filled_qty"] or 0.0)
        ordered = float(row["ordered_qty"] or 0.0)
        delta = new_cumulative - prev
        if delta <= 0:
            # 관측 역전 또는 이미 반영됨 — 단조성 유지, no-op. 확정값은 직전 recorded.
            return RecordFillResult(delta=0.0, confirmed_cumulative=prev)

        # terminal(취소/거부/실패/만료) 이후에도 잔여 체결이 관측되면 부분/완료로
        # 되돌린다. CAS WHERE 절은 단조성(recorded < :c)만 강제한다.
        new_status = (
            "filled"
            if ordered > 0 and new_cumulative >= ordered
            else ("partially_filled")
        )
        updated = await self._db.execute_fetch_one(
            """UPDATE order_tracker
                  SET recorded_filled_qty = ?,
                      avg_fill_price = ?,
                      status = ?,
                      last_polled_at = datetime('now'),
                      terminal_at = CASE WHEN ? = 'filled'
                                         THEN datetime('now') ELSE NULL END
                WHERE order_id = ? AND recorded_filled_qty < ?
            RETURNING recorded_filled_qty""",
            (
                new_cumulative,
                avg_price,
                new_status,
                new_status,
                order_id,
                new_cumulative,
            ),
        )
        if updated is None:
            # 동시 advance 로 다른 호출이 먼저 recorded 를 올림 — 단조성 보존, no-op.
            # (단일 Lock 경로에선 발생하지 않으나 방어적으로 처리.)
            return RecordFillResult(delta=0.0, confirmed_cumulative=prev)
        # CAS RETURNING 으로 확정된 누적값. fill_dedup_key 의 결정적 기준.
        confirmed = float(updated["recorded_filled_qty"] or 0.0)
        return RecordFillResult(delta=delta, confirmed_cumulative=confirmed)

    async def mark_terminal(self, order_id: str, status: str) -> None:
        """주문을 종료 상태로 표기 (취소/거부/실패/만료).

        이미 ``filled`` 인 주문은 덮어쓰지 않는다 (체결 완료가 우선).
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"비-terminal status: {status!r}")
        await self._db.execute(
            """UPDATE order_tracker
                  SET status = ?, terminal_at = datetime('now')
                WHERE order_id = ? AND status != 'filled'""",
            (status, order_id),
        )

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
        """``(account_id, bot_id, symbol, side)`` 의 non-terminal 주문 (#1950).

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

        spec §4.1 scope: **non-terminal** 이면서 추적 ``submitted_date`` 가 관측
        영업일 **이하**(``submitted_date <= observed_date``)인 주문을 매핑한다.
        정확매칭(``= observed_date``)이 아니라 ``<=`` 로 완화하는 이유 (I6):

        - 폴이 관측한 KIS ``ord_dt``(주문일자)는 tracker seed 의
          ``business_date_kst()`` 와 보통 동일하나, KST 영업일 rollover 나 timezone
          drift 로 미세하게 어긋날 수 있다. 전일(또는 그 이전) 영업일에 seed 된
          non-terminal 주문이 다운타임 중 체결돼 당일 history 로 관측될 때, 정확
          매칭이면 매핑이 누락되어 복구가 실패한다. ``<=`` 가 이를 덮는다.
        - 일자 재사용 격리는 유지된다: 같은 ``broker_order_id`` 의 과거 주문은
          체결/취소/만료로 **terminal** 이 되어 매핑 대상에서 제외되고, 미래
          영업일(``submitted_date > observed_date``) seed 는 ``<=`` 가 배제한다.
        - 같은 odno 의 non-terminal 이 여러 영업일에 동시 존재하는 경합에서는
          ``submitted_date`` 최신(MAX) 1건을 골라 "가장 최근 주문 우선" 으로
          결정론적이게 한다.
        """
        validated = require_account_id(
            account_id, context="order_tracker.lookup_order_id"
        )
        placeholders = ", ".join("?" for _ in OPEN_STATUSES)
        row = await self._db.fetch_one(
            f"""SELECT order_id FROM order_tracker
                 WHERE account_id = ? AND broker_order_id = ?
                   AND submitted_date <= ? AND status IN ({placeholders})
                 ORDER BY submitted_date DESC
                 LIMIT 1""",
            (validated, broker_order_id, submitted_date, *sorted(OPEN_STATUSES)),
        )
        return row["order_id"] if row else None

    async def get(self, order_id: str) -> OrderTrackerRecord | None:
        """order_id 로 추적 주문 단건 조회 (이벤트 정체성 복원용)."""
        row = await self._db.fetch_one(
            "SELECT * FROM order_tracker WHERE order_id = ?",
            (order_id,),
        )
        return OrderTrackerRecord.from_row(row) if row else None

    async def expire_stale(self, account_id: str, before_date: str) -> int:
        """``submitted_date < before_date`` 인 **genuinely-dead** ``open`` 만
        ``expired`` 표기.

        spec §8: EOD 경과 open 중 **history 체결이 관측되지 않은** genuinely-dead
        주문(pending 에도 없음)만 만료한다. 부분 체결(``partially_filled``)은
        체결이 관측·진행 중이므로 만료 대상이 **아니다** — ``open`` 상태만
        만료한다(I2). fill-recovery 가 poll-first 로 다운타임 체결을 먼저 복구하면
        해당 주문은 ``filled``/``partially_filled`` 로 전이되어 자연히 이 만료에서
        제외된다. 이로써 일중 미체결 주문의 무한 폴·phantom pending 은 막되, 미복구
        체결분을 영구 만료/오분류하지 않는다(I7). 만료 건수를 반환한다.
        """
        validated = require_account_id(account_id, context="order_tracker.expire_stale")
        before = await self._db.fetch_one(
            """SELECT COUNT(*) AS c FROM order_tracker
                 WHERE account_id = ? AND submitted_date < ?
                   AND status = 'open'""",
            (validated, before_date),
        )
        count = int(before["c"]) if before else 0
        if count:
            await self._db.execute(
                """UPDATE order_tracker
                       SET status = 'expired', terminal_at = datetime('now')
                     WHERE account_id = ? AND submitted_date < ?
                       AND status = 'open'""",
                (validated, before_date),
            )
            logger.info(
                "OrderTracker EOD 만료: account=%s, %d건 (before=%s)",
                validated,
                count,
                before_date,
            )
        return count
