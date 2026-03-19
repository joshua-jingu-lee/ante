"""ApprovalService — 결재 요청 관리."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ante.approval.auto_approve import AutoApproveEvaluator
from ante.approval.models import ApprovalRequest, ApprovalStatus

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
        auto_approve_evaluator: AutoApproveEvaluator | None = None,
    ) -> None:
        self._db = db
        self._eventbus = eventbus
        self._executors = executors or {}
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
        request_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        params = params or {}

        history = [
            {
                "action": "created",
                "actor": requester,
                "at": now,
                "detail": "",
            }
        ]

        request = ApprovalRequest(
            id=request_id,
            type=type,
            status=ApprovalStatus.PENDING,
            requester=requester,
            title=title,
            body=body,
            params=params,
            reviews=[],
            history=history,
            reference_id=reference_id,
            expires_at=expires_at,
            created_at=now,
        )

        # 전결 평가
        auto_approved = self._auto_approve.should_auto_approve(type, params)

        if auto_approved:
            # 즉시 승인 처리: status를 APPROVED로 설정
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

        # DB INSERT (auto_approved이면 approved 상태로 저장)
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

        logger.info(
            "결재 요청 생성: %s (%s) by %s%s",
            request.id,
            request.type,
            request.requester,
            " [자동 승인]" if auto_approved else "",
        )

        # ApprovalCreatedEvent 발행
        from ante.eventbus.events import ApprovalCreatedEvent

        await self._eventbus.publish(
            ApprovalCreatedEvent(
                approval_id=request.id,
                approval_type=request.type,
                requester=request.requester,
                title=request.title,
                auto_approved=auto_approved,
            )
        )

        # 전결 시 executor 즉시 실행
        if auto_approved:
            executor = self._executors.get(request.type)
            if executor:
                try:
                    await executor(request.params)
                    request.history.append(
                        {
                            "action": "executed",
                            "actor": "system:auto_approve",
                            "at": now,
                            "detail": "",
                        }
                    )
                    await self._db.execute(
                        """UPDATE approvals SET history = ? WHERE id = ?""",
                        (
                            json.dumps(request.history, ensure_ascii=False),
                            request.id,
                        ),
                    )
                    logger.info("전결 실행 완료: %s (%s)", request.id, request.type)
                except Exception as exc:
                    request.status = ApprovalStatus.EXECUTION_FAILED
                    request.history.append(
                        {
                            "action": "execution_failed",
                            "actor": "system:auto_approve",
                            "at": now,
                            "detail": str(exc),
                        }
                    )
                    await self._db.execute(
                        """UPDATE approvals
                           SET status = ?, history = ?
                           WHERE id = ?""",
                        (
                            ApprovalStatus.EXECUTION_FAILED,
                            json.dumps(request.history, ensure_ascii=False),
                            request.id,
                        ),
                    )
                    logger.exception(
                        "전결 실행 실패: %s (%s)", request.id, request.type
                    )

            # ApprovalResolvedEvent 발행
            from ante.eventbus.events import ApprovalResolvedEvent

            await self._eventbus.publish(
                ApprovalResolvedEvent(
                    approval_id=request.id,
                    approval_type=request.type,
                    resolution=request.status,
                    resolved_by="system:auto_approve",
                )
            )

        return request

    async def approve(
        self,
        id: str,
        resolved_by: str = "user",
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

        request.status = ApprovalStatus.APPROVED
        request.resolved_at = now
        request.resolved_by = resolved_by

        logger.info("결재 승인: %s by %s", id, resolved_by)

        # 자동 실행
        executor = self._executors.get(request.type)
        if executor:
            try:
                await executor(request.params)
                request.history.append(
                    {
                        "action": "executed",
                        "actor": resolved_by,
                        "at": now,
                        "detail": "",
                    }
                )
                logger.info("결재 실행 완료: %s (%s)", id, request.type)
            except Exception as exc:
                request.status = ApprovalStatus.EXECUTION_FAILED
                request.history.append(
                    {
                        "action": "execution_failed",
                        "actor": resolved_by,
                        "at": now,
                        "detail": str(exc),
                    }
                )
                await self._db.execute(
                    """UPDATE approvals
                       SET status = ?, history = ?
                       WHERE id = ?""",
                    (
                        ApprovalStatus.EXECUTION_FAILED,
                        json.dumps(request.history, ensure_ascii=False),
                        id,
                    ),
                )
                logger.exception("결재 실행 실패: %s (%s)", id, request.type)
            else:
                # 실행 성공 시 history만 갱신
                await self._db.execute(
                    """UPDATE approvals SET history = ? WHERE id = ?""",
                    (json.dumps(request.history, ensure_ascii=False), id),
                )

        # ApprovalResolvedEvent 발행
        from ante.eventbus.events import ApprovalResolvedEvent

        await self._eventbus.publish(
            ApprovalResolvedEvent(
                approval_id=id,
                approval_type=request.type,
                resolution=request.status,
                resolved_by=resolved_by,
            )
        )

        return request

    async def reject(
        self,
        id: str,
        resolved_by: str = "user",
        reject_reason: str = "",
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
