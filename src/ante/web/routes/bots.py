"""봇 관리 API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    require_bot_admin,
    require_bot_read,
)
from ante.web.errors import sanitize_validation_errors
from ante.web.schemas import (
    BotDetailResponse,
    BotListResponse,
    BotUpdateRequest,
)
from ante.web.utils.account_params import reject_invalid_account_id
from ante.web.utils.date_params import reject_inverted_date_range

logger = logging.getLogger(__name__)

router = APIRouter()

_BOT_NOT_FOUND = "BOT_NOT_FOUND: 봇을 찾을 수 없습니다"

# bot logs API (#1437) — r2는 ``EventHistoryStore``에 SQL JSON1
# ``payload_filter``를 추가해 ``bot_id``를 SQL 단계에서 필터링하므로
# in-memory fetch hard cap이 필요 없다. r1의 ``_BOT_LOGS_FETCH_HARD_CAP``
# (=10000)은 다른 봇의 로그가 cap을 채워서 특정 봇 로그를 누락시킬 수
# 있는 silent failure였다(Codex P2 #2). r2에서 제거됨.
#
# in-memory ``EventBus.get_history`` fallback도 동일 문제(다른 봇 로그가
# cap을 채워 특정 봇 로그를 누락)가 있어 r3에서 추가 cap을 제거한다.
# Ring buffer는 ``EventBus._history_size`` (기본 1000)로 이미 자연 제한
# 되므로, 그 값을 그대로 ``limit``으로 넘겨 ring buffer 전체를 가져온다.


class BotCreateRequest(BaseModel):
    """봇 생성 요청.

    strategy_id 또는 strategy_name 중 하나를 필수로 전달해야 한다 (#1436).
    strategy_name만 전달하면 최신 버전의 strategy_id로 자동 변환된다.
    둘 다 전달되면 strategy_id를 우선 사용한다.

    ``model_config = ConfigDict(extra="forbid")``로 미지정 필드는 422로 거부된다
    (#1436). 과거 ``bot_type`` 같은 legacy 키는 무시(silent drop)되었으나
    스펙과 코드 truth(``manager.py:124-125``)가 일치하지 않아 호출자가
    잘못된 payload를 보내도 감지되지 않았다.
    """

    model_config = ConfigDict(extra="forbid")

    bot_id: str
    strategy_id: str | None = None
    strategy_name: str | None = None
    name: str = ""
    account_id: str | None = None
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    budget: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _require_strategy_identifier(self) -> BotCreateRequest:
        """strategy_id 또는 strategy_name 중 하나 이상 필수 (#1436).

        둘 다 None이면 ValidationError로 422 거부. 둘 다 전달돼도 허용하며,
        handler는 strategy_id를 우선 사용한다(``create_bot`` L339-348).
        """
        if self.strategy_id is None and self.strategy_name is None:
            raise ValueError(
                "strategy_id 또는 strategy_name 중 하나가 필요합니다 "
                "(둘 다 전달 시 strategy_id 우선)"
            )
        return self


# POST /api/bots OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1371). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type BotCreateRequest``를
# 만들지 못한다. 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고
# 본체 schema는 ``_install_openapi_customizer``가 ``components.schemas``에
# 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴).
BOT_CREATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "BotCreateRequest",
    "description": (
        "POST /api/bots 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1371). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다. "
        "Pydantic ``extra='forbid'`` (#1436) — 정의되지 않은 필드(예: legacy "
        "``bot_type``)는 422로 거부된다. "
        "strategy_id 또는 strategy_name 중 하나를 필수로 전달해야 하며 "
        "(model_validator로 강제, #1436), 둘 다 전달 시 strategy_id를 우선 사용한다. "
        "OpenAPI ``anyOf`` 로 strategy 식별자 필수 조건을 명시하여 generated "
        "TS/SDK 가 ``{bot_id: ...}`` 만 담긴 payload 를 valid 로 인식하지 못하도록 "
        "한다 (codex r1 FAIL). anyOf branches 는 ``type``/``properties`` 까지 "
        "명시하여 openapi-typescript 가 ``unknown`` 으로 붕괴되지 않고 "
        "``{strategy_id: string} | {strategy_name: string}`` 으로 narrow 되도록 "
        "한다 (codex r2 FAIL)."
    ),
    "additionalProperties": False,
    "required": ["bot_id"],
    "anyOf": [
        {
            "type": "object",
            "required": ["strategy_id"],
            "properties": {"strategy_id": {"type": "string"}},
        },
        {
            "type": "object",
            "required": ["strategy_name"],
            "properties": {"strategy_name": {"type": "string"}},
        },
    ],
    "properties": {
        "bot_id": {
            "type": "string",
            "description": "생성할 봇의 식별자.",
        },
        "strategy_id": {
            "type": ["string", "null"],
            "description": (
                "전략 ID. ``strategy_name``과 둘 중 하나는 반드시 전달해야 한다."
            ),
        },
        "strategy_name": {
            "type": ["string", "null"],
            "description": (
                "전략 이름. 최신 버전의 strategy_id로 자동 변환된다. "
                "``strategy_id``와 둘 중 하나는 반드시 전달해야 한다."
            ),
        },
        "name": {
            "type": "string",
            "default": "",
            "description": "사용자에게 표시되는 봇 이름. 비우면 bot_id를 사용한다.",
        },
        "account_id": {
            "type": ["string", "null"],
            "description": (
                "사용할 계좌 ID. 미지정 시 단일 active 계좌가 자동 선택된다."
            ),
        },
        "interval_seconds": {
            "type": "integer",
            "minimum": 10,
            "maximum": 3600,
            "default": 60,
            "description": "봇 step 주기 (초).",
        },
        "budget": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "description": (
                "예산 할당액 (원). 양수 finite number만 허용 "
                "(Infinity/NaN은 422로 거부, #1435)."
            ),
        },
    },
}


@router.get(
    "",
    response_model=BotListResponse,
    responses={
        422: {
            "description": (
                "Invalid ``account_id`` query. 제공된 runtime-invalid 값"
                ' (``""``/``"default"``/``^[a-zA-Z0-9\\-]{3,30}$`` 불일치)은'
                " 필터링 이전에 422로 거부된다 — ``if account_id`` truthy 분기가"
                ' provided-``""``/invalid를 빈 목록/전체 반환으로 흡수하던'
                " contract-drift를 차단한다. ``account_id`` 미지정(``None``)은"
                " 전체 봇 반환으로 통과한다 (#1218 보존, #1624)."
            ),
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
async def list_bots(
    _caller_id: Annotated[str, Depends(require_bot_read)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    account_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    """봇 목록 조회 (cursor 기반 페이지네이션). 인증된 master/human 또는
    ``bot:read`` scope 를 보유한 agent 만 호출 가능 (#1407).

    제공된 runtime-invalid ``account_id`` (``""``/``"default"``/패턴 위반)는
    필터링 **이전**에 422로 거부한다 (#1624). 기존 ``if account_id`` truthy
    분기는 provided-``""``를 omitted처럼 흡수(전체 반환)하고 ``"default"``/
    패턴위반은 빈 목록으로 흡수하던 contract-drift였다. 이제 ingress 가드 +
    ``account_id is not None`` 명시 필터로 교체해 ``None``(미지정)만 전체
    반환 분기로 통과시킨다 (#1218 보존). valid-pattern but absent
    (``acc-9999``)는 가드를 통과해 기존 200 empty(매칭 0건)를 유지한다."""
    from ante.web.pagination import paginate

    reject_invalid_account_id(account_id)

    bots = bot_manager.list_bots()
    if account_id is not None:
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
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization header "
                "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
                "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
                "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 bot:admin "
                "scope 보유 agent 만 허용)"
            ),
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
                "Body validation 실패 (JSON 파싱 실패, 빈 body, type mismatch, "
                "미지정 필드, strategy_id/strategy_name 동시 누락) 또는 budget "
                "allocation 실패 (Treasury error: insufficient funds, treasury "
                "not configured for account, etc.). On budget failure the newly "
                "created bot is rolled back via delete_bot(handle_positions="
                "'keep'). 단, 인증이 실패하면 body validation은 실행되지 않고 "
                "401이 우선 반환된다(#1371)."
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
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/BotCreateRequest"},
                },
            },
        },
    },
)
async def create_bot(
    request: Request,
    caller_id: Annotated[str, Depends(require_bot_admin)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 생성. 인증된 master/human 또는 ``bot:admin`` scope 를 보유한 agent
    만 호출 가능 (#1407 — spec ``bot:admin`` 정합, #1371 master_caller 에서
    마이그레이션).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: BotCreateRequest`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_bot_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``BotCreateRequest.model_validate`` — ValidationError → 422.
    4. service 호출 (``BotError`` → 409, ``TreasuryError`` → 422).
    """
    from pathlib import Path

    from ante.account.errors import AccountNotFoundError
    from ante.account.models import AccountStatus
    from ante.bot.config import BotConfig
    from ante.bot.exceptions import BotError
    from ante.strategy.loader import StrategyLoader

    # 1. raw body 읽기 + JSON 파싱 — 인증 통과 후에만 실행된다.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422, detail="요청 body의 JSON 파싱에 실패했습니다."
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422, detail="요청 body는 JSON object여야 합니다."
        )

    # 2. Pydantic 검증.
    try:
        body = BotCreateRequest.model_validate(payload)
    except ValidationError as e:
        # 공용 chokepoint ``sanitize_validation_errors`` 로 detail 을 sanitize
        # 한다 (codex r3 FAIL #1436 + #1650). ``_require_strategy_identifier``
        # model_validator 가 raise 하는 ``ValueError`` 는 Pydantic
        # ``e.errors()`` 의 ``ctx.error`` 필드에 ``ValueError`` 객체로
        # 노출된다. ``HTTPException(detail=e.errors())`` 를 그대로 사용하면
        # ``http_exception_handler`` 가 ``str(exc.detail)`` 로 Python repr 을
        # 그대로 노출(``ValueError('...')``)하여 호출자가 구조적으로 파싱할
        # 수 없는 깨진 응답이 된다. ``budget`` 같은 finite-positive 필드에
        # NaN/Inf 가 들어오면 ``input`` 에도 non-finite ``float`` 가 담겨
        # ``JSONResponse(allow_nan=False)`` 가 직렬화에 실패해 422 대신 500 이
        # 반환될 수 있는 잠재 위험도 chokepoint 가 함께 sanitize 한다 (#1380
        # accounts.py RuleUpdateRequest 선례). chokepoint 는 추가로
        # ``extra_forbidden`` 항목의 ``loc`` 말단 caller 키를 placeholder 로
        # 정규화한다 (#1650 L2; ``bot_type`` 등 extra='forbid' 거부 키).
        raise HTTPException(
            status_code=422,
            detail=sanitize_validation_errors(e),
        ) from None

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

    # 계좌 상태 검증: active가 아니면 봇 생성 거부.
    # ``account_id`` 가 명시 전달됐는데 존재하지 않는 경우 account 라우트
    # SSOT(``accounts.py``)와 동일하게 404로 변환한다(#1371). catch 없이
    # propagate하면 500이 되어 client는 잘못된 입력 vs 시스템 오류를 구분할 수
    # 없다.
    try:
        account = await account_service.get(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(
            status_code=404, detail=f"계좌를 찾을 수 없습니다: {account_id}"
        ) from e
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
            member_id=caller_id,
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
    _caller_id: Annotated[str, Depends(require_bot_read)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    treasury: Annotated[Any | None, Depends(get_treasury_optional)],
    trade_service: Annotated[Any | None, Depends(get_trade_service_optional)],
) -> dict:
    """봇 상세 조회. 인증된 master/human 또는 ``bot:read`` scope 를 보유한
    agent 만 호출 가능 (#1407)."""
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
    caller_id: Annotated[str, Depends(require_bot_admin)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 시작. 인증된 master/human 또는 ``bot:admin`` scope 를 보유한 agent
    만 호출 가능 (#1407)."""
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
            member_id=caller_id,
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
    caller_id: Annotated[str, Depends(require_bot_admin)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 중지. 인증된 master/human 또는 ``bot:admin`` scope 를 보유한 agent
    만 호출 가능 (#1407)."""
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
            member_id=caller_id,
            action="bot.stop",
            resource=f"bot:{bot_id}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


@router.delete(
    "/{bot_id}",
    status_code=204,
    responses={
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization header "
                "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
                "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
                "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 bot:admin "
                "scope 보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
    caller_id: Annotated[str, Depends(require_bot_admin)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
    handle_positions: str = "keep",
) -> None:
    """봇 삭제. 인증된 master/human 또는 ``bot:admin`` scope 를 보유한 agent
    만 호출 가능 (#1407 — spec ``bot:admin`` 정합, #1371 master_caller 에서
    마이그레이션).

    body가 없으므로 raw-body cold-path는 적용하지 않는다. 인증 가드가
    handle_positions query 파라미터 검증보다 먼저 실행되어 unauth는 401,
    non-master는 403으로 차단된다.

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
            member_id=caller_id,
            action="bot.delete",
            resource=f"bot:{bot_id}",
            detail=f"handle_positions={handle_positions}",
            ip=request.client.host if request.client else "",
        )


# PUT /api/bots/{bot_id} OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1352). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type BotUpdateRequest``를
# 만들지 못한다. 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고
# 본체 schema는 ``_install_openapi_customizer``가 ``components.schemas``에
# 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴).
BOT_UPDATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "BotUpdateRequest",
    "description": (
        "PUT /api/bots/{bot_id} 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1352). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다. "
        "None/null인 필드는 변경하지 않는다."
    ),
    "additionalProperties": False,
    # 모든 필드는 ``str | None = None`` Pydantic 정의와 정합하도록 nullable로
    # 노출한다 — 기존 frontend axios 클라이언트(``frontend/src/api/bots.ts``)는
    # 각 옵셔널 필드에 ``null`` 또는 값으로 전달하므로 nullable 누락 시 codegen
    # 결과에서 ``null`` payload가 type error로 거부된다.
    "properties": {
        "name": {
            "type": ["string", "null"],
            "description": "사용자에게 표시되는 봇 이름.",
        },
        "strategy_name": {
            "type": ["string", "null"],
            "description": "변경할 전략 이름. 최신 버전의 strategy_id로 자동 변환된다.",
        },
        "interval_seconds": {
            "type": ["integer", "null"],
            "minimum": 10,
            "maximum": 3600,
            "description": "봇 step 주기 (초).",
        },
        "budget": {
            "type": ["number", "null"],
            "exclusiveMinimum": 0,
            "description": (
                "예산 할당액 (원). 양수 finite number만 허용 "
                "(Infinity/NaN은 422로 거부, #1435)."
            ),
        },
        "auto_restart": {
            "type": ["boolean", "null"],
            "description": "봇 자동 재시작 여부.",
        },
        "max_restart_attempts": {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": 10,
            "description": (
                "재시작 최대 시도 횟수. 허용 범위 1~10 외 값은 422 (#1456)."
            ),
        },
        "restart_cooldown_seconds": {
            "type": ["integer", "null"],
            "minimum": 10,
            "maximum": 600,
            "description": ("재시작 쿨다운(초). 허용 범위 10~600 외 값은 422 (#1456)."),
        },
        "step_timeout_seconds": {
            "type": ["integer", "null"],
            "minimum": 5,
            "maximum": 120,
            "description": ("step 타임아웃(초). 허용 범위 5~120 외 값은 422 (#1456)."),
        },
        "max_signals_per_step": {
            "type": ["integer", "null"],
            "minimum": 1,
            "maximum": 200,
            "description": (
                "step당 최대 signal 수. 허용 범위 1~200 외 값은 422 (#1456)."
            ),
        },
    },
}


@router.put(
    "/{bot_id}",
    response_model=BotDetailResponse,
    responses={
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization header "
                "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
                "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
                "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 bot:admin "
                "scope 보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, type mismatch, "
                "미지정 필드) 또는 budget update 실패. 단, 인증이 실패하면 body "
                "validation은 실행되지 않고 401이 우선 반환된다(#1352)."
            ),
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
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/BotUpdateRequest"},
                },
            },
        },
    },
)
async def update_bot(
    bot_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_bot_admin)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 설정 수정. 인증된 master/human 또는 ``bot:admin`` scope 를 보유한
    agent 만 호출 가능 (#1407 — spec ``bot:admin`` 정합, #1352 master_caller
    에서 마이그레이션). 중지 상태에서만 허용.

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: BotUpdateRequest`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_bot_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``BotUpdateRequest.model_validate`` — ValidationError → 422.
    4. service 호출 (``BotError`` → 409, ``TreasuryError`` → 422).
    """
    from ante.bot.exceptions import BotError
    from ante.treasury.exceptions import TreasuryError

    # 1. raw body 읽기 + JSON 파싱.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422, detail="요청 body의 JSON 파싱에 실패했습니다."
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422, detail="요청 body는 JSON object여야 합니다."
        )

    # 2. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = BotUpdateRequest.model_validate(payload)
    except ValidationError as e:
        # detail sanitize — POST /api/bots 와 동일 정책 (codex r3 FAIL #1436 +
        # #1650). ``budget`` finite-positive 필드에 NaN/Inf 가 들어오면
        # ``input`` 에 non-finite ``float`` 가 담겨
        # ``JSONResponse(allow_nan=False)`` 가 직렬화에 실패해 422 대신 500 이
        # 반환될 수 있다 (#1435 BotUpdateRequest finite invariant). 공용
        # chokepoint 가 input/ctx 제거 + extra_forbidden loc 말단 정규화한다.
        raise HTTPException(
            status_code=422,
            detail=sanitize_validation_errors(e),
        ) from None

    # 3. 봇 존재 확인.
    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"bot": bot.get_info()}

    # 4. strategy_name → strategy_id 변환.
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
            member_id=caller_id,
            action="bot.update",
            resource=f"bot:{bot_id}",
            detail=f"fields={list(updates.keys())}",
            ip=request.client.host if request.client else "",
        )

    return {"bot": bot.get_info()}


def _validate_iso_date_param(
    value: str | None,
    field: str,
    *,
    end_of_day: bool = False,
) -> datetime | None:
    """``value``가 ISO 8601 date 또는 datetime인지 검증하고 UTC-aware
    ``datetime``으로 정규화.

    bot logs 페이지네이션(#1437 r1)은 ``EventHistoryStore``의 SQL
    ``timestamp >= ? AND timestamp <= ?`` 텍스트 비교로 동작한다. 저장 측은
    :class:`Event.timestamp` (``datetime.now(UTC)`` — tz-aware UTC) 의
    ``isoformat()`` 결과를 그대로 저장하므로 storage 문자열은
    ``"2026-05-13T12:00:00+00:00"`` 같이 ``+00:00`` suffix를 가진다.
    ``EventHistoryStore.query``는 SQL 파라미터로 ``since.isoformat()`` /
    ``until.isoformat()``을 사용하므로, 입력 datetime을 UTC-aware로 유지하면
    양쪽 모두 ``+00:00`` suffix가 붙어 ASCII 텍스트 비교가 실제 UTC 시간
    관계와 일치한다 (suffix 정합).

    Codex P2 (#1437 r1):
        r0 구현은 입력 문자열을 그대로 보존(``2026-01-01T09:00:00+09:00`` →
        ``"2026-01-01T09:00:00+09:00"``)한 채 in-memory ``timestamp >= ?``
        문자열 비교에 사용했다. 저장된 timestamp는
        ``"2026-01-01T00:30:00+00:00"`` 같은 ISO 문자열이므로, ``+09:00``
        offset이 그대로 SQL 텍스트 비교에 들어가면 ASCII ``+`` (0x2B) < digit
        (0x30..0x39) 규칙과 zone offset이 섞여 실제 UTC 시간 관계와 어긋난다.
        본 헬퍼는 입력을 UTC(``+00:00``)로 환산해 storage suffix와 일치시킨다.

    허용 형식:
        - ``YYYY-MM-DD`` (date-only) — ``end_of_day=True``면
          ``YYYY-MM-DDT23:59:59+00:00``로 확장, 그 외엔
          ``YYYY-MM-DDT00:00:00+00:00``.
        - ``YYYY-MM-DDTHH:MM:SS[.ffffff][Z]`` / ``+HH:MM`` offset — UTC로
          환산.
        - timezone 없는 naive datetime — UTC로 가정.

    파싱 실패 시 ``HTTPException(422)``로 거부한다 (#1414 audit 패턴 답습).

    Args:
        value: 입력 ISO 문자열 또는 ``None``.
        field: 에러 메시지용 필드명 (``start_date`` / ``end_date``).
        end_of_day: ``True``면 date-only 입력을 ``T23:59:59``로 확장 (inclusive
            upper bound 의미 보존).

    Returns:
        UTC tz-aware ``datetime`` 또는 ``None``.
    """
    if value is None:
        return None
    # ISO date 시도 — Python 3.13은 ``20260510``, ``2026-W19-1`` 같은 비표준
    # 포맷도 수락하므로, ``.isoformat()``로 항상 ``YYYY-MM-DD`` 표준 형식으로
    # 정규화한 뒤 UTC tz-aware datetime으로 확장.
    try:
        d = date.fromisoformat(value)
    except ValueError:
        d = None
    if d is not None:
        if end_of_day:
            # microseconds=999_999까지 확장 — storage timestamp는
            # ``datetime.now(UTC)``로 microseconds까지 가질 수 있다. ASCII
            # 텍스트 비교에서 ``T23:59:59`` < ``T23:59:59.xxxxxx`` < ``T23:59:59+00:00``
            # (``.`` < ``+``) 이므로, ``T23:59:59+00:00``로만 확장하면
            # microseconds 있는 storage row가 inclusive upper bound에서
            # 누락된다. ``T23:59:59.999999`` (microseconds 최대)로 확장해
            # 같은 날짜 모든 microseconds row를 포함시킨다.
            return datetime(d.year, d.month, d.day, 23, 59, 59, 999_999, tzinfo=UTC)
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=UTC)
    # ISO datetime 시도 (Z/offset 허용) — UTC tz-aware로 정규화.
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is not None:
        if dt.tzinfo is None:
            # tz 없는 naive 입력은 UTC로 간주(저장 측 가정 일치).
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    raise HTTPException(
        status_code=422,
        detail=(
            f"Invalid ISO 8601 date for {field}: {value!r}. "
            "허용 형식: ``YYYY-MM-DD`` 또는 ``YYYY-MM-DDTHH:MM:SS[Z]``."
        ),
    )


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
        422: {
            "description": (
                "Invalid date filter (ISO 8601 required). ``start_date``/"
                "``end_date``는 ISO 8601 date(``YYYY-MM-DD``) 또는 "
                "datetime(``YYYY-MM-DDTHH:MM:SS[Z]``)만 허용한다. UTC 정규화 "
                "후 ``start_date > end_date`` (inverted range)도 422로 거부한다 "
                "(#1595)."
            ),
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
    _caller_id: Annotated[str, Depends(require_bot_read)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    event_history_store: Annotated[
        Any | None, Depends(get_event_history_store_optional)
    ],
    eventbus: Annotated[Any | None, Depends(get_eventbus_optional)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    start_date: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 date (``YYYY-MM-DD``) 또는 datetime "
                "(``YYYY-MM-DDTHH:MM:SS[Z]``). inclusive lower bound."
            ),
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 date (``YYYY-MM-DD``) 또는 datetime "
                "(``YYYY-MM-DDTHH:MM:SS[Z]``). inclusive upper bound. "
                "date-only는 ``T23:59:59``로 확장된다."
            ),
        ),
    ] = None,
) -> dict:
    """봇 실행 로그 조회. 인증된 master/human 또는 ``bot:read`` scope 를 보유한
    agent 만 호출 가능 (#1407).

    BotStepCompletedEvent 이력을 반환한다.
    event_history_store(SQLite)가 있으면 영속 로그를 조회하고,
    없으면 EventBus 인메모리 히스토리에서 조회한다.

    응답 형식 (#1437): ``{"bot_id", "logs": [...], "total"}``.
    - ``total``은 bot_id + date range 필터 적용 후의 총 개수 (페이지네이션 전).
    - ``logs``는 ``offset..offset+limit`` 범위의 페이지 데이터.

    Query 파라미터 (#1437):
        - ``limit``: 페이지 크기 (기본 50, 1..100).
        - ``offset``: 페이지 시작 인덱스 (기본 0, ge=0).
        - ``start_date``/``end_date``: ISO 8601 date 또는 datetime. 핸들러는
          입력을 UTC-naive ``datetime``으로 정규화한 뒤 ``EventHistoryStore``
          SQL filter(``timestamp >= ? AND timestamp <= ?``)에 전달한다.

    Codex P2 (#1437 fix loop r2):
        r1 구현은 두 가지 silent failure가 남아있었다.

        (1) ``EventHistoryStore.query`` 시그니처 — r1은 ``until``을 ``limit``
            앞 위치 인자로 추가해 기존 caller ``store.query(type, since, 50)``
            의 세 번째 위치 인자 ``50``이 ``limit`` 대신 ``until``로
            잘못 바인딩되는 위험이 있었다. r2는 ``until``/``offset``/
            ``payload_filter``를 keyword-only로 옮겨 위치 인자 호환성을
            복원한다.

        (2) hard cap ``_BOT_LOGS_FETCH_HARD_CAP=10000`` — r1은 ``bot_id`` 가
            payload JSON 안이라 SQL 직접 필터가 어렵다는 이유로 매칭 가능
            범위(event_type + since/until)를 한번에 10000건 fetch한 뒤
            in-memory ``bot_id`` 필터를 적용했다. 다른 봇의 로그가 cap을
            먼저 채우면 특정 봇의 로그가 결과에서 누락될 수 있다(여러 봇이
            병렬로 step을 찍는 환경에서 silent under-count). r2는
            ``EventHistoryStore``에 SQL JSON1 ``payload_filter``를 추가해
            ``bot_id``를 SQL 단계에서 필터링한다 — cap이 필요 없고
            ``total``/``logs``가 cap에 무관하게 정확하다.

        (3) ``start_date``/``end_date`` 의 timezone 정합 (r1에서 해결, r2에서
            그대로 유지): ``_validate_iso_date_param``으로 입력을 UTC tz-aware
            ``datetime``으로 정규화한 뒤 ``EventHistoryStore``의 SQL 텍스트
            비교에 그대로 사용한다. event timestamp는 dataclass field default
            ``datetime.now(UTC)``로 tz-aware UTC이며, ``isoformat()`` 결과의
            ``+00:00`` suffix가 양쪽에 일관되게 붙어 ASCII 비교가 실제 UTC
            시간 관계와 일치한다.
    """
    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    # ISO 8601 검증 + UTC tz-aware 정규화 (timezone 정렬 일관화).
    # end_date는 ``end_of_day=True``로 date-only를 ``T23:59:59.999999``로 확장.
    start_validated = _validate_iso_date_param(start_date, "start_date")
    end_validated = _validate_iso_date_param(end_date, "end_date", end_of_day=True)
    # 둘 다 UTC-aware datetime으로 정규화된 뒤 비교 → cross-offset 입력도
    # aware/naive TypeError 없이 실제 UTC 순서로 inverted range만 422 거부.
    # end_date는 ``end_of_day=True``로 ``T23:59:59``라 동일 날짜는 통과 (#1595).
    reject_inverted_date_range(start_validated, end_validated)

    if event_history_store is not None:
        # r2: ``bot_id``를 SQL JSON1 ``payload_filter``로 끌어올려 SQL 단계
        # 필터링. ``total``은 ``count(...)``가 페이지네이션과 무관한 정확
        # 매칭 row 수를 반환. hard cap 불필요.
        payload_filter = {"bot_id": bot_id}
        rows = await event_history_store.query(
            event_type="BotStepCompletedEvent",
            since=start_validated,
            limit=limit,
            until=end_validated,
            offset=offset,
            payload_filter=payload_filter,
        )
        total = await event_history_store.count(
            event_type="BotStepCompletedEvent",
            since=start_validated,
            until=end_validated,
            payload_filter=payload_filter,
        )
        logs = [
            {
                "event_id": row.get("event_id", ""),
                "timestamp": row.get("timestamp", ""),
                "result": row.get("payload", {}).get("result", ""),
                "message": row.get("payload", {}).get("message", ""),
            }
            for row in rows
        ]
        return {"bot_id": bot_id, "logs": logs, "total": total}

    if eventbus is not None:
        from ante.eventbus.events import BotStepCompletedEvent

        # in-memory ring buffer ``get_history``는 ``since``/``until``/
        # ``offset``/``payload_filter`` 시그니처가 없으므로(Non-Goal — bus
        # interface 변경은 본 패치 범위 외) 핸들러에서 ``bot_id``/날짜/
        # 페이지 필터를 in-memory로 적용한다.
        #
        # ``limit``은 ring buffer 전체 사이즈(``EventBus._history_size``)로
        # 잡아 ring buffer를 통째로 가져온다. 작은 cap(예: 10000)을 쓰면
        # history_size가 더 큰 환경에서 다른 봇 로그가 cap을 채워 특정
        # 봇 로그가 누락되는 silent failure가 발생한다(Codex P3 r2).
        # ring buffer 자체가 ``_history_size``로 capped이므로 추가 cap은
        # 불필요하다.
        history_cap = getattr(eventbus, "_history_size", 1000)
        history = eventbus.get_history(
            event_type=BotStepCompletedEvent,
            limit=history_cap,
        )
        filtered: list[dict] = []
        for evt in history:
            if evt.bot_id != bot_id:
                continue
            evt_ts = evt.timestamp
            # event.timestamp는 ``datetime.now(UTC)`` (tz-aware UTC) default.
            # start_validated/end_validated가 UTC tz-aware이므로 tz 정합 비교.
            # 혹시 외부에서 naive datetime을 넣은 경우 UTC로 간주.
            if evt_ts.tzinfo is None:
                evt_ts = evt_ts.replace(tzinfo=UTC)
            else:
                evt_ts = evt_ts.astimezone(UTC)
            if start_validated is not None and evt_ts < start_validated:
                continue
            if end_validated is not None and evt_ts > end_validated:
                continue
            filtered.append(
                {
                    "event_id": str(evt.event_id),
                    "timestamp": evt.timestamp.isoformat(),
                    "result": evt.result,
                    "message": evt.message,
                }
            )

        total = len(filtered)
        paginated = filtered[offset : offset + limit]
        return {"bot_id": bot_id, "logs": paginated, "total": total}

    return {"bot_id": bot_id, "logs": [], "total": 0}
