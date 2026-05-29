"""FillOutbox — 체결 이벤트 transactional outbox (#1949).

#1946 이후 ``recorded_filled_qty`` advance + ``TradeRecord`` insert +
``PositionHistory.on_trade`` 는 단일 ``Database.transaction()`` 으로 묶여
positions/trades crash-safe exactly-once 를 보장한다. 그러나 ``OrderFilledEvent``
는 **commit 이후** 알림으로 발행되므로, **commit↔publish 사이 narrow crash
window** 에서는 다운스트림 소비자(Treasury 정산·전략 ``on_fill``·notification)로의
**이벤트 전달이 유실**될 수 있었다(#1946 R4 bounded-limitation).

FillOutbox 는 그 crash window 를 닫는다:

1. ``FillApplier`` 가 체결 적용 트랜잭션 **안**(recorded advance + trade + position
   과 동일 원자 커밋)에서 outbox row 를 INSERT 한다. commit 이 성공하면 이벤트
   payload 도 반드시 영속화돼 있다 → **무손실(durability)**.
2. ``FillOutboxPublisher`` 워커가 미발행 row 를 읽어 ``OrderFilledEvent`` 를
   **publish 성공 → mark published 순서**(역순 금지)로 발행한다. 기동 시 미발행분을
   재전달(at-least-once)하므로 commit-후-crash 에서도 이벤트가 결국 전달된다.

전달 시맨틱은 **at-least-once** 다. publish↔mark 사이 micro-window 에서 같은 row 가
두 번 발행될 수 있으나, 각 이벤트는 결정적 ``fill_dedup_key``(CAS 로 확정된
``order_id:confirmed_cumulative``)를 실어 보내므로 소비자가 멱등 처리할 수 있다.
**소비자 멱등화 자체는 본 이슈(#1949) 범위 밖이며 별도 이슈(#1957)에서 해소**한다.
#1949 는 outbox 무손실 전달 + 결정적 키 제공까지만 책임진다.

상세 설계: ``docs/specs/eventbus/eventbus.md``(전달 시맨틱),
``docs/specs/broker-adapter/18-fill-recovery.md``(§5.2 durability 해소).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# outbox 테이블 DDL (db-schema 생성기가 *_SCHEMA plain-string 상수로 추출하므로
# f-string 으로 쓰지 않는다). UNIQUE(fill_dedup_key) 가 같은 체결의 중복 outbox
# row 생성을 막아, 같은 fill 을 두 번 관측해도 row 는 1개만 생긴다.
FILL_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS fill_outbox (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_dedup_key  TEXT NOT NULL UNIQUE,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    published       INTEGER NOT NULL DEFAULT 0,
    published_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_fill_outbox_unpublished
    ON fill_outbox(published, id);
"""


def canonical_cumulative(value: float) -> str:
    """누적 체결량을 결정적 문자열로 정규화 (fill_dedup_key 산출용, #1949).

    SQLite REAL 과 Python ``float`` 은 모두 IEEE754 double 이므로,
    ``record_fill`` 이 CAS ``RETURNING`` 으로 돌려준 확정 누적값을 ``repr`` 로
    포매팅하면 **round-trip 을 보장하는 최단 표현**이 나온다. 같은 double 값은
    항상 같은 ``repr`` 을 내므로 재전달 시 키가 결정적이다.

    ``repr(float)`` 을 쓰는 이유: ``str(float)`` 과 동일하게 round-trip-safe 이며,
    플랫폼·실행 간 동일 double 에 대해 안정적이다. 고정 소수 포맷(``f"{:.Nf}"``)은
    유효 자릿수를 잘라 서로 다른 체결량이 같은 키로 충돌할 수 있어 쓰지 않는다.
    """
    return repr(float(value))


def make_fill_dedup_key(order_id: str, confirmed_cumulative: float) -> str:
    """결정적 ``fill_dedup_key = order_id:canonical(confirmed_cumulative)``.

    ``confirmed_cumulative`` 는 ``record_fill`` CAS ``RETURNING`` 확정값이어야
    한다(입력 ``observed_cumulative`` 가 아니다). 같은 advance 경계는 항상 같은
    키를 내므로, outbox 재전달 시 소비자가 중복을 식별할 수 있다.
    """
    return f"{order_id}:{canonical_cumulative(confirmed_cumulative)}"


class FillOutbox:
    """체결 이벤트 outbox 저장소 (테이블 관리 + txn 내 insert + 발행 마킹).

    insert 는 ``FillApplier`` 의 체결 적용 ``Database.transaction()`` 안에서
    호출되어 recorded/trade/position 과 원자 커밋된다. 발행/마킹은
    ``FillOutboxPublisher`` 워커가 트랜잭션 밖에서 수행한다.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(FILL_OUTBOX_SCHEMA)
        logger.info("FillOutbox 초기화 완료")

    async def enqueue(self, *, fill_dedup_key: str, payload: dict[str, Any]) -> None:
        """체결 이벤트 payload 를 outbox 에 INSERT (**트랜잭션 안에서 호출**).

        반드시 ``FillApplier`` 의 ``async with self._db.transaction():`` 블록
        안에서 호출해, recorded advance + trade insert + position update 와 같은
        원자 커밋에 묶여야 한다. 그래야 commit 성공 = 이벤트 영속 보장이 된다.

        ``ON CONFLICT(fill_dedup_key) DO NOTHING`` 으로 같은 체결을 두 번 관측해도
        outbox row 가 중복 생성되지 않는다(단조 advance 경로에선 같은 키가 두 번
        커밋되지 않으나, 방어적으로 멱등하게 둔다).
        """
        await self._db.execute(
            """INSERT INTO fill_outbox (fill_dedup_key, payload)
               VALUES (?, ?)
               ON CONFLICT(fill_dedup_key) DO NOTHING""",
            (fill_dedup_key, json.dumps(payload, ensure_ascii=False)),
        )

    async def fetch_unpublished(self, limit: int = 100) -> list[dict[str, Any]]:
        """미발행 outbox row 를 id 오름차순으로 조회 (발행 순서 보존)."""
        rows = await self._db.fetch_all(
            """SELECT id, fill_dedup_key, payload
                 FROM fill_outbox
                WHERE published = 0
                ORDER BY id
                LIMIT ?""",
            (limit,),
        )
        return rows

    async def mark_published(self, row_id: int) -> None:
        """row 를 발행 완료로 마킹.

        **반드시 publish 성공 이후에만 호출**(역순 금지). publish 실패 시 마킹하지
        않아 다음 사이클·기동 재전달에서 다시 발행된다(at-least-once).
        """
        await self._db.execute(
            """UPDATE fill_outbox
                  SET published = 1, published_at = datetime('now')
                WHERE id = ?""",
            (row_id,),
        )


# 미발행 row 폴 cadence. 워커는 enqueue 직후 ``notify()`` 로 즉시 드레인되며,
# 이 주기는 누락 통지/기동 잔여분에 대한 백스톱이다.
DEFAULT_DRAIN_INTERVAL = 1.0


class FillOutboxPublisher:
    """미발행 outbox row 를 ``OrderFilledEvent`` 로 발행하는 워커 (lifecycle).

    - **기동 재전달**: ``catch_up_once`` 가 미발행분을 한 번 드레인한다(commit-후-
      crash 로 미발행된 이벤트를 재전달). main barrier 에서 await 한다.
    - **이벤트 드레인**: ``notify()`` 로 enqueue 직후 즉시 드레인하고, ``start()``
      의 주기 루프가 백스톱으로 미발행분을 처리한다.
    - **순서 보장**: row 마다 ``publish 성공 → mark_published`` 순서를 지킨다.
      publish 가 실패(예외)하면 마킹하지 않고 다음 사이클에 재시도한다.

    EventBus 는 fire-and-forget(핸들러 예외 swallow)이므로, publish 자체가 예외를
    던지지 않는 한 본 워커는 핸들러 실패와 무관하게 mark_published 한다. 즉 전달
    시맨틱은 at-least-once 이며, 소비자 멱등은 #1957 범위다.
    """

    def __init__(
        self,
        *,
        outbox: FillOutbox,
        eventbus: EventBus,
        drain_interval: float = DEFAULT_DRAIN_INTERVAL,
    ) -> None:
        self._outbox = outbox
        self._eventbus = eventbus
        self._drain_interval = drain_interval
        self._task: asyncio.Task[None] | None = None
        self._running = False
        # enqueue 직후 즉시 드레인을 깨우는 신호. 누락돼도 주기 루프가 백스톱한다.
        self._wakeup = asyncio.Event()
        self._drain_lock = asyncio.Lock()

    def notify(self) -> None:
        """enqueue 직후 호출 — 워커를 깨워 즉시 드레인하게 한다(비동기 트리거)."""
        self._wakeup.set()

    async def catch_up_once(self) -> int:
        """미발행 outbox row 를 한 번 드레인. 발행한 건수를 반환 (기동 재전달용).

        main 기동에서 await 하면 commit-후-crash 로 미발행된 체결 이벤트가 소비자
        구독 이후 재전달된다. 발행 순서는 id 오름차순으로 보존된다.
        """
        return await self._drain()

    async def _drain(self) -> int:
        """미발행 row 를 모두 발행 (publish 성공 → mark 순서). 발행 건수 반환."""
        published = 0
        async with self._drain_lock:
            while True:
                rows = await self._outbox.fetch_unpublished(limit=100)
                if not rows:
                    return published
                for row in rows:
                    try:
                        await self._publish_row(row)
                    except Exception:
                        # publish 실패 — mark 하지 않아 다음 사이클/기동에 재전달.
                        # (역순 금지: mark 가 publish 보다 먼저 일어나지 않는다.)
                        logger.warning(
                            "outbox 발행 실패 (id=%s, key=%s) — 재전달 대기",
                            row.get("id"),
                            row.get("fill_dedup_key"),
                            exc_info=True,
                        )
                        # 같은 row 에서 무한 루프하지 않도록 이번 드레인은 중단.
                        return published
                    await self._outbox.mark_published(int(row["id"]))
                    published += 1

    async def _publish_row(self, row: dict[str, Any]) -> None:
        """outbox row payload 를 ``OrderFilledEvent`` 로 복원해 발행."""
        from ante.eventbus.events import OrderFilledEvent

        payload = json.loads(row["payload"])
        await self._eventbus.publish(OrderFilledEvent(**payload))

    async def start(self) -> None:
        """주기 드레인 루프 시작 (catch_up_once 와 별개 background task)."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="fill-outbox-publisher")
        logger.info(
            "FillOutboxPublisher 시작 (drain_interval=%.1fs)", self._drain_interval
        )

    async def stop(self) -> None:
        """루프 중지 (graceful)."""
        self._running = False
        self._wakeup.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.wait_for(
                    self._wakeup.wait(), timeout=self._drain_interval
                )
            except TimeoutError:
                # 주기 백스톱 드레인 (notify 누락 대비).
                pass
            self._wakeup.clear()
            if not self._running:
                return
            try:
                await self._drain()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "FillOutboxPublisher 드레인 오류 — 다음 사이클 재시도",
                    exc_info=True,
                )
