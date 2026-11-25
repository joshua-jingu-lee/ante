"""Rule Engine 기본 타입 — Rule ABC, 데이터 모델."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


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
    ``account_id`` 는 dataclass field ordering 때문에 default를 유지
    하지만, ``__post_init__`` 에서 :func:`require_account_id` 로 runtime
    검증된다.
    """

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

    current_price: float = 0.0
    current_position: float = 0.0
    available_balance: float = 0.0
    bot_allocated_budget: float = 0.0

    unrealized_pnl: float = 0.0

    account_status: str = "active"
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    prev_day_total_asset: float = 0.0
    total_asset: float = 0.0
    total_exposure: float = 0.0

    trading_hours_start: str = "09:00"
    trading_hours_end: str = "15:30"
    timezone: str = "Asia/Seoul"

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from ante.account.scoping import require_account_id

        self.account_id = require_account_id(
            self.account_id, context="rule_context.__post_init__"
        )


@dataclass
class EvaluationResult:
    """전체 룰 평가 종합 결과."""

    overall_result: RuleResult
    evaluations: list[RuleEvaluation] = field(default_factory=list)
    rejection_reason: str = ""
    actions: list[RuleAction] = field(default_factory=list)


COMMON_CONFIG_KEYS: frozenset[str] = frozenset(
    {"type", "id", "name", "description", "priority", "enabled"}
)


class Rule(ABC):
    """룰 추상 기본 클래스."""

    CONFIG_KEYS: ClassVar[frozenset[str]] = frozenset()

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

    @classmethod
    def validate_config(cls, params: dict[str, Any]) -> list[str]:
        """룰 파라미터의 유효성을 검증한다.

        Args:
            params: 검증할 config 파라미터 딕셔너리.

        Returns:
            에러 메시지 리스트. 비어 있으면 유효.
        """
        return []

    @classmethod
    def config_errors(cls, cfg: dict[str, Any]) -> list[str]:
        """룰 항목 config의 오류를 정해진 순서로 돌려준다.

        모르는 key(공통 key와 ``CONFIG_KEYS`` 밖, 값은 싣지 않는다), 문자열이 아닌
        ``id``, ``validate_config`` 의 결과 순이다. 비어 있으면 유효.
        """
        rule_type = cfg.get("type")
        rule_keys = ", ".join(sorted(cls.CONFIG_KEYS))
        unknown = sorted(cfg.keys() - COMMON_CONFIG_KEYS - cls.CONFIG_KEYS, key=repr)
        errors = [
            f"{key!r} is not a config key of {rule_type} (rule keys: {rule_keys})"
            for key in unknown
        ]
        if "id" in cfg and not isinstance(cfg["id"], str):
            errors.append("id must be a string")
        return errors + cls.validate_config(cfg)

    def is_applicable(self, context: RuleContext) -> bool:
        """이 룰이 해당 상황에 적용되는지 확인."""
        return self.enabled
