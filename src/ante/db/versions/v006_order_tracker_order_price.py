"""v006: order_tracker 에 order_price 컬럼 추가 (#2391, 주문 정정 v1).

주문 정정 v1(price-only, #2391)은 buy 가격↓ fail-closed 판정
(``new_price <= record.order_price``)을 위해 원주문 지정가 단가를 추적 저장소에
보존해야 한다. ``OrderTracker.initialize()`` 는 ``CREATE TABLE IF NOT EXISTS`` 만
실행하므로 기존(이미 생성된) DB 에는 신규 컬럼이 반영되지 않는다 → 본 마이그레이션이
기존 DB 의 ``order_tracker`` 테이블에 ``order_price`` 컬럼을 추가한다.

설계:
- **테이블 부재 가드**: fresh install(빈 DB)은 DDL(``ORDER_TRACKER_SCHEMA``)에 이미
  ``order_price`` 가 포함되어 있고, ``run_migrations`` 전체 실행 경로를 보존하기 위해
  테이블 부재 시 no-op 한다.
- **컬럼 존재 가드(멱등)**: ``PRAGMA table_info`` 로 ``order_price`` 컬럼이 이미
  있으면(재실행/신규 설치 후 마이그레이션) no-op 한다. SQLite ``ALTER TABLE ADD
  COLUMN`` 은 IF NOT EXISTS 를 지원하지 않으므로 사전 검사로 멱등성을 보장한다.
- **NULL 기본값**: ``order_price`` 는 nullable 이며 기존 row 는 NULL 로 남는다.
  legacy row(원주문 가격 미상)의 buy 정정은 Gateway 가 ``order_price`` None →
  buy fail-closed(``modify_budget_increase_unsupported``)로 안전하게 거부한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """기존 ``order_tracker`` 테이블에 ``order_price REAL`` 컬럼을 추가한다.

    트랜잭션 owner 태스크 안에서 ``execute_script`` 금지(#2365) — DDL 은
    ``db.execute(...)`` 로 문장 단위 실행한다.
    """
    table = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='order_tracker'"
    )
    if table is None:
        return  # order_tracker 테이블이 없으면 스킵 (신규 설치 시 DDL에 이미 포함).

    cols = await db.fetch_all("PRAGMA table_info(order_tracker)")
    if any(row["name"] == "order_price" for row in cols):
        return  # 이미 컬럼 존재 (재실행/신규 설치 후) → 멱등 no-op.

    await db.execute("ALTER TABLE order_tracker ADD COLUMN order_price REAL")
