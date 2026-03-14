"""자산 곡선(equity curve) 기능 테스트."""

import json

from ante.report.draft import ReportDraftGenerator, _standardize_equity_curve
from ante.report.models import StrategyReport

# ── _standardize_equity_curve ──


def test_standardize_equity_curve_basic():
    """백테스트 equity_curve가 표준 포맷으로 변환된다."""
    raw = [
        {"timestamp": "2025-01-01 09:00:00", "equity": 10000000, "balance": 9500000},
        {"timestamp": "2025-01-02 09:00:00", "equity": 10100000, "balance": 9600000},
    ]
    result = _standardize_equity_curve(raw)
    assert len(result) == 2
    assert result[0] == {"date": "2025-01-01", "value": 10000000}
    assert result[1] == {"date": "2025-01-02", "value": 10100000}


def test_standardize_equity_curve_empty():
    """빈 리스트는 빈 리스트를 반환한다."""
    assert _standardize_equity_curve([]) == []


def test_standardize_equity_curve_preserves_value_key():
    """이미 표준 포맷(date/value)인 경우에도 동작한다."""
    raw = [{"timestamp": "2025-03-01", "value": 5000000}]
    result = _standardize_equity_curve(raw)
    assert result[0]["value"] == 5000000


# ── ReportDraftGenerator ──


def test_generate_draft_includes_equity_curve():
    """generate_draft()가 detail_json에 표준 equity_curve를 포함한다."""
    result_data = {
        "strategy": "momentum_v1.0.0",
        "period": "2025-01 ~ 2025-12",
        "total_return_pct": 15.5,
        "total_trades": 42,
        "metrics": {"sharpe_ratio": 1.2, "max_drawdown": -5.3, "win_rate": 0.55},
        "equity_curve": [
            {"timestamp": "2025-01-01 09:00:00", "equity": 10000000},
            {"timestamp": "2025-06-15 09:00:00", "equity": 10500000},
            {"timestamp": "2025-12-31 09:00:00", "equity": 11550000},
        ],
        "trades": [],
    }
    report = ReportDraftGenerator.generate_draft(result_data, "strat1")
    detail = json.loads(report.detail_json)

    curve = detail["equity_curve"]
    assert len(curve) == 3
    assert curve[0] == {"date": "2025-01-01", "value": 10000000}
    assert curve[2] == {"date": "2025-12-31", "value": 11550000}


def test_generate_draft_no_equity_curve():
    """equity_curve가 없어도 에러 없이 빈 리스트로 저장한다."""
    result_data = {
        "strategy": "simple",
        "period": "2025-01",
        "total_return_pct": 0.0,
        "total_trades": 0,
        "metrics": {},
    }
    report = ReportDraftGenerator.generate_draft(result_data, "strat1")
    detail = json.loads(report.detail_json)
    assert detail["equity_curve"] == []


# ── StrategyReport.get_equity_curve ──


def test_report_get_equity_curve():
    """StrategyReport.get_equity_curve()가 detail_json에서 추출한다."""
    from datetime import UTC, datetime

    from ante.report.models import ReportStatus

    curve = [
        {"date": "2025-01-01", "value": 10000000},
        {"date": "2025-06-15", "value": 10500000},
    ]
    report = StrategyReport(
        report_id="r1",
        strategy_name="test",
        strategy_version="1.0",
        strategy_path="",
        status=ReportStatus.DRAFT,
        submitted_at=datetime.now(tz=UTC),
        detail_json=json.dumps({"equity_curve": curve}),
    )
    assert report.get_equity_curve() == curve


def test_report_get_equity_curve_empty():
    """equity_curve가 없으면 빈 리스트를 반환한다."""
    from datetime import UTC, datetime

    from ante.report.models import ReportStatus

    report = StrategyReport(
        report_id="r2",
        strategy_name="test",
        strategy_version="1.0",
        strategy_path="",
        status=ReportStatus.DRAFT,
        submitted_at=datetime.now(tz=UTC),
        detail_json="{}",
    )
    assert report.get_equity_curve() == []


def test_report_get_equity_curve_invalid_json():
    """detail_json이 유효하지 않으면 빈 리스트를 반환한다."""
    from datetime import UTC, datetime

    from ante.report.models import ReportStatus

    report = StrategyReport(
        report_id="r3",
        strategy_name="test",
        strategy_version="1.0",
        strategy_path="",
        status=ReportStatus.DRAFT,
        submitted_at=datetime.now(tz=UTC),
        detail_json="not valid json",
    )
    assert report.get_equity_curve() == []


# ── PerformanceFeedback.get_equity_curve ──


async def test_feedback_get_equity_curve():
    """PerformanceFeedback.get_equity_curve()가 거래 이력에서 곡선을 생성한다."""
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock

    from ante.report.feedback import PerformanceFeedback
    from ante.trade.recorder import TradeRecord, TradeStatus

    trades = [
        TradeRecord(
            trade_id="t1",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000,
            status=TradeStatus.FILLED,
            timestamp=datetime(2025, 1, 10, tzinfo=UTC),
        ),
        TradeRecord(
            trade_id="t2",
            bot_id="bot1",
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=10,
            price=52000,
            status=TradeStatus.FILLED,
            timestamp=datetime(2025, 1, 15, tzinfo=UTC),
        ),
    ]

    mock_trade = AsyncMock()
    mock_trade.get_trades = AsyncMock(return_value=trades)
    mock_bots = MagicMock()

    fb = PerformanceFeedback(trade_service=mock_trade, bot_manager=mock_bots)
    curve = await fb.get_equity_curve("bot1", initial_balance=10000000)

    assert len(curve) == 2
    # 1/10: buy 10 × 50000 = -500000
    assert curve[0]["date"] == "2025-01-10"
    assert curve[0]["value"] == 10000000 - 500000
    # 1/15: sell 10 × 52000 = +520000
    assert curve[1]["date"] == "2025-01-15"
    assert curve[1]["value"] == 10000000 - 500000 + 520000


async def test_feedback_get_equity_curve_no_trades():
    """거래가 없으면 빈 리스트를 반환한다."""
    from unittest.mock import AsyncMock, MagicMock

    from ante.report.feedback import PerformanceFeedback

    mock_trade = AsyncMock()
    mock_trade.get_trades = AsyncMock(return_value=[])
    mock_bots = MagicMock()

    fb = PerformanceFeedback(trade_service=mock_trade, bot_manager=mock_bots)
    curve = await fb.get_equity_curve("bot1")

    assert curve == []
