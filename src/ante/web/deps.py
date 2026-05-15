"""Web API 공통 의존성 함수.

모든 라우트 핸들러는 getattr(request.app.state, ...) 대신
이 모듈의 의존성 함수를 Annotated[Type, Depends(...)] 형태로 사용한다.

필수 의존성: 서비스가 없으면 HTTPException 503을 발생시킨다.
선택적 의존성: 서비스가 없으면 None을 반환한다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)

# ── 필수 의존성 ─────────────────────────────────────────


def get_approval_service(request: Request) -> Any:
    """결재 서비스 (필수)."""
    svc = getattr(request.app.state, "approval_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Approval service not available")
    return svc


def get_audit_logger(request: Request) -> Any:
    """감사 로거 (필수)."""
    svc = getattr(request.app.state, "audit_logger", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Audit logger not available")
    return svc


def get_bot_manager(request: Request) -> Any:
    """봇 매니저 (필수)."""
    svc = getattr(request.app.state, "bot_manager", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Bot manager not available")
    return svc


def get_strategy_registry(request: Request) -> Any:
    """전략 레지스트리 (필수)."""
    svc = getattr(request.app.state, "strategy_registry", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")
    return svc


def get_treasury(request: Request) -> Any:
    """자금 관리 (필수).

    app.state.treasury가 없으면 treasury_manager에서
    첫 번째 Treasury 인스턴스를 fallback으로 반환한다.
    """
    svc = getattr(request.app.state, "treasury", None)
    if svc is not None:
        return svc

    # fallback: treasury_manager에서 첫 번째 Treasury 반환
    manager = getattr(request.app.state, "treasury_manager", None)
    if manager is not None:
        treasuries = manager.list_all()
        if treasuries:
            return treasuries[0]

    raise HTTPException(status_code=503, detail="Treasury not available")


def get_trade_service(request: Request) -> Any:
    """거래 서비스 (필수)."""
    svc = getattr(request.app.state, "trade_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trade service not available")
    return svc


def get_report_store(request: Request) -> Any:
    """리포트 저장소 (필수)."""
    svc = getattr(request.app.state, "report_store", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Report store not available")
    return svc


def get_dynamic_config(request: Request) -> Any:
    """동적 설정 서비스 (필수)."""
    svc = getattr(request.app.state, "dynamic_config", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Config service not available")
    return svc


def get_account_service(request: Request) -> Any:
    """계좌 서비스 (필수)."""
    svc = getattr(request.app.state, "account_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Account service not available")
    return svc


def get_treasury_manager(request: Request) -> Any:
    """Treasury 매니저 (필수)."""
    svc = getattr(request.app.state, "treasury_manager", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Treasury manager not available")
    return svc


def get_notification_service(request: Request) -> Any:
    """알림 서비스 (필수)."""
    svc = getattr(request.app.state, "notification_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="Notification service not available"
        )
    return svc


def get_member_service(request: Request) -> Any:
    """멤버 서비스 (필수)."""
    svc = getattr(request.app.state, "member_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Member service not available")
    return svc


def get_member_service_optional(request: Request) -> Any | None:
    """멤버 서비스 (선택적). 없으면 None.

    ``require_master_caller``는 ``member_service`` 미주입 환경에서도 cold-path
    invariant I1(예: ``test_update_blocks_when_structural_without_account_service``)
    을 깨지 않고 401로 떨어뜨리기 위해 optional 버전을 사용한다.
    """
    return getattr(request.app.state, "member_service", None)


def get_session_service(request: Request) -> Any:
    """세션 서비스 (필수)."""
    svc = getattr(request.app.state, "session_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Session service not available")
    return svc


def get_db(request: Request) -> Any:
    """데이터베이스 (필수)."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return db


# ── 선택적 의존성 ───────────────────────────────────────


def get_db_optional(request: Request) -> Any | None:
    """데이터베이스 (선택적). 없으면 None."""
    return getattr(request.app.state, "db", None)


def get_data_store(request: Request) -> Any | None:
    """데이터 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "data_store", None)


def get_bot_manager_optional(request: Request) -> Any | None:
    """봇 매니저 (선택적). 없으면 None."""
    return getattr(request.app.state, "bot_manager", None)


def get_strategy_registry_optional(request: Request) -> Any | None:
    """전략 레지스트리 (선택적). 없으면 None."""
    return getattr(request.app.state, "strategy_registry", None)


def get_treasury_optional(request: Request) -> Any | None:
    """자금 관리 (선택적). 없으면 None."""
    return getattr(request.app.state, "treasury", None)


def get_trade_service_optional(request: Request) -> Any | None:
    """거래 서비스 (선택적). 없으면 None."""
    return getattr(request.app.state, "trade_service", None)


def get_report_store_optional(request: Request) -> Any | None:
    """리포트 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "report_store", None)


def get_account_service_optional(request: Request) -> Any | None:
    """계좌 서비스 (선택적). 없으면 None."""
    return getattr(request.app.state, "account_service", None)


def get_treasury_manager_optional(request: Request) -> Any | None:
    """Treasury 매니저 (선택적). 없으면 None."""
    return getattr(request.app.state, "treasury_manager", None)


def get_config(request: Request) -> Any | None:
    """앱 설정 (선택적). 없으면 None."""
    return getattr(request.app.state, "config", None)


def get_broker(request: Request) -> Any | None:
    """브로커 (선택적). 없으면 None."""
    return getattr(request.app.state, "broker", None)


def get_audit_logger_optional(request: Request) -> Any | None:
    """감사 로거 (선택적). 없으면 None."""
    return getattr(request.app.state, "audit_logger", None)


def get_session_service_optional(request: Request) -> Any | None:
    """세션 서비스 (선택적). 없으면 None.

    ``POST /api/members`` 같은 라우트는 Bearer 토큰 인증을 1순위로 쓰고,
    세션 쿠키 인증은 fallback이므로 session_service가 부재한 환경에서도
    503으로 실패해서는 안 된다(#1339 P1). 일반 인증 라우트(``/api/auth/*``)
    는 그대로 ``get_session_service`` (필수)를 사용한다.
    """
    return getattr(request.app.state, "session_service", None)


def get_event_history_store(request: Request) -> Any:
    """이벤트 히스토리 저장소 (필수)."""
    svc = getattr(request.app.state, "event_history_store", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Event history store not available")
    return svc


def get_event_history_store_optional(request: Request) -> Any | None:
    """이벤트 히스토리 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "event_history_store", None)


def get_eventbus_optional(request: Request) -> Any | None:
    """EventBus (선택적). 없으면 None."""
    return getattr(request.app.state, "eventbus", None)


# ── Master 인증 가드 (#1352) ───────────────────────────────────────


_MASTER_AUTH_REQUIRED_DETAIL = (
    "인증이 필요합니다. Authorization: Bearer <token> 헤더 또는 "
    "유효한 ante_session 쿠키가 필요합니다."
)

_MASTER_PERMISSION_DENIED_DETAIL = "이 작업은 master 권한이 필요합니다."

_AUDIT_READ_PERMISSION_DENIED_DETAIL = (
    "이 작업은 human 멤버 또는 audit:read scope를 보유한 agent만 수행할 수 있습니다."
)

_CONFIG_WRITE_PERMISSION_DENIED_DETAIL = (
    "이 작업은 master, human 멤버 또는 config:write scope를 보유한 agent만 "
    "수행할 수 있습니다."
)

_REPORT_WRITE_PERMISSION_DENIED_DETAIL = (
    "이 작업은 master, human 멤버 또는 report:write scope를 보유한 agent만 "
    "수행할 수 있습니다."
)

_STRATEGY_WRITE_PERMISSION_DENIED_DETAIL = (
    "이 작업은 master, human 멤버 또는 strategy:write scope를 보유한 agent만 "
    "수행할 수 있습니다."
)

_MEMBER_INACTIVE_DETAIL = "멤버가 비활성 상태입니다."

# 미들웨어 invariant 위반 시 사용. ``RequireAuthMiddleware`` (#1403) 가 보호
# 라우트에 진입 전에 ``request.state.member_id`` 를 반드시 채우므로, dep 시점에
# caller 가 비어 있다면 client 인증 실패가 아니라 미들웨어 설치 누락/순서 오류
# 같은 서버 내부 invariant 위반이다. 401 (인증 실패) 와 구분되도록 500 응답.
_AUTH_MIDDLEWARE_INVARIANT_DETAIL = (
    "auth middleware did not populate member_id (invariant violation)"
)


async def require_master_caller(
    request: Request,
    member_service: Annotated[Any | None, Depends(get_member_service_optional)],
) -> str:
    """``request.state.member_id`` 가 master 권한을 가지는지 강제하는 FastAPI
    dependency.

    이슈 #1408: 인증 / caller resolution / ACTIVE 1차 검사는 모두 ``RequireAuth
    Middleware`` (#1403) 가 담당한다. 본 dep 은 미들웨어가 채운 ``request.state.
    member_id`` 를 신뢰하고 다음만 수행한다:

    1. ``member_service.get(caller)`` 로 멤버를 조회.
    2. ``MemberStatus.ACTIVE`` re-check (TOCTOU race guard — 미들웨어 통과 후
       권한 분기 전 사이에 ``SUSPENDED`` / ``REVOKED`` 로 전환된 경우 차단).
    3. ``MemberRole.MASTER`` 가 아니면 ``HTTPException(403)``.

    이슈 #1352: oracle A7 시그니처에서 발견된 5개 mutation route(account
    update/suspend/activate, bot update, treasury set_balance) 의 master-only
    가드를 제공한다.

    Returns:
        caller_id (str): 인증/권한 검증을 통과한 master member_id.

    Raises:
        HTTPException(403): 멤버 비활성 / master 아님 / ``member_service`` 에
            caller_id 가 없는 ghost caller 케이스.
        HTTPException(500): 미들웨어 invariant 위반 (``request.state.member_id``
            미설정). 정상 운영에서는 발생하지 않음.
        HTTPException(503): ``member_service`` 미주입 (cold-path).
    """
    from ante.member.models import MemberRole, MemberStatus

    if member_service is None:
        # ``member_service`` 미주입은 cold-path invariant. 미들웨어 통과 시점에
        # 이미 ``member_service.get`` 으로 ACTIVE 검증을 했으므로 정상 배포에서는
        # 도달하지 않는다. 503 으로 서비스 미가용 표현.
        raise HTTPException(status_code=503, detail="Member service not available")

    caller = getattr(request.state, "member_id", "") or ""
    if not caller:
        # 미들웨어 invariant 위반 — client 인증 실패 (401) 가 아님.
        raise HTTPException(status_code=500, detail=_AUTH_MIDDLEWARE_INVARIANT_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    if member is None:
        # ghost caller (미들웨어가 채운 id 가 멤버 서비스에 없음).
        raise HTTPException(status_code=403, detail=_MASTER_PERMISSION_DENIED_DETAIL)

    # ACTIVE re-check (TOCTOU race guard). 미들웨어가 1차 검증 후 권한 분기
    # 전에 ``SUSPENDED`` / ``REVOKED`` 로 전환된 경우 여기서 차단한다.
    status = getattr(member, "status", None)
    status_value = getattr(status, "value", status)
    if status_value != MemberStatus.ACTIVE.value:
        raise HTTPException(status_code=403, detail=_MEMBER_INACTIVE_DETAIL)

    role = getattr(member, "role", None)
    role_value = getattr(role, "value", role)
    if role_value != MemberRole.MASTER.value:
        raise HTTPException(status_code=403, detail=_MASTER_PERMISSION_DENIED_DETAIL)

    return caller


# ── require_scope factory (#1406) ──────────────────────────────────────────
#
# 4개 mutation guard (audit:read / config:write / report:write / strategy:write)
# 는 spec ``docs/specs/member/02-design-decisions.md:210-227`` 의
# ``require_scope`` predicate 를 동일하게 구현하므로 (scope 문자열과 denied
# detail 만 다름), 한 개의 factory 와 helper 로 통합한다. 기존 4개 라우트
# import (``from ante.web.deps import require_audit_read`` 등) 와 외부 응답의
# detail 문자열은 무변경으로 보존한다.
#
# detail 매핑 정책:
#   - 기존 4개 scope: ``_SCOPE_DENIED_DETAIL_MAP`` 의 기존 상수를 byte-exact
#     재사용. ``audit:read`` 는 "human 멤버 또는 audit:read scope" 처럼
#     "master" 단어가 없는 특수 case 라서 mapping 으로만 보존한다.
#   - 신규 scope (e.g. #1407 후속 마이그레이션): ``_default_denied_detail``
#     템플릿(``"master, human 멤버 또는 {scope} scope ..."``)을 사용한다.
_SCOPE_DENIED_DETAIL_MAP: dict[str, str] = {
    "audit:read": _AUDIT_READ_PERMISSION_DENIED_DETAIL,
    "config:write": _CONFIG_WRITE_PERMISSION_DENIED_DETAIL,
    "report:write": _REPORT_WRITE_PERMISSION_DENIED_DETAIL,
    "strategy:write": _STRATEGY_WRITE_PERMISSION_DENIED_DETAIL,
}


def _default_denied_detail(scope: str) -> str:
    """신규 scope 에 대한 기본 denied detail 템플릿.

    spec ``docs/specs/member/02-design-decisions.md`` 의 ``require_scope``
    predicate (master / human / scope ∈ scopes) 와 정합한 사용자 메시지를
    생성한다. ``_SCOPE_DENIED_DETAIL_MAP`` 에 등록되지 않은 새 scope 에 대해
    factory 가 사용한다.
    """
    return (
        f"이 작업은 master, human 멤버 또는 {scope} scope를 보유한 agent만 "
        "수행할 수 있습니다."
    )


async def _resolve_caller_with_scope(
    request: Request,
    member_service: Any | None,
    scope: str,
    denied_detail: str,
) -> str:
    """``request.state.member_id`` 의 scope 권한을 강제하는 공통 helper.

    이슈 #1408: 인증 / caller resolution / ACTIVE 1차 검사는 모두 ``RequireAuth
    Middleware`` (#1403) 가 담당한다. 본 helper 는 미들웨어가 채운
    ``request.state.member_id`` 를 신뢰하고 spec ``docs/specs/member/
    02-design-decisions.md:210-227`` 의 ``require_scope`` predicate 만 수행한다:

    - caller_member.role == ``MemberRole.MASTER`` → 통과
    - caller_member.type == ``MemberType.HUMAN`` → 통과 (scope 무관, spec
      predicate 가 ``human`` 멤버는 scope 검증을 무조건 통과시킨다)
    - ``scope`` ∈ caller_member.scopes → 통과 (agent 정상 경로)
    - 그 외 (agent without scope) → ``HTTPException(403, denied_detail)``

    ACTIVE re-check 는 TOCTOU race guard 로 보존된다 — 미들웨어가 1차 검증한
    뒤 권한 분기 전 사이에 ``SUSPENDED`` / ``REVOKED`` 로 전환된 멤버가 통과
    하지 않도록 (#1359 fix loop 4차 패턴) 다시 한 번 검사한다.

    Returns:
        caller_id (str): 검증을 통과한 member_id.

    Raises:
        HTTPException(403): 멤버 비활성 / scope 권한 없음 / ``member_service``
            에 caller_id 가 없는 ghost caller.
        HTTPException(500): 미들웨어 invariant 위반 (``request.state.member_id``
            미설정).
        HTTPException(503): ``member_service`` 미주입 (cold-path).
    """
    from ante.member.models import MemberRole, MemberStatus, MemberType

    if member_service is None:
        # ``member_service`` 미주입은 cold-path invariant. 정상 배포에서는
        # 도달하지 않는다. 503 으로 서비스 미가용 표현.
        raise HTTPException(status_code=503, detail="Member service not available")

    caller = getattr(request.state, "member_id", "") or ""
    if not caller:
        # 미들웨어 invariant 위반 — client 인증 실패 (401) 가 아님.
        raise HTTPException(status_code=500, detail=_AUTH_MIDDLEWARE_INVARIANT_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    if member is None:
        # ghost caller (미들웨어가 채운 id 가 멤버 서비스에 없음).
        raise HTTPException(status_code=403, detail=denied_detail)

    # ACTIVE re-check (TOCTOU race guard).
    status = getattr(member, "status", None)
    status_value = getattr(status, "value", status)
    if status_value != MemberStatus.ACTIVE.value:
        raise HTTPException(status_code=403, detail=_MEMBER_INACTIVE_DETAIL)

    role = getattr(member, "role", None)
    role_value = getattr(role, "value", role)
    is_master = role_value == MemberRole.MASTER.value

    member_type = getattr(member, "type", None)
    member_type_value = getattr(member_type, "value", member_type)
    is_human = member_type_value == MemberType.HUMAN.value

    scopes = getattr(member, "scopes", None) or []
    has_scope = scope in scopes

    if not is_master and not is_human and not has_scope:
        raise HTTPException(status_code=403, detail=denied_detail)

    return caller


def require_scope(scope: str) -> Callable[..., Awaitable[str]]:
    """주어진 ``scope`` 에 대한 FastAPI dependency 를 생성하는 factory.

    spec ``docs/specs/member/02-design-decisions.md:210-227`` 의
    ``require_scope`` predicate 를 한 곳에 캡슐화한다. 라우트 코드는
    ``Depends(require_audit_read)`` 같은 module-level alias 를 그대로 사용해
    FastAPI Dependant cache identity 를 보존한다 (라우트 안에서 매번
    ``Depends(require_scope("..."))`` 를 호출하면 새 dependency 객체가
    생성되어 cache 가 깨진다).

    detail 문자열은 다음 정책으로 결정한다:

    - ``scope`` 가 ``_SCOPE_DENIED_DETAIL_MAP`` 에 있으면 매핑된 기존 상수를
      재사용 (byte-exact 보존, ``audit:read`` 특수 case 포함).
    - 아니면 ``_default_denied_detail(scope)`` 템플릿을 사용.

    반환된 dependency callable 은:

    - ``__name__ == f"require_scope_{scope.replace(':', '_')}"`` (디버깅용)
    - ``_is_authentication_dependency = True`` marker 부착 (#1405
      ``test_route_auth_coverage`` 가 인식)

    Returns:
        Awaitable FastAPI dependency that returns the caller member_id (str)
        on success.

    Raises (when invoked as a FastAPI dependency):
        HTTPException(403): ``scope`` 권한 없음, 멤버 비활성, ghost caller.
        HTTPException(500): 미들웨어 invariant 위반 (#1408).
        HTTPException(503): ``member_service`` 미주입 (cold-path).

    인증 자체 (401) 는 ``RequireAuthMiddleware`` (#1403) 가 본 dep 진입 전에
    처리한다.
    """
    detail = _SCOPE_DENIED_DETAIL_MAP.get(scope) or _default_denied_detail(scope)

    async def inner_dep(
        request: Request,
        member_service: Annotated[Any | None, Depends(get_member_service_optional)],
    ) -> str:
        return await _resolve_caller_with_scope(request, member_service, scope, detail)

    inner_dep.__name__ = f"require_scope_{scope.replace(':', '_')}"
    # ``test_route_auth_coverage`` 가 본 marker 로 인증 dependency 를 식별한다
    # (#1405). 새 scope alias 를 추가할 때 본 factory 가 자동으로 marker 를
    # 부착해주므로 호출처에서 별도 관리할 필요는 없다.
    inner_dep._is_authentication_dependency = True  # type: ignore[attr-defined]
    return inner_dep


# ── Module-level scope alias (#1406 + #1407) ───────────────────────────────
#
# 라우트 import 호환성과 FastAPI Depends() instance cache 보존을 위해
# 모든 scope dependency 를 module-level alias 로 정의한다. 라우트 안에서
# ``Depends(require_scope("audit:read"))`` 처럼 inline 으로 호출하면 매
# 라우트 정의마다 새 callable 이 생성되어 cache identity 가 깨지므로,
# 신규 scope alias 도 반드시 module-level 에 한 번만 정의해야 한다.
#
# 기존 4개 (#1406) — detail 은 ``_SCOPE_DENIED_DETAIL_MAP`` 매핑으로 byte-exact
# 보존된다.
require_audit_read = require_scope("audit:read")
require_config_write = require_scope("config:write")
require_report_write = require_scope("report:write")
require_strategy_write = require_scope("strategy:write")

# 신규 20개 (#1407) — SSOT ``docs/specs/web-api/11-route-scope-table.md`` 결정
# scope 컬럼에서 byte-exact 추출. detail 은 ``_default_denied_detail`` 템플릿
# ("master, human 멤버 또는 {scope} scope ...") 을 사용한다. 라우트는 본 alias
# 를 import 해 ``Depends(require_X_Y)`` 형태로 부착한다.
require_account_read = require_scope("account:read")
require_account_write = require_scope("account:write")
require_approval_read = require_scope("approval:read")
require_approval_admin = require_scope("approval:admin")
require_bot_read = require_scope("bot:read")
require_bot_admin = require_scope("bot:admin")
require_config_read = require_scope("config:read")
require_data_read = require_scope("data:read")
require_data_write = require_scope("data:write")
require_member_read = require_scope("member:read")
# ``require_member_admin`` 은 #1407 에서 ``require_scope("member:admin")`` 으로
# 도입되었으나, #1511 oracle drift 분석 결과 member admin mutation 은 master-only
# 계약임이 #1542 에서 spec SSOT (``docs/specs/web-api/11-route-scope-table.md``)
# 로 확정되었다. ``MemberService._assert_master`` 가 런타임에서 거부하므로 표면
# 가드만 ``member:admin`` agent 를 허용하는 것은 contract drift 였다.
#
# #1543: 표면 가드도 master-only 로 정렬한다. backward-compat 을 위해 symbol 은
# 보존하되 의미를 ``require_master_caller`` 로 재할당한다 — 외부 import (라우트,
# 테스트) 는 그대로 동작하지만 실제 권한 검증은 master-only 로 강제된다.
# ``member:admin`` scope vocabulary 는 #1542 결정에 따라 reserved 상태로 유지된다
# (``src/ante/member/scopes.py`` SSOT, 제거 금지).
require_member_admin = require_master_caller
require_report_read = require_scope("report:read")
require_rule_read = require_scope("rule:read")
require_rule_admin = require_scope("rule:admin")
require_strategy_read = require_scope("strategy:read")
require_system_read = require_scope("system:read")
require_system_admin = require_scope("system:admin")
require_trade_read = require_scope("trade:read")
require_treasury_read = require_scope("treasury:read")
require_treasury_admin = require_scope("treasury:admin")


# ── 인증 dependency 정적 검증 marker (#1405) ───────────────────────────────
#
# ``tests/unit/test_route_auth_coverage.py`` 는 17개 currently-attached 라우트
# (ATTACHED_ROUTE_ALLOWLIST) 가 본 모듈의 인증 dependency 중 하나에 의해
# 보호되는지 정적으로 회귀 검증한다. 검증 helper ``_has_auth_marker`` 는
# FastAPI Dependant 트리를 walk 하면서 각 dependency callable 의
# ``_is_authentication_dependency`` 속성을 확인한다.
#
# ``require_scope`` factory 가 만든 4개 alias 는 factory 내부에서 marker 를
# 부착하므로 별도 부착이 불필요하다. ``require_master_caller`` 는 factory
# 외 분기이므로 본 위치에서 명시 부착한다.
require_master_caller._is_authentication_dependency = True  # type: ignore[attr-defined]
