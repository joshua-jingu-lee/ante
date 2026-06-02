"""Report submission validation models."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("detail_json")
    @classmethod
    def _validate_detail_json(cls, v: str) -> str:
        """``detail_json``이 표준 JSON 문자열인지 검증한다.

        비표준 JSON 토큰(``Infinity``/``-Infinity``/``NaN``)은 중첩
        위치를 포함하여 거부한다. ``json.dumps``는 기본적으로 이 토큰을
        직렬화하므로, dict 입력 경로(CLI)에서 ``float('inf')`` 등이
        흘러들어오면 이 검증에서 차단된다. 파싱 불가능한 비-JSON 문자열도
        거부한다. 검증을 통과하면 원본 문자열을 그대로 반환한다.
        """

        def _reject(constant: str) -> float:
            msg = f"detail_json은 표준 JSON이어야 합니다 (비표준 토큰: {constant})"
            raise ValueError(msg)

        try:
            json.loads(v, parse_constant=_reject)
        except json.JSONDecodeError as exc:
            msg = "detail_json은 유효한 JSON 문자열이어야 합니다"
            raise ValueError(msg) from exc
        return v
