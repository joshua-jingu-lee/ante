"""시나리오별 시드 SQL 생성기.

Usage:
    python -m tests.fixtures.seed.generate_scenario --all
    python -m tests.fixtures.seed.generate_scenario --scenario strategy-browse
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from tests.fixtures.seed.generators.price import generate_multi_stock_prices
from tests.fixtures.seed.generators.trading import (
    TradingProfile,
    TradingResult,
    simulate_trading,
)
from tests.fixtures.seed.generators.treasury import calculate_treasury
from tests.fixtures.seed.generators.writer import (
    BotDef,
    EventLogDef,
    MemberDef,
    StrategyDef,
    write_scenario_sql,
)

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# 시나리오별 고정 시드
SCENARIO_SEEDS: dict[str, int] = {
    "strategy-browse": 42,
    "bot-management": 123,
    "treasury": 456,
    "login-dashboard": 789,
}

# 공통 멤버
DEFAULT_MEMBERS: list[MemberDef] = [
    MemberDef(
        member_id="strategy-dev-01",
        member_type="agent",
        role="default",
        org="strategy-lab",
        name="전략 리서치 1호",
        emoji="\U0001f98a",
        status="active",
        scopes=["strategy:write", "data:read", "backtest:run", "report:write"],
        created_at="datetime('now', '-60 days')",
    ),
    MemberDef(
        member_id="strategy-dev-02",
        member_type="agent",
        role="default",
        org="strategy-lab",
        name="전략 리서치 2호",
        emoji="\U0001f43c",
        status="active",
        scopes=["strategy:write", "data:read", "backtest:run"],
        created_at="datetime('now', '-45 days')",
    ),
]


def _days_ago(n: int) -> str:
    """n일 전 날짜 문자열."""
    return (date.today() - timedelta(days=n)).isoformat()


def _datetime_ago(n: int, hour: int = 9, minute: int = 0) -> str:
    """n일 전 날짜+시각 문자열."""
    d = date.today() - timedelta(days=n)
    return f"{d.isoformat()} {hour:02d}:{minute:02d}:00"


def _make_event_logs(bot_id: str, trades: list, bot_status: str) -> list[EventLogDef]:
    """거래 기반 이벤트 로그 생성."""
    events: list[EventLogDef] = []
    seq = 0
    prefix = bot_id[:8]

    # 거래 기반 step.success 이벤트 (매 5건마다 1개)
    for i, t in enumerate(trades):
        if i % 5 == 0:
            seq += 1
            events.append(
                EventLogDef(
                    event_id=f"ev-{prefix}-{seq:03d}",
                    event_type="bot.step.success",
                    timestamp=t.timestamp,
                    payload={"bot_id": bot_id, "message": "매매 사이클 완료"},
                )
            )

    # 봇 상태별 추가 이벤트
    if bot_status == "stopped":
        seq += 1
        events.append(
            EventLogDef(
                event_id=f"ev-{prefix}-{seq:03d}",
                event_type="bot.stopped",
                timestamp=_datetime_ago(1, 15, 0),
                payload={"bot_id": bot_id, "message": "Bot 중지됨 — 사용자 요청"},
            )
        )
    elif bot_status == "error":
        for msg in [
            "전략 로드 실패: ModuleNotFoundError",
            "전략 초기화 실패: invalid config",
        ]:
            seq += 1
            events.append(
                EventLogDef(
                    event_id=f"ev-{prefix}-{seq:03d}",
                    event_type="bot.step.error",
                    timestamp=_datetime_ago(3, 10, 0),
                    payload={"bot_id": bot_id, "message": msg},
                )
            )

    return events


# ─────────────────────────────────────────────────────────────
# 시나리오 정의
# ─────────────────────────────────────────────────────────────


def generate_strategy_browse() -> None:
    """전략 탐색 시나리오: 수익/보합/손실 전략 혼합."""
    seed = SCENARIO_SEEDS["strategy-browse"]
    symbols_a = ["005930", "000660", "035420"]
    symbols_b = ["035720", "005380"]
    symbols_c = ["005930", "035420", "035720"]
    start = date.today() - timedelta(days=90)

    prices_a = generate_multi_stock_prices(
        symbols_a, days=60, start_date=start, seed=seed
    )
    prices_b = generate_multi_stock_prices(
        symbols_b, days=60, start_date=start, seed=seed + 100
    )
    prices_c = generate_multi_stock_prices(
        symbols_c, days=45, start_date=start, seed=seed + 200
    )

    strategies = [
        StrategyDef(
            "sma-cross-01",
            "SMA 크로스",
            "1.0.0",
            "strategies/sma_cross.py",
            "registered",
            _datetime_ago(60),
            "SMA 5/20 크로스오버 전략",
            "strategy-dev-01",
        ),
        StrategyDef(
            "momentum-v2",
            "모멘텀 돌파 전략 v2",
            "2.1.0",
            "strategies/momentum_v2.py",
            "active",
            _datetime_ago(45),
            "20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도",
            "strategy-dev-01",
        ),
        StrategyDef(
            "rsi-reversal-01",
            "RSI 반등",
            "1.0.0",
            "strategies/rsi_reversal.py",
            "active",
            _datetime_ago(30),
            "RSI 과매도 구간 반등 매수 전략",
            "strategy-dev-01",
        ),
        StrategyDef(
            "mean-revert-01",
            "평균회귀",
            "1.2.0",
            "strategies/mean_revert.py",
            "inactive",
            _datetime_ago(60),
            "볼린저밴드 기반 평균회귀 전략",
            "strategy-dev-02",
        ),
    ]

    bots = [
        BotDef(
            "bot-momentum-browse",
            "모멘텀 봇",
            "momentum-v2",
            "live",
            "running",
            _datetime_ago(45),
            symbols=symbols_a,
        ),
        BotDef(
            "bot-rsi-browse",
            "RSI 봇",
            "rsi-reversal-01",
            "paper",
            "running",
            _datetime_ago(25),
            symbols=symbols_b,
        ),
    ]

    results: dict[str, TradingResult] = {}
    results["bot-momentum-browse"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=3,
            win_rate_target=0.65,
            avg_hold_days=5,
            max_position_count=3,
            symbols=symbols_a,
        ),
        prices=prices_a,
        bot_id="bot-momentum-browse",
        strategy_id="momentum-v2",
        budget=15_000_000,
        seed=seed,
    )
    results["bot-rsi-browse"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.50,
            avg_hold_days=7,
            max_position_count=2,
            symbols=symbols_b,
        ),
        prices=prices_b,
        bot_id="bot-rsi-browse",
        strategy_id="rsi-reversal-01",
        budget=5_000_000,
        seed=seed + 50,
    )

    # 과거 손실 전략 (mean-revert-01) — 별도 봇 없이 거래만 삽입
    mean_result = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.35,
            avg_hold_days=4,
            max_position_count=2,
            symbols=symbols_c,
        ),
        prices=prices_c,
        bot_id="bot-mean-old",
        strategy_id="mean-revert-01",
        budget=8_000_000,
        seed=seed + 300,
    )
    results["bot-mean-old"] = mean_result

    treasury = calculate_treasury(
        initial_balance=50_000_000,
        bot_configs={"bot-momentum-browse": 15_000_000, "bot-rsi-browse": 5_000_000},
        bot_results=results,
    )

    event_logs = _make_event_logs(
        "bot-momentum-browse", results["bot-momentum-browse"].trades, "running"
    )
    event_logs += _make_event_logs(
        "bot-rsi-browse", results["bot-rsi-browse"].trades, "running"
    )

    write_scenario_sql(
        path=SCENARIOS_DIR / "strategy-browse.sql",
        scenario_name="strategy-browse",
        strategies=strategies,
        bots=bots,
        trading_results=results,
        treasury=treasury,
        members=DEFAULT_MEMBERS,
        event_logs=event_logs,
        seed=seed,
    )

    _print_summary("strategy-browse", results)


def generate_bot_management() -> None:
    """봇 관리 시나리오: 4봇 (created/running/stopped/error)."""
    seed = SCENARIO_SEEDS["bot-management"]
    symbols_momentum = ["005930", "035420", "035720"]
    symbols_mean = ["005930", "035420", "000660"]
    start = date.today() - timedelta(days=90)

    prices_momentum = generate_multi_stock_prices(
        symbols_momentum, days=45, start_date=start, seed=seed
    )
    prices_mean = generate_multi_stock_prices(
        symbols_mean, days=30, start_date=start, seed=seed + 100
    )

    strategies = [
        StrategyDef(
            "sma-cross",
            "SMA 크로스",
            "1.0.0",
            "strategies/sma_cross.py",
            "active",
            _datetime_ago(45),
            "SMA 5/20 크로스오버 전략",
            "strategy-dev-01",
        ),
        StrategyDef(
            "momentum-v2",
            "모멘텀 돌파 전략 v2",
            "2.1.0",
            "strategies/momentum_v2.py",
            "active",
            _datetime_ago(60),
            "20일 고점 돌파 시 매수, ATR 기반 트레일링 스탑으로 매도",
            "strategy-dev-01",
        ),
        StrategyDef(
            "mean-revert",
            "평균회귀",
            "1.2.0",
            "strategies/mean_revert.py",
            "active",
            _datetime_ago(45),
            "볼린저밴드 기반 평균회귀 전략",
            "strategy-dev-02",
        ),
        StrategyDef(
            "broken-strategy",
            "Broken Strategy",
            "0.1.0",
            "strategies/broken.py",
            "registered",
            _datetime_ago(14),
            "오류 테스트용 전략",
            "seed",
        ),
    ]

    bots = [
        BotDef(
            "bot-sma-01",
            "SMA 크로스 봇",
            "sma-cross",
            "paper",
            "created",
            _datetime_ago(7),
            symbols=["005930"],
        ),
        BotDef(
            "bot-momentum-01",
            "모멘텀 추세 봇",
            "momentum-v2",
            "live",
            "running",
            _datetime_ago(45),
            symbols=symbols_momentum,
        ),
        BotDef(
            "bot-mean-01",
            "평균회귀 실전 봇",
            "mean-revert",
            "live",
            "stopped",
            _datetime_ago(30),
            symbols=symbols_mean,
        ),
        BotDef(
            "bot-err-01",
            "오류 테스트 봇",
            "broken-strategy",
            "paper",
            "error",
            _datetime_ago(10),
        ),
    ]

    results: dict[str, TradingResult] = {}
    results["bot-momentum-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=3,
            win_rate_target=0.55,
            avg_hold_days=5,
            max_position_count=3,
            symbols=symbols_momentum,
        ),
        prices=prices_momentum,
        bot_id="bot-momentum-01",
        strategy_id="momentum-v2",
        budget=15_000_000,
        seed=seed,
    )
    results["bot-mean-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.40,
            avg_hold_days=6,
            max_position_count=3,
            symbols=symbols_mean,
        ),
        prices=prices_mean,
        bot_id="bot-mean-01",
        strategy_id="mean-revert",
        budget=3_000_000,
        seed=seed + 50,
    )

    treasury = calculate_treasury(
        initial_balance=100_000_000,
        bot_configs={
            "bot-sma-01": 1_000_000,
            "bot-momentum-01": 15_000_000,
            "bot-mean-01": 3_000_000,
            "bot-err-01": 500_000,
        },
        bot_results=results,
    )

    event_logs = _make_event_logs(
        "bot-momentum-01", results["bot-momentum-01"].trades, "running"
    )
    event_logs += _make_event_logs(
        "bot-mean-01", results["bot-mean-01"].trades, "stopped"
    )
    event_logs += _make_event_logs("bot-err-01", [], "error")

    write_scenario_sql(
        path=SCENARIOS_DIR / "bot-management.sql",
        scenario_name="bot-management",
        strategies=strategies,
        bots=bots,
        trading_results=results,
        treasury=treasury,
        members=DEFAULT_MEMBERS,
        event_logs=event_logs,
        seed=seed,
    )

    _print_summary("bot-management", results)


def generate_treasury() -> None:
    """자금 관리 시나리오: 3봇, 다양한 예산 규모."""
    seed = SCENARIO_SEEDS["treasury"]
    symbols_m = ["005930", "035420"]
    symbols_macd = ["005930", "000660"]
    symbols_rsi = ["035720", "005380"]
    start = date.today() - timedelta(days=90)

    prices_m = generate_multi_stock_prices(
        symbols_m, days=60, start_date=start, seed=seed
    )
    prices_macd = generate_multi_stock_prices(
        symbols_macd, days=45, start_date=start, seed=seed + 100
    )
    prices_rsi = generate_multi_stock_prices(
        symbols_rsi, days=45, start_date=start, seed=seed + 200
    )

    strategies = [
        StrategyDef(
            "momentum-v2",
            "모멘텀 돌파 전략 v2",
            "2.1.0",
            "strategies/momentum_v2.py",
            "active",
            _datetime_ago(60),
            "20일 고점 돌파 시 매수",
            "strategy-dev-01",
        ),
        StrategyDef(
            "macd-cross",
            "MACD 크로스",
            "1.0.0",
            "strategies/macd_cross.py",
            "active",
            _datetime_ago(30),
            "MACD 골든/데드크로스 전략",
            "strategy-dev-01",
        ),
        StrategyDef(
            "rsi-reversal",
            "RSI 반등",
            "1.0.0",
            "strategies/rsi_reversal.py",
            "active",
            _datetime_ago(45),
            "RSI 과매도 반등 전략",
            "strategy-dev-02",
        ),
    ]

    bots = [
        BotDef(
            "bot-momentum-01",
            "모멘텀 봇",
            "momentum-v2",
            "live",
            "running",
            _datetime_ago(50),
            symbols=symbols_m,
        ),
        BotDef(
            "bot-macd-cross",
            "MACD 봇",
            "macd-cross",
            "live",
            "running",
            _datetime_ago(30),
            symbols=symbols_macd,
        ),
        BotDef(
            "bot-rsi-01",
            "RSI 봇",
            "rsi-reversal",
            "live",
            "stopped",
            _datetime_ago(40),
            symbols=symbols_rsi,
        ),
    ]

    results: dict[str, TradingResult] = {}
    results["bot-momentum-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=3,
            win_rate_target=0.60,
            avg_hold_days=5,
            max_position_count=2,
            symbols=symbols_m,
        ),
        prices=prices_m,
        bot_id="bot-momentum-01",
        strategy_id="momentum-v2",
        budget=15_000_000,
        seed=seed,
    )
    results["bot-macd-cross"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.50,
            avg_hold_days=6,
            max_position_count=2,
            symbols=symbols_macd,
        ),
        prices=prices_macd,
        bot_id="bot-macd-cross",
        strategy_id="macd-cross",
        budget=10_000_000,
        seed=seed + 50,
    )
    results["bot-rsi-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.45,
            avg_hold_days=7,
            max_position_count=2,
            symbols=symbols_rsi,
        ),
        prices=prices_rsi,
        bot_id="bot-rsi-01",
        strategy_id="rsi-reversal",
        budget=10_000_000,
        seed=seed + 100,
    )

    treasury = calculate_treasury(
        initial_balance=42_000_000,
        bot_configs={
            "bot-momentum-01": 15_000_000,
            "bot-macd-cross": 10_000_000,
            "bot-rsi-01": 10_000_000,
        },
        bot_results=results,
    )

    event_logs = _make_event_logs(
        "bot-momentum-01", results["bot-momentum-01"].trades, "running"
    )
    event_logs += _make_event_logs(
        "bot-macd-cross", results["bot-macd-cross"].trades, "running"
    )
    event_logs += _make_event_logs(
        "bot-rsi-01", results["bot-rsi-01"].trades, "stopped"
    )

    write_scenario_sql(
        path=SCENARIOS_DIR / "treasury.sql",
        scenario_name="treasury",
        strategies=strategies,
        bots=bots,
        trading_results=results,
        treasury=treasury,
        members=DEFAULT_MEMBERS,
        event_logs=event_logs,
        seed=seed,
    )

    _print_summary("treasury", results)


def generate_login_dashboard() -> None:
    """대시보드 메인 시나리오: 포트폴리오 차트용 equity curve."""
    seed = SCENARIO_SEEDS["login-dashboard"]
    symbols_a = ["005930", "000660", "035420"]
    symbols_b = ["035720", "005380"]
    start = date.today() - timedelta(days=100)

    prices_a = generate_multi_stock_prices(
        symbols_a, days=60, start_date=start, seed=seed
    )
    prices_b = generate_multi_stock_prices(
        symbols_b, days=60, start_date=start, seed=seed + 100
    )

    strategies = [
        StrategyDef(
            "momentum-v2",
            "모멘텀 돌파 전략 v2",
            "2.1.0",
            "strategies/momentum_v2.py",
            "active",
            _datetime_ago(60),
            "20일 고점 돌파 시 매수",
            "strategy-dev-01",
        ),
        StrategyDef(
            "rsi-reversal",
            "RSI 반등",
            "1.0.0",
            "strategies/rsi_reversal.py",
            "active",
            _datetime_ago(45),
            "RSI 과매도 반등 전략",
            "strategy-dev-02",
        ),
    ]

    bots = [
        BotDef(
            "bot-momentum-01",
            "모멘텀 봇",
            "momentum-v2",
            "live",
            "running",
            _datetime_ago(55),
            symbols=symbols_a,
        ),
        BotDef(
            "bot-rsi-01",
            "RSI 봇",
            "rsi-reversal",
            "live",
            "running",
            _datetime_ago(50),
            symbols=symbols_b,
        ),
    ]

    results: dict[str, TradingResult] = {}
    results["bot-momentum-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=3,
            win_rate_target=0.60,
            avg_hold_days=5,
            max_position_count=3,
            symbols=symbols_a,
        ),
        prices=prices_a,
        bot_id="bot-momentum-01",
        strategy_id="momentum-v2",
        budget=25_000_000,
        seed=seed,
    )
    results["bot-rsi-01"] = simulate_trading(
        profile=TradingProfile(
            avg_trades_per_week=2,
            win_rate_target=0.55,
            avg_hold_days=7,
            max_position_count=2,
            symbols=symbols_b,
        ),
        prices=prices_b,
        bot_id="bot-rsi-01",
        strategy_id="rsi-reversal",
        budget=15_000_000,
        seed=seed + 50,
    )

    treasury = calculate_treasury(
        initial_balance=100_000_000,
        bot_configs={"bot-momentum-01": 25_000_000, "bot-rsi-01": 15_000_000},
        bot_results=results,
    )

    # 대시보드용 결재 대기 건
    extra_members = list(DEFAULT_MEMBERS) + [
        MemberDef(
            member_id="treasury-agent",
            member_type="agent",
            role="default",
            org="treasury",
            name="자금 관리",
            emoji="\U0001f433",
            status="active",
            scopes=["approval:create", "data:read"],
            created_at="datetime('now', '-30 days')",
        ),
    ]

    write_scenario_sql(
        path=SCENARIOS_DIR / "login-dashboard.sql",
        scenario_name="login-dashboard",
        strategies=strategies,
        bots=bots,
        trading_results=results,
        treasury=treasury,
        members=extra_members,
        seed=seed,
    )

    # 결재 대기 건은 별도 append (write_scenario_sql에 없는 테이블)
    approval_sql = (
        "\n-- ── 승인 대기 ──────────────────────────────────\n"
        "INSERT INTO approvals "
        "(id, type, status, requester, title, body,"
        " params, created_at, expires_at)\n"
        "VALUES (\n"
        "    'approval-login-01', 'strategy_adopt', 'pending',\n"
        "    'strategy-dev-01',\n"
        "    '모멘텀 돌파 전략 v2 채택 요청',\n"
        "    '백테스트 결과 양호하여 채택 요청합니다.',\n"
        '    \'{"strategy_id": "momentum-v2"}\',\n'
        "    datetime('now', '-1 hours'),\n"
        "    datetime('now', '+3 days')\n"
        ");\n\n"
        "INSERT INTO approvals "
        "(id, type, status, requester, title, body,"
        " params, created_at, expires_at)\n"
        "VALUES (\n"
        "    'approval-login-02', 'budget_change', 'pending',\n"
        "    'treasury-agent',\n"
        "    'bot-momentum-01 예산 증액 요청',\n"
        "    '운용 성과 양호하여 예산 증액 요청합니다.',\n"
        '    \'{"bot_id": "bot-momentum-01", "amount": 25000000}\',\n'
        "    datetime('now', '-2 hours'),\n"
        "    datetime('now', '+3 days')\n"
        ");\n"
    )
    path = SCENARIOS_DIR / "login-dashboard.sql"
    with path.open("a", encoding="utf-8") as f:
        f.write(approval_sql)

    _print_summary("login-dashboard", results)


def _print_summary(name: str, results: dict[str, TradingResult]) -> None:
    """생성 결과 요약 출력."""
    total_trades = sum(len(r.trades) for r in results.values())
    total_ph = sum(len(r.position_history) for r in results.values())
    total_pos = sum(len(r.final_positions) for r in results.values())

    print(f"  [{name}]")
    print(
        f"    거래: {total_trades}건, "
        f"포지션이력: {total_ph}건, "
        f"최종포지션: {total_pos}건"
    )
    for bot_id, r in results.items():
        sells = [t for t in r.trades if t.side == "sell"]
        buys = [t for t in r.trades if t.side == "buy"]
        print(f"    {bot_id}: 매수 {len(buys)}건, 매도 {len(sells)}건")


GENERATORS: dict[str, callable] = {
    "strategy-browse": generate_strategy_browse,
    "bot-management": generate_bot_management,
    "treasury": generate_treasury,
    "login-dashboard": generate_login_dashboard,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E 테스트 시나리오 시드 SQL 생성")
    parser.add_argument("--scenario", type=str, help="생성할 시나리오 이름")
    parser.add_argument("--all", action="store_true", help="모든 시나리오 생성")
    args = parser.parse_args()

    if not args.all and not args.scenario:
        parser.error("--scenario 또는 --all 중 하나를 지정하세요")

    scenarios = list(GENERATORS.keys()) if args.all else [args.scenario]

    print(f"시드 SQL 생성 시작 (대상: {', '.join(scenarios)})")
    for name in scenarios:
        if name not in GENERATORS:
            print(f"  [!] 알 수 없는 시나리오: {name}")
            continue
        GENERATORS[name]()

    print(f"완료. 출력 디렉토리: {SCENARIOS_DIR}")


if __name__ == "__main__":
    main()
