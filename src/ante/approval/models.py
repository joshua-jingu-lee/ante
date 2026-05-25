"""Approval 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalStatus(StrEnum):
    """결재 상태."""

    PENDING = "pending"
    APPROVED = "approved"
    EXECUTION_FAILED = "execution_failed"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalType(StrEnum):
    """결재 유형."""

    STRATEGY_ADOPT = "strategy_adopt"
    STRATEGY_RETIRE = "strategy_retire"
    BOT_CREATE = "bot_create"
    BOT_ASSIGN_STRATEGY = "bot_assign_strategy"
    BOT_CHANGE_STRATEGY = "bot_change_strategy"
    BOT_STOP = "bot_stop"
    BOT_RESUME = "bot_resume"
    BOT_DELETE = "bot_delete"
    BUDGET_CHANGE = "budget_change"
    RULE_CHANGE = "rule_change"


@dataclass
class ApprovalRequest:
    """결재 요청."""

    id: str
    type: str
    status: str
    requester: str
    title: str
    body: str = ""
    params: dict = field(default_factory=dict)
    reviews: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    reference_id: str = ""
    expires_at: str = ""
    created_at: str = ""
    resolved_at: str = ""
    resolved_by: str = ""
    reject_reason: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """사전 검증 결과.

    grade:
        - "fail": 논리적으로 실행 불가능 — 요청 생성 차단
        - "warn": 판단 여지 있음 — 경고를 reviews에 첨부
        - "pass": 검증 통과
    """

    grade: str
    detail: str
    reviewer: str


class ApprovalValidationError(Exception):
    """사전 검증 실패 — 요청 생성 차단.

    클래스 레벨 ``code`` 속성은 IPC 서버 envelope 이 안정 코드
    ``"APPROVAL_VALIDATION_ERROR"`` 로 surface 하도록 한다 (#1843 sub-PR 2;
    CLI ``approval request`` 의 ``--params`` / ``--type`` / ``--expires-in``
    ingress validation 과 동일한 안정 코드). helper
    (``error_spec_for_exception``) 의 registry MRO lookup 도 동일 코드로
    resolve 한다.
    """

    code: str = "APPROVAL_VALIDATION_ERROR"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)
