"""v007: order_tracker 에 exchange 컬럼 추가 (#2487, 주문 이벤트 exchange 전파).

주문 생애주기 이벤트는 ``exchange`` 를 나르지만(``docs/specs/eventbus/eventbus.md``),
체결 영속 계층(``TradeRecord``/``OrderFilledEvent`` payload)은 그 값을 얻을 소스가
없어 ``events.py`` 기본값 ``"KRX"`` 가 ``trades``/``position_history`` 에 기록됐다.
값 자체는 이미 ``OrderSubmittedEvent`` 로 Gateway 까지 도달하므로, 그 값을
``order_tracker`` 에 seed 해 체결 시점 단일 소스로 삼는다(source chokepoint).
``OrderTracker.initialize()`` 는 ``CREATE TABLE IF NOT EXISTS`` 만 실행하므로 기존
(이미 생성된) DB 에는 신규 컬럼이 반영되지 않는다 → 본 마이그레이션이 기존 DB 의
``order_tracker`` 테이블에 ``exchange`` 컬럼을 추가한다.

설계 (v006 동형):
- **테이블 부재 가드**: fresh install(빈 DB)은 DDL(``ORDER_TRACKER_SCHEMA``)에 이미
  ``exchange`` 가 포함되어 있고, ``run_migrations`` 전체 실행 경로를 보존하기 위해
  테이블 부재 시 no-op 한다.
- **컬럼 존재 가드(멱등)**: ``PRAGMA table_info`` 로 ``exchange`` 컬럼이 이미
  있으면(재실행/신규 설치 후 마이그레이션) no-op 한다. SQLite ``ALTER TABLE ADD
  COLUMN`` 은 IF NOT EXISTS 를 지원하지 않으므로 사전 검사로 멱등성을 보장한다.
- **NULL 기본값**: ``exchange`` 는 nullable 이며 기존 row 는 NULL 로 남는다.
  legacy row(거래소 미상)의 체결은 소비 측(``FillApplier``)이 ``"KRX"`` 로
  폴백한다 — 마이그레이션 이전과 동일한 관측값이라 회귀가 없다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """기존 ``order_tracker`` 테이블에 ``exchange TEXT`` 컬럼을 추가한다.

    트랜잭션 owner 태스크 안에서 ``execute_script`` 금지(#2365) — DDL 은
    ``db.execute(...)`` 로 문장 단위 실행한다.
    """
    table = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='order_tracker'"
    )
    if table is None:
        return  # order_tracker 테이블이 없으면 스킵 (신규 설치 시 DDL에 이미 포함).

    cols = await db.fetch_all("PRAGMA table_info(order_tracker)")
    if any(row["name"] == "exchange" for row in cols):
        return  # 이미 컬럼 존재 (재실행/신규 설치 후) → 멱등 no-op.

    await db.execute("ALTER TABLE order_tracker ADD COLUMN exchange TEXT")
