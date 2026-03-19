"""전략 관리 API."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ante.web.deps import (
    get_bot_manager_optional,
    get_db,
    get_strategy_registry,
    get_trade_service,
    get_trade_service_optional,
)
from ante.web.schemas import (
    DailySummaryResponse,
    MonthlySummaryResponse,
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyPerformanceResponse,
    StrategyTradesResponse,
    StrategyValidateResponse,
    WeeklySummaryResponse,
)

router = APIRouter()

_STRATEGY_NOT_FOUND = "전략을 찾을 수 없습니다"


@router.post(
    "/validate",
    response_model=StrategyValidateResponse,
    responses={
        400: {"description": "Path is required"},
        404: {"description": "Strategy file not found"},
    },
)
async def validate_strategy(body: dict) -> dict:
    """전략 파일 정적 검증.

    Body: {"path": "/path/to/strategy.py"}
    """
    from ante.strategy.validator import StrategyValidator

    filepath = body.get("path", "")
    if not filepath:
        raise HTTPException(status_code=400, detail="path is required")

    path = Path(filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy file not found")

    validator = StrategyValidator()
    result = validator.validate(path)

    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get(
    "",
    response_model=StrategyListResponse,
    responses={503: {"description": "Strategy registry not available"}},
)
async def list_strategies(
    registry: Annotated[Any, Depends(get_strategy_registry)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    status: str | None = Query(default=None),
) -> dict:
    """전략 목록 조회."""
    records = await registry.list_strategies(status=status)

    bots_by_strategy: dict[str, dict] = {}
    if bot_manager is not None:
        for bot_info in bot_manager.list_bots():
            sid = bot_info.get("strategy_id", "")
            if sid:
                bots_by_strategy[sid] = bot_info

    strategies = []
    for r in records:
        bot_info = bots_by_strategy.get(r.strategy_id)
        strategies.append(
            {
                "id": r.strategy_id,
                "name": r.name,
                "version": r.version,
                "status": r.status.value
                if hasattr(r.status, "value")
                else str(r.status),
                "author": r.author,
                "bot_id": bot_info["bot_id"] if bot_info else None,
                "bot_status": bot_info["status"] if bot_info else None,
            }
        )

    return {"strategies": strategies}


@router.get(
    "/{strategy_id}",
    response_model=StrategyDetailResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry not available"},
    },
)
async def get_strategy(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 상세 조회."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    strategy_dict = asdict(record)
    strategy_dict["status"] = (
        record.status.value if hasattr(record.status, "value") else str(record.status)
    )
    # datetime → str 변환 (response_model 호환)
    if hasattr(record.registered_at, "isoformat"):
        strategy_dict["registered_at"] = record.registered_at.isoformat()

    bot_info = None
    if bot_manager is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                bot_info = b
                break

    return {"strategy": strategy_dict, "bot": bot_info}


@router.get(
    "/{strategy_id}/performance",
    response_model=StrategyPerformanceResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry or database not available"},
    },
)
async def get_strategy_performance(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    trade_service: Annotated[Any | None, Depends(get_trade_service_optional)],
) -> dict:
    """전략 성과 지표 조회."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)
    metrics = await tracker.calculate(strategy_id=strategy_id)

    result = asdict(metrics)

    # equity curve: bot_id가 있으면 추가
    equity_curve: list[dict] = []
    if bot_manager is not None and trade_service is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                from ante.report.feedback import PerformanceFeedback

                feedback = PerformanceFeedback(
                    trade_service=trade_service,
                    bot_manager=bot_manager,
                )
                equity_curve = await feedback.get_equity_curve(b["bot_id"])
                break

    result["equity_curve"] = equity_curve
    return result


@router.get(
    "/{strategy_id}/daily-summary",
    response_model=DailySummaryResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry or database not available"},
    },
)
async def get_strategy_daily_summary(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 일별 성과 집계."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    # strategy에 연결된 bot_id 찾기
    bot_id = None
    if bot_manager is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                bot_id = b["bot_id"]
                break

    summaries = await tracker.get_daily_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "date": s.date,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/weekly-summary",
    response_model=WeeklySummaryResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry or database not available"},
    },
)
async def get_strategy_weekly_summary(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 주별 성과 집계."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    bot_id = None
    if bot_manager is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                bot_id = b["bot_id"]
                break

    summaries = await tracker.get_weekly_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "week_start": s.week_start,
                "week_end": s.week_end,
                "week_label": s.week_label,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/monthly-summary",
    response_model=MonthlySummaryResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry or database not available"},
    },
)
async def get_strategy_monthly_summary(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 월별 성과 집계."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    bot_id = None
    if bot_manager is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                bot_id = b["bot_id"]
                break

    summaries = await tracker.get_monthly_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "year": s.year,
                "month": s.month,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/trades",
    response_model=StrategyTradesResponse,
    responses={
        404: {"description": "Strategy not found"},
        503: {"description": "Strategy registry or trade service not available"},
    },
)
async def get_strategy_trades(
    strategy_id: str,
    registry: Annotated[Any, Depends(get_strategy_registry)],
    trade_service: Annotated[Any, Depends(get_trade_service)],
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """전략 거래 내역 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    trades = await trade_service.get_trades(
        strategy_id=strategy_id,
        limit=limit + 1,
    )

    items = [
        {
            "trade_id": t.trade_id,
            "bot_id": t.bot_id,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "price": t.price,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "timestamp": str(t.timestamp),
        }
        for t in trades
    ]

    result = paginate(items, cursor_field="trade_id", limit=limit, cursor=cursor)
    return {"trades": result["items"], "next_cursor": result["next_cursor"]}
