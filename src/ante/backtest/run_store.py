"""BacktestRunStore — 백테스트 실행 이력 저장·조회."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

BACKTEST_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id           TEXT PRIMARY KEY,
    strategy_name    TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    params_json      TEXT DEFAULT '{}',
    total_return_pct REAL,
    sharpe_ratio     REAL,
    max_drawdown_pct REAL,
    total_trades     INTEGER,
    win_rate         REAL,
    result_path      TEXT NOT NULL,
    created_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy
    ON backtest_runs(strategy_name);
"""


@dataclass
class BacktestRun:
    """백테스트 실행 이력 레코드."""

    run_id: str
    strategy_name: str
    strategy_version: str
    params_json: str = "{}"
    total_return_pct: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    total_trades: int | None = None
    win_rate: float | None = None
    result_path: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리 변환."""
        return {
            "run_id": self.run_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "params_json": self.params_json,
            "total_return_pct": self.total_return_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_pct": self.max_drawdown_pct,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "result_path": self.result_path,
            "created_at": self.created_at,
        }


class BacktestRunStore:
    """백테스트 실행 이력 저장·조회."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(BACKTEST_RUNS_SCHEMA)
        logger.info("BacktestRunStore 초기화 완료")

    async def save(
        self,
        *,
        strategy_name: str,
        strategy_version: str,
        params: dict[str, Any] | None = None,
        total_return_pct: float | None = None,
        sharpe_ratio: float | None = None,
        max_drawdown_pct: float | None = None,
        total_trades: int | None = None,
        win_rate: float | None = None,
        result_path: str = "",
    ) -> str:
        """실행 이력 저장. run_id 반환."""
        run_id = str(uuid.uuid4())
        created_at = datetime.now(tz=UTC).isoformat()
        params_json = json.dumps(params or {}, default=str)

        await self._db.execute(
            """INSERT INTO backtest_runs
               (run_id, strategy_name, strategy_version, params_json,
                total_return_pct, sharpe_ratio, max_drawdown_pct,
                total_trades, win_rate, result_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                strategy_name,
                strategy_version,
                params_json,
                total_return_pct,
                sharpe_ratio,
                max_drawdown_pct,
                total_trades,
                win_rate,
                result_path,
                created_at,
            ),
        )
        logger.info("백테스트 이력 저장: %s (%s)", run_id, strategy_name)
        return run_id

    async def get(self, run_id: str) -> BacktestRun | None:
        """이력 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM backtest_runs WHERE run_id = ?",
            (run_id,),
        )
        if not row:
            return None
        return self._row_to_run(row)

    async def list_by_strategy(
        self,
        strategy_name: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[BacktestRun]:
        """전략별 이력 조회 (최신순)."""
        rows = await self._db.fetch_all(
            """SELECT * FROM backtest_runs
               WHERE strategy_name = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (strategy_name, limit, offset),
        )
        return [self._row_to_run(row) for row in rows]

    @staticmethod
    def _row_to_run(row: dict) -> BacktestRun:
        """DB row → BacktestRun."""
        return BacktestRun(
            run_id=row["run_id"],
            strategy_name=row["strategy_name"],
            strategy_version=row["strategy_version"],
            params_json=row.get("params_json", "{}"),
            total_return_pct=(
                float(row["total_return_pct"])
                if row.get("total_return_pct") is not None
                else None
            ),
            sharpe_ratio=(
                float(row["sharpe_ratio"])
                if row.get("sharpe_ratio") is not None
                else None
            ),
            max_drawdown_pct=(
                float(row["max_drawdown_pct"])
                if row.get("max_drawdown_pct") is not None
                else None
            ),
            total_trades=(
                int(row["total_trades"])
                if row.get("total_trades") is not None
                else None
            ),
            win_rate=(
                float(row["win_rate"]) if row.get("win_rate") is not None else None
            ),
            result_path=row.get("result_path", ""),
            created_at=row.get("created_at", ""),
        )
