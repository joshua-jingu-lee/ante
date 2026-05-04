"""PositionHistory — 포지션 변동 추적.

Trade 모듈의 positions 테이블이 시스템 유일의 포지션 소스이다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ante.account.errors import InvalidAccountIdError
from ante.account.scoping import require_account_id
from ante.trade.models import PositionSnapshot, TradeRecord, TradeStatus

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

POSITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    bot_id           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    quantity         REAL NOT NULL DEFAULT 0,
    avg_entry_price  REAL NOT NULL DEFAULT 0.0,
    realized_pnl     REAL NOT NULL DEFAULT 0.0,
    updated_at       TEXT DEFAULT (datetime('now')),
    account_id       TEXT NOT NULL DEFAULT 'default',
    PRIMARY KEY (bot_id, symbol)
);

CREATE TABLE IF NOT EXISTS position_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id         TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    action         TEXT NOT NULL,
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    pnl            REAL DEFAULT 0.0,
    timestamp      TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    account_id     TEXT NOT NULL DEFAULT 'default',
    exchange       TEXT DEFAULT 'KRX',
    trade_id       TEXT
);
CREATE INDEX IF NOT EXISTS idx_position_history_bot
    ON position_history(bot_id, timestamp);
"""


class PositionHistory:
    """포지션 변동 이력 관리."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._position_cache: dict[str, dict[str, PositionSnapshot]] = {}

    async def initialize(self) -> None:
        """스키마 생성 + 캐시 워밍."""
        await self._db.execute_script(POSITION_SCHEMA)
        await self._warm_cache()
        logger.info("PositionHistory 초기화 완료")

    async def _warm_cache(self) -> None:
        """DB에서 전체 포지션을 읽어 인메모리 캐시에 적재.

        legacy 'default' (또는 기타 invalid) ``account_id`` row는
        :class:`InvalidAccountIdError` 로 skip하고 warning만 남긴다.
        스키마/데이터 마이그레이션(#1219 등)이 완료되기 전에도 서버 부팅이
        실패하지 않도록 하기 위함이다.
        """
        rows = await self._db.fetch_all("SELECT * FROM positions WHERE quantity > 0")
        self._position_cache.clear()
        for row in rows:
            snapshot = self._row_to_snapshot_safe(row, context="warm cache")
            if snapshot is None:
                continue
            self._position_cache.setdefault(snapshot.bot_id, {})[snapshot.symbol] = (
                snapshot
            )

    def get_positions_sync(self, bot_id: str) -> list[PositionSnapshot]:
        """봇의 현재 포지션 동기 조회 (인메모리 캐시). PortfolioView용."""
        bot_positions = self._position_cache.get(bot_id, {})
        return list(bot_positions.values())

    async def on_trade(self, record: TradeRecord) -> None:
        """체결 기록을 반영하여 포지션 상태 갱신."""
        if record.status != TradeStatus.FILLED:
            return

        position = await self._get_current(record.bot_id, record.symbol)

        if record.side == "buy":
            total_cost = position["avg_entry_price"] * position["quantity"]
            new_cost = record.price * record.quantity
            new_quantity = position["quantity"] + record.quantity
            new_avg = (
                (total_cost + new_cost) / new_quantity if new_quantity > 0 else 0.0
            )

            await self._update_position(
                record.bot_id,
                record.symbol,
                quantity=new_quantity,
                avg_entry_price=new_avg,
                account_id=record.account_id,
            )

            await self._save_history(
                bot_id=record.bot_id,
                symbol=record.symbol,
                action="buy",
                quantity=record.quantity,
                price=record.price,
                pnl=0.0,
                timestamp=record.timestamp,
                exchange=record.exchange,
                trade_id=str(record.trade_id),
            )

        elif record.side == "sell":
            held_qty = position["quantity"]
            effective_qty = min(record.quantity, held_qty)

            if record.quantity > held_qty:
                logger.warning(
                    "초과 매도 감지: bot=%s symbol=%s 보유=%s 요청=%s → "
                    "유효 수량 %s로 클램핑 (Reconciler 개입 필요)",
                    record.bot_id,
                    record.symbol,
                    held_qty,
                    record.quantity,
                    effective_qty,
                )

            pnl = (record.price - position["avg_entry_price"]) * effective_qty
            pnl -= record.commission
            new_quantity = held_qty - record.quantity

            await self._update_position(
                record.bot_id,
                record.symbol,
                quantity=max(new_quantity, 0),
                avg_entry_price=position["avg_entry_price"]
                if new_quantity > 0
                else 0.0,
                realized_pnl_delta=pnl,
                account_id=record.account_id,
            )

            await self._save_history(
                bot_id=record.bot_id,
                symbol=record.symbol,
                action="sell",
                quantity=effective_qty,
                price=record.price,
                pnl=pnl,
                timestamp=record.timestamp,
                exchange=record.exchange,
                trade_id=str(record.trade_id),
            )

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
    ) -> list[PositionSnapshot]:
        """봇의 현재 포지션 조회.

        legacy 'default' (또는 기타 invalid) ``account_id`` row는 skip하고
        warning만 남긴다. dashboard / Treasury 동기화가 마이그레이션 전에도
        실패하지 않도록 하기 위함이다.
        """
        if include_closed:
            rows = await self._db.fetch_all(
                "SELECT * FROM positions WHERE bot_id = ?", (bot_id,)
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM positions WHERE bot_id = ? AND quantity > 0",
                (bot_id,),
            )
        return self._rows_to_snapshots(rows, context="get_positions")

    async def get_all_positions(self) -> list[PositionSnapshot]:
        """전체 봇의 모든 포지션 조회 (대사 계좌 합산 검증용).

        legacy 'default' (또는 기타 invalid) ``account_id`` row는 skip하고
        warning만 남긴다.
        """
        rows = await self._db.fetch_all("SELECT * FROM positions WHERE quantity > 0")
        return self._rows_to_snapshots(rows, context="get_all_positions")

    async def get_current(self, bot_id: str, symbol: str) -> dict:
        """현재 포지션 조회 (public)."""
        return await self._get_current(bot_id, symbol)

    async def get_history(
        self,
        bot_id: str,
        symbol: str | None = None,
    ) -> list[dict]:
        """포지션 변동 이력 조회."""
        if symbol:
            rows = await self._db.fetch_all(
                "SELECT * FROM position_history"
                " WHERE bot_id = ? AND symbol = ?"
                " ORDER BY created_at DESC",
                (bot_id, symbol),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM position_history"
                " WHERE bot_id = ?"
                " ORDER BY created_at DESC",
                (bot_id,),
            )
        return [dict(row) for row in rows]

    async def force_update(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        *,
        account_id: str,
    ) -> None:
        """Reconciler 전용: 포지션 강제 덮어쓰기."""
        validated_account_id = require_account_id(
            account_id, context="position.force_update"
        )
        await self._db.execute(
            """INSERT INTO positions
               (bot_id, symbol, quantity, avg_entry_price, account_id, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(bot_id, symbol) DO UPDATE SET
                 quantity = excluded.quantity,
                 avg_entry_price = excluded.avg_entry_price,
                 account_id = excluded.account_id,
                 updated_at = excluded.updated_at""",
            (bot_id, symbol, quantity, avg_entry_price, validated_account_id),
        )
        # 인메모리 캐시 갱신
        self._update_cache(
            bot_id, symbol, quantity, avg_entry_price, account_id=account_id
        )

    async def _get_current(self, bot_id: str, symbol: str) -> dict:
        """현재 포지션 조회. 없으면 빈 포지션 반환."""
        row = await self._db.fetch_one(
            "SELECT * FROM positions WHERE bot_id = ? AND symbol = ?",
            (bot_id, symbol),
        )
        if row:
            return dict(row)
        return {
            "bot_id": bot_id,
            "symbol": symbol,
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "realized_pnl": 0.0,
        }

    async def _update_position(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        *,
        account_id: str,
        realized_pnl_delta: float = 0.0,
    ) -> None:
        """포지션 상태 갱신."""
        await self._db.execute(
            """INSERT INTO positions
               (bot_id, symbol, quantity, avg_entry_price,
                realized_pnl, updated_at, account_id)
               VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
               ON CONFLICT(bot_id, symbol) DO UPDATE SET
                 quantity = ?,
                 avg_entry_price = ?,
                 realized_pnl = realized_pnl + ?,
                 account_id = ?,
                 updated_at = datetime('now')""",
            (
                bot_id,
                symbol,
                quantity,
                avg_entry_price,
                realized_pnl_delta,
                account_id,
                quantity,
                avg_entry_price,
                realized_pnl_delta,
                account_id,
            ),
        )
        # 인메모리 캐시 갱신
        self._update_cache(
            bot_id,
            symbol,
            quantity,
            avg_entry_price,
            account_id=account_id,
            realized_pnl_delta=realized_pnl_delta,
        )

    def _update_cache(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        *,
        account_id: str,
        realized_pnl_delta: float = 0.0,
    ) -> None:
        """인메모리 포지션 캐시 갱신."""
        bot_cache = self._position_cache.setdefault(bot_id, {})
        existing = bot_cache.get(symbol)
        prev_pnl = existing.realized_pnl if existing else 0.0

        if quantity > 0:
            bot_cache[symbol] = PositionSnapshot(
                bot_id=bot_id,
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=avg_entry_price,
                realized_pnl=prev_pnl + realized_pnl_delta,
                account_id=account_id,
            )
        else:
            bot_cache.pop(symbol, None)

    async def _save_history(
        self,
        bot_id: str,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        pnl: float,
        timestamp: object | None,
        exchange: str = "KRX",
        trade_id: str | None = None,
    ) -> None:
        """포지션 변동 이력 저장."""
        ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else None
        await self._db.execute(
            """INSERT INTO position_history
               (bot_id, symbol, action, quantity, price, pnl, timestamp,
                exchange, trade_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (bot_id, symbol, action, quantity, price, pnl, ts, exchange, trade_id),
        )

    @staticmethod
    def _row_to_snapshot(row: dict) -> PositionSnapshot:
        """DB row → PositionSnapshot."""
        return PositionSnapshot(
            bot_id=row["bot_id"],
            symbol=row["symbol"],
            quantity=float(row["quantity"]),
            avg_entry_price=float(row["avg_entry_price"]),
            realized_pnl=float(row.get("realized_pnl", 0)),
            updated_at=row.get("updated_at", ""),
            account_id=row["account_id"],
        )

    def _row_to_snapshot_safe(
        self, row: dict, *, context: str
    ) -> PositionSnapshot | None:
        """DB row → PositionSnapshot, legacy invalid account_id row는 skip.

        legacy 'default' (또는 기타 invalid) ``account_id`` row는
        :class:`InvalidAccountIdError` 로 skip하고 warning만 남긴다.
        스키마/데이터 마이그레이션(#1219 등)이 완료되기 전에도 read 경로가
        실패하지 않도록 하기 위함이다.
        """
        try:
            return self._row_to_snapshot(row)
        except InvalidAccountIdError as e:
            logger.warning(
                "%s: invalid account_id row skip (legacy migration 필요): %s, row=%s",
                context,
                e,
                dict(row),
            )
            return None

    def _rows_to_snapshots(
        self, rows: list[dict], *, context: str
    ) -> list[PositionSnapshot]:
        """rows → snapshots, legacy invalid account_id row는 skip."""
        snapshots: list[PositionSnapshot] = []
        for row in rows:
            snapshot = self._row_to_snapshot_safe(row, context=context)
            if snapshot is not None:
                snapshots.append(snapshot)
        return snapshots
