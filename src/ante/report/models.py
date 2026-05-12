"""Report Store 데이터 모델."""

from __future__ import annotations

import math
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

    def __post_init__(self) -> None:
        """metric invariant 가드 (defense in depth, #1415).

        SSOT는 ``src/ante/web/schemas.py::ReportSubmitRequest`` (Web API 입력 검증)다.
        본 가드는 CLI/내부 호출자 경유 invalid 값이 DB까지 흘러가지 않도록 차단한다.

        invariants:
        - ``total_trades >= 0`` (거래 수는 음수 불가).
        - ``win_rate``는 ``[0.0, 100.0]`` percent 단위 또는 ``None``.
        - ``total_return_pct``/``sharpe_ratio``/``max_drawdown_pct``/``win_rate``는
          finite (NaN/Inf 금지).
        """
        if self.total_trades < 0:
            raise ValueError(f"total_trades must be >= 0 (got {self.total_trades})")
        if self.win_rate is not None and not (0.0 <= self.win_rate <= 100.0):
            raise ValueError(f"win_rate must be in [0.0, 100.0] (got {self.win_rate})")
        for name in (
            "total_return_pct",
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate",
        ):
            v = getattr(self, name)
            if v is not None and not math.isfinite(v):
                raise ValueError(f"{name} must be finite (got {v!r})")

    def get_equity_curve(self) -> list[dict]:
        """detail_json에서 자산 곡선 데이터를 추출.

        Returns:
            ``[{"date": "2025-01-01", "value": 10000000}, ...]`` 형식 리스트.
            equity_curve가 없으면 빈 리스트.
        """
        import json

        try:
            data = json.loads(self.detail_json)
        except (json.JSONDecodeError, TypeError):
            return []
        return data.get("equity_curve", [])
