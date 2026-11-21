"""v006: order_tracker 에 order_price 컬럼 추가 (주문 정정 v1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """기존 ``order_tracker`` 테이블에 ``order_price REAL`` 컬럼을 추가한다.

    트랜잭션 owner 태스크 안에서 ``execute_script`` 금지 — DDL 은
    ``db.execute(...)`` 로 문장 단위 실행한다.
    """
    table = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='order_tracker'"
    )
    if table is None:
        return

    cols = await db.fetch_all("PRAGMA table_info(order_tracker)")
    if any(row["name"] == "order_price" for row in cols):
        return

    await db.execute("ALTER TABLE order_tracker ADD COLUMN order_price REAL")
