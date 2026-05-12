"""감사 로그 API."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ante.web.deps import get_audit_logger, require_audit_read
from ante.web.schemas import AuditLogListResponse

router = APIRouter()


def _normalize_iso_datetime(value: str) -> str:
    """ISO datetime을 ``AuditLogger`` storage format으로 정규화.

    ``AuditLogger.log``는 ``datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")``
    형식(Z 없는 naive UTC)으로 ``created_at``을 저장한다. ``query``/``count``
    는 SQL 텍스트 비교(``created_at >= ?``, ``created_at <= ?``)를 사용하므로,
    입력 str을 **동일한 storage format**으로 맞추지 않으면 inclusive boundary
    가 깨진다.

    Codex P2 (#1414 fix loop r2):
        ``from_date=2026-05-10T00:00:00Z``를 검증만 통과시켜 그대로
        ``AuditLogger.query``에 넘기면 SQL은 ``created_at >=
        '2026-05-10T00:00:00Z'``가 되고, 저장값은 ``'2026-05-10T00:00:00'``
        (Z 없음). ASCII ``Z`` > digit이므로 ``'2026-05-10T00:00:00'`` <
        ``'2026-05-10T00:00:00Z'``로 평가되어, 정확히 같은 시각의 row가
        inclusive lower bound에서 누락되는 silent regression이 발생한다.

    변환 규칙:
        - ``Z`` suffix → 제거(UTC 가정 보존)
        - ``+HH:MM`` / ``-HH:MM`` offset → UTC로 환산 후 ``tzinfo`` 제거
        - timezone 없는 naive datetime → 그대로 반환(UTC 가정)

    Raises:
        ``ValueError``: ISO datetime 파싱 실패 시 (caller가 422로 변환).
    """
    # ``Z`` → ``+00:00``으로 변환해야 ``fromisoformat``이 timezone-aware로 인식.
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        # UTC로 변환 후 timezone-aware → naive로 평탄화(storage format 일치).
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _validate_iso_date(value: str | None, field: str) -> str | None:
    """``value``가 ISO 8601 date(``YYYY-MM-DD``) 또는 datetime인지 검증.

    검증 통과 시:
        - date-only(``YYYY-MM-DD``, 10자리)는 **변환 없이** 그대로 반환한다.
          ``AuditLogger.query/count``는 10자리 ``to_date``를 받으면 SQL에서
          ``T23:59:59``로 자동 확장하여 자정 이후 데이터 누락을 막는다.
        - datetime은 ``_normalize_iso_datetime``으로 storage format
          (``%Y-%m-%dT%H:%M:%S``, naive UTC)으로 정규화하여 반환한다.
          ``Z``/offset suffix를 보존한 채 SQL 텍스트 비교에 넘기면 inclusive
          boundary가 어긋난다(Codex r2 finding 참고).

    파싱 실패 시 422로 거부한다 (FastAPI/Pydantic 422 응답과 동일 형식).

    Codex P2 (#1414 fix loop r1): 1차 구현은 ``Annotated[datetime | None,
    Query(...)]``로 좁혀 422 거부는 통과시켰으나, Pydantic이 date-only
    (``2026-05-10``)를 ``datetime(2026, 5, 10, 0, 0, 0)``으로 자동 변환한 뒤
    ``isoformat()`` → ``"2026-05-10T00:00:00"`` (19자리)로 변환되어
    ``AuditLogger.query``의 ``len(to_date) == 10`` 분기가 작동하지 않게 되었다.
    결과적으로 ``to_date=2026-05-10`` 호출이 자정 이전 데이터만 반환하는
    **silent semantic regression**이 발생했다. 본 헬퍼는 그 회귀를 해소하기
    위해 date-only 입력 str을 보존한다.

    Codex P2 (#1414 fix loop r2): r1 구현은 datetime 입력도 보존했으나,
    ``Z``/offset suffix를 그대로 SQL 텍스트 비교(``created_at >= ?``)에 넘기면
    storage format(Z 없는 naive UTC)과 어긋나 inclusive boundary가 깨졌다.
    datetime 입력은 storage format으로 정규화하여 누락을 막는다.
    """
    if value is None:
        return None
    # 10자리 YYYY-MM-DD 시도 (AuditLogger.query의 자동 확장 경로 보존)
    try:
        date.fromisoformat(value)
        return value
    except ValueError:
        pass
    # ISO datetime 시도 (Z/offset 허용) — storage format으로 정규화
    try:
        return _normalize_iso_datetime(value)
    except ValueError:
        pass
    raise HTTPException(
        status_code=422,
        detail=(
            f"Invalid ISO 8601 date for {field}: {value!r}. "
            "허용 형식: ``YYYY-MM-DD`` 또는 ``YYYY-MM-DDTHH:MM:SS[Z]``."
        ),
    )


@router.get(
    "",
    response_model=AuditLogListResponse,
    responses={
        401: {
            "description": "Authentication required",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": "Master role or audit:read scope required",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Invalid date filter (ISO 8601 required). ``from_date``/"
                "``to_date``는 ISO 8601 date(``YYYY-MM-DD``) 또는 "
                "datetime(``YYYY-MM-DDTHH:MM:SS[Z]``)만 허용한다. 파싱 불가능한"
                "임의 문자열(예: ``not-a-date``)은 핸들러가 422로 거부한다"
                "(#1414). date-only 입력은 ``AuditLogger.query``의 자동 확장"
                "(SQL ``<= 'YYYY-MM-DDT23:59:59'``) 동작을 보존하기 위해 "
                "변환 없이 그대로 전달된다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Audit logger not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_audit_logs(
    caller_id: Annotated[str, Depends(require_audit_read)],
    audit_logger: Annotated[Any, Depends(get_audit_logger)],
    member_id: str | None = None,
    action: str | None = None,
    from_date: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 date (``YYYY-MM-DD``) 또는 datetime "
                "(``YYYY-MM-DDTHH:MM:SS[Z]``). inclusive lower bound."
            ),
        ),
    ] = None,
    to_date: Annotated[
        str | None,
        Query(
            description=(
                "ISO 8601 date (``YYYY-MM-DD``) 또는 datetime "
                "(``YYYY-MM-DDTHH:MM:SS[Z]``). inclusive upper bound. "
                "date-only는 ``AuditLogger`` 내부에서 ``T23:59:59``로 확장된다."
            ),
        ),
    ] = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """감사 로그 조회.

    인증/권한:
        oracle A7 시그니처(#1359)에서 본 라우트는 인증 없이 감사 로그 목록을
        반환하고 있었다. 감사 로그는 운영 행위 추적 정보(member_id, action,
        resource, IP 등)를 담으므로 인증 가드를 적용한다. 인증 누락은 401,
        권한 없음은 403.

        Codex P2 (#1359 fix loop, 2차): 초기 패치는 ``require_master_caller``
        를 그대로 적용해 ``master`` role만 허용했으나,
        ``docs/specs/member/02-design-decisions.md:188-229`` 의 모니터링 agent
        (``audit:read`` scope만 가진 default role)가 차단되는 문제가 있었다.
        spec은 audit 도메인 read 권한을 ``master`` role 또는 ``audit:read``
        scope 중 하나로 정의하므로, ``require_audit_read`` (master OR
        ``audit:read`` ∈ Member.scopes)로 교체해 spec과 일치시켰다.

    Codex P2 (#1359 fix loop): FastAPI는 핸들러 매개변수 선언 순서대로
    dependency를 해결한다. ``audit_logger`` (필수 service, 미주입 시 503)를
    ``require_audit_read`` 보다 먼저 두면, 인증 정보가 없는 호출자에게
    503이 먼저 반환되어 "인증 누락은 401" 계약이 깨진다. 그러므로 인증
    가드(``caller_id``)를 항상 먼저 선언해 401/403이 503보다 우선하도록 한다.

    NOTE: ``limit``은 다른 list endpoint와 일관된 ``le=100``으로 검증한다.
    이전 구현은 ``min(limit, 200)``로 자동 클램프했으나, #1356에서
    pagination contract 일관성을 위해 클램프를 제거하고 Query
    validation으로 대체했다 (101..200 범위 요청은 새로 422). 다른 caller가
    이 범위를 강제하면 별도 endpoint로 분리한다.

    Codex P2 (#1414 fix loop r1): ``from_date``/``to_date``는 ``str | None``
    타입으로 받아 ``_validate_iso_date`` 헬퍼로 ISO 8601 파싱 가능성만 검증
    하고, 원본 str을 그대로 ``AuditLogger.query/count``에 전달한다. 이전
    구현은 ``Annotated[datetime | None, ...]``로 좁혀 Pydantic이 자동 변환
    하도록 했으나, date-only 입력이 ``"2026-05-10T00:00:00"`` (19자리)로
    변환되어 ``AuditLogger`` 내부의 ``len(to_date) == 10`` 자동 확장 분기가
    작동하지 않게 되어 자정 이후 데이터를 누락하는 silent semantic
    regression이 발생했다. 본 구현은 str을 보존해 그 회귀를 해소한다.

    Codex P2 (#1414 fix loop r2): datetime 입력(``2026-05-10T00:00:00Z`` 등)
    을 r1처럼 그대로 보존하면 SQL 텍스트 비교에서 storage format(Z 없는
    naive UTC)과 어긋나 inclusive boundary가 깨진다. ``Z``/offset 입력을
    storage format으로 정규화하도록 헬퍼를 보강했다. date-only는 자동 확장
    경로를 위해 변환 없이 그대로 보존된다.
    """
    # caller_id는 ``require_audit_read``가 ``request.state.member_id``에
    # 이미 반영하고 ``AuditMiddleware``가 자동 감사 로그 주체로 사용한다.
    # 핸들러 자체에서 audit query 필터로는 사용하지 않는다 (caller가 master
    # 또는 audit:read scope를 가진 한 전체 로그 조회 권한을 가지며, 현재는
    # 두 조건 OR 모델이므로 이 정책이 안전하다). 변수 사용 표시를 위한 명시적
    # reference.
    _ = caller_id
    # #1414 r1: ISO 8601 검증 후 원본 str을 그대로 전달.
    from_date_validated = _validate_iso_date(from_date, "from_date")
    to_date_validated = _validate_iso_date(to_date, "to_date")
    logs = await audit_logger.query(
        member_id=member_id,
        action=action,
        from_date=from_date_validated,
        to_date=to_date_validated,
        limit=limit,
        offset=offset,
    )
    total = await audit_logger.count(
        member_id=member_id,
        action=action,
        from_date=from_date_validated,
        to_date=to_date_validated,
    )
    return {"logs": logs, "total": total}
