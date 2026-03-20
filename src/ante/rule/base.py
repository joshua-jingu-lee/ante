"""Rule Engine 기본 타입 — Rule ABC, 데이터 모델."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RuleResult(StrEnum):
    """룰 평가 결과."""

    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    REJECT = "reject"


class RuleAction(StrEnum):
    """룰 위반 시 조치."""

    LOG = "log"
    NOTIFY = "notify"
    STOP_BOT = "stop_bot"
    HALT_ACCOUNT = "halt_account"


@dataclass(frozen=True)
class RuleEvaluation:
    """단일 룰 평가 결과."""

    rule_id: str
    rule_name: str
    result: RuleResult
    action: RuleAction
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleContext:
    """룰 평가 컨텍스트.

    RuleEngine이 OrderRequestEvent와 계좌 상태를 조합하여 생성한다.
    """

    # 주문 정보
    bot_id: str = ""
    account_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    order_type: str = "market"
    price: float | None = None
    exchange: str = "KRX"
    currency: str = "KRW"

    # 시장/포지션 정보
    current_price: float = 0.0
    current_position: float = 0.0
    available_balance: float = 0.0

    # 계좌 상태
    account_status: str = "active"
    daily_pnl: float = 0.0
    total_pnl: float = 0.0

    # 추가 메타데이터
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationResult:
    """전체 룰 평가 종합 결과."""

    overall_result: RuleResult
    evaluations: list[RuleEvaluation] = field(default_factory=list)
    rejection_reason: str = ""
    actions: list[RuleAction] = field(default_factory=list)


class Rule(ABC):
    """룰 추상 기본 클래스."""

    def __init__(self, rule_id: str, config: dict[str, Any]) -> None:
        self.rule_id = rule_id
        self.config = config
        self.name: str = config.get("name", rule_id)
        self.description: str = config.get("description", "")
        self.priority: int = config.get("priority", 0)
        self.enabled: bool = config.get("enabled", True)

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        """룰 평가 로직."""
        ...

    def is_applicable(self, context: RuleContext) -> bool:
        """이 룰이 해당 상황에 적용되는지 확인."""
        return self.enabled
