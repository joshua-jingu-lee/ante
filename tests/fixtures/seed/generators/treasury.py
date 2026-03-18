"""자금 흐름 계산 — treasury_state, bot_budgets, treasury_transactions 생성.

매매 결과(TradingResult)를 기반으로 정합성 있는 자금 데이터를 산출한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.fixtures.seed.generators.price import SYMBOL_NAMES
from tests.fixtures.seed.generators.trading import TradingResult


@dataclass(frozen=True)
class BudgetRecord:
    """봇별 예산 스냅샷."""

    bot_id: str
    allocated: float
    available: float
    reserved: float
    spent: float
    returned: float


@dataclass(frozen=True)
class TransactionRecord:
    """자금 변동 이력."""

    bot_id: str
    transaction_type: str  # 'allocate' | 'trade' | 'return'
    amount: float
    description: str
    created_at: str


@dataclass
class TreasurySnapshot:
    """전역 자금 상태."""

    account_balance: float = 0.0
    allocated: float = 0.0
    unallocated: float = 0.0
    budgets: list[BudgetRecord] = field(default_factory=list)
    transactions: list[TransactionRecord] = field(default_factory=list)


def calculate_treasury(
    initial_balance: float,
    bot_configs: dict[str, float],
    bot_results: dict[str, TradingResult],
) -> TreasurySnapshot:
    """모든 봇의 매매 결과를 합산하여 자금 상태를 산출한다.

    Args:
        initial_balance: 계좌 총 잔고.
        bot_configs: {bot_id: allocated_budget} 배정 예산.
        bot_results: {bot_id: TradingResult} 매매 결과.

    Returns:
        TreasurySnapshot: treasury_state, bot_budgets, transactions.
    """
    snapshot = TreasurySnapshot(account_balance=initial_balance)
    total_allocated = 0.0

    for bot_id, allocated in bot_configs.items():
        total_allocated += allocated
        result = bot_results.get(bot_id)

        # 할당 트랜잭션
        if result and result.trades:
            first_trade_ts = result.trades[0].timestamp
            alloc_ts = first_trade_ts[:10] + " 09:00:00"
        else:
            alloc_ts = "2026-01-20 09:00:00"

        snapshot.transactions.append(
            TransactionRecord(
                bot_id=bot_id,
                transaction_type="allocate",
                amount=allocated,
                description="초기 할당",
                created_at=alloc_ts,
            )
        )

        if result is None:
            # 거래 없는 봇
            snapshot.budgets.append(
                BudgetRecord(
                    bot_id=bot_id,
                    allocated=allocated,
                    available=allocated,
                    reserved=0.0,
                    spent=0.0,
                    returned=0.0,
                )
            )
            continue

        # 거래별 트랜잭션 생성
        for trade in result.trades:
            sym_name = SYMBOL_NAMES.get(trade.symbol, trade.symbol)
            qty = int(trade.quantity)
            if trade.side == "buy":
                amount = -(trade.price * trade.quantity + trade.commission)
                desc = f"{sym_name} {qty}주 매수"
            else:
                amount = trade.price * trade.quantity - trade.commission
                desc = f"{sym_name} {qty}주 매도"

            snapshot.transactions.append(
                TransactionRecord(
                    bot_id=bot_id,
                    transaction_type="trade",
                    amount=round(amount),
                    description=desc,
                    created_at=trade.timestamp,
                )
            )

        # 예산 계산
        spent = result.total_spent
        returned = result.total_returned
        # 현재 보유 포지션의 매입 금액
        holding_value = sum(
            p.quantity * p.avg_entry_price
            for p in result.final_positions
            if p.quantity > 0
        )
        available = allocated - spent + returned - holding_value

        snapshot.budgets.append(
            BudgetRecord(
                bot_id=bot_id,
                allocated=round(allocated),
                available=round(max(available, 0)),
                reserved=0.0,
                spent=round(spent),
                returned=round(returned),
            )
        )

    snapshot.allocated = round(total_allocated)
    snapshot.unallocated = round(initial_balance - total_allocated)

    # 트랜잭션을 시간순 정렬
    snapshot.transactions.sort(key=lambda t: t.created_at)

    return snapshot
