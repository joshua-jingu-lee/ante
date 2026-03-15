"""전략 관리 API."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.post("/validate")
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


@router.get("")
async def list_strategies(
    request: Request,
    status: str | None = Query(default=None),
) -> dict:
    """전략 목록 조회."""
    registry = getattr(request.app.state, "strategy_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")

    records = await registry.list_strategies(status=status)

    bot_manager = getattr(request.app.state, "bot_manager", None)
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
                "bot_id": bot_info["bot_id"] if bot_info else None,
                "bot_status": bot_info["status"] if bot_info else None,
            }
        )

    return {"strategies": strategies}


@router.get("/{strategy_id}")
async def get_strategy(request: Request, strategy_id: str) -> dict:
    """전략 상세 조회."""
    registry = getattr(request.app.state, "strategy_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    strategy_dict = asdict(record)
    strategy_dict["status"] = (
        record.status.value if hasattr(record.status, "value") else str(record.status)
    )

    bot_info = None
    bot_manager = getattr(request.app.state, "bot_manager", None)
    if bot_manager is not None:
        for b in bot_manager.list_bots():
            if b.get("strategy_id") == strategy_id:
                bot_info = b
                break

    return {"strategy": strategy_dict, "bot": bot_info}


@router.get("/{strategy_id}/performance")
async def get_strategy_performance(request: Request, strategy_id: str) -> dict:
    """전략 성과 지표 조회."""
    registry = getattr(request.app.state, "strategy_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    trade_service = getattr(request.app.state, "trade_service", None)
    if trade_service is None:
        raise HTTPException(status_code=503, detail="Trade service not available")

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(trade_service)
    metrics = await tracker.calculate(strategy_id=strategy_id)

    result = asdict(metrics)

    # equity curve: bot_id가 있으면 추가
    equity_curve: list[dict] = []
    bot_manager = getattr(request.app.state, "bot_manager", None)
    if bot_manager is not None:
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


@router.get("/{strategy_id}/trades")
async def get_strategy_trades(
    request: Request,
    strategy_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """전략 거래 내역 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    registry = getattr(request.app.state, "strategy_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    trade_service = getattr(request.app.state, "trade_service", None)
    if trade_service is None:
        raise HTTPException(status_code=503, detail="Trade service not available")

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
