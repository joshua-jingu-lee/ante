"""AutoApproveEvaluator — 결재 전결(자동 승인) 규칙 평가기."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 전결 대상에서 제외되는 유형
EXCLUDED_TYPES: frozenset[str] = frozenset({"strategy_adopt", "strategy_retire"})


@dataclass(frozen=True)
class AutoApproveConfig:
    """전결 설정.

    system.toml의 [approval.auto_approve] 섹션에 대응한다.
    """

    enabled: bool = False
    bot_stop: bool = True
    bot_create_paper: bool = True
    budget_change_max: float = 5_000_000

    @classmethod
    def from_dict(cls, data: dict) -> AutoApproveConfig:
        """dict에서 AutoApproveConfig 생성.

        Config.get("approval.auto_approve", {}) 결과를 받는다.
        """
        rules = data.get("rules", {})
        return cls(
            enabled=bool(data.get("enabled", False)),
            bot_stop=bool(rules.get("bot_stop", True)),
            bot_create_paper=bool(rules.get("bot_create_paper", True)),
            budget_change_max=float(rules.get("budget_change_max", 5_000_000)),
        )


@dataclass
class AutoApproveEvaluator:
    """결재 전결 규칙 평가기.

    ApprovalService.create() 호출 시, 요청 유형과 파라미터를 기반으로
    자동 승인 여부를 판단한다.
    """

    config: AutoApproveConfig = field(default_factory=AutoApproveConfig)

    def should_auto_approve(self, type: str, params: dict | None = None) -> bool:
        """전결 조건 평가.

        Args:
            type: 결재 요청 유형 (예: "bot_stop", "budget_change")
            params: 유형별 실행 파라미터

        Returns:
            True이면 자동 승인 대상.
        """
        if not self.config.enabled:
            return False

        if type in EXCLUDED_TYPES:
            return False

        params = params or {}

        if type == "bot_stop" and self.config.bot_stop:
            return True

        if type == "bot_create" and self.config.bot_create_paper:
            if params.get("mode") == "paper":
                return True

        if type == "budget_change" and self.config.budget_change_max > 0:
            amount = params.get("amount", 0)
            current = params.get("current", 0)
            change = abs(float(amount) - float(current))
            if change <= self.config.budget_change_max:
                return True

        return False
