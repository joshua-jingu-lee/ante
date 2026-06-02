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


def validate_strategy_report_metrics(
    total_trades: int,
    win_rate: float | None,
    total_return_pct: float | None,
    sharpe_ratio: float | None,
    max_drawdown_pct: float | None,
) -> None:
    """``StrategyReport`` metric invariant 명시 검증 (#1415).

    저장 경로 (CLI submit 등 새 값을 DB에 쓰는 경계)에서만 호출한다.
    DB read path (``ReportStore._row_to_report``)는 **legacy invalid row**를 허용하기
    위해 호출하지 않는다 — 그렇지 않으면 이 PR 이전에 저장된 invalid row가 존재할 때
    list/detail 조회가 ``ValueError``로 fail해 사용자가 정리할 수 없다 (codex r1 P2).

    SSOT:
    - ``src/ante/report/validation.py::ReportSubmitRequest`` — CLI 입력 검증 SSOT.

    invariants:
    - ``total_trades >= 0`` (거래 수는 음수 불가).
    - ``win_rate``는 ``[0.0, 100.0]`` percent 단위 또는 ``None``.
    - ``total_return_pct``/``sharpe_ratio``/``max_drawdown_pct``/``win_rate``는
      finite (NaN/Inf 금지).

    Raises:
        ValueError: invariant 위반 시.
    """
    if total_trades < 0:
        raise ValueError(f"total_trades must be >= 0 (got {total_trades})")
    if win_rate is not None and not (0.0 <= win_rate <= 100.0):
        raise ValueError(f"win_rate must be in [0.0, 100.0] (got {win_rate})")
    for name, v in (
        ("total_return_pct", total_return_pct),
        ("sharpe_ratio", sharpe_ratio),
        ("max_drawdown_pct", max_drawdown_pct),
        ("win_rate", win_rate),
    ):
        if v is not None and not math.isfinite(v):
            raise ValueError(f"{name} must be finite (got {v!r})")


@dataclass
class StrategyReport:
    """전략 검증 리포트.

    note:
        metric invariant 검증은 ``validate_strategy_report_metrics`` 함수로 분리되어
        있다 (#1415 codex r1). dataclass ``__post_init__`` 검증을 두지 않는 이유는
        ``ReportStore._row_to_report``의 DB read path가 legacy invalid row를 재구성할
        때 raise되면 사용자가 list/detail 조회로 잘못된 row를 확인하거나 정리할 길이
        없어지기 때문이다. 저장 경계 (CLI/Web submit)에서 명시 검증을 수행한다.
    """

    report_id: str
    strategy_name: str
    strategy_version: str
    strategy_path: str
    status: ReportStatus
    submitted_at: datetime
    submitted_by: str = "agent"

    # 백테스트 결과 요약
    backtest_period: str = ""
    # 참조한 백테스트 run_id (CLI ``--run`` 또는 payload backtest_run_id).
    # 빈 문자열은 "참조 없음"을 의미한다 (#1999).
    backtest_run_id: str = ""
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
