"""SystemState — 킬 스위치(Trading State) 관리."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

SYSTEM_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS system_state_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    old_state  TEXT NOT NULL,
    new_state  TEXT NOT NULL,
    reason     TEXT DEFAULT '',
    changed_by TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class TradingState(StrEnum):
    """거래 상태 (킬 스위치)."""

    ACTIVE = "active"
    REDUCING = "reducing"
    HALTED = "halted"


class SystemState:
    """시스템 거래 상태(킬 스위치) 관리.

    인메모리에서 즉시 조회 가능하며, SQLite에 재시작 복원용으로 영속화.
    상태 변경 시 TradingStateChangedEvent를 발행하여 시스템 전체에 전파.
    """

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus
        self._state: TradingState = TradingState.ACTIVE

    async def initialize(self) -> None:
        """스키마 생성 + DB에서 마지막 상태 복원."""
        await self._db.execute_script(SYSTEM_STATE_SCHEMA)
        await self._load_from_db()

    async def _load_from_db(self) -> None:
        """DB에서 마지막 상태 복원."""
        row = await self._db.fetch_one(
            "SELECT value FROM system_state WHERE key = 'trading_state'"
        )
        if row is not None:
            try:
                self._state = TradingState(row["value"])
                logger.info("거래 상태 복원: %s", self._state)
            except ValueError:
                logger.warning(
                    "DB에 잘못된 거래 상태: %s — ACTIVE로 초기화", row["value"]
                )
                self._state = TradingState.ACTIVE

    @property
    def trading_state(self) -> TradingState:
        """현재 거래 상태 조회. 인메모리에서 즉시 반환."""
        return self._state

    async def set_state(
        self, state: TradingState, reason: str = "", changed_by: str = ""
    ) -> None:
        """거래 상태 변경. 인메모리 즉시 반영 + DB 영속화 + 이벤트 발행."""
        from ante.eventbus.events import TradingStateChangedEvent

        old_state = self._state
        if old_state == state:
            return

        self._state = state
        await self._db.execute(
            """INSERT INTO system_state (key, value, updated_at)
               VALUES ('trading_state', ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at""",
            (state.value,),
        )
        await self._db.execute(
            """INSERT INTO system_state_history
               (old_state, new_state, reason, changed_by)
               VALUES (?, ?, ?, ?)""",
            (old_state.value, state.value, reason, changed_by),
        )
        await self._eventbus.publish(
            TradingStateChangedEvent(
                old_state=old_state.value,
                new_state=state.value,
                reason=reason,
                changed_by=changed_by,
            )
        )

        from ante.eventbus.events import NotificationEvent

        await self._eventbus.publish(
            NotificationEvent(
                level="critical",
                title="거래 상태 변경",
                message=(f"{old_state.value} → *{state.value}*\n사유: {reason}"),
                category="system",
            )
        )
        logger.info(
            "거래 상태 변경: %s → %s (사유: %s, 변경자: %s)",
            old_state,
            state,
            reason,
            changed_by,
        )
