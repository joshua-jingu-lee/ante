"""RuleEngine 미실현 손익 account_id 스코핑 회귀 테스트. Refs #2140.

`RuleEngine`은 계좌별 인스턴스(`self._account_id`)다. `_calculate_bot_unrealized_pnl`
이 `TradeService.get_positions`를 `account_id` 없이 호출하면, 같은 `bot_id`를
공유하는 타 계좌 포지션이 `RuleContext.unrealized_pnl`에 혼입되어
`UnrealizedLossLimitRule`이 잘못 reject/pass 한다.

이 테스트는 (a) 미실현 손익 합산이 자기 계좌 포지션만 사용하는지, (b)
`get_positions`가 `account_id=<엔진 계좌>` 로 호출되는지 회귀 잠금한다.
#2138(PR#2162) account_id 스코핑 동형 선례.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ante.eventbus import EventBus
from ante.rule import RuleEngine


@dataclass
class FakePosition:
    """미실현 손익 계산에 필요한 최소 PositionSnapshot 형태."""

    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0


class FakeTradeService:
    """account_id로 포지션을 필터링하는 가짜 TradeService.

    `get_positions`는 실제 `TradeService.get_positions`와 동일하게
    `bot_id` positional + keyword-only `account_id`(기본 None)를 받으며,
    호출 인자를 `calls`에 캡처한다. `account_id`가 주어지면 해당 계좌
    포지션만 반환하여(미스코핑이면 타 계좌 혼입), 엔진의 스코핑 누락을
    드러낸다.
    """

    def __init__(self, positions_by_account: dict[str, list[FakePosition]]):
        self._positions_by_account = positions_by_account
        self.calls: list[dict[str, object]] = []

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[FakePosition]:
        self.calls.append(
            {
                "bot_id": bot_id,
                "include_closed": include_closed,
                "account_id": account_id,
            }
        )
        if account_id is None:
            # 미스코핑 시나리오: 모든 계좌 포지션을 합쳐 반환(타 계좌 혼입).
            merged: list[FakePosition] = []
            for positions in self._positions_by_account.values():
                merged.extend(positions)
            return [p for p in merged if p.bot_id == bot_id]
        scoped = self._positions_by_account.get(account_id, [])
        return [p for p in scoped if p.bot_id == bot_id]


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def trade_service() -> FakeTradeService:
    """동일 bot_id를 공유하는 두 계좌(acc-a, acc-b) 포지션.

    acc-a: 005930 10주, 평단 60000 (current 59995 → -50.0)
    acc-b: 005930 100주, 평단 60000 (current 59995 → -500.0)
    혼입 시 합계 -550.0, 자기 계좌(acc-a)만이면 -50.0.
    """
    return FakeTradeService(
        {
            "acc-a": [
                FakePosition(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=10.0,
                    avg_entry_price=60000.0,
                ),
            ],
            "acc-b": [
                FakePosition(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=60000.0,
                ),
            ],
        }
    )


@pytest.fixture
def engine(eventbus: EventBus, trade_service: FakeTradeService) -> RuleEngine:
    return RuleEngine(
        eventbus=eventbus,
        account_id="acc-a",
        trade_service=trade_service,
    )


class TestUnrealizedPnlAccountScope:
    @pytest.mark.asyncio
    async def test_unrealized_pnl_sums_only_own_account(
        self, engine: RuleEngine
    ) -> None:
        """미실현 손익은 엔진 계좌(acc-a) 포지션만 합산한다(타 계좌 혼입 금지)."""
        result = await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=59995.0,  # 평단 60000 대비 -5
            order_symbol="005930",
        )
        # acc-a만: (59995 - 60000) * 10 = -50.0
        # acc-b 혼입 시: 추가 (59995 - 60000) * 100 = -500.0 → 합계 -550.0
        assert result == pytest.approx(-50.0)
        assert result != pytest.approx(-550.0)

    @pytest.mark.asyncio
    async def test_get_positions_called_with_engine_account_id(
        self, engine: RuleEngine, trade_service: FakeTradeService
    ) -> None:
        """get_positions가 엔진 계좌(acc-a)로 스코핑되어 호출된다."""
        await engine._calculate_bot_unrealized_pnl(
            bot_id="bot1",
            current_price=59995.0,
            order_symbol="005930",
        )
        assert len(trade_service.calls) == 1
        call = trade_service.calls[0]
        assert call["bot_id"] == "bot1"
        assert call["account_id"] == "acc-a"
