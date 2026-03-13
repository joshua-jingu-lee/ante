"""Approval 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ApprovalStatus(StrEnum):
    """결재 상태."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalType(StrEnum):
    """결재 유형."""

    STRATEGY_ADOPT = "strategy_adopt"
    BUDGET_CHANGE = "budget_change"
    BOT_CREATE = "bot_create"
    BOT_STOP = "bot_stop"
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
