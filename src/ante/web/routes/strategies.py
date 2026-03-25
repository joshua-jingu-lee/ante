"""전략 관리 API."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ante.web.deps import (
    get_bot_manager_optional,
    get_db,
    get_db_optional,
    get_strategy_registry,
    get_trade_service,
    get_trade_service_optional,
)
from ante.web.schemas import (
    DailySummaryResponse,
    MonthlySummaryResponse,
    StatusUpdateRequest,
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyPerformanceResponse,
    StrategyTradesResponse,
    StrategyValidateResponse,
    WeeklySummaryResponse,
)

router = APIRouter()

_STRATEGY_NOT_FOUND = "전략을 찾을 수 없습니다"
_VALID_STATUS_FILTERS = {"registered", "adopted", "archived"}
_logger = logging.getLogger(__name__)


def _find_bot_for_strategy(bot_manager: Any, strategy_id: str) -> dict | None:
    """bot_manager에서 strategy_id에 매칭되는 봇을 찾아 반환한다."""
    if bot_manager is None:
        return None
    for b in bot_manager.list_bots():
        if b.get("strategy_id") == strategy_id:
            return b
    return None


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
    db: Annotated[Any | None, Depends(get_db_optional)],
    status: str | None = Query(default=None),
) -> dict:
    """전략 목록 조회."""
    if status is not None and status not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않은 status 값: {status} "
            f"(허용: {', '.join(sorted(_VALID_STATUS_FILTERS))})",
        )
    records = await registry.list_strategies(status=status)

    bots_by_strategy: dict[str, dict] = {}
    if bot_manager is not None:
        for bot_info in bot_manager.list_bots():
            sid = bot_info.get("strategy_id", "")
            if sid:
                bots_by_strategy[sid] = bot_info

    # 전략별 cumulative_return 일괄 조회
    cumulative_returns: dict[str, float | None] = {}
    if db is not None:
        from ante.trade.performance import PerformanceTracker

        tracker = PerformanceTracker(db)

        # N+1 해소: asyncio.gather 로 병렬 호출
        def _account_id_for(r: Any) -> str:
            bi = bots_by_strategy.get(r.strategy_id)
            return bi.get("account_id", "default") if bi else "default"

        tasks = [
            tracker.calculate(account_id=_account_id_for(r), strategy_id=r.strategy_id)
            for r in records
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r, result in zip(records, results):
            if isinstance(result, BaseException):
                _logger.debug(
                    "전략 %s cumulative_return 계산 실패",
                    r.strategy_id,
                    exc_info=result,
                )
                cumulative_returns[r.strategy_id] = None
            elif result.total_trades > 0:
                cumulative_returns[r.strategy_id] = result.net_pnl
            else:
                cumulative_returns[r.strategy_id] = None

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
                "author_name": r.author_name,
                "author_id": r.author_id,
                "bot_id": bot_info["bot_id"] if bot_info else None,
                "bot_status": bot_info["status"] if bot_info else None,
                "cumulative_return": cumulative_returns.get(r.strategy_id),
            }
        )

    return {"strategies": strategies}


@router.patch(
    "/{strategy_id}/status",
    status_code=204,
    responses={
        400: {"description": "허용되지 않은 상태 전환"},
        404: {"description": "Strategy not found"},
    },
)
async def update_strategy_status(
    strategy_id: str,
    body: StatusUpdateRequest,
    registry: Annotated[Any, Depends(get_strategy_registry)],
) -> None:
    """전략 상태 변경. 보관 전환용."""
    from ante.strategy.exceptions import StrategyError
    from ante.strategy.registry import StrategyStatus

    try:
        new_status = StrategyStatus(body.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 status 값: {body.status} "
            f"(허용: {', '.join(s.value for s in StrategyStatus)})",
        )

    try:
        await registry.update_status(strategy_id, new_status)
    except StrategyError:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    # datetime -> str 변환 (response_model 호환)
    if hasattr(record.registered_at, "isoformat"):
        strategy_dict["registered_at"] = record.registered_at.isoformat()

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)

    # 전략 클래스에서 params/param_schema 런타임 추출
    params: dict[str, Any] = {}
    param_schema: dict[str, str] = {}
    filepath = record.filepath
    if filepath:
        try:
            from ante.strategy.loader import StrategyLoader

            strategy_cls = StrategyLoader.load(Path(filepath))
            instance = strategy_cls(ctx=None)
            params = instance.get_params()
            param_schema = instance.get_param_schema()
        except Exception:
            _logger.debug(
                "전략 %s params 추출 실패 (filepath=%s)",
                strategy_id,
                filepath,
                exc_info=True,
            )

    # rationale, risks: StrategyRecord에서 추출
    rationale = getattr(record, "rationale", "") or ""
    risks = getattr(record, "risks", []) or []

    return {
        "strategy": strategy_dict,
        "bot": bot_info,
        "status": strategy_dict["status"],
        "params": params,
        "param_schema": param_schema,
        "rationale": rationale,
        "risks": risks,
    }


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
    account_id: str | None = None,
) -> dict:
    """전략 성과 지표 조회."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    # account_id 결정: 쿼리 파라미터 우선, 없으면 봇에서 추출
    resolved_account_id = account_id
    if not resolved_account_id:
        bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
        if bot_info:
            resolved_account_id = bot_info.get("account_id")
    if not resolved_account_id:
        resolved_account_id = "default"

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)
    metrics = await tracker.calculate(
        account_id=resolved_account_id, strategy_id=strategy_id
    )

    result = asdict(metrics)
    # sharpe_ratio가 None이면 응답 모델(float)과 호환되도록 0.0으로 변환
    if result.get("sharpe_ratio") is None:
        result["sharpe_ratio"] = 0.0

    # equity curve: bot_id가 있으면 추가
    equity_curve: list[dict] = []
    if trade_service is not None:
        bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
        if bot_info:
            from ante.report.feedback import PerformanceFeedback

            assert bot_manager is not None  # guarded by bot_info check
            feedback = PerformanceFeedback(
                trade_service=trade_service,
                bot_manager=bot_manager,
            )
            equity_curve = await feedback.get_equity_curve(bot_info["bot_id"])

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
    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

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

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

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

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

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
            "trade_id": str(t.trade_id),
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
