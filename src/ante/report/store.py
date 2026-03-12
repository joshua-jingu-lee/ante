"""ReportStore — 리포트 저장·관리."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from ante.report.models import ReportStatus, StrategyReport

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    report_id          TEXT PRIMARY KEY,
    strategy_name      TEXT NOT NULL,
    strategy_version   TEXT NOT NULL,
    strategy_path      TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'submitted',
    submitted_at       TEXT NOT NULL,
    submitted_by       TEXT DEFAULT 'agent',
    backtest_period    TEXT DEFAULT '',
    total_return_pct   REAL DEFAULT 0.0,
    total_trades       INTEGER DEFAULT 0,
    sharpe_ratio       REAL,
    max_drawdown_pct   REAL,
    win_rate           REAL,
    summary            TEXT DEFAULT '',
    rationale          TEXT DEFAULT '',
    risks              TEXT DEFAULT '',
    recommendations    TEXT DEFAULT '',
    detail_json        TEXT DEFAULT '{}',
    user_notes         TEXT DEFAULT '',
    reviewed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_strategy
    ON reports(strategy_name);
CREATE INDEX IF NOT EXISTS idx_reports_status
    ON reports(status);
"""


class ReportStore:
    """리포트 저장·관리."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(REPORT_SCHEMA)
        logger.info("ReportStore 초기화 완료")

    async def submit(self, report: StrategyReport) -> str:
        """리포트 제출."""
        await self._db.execute(
            """INSERT INTO reports
               (report_id, strategy_name, strategy_version,
                strategy_path, status, submitted_at, submitted_by,
                backtest_period, total_return_pct, total_trades,
                sharpe_ratio, max_drawdown_pct, win_rate,
                summary, rationale, risks, recommendations,
                detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.report_id,
                report.strategy_name,
                report.strategy_version,
                report.strategy_path,
                report.status.value,
                report.submitted_at.isoformat(),
                report.submitted_by,
                report.backtest_period,
                report.total_return_pct,
                report.total_trades,
                report.sharpe_ratio,
                report.max_drawdown_pct,
                report.win_rate,
                report.summary,
                report.rationale,
                report.risks,
                report.recommendations,
                report.detail_json,
            ),
        )
        logger.info(
            "리포트 제출: %s (%s v%s)",
            report.report_id,
            report.strategy_name,
            report.strategy_version,
        )
        return report.report_id

    async def get(self, report_id: str) -> StrategyReport | None:
        """리포트 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM reports WHERE report_id = ?",
            (report_id,),
        )
        if not row:
            return None
        return self._row_to_report(row)

    async def list_reports(
        self,
        strategy_name: str | None = None,
        status: ReportStatus | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[StrategyReport]:
        """리포트 목록 조회."""
        conditions: list[str] = []
        params: list[object] = []

        if strategy_name:
            conditions.append("strategy_name = ?")
            params.append(strategy_name)
        if status:
            conditions.append("status = ?")
            params.append(status.value)

        where = " AND ".join(conditions) if conditions else "1=1"
        query = (
            f"SELECT * FROM reports WHERE {where}"
            " ORDER BY submitted_at DESC"
            " LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_report(row) for row in rows]

    async def update_status(
        self,
        report_id: str,
        status: ReportStatus,
        user_notes: str = "",
    ) -> None:
        """리포트 상태 변경."""
        reviewed_at = (
            datetime.now().isoformat()
            if status
            in (
                ReportStatus.REVIEWED,
                ReportStatus.ADOPTED,
                ReportStatus.REJECTED,
            )
            else None
        )
        await self._db.execute(
            """UPDATE reports
               SET status = ?, user_notes = ?, reviewed_at = ?
               WHERE report_id = ?""",
            (status.value, user_notes, reviewed_at, report_id),
        )
        logger.info("리포트 상태 변경: %s → %s", report_id, status)

    async def delete(self, report_id: str) -> None:
        """리포트 삭제."""
        await self._db.execute(
            "DELETE FROM reports WHERE report_id = ?",
            (report_id,),
        )

    @staticmethod
    def get_schema() -> dict:
        """리포트 제출 스키마 반환."""
        return {
            "required_fields": [
                "strategy_name",
                "strategy_version",
                "strategy_path",
                "backtest_period",
                "total_return_pct",
                "total_trades",
                "summary",
                "rationale",
            ],
            "optional_fields": [
                "sharpe_ratio",
                "max_drawdown_pct",
                "win_rate",
                "risks",
                "recommendations",
                "detail_json",
            ],
            "format": "JSON",
            "example": {
                "strategy_name": "momentum_breakout",
                "strategy_version": "1.0.0",
                "strategy_path": "strategies/momentum_breakout.py",
                "backtest_period": "2024-01 ~ 2026-03",
                "total_return_pct": 15.3,
                "total_trades": 42,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -8.5,
                "win_rate": 0.58,
                "summary": "20일 이동평균 돌파 매매 전략",
                "rationale": "모멘텀 효과를 활용한 추세 추종",
                "risks": "횡보장에서 잦은 손절 발생 가능",
            },
        }

    @staticmethod
    def _row_to_report(row: dict) -> StrategyReport:
        """DB row → StrategyReport 변환."""
        submitted_at = row["submitted_at"]
        reviewed_at = row.get("reviewed_at")
        return StrategyReport(
            report_id=row["report_id"],
            strategy_name=row["strategy_name"],
            strategy_version=row["strategy_version"],
            strategy_path=row["strategy_path"],
            status=ReportStatus(row["status"]),
            submitted_at=(
                datetime.fromisoformat(submitted_at)
                if isinstance(submitted_at, str)
                else submitted_at
            ),
            submitted_by=row.get("submitted_by", "agent"),
            backtest_period=row.get("backtest_period", ""),
            total_return_pct=float(row.get("total_return_pct", 0)),
            total_trades=int(row.get("total_trades", 0)),
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
            win_rate=(
                float(row["win_rate"]) if row.get("win_rate") is not None else None
            ),
            summary=row.get("summary", ""),
            rationale=row.get("rationale", ""),
            risks=row.get("risks", ""),
            recommendations=row.get("recommendations", ""),
            detail_json=row.get("detail_json", "{}"),
            user_notes=row.get("user_notes", ""),
            reviewed_at=(datetime.fromisoformat(reviewed_at) if reviewed_at else None),
        )
