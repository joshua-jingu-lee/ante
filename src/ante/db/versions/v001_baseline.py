"""기준선 마이그레이션 (no-op).

기존 스키마가 이미 생성되어 있으므로 추가 작업 없음.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """No-op baseline migration."""
