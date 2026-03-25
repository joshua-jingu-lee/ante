"""전략 API 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.strategy.registry import StrategyStatus  # noqa: E402
from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeStrategyRecord:
    strategy_id: str
    name: str
    version: str
    filepath: str = ""
    status: StrategyStatus = StrategyStatus.ACTIVE
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    description: str = ""
    author_name: str = "agent"
    author_id: str = "agent"
    validation_warnings: list[str] = field(default_factory=list)
    rationale: str = ""
    risks: list[str] = field(default_factory=list)


@dataclass
class FakeTradeRecord:
    trade_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: str = "filled"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeRegistry:
    def __init__(self) -> None:
        self._strategies: list[FakeStrategyRecord] = []

    async def list_strategies(
        self, status: str | None = None
    ) -> list[FakeStrategyRecord]:
        if status:
            return [s for s in self._strategies if s.status.value == status]
        return list(self._strategies)

    async def get(self, strategy_id: str) -> FakeStrategyRecord | None:
        for s in self._strategies:
            if s.strategy_id == strategy_id:
                return s
        return None


class FakeBotManager:
    def __init__(self) -> None:
        self._bots: list[dict] = []

    def list_bots(self) -> list[dict]:
        return list(self._bots)


class FakeTradeService:
    def __init__(self) -> None:
        self._trades: list[FakeTradeRecord] = []

    async def get_trades(
        self,
        strategy_id: str | None = None,
        limit: int = 100,
        **kwargs: object,
    ) -> list[FakeTradeRecord]:
        trades = self._trades
        if strategy_id:
            trades = [t for t in trades if t.strategy_id == strategy_id]
        return trades[:limit]


@pytest.fixture
def registry():
    return FakeRegistry()


@pytest.fixture
def bot_manager():
    return FakeBotManager()


@pytest.fixture
def trade_service():
    return FakeTradeService()


@pytest.fixture
def client(registry, bot_manager, trade_service):
    app = create_app(
        strategy_registry=registry,
        bot_manager=bot_manager,
        trade_service=trade_service,
    )
    return TestClient(app)


class TestListStrategies:
    def test_empty_list(self, client):
        """전략 없을 때 빈 목록."""
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        assert resp.json()["strategies"] == []

    def test_list_with_data(self, client, registry):
        """전략 목록 반환."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="ma_cross_v1",
                name="ma_cross",
                version="1",
                status=StrategyStatus.ACTIVE,
            ),
        ]
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["id"] == "ma_cross_v1"
        assert data["strategies"][0]["name"] == "ma_cross"
        assert data["strategies"][0]["status"] == "active"

    def test_filter_by_status(self, client, registry):
        """상태 필터."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1", name="s1", version="1", status=StrategyStatus.ACTIVE
            ),
            FakeStrategyRecord(
                strategy_id="s2", name="s2", version="1", status=StrategyStatus.INACTIVE
            ),
        ]
        resp = client.get("/api/strategies?status=active")
        assert resp.status_code == 200
        assert len(resp.json()["strategies"]) == 1
        assert resp.json()["strategies"][0]["id"] == "s1"

    def test_includes_bot_info(self, client, registry, bot_manager):
        """봇 정보 포함."""
        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        bot_manager._bots = [
            {"bot_id": "bot-1", "strategy_id": "s1", "status": "running"},
        ]
        resp = client.get("/api/strategies")
        data = resp.json()["strategies"][0]
        assert data["bot_id"] == "bot-1"
        assert data["bot_status"] == "running"

    def test_cumulative_return_null_without_db(self, client, registry):
        """DB 없으면 cumulative_return은 null."""
        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] is None

    def test_cumulative_return_null_no_trades(self, registry):
        """거래 없으면 cumulative_return은 null."""
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()
        fake_db.fetch_all = AsyncMock(return_value=[])

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(strategy_registry=registry, db=fake_db)
        c = TestClient(app)

        resp = c.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] is None

    def test_cumulative_return_with_trades(self, registry, bot_manager):
        """거래가 있으면 cumulative_return에 net_pnl 값 반환."""
        from unittest.mock import AsyncMock, patch

        from ante.trade.models import PerformanceMetrics

        fake_db = AsyncMock()
        fake_metrics = PerformanceMetrics(
            total_trades=5,
            net_pnl=12345.0,
        )

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        bot_manager._bots = [
            {
                "bot_id": "bot-1",
                "strategy_id": "s1",
                "status": "running",
                "account_id": "acc-1",
            },
        ]

        app = create_app(
            strategy_registry=registry,
            bot_manager=bot_manager,
            db=fake_db,
        )
        c = TestClient(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ):
            resp = c.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] == 12345.0

    def test_cumulative_return_db_error_graceful(self, registry):
        """DB 에러 시 cumulative_return은 null (500 아님)."""
        from unittest.mock import AsyncMock, patch

        fake_db = AsyncMock()

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(strategy_registry=registry, db=fake_db)
        c = TestClient(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            resp = c.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] is None


class TestGetStrategy:
    def test_get_existing(self, client, registry):
        """전략 상세 조회."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="ma_cross_v1",
                name="ma_cross",
                version="1",
                description="이동평균 크로스",
            ),
        ]
        resp = client.get("/api/strategies/ma_cross_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"]["strategy_id"] == "ma_cross_v1"
        assert data["strategy"]["description"] == "이동평균 크로스"

    def test_root_level_status(self, client, registry):
        """응답 root level에 status 필드 포함 (#672)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] is not None
        assert data["status"] == "registered"
        assert data["status"] == data["strategy"]["status"]

    def test_get_nonexistent(self, client):
        """존재하지 않는 전략 → 404."""
        resp = client.get("/api/strategies/nonexistent")
        assert resp.status_code == 404

    def test_detail_includes_rationale_risks(self, client, registry):
        """응답에 rationale, risks 포함 (#802)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                rationale="모멘텀 기반 매매 전략",
                risks=["급락장에서 큰 손실 가능", "거래량 부족 종목 슬리피지"],
            ),
        ]
        resp = client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rationale"] == "모멘텀 기반 매매 전략"
        assert data["risks"] == ["급락장에서 큰 손실 가능", "거래량 부족 종목 슬리피지"]
        # strategy 객체에도 포함
        assert data["strategy"]["rationale"] == "모멘텀 기반 매매 전략"
        assert data["strategy"]["risks"] == [
            "급락장에서 큰 손실 가능",
            "거래량 부족 종목 슬리피지",
        ]

    def test_detail_includes_params_defaults(self, client, registry):
        """params, param_schema는 전략 로드 실패 시 빈 dict (#802)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                filepath="/nonexistent/path.py",
            ),
        ]
        resp = client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["params"] == {}
        assert data["param_schema"] == {}

    def test_detail_params_from_strategy_file(self, client, registry, tmp_path):
        """전략 파일이 존재하면 params/param_schema를 런타임 추출 (#802)."""
        code = """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class TestStrat(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []

    def get_params(self):
        return {"lookback": 20, "threshold": 0.05}

    def get_param_schema(self):
        return {"lookback": "되돌아볼 기간", "threshold": "매매 임계값"}
"""
        filepath = tmp_path / "test_strat.py"
        filepath.write_text(code)

        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                filepath=str(filepath),
            ),
        ]
        resp = client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["params"] == {"lookback": 20, "threshold": 0.05}
        assert data["param_schema"] == {
            "lookback": "되돌아볼 기간",
            "threshold": "매매 임계값",
        }

    def test_detail_rationale_risks_defaults(self, client, registry):
        """rationale, risks 미설정 시 기본값 (#802)."""
        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        resp = client.get("/api/strategies/s1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rationale"] == ""
        assert data["risks"] == []


class TestStrategyTrades:
    def test_get_trades(self, client, registry, trade_service):
        """거래 내역 조회."""
        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        trade_service._trades = [
            FakeTradeRecord(
                trade_id="t1",
                bot_id="bot-1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10,
                price=70000,
            ),
        ]
        resp = client.get("/api/strategies/s1/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) == 1
        assert data["trades"][0]["trade_id"] == "t1"
        assert data["trades"][0]["symbol"] == "005930"

    def test_trades_nonexistent_strategy(self, client):
        """존재하지 않는 전략 거래 → 404."""
        resp = client.get("/api/strategies/nonexistent/trades")
        assert resp.status_code == 404

    def test_trades_pagination(self, client, registry, trade_service):
        """커서 페이지네이션 테스트."""
        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        trade_service._trades = [
            FakeTradeRecord(
                trade_id=f"t{i}",
                bot_id="bot-1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=1,
                price=70000,
            )
            for i in range(5)
        ]
        resp = client.get("/api/strategies/s1/trades?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) == 2
        assert data["next_cursor"] is not None


class TestStrategyPerformance:
    """전략 성과 조회 API 테스트."""

    def test_performance_no_trades_table(self, registry):
        """trades 테이블이 없을 때 500이 아닌 200 반환 (#659)."""
        import sqlite3
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()
        fake_db.fetch_all = AsyncMock(
            side_effect=sqlite3.OperationalError("no such table: trades")
        )

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
        )
        client = TestClient(app)

        resp = client.get("/api/strategies/s1/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0
        assert data["total_pnl"] == 0.0
        assert data["equity_curve"] == []

    def test_performance_empty_trades(self, registry):
        """trades 테이블은 있지만 거래가 없을 때 200 반환."""
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()
        fake_db.fetch_all = AsyncMock(return_value=[])

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
        )
        client = TestClient(app)

        resp = client.get("/api/strategies/s1/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["equity_curve"] == []

    def test_performance_nonexistent_strategy(self, registry):
        """존재하지 않는 전략 성과 → 404."""
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()
        app = create_app(
            strategy_registry=registry,
            db=fake_db,
        )
        client = TestClient(app)

        resp = client.get("/api/strategies/nonexistent/performance")
        assert resp.status_code == 404
