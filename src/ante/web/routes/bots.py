"""봇 관리 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ante.web.deps import (
    get_account_service,
    get_audit_logger_optional,
    get_bot_manager,
    get_event_history_store_optional,
    get_eventbus_optional,
    get_strategy_registry,
    get_strategy_registry_optional,
    get_trade_service_optional,
    get_treasury_optional,
)
from ante.web.schemas import BotDetailResponse, BotListResponse, BotUpdateRequest

router = APIRouter()

_BOT_NOT_FOUND = "봇을 찾을 수 없습니다"


class BotCreateRequest(BaseModel):
    """봇 생성 요청.

    strategy_id 또는 strategy_name 중 하나를 필수로 전달해야 한다.
    strategy_name만 전달하면 최신 버전의 strategy_id로 자동 변환된다.
    """

    bot_id: str
    strategy_id: str | None = None
    strategy_name: str | None = None
    name: str = ""
    account_id: str | None = None
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    budget: float | None = Field(default=None, gt=0)


@router.get(
    "",
    response_model=BotListResponse,
    responses={503: {"description": "Bot manager not available"}},
)
async def list_bots(
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    account_id: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """봇 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    bots = bot_manager.list_bots()
    if account_id:
        bots = [
            b
            for b in bots
            if (
                b.get("account_id")
                if isinstance(b, dict)
                else getattr(b, "account_id", None)
            )
            == account_id
        ]

    # 전략 이름/작성자 조인
    if registry is not None:
        for bot_info in bots:
            sid = (
                bot_info.get("strategy_id", "")
                if isinstance(bot_info, dict)
                else getattr(bot_info, "strategy_id", "")
            )
            if sid:
                record = await registry.get(sid)
                if record:
                    if isinstance(bot_info, dict):
                        bot_info["strategy_name"] = record.name
                        bot_info["strategy_author_name"] = record.author_name
                        bot_info["strategy_author_id"] = record.author_id
                    else:
                        bot_info.strategy_name = record.name
                        bot_info.strategy_author_name = record.author_name
                        bot_info.strategy_author_id = record.author_id

    result = paginate(bots, cursor_field="bot_id", limit=limit, cursor=cursor)
    return {"bots": result["items"], "next_cursor": result["next_cursor"]}


@router.post(
    "",
    status_code=201,
    response_model=BotDetailResponse,
    responses={
        400: {"description": "Strategy loading failed"},
        404: {"description": "Strategy not found"},
        409: {"description": "Bot already exists or conflict"},
        422: {"description": "strategy_id/strategy_name both missing or budget error"},
        503: {"description": "Bot manager or strategy registry not available"},
    },
)
async def create_bot(
    body: BotCreateRequest,
    request: Request,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 생성."""
    from pathlib import Path

    from ante.account.models import AccountStatus
    from ante.bot.config import BotConfig
    from ante.bot.exceptions import BotError
    from ante.strategy.loader import StrategyLoader

    # strategy_id / strategy_name 해석 ─────────────────────
    strategy_id = body.strategy_id
    if strategy_id is None and body.strategy_name is not None:
        # strategy_name → 최신 버전 strategy_id 자동 변환
        records = await registry.get_by_name(body.strategy_name)
        if not records:
            raise HTTPException(
                status_code=404,
                detail=f"전략을 찾을 수 없습니다: {body.strategy_name}",
            )
        strategy_id = records[0].strategy_id
    if strategy_id is None:
        raise HTTPException(
            status_code=422,
            detail="strategy_id 또는 strategy_name 중 하나를 전달해야 합니다",
        )

    # account_id 기본값: 첫 번째 active 계좌 ───────────────
    account_id = body.account_id
    if account_id is None:
        accounts = await account_service.list()
        active = [
            a
            for a in accounts
            if (a.status if hasattr(a, "status") else a.get("status"))
            == AccountStatus.ACTIVE
        ]
        if not active:
            raise HTTPException(
                status_code=422,
                detail="활성 계좌가 없습니다. 계좌를 먼저 등록하세요",
            )
        account_id = (
            active[0].account_id
            if hasattr(active[0], "account_id")
            else active[0]["account_id"]
        )

    # 계좌 상태 검증: active가 아니면 봇 생성 거부
    account = await account_service.get(account_id)
    if account.status != AccountStatus.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=f"계좌가 '{account.status}' 상태이므로 봇을 생성할 수 없습니다",
        )

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    try:
        strategy_cls = StrategyLoader.load(Path(record.filepath))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"전략 로딩 실패: {e}") from e

    config = BotConfig(
        bot_id=body.bot_id,
        strategy_id=strategy_id,
        name=body.name or body.bot_id,
        account_id=account_id,
        interval_seconds=body.interval_seconds,
    )

    try:
        bot = await bot_manager.create_bot(
            config=config,
            strategy_cls=strategy_cls,
            source_path=Path(record.filepath),
        )
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    # budget이 지정된 경우 예산 배정 ────────────────────────
    if body.budget is not None:
        try:
            await bot_manager.update_bot(body.bot_id, budget=body.budget)
        except Exception:
            pass  # 봇은 이미 생성됨, budget 배정 실패는 무시 (이후 수정 가능)

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="bot.create",
            resource=f"bot:{body.bot_id}",
            detail=f"strategy={strategy_id}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


@router.get(
    "/{bot_id}",
    response_model=BotDetailResponse,
    responses={
        404: {"description": "Bot not found"},
        503: {"description": "Bot manager not available"},
    },
)
async def get_bot(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    treasury: Annotated[Any | None, Depends(get_treasury_optional)],
    trade_service: Annotated[Any | None, Depends(get_trade_service_optional)],
) -> dict:
    """봇 상세 조회."""
    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    info = bot.get_info()

    # 전략 정보 추가
    if registry is not None:
        record = await registry.get(info.get("strategy_id", ""))
        if record:
            info["strategy_name"] = record.name
            info["strategy_author_name"] = record.author_name
            info["strategy_author_id"] = record.author_id
            info["strategy"] = {
                "name": record.name,
                "version": record.version,
                "author_name": record.author_name,
                "author_id": record.author_id,
                "description": record.description,
            }

    # 예산 정보 추가
    if treasury is not None:
        budget = treasury.get_budget(bot_id)
        if budget:
            info["budget"] = {
                "allocated": budget.allocated,
                "spent": budget.spent,
                "reserved": budget.reserved,
                "available": budget.available,
            }

    # 포지션 정보 추가
    if trade_service is not None:
        positions = await trade_service.get_positions(
            bot_id=bot_id, include_closed=True
        )
        info["positions"] = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "realized_pnl": p.realized_pnl,
            }
            for p in positions
        ]

    return {"bot": info}


@router.post(
    "/{bot_id}/start",
    response_model=BotDetailResponse,
    responses={
        404: {"description": "Bot not found"},
        409: {"description": "Bot state conflict"},
        422: {"description": "Account credentials not configured"},
        503: {"description": "Bot manager not available"},
    },
)
async def start_bot(
    bot_id: str,
    request: Request,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 시작."""
    from ante.bot.exceptions import BotError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    # 계좌 인증정보 검증: app_key가 없으면 봇 시작 거부
    account = await account_service.get(bot.config.account_id)
    if not account.credentials.get("app_key"):
        raise HTTPException(
            status_code=422,
            detail="계좌에 인증정보(app_key)가 설정되지 않았습니다",
        )

    try:
        await bot_manager.start_bot(bot_id)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="bot.start",
            resource=f"bot:{bot_id}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


@router.post(
    "/{bot_id}/stop",
    response_model=BotDetailResponse,
    responses={
        404: {"description": "Bot not found"},
        409: {"description": "Bot state conflict"},
        503: {"description": "Bot manager not available"},
    },
)
async def stop_bot(
    bot_id: str,
    request: Request,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 중지."""
    from ante.bot.exceptions import BotError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    try:
        await bot_manager.stop_bot(bot_id)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="bot.stop",
            resource=f"bot:{bot_id}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


@router.delete(
    "/{bot_id}",
    status_code=204,
    responses={
        404: {"description": "Bot not found"},
        409: {"description": "Bot state conflict"},
        422: {"description": "Invalid handle_positions value"},
        503: {"description": "Bot manager not available"},
    },
)
async def delete_bot(
    bot_id: str,
    request: Request,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
    handle_positions: str = "keep",
) -> None:
    """봇 삭제.

    handle_positions:
        - keep (기본): 포지션을 유지한 채 봇만 삭제.
        - liquidate: 보유 종목 시장가 매도 주문 발행 후 삭제.
    """
    from ante.bot.exceptions import BotError

    if handle_positions not in ("keep", "liquidate"):
        raise HTTPException(
            status_code=422,
            detail=f"잘못된 handle_positions 값: {handle_positions!r} "
            f"(허용: keep, liquidate)",
        )

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    try:
        await bot_manager.delete_bot(bot_id, handle_positions=handle_positions)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="bot.delete",
            resource=f"bot:{bot_id}",
            detail=f"handle_positions={handle_positions}",
            ip=request.client.host if request.client else "",
        )


@router.put(
    "/{bot_id}",
    response_model=BotDetailResponse,
    responses={
        404: {"description": "Bot not found"},
        409: {"description": "Bot state conflict (not stopped)"},
        422: {"description": "Budget update failed (e.g. insufficient funds)"},
        503: {"description": "Bot manager not available"},
    },
)
async def update_bot(
    bot_id: str,
    body: BotUpdateRequest,
    request: Request,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 설정 수정. 중지 상태에서만 허용."""
    from ante.bot.exceptions import BotError
    from ante.treasury.exceptions import TreasuryError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"bot": bot.get_info()}

    # strategy_name → strategy_id 변환
    strategy_name = updates.pop("strategy_name", None)
    if strategy_name is not None:
        if registry is None:
            raise HTTPException(
                status_code=503, detail="전략 레지스트리를 사용할 수 없습니다"
            )
        records = await registry.get_by_name(strategy_name)
        if not records:
            raise HTTPException(
                status_code=404, detail=f"전략을 찾을 수 없습니다: {strategy_name}"
            )
        updates["strategy_id"] = records[0].strategy_id

    try:
        bot = await bot_manager.update_bot(bot_id, **updates)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except TreasuryError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="bot.update",
            resource=f"bot:{bot_id}",
            detail=f"fields={list(updates.keys())}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


@router.get(
    "/{bot_id}/logs",
    responses={
        404: {"description": "Bot not found"},
        503: {"description": "Event history store not available"},
    },
)
async def get_bot_logs(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    event_history_store: Annotated[
        Any | None, Depends(get_event_history_store_optional)
    ],
    eventbus: Annotated[Any | None, Depends(get_eventbus_optional)],
    limit: int = 50,
) -> dict:
    """봇 실행 로그 조회.

    BotStepCompletedEvent 이력을 반환한다.
    event_history_store(SQLite)가 있으면 영속 로그를 조회하고,
    없으면 EventBus 인메모리 히스토리에서 조회한다.
    """
    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    logs: list[dict] = []

    if event_history_store is not None:
        rows = await event_history_store.query(
            event_type="BotStepCompletedEvent",
            limit=limit,
        )
        for row in rows:
            payload = row.get("payload", {})
            if payload.get("bot_id") == bot_id:
                logs.append(
                    {
                        "event_id": row.get("event_id", ""),
                        "timestamp": row.get("timestamp", ""),
                        "result": payload.get("result", ""),
                        "message": payload.get("message", ""),
                    }
                )
    elif eventbus is not None:
        from ante.eventbus.events import BotStepCompletedEvent

        history = eventbus.get_history(event_type=BotStepCompletedEvent, limit=limit)
        for evt in history:
            if evt.bot_id == bot_id:
                logs.append(
                    {
                        "event_id": str(evt.event_id),
                        "timestamp": evt.timestamp.isoformat(),
                        "result": evt.result,
                        "message": evt.message,
                    }
                )

    return {"bot_id": bot_id, "logs": logs}
