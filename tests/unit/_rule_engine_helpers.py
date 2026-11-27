"""RuleEngine 테스트가 쓰는 가짜 Treasury. Refs #3047.

RuleEngine은 Treasury가 없거나 조회가 예외를 던지면 매수를 거부한다
(`docs/specs/rule-engine/07-rule-engine-core.md` 「판정 입력 조회 실패」).
매수 승인 경로를 검증하는 테스트는 이 가짜를 주입한다. 기본값은 예전의
미주입 엔진이 채우던 값(전부 0·스냅샷 없음·예산 없음)과 같아 룰 판정을 바꾸지
않는다. ``fail``에 조회 이름을 주면 그 조회만 예외를 던진다.

시장가 매수를 통과시키는 테스트는 ``fixed_quote``를 시세 조회로 넣는다(#3097).
보유 종목의 동기화 시세와 성공한 동기화의 범위는 기본으로 없다(#3102).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ante.treasury.treasury import SYNCED_PRICE_MISSING

TREASURY_QUERIES = (
    "get_summary",
    "get_budget",
    "get_prev_day_snapshot",
)


FIXED_QUOTE = 10_000.0


async def fixed_quote(symbol: str) -> float:
    """시장가 매수 평가에 쓰는 고정 시세."""
    return FIXED_QUOTE


@dataclass
class StubBudget:
    allocated: float


class StubTreasury:
    """룰 엔진이 읽는 Treasury 조회 셋만 흉내 낸다."""

    def __init__(
        self,
        *,
        fail: str | None = None,
        summary: dict[str, float] | None = None,
        budget: float | None = None,
        prev_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if fail is not None and fail not in TREASURY_QUERIES:
            raise ValueError(f"unknown treasury query: {fail}")
        self._fail = fail
        self._summary = summary or {
            "total_profit_loss": 0.0,
            "total_evaluation": 0.0,
            "ante_eval_amount": 0.0,
        }
        self._budget = budget
        self._prev = prev_snapshot

    def _maybe_fail(self, name: str) -> None:
        if self._fail == name:
            raise RuntimeError(f"simulated {name} failure")

    def get_summary(self) -> dict[str, float]:
        self._maybe_fail("get_summary")
        return dict(self._summary)

    def get_budget(self, bot_id: str) -> StubBudget | None:
        self._maybe_fail("get_budget")
        return None if self._budget is None else StubBudget(self._budget)

    async def get_prev_day_snapshot(self, before_date: str) -> dict[str, Any] | None:
        self._maybe_fail("get_prev_day_snapshot")
        return self._prev

    def get_synced_price(self, symbol: str) -> tuple[float | None, str | None]:
        """동기화 시세는 없다(#3102)."""
        return None, SYNCED_PRICE_MISSING

    def get_last_sync_coverage(self) -> None:
        """성공한 동기화는 없다(#3102)."""
        return None


class StubTreasuryManager:
    """`RuleEngineManager`에 넘기는 가짜 TreasuryManager. 계좌마다 같은 가짜를 준다."""

    def __init__(self, treasury: StubTreasury | None = None) -> None:
        self._treasury = treasury or StubTreasury()

    def get(self, account_id: str) -> StubTreasury:
        return self._treasury
