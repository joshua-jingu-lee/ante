"""ApprovalService — 결재 요청 관리."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ante.account.scoping import require_account_id
from ante.approval.auto_approve import AutoApproveEvaluator
from ante.approval.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
    ApprovalValidationError,
    ValidationResult,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


# Refs #1217 → #1241 SPLIT-2: ``docs/specs/account/14-account-id-contract.md``
# §6 ApprovalService 표 기준. account-scoped payload 가 필수인 결재 유형만
# 포함한다. ``bot_stop``, ``bot_resume``, ``bot_delete``, ``bot_assign_strategy``,
# ``bot_change_strategy`` 는 ``bot_id`` 로 봇/계좌가 결정되므로 제외하고,
# ``strategy_adopt``/``strategy_retire`` 는 글로벌 결재이므로 제외한다.
_ACCOUNT_SCOPED_APPROVAL_TYPES: frozenset[str] = frozenset(
    {"budget_change", "rule_change", "bot_create"}
)


# Refs #1418 → #1470 SPLIT-B: ApprovalType enum SSOT.
# ``ApprovalType`` 의 모든 값을 frozenset 으로 보관한다. enum 멤버십 검증을
# ``create()`` (#1469), ``approve()`` (#1470), ``_execute_approved()``
# (#1470 defense-in-depth) 세 진입점에서 공유한다. 동치성: ``set(t.value for
# t in ApprovalType)`` 와 항상 동일하므로 신규 ApprovalType 멤버 추가 시
# 자동으로 반영된다.
_VALID_APPROVAL_TYPES: frozenset[str] = frozenset(t.value for t in ApprovalType)


def _extract_account_id(type: str, params: dict | None) -> str | None:
    """account-scoped approval payload 에서 account_id 를 꺼낸다.

    우선순위 (config-first → flat fallback):

    1. ``params["config"]["account_id"]`` (web/CLI 가 BotConfig 형태로
       래핑해 보내는 신규 형태)
    2. ``params["account_id"]`` (legacy 평면 형태)

    어느 위치에서든 발견되지 않으면 ``None`` 을 반환하고, 호출자가
    :func:`ante.account.scoping.require_account_id` 로 거부한다.
    """
    if params is None:
        return None
    config = params.get("config")
    if isinstance(config, dict):
        candidate = config.get("account_id")
        if candidate is not None:
            return candidate  # type: ignore[no-any-return]
    return params.get("account_id")


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
        """결재 요청 생성.

        Refs #1217 → #1241 SPLIT-2: ``type`` 이 account-scoped 결재 유형
        (``budget_change``, ``rule_change``, ``bot_create``) 이면
        ``params`` 에서 account_id 를 추출해 :func:`require_account_id` 로
        검증한다. invalid 면 :class:`InvalidAccountIdError` 가 raise 되어
        호출자에 전달된다.
        """
        now = datetime.now(UTC).isoformat()
        params = params or {}

        # ApprovalType SSOT 검증 — defense-in-depth (IPC handler 가 직접 호출,
        # #1469). ``_validate_params`` 보다 먼저 실행되어야 한다.
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

        # 전결 평가
        auto_approved = await self._auto_approve.should_auto_approve(type, params)
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

        # Refs #1418 → #1470 SPLIT-B: legacy invalid approval type pending row
        # 가 DB 에 남아있을 수 있다 (#1469 write-path 가드 이전 데이터). status
        # transition 전에 enum 멤버십을 검증해 PENDING → APPROVED 전이를 차단한다.
        # 차단된 경우 history/event/notification 발행이 모두 없으므로 silent
        # success 가 발생하지 않는다.
        if request.type not in _VALID_APPROVAL_TYPES:
            msg = f"invalid approval type: {request.type!r}"
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

        # Refs #1217 → #1241 SPLIT-2: account-scoped 결재 유형 reopen 시
        # 갱신된 params 에 대해 account_id 재검증. params 가 None 이면 기존
        # request.params 가 이미 create() 단계에서 검증됐으므로 스킵한다.
        if params is not None and request.type in _ACCOUNT_SCOPED_APPROVAL_TYPES:
            require_account_id(
                _extract_account_id(request.type, params),
                context=f"approval.{request.type}.reopen",
            )

        # 사전 검증(validator) 재실행
        now = datetime.now(UTC).isoformat()
        warn_reviews = await self._validate_params(request.type, request.params, now)
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
            f"SELECT * FROM approvals WHERE {where}"  # noqa: S608
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
        query = f"SELECT COUNT(*) AS cnt FROM approvals WHERE {where}"  # noqa: S608

        row = await self._db.fetch_one(query, tuple(params))
        return row["cnt"] if row else 0

    # Refs #1418 → #1472 SPLIT-D: legacy invalid-type approval cleanup.
    # ``list_invalid_type_requests`` 와 ``cancel_invalid_type_request`` 는
    # ``_VALID_APPROVAL_TYPES`` SSOT 에 없는 ``type`` 값을 가진 legacy row 만
    # 다룬다. 정상 type row 는 두 메서드 모두에서 절대 처리되지 않는다.
    async def list_invalid_type_requests(
        self,
        *,
        status: str | None = None,
    ) -> list[ApprovalRequest]:
        """``_VALID_APPROVAL_TYPES`` 외의 ``type`` 을 가진 legacy row 만 반환.

        ``status`` 미지정 시 모든 상태를 포함한다. 정상 type row 는 enum SSOT
        의 모든 멤버를 ``NOT IN`` 으로 제외해 결과에서 자동으로 빠진다.

        Refs #1418 → #1472 SPLIT-D.
        """
        valid_types = sorted(_VALID_APPROVAL_TYPES)
        placeholders = ", ".join(["?"] * len(valid_types))
        conditions: list[str] = [f"type NOT IN ({placeholders})"]
        params: list[object] = list(valid_types)

        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions)
        query = (
            f"SELECT * FROM approvals WHERE {where} "  # noqa: S608
            "ORDER BY created_at DESC"
        )

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

        - ``type`` 이 ``_VALID_APPROVAL_TYPES`` 에 있으면 ``ValueError`` raise.
        - 처리 가능 상태는 ``pending``, ``on_hold``, ``execution_failed`` 한정.
        - history 에 ``cancelled_invalid_type`` 액션을 append 하고,
          ``status=cancelled``, ``resolved_by``/``resolved_at`` 을 기록한다.
        - ``suppress_notification=True`` (기본) 시 ``ApprovalResolvedEvent`` /
          notification 발행을 생략한다. False 면 일반 ``cancel()`` 과 동일한
          event/notification 경로를 탄다.

        Refs #1418 → #1472 SPLIT-D.
        """
        request = await self.get(id)
        if not request:
            msg = f"결재 요청을 찾을 수 없음: {id}"
            raise ValueError(msg)

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

        now = datetime.now(UTC).isoformat()
        request.history.append(
            {
                "action": "cancelled_invalid_type",
                "actor": resolved_by,
                "at": now,
                "detail": detail,
            }
        )

        await self._db.execute(
            """UPDATE approvals
               SET status = ?, resolved_at = ?, resolved_by = ?,
                   history = ?
               WHERE id = ?""",
            (
                ApprovalStatus.CANCELLED,
                now,
                resolved_by,
                json.dumps(request.history, ensure_ascii=False),
                id,
            ),
        )

        request.status = ApprovalStatus.CANCELLED
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

    async def _validate_params(
        self,
        type: str,
        params: dict,
        now: str,
    ) -> list[dict]:
        """사전 검증(validator)을 실행하고 warn reviews를 반환한다.

        validator가 async이면 await, 동기이면 그대로 호출한다.
        """
        import inspect

        reviews: list[dict] = []
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
        """승인된 요청의 executor를 실행하고 결과를 반영한다.

        create()의 전결 실행과 approve()의 자동 실행에서 공유된다.

        Refs #1418 → #1470 SPLIT-B:
        - 진입부에서 ``request.type`` 의 enum 멤버십을 다시 검증한다
          (defense-in-depth). ``approve()`` 와 ``create()`` 에서 이미 검증
          했지만 ``create()`` 의 auto-approval 경로는 ``approve()`` 가드를
          거치지 않으므로 여기서 한 번 더 차단한다. invalid → ``ValueError``.
        - executor 가 등록되지 않은 경우 (enum 은 valid 한데 dispatch
          대상 없음): status 를 ``EXECUTION_FAILED`` 로 설정하고
          ``no_executor`` history 를 남긴다. 이로써 silent success 가
          차단되고 후속 ``ApprovalResolvedEvent`` 의 ``resolution`` 이
          ``execution_failed`` 로 전달된다.
        """
        if request.type not in _VALID_APPROVAL_TYPES:
            msg = f"invalid approval type: {request.type!r}"
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
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
        else:
            # enum 은 valid 하지만 dispatch executor 가 없는 경우. 이전에는
            # silent 하게 ``ApprovalResolvedEvent`` 만 발행되어 호출자가
            # 성공 처리한 것으로 오인했다. 명시적으로 EXECUTION_FAILED 로
            # 마무리하고 history 에 ``no_executor`` 를 남긴다.
            request.status = ApprovalStatus.EXECUTION_FAILED
            request.history.append(
                {
                    "action": "no_executor",
                    "actor": actor,
                    "at": now,
                    "detail": (f"no executor registered for type {request.type!r}"),
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
