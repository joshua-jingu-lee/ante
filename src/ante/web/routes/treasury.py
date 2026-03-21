"""Treasury 자금 관리 API."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ante.web.deps import (
    get_audit_logger_optional,
    get_bot_manager_optional,
    get_treasury,
    get_treasury_manager_optional,
)
from ante.web.schemas import (
    BalanceSetResponse,
    BudgetListResponse,
    BudgetOperationResponse,
    TransactionListResponse,
    TreasurySummaryResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


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
    responses={
        404: {"description": "Account not found"},
        503: {"description": "Treasury not available"},
    },
)
async def get_summary(
    request: Request,
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """자금 현황 요약.

    account_id 지정 시 해당 계좌의 Treasury 요약을 반환한다.
    미지정 시 기본 Treasury 요약을 반환한다 (하위 호환).
    """
    target_treasury = treasury
    if account_id and treasury_manager is not None:
        try:
            target_treasury = treasury_manager.get(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"계좌를 찾을 수 없습니다: {account_id}",
            )

    summary = target_treasury.get_summary()
    summary["account_id"] = getattr(target_treasury, "account_id", None)
    summary["currency"] = getattr(target_treasury, "currency", "KRW")
    summary["commission_rate"] = getattr(
        target_treasury, "buy_commission_rate", 0.00015
    )
    summary["sell_tax_rate"] = getattr(target_treasury, "sell_commission_rate", 0.00195)

    # 브로커 메타정보 (하위 호환)
    broker = getattr(request.app.state, "broker", None)
    if broker is not None:
        summary["broker_id"] = broker.broker_id
        summary["broker_name"] = broker.broker_name
        summary["broker_short_name"] = broker.broker_short_name
        summary["exchange"] = broker.exchange

    # KIS 계좌 헤더 정보 (하위 호환)
    config = getattr(request.app.state, "config", None)
    if config is not None:
        try:
            account_no = config.secret("KIS_ACCOUNT_NO")
            if account_no and len(account_no) == 10:
                summary["account_no"] = f"{account_no[:8]}-{account_no[8:]}"
            elif account_no:
                summary["account_no"] = account_no
        except Exception as e:
            logger.warning("KIS 계좌번호 조회 실패: %s", e)
        broker_config = config.get("broker", {})
        if isinstance(broker_config, dict):
            summary["is_virtual"] = broker_config.get("is_paper", True)

    last_synced = getattr(target_treasury, "last_synced_at", None)
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
    account_id: str | None = None,
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

    if account_id:
        where_clauses.append("account_id = ?")
        params.append(account_id)
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
        404: {"description": "Bot not found"},
        409: {"description": "Bot not stopped"},
        503: {"description": "Treasury not available"},
    },
)
async def allocate(
    bot_id: str,
    body: BudgetChangeRequest,
    request: Request,
    treasury: Annotated[Any, Depends(get_treasury)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇에 예산 할당."""
    from ante.treasury.exceptions import BotNotStoppedError

    if bot_manager is not None and bot_manager.get_bot(bot_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"봇을 찾을 수 없습니다: {bot_id}",
        )

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

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="treasury.allocate",
            resource=f"bot:{bot_id}",
            detail=f"amount={body.amount:,.0f}",
            ip=request.client.host if request.client else "",
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
        404: {"description": "Bot not found"},
        409: {"description": "Bot not stopped"},
        503: {"description": "Treasury not available"},
    },
)
async def deallocate(
    bot_id: str,
    body: BudgetChangeRequest,
    request: Request,
    treasury: Annotated[Any, Depends(get_treasury)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 예산 회수."""
    from ante.treasury.exceptions import BotNotStoppedError

    if bot_manager is not None and bot_manager.get_bot(bot_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"봇을 찾을 수 없습니다: {bot_id}",
        )

    try:
        success = await treasury.deallocate(bot_id, body.amount)
    except BotNotStoppedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"예산 회수 실패: 가용 예산 부족 (요청: {body.amount:,.0f}원)",
        )

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="treasury.deallocate",
            resource=f"bot:{bot_id}",
            detail=f"amount={body.amount:,.0f}",
            ip=request.client.host if request.client else "",
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
    items = []
    for b in budgets:
        d = asdict(b)
        # datetime → str 변환 (response_model 호환)
        if hasattr(b.last_updated, "isoformat"):
            d["last_updated"] = b.last_updated.isoformat()
        items.append(d)
    return {"budgets": items}


@router.post(
    "/balance",
    response_model=BalanceSetResponse,
    responses={503: {"description": "Treasury not available"}},
)
async def set_balance(
    body: BalanceSetRequest,
    request: Request,
    treasury: Annotated[Any, Depends(get_treasury)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """계좌 총 잔고 수동 설정."""
    from datetime import UTC, datetime

    await treasury.set_account_balance(body.balance)

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="treasury.set_balance",
            resource="treasury",
            detail=f"balance={body.balance:,.0f}",
            ip=request.client.host if request.client else "",
        )

    return {
        "total_balance": treasury.account_balance,
        "updated_at": datetime.now(UTC).isoformat(),
    }


# ── 일별 자산 스냅샷 ──────────────────────────────────────


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
    "/snapshots/latest",
    responses={
        404: {"description": "No snapshot found"},
        503: {"description": "Treasury not available"},
    },
)
async def get_latest_snapshot(
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """가장 최근 일별 스냅샷 조회."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_latest_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="스냅샷이 없습니다")
    return {"snapshot": snapshot}


@router.get(
    "/snapshots",
    responses={503: {"description": "Treasury not available"}},
)
async def list_snapshots(
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """기간별 일별 스냅샷 목록."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)

    if start_date is None:
        start_date = "2000-01-01"
    if end_date is None:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")

    snapshots = await target.get_snapshots(start_date, end_date)
    return {"snapshots": snapshots}


@router.get(
    "/snapshots/{date}",
    responses={
        404: {"description": "Snapshot not found"},
        503: {"description": "Treasury not available"},
    },
)
async def get_snapshot_by_date(
    date: str,
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """특정일 스냅샷 조회."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_daily_snapshot(date)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"스냅샷을 찾을 수 없습니다: {date}",
        )
    return {"snapshot": snapshot}
