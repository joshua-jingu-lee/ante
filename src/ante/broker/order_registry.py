"""OrderRegistry — order_id → bot_id 매핑 관리.

복수 봇이 같은 계좌에서 거래할 때,
브로커가 반환하는 order_id가 어느 봇의 주문인지 추적한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.account.scoping import require_account_id

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

ORDER_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_registry (
    order_id    TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    bot_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_order_registry_bot
    ON order_registry(bot_id);
CREATE INDEX IF NOT EXISTS idx_order_registry_account
    ON order_registry(account_id);
CREATE INDEX IF NOT EXISTS idx_order_registry_account_bot
    ON order_registry(account_id, bot_id);
"""


class OrderRegistry:
    """order_id → bot_id 매핑 관리.

    주문 제출 시 등록, 대사 시 조회.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(ORDER_REGISTRY_SCHEMA)
        logger.info("OrderRegistry 초기화 완료")

    async def register(
        self,
        order_id: str,
        account_id: str,
        bot_id: str,
        symbol: str,
    ) -> None:
        """주문 제출 시 매핑 등록."""
        validated_account_id = require_account_id(
            account_id, context="order_registry.register"
        )
        await self._db.execute(
            """INSERT INTO order_registry (order_id, account_id, bot_id, symbol)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(order_id) DO UPDATE SET
                 account_id = excluded.account_id,
                 bot_id = excluded.bot_id,
                 symbol = excluded.symbol""",
            (order_id, validated_account_id, bot_id, symbol),
        )
        logger.debug(
            "주문 등록: %s / %s → %s (%s)",
            validated_account_id,
            order_id,
            bot_id,
            symbol,
        )

    async def get_bot_id(self, order_id: str, account_id: str) -> str | None:
        """order_id로 bot_id 조회."""
        validated_account_id = require_account_id(
            account_id, context="order_registry.get_bot_id"
        )
        row = await self._db.fetch_one(
            "SELECT bot_id FROM order_registry WHERE order_id = ? AND account_id = ?",
            (order_id, validated_account_id),
        )
        return row["bot_id"] if row else None

    async def get_orders_by_bot(self, account_id: str, bot_id: str) -> list[dict]:
        """봇의 모든 주문 조회."""
        validated_account_id = require_account_id(
            account_id, context="order_registry.get_orders_by_bot"
        )
        return await self._db.fetch_all(
            """SELECT * FROM order_registry
               WHERE account_id = ? AND bot_id = ?
               ORDER BY created_at DESC""",
            (validated_account_id, bot_id),
        )

    async def remove(self, order_id: str, account_id: str) -> None:
        """매핑 삭제."""
        validated_account_id = require_account_id(
            account_id, context="order_registry.remove"
        )
        await self._db.execute(
            "DELETE FROM order_registry WHERE order_id = ? AND account_id = ?",
            (order_id, validated_account_id),
        )
