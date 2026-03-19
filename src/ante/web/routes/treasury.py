"""Treasury 자금 관리 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ante.web.deps import get_broker, get_config, get_treasury
from ante.web.schemas import (
    BalanceSetResponse,
    BudgetListResponse,
    BudgetOperationResponse,
    TransactionListResponse,
    TreasurySummaryResponse,
)

router = APIRouter()


class BudgetChangeRequest(BaseModel):
    """예산 할당/회수 요청."""

    amount: float


class BalanceSetRequest(BaseModel):
    """잔고 수동 설정 요청."""

    balance: float


@router.get(
    "",
    response_model=TreasurySummaryResponse,
    response_model_exclude_none=True,
    responses={503: {"description": "Treasury not available"}},
)
async def get_summary(
    treasury: Annotated[Any, Depends(get_treasury)],
    broker: Annotated[Any | None, Depends(get_broker)],
    config: Annotated[Any | None, Depends(get_config)],
) -> dict:
    """자금 현황 요약."""
    summary = treasury.get_summary()
    summary["commission_rate"] = getattr(treasury, "commission_rate", 0.00015)
    summary["sell_tax_rate"] = getattr(treasury, "sell_tax_rate", 0.0023)

    # 브로커 메타정보
    if broker is not None:
        summary["broker_id"] = broker.broker_id
        summary["broker_name"] = broker.broker_name
        summary["broker_short_name"] = broker.broker_short_name
        summary["exchange"] = broker.exchange

    # KIS 계좌 헤더 정보
    if config is not None:
        try:
            account_no = config.secret("KIS_ACCOUNT_NO")
            # "1234567801" -> "12345678-01" 포맷 변환
            if account_no and len(account_no) == 10:
                summary["account_no"] = f"{account_no[:8]}-{account_no[8:]}"
            elif account_no:
                summary["account_no"] = account_no
        except Exception:
            pass
        broker_config = config.get("broker", {})
        if isinstance(broker_config, dict):
            summary["is_virtual"] = broker_config.get("is_paper", True)

    last_synced = getattr(treasury, "last_synced_at", None)
    if last_synced is not None:
        summary["synced_at"] = last_synced.isoformat()

    return summary


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    responses={503: {"description": "Treasury not available"}},
)
async def list_transactions(
    treasury: Annotated[Any, Depends(get_treasury)],
    type: str | None = None,
    bot_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """자금 변동 이력 조회."""
    db = getattr(treasury, "_db", None)
    if db is None:
        return {"items": [], "total": 0}

    where_clauses: list[str] = []
    params: list[str | int] = []

    if type:
        where_clauses.append("transaction_type = ?")
        params.append(type)
    if bot_id:
        where_clauses.append("bot_id = ?")
        params.append(bot_id)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_row = await db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM treasury_transactions{where_sql}",
        tuple(params),
    )
    total = count_row["cnt"] if count_row else 0

    query = (
        f"SELECT * FROM treasury_transactions{where_sql}"
        " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    )
    rows = await db.fetch_all(query, (*params, limit, offset))
    items = [
        {
            "id": r["id"],
            "type": r["transaction_type"],
            "bot_id": r["bot_id"],
            "amount": r["amount"],
            "description": r["description"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"items": items, "total": total}


@router.post(
    "/bots/{bot_id}/allocate",
    response_model=BudgetOperationResponse,
    responses={
        400: {"description": "Insufficient funds or invalid amount"},
        409: {"description": "Bot not stopped"},
        503: {"description": "Treasury not available"},
    },
)
async def allocate(
    bot_id: str,
    body: BudgetChangeRequest,
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """봇에 예산 할당."""
    from ante.treasury.exceptions import BotNotStoppedError

    try:
        success = await treasury.allocate(bot_id, body.amount)
    except BotNotStoppedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not success:
        raise HTTPException(
            status_code=400,
            detail=(
                "예산 할당 실패: 미할당 자금 부족 또는 금액 오류"
                f" (요청: {body.amount:,.0f}원)"
            ),
        )

    budget = treasury.get_budget(bot_id)
    return {
        "bot_id": bot_id,
        "allocated": budget.allocated if budget else 0.0,
        "available": budget.available if budget else 0.0,
    }


@router.post(
    "/bots/{bot_id}/deallocate",
    response_model=BudgetOperationResponse,
    responses={
        400: {"description": "Insufficient available budget"},
        409: {"description": "Bot not stopped"},
        503: {"description": "Treasury not available"},
    },
)
async def deallocate(
    bot_id: str,
    body: BudgetChangeRequest,
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """봇 예산 회수."""
    from ante.treasury.exceptions import BotNotStoppedError

    try:
        success = await treasury.deallocate(bot_id, body.amount)
    except BotNotStoppedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"예산 회수 실패: 가용 예산 부족 (요청: {body.amount:,.0f}원)",
        )

    budget = treasury.get_budget(bot_id)
    return {
        "bot_id": bot_id,
        "allocated": budget.allocated if budget else 0.0,
        "available": budget.available if budget else 0.0,
    }


@router.get(
    "/budgets",
    response_model=BudgetListResponse,
    responses={503: {"description": "Treasury not available"}},
)
async def list_budgets(
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """봇별 예산 목록 조회."""
    from dataclasses import asdict

    budgets = treasury.list_budgets()
    return {"budgets": [asdict(b) for b in budgets]}


@router.post(
    "/balance",
    response_model=BalanceSetResponse,
    responses={503: {"description": "Treasury not available"}},
)
async def set_balance(
    body: BalanceSetRequest,
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """계좌 총 잔고 수동 설정."""
    from datetime import UTC, datetime

    await treasury.set_account_balance(body.balance)
    return {
        "total_balance": treasury.account_balance,
        "updated_at": datetime.now(UTC).isoformat(),
    }
