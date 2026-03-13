"""Report Store 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReportStatus(StrEnum):
    """리포트 상태."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass
class StrategyReport:
    """전략 검증 리포트."""

    report_id: str
    strategy_name: str
    strategy_version: str
    strategy_path: str
    status: ReportStatus
    submitted_at: datetime
    submitted_by: str = "agent"

    # 백테스트 결과 요약
    backtest_period: str = ""
    total_return_pct: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float | None = None
    max_drawdown_pct: float | None = None
    win_rate: float | None = None

    # Agent 코멘트
    summary: str = ""
    rationale: str = ""
    risks: str = ""
    recommendations: str = ""

    # 상세 데이터 (JSON)
    detail_json: str = "{}"

    # 사용자 피드백
    user_notes: str = ""
    reviewed_at: datetime | None = None
