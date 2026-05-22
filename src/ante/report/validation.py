"""Report submission validation models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReportSubmitRequest(BaseModel):
    """리포트 제출 요청 모델.

    입력 계약은 ``docs/specs/report-store/report-store.md``의 리포트 제출
    스키마를 따른다. ``win_rate``는 percent 단위다.
    """

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    strategy_version: str
    strategy_path: str
    backtest_period: str
    total_return_pct: float = Field(allow_inf_nan=False)
    total_trades: int = Field(ge=0)
    sharpe_ratio: float | None = Field(default=None, allow_inf_nan=False)
    max_drawdown_pct: float | None = Field(default=None, allow_inf_nan=False)
    win_rate: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    summary: str
    rationale: str
    risks: str = ""
    recommendations: str = ""
    detail_json: str = "{}"
