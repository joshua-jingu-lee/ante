"""Web API 공통 의존성 함수.

모든 라우트 핸들러는 getattr(request.app.state, ...) 대신
이 모듈의 의존성 함수를 Annotated[Type, Depends(...)] 형태로 사용한다.

필수 의존성: 서비스가 없으면 HTTPException 503을 발생시킨다.
선택적 의존성: 서비스가 없으면 None을 반환한다.
"""

from __future__ import annotations

import logging
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

_MEMBER_INACTIVE_DETAIL = "멤버가 비활성 상태입니다."


async def require_master_caller(
    request: Request,
    member_service: Annotated[Any | None, Depends(get_member_service_optional)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
) -> str:
    """Bearer 토큰 또는 ``ante_session`` 쿠키로 caller를 결정하고 master 권한을
    강제하는 FastAPI dependency.

    이슈 #1352: oracle A7 시그니처에서 발견된 5개 mutation route(account
    update/suspend/activate, bot update, treasury set_balance)는 인증 없이
    상태 변경을 허용하고 있었다. 이 dependency는 #1351 ``_resolve_caller_or_401``
    패턴을 web layer 공통 가드로 끌어올리고, 추가로 caller가 ``MASTER`` role을
    가지는지 검증한다.

    절차:

    1. ``TokenAuthMiddleware``가 채운 ``request.state.member_id``를 우선 사용
       (Bearer 토큰 경로).
    2. 비어 있으면 ``ante_session`` 쿠키 fallback. 단, ``session_service is
       None`` 배포 분기에서는 fallback을 건너뛰고 caller 빈 상태를 유지 → 401.
       ``session_service.validate`` 자체가 raise하면 401로 흡수한다.
    3. caller가 빈 문자열이면 ``HTTPException(401)``을 raise.
    4. ``member_service.get(caller)``로 멤버를 조회. 멤버가 None이거나
       role이 ``MemberRole.MASTER``가 아니면 ``HTTPException(403)``.
    5. 세션 쿠키 fallback에서 caller가 결정된 경우 ``request.state.member_id``
       를 갱신해 ``AuditMiddleware``의 자동 감사 로그 주체와 일관성 유지.

    Returns:
        caller_id (str): 인증/권한 검증을 통과한 master member_id.

    Raises:
        HTTPException(401): 인증 누락/실패.
        HTTPException(403): 인증은 통과했으나 master가 아님.
    """
    from ante.member.models import MemberRole

    caller = getattr(request.state, "member_id", "") or ""

    # Bearer 인증이 caller를 결정하지 못했고 session_service가 사용 가능하면
    # ante_session 쿠키 fallback (#1351 SSOT 패턴).
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                resolved = session.get("member_id", "") or ""
                if resolved:
                    caller = resolved
                    # AuditMiddleware의 자동 감사 로그 주체 일관성을 위해
                    # request.state.member_id에도 반영한다.
                    request.state.member_id = caller

    if not caller:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    # ``member_service`` 미주입 분기는 본 dependency가 자체적으로 401로
    # 떨어뜨려 cold-path invariant I1(``account_service`` 미주입에서도 409
    # 회복)을 깨지 않는다. 정상 배포에서는 항상 주입돼 있다.
    if member_service is None:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    role = getattr(member, "role", None) if member is not None else None
    role_value = getattr(role, "value", role)
    if member is None or role_value != MemberRole.MASTER.value:
        raise HTTPException(status_code=403, detail=_MASTER_PERMISSION_DENIED_DETAIL)

    return caller


async def require_audit_read(
    request: Request,
    member_service: Annotated[Any | None, Depends(get_member_service_optional)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
) -> str:
    """Bearer 토큰 또는 ``ante_session`` 쿠키로 caller를 결정하고
    audit 도메인 read 권한을 강제하는 FastAPI dependency.

    배경 (Codex P2 #1359 fix loop 3차):
        spec ``docs/specs/member/02-design-decisions.md:210-221`` 의
        ``require_scope`` predicate는 ``member.type == "human"`` 이면 scope 검증을
        무조건 통과시킨다. scope는 오직 agent 멤버를 제한하기 위한 장치이므로,
        human admin/default 멤버도 audit 로그를 읽을 수 있어야 한다.
        2차 패치는 master role 또는 ``audit:read`` scope만 허용해 human admin/
        default 사용자를 403으로 차단하는 회귀가 있었다. 본 패치는 spec
        predicate를 그대로 반영해 다음 OR 분기로 통과시킨다:

    - caller_member.role == ``MemberRole.MASTER`` → 통과
    - caller_member.type == ``MemberType.HUMAN`` → 통과 (scope 무관)
    - ``"audit:read"`` ∈ caller_member.scopes → 통과 (agent의 정상 경로)
    - 그 외 (agent without scope) → ``HTTPException(403)``

    배경 (Codex P2 #1359 fix loop 4차):
        ``TokenAuthMiddleware``는 토큰 인증 시점에 비활성 멤버
        (``status != ACTIVE``)를 거부하지만, ``ante_session`` 쿠키 fallback에서는
        ``SessionService.validate``가 세션 만료만 검사하므로 suspended/revoked
        상태로 전환된 멤버가 기존 세션을 그대로 사용해 통과할 수 있었다.
        본 패치는 권한 분기 직전에 ``MemberStatus.ACTIVE`` 검사를 추가해 두
        인증 경로 모두에서 비활성 멤버를 차단한다.

    인증 절차는 ``require_master_caller``와 동일하다 (Bearer 우선,
    ``session_service`` 가용 시 ``ante_session`` 쿠키 fallback,
    ``session_service`` 미주입/예외/멤버 미존재는 모두 401/403으로 흡수).

    Returns:
        caller_id (str): 인증/권한 검증을 통과한 member_id.

    Raises:
        HTTPException(401): 인증 누락/실패.
        HTTPException(403): 인증은 통과했으나 audit 도메인 read 권한 없음
            또는 멤버 비활성 상태.
    """
    from ante.member.models import MemberRole, MemberStatus, MemberType

    caller = getattr(request.state, "member_id", "") or ""

    # Bearer 인증이 caller를 결정하지 못했고 session_service가 사용 가능하면
    # ante_session 쿠키 fallback (#1351 SSOT 패턴, require_master_caller와 동일).
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                resolved = session.get("member_id", "") or ""
                if resolved:
                    caller = resolved
                    request.state.member_id = caller

    if not caller:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    if member_service is None:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    if member is None:
        raise HTTPException(
            status_code=403, detail=_AUDIT_READ_PERMISSION_DENIED_DETAIL
        )

    # 비활성 멤버 차단 (Codex P2 #1359 fix loop 4차).
    # ``TokenAuthMiddleware``는 토큰 인증 시 비활성을 거부하지만 세션 쿠키
    # fallback에서는 ``SessionService.validate``가 만료만 보므로, suspended/
    # revoked 상태로 전환된 멤버가 통과할 수 있다. 권한 분기 직전에 명시적으로
    # 차단해 두 경로 모두에서 일관된 invariant를 유지한다.
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
    has_audit_read = "audit:read" in scopes

    if not is_master and not is_human and not has_audit_read:
        raise HTTPException(
            status_code=403, detail=_AUDIT_READ_PERMISSION_DENIED_DETAIL
        )

    return caller


async def require_config_write(
    request: Request,
    member_service: Annotated[Any | None, Depends(get_member_service_optional)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
) -> str:
    """Bearer 토큰 또는 ``ante_session`` 쿠키로 caller를 결정하고 dynamic
    config write 권한을 강제하는 FastAPI dependency (#1373).

    배경:
        oracle A7 finding (#1373): ``PUT /api/config/{key}`` 가 인증 없이 익명
        호출을 받아 ``system.log_level`` 같은 동적 설정을 변경할 수 있었다.
        spec ``docs/specs/member/02-design-decisions.md:210-221`` 의
        ``require_scope`` predicate 와 동일한 OR 분기를 적용해 SSOT 와 정합한다:

    - caller_member.role == ``MemberRole.MASTER`` → 통과
    - caller_member.type == ``MemberType.HUMAN`` → 통과 (scope 무관, spec
      predicate 가 ``human`` 멤버는 scope 검증을 무조건 통과시킨다)
    - ``"config:write"`` ∈ caller_member.scopes → 통과 (agent의 정상 경로,
      CLI ``src/ante/cli/commands/config.py`` 가 사용 중인 scope 와 동일)
    - 그 외 (agent without scope) → ``HTTPException(403)``

    인증 절차는 ``require_master_caller`` / ``require_audit_read`` 와 동일하다
    (Bearer 우선, ``session_service`` 가용 시 ``ante_session`` 쿠키 fallback,
    ``session_service`` 미주입/예외/멤버 미존재는 모두 401/403으로 흡수).
    비활성 멤버(``MemberStatus.ACTIVE`` 미상태)는 권한 분기 직전에 403으로
    차단해 ``TokenAuthMiddleware`` 가 거부하지 못한 세션 쿠키 fallback 경로의
    회귀를 잠근다(``require_audit_read`` 4차 fix 패턴 답습).

    Returns:
        caller_id (str): 인증/권한 검증을 통과한 member_id.

    Raises:
        HTTPException(401): 인증 누락/실패.
        HTTPException(403): 인증은 통과했으나 config write 권한 없음 또는
            멤버 비활성 상태.
    """
    from ante.member.models import MemberRole, MemberStatus, MemberType

    caller = getattr(request.state, "member_id", "") or ""

    # Bearer 인증이 caller를 결정하지 못했고 session_service가 사용 가능하면
    # ante_session 쿠키 fallback (#1351 SSOT 패턴, require_master_caller /
    # require_audit_read 와 동일).
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                resolved = session.get("member_id", "") or ""
                if resolved:
                    caller = resolved
                    request.state.member_id = caller

    if not caller:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    if member_service is None:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    if member is None:
        raise HTTPException(
            status_code=403, detail=_CONFIG_WRITE_PERMISSION_DENIED_DETAIL
        )

    # 비활성 멤버 차단 (require_audit_read #1359 fix loop 4차 패턴 답습).
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
    has_config_write = "config:write" in scopes

    if not is_master and not is_human and not has_config_write:
        raise HTTPException(
            status_code=403, detail=_CONFIG_WRITE_PERMISSION_DENIED_DETAIL
        )

    return caller


async def require_report_write(
    request: Request,
    member_service: Annotated[Any | None, Depends(get_member_service_optional)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
) -> str:
    """Bearer 토큰 또는 ``ante_session`` 쿠키로 caller를 결정하고 strategy
    report 제출 권한을 강제하는 FastAPI dependency (#1374).

    배경:
        oracle A7 finding (#1374): ``POST /api/reports`` 가 인증 없이 익명
        호출을 받아 가짜 strategy review artifact 를 큐에 밀어 넣을 수 있었다.
        spec ``docs/specs/member/02-design-decisions.md:210-227`` 의
        ``require_scope`` predicate 와 동일한 OR 분기를 적용해 SSOT 와 정합한다.
        spec 은 ``report:write`` 를 전략 리서치 agent 의 정상 scope 로 명시하고
        있으므로 이 dependency 는 master / human 외에도 해당 scope 를 보유한
        agent 에게 정상 경로를 열어둔다.

    - caller_member.role == ``MemberRole.MASTER`` → 통과
    - caller_member.type == ``MemberType.HUMAN`` → 통과 (scope 무관, spec
      predicate 가 ``human`` 멤버는 scope 검증을 무조건 통과시킨다)
    - ``"report:write"`` ∈ caller_member.scopes → 통과 (전략 리서치 agent 의
      정상 경로)
    - 그 외 (agent without scope) → ``HTTPException(403)``

    인증 절차는 ``require_master_caller`` / ``require_audit_read`` /
    ``require_config_write`` 와 동일하다 (Bearer 우선, ``session_service``
    가용 시 ``ante_session`` 쿠키 fallback, ``session_service`` 미주입/예외/
    멤버 미존재는 모두 401/403으로 흡수). 비활성 멤버
    (``MemberStatus.ACTIVE`` 미상태)는 권한 분기 직전에 403으로 차단해
    ``TokenAuthMiddleware`` 가 거부하지 못한 세션 쿠키 fallback 경로의
    회귀를 잠근다(``require_audit_read`` 4차 fix 패턴 답습).

    Returns:
        caller_id (str): 인증/권한 검증을 통과한 member_id.

    Raises:
        HTTPException(401): 인증 누락/실패.
        HTTPException(403): 인증은 통과했으나 report write 권한 없음 또는
            멤버 비활성 상태.
    """
    from ante.member.models import MemberRole, MemberStatus, MemberType

    caller = getattr(request.state, "member_id", "") or ""

    # Bearer 인증이 caller를 결정하지 못했고 session_service가 사용 가능하면
    # ante_session 쿠키 fallback (#1351 SSOT 패턴, require_master_caller /
    # require_audit_read / require_config_write 와 동일).
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                resolved = session.get("member_id", "") or ""
                if resolved:
                    caller = resolved
                    request.state.member_id = caller

    if not caller:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    if member_service is None:
        raise HTTPException(status_code=401, detail=_MASTER_AUTH_REQUIRED_DETAIL)

    member = None
    try:
        member = await member_service.get(caller)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", caller)

    if member is None:
        raise HTTPException(
            status_code=403, detail=_REPORT_WRITE_PERMISSION_DENIED_DETAIL
        )

    # 비활성 멤버 차단 (require_audit_read #1359 fix loop 4차 패턴 답습).
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
    has_report_write = "report:write" in scopes

    if not is_master and not is_human and not has_report_write:
        raise HTTPException(
            status_code=403, detail=_REPORT_WRITE_PERMISSION_DENIED_DETAIL
        )

    return caller
