"""매매 시뮬레이션 — trades, position_history, positions 일괄 생성.

성과 계산 로직(performance.py, feedback.py)과 정합성을 보장한다:
- position_history: sell 시 pnl 기록 (price, quantity로 JOIN)
- trades: status='filled', timestamp 필수
- equity curve: buy=-qty*price, sell=+qty*price (commission 차감)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time

from tests.fixtures.seed.generators.price import SYMBOL_NAMES, DailyPrice

# 수수료/세금 (한국 주식)
COMMISSION_RATE = 0.00015  # 매수·매도 수수료율
SELL_TAX_RATE = 0.0023  # 증권거래세


@dataclass(frozen=True)
class TradeRecord:
    """거래 기록."""

    trade_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    side: str  # 'buy' | 'sell'
    quantity: float
    price: float
    status: str  # 'filled'
    commission: float
    timestamp: str  # ISO 8601
    order_type: str = ""
    reason: str = ""


@dataclass(frozen=True)
class PositionHistoryRecord:
    """포지션 변동 이력."""

    bot_id: str
    symbol: str
    action: str  # 'buy' | 'sell'
    quantity: float
    price: float
    pnl: float  # sell 시 실현 손익
    timestamp: str


@dataclass(frozen=True)
class PositionRecord:
    """최종 포지션 스냅샷."""

    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float
    updated_at: str


@dataclass
class TradingProfile:
    """봇의 매매 성향."""

    avg_trades_per_week: float  # 주당 평균 매도 횟수
    win_rate_target: float  # 목표 승률 (0.0~1.0)
    avg_hold_days: int  # 평균 보유 기간
    max_position_count: int  # 동시 보유 종목 수
    symbols: list[str]  # 거래 대상 종목
    position_size_pct: float = 0.25  # 1회 매수 비중 (예산 대비)


@dataclass
class TradingResult:
    """매매 시뮬레이션 결과."""

    trades: list[TradeRecord] = field(default_factory=list)
    position_history: list[PositionHistoryRecord] = field(default_factory=list)
    final_positions: list[PositionRecord] = field(default_factory=list)
    total_spent: float = 0.0
    total_returned: float = 0.0
    total_commission: float = 0.0


@dataclass
class _OpenPosition:
    """시뮬레이션 중 보유 포지션 상태."""

    symbol: str
    quantity: float
    avg_entry_price: float
    buy_date: date
    realized_pnl: float = 0.0


def _make_trade_id(prefix: str, seq: int) -> str:
    """시나리오 내 고유 trade_id 생성."""
    return f"{prefix}-{seq:04d}"


def _make_timestamp(d: date, hour: int = 10, minute: int = 0) -> str:
    """거래일 + 시각 → ISO 8601 문자열."""
    return datetime.combine(d, time(hour, minute)).strftime("%Y-%m-%d %H:%M:%S")


def simulate_trading(
    profile: TradingProfile,
    prices: dict[str, list[DailyPrice]],
    bot_id: str,
    strategy_id: str,
    budget: float,
    seed: int = 42,
) -> TradingResult:
    """매매 시뮬레이션을 수행하고 모든 관련 레코드를 생성한다.

    Args:
        profile: 매매 성향 설정.
        prices: symbol → 일봉 리스트 (모든 종목이 같은 날짜 범위).
        bot_id: 봇 ID.
        strategy_id: 전략 ID.
        budget: 배정 예산.
        seed: 랜덤 시드.

    Returns:
        TradingResult: trades, position_history, final_positions 등.
    """
    rng = random.Random(seed)

    # 모든 종목의 공통 거래일 추출
    first_symbol = profile.symbols[0]
    trading_days = [dp.date for dp in prices[first_symbol]]

    # 가격 인덱스: {symbol: {date: DailyPrice}}
    price_index: dict[str, dict[date, DailyPrice]] = {}
    for sym in profile.symbols:
        price_index[sym] = {dp.date: dp for dp in prices[sym]}

    # 시뮬레이션 상태
    open_positions: dict[str, _OpenPosition] = {}
    available_cash = budget
    result = TradingResult()
    trade_seq = 0
    trade_prefix = f"t-{bot_id[:8]}"

    # 매매 빈도 → 일별 매도 확률
    sell_prob_per_day = profile.avg_trades_per_week / 5.0

    for day in trading_days:
        # ── 매도 판단 ──
        symbols_to_sell = []
        for sym, pos in list(open_positions.items()):
            hold_days = (day - pos.buy_date).days
            if hold_days < 1:
                continue

            dp = price_index[sym].get(day)
            if dp is None:
                continue

            # 보유일 초과 시 매도 확률 증가
            base_sell_prob = sell_prob_per_day * (hold_days / profile.avg_hold_days)
            sell_prob = min(base_sell_prob, 0.9)

            if rng.random() < sell_prob:
                symbols_to_sell.append(sym)

        for sym in symbols_to_sell:
            pos = open_positions[sym]
            dp = price_index[sym][day]

            # 매도가: 당일 종가 근처
            sell_price = dp.close
            sell_amount = sell_price * pos.quantity
            commission = round(sell_amount * COMMISSION_RATE)
            tax = round(sell_amount * SELL_TAX_RATE)
            pnl = round(
                (sell_price - pos.avg_entry_price) * pos.quantity - commission - tax
            )

            # 승률 조절: win_rate_target에 맞춰 손절/익절 여부를 확률적으로 결정
            if pnl > 0 and rng.random() > profile.win_rate_target:
                # 이익인데 목표 승률 초과 시 일부를 손실로 전환 (매도 스킵)
                continue
            if pnl < 0 and rng.random() < profile.win_rate_target * 0.3:
                # 손실인데 승률 부족 시 일부를 보유 연장 (매도 스킵)
                continue

            trade_seq += 1
            ts = _make_timestamp(day, rng.randint(10, 15), rng.randint(0, 59))

            result.trades.append(
                TradeRecord(
                    trade_id=_make_trade_id(trade_prefix, trade_seq),
                    bot_id=bot_id,
                    strategy_id=strategy_id,
                    symbol=sym,
                    side="sell",
                    quantity=pos.quantity,
                    price=sell_price,
                    status="filled",
                    commission=commission,
                    timestamp=ts,
                    reason=f"{SYMBOL_NAMES.get(sym, sym)} 매도",
                )
            )
            result.position_history.append(
                PositionHistoryRecord(
                    bot_id=bot_id,
                    symbol=sym,
                    action="sell",
                    quantity=pos.quantity,
                    price=sell_price,
                    pnl=pnl,
                    timestamp=ts,
                )
            )

            pos.realized_pnl += pnl
            available_cash += sell_amount - commission - tax
            result.total_returned += sell_amount - commission - tax
            result.total_commission += commission + tax

            del open_positions[sym]

        # ── 매수 판단 ──
        if len(open_positions) < profile.max_position_count:
            # 매수 가능 종목: 미보유 종목 중 선택
            available_symbols = [s for s in profile.symbols if s not in open_positions]
            if available_symbols:
                # 매수 확률: 빈 슬롯 비율에 비례
                buy_prob = sell_prob_per_day * 1.2
                if rng.random() < buy_prob:
                    sym = rng.choice(available_symbols)
                    dp = price_index[sym].get(day)
                    if dp is not None:
                        buy_price = dp.close
                        # 예산의 position_size_pct만큼 매수
                        target_amount = budget * profile.position_size_pct
                        max_affordable = available_cash * 0.95  # 5% 여유
                        invest_amount = min(target_amount, max_affordable)

                        if invest_amount > buy_price:
                            quantity = int(invest_amount / buy_price)
                            if quantity > 0:
                                actual_amount = buy_price * quantity
                                commission = round(actual_amount * COMMISSION_RATE)

                                trade_seq += 1
                                ts = _make_timestamp(
                                    day, rng.randint(9, 11), rng.randint(0, 59)
                                )

                                result.trades.append(
                                    TradeRecord(
                                        trade_id=_make_trade_id(
                                            trade_prefix, trade_seq
                                        ),
                                        bot_id=bot_id,
                                        strategy_id=strategy_id,
                                        symbol=sym,
                                        side="buy",
                                        quantity=quantity,
                                        price=buy_price,
                                        status="filled",
                                        commission=commission,
                                        timestamp=ts,
                                        reason=f"{SYMBOL_NAMES.get(sym, sym)} 매수",
                                    )
                                )
                                result.position_history.append(
                                    PositionHistoryRecord(
                                        bot_id=bot_id,
                                        symbol=sym,
                                        action="buy",
                                        quantity=quantity,
                                        price=buy_price,
                                        pnl=0.0,
                                        timestamp=ts,
                                    )
                                )

                                open_positions[sym] = _OpenPosition(
                                    symbol=sym,
                                    quantity=quantity,
                                    avg_entry_price=buy_price,
                                    buy_date=day,
                                )

                                available_cash -= actual_amount + commission
                                result.total_spent += actual_amount + commission
                                result.total_commission += commission

    # ── 최종 포지션 스냅샷 ──
    last_day = trading_days[-1]
    for sym, pos in open_positions.items():
        dp = price_index[sym].get(last_day)
        updated_at = _make_timestamp(last_day, 15, 30)
        result.final_positions.append(
            PositionRecord(
                bot_id=bot_id,
                symbol=sym,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                realized_pnl=pos.realized_pnl,
                updated_at=updated_at,
            )
        )

    # 청산된 종목도 realized_pnl > 0이면 기록 (quantity=0)
    traded_symbols = {t.symbol for t in result.trades}
    open_symbols = {p.symbol for p in result.final_positions}
    for sym in traded_symbols - open_symbols:
        # 해당 종목의 총 실현 손익
        total_pnl = sum(
            ph.pnl
            for ph in result.position_history
            if ph.symbol == sym and ph.action == "sell"
        )
        if total_pnl != 0:
            result.final_positions.append(
                PositionRecord(
                    bot_id=bot_id,
                    symbol=sym,
                    quantity=0,
                    avg_entry_price=0.0,
                    realized_pnl=total_pnl,
                    updated_at=_make_timestamp(last_day, 15, 30),
                )
            )

    return result
