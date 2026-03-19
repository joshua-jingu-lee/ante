"""ApprovalService — 결재 요청 관리."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ante.approval.auto_approve import AutoApproveEvaluator
from ante.approval.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalValidationError,
    ValidationResult,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

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
        executors: dict[str, Callable[..., Awaitable]] | None = None,
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
        params: dict | None = None,
        reference_id: str = "",
        expires_at: str = "",
    ) -> ApprovalRequest:
        """결재 요청 생성."""
        now = datetime.now(UTC).isoformat()
        params = params or {}

        reviews = self._validate_params(type, params, now)

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

        # 전결 평가
        auto_approved = self._auto_approve.should_auto_approve(type, params)
        if auto_approved:
            request.status = ApprovalStatus.APPROVED
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
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        approvable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
        if request.status not in approvable:
            msg = (
                "pending/execution_failed 상태에서만 승인 가능"
                f" (현재: {request.status})"
            )
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {"action": "approved", "actor": resolved_by, "at": now, "detail": ""}
        )

        request.status = ApprovalStatus.APPROVED
        request.resolved_at = now
        request.resolved_by = resolved_by

        await self._db.execute(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ?""",
            (
                ApprovalStatus.APPROVED,
                now,
                resolved_by,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

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
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        rejectable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
        if request.status not in rejectable:
            msg = (
                "pending/execution_failed 상태에서만 거절 가능"
                f" (현재: {request.status})"
            )
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {
                "action": "rejected",
                "actor": resolved_by,
                "at": now,
                "detail": reject_reason,
            }
        )

        await self._db.execute(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   reject_reason = ?, history = ?
               WHERE id = ?""",
            (
                ApprovalStatus.REJECTED,
                now,
                resolved_by,
                reject_reason,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        request.status = ApprovalStatus.REJECTED
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
        params: dict | None = None,
    ) -> ApprovalRequest:
        """거절된 요청을 수정하여 재상신 (rejected → pending).

        body와 params를 갱신할 수 있다. None이면 기존 값 유지.
        본인 요청만 reopen 가능. 사전 검증(validator)을 재실행한다.
        """
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        # 상태 검증: rejected만 허용
        if request.status != ApprovalStatus.REJECTED:
            msg = f"rejected 상태에서만 reopen 가능 (현재: {request.status})"
            raise ValueError(msg)

        # 권한 검증: 본인 요청만 reopen 가능
        if request.requester != requester:
            msg = f"본인 요청만 reopen 가능 (요청자: {request.requester})"
            raise ValueError(msg)

        # body/params 갱신 (None이면 기존 값 유지)
        if body is not None:
            request.body = body
        if params is not None:
            request.params = params

        # 사전 검증(validator) 재실행
        now = datetime.now(UTC).isoformat()
        warn_reviews = self._validate_params(request.type, request.params, now)
        request.reviews.extend(warn_reviews)

        # 상태 전환 + 이력 기록
        request.status = ApprovalStatus.PENDING
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

        # DB 업데이트
        await self._db.execute(
            """UPDATE approvals
               SET status = ?, body = ?, params = ?, reviews = ?,
                   history = ?, reject_reason = ?,
                   resolved_at = ?, resolved_by = ?
               WHERE id = ?""",
            (
                ApprovalStatus.PENDING,
                request.body,
                json.dumps(request.params, ensure_ascii=False),
                json.dumps(request.reviews, ensure_ascii=False),
                json.dumps(request.history, ensure_ascii=False),
                "",
                "",
                "",
                id,
            ),
        )

        logger.info("결재 재상신: %s by %s", id, requester)

        # ApprovalCreatedEvent 재발행 (알림 재발송)
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
        """결재 철회 (요청자만 가능, pending/on_hold 상태에서만)."""
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

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

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {"action": "cancelled", "actor": requester, "at": now, "detail": ""}
        )

        await self._db.execute(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ?""",
            (
                ApprovalStatus.CANCELLED,
                now,
                requester,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        request.status = ApprovalStatus.CANCELLED
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
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        holdable = (ApprovalStatus.PENDING, ApprovalStatus.EXECUTION_FAILED)
        if request.status not in holdable:
            msg = (
                "pending/execution_failed 상태에서만 보류 가능"
                f" (현재: {request.status})"
            )
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {"action": "held", "actor": "user", "at": now, "detail": ""}
        )

        await self._db.execute(
            """UPDATE approvals SET status = ?, history = ? WHERE id = ?""",
            (
                ApprovalStatus.ON_HOLD,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        request.status = ApprovalStatus.ON_HOLD
        logger.info("결재 보류: %s", id)
        return request

    async def resume(self, id: str) -> ApprovalRequest:
        """보류 해제 → pending."""
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        if request.status != ApprovalStatus.ON_HOLD:
            msg = f"on_hold 상태에서만 재개 가능 (현재: {request.status})"
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {"action": "resumed", "actor": "user", "at": now, "detail": ""}
        )

        await self._db.execute(
            """UPDATE approvals SET status = ?, history = ? WHERE id = ?""",
            (
                ApprovalStatus.PENDING,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        request.status = ApprovalStatus.PENDING
        logger.info("결재 재개: %s", id)
        return request

    async def add_review(
        self,
        id: str,
        reviewer: str,
        result: str,
        detail: str = "",
    ) -> ApprovalRequest:
        """검토 의견 추가."""
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()

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
        now = datetime.now(UTC).isoformat()

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

            await self._db.execute(
                """UPDATE approvals
                   SET status = ?, resolved_at = ?, resolved_by = ?,
                       history = ?
                   WHERE id = ?""",
                (
                    ApprovalStatus.EXPIRED,
                    now,
                    "system",
                    json.dumps(request.history, ensure_ascii=False),
                    request.id,
                ),
            )

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

    async def list(
        self,
        status: str | None = None,
        type: str | None = None,
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

        where = " AND ".join(conditions) if conditions else "1=1"
        query = (
            f"SELECT * FROM approvals WHERE {where}"  # noqa: S608
            " ORDER BY created_at DESC"
            " LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_request(row) for row in rows]

    def _validate_params(
        self,
        type: str,
        params: dict,
        now: str,
    ) -> list[dict]:
        """사전 검증(validator)을 실행하고 warn reviews를 반환한다."""
        reviews: list[dict] = []
        validator = self._validators.get(type)
        if not validator:
            return reviews

        results = validator(params)
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
        """승인된 요청의 executor를 실행하고 결과를 반영한다.

        create()의 전결 실행과 approve()의 자동 실행에서 공유된다.
        """
        executor = self._executors.get(request.type)
        if executor:
            now = datetime.now(UTC).isoformat()
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
                request.status = ApprovalStatus.EXECUTION_FAILED
                request.history.append(
                    {
                        "action": "execution_failed",
                        "actor": actor,
                        "at": now,
                        "detail": str(exc),
                    }
                )
                await self._db.execute(
                    """UPDATE approvals SET status = ?, history = ? WHERE id = ?""",
                    (
                        ApprovalStatus.EXECUTION_FAILED,
                        json.dumps(request.history, ensure_ascii=False),
                        request.id,
                    ),
                )
                logger.exception("결재 실행 실패: %s (%s)", request.id, request.type)

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
    def _row_to_request(row: dict) -> ApprovalRequest:
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
