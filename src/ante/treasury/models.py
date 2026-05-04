"""Treasury 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BotBudget:
    """봇별 예산 상태.

    ``account_id`` 는 필수다 — write 경로의 fallback 금지 정책
    (`docs/specs/account/14-account-id-contract.md`) 에 따라 빈 값/
    fallback 값을 거부한다.
    """

    bot_id: str
    account_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))
