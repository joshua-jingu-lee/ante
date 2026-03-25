"""v004: StrategyStatus 간소화 (active→adopted, inactive→archived)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """기존 active/inactive 상태를 adopted/archived로 변환한다."""
    await db.execute("UPDATE strategies SET status = 'adopted' WHERE status = 'active'")
    await db.execute(
        "UPDATE strategies SET status = 'archived' WHERE status = 'inactive'"
    )
