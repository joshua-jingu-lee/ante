"""포트폴리오 API — 자산 가치 + 추이 (스냅샷 기반)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ante.web.deps import (
    get_treasury,
    get_treasury_manager_optional,
    require_treasury_read,
)
from ante.web.schemas import (
    PortfolioHistoryResponse,
    PortfolioValueResponse,
)
from ante.web.utils.account_params import reject_invalid_account_id
from ante.web.utils.date_params import (
    reject_inverted_date_range,
    validate_iso_date_only,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_treasury(
    treasury: Any,
    treasury_manager: Any | None,
    account_id: str | None,
) -> Any:
    """account_id가 주어지면 해당 계좌의 Treasury를 반환한다.

    제공된 runtime-invalid ``account_id`` (``""``/``"default"``/패턴 위반)는
    lookup 이전에 422로 거부한다 (#1624, Account ID 계약 read-API ingress).
    ``account_id is None`` (미지정)은 통과 — #1218 단일-treasury 분기 보존.
    """
    reject_invalid_account_id(account_id)
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
        422: {
            "description": (
                "Invalid ``account_id`` query. 제공된 runtime-invalid 값"
                ' (``""``/``"default"``/``^[a-zA-Z0-9\\-]{3,30}$`` 불일치)은'
                " lookup 이전에 422로 거부된다. ``account_id`` 미지정은"
                " all-account 집계 분기로 통과한다 (#1218 보존, #1624)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def portfolio_value(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """총 자산 가치 + 당일 손익 + 수익률 + 미실현 손익 (최신 스냅샷 기반).
    인증된 master/human 또는 ``treasury:read`` scope 를 보유한 agent 만 호출
    가능 (#1407 — portfolio 라우트는 ``treasury_daily_snapshots`` 를 읽으므로
    spec ``treasury:read`` 정합)."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_latest_snapshot()
    if snapshot is not None:
        daily_return = snapshot["daily_return"]
        return {
            "total_value": snapshot["total_asset"],
            "daily_pnl": snapshot["daily_pnl"],
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
        "daily_return": 0.0,
        "unrealized_pnl": 0.0,
        "updated_at": now,
    }


@router.get(
    "/history",
    response_model=PortfolioHistoryResponse,
    responses={
        422: {
            "description": (
                "Invalid ``start_date``/``end_date`` (ISO ``YYYY-MM-DD`` required). "
                "``treasury_daily_snapshots.snapshot_date`` 컬럼이 date-only로 "
                "저장되므로 임의 문자열을 허용하지 않는다 (#1440). "
                "``start_date > end_date`` (inverted range)도 422로 거부한다 "
                "(#1595). 제공된 runtime-invalid ``account_id`` "
                '(``""``/``"default"``/``^[a-zA-Z0-9\\-]{3,30}$`` 불일치)도 '
                "lookup 이전에 422로 거부된다. ``account_id`` 미지정은 "
                "all-account 집계 분기로 통과한다 (#1218 보존, #1624)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def portfolio_history(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """기간별 자산 추이 (daily_snapshots 시계열 반환). 인증된 master/human 또는
    ``treasury:read`` scope 를 보유한 agent 만 호출 가능 (#1407).

    ``start_date``/``end_date``는 ISO ``YYYY-MM-DD`` (date-only)만 허용한다.
    파싱 실패 또는 캘린더 invalid (``2026-13-32``)는 422로 거부된다 (#1440).
    """
    start_date = validate_iso_date_only(start_date, "start_date")
    end_date = validate_iso_date_only(end_date, "end_date")
    # default 적용 이전: 미지정(None)은 통과, start>end (inverted) 만 거부 (#1595).
    reject_inverted_date_range(start_date, end_date)

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
