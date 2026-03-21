"""포트폴리오 API — 자산 가치 + 추이 (스냅샷 기반)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ante.web.deps import (
    get_treasury,
    get_treasury_manager_optional,
)
from ante.web.schemas import (
    PortfolioHistoryResponse,
    PortfolioValueResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_treasury(
    treasury: Any,
    treasury_manager: Any | None,
    account_id: str | None,
) -> Any:
    """account_id가 주어지면 해당 계좌의 Treasury를 반환한다."""
    if account_id and treasury_manager is not None:
        try:
            return treasury_manager.get(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"계좌를 찾을 수 없습니다: {account_id}",
            )
    return treasury


@router.get(
    "/value",
    response_model=PortfolioValueResponse,
    response_model_exclude_none=True,
    responses={
        503: {"description": "Treasury not available"},
    },
)
async def portfolio_value(
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """총 자산 가치 + 당일 손익 + 수익률 + 미실현 손익 (최신 스냅샷 기반)."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_latest_snapshot()
    if snapshot is not None:
        daily_return = snapshot["daily_return"]
        return {
            "total_value": snapshot["total_asset"],
            "daily_pnl": snapshot["daily_pnl"],
            "daily_pnl_pct": daily_return,
            "daily_return": daily_return,
            "unrealized_pnl": snapshot["unrealized_pnl"],
            "snapshot_date": snapshot["snapshot_date"],
            "updated_at": snapshot["created_at"],
        }

    # 스냅샷 미존재 시 get_summary() fallback (시스템 초기 구동)
    summary = target.get_summary()
    now = datetime.now(UTC).isoformat()
    return {
        "total_value": summary.get("total_evaluation", 0.0),
        "daily_pnl": 0.0,
        "daily_pnl_pct": 0.0,
        "daily_return": 0.0,
        "unrealized_pnl": 0.0,
        "updated_at": now,
    }


@router.get(
    "/history",
    response_model=PortfolioHistoryResponse,
    responses={
        503: {"description": "Treasury not available"},
    },
)
async def portfolio_history(
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """기간별 자산 추이 (daily_snapshots 시계열 반환)."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)

    if end_date is None:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    snapshots = await target.get_snapshots(start_date, end_date)
    data = [
        {
            "date": s["snapshot_date"],
            "total_asset": s["total_asset"],
            "daily_pnl": s["daily_pnl"],
            "daily_return": s["daily_return"],
            "unrealized_pnl": s["unrealized_pnl"],
        }
        for s in snapshots
    ]

    return {
        "data": data,
        "start_date": start_date,
        "end_date": end_date,
    }
