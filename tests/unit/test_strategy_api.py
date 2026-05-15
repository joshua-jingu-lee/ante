"""전략 API 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.strategy.registry import StrategyStatus  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


@dataclass
class FakeStrategyRecord:
    strategy_id: str
    name: str
    version: str
    filepath: str = ""
    status: StrategyStatus = StrategyStatus.ADOPTED
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

    async def update_status(self, strategy_id: str, status: StrategyStatus) -> None:
        from ante.strategy.exceptions import StrategyError

        record = await self.get(strategy_id)
        if record is None:
            raise StrategyError(f"Strategy not found: {strategy_id}")

        # 허용된 전환만 수행 (실제 registry와 동일한 로직)
        _allowed: dict[StrategyStatus, set[StrategyStatus]] = {
            StrategyStatus.REGISTERED: {
                StrategyStatus.ADOPTED,
                StrategyStatus.ARCHIVED,
            },
            StrategyStatus.ADOPTED: {StrategyStatus.ARCHIVED},
            StrategyStatus.ARCHIVED: set(),
        }
        allowed = _allowed.get(record.status, set())
        if status not in allowed:
            raise ValueError(
                f"전환 불가: {record.status.value} → {status.value} "
                f"(허용: {', '.join(s.value for s in sorted(allowed))})"
            )
        record.status = status


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


# ── Member / Session fakes (#1378) ──────────────────────────────────────
#
# ``PATCH /api/strategies/{strategy_id}/status`` 는 ``require_strategy_write``
# 가드를 통과해야 200/204 를 반환한다 (#1378). 기존 status 변경 테스트들이
# 익명 호출을 가정하고 작성됐으므로, master 인증 fixture 를 client 에 주입해
# regression 을 막는다.
@dataclass
class _AuthFakeMember:
    member_id: str
    type: str = "human"
    role: str = "master"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _AuthFakeMemberService:
    def __init__(self) -> None:
        self._members: dict[str, _AuthFakeMember] = {
            "master-user": _AuthFakeMember(member_id="master-user"),
        }
        self._tokens: dict[str, str] = {"master-token": "master-user"}

    async def authenticate(self, token: str) -> _AuthFakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _AuthFakeMember | None:
        return self._members.get(member_id)


@pytest.fixture
def member_service():
    return _AuthFakeMemberService()


_MASTER_AUTH_HEADERS = {"Authorization": "Bearer master-token"}


@pytest.fixture
def client(registry, bot_manager, trade_service, member_service):
    app = create_app(
        strategy_registry=registry,
        bot_manager=bot_manager,
        trade_service=trade_service,
        member_service=member_service,
    )
    test_client = make_authed_client(app)
    # ``RequireAuthMiddleware`` (#1403) default-deny: master Bearer 디폴트 부착.
    test_client.headers.update(_MASTER_AUTH_HEADERS)
    return test_client


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
                status=StrategyStatus.ADOPTED,
            ),
        ]
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["id"] == "ma_cross_v1"
        assert data["strategies"][0]["name"] == "ma_cross"
        assert data["strategies"][0]["status"] == "adopted"

    def test_filter_by_status(self, client, registry):
        """상태 필터."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1", name="s1", version="1", status=StrategyStatus.ADOPTED
            ),
            FakeStrategyRecord(
                strategy_id="s2", name="s2", version="1", status=StrategyStatus.ARCHIVED
            ),
        ]
        resp = client.get("/api/strategies?status=adopted")
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

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

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
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

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

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            side_effect=Exception("DB error"),
        ):
            resp = c.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] is None

    def test_cumulative_return_no_bot_returns_null(self, registry):
        """봇이 없는 strategy는 cumulative_return=null (default 호출 금지, #1218)."""
        from unittest.mock import AsyncMock, patch

        fake_db = AsyncMock()

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        # PerformanceTracker.calculate가 호출되면 안 된다
        # (account_id를 알 수 없으므로).
        calc_mock = AsyncMock()
        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            calc_mock,
        ):
            resp = c.get("/api/strategies")

        assert resp.status_code == 200
        data = resp.json()["strategies"][0]
        assert data["cumulative_return"] is None
        # 봇이 없으면 calculate 호출 자체를 skip한다.
        calc_mock.assert_not_awaited()


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
        """trades 테이블이 없을 때 500이 아닌 200 반환 (#659).

        #1218 이후로는 account_id 명시 또는 봇 연결이 필요하므로,
        ?account_id=... 쿼리를 명시한다.
        """
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
            member_service=make_master_member_service(),
        )
        client = make_authed_client(app)

        resp = client.get("/api/strategies/s1/performance?account_id=acc-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        assert data["win_rate"] == 0.0
        assert data["total_pnl"] == 0.0
        assert data["equity_curve"] == []

    def test_performance_empty_trades(self, registry):
        """trades 테이블은 있지만 거래가 없을 때 200 반환.

        #1218 이후로는 account_id 명시 또는 봇 연결이 필요하므로,
        ?account_id=... 쿼리를 명시한다.
        """
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()
        fake_db.fetch_all = AsyncMock(return_value=[])

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        client = make_authed_client(app)

        resp = client.get("/api/strategies/s1/performance?account_id=acc-test")
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
            member_service=make_master_member_service(),
        )
        client = make_authed_client(app)

        resp = client.get("/api/strategies/nonexistent/performance")
        assert resp.status_code == 404

    def test_performance_account_required_when_no_bot(self, registry):
        """account_id query 미지정 + 봇도 없으면 400 (#1218)."""
        from unittest.mock import AsyncMock

        fake_db = AsyncMock()

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        resp = c.get("/api/strategies/s1/performance")
        assert resp.status_code == 400
        assert "account" in resp.json()["detail"].lower()

    def test_performance_account_resolved_from_bot(self, registry, bot_manager):
        """account_id 미지정이라도 봇에서 추출 가능하면 200 (#1218)."""
        from unittest.mock import AsyncMock, patch

        from ante.trade.models import PerformanceMetrics

        fake_db = AsyncMock()
        fake_metrics = PerformanceMetrics(total_trades=0)

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]
        bot_manager._bots = [
            {
                "bot_id": "bot-1",
                "strategy_id": "s1",
                "status": "running",
                "account_id": "acc-1",
            }
        ]

        app = create_app(
            strategy_registry=registry,
            bot_manager=bot_manager,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ) as mock_calc:
            resp = c.get("/api/strategies/s1/performance")

        assert resp.status_code == 200
        mock_calc.assert_awaited_once()
        kwargs = mock_calc.await_args.kwargs
        assert kwargs["account_id"] == "acc-1"

    def test_performance_with_explicit_account_id(self, registry):
        """account_id query 명시 시 200 (#1218)."""
        from unittest.mock import AsyncMock, patch

        from ante.trade.models import PerformanceMetrics

        fake_db = AsyncMock()
        fake_metrics = PerformanceMetrics(total_trades=0)

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ) as mock_calc:
            resp = c.get("/api/strategies/s1/performance?account_id=acc-explicit")

        assert resp.status_code == 200
        kwargs = mock_calc.await_args.kwargs
        assert kwargs["account_id"] == "acc-explicit"

    def test_performance_missing_account(self, registry):
        """strategy 존재 + 미존재 account → 404 + 계좌 not-found detail (#1563).

        SELECT 1 FROM accounts WHERE account_id=? 가 row None → 404.
        """
        from unittest.mock import AsyncMock, patch

        fake_db = AsyncMock()
        fake_db.fetch_one = AsyncMock(return_value=None)

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
        ) as mock_calc:
            resp = c.get(
                "/api/strategies/s1/performance?account_id=oracle-missing-account"
            )

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "계좌를 찾을 수 없습니다" in detail
        assert "oracle-missing-account" in detail
        # account 미존재이므로 metric 계산까지 가지 않는다.
        mock_calc.assert_not_awaited()

    def test_performance_real_account_regression(self, registry):
        """regression guard: 실재 account → 200 + metrics 유지 (#1563)."""
        from unittest.mock import AsyncMock, patch

        from ante.trade.models import PerformanceMetrics

        fake_db = AsyncMock()
        fake_db.fetch_one = AsyncMock(return_value={"1": 1})
        fake_metrics = PerformanceMetrics(total_trades=0)

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
            return_value=fake_metrics,
        ) as mock_calc:
            resp = c.get("/api/strategies/s1/performance?account_id=acc-real")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_trades"] == 0
        mock_calc.assert_awaited_once()
        assert mock_calc.await_args.kwargs["account_id"] == "acc-real"

    def test_performance_missing_account_no_accounts_table(self, registry):
        """accounts 테이블 부재 → 404 정규화, OperationalError 비누설 (#1563).

        부분 초기화/legacy DB에서 ``no such table: accounts``가 전파되면
        404 계약을 우회한다. 동일 404로 정규화하고 메시지를 누설하지 않는다.
        """
        import sqlite3
        from unittest.mock import AsyncMock, patch

        fake_db = AsyncMock()
        fake_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("no such table: accounts")
        )

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = make_authed_client(app)

        with patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new_callable=AsyncMock,
        ) as mock_calc:
            resp = c.get(
                "/api/strategies/s1/performance?account_id=oracle-missing-account"
            )

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "계좌를 찾을 수 없습니다" in detail
        assert "no such table" not in detail
        mock_calc.assert_not_awaited()

    def test_performance_other_operational_error_propagates(self, registry):
        """malformed db 등 다른 OperationalError는 삼키지 않고 전파 (#1563)."""
        import sqlite3
        from unittest.mock import AsyncMock

        from fastapi.testclient import TestClient

        from tests.unit.conftest import MASTER_AUTH_HEADERS

        fake_db = AsyncMock()
        fake_db.fetch_one = AsyncMock(
            side_effect=sqlite3.OperationalError("database disk image is malformed")
        )

        registry._strategies = [
            FakeStrategyRecord(strategy_id="s1", name="s1", version="1"),
        ]

        app = create_app(
            strategy_registry=registry,
            db=fake_db,
            member_service=make_master_member_service(),
        )
        c = TestClient(app, raise_server_exceptions=False)
        c.headers.update(MASTER_AUTH_HEADERS)

        resp = c.get("/api/strategies/s1/performance?account_id=acc-test")
        # 404로 정규화되지 않고 서버 에러로 전파된다.
        assert resp.status_code == 500


class TestUpdateStrategyStatus:
    """PATCH /api/strategies/{id}/status 테스트."""

    def test_update_status_adopted(self, client, registry):
        """registered -> adopted 전환 성공 시 204."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "adopted"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 204
        assert registry._strategies[0].status == StrategyStatus.ADOPTED

    def test_update_status_archived(self, client, registry):
        """adopted -> archived 전환 성공 시 204."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.ADOPTED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "archived"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 204
        assert registry._strategies[0].status == StrategyStatus.ARCHIVED

    def test_update_status_not_found(self, client):
        """존재하지 않는 전략 -> 404."""
        resp = client.patch(
            "/api/strategies/nonexistent/status",
            json={"status": "adopted"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 404

    def test_update_status_invalid_transition(self, client, registry):
        """archived -> adopted 전환 불가 -> 400."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.ARCHIVED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "adopted"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 400
        assert "전환 불가" in resp.json()["detail"]

    def test_update_status_invalid_value(self, client, registry):
        """유효하지 않은 status 값 -> 422 (#1441 — Pydantic Literal 차단)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "invalid_status"},
            headers=_MASTER_AUTH_HEADERS,
        )
        # Pydantic Literal validation 으로 422 로 거부된다 (#1441 — 기존
        # 400 분기는 dead-code 였음).
        assert resp.status_code == 422

    def test_update_status_extra_key_rejected(self, client, registry):
        """status 외 임의 필드는 422 로 거부 (#1441 — ``extra='forbid'``)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "archived", "unexpected": True},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 422
        # transition 이 실행되지 않았음을 확인 (extra key 차단으로 handler
        # 진입 자체가 차단).
        assert registry._strategies[0].status == StrategyStatus.REGISTERED

    def test_update_status_extra_key_reason_rejected(self, client, registry):
        """status + 추가 ``reason`` 필드도 422 (#1441 — closed object)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.ADOPTED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "archived", "reason": "test"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 422
        assert registry._strategies[0].status == StrategyStatus.ADOPTED

    def test_update_status_registered_rejected_as_transition(self, client, registry):
        """``registered`` 는 GET filter 전용 — PATCH 시 422 (#1441)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={"status": "registered"},
            headers=_MASTER_AUTH_HEADERS,
        )
        # transition target 이 아니므로 Pydantic Literal 단에서 422.
        assert resp.status_code == 422

    def test_update_status_missing_field(self, client, registry):
        """``status`` 누락 -> 422 (#1441 — required 필드)."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.patch(
            "/api/strategies/s1/status",
            json={},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 422

    def test_update_status_nonexistent_with_valid_body(self, client):
        """정상 body (``adopted``) 전달해도 strategy 없으면 404 회귀 (#1441)."""
        resp = client.patch(
            "/api/strategies/nonexistent/status",
            json={"status": "adopted"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 404

    def test_update_status_nonexistent_archived_body(self, client):
        """정상 body (``archived``) 전달해도 strategy 없으면 404 회귀 (#1441)."""
        resp = client.patch(
            "/api/strategies/nonexistent/status",
            json={"status": "archived"},
            headers=_MASTER_AUTH_HEADERS,
        )
        assert resp.status_code == 404


class TestListStrategiesStatusFilter:
    """GET /api/strategies?status= 필터 검증 테스트."""

    def test_filter_active_rejected(self, client):
        """deprecated status=active 전달 시 400."""
        resp = client.get("/api/strategies?status=active")
        assert resp.status_code == 400
        assert "허용되지 않은 status" in resp.json()["detail"]

    def test_filter_inactive_rejected(self, client):
        """deprecated status=inactive 전달 시 400."""
        resp = client.get("/api/strategies?status=inactive")
        assert resp.status_code == 400

    def test_filter_registered_accepted(self, client, registry):
        """status=registered 허용."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.REGISTERED,
            ),
        ]
        resp = client.get("/api/strategies?status=registered")
        assert resp.status_code == 200
        assert len(resp.json()["strategies"]) == 1

    def test_filter_adopted_accepted(self, client, registry):
        """status=adopted 허용."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.ADOPTED,
            ),
        ]
        resp = client.get("/api/strategies?status=adopted")
        assert resp.status_code == 200

    def test_filter_archived_accepted(self, client, registry):
        """status=archived 허용."""
        registry._strategies = [
            FakeStrategyRecord(
                strategy_id="s1",
                name="s1",
                version="1",
                status=StrategyStatus.ARCHIVED,
            ),
        ]
        resp = client.get("/api/strategies?status=archived")
        assert resp.status_code == 200
