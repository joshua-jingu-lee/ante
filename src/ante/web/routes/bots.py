"""봇 관리 API."""

from __future__ import annotations

import logging
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
from ante.web.schemas import (
    BotDetailResponse,
    BotListResponse,
    BotUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_BOT_NOT_FOUND = "BOT_NOT_FOUND: 봇을 찾을 수 없습니다"


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
    responses={
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
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
        400: {
            "description": "Strategy loading failed",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot already exists or conflict",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "strategy_id/strategy_name both missing, or budget allocation"
                " failed (Treasury error: insufficient funds, treasury not"
                " configured for account, etc.). On budget failure the newly"
                " created bot is rolled back via delete_bot(handle_positions="
                "'keep')."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        500: {
            "description": (
                "Internal error (e.g. budget allocation failed AND rollback"
                " also failed; bot may be left in partial state — manual"
                " inspection of bot status and treasury required)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager or strategy registry not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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

    # account_id 결정: 명시 전달이 우선, 미전달 시 단일 active 계좌만 자동 선택.
    # 0개/2개 이상은 명시적으로 BOT_MISSING_REQUIRED_ACCOUNT 에러 (#1218).
    # CLI `_resolve_account_non_interactive`와 일관된 정책.
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
                status_code=400,
                detail=(
                    "BOT_MISSING_REQUIRED_ACCOUNT: "
                    "활성 계좌가 없습니다. 먼저 계좌를 등록한 뒤 "
                    "account_id를 명시하세요."
                ),
            )
        if len(active) > 1:
            ids = ", ".join(
                a.account_id if hasattr(a, "account_id") else a["account_id"]
                for a in active
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "BOT_MISSING_REQUIRED_ACCOUNT: "
                    f"활성 계좌가 여러 개입니다. account_id를 명시하세요. "
                    f"(가능한 계좌: {ids})"
                ),
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
    # Refs #1335: 과거에는 ``except Exception: pass`` 로 모든 실패를 삼켜
    # client 가 예산 배정 실패를 감지할 수 없었다. 이제 ``TreasuryError``
    # 는 422 로 매핑하고, 신규 봇은 best-effort 롤백한다. 비-TreasuryError
    # (예: BotNotFoundError) 는 매핑하지 않고 propagate 시켜 기존 거동을
    # 유지한다 (대부분 500 으로 표면화).
    if body.budget is not None:
        from ante.treasury.exceptions import TreasuryError

        try:
            await bot_manager.update_bot(body.bot_id, budget=body.budget)
        except TreasuryError as e:
            # 롤백 try/except 는 별도 블록으로 분리한다. 같은 try 안에서
            # 422 HTTPException 을 raise 하면 외부 ``except Exception``
            # 에 잡혀 500 으로 오분류될 수 있기 때문이다.
            rollback_failed = False
            try:
                # Refs #1335 P2: ``hard=True`` — soft delete 만 수행하면
                # ``status='deleted'`` row 가 남아 같은 ``bot_id`` 재시도
                # 시 ``_save_bot_config()`` UPSERT 가 status 를 복구하지
                # 않으므로, 재시도가 ``201`` 을 반환해도 봇은 메모리에만
                # 존재하고 재시작 후 ``load_from_db()`` 에서 제외된다.
                # 생성 실패 rollback 경로에서는 row 자체를 제거해
                # 재시도 의미를 보존한다.
                await bot_manager.delete_bot(
                    body.bot_id, handle_positions="keep", hard=True
                )
            except Exception as rollback_error:
                rollback_failed = True
                logger.exception(
                    "budget 배정 실패 후 봇 롤백도 실패: %s — 부분 생성 상태 유지",
                    body.bot_id,
                )
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"budget allocation failed: {e}. "
                        f"rollback also failed; bot {body.bot_id} may be in "
                        "partial state. Check bot status and treasury manually."
                    ),
                ) from rollback_error
            # rollback 성공: 원 422 에러를 client 에 전달한다.
            # (rollback_failed 는 type checker 를 위한 가드 -- 위 raise 후
            # 도달하지 않지만 명시한다.)
            if not rollback_failed:
                raise HTTPException(status_code=422, detail=str(e)) from e

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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot state conflict",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": "Account credentials not configured",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot state conflict",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot state conflict",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": "Invalid handle_positions value",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot state conflict (not stopped)",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": "Budget update failed (e.g. insufficient funds)",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Bot manager not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Event history store not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
