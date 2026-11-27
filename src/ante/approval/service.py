"""ApprovalService — 결재 요청 관리."""

from __future__ import annotations

import json
import logging
from datetime import UTC
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import uuid4

from ante.account.scoping import require_account_id
from ante.approval.auto_approve import AutoApproveEvaluator
from ante.approval.errors import ApprovalNotFoundError, ApprovalStatusConflictError
from ante.approval.models import (
    APPROVAL_STATUS_TRANSITIONS,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
    ApprovalValidationError,
    ValidationResult,
)
from ante.core import clock

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


_ACCOUNT_SCOPED_APPROVAL_TYPES: frozenset[str] = frozenset(
    {"budget_change", "rule_change", "bot_create"}
)


_VALID_APPROVAL_TYPES: frozenset[str] = frozenset(t.value for t in ApprovalType)


def _extract_account_id(type: str, params: dict[str, Any] | None) -> str | None:
    """account-scoped approval payload 에서 account_id 를 꺼낸다."""
    if params is None:
        return None
    config = params.get("config")
    if isinstance(config, dict):
        candidate = config.get("account_id")
        if candidate is not None:
            return candidate  # type: ignore[no-any-return]
    return params.get("account_id")


def _transition_status(
    request: ApprovalRequest, target: ApprovalStatus, action: str
) -> ApprovalStatus:
    if target not in APPROVAL_STATUS_TRANSITIONS.get(request.status, set()):
        raise ApprovalStatusConflictError(
            request.id,
            current_status=str(request.status),
            requested_action=action,
        )
    request.status = target
    return target


def _require_found(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    if not request:
        msg = f"결재 요청을 찾을 수 없음: {id}"
        raise ValueError(msg)
    return request


def _check_approve(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    request = _require_found(id, request)
    if request.type not in _VALID_APPROVAL_TYPES:
        msg = f"invalid approval type: {request.type!r}"
        raise ValueError(msg)
    approvable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
    if request.status not in approvable:
        raise ApprovalStatusConflictError(
            id,
            current_status=str(request.status),
            requested_action="approve",
        )
    return request


def _check_reject(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    request = _require_found(id, request)
    rejectable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
    if request.status not in rejectable:
        raise ApprovalStatusConflictError(
            id,
            current_status=str(request.status),
            requested_action="reject",
        )
    return request


def _check_reopen(
    id: str, request: ApprovalRequest | None, requester: str
) -> ApprovalRequest:
    request = _require_found(id, request)
    if request.status != ApprovalStatus.REJECTED:
        msg = f"rejected 상태에서만 reopen 가능 (현재: {request.status})"
        raise ValueError(msg)
    if request.requester != requester:
        msg = f"본인 요청만 reopen 가능 (요청자: {request.requester})"
        raise ValueError(msg)
    return request


def _check_cancel(
    id: str, request: ApprovalRequest | None, requester: str
) -> ApprovalRequest:
    request = _require_found(id, request)
    if request.requester != requester:
        msg = f"본인 요청만 철회 가능 (요청자: {request.requester})"
        raise ValueError(msg)
    cancellable = (
        ApprovalStatus.PENDING,
        ApprovalStatus.ON_HOLD,
        ApprovalStatus.EXECUTION_FAILED,
    )
    if request.status not in cancellable:
        msg = (
            "pending/on_hold/execution_failed 상태에서만 철회 가능"
            f" (현재: {request.status})"
        )
        raise ValueError(msg)
    return request


def _check_hold(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    request = _require_found(id, request)
    holdable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
    if request.status not in holdable:
        msg = f"pending/execution_failed 상태에서만 보류 가능 (현재: {request.status})"
        raise ValueError(msg)
    return request


def _check_resume(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    request = _require_found(id, request)
    if request.status != ApprovalStatus.ON_HOLD:
        msg = f"on_hold 상태에서만 재개 가능 (현재: {request.status})"
        raise ValueError(msg)
    return request


def _check_cancel_invalid(id: str, request: ApprovalRequest | None) -> ApprovalRequest:
    if not request:
        raise ApprovalNotFoundError(id)
    if request.type in _VALID_APPROVAL_TYPES:
        msg = (
            f"not an invalid-type request: id={id!r} type={request.type!r}"
            " — use 'ante approval cancel' instead"
        )
        raise ValueError(msg)
    cancellable = (
        ApprovalStatus.PENDING,
        ApprovalStatus.ON_HOLD,
        ApprovalStatus.EXECUTION_FAILED,
    )
    if request.status not in cancellable:
        msg = (
            "pending/on_hold/execution_failed 상태에서만 cancel-invalid 가능"
            f" (현재: {request.status})"
        )
        raise ValueError(msg)
    return request


APPROVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requester       TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    params          TEXT NOT NULL DEFAULT '{}',
    reviews         TEXT NOT NULL DEFAULT '[]',
    history         TEXT NOT NULL DEFAULT '[]',
    reference_id    TEXT DEFAULT '',
    expires_at      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    resolved_at     TEXT DEFAULT '',
    resolved_by     TEXT DEFAULT '',
    reject_reason   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_type ON approvals(type);
"""


class ApprovalService:
    """결재 요청 관리 서비스."""

    def __init__(
        self,
        db: Database,
        eventbus: EventBus,
        executors: dict[str, Callable[..., Awaitable[Any]]] | None = None,
        validators: dict[str, Callable[..., list[ValidationResult]]] | None = None,
        auto_approve_evaluator: AutoApproveEvaluator | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._executors = executors or {}
        self._validators = validators or {}
        self._auto_approve = auto_approve_evaluator or AutoApproveEvaluator()

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(APPROVAL_SCHEMA)
        logger.info("ApprovalService 초기화 완료")

    async def create(
        self,
        type: str,
        requester: str,
        title: str,
        body: str = "",
        params: dict[str, Any] | None = None,
        reference_id: str = "",
        expires_at: str = "",
    ) -> ApprovalRequest:
        """결재 요청 생성.

        ``type`` 이 account-scoped 결재 유형
        (``budget_change``, ``rule_change``, ``bot_create``) 이면
        ``params`` 에서 account_id 를 추출해 :func:`require_account_id` 로
        검증한다. invalid 면 :class:`InvalidAccountIdError` 가 raise 되어
        호출자에 전달된다.
        """
        now = clock.now(UTC).isoformat()
        params = params or {}

        if type not in _VALID_APPROVAL_TYPES:
            msg = f"invalid approval type: {type!r}"
            raise ValueError(msg)

        if type in _ACCOUNT_SCOPED_APPROVAL_TYPES:
            require_account_id(
                _extract_account_id(type, params),
                context=f"approval.{type}.create",
            )

        reviews = await self._validate_params(type, params, now)

        request = ApprovalRequest(
            id=str(uuid4()),
            type=type,
            status=ApprovalStatus.PENDING,
            requester=requester,
            title=title,
            body=body,
            params=params,
            reviews=reviews,
            history=[
                {"action": "created", "actor": requester, "at": now, "detail": ""}
            ],
            reference_id=reference_id,
            expires_at=expires_at,
            created_at=now,
        )

        auto_approved = await self._auto_approve.should_auto_approve(type, params)
        if auto_approved:
            _transition_status(request, ApprovalStatus.APPROVED, "create")
            request.resolved_at = now
            request.resolved_by = "system:auto_approve"
            request.history.append(
                {
                    "action": "approved",
                    "actor": "system:auto_approve",
                    "at": now,
                    "detail": "전결 규칙에 의한 자동 승인",
                }
            )

        await self._persist_request(request)

        logger.info(
            "결재 요청 생성: %s (%s) by %s%s",
            request.id,
            request.type,
            request.requester,
            " [자동 승인]" if auto_approved else "",
        )

        await self._publish_created(request, auto_approved)

        if auto_approved:
            await self._execute_approved(request, "system:auto_approve")

        return request

    async def approve(
        self,
        id: str,
        resolved_by: str = "user",
        *,
        suppress_notification: bool = False,
    ) -> ApprovalRequest:
        """결재 승인 + 자동 실행."""
        request = _check_approve(id, await self.get(id))
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {"action": "approved", "actor": resolved_by, "at": now, "detail": ""}
        )

        status = _transition_status(request, ApprovalStatus.APPROVED, "approve")
        request.resolved_at = now
        request.resolved_by = resolved_by

        won = await self._db.execute_fetch_one(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ? AND status = ?
               RETURNING id""",
            (
                status,
                now,
                resolved_by,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(id, lambda r: _check_approve(id, r), "approve")

        logger.info("결재 승인: %s by %s", id, resolved_by)

        await self._execute_approved(
            request, resolved_by, suppress_notification=suppress_notification
        )

        return request

    async def reject(
        self,
        id: str,
        resolved_by: str = "user",
        reject_reason: str = "",
        *,
        suppress_notification: bool = False,
    ) -> ApprovalRequest:
        """결재 거절."""
        request = _check_reject(id, await self.get(id))
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {
                "action": "rejected",
                "actor": resolved_by,
                "at": now,
                "detail": reject_reason,
            }
        )

        status = _transition_status(request, ApprovalStatus.REJECTED, "reject")
        won = await self._db.execute_fetch_one(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   reject_reason = ?, history = ?
               WHERE id = ? AND status = ?
               RETURNING id""",
            (
                status,
                now,
                resolved_by,
                reject_reason,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(id, lambda r: _check_reject(id, r), "reject")

        request.resolved_at = now
        request.resolved_by = resolved_by
        request.reject_reason = reject_reason

        logger.info("결재 거절: %s by %s (사유: %s)", id, resolved_by, reject_reason)

        from ante.eventbus.events import ApprovalResolvedEvent

        await self._eventbus.publish(
            ApprovalResolvedEvent(
                approval_id=id,
                approval_type=request.type,
                resolution=ApprovalStatus.REJECTED,
                resolved_by=resolved_by,
            )
        )
        if not suppress_notification:
            await self._publish_resolved_notification(
                id, request.type, ApprovalStatus.REJECTED, resolved_by
            )

        return request

    async def reopen(
        self,
        id: str,
        requester: str,
        body: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """거절된 요청을 수정하여 재상신 (rejected → pending).

        body와 params를 갱신할 수 있다. None이면 기존 값 유지.
        본인 요청만 reopen 가능. 사전 검증(validator)을 재실행한다.
        """
        request = _check_reopen(id, await self.get(id), requester)
        read_status = request.status

        if body is not None:
            request.body = body
        if params is not None:
            request.params = params

        if params is not None and request.type in _ACCOUNT_SCOPED_APPROVAL_TYPES:
            require_account_id(
                _extract_account_id(request.type, params),
                context=f"approval.{request.type}.reopen",
            )

        now = clock.now(UTC).isoformat()
        warn_reviews = await self._validate_params(request.type, request.params, now)
        request.reviews.extend(warn_reviews)

        status = _transition_status(request, ApprovalStatus.PENDING, "reopen")
        request.reject_reason = ""
        request.resolved_at = ""
        request.resolved_by = ""

        detail_parts: list[str] = []
        if body is not None:
            detail_parts.append("body 수정")
        if params is not None:
            detail_parts.append("params 수정")
        detail = ", ".join(detail_parts) + " 후 재상신" if detail_parts else "재상신"

        request.history.append(
            {
                "action": "reopened",
                "actor": requester,
                "at": now,
                "detail": detail,
            }
        )

        won = await self._db.execute_fetch_one(
            """UPDATE approvals
               SET status = ?, body = ?, params = ?, reviews = ?,
                   history = ?, reject_reason = ?,
                   resolved_at = ?, resolved_by = ?
               WHERE id = ? AND status = ?
               RETURNING id""",
            (
                status,
                request.body,
                json.dumps(request.params, ensure_ascii=False),
                json.dumps(request.reviews, ensure_ascii=False),
                json.dumps(request.history, ensure_ascii=False),
                "",
                "",
                "",
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(
                id, lambda r: _check_reopen(id, r, requester), "reopen"
            )

        logger.info("결재 재상신: %s by %s", id, requester)

        from ante.eventbus.events import ApprovalCreatedEvent

        await self._eventbus.publish(
            ApprovalCreatedEvent(
                approval_id=request.id,
                approval_type=request.type,
                requester=request.requester,
                title=request.title,
                auto_approved=False,
            )
        )

        return request

    async def cancel(
        self,
        id: str,
        requester: str,
    ) -> ApprovalRequest:
        """결재 철회 (요청자만 가능, pending/on_hold/execution_failed 상태에서만)."""
        request = _check_cancel(id, await self.get(id), requester)
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {"action": "cancelled", "actor": requester, "at": now, "detail": ""}
        )

        status = _transition_status(request, ApprovalStatus.CANCELLED, "cancel")
        won = await self._db.execute_fetch_one(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ? AND status = ?
               RETURNING id""",
            (
                status,
                now,
                requester,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(
                id, lambda r: _check_cancel(id, r, requester), "cancel"
            )

        request.resolved_at = now
        request.resolved_by = requester

        logger.info("결재 철회: %s by %s", id, requester)

        from ante.eventbus.events import ApprovalResolvedEvent

        await self._eventbus.publish(
            ApprovalResolvedEvent(
                approval_id=id,
                approval_type=request.type,
                resolution=ApprovalStatus.CANCELLED,
                resolved_by=requester,
            )
        )
        await self._publish_resolved_notification(
            id, request.type, ApprovalStatus.CANCELLED, requester
        )

        return request

    async def hold(self, id: str) -> ApprovalRequest:
        """보류 전환."""
        request = _check_hold(id, await self.get(id))
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {"action": "held", "actor": "user", "at": now, "detail": ""}
        )

        status = _transition_status(request, ApprovalStatus.ON_HOLD, "hold")
        won = await self._db.execute_fetch_one(
            """UPDATE approvals SET status = ?, history = ?
               WHERE id = ? AND status = ? RETURNING id""",
            (
                status,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(id, lambda r: _check_hold(id, r), "hold")

        logger.info("결재 보류: %s", id)
        return request

    async def resume(self, id: str) -> ApprovalRequest:
        """보류 해제 → pending."""
        request = _check_resume(id, await self.get(id))
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {"action": "resumed", "actor": "user", "at": now, "detail": ""}
        )

        status = _transition_status(request, ApprovalStatus.PENDING, "resume")
        won = await self._db.execute_fetch_one(
            """UPDATE approvals SET status = ?, history = ?
               WHERE id = ? AND status = ? RETURNING id""",
            (
                status,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(id, lambda r: _check_resume(id, r), "resume")

        logger.info("결재 재개: %s", id)
        return request

    async def add_review(
        self,
        id: str,
        reviewer: str,
        result: str,
        detail: str = "",
    ) -> ApprovalRequest:
        """검토 의견 추가.

        not-found 는 ``ApprovalNotFoundError`` 로 raise 해 CLI ``approval
        review`` 가 typed envelope code ``APPROVAL_NOT_FOUND`` 로 surface
        할 수 있도록 한다 (``cancel_invalid_type_request``
        동형 패턴).
        """
        request = await self.get(id)
        if not request:
            raise ApprovalNotFoundError(id)

        now = clock.now(UTC).isoformat()

        review = {
            "reviewer": reviewer,
            "result": result,
            "detail": detail,
            "reviewed_at": now,
        }
        request.reviews.append(review)

        request.history.append(
            {
                "action": "review_added",
                "actor": reviewer,
                "at": now,
                "detail": f"{result}: {detail}" if detail else result,
            }
        )

        await self._db.execute(
            """UPDATE approvals SET reviews = ?, history = ? WHERE id = ?""",
            (
                json.dumps(request.reviews, ensure_ascii=False),
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        logger.info("검토 의견 추가: %s by %s (%s)", id, reviewer, result)
        return request

    async def expire_stale(self) -> int:
        """만료 기한이 지난 pending 요청 일괄 expired 처리."""
        now = clock.now(UTC).isoformat()

        rows = await self._db.fetch_all(
            """SELECT * FROM approvals
               WHERE status = ? AND expires_at != '' AND expires_at < ?""",
            (ApprovalStatus.PENDING, now),
        )

        count = 0
        for row in rows:
            request = self._row_to_request(row)
            request.history.append(
                {"action": "expired", "actor": "system", "at": now, "detail": ""}
            )

            read_status = request.status
            status = _transition_status(request, ApprovalStatus.EXPIRED, "expire_stale")
            won = await self._db.execute_fetch_one(
                """UPDATE approvals
                   SET status = ?, resolved_at = ?, resolved_by = ?,
                       history = ?
                   WHERE id = ? AND status = ?
                   RETURNING id""",
                (
                    status,
                    now,
                    "system",
                    json.dumps(request.history, ensure_ascii=False),
                    request.id,
                    read_status,
                ),
            )
            if won is None:
                logger.debug("만료 처리 건너뜀 (상태가 바뀜): %s", request.id)
                continue

            from ante.eventbus.events import ApprovalResolvedEvent

            await self._eventbus.publish(
                ApprovalResolvedEvent(
                    approval_id=request.id,
                    approval_type=request.type,
                    resolution=ApprovalStatus.EXPIRED,
                    resolved_by="system",
                )
            )
            await self._publish_resolved_notification(
                request.id, request.type, ApprovalStatus.EXPIRED, "system"
            )
            count += 1

        if count:
            logger.info("만료 처리: %d건", count)
        return count

    async def get(self, id: str) -> ApprovalRequest | None:
        """단건 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM approvals WHERE id = ?",
            (id,),
        )
        if not row:
            return None
        return self._row_to_request(row)

    async def list_approvals(
        self,
        status: str | None = None,
        type: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ApprovalRequest]:
        """필터 조회."""
        conditions: list[str] = []
        params: list[object] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if type:
            conditions.append("type = ?")
            params.append(type)
        if search:
            conditions.append("(title LIKE ? OR requester LIKE ?)")
            like_pattern = f"%{search}%"
            params.extend([like_pattern, like_pattern])

        where = " AND ".join(conditions) if conditions else "1=1"
        query = (
            f"SELECT * FROM approvals WHERE {where}"
            " ORDER BY created_at DESC"
            " LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_request(row) for row in rows]

    async def count(
        self,
        status: str | None = None,
        type: str | None = None,
        search: str | None = None,
    ) -> int:
        """필터 조건에 맞는 전체 건수를 반환한다."""
        conditions: list[str] = []
        params: list[object] = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if type:
            conditions.append("type = ?")
            params.append(type)
        if search:
            conditions.append("(title LIKE ? OR requester LIKE ?)")
            like_pattern = f"%{search}%"
            params.extend([like_pattern, like_pattern])

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT COUNT(*) AS cnt FROM approvals WHERE {where}"

        row = await self._db.fetch_one(query, tuple(params))
        return row["cnt"] if row else 0

    async def list_invalid_type_requests(
        self,
        *,
        status: str | None = None,
    ) -> list[ApprovalRequest]:
        """``_VALID_APPROVAL_TYPES`` 외의 ``type`` 을 가진 legacy row 만 반환.

        ``status`` 미지정 시 모든 상태를 포함한다. 정상 type row 는 enum SSOT
        의 모든 멤버를 ``NOT IN`` 으로 제외해 결과에서 자동으로 빠진다.
        """
        valid_types = sorted(_VALID_APPROVAL_TYPES)
        placeholders = ", ".join(["?"] * len(valid_types))
        conditions: list[str] = [f"type NOT IN ({placeholders})"]
        params: list[object] = list(valid_types)

        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        query = f"SELECT * FROM approvals WHERE {where} ORDER BY created_at DESC"

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_request(row) for row in rows]

    async def cancel_invalid_type_request(
        self,
        id: str,
        *,
        resolved_by: str,
        suppress_notification: bool = True,
        detail: str = "legacy invalid type cleanup",
    ) -> ApprovalRequest:
        """administrative cancellation of a legacy invalid-type approval.

        일반 ``cancel()`` 의 requester ownership rule 을 우회해 admin 운영자가
        cleanup 할 수 있게 한다. 정상 type row 와 종결 상태 row 는 거부한다.

        - 처리 가능 상태는 ``pending``, ``on_hold``, ``execution_failed`` 한정.
        - ``suppress_notification=True`` (기본) 시 ``ApprovalResolvedEvent`` /
          notification 발행을 생략한다. False 면 일반 ``cancel()`` 과 동일한
          event/notification 경로를 탄다.
        """
        request = _check_cancel_invalid(id, await self.get(id))
        read_status = request.status

        now = clock.now(UTC).isoformat()
        request.history.append(
            {
                "action": "cancelled_invalid_type",
                "actor": resolved_by,
                "at": now,
                "detail": detail,
            }
        )

        status = _transition_status(
            request, ApprovalStatus.CANCELLED, "cancel_invalid_type_request"
        )
        won = await self._db.execute_fetch_one(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ? AND status = ?
               RETURNING id""",
            (
                status,
                now,
                resolved_by,
                json.dumps(request.history, ensure_ascii=False),
                id,
                read_status,
            ),
        )
        if won is None:
            await self._raise_lost(
                id,
                lambda r: _check_cancel_invalid(id, r),
                "cancel_invalid_type_request",
            )

        request.resolved_at = now
        request.resolved_by = resolved_by

        logger.info(
            "invalid-type 결재 cleanup: %s (type=%s) by %s",
            id,
            request.type,
            resolved_by,
        )

        if not suppress_notification:
            from ante.eventbus.events import ApprovalResolvedEvent

            await self._eventbus.publish(
                ApprovalResolvedEvent(
                    approval_id=id,
                    approval_type=request.type,
                    resolution=ApprovalStatus.CANCELLED,
                    resolved_by=resolved_by,
                )
            )
            await self._publish_resolved_notification(
                id, request.type, ApprovalStatus.CANCELLED, resolved_by
            )

        return request

    async def _raise_lost(
        self,
        id: str,
        check: Callable[[ApprovalRequest | None], ApprovalRequest],
        action: str,
    ) -> NoReturn:
        """진 쪽: 다시 읽어 가드를 다시 돌리고, 통과하면 상태 충돌을 낸다."""
        current = check(await self.get(id))
        raise ApprovalStatusConflictError(
            id,
            current_status=str(current.status),
            requested_action=action,
        )

    async def _validate_params(
        self,
        type: str,
        params: dict[str, Any],
        now: str,
    ) -> list[dict[str, Any]]:
        """사전 검증(validator)을 실행하고 warn reviews를 반환한다."""
        import inspect

        reviews: list[dict[str, Any]] = []
        validator = self._validators.get(type)
        if not validator:
            return reviews

        result_or_coro = validator(params)
        if inspect.isawaitable(result_or_coro):
            results = await result_or_coro
        else:
            results = result_or_coro

        for r in results:
            if r.grade == "fail":
                logger.info("사전 검증 실패 (%s): %s — %s", type, r.reviewer, r.detail)
                raise ApprovalValidationError(r.detail)
            if r.grade == "warn":
                reviews.append(
                    {
                        "reviewer": r.reviewer,
                        "result": "warn",
                        "detail": r.detail,
                        "reviewed_at": now,
                    }
                )
        return reviews

    async def _persist_request(self, request: ApprovalRequest) -> None:
        """ApprovalRequest를 DB에 INSERT한다."""
        await self._db.execute(
            """INSERT INTO approvals
               (id, type, status, requester, title, body, params,
                reviews, history, reference_id, expires_at, created_at,
                resolved_at, resolved_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request.id,
                request.type,
                request.status,
                request.requester,
                request.title,
                request.body,
                json.dumps(request.params, ensure_ascii=False),
                json.dumps(request.reviews, ensure_ascii=False),
                json.dumps(request.history, ensure_ascii=False),
                request.reference_id,
                request.expires_at,
                request.created_at,
                request.resolved_at,
                request.resolved_by,
            ),
        )

    async def _publish_created(
        self, request: ApprovalRequest, auto_approved: bool
    ) -> None:
        """ApprovalCreatedEvent + 알림을 발행한다."""
        from ante.eventbus.events import ApprovalCreatedEvent, NotificationEvent

        await self._eventbus.publish(
            ApprovalCreatedEvent(
                approval_id=request.id,
                approval_type=request.type,
                requester=request.requester,
                title=request.title,
                auto_approved=auto_approved,
            )
        )

        prefix = "[자동 승인] " if auto_approved else ""
        buttons = None
        if not auto_approved:
            buttons = [
                [
                    {"text": "승인", "callback_data": f"approve:{request.id}"},
                    {"text": "거절", "callback_data": f"reject:{request.id}"},
                ]
            ]
        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="결재 요청",
                message=(
                    f"{prefix}유형: `{request.type}`\n"
                    f"제목: {request.title}\n"
                    f"요청자: `{request.requester}`\n"
                    f"ID: `{request.id}`"
                ),
                category="approval",
                buttons=buttons,
            )
        )

    async def _execute_approved(
        self,
        request: ApprovalRequest,
        actor: str,
        *,
        suppress_notification: bool = False,
    ) -> None:
        """승인된 요청의 executor를 실행하고 결과를 반영한다."""
        if request.type not in _VALID_APPROVAL_TYPES:
            msg = f"invalid approval type: {request.type!r}"
            raise ValueError(msg)

        now = clock.now(UTC).isoformat()
        read_status = request.status
        executor = self._executors.get(request.type)
        if executor:
            try:
                await executor(request.params)
                request.history.append(
                    {"action": "executed", "actor": actor, "at": now, "detail": ""}
                )
                await self._db.execute(
                    """UPDATE approvals SET history = ? WHERE id = ?""",
                    (json.dumps(request.history, ensure_ascii=False), request.id),
                )
                logger.info("결재 실행 완료: %s (%s)", request.id, request.type)
            except Exception as exc:
                status = _transition_status(
                    request, ApprovalStatus.EXECUTION_FAILED, "execute"
                )
                request.history.append(
                    {
                        "action": "execution_failed",
                        "actor": actor,
                        "at": now,
                        "detail": str(exc),
                    }
                )
                won = await self._db.execute_fetch_one(
                    """UPDATE approvals SET status = ?, history = ?
                       WHERE id = ? AND status = ? RETURNING id""",
                    (
                        status,
                        json.dumps(request.history, ensure_ascii=False),
                        request.id,
                        read_status,
                    ),
                )
                if won is None:
                    logger.warning(
                        "결재 실행 실패 기록 건너뜀 (상태가 바뀜): %s (%s): %s",
                        request.id,
                        request.type,
                        exc,
                    )
                    return
                logger.exception("결재 실행 실패: %s (%s)", request.id, request.type)
        else:
            status = _transition_status(
                request, ApprovalStatus.EXECUTION_FAILED, "execute"
            )
            request.history.append(
                {
                    "action": "no_executor",
                    "actor": actor,
                    "at": now,
                    "detail": (f"no executor registered for type {request.type!r}"),
                }
            )
            won = await self._db.execute_fetch_one(
                """UPDATE approvals SET status = ?, history = ?
                   WHERE id = ? AND status = ? RETURNING id""",
                (
                    status,
                    json.dumps(request.history, ensure_ascii=False),
                    request.id,
                    read_status,
                ),
            )
            if won is None:
                logger.warning(
                    "결재 실행 불가 기록 건너뜀 (상태가 바뀜): %s (%s)",
                    request.id,
                    request.type,
                )
                return
            logger.warning(
                "결재 실행 불가 (executor 미등록): %s (%s)",
                request.id,
                request.type,
            )

        from ante.eventbus.events import ApprovalResolvedEvent

        await self._eventbus.publish(
            ApprovalResolvedEvent(
                approval_id=request.id,
                approval_type=request.type,
                resolution=request.status,
                resolved_by=actor,
            )
        )
        if not suppress_notification:
            await self._publish_resolved_notification(
                request.id, request.type, request.status, actor
            )

    async def _publish_resolved_notification(
        self,
        approval_id: str,
        approval_type: str,
        resolution: str,
        resolved_by: str,
    ) -> None:
        """결재 처리 완료 알림 발행."""
        from ante.eventbus.events import NotificationEvent

        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title="결재 처리 완료",
                message=(
                    f"유형: `{approval_type}`\n"
                    f"결과: *{resolution}*\n"
                    f"처리자: `{resolved_by}`\n"
                    f"ID: `{approval_id}`"
                ),
                category="approval",
            )
        )

    @staticmethod
    def _row_to_request(row: dict[str, Any]) -> ApprovalRequest:
        """DB row → ApprovalRequest 변환."""
        return ApprovalRequest(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            requester=row["requester"],
            title=row["title"],
            body=row.get("body", ""),
            params=json.loads(row.get("params", "{}")),
            reviews=json.loads(row.get("reviews", "[]")),
            history=json.loads(row.get("history", "[]")),
            reference_id=row.get("reference_id", ""),
            expires_at=row.get("expires_at", ""),
            created_at=row.get("created_at", ""),
            resolved_at=row.get("resolved_at", ""),
            resolved_by=row.get("resolved_by", ""),
            reject_reason=row.get("reject_reason", ""),
        )
