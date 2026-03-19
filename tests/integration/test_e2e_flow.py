"""E2E 통합 테스트 — 전략 제출 → 백테스트 → 봇 생성 → 거래 → 성과 리포트.

시스템의 전체 흐름을 외부 의존성(증권사 API) 없이 검증한다.
MockBroker + 자동 체결 시뮬레이터로 이벤트 체인 전체를 테스트한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ante.bot.config import BotConfig
from ante.bot.manager import BotManager
from ante.broker.base import BrokerAdapter
from ante.config import Config, DynamicConfigService, SystemState
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderFilledEvent,
    OrderRequestEvent,
    OrderSubmittedEvent,
    OrderValidatedEvent,
)
from ante.gateway import APIGateway
from ante.report import ReportStore
from ante.report.models import ReportStatus, StrategyReport
from ante.rule import RuleEngine
from ante.strategy import StrategyRegistry
from ante.strategy.base import DataProvider, OrderView, PortfolioView
from ante.strategy.context import StrategyContext
from ante.strategy.loader import StrategyLoader
from ante.strategy.validator import StrategyValidator
from ante.trade import PerformanceTracker, PositionHistory, TradeRecorder, TradeService
from ante.treasury import Treasury

# ── Mock/Fake 구현체 ──────────────────────────────────


class MockBrokerAdapter(BrokerAdapter):
    """증권사 API 없이 즉시 체결하는 모의 브로커."""

    def __init__(self) -> None:
        super().__init__(config={})
        self.is_connected = True
        self._prices: dict[str, float] = {"005930": 70000.0, "000660": 120000.0}
        self._orders: dict[str, dict[str, Any]] = {}
        self._positions: list[dict[str, Any]] = []
        self._balance = {"cash": 10_000_000.0, "total_assets": 10_000_000.0}

    async def connect(self) -> None:
        self.is_connected = True

    async def disconnect(self) -> None:
        self.is_connected = False

    async def get_account_balance(self) -> dict[str, float]:
        return self._balance.copy()

    async def get_positions(self) -> list[dict[str, Any]]:
        return self._positions.copy()

    async def get_current_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 50000.0)

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        broker_order_id = f"MOCK-{uuid4().hex[:8]}"
        fill_price = price or self._prices.get(symbol, 50000.0)
        self._orders[broker_order_id] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": fill_price,
            "status": "filled",
        }
        return broker_order_id

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return True
        return False

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        return self._orders.get(order_id, {"status": "unknown"})

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        return []

    async def realtime_price_stream(
        self, symbols: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        yield {}

    async def realtime_order_stream(self) -> AsyncIterator[dict[str, Any]]:
        yield {}

    async def get_account_positions(self) -> list[dict[str, Any]]:
        return self._positions.copy()

    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._orders.values())

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        return []

    def get_commission_info(self) -> Any:
        from ante.broker.models import CommissionInfo

        return CommissionInfo()


class AutoFillSimulator:
    """OrderSubmittedEvent를 수신하면 즉시 OrderFilledEvent를 발행하는 시뮬레이터.

    실제 시스템에서는 증권사 스트리밍이 담당하는 역할.
    """

    def __init__(self, eventbus: EventBus, broker: MockBrokerAdapter) -> None:
        self._eventbus = eventbus
        self._broker = broker
        self.filled_events: list[OrderFilledEvent] = []

    def subscribe(self) -> None:
        self._eventbus.subscribe(OrderSubmittedEvent, self._on_submitted, priority=0)

    async def _on_submitted(self, event: object) -> None:
        if not isinstance(event, OrderSubmittedEvent):
            return

        order = self._broker._orders.get(event.broker_order_id, {})
        fill_price = order.get("price", 50000.0)
        commission = fill_price * event.quantity * 0.00015

        filled = OrderFilledEvent(
            order_id=event.order_id,
            broker_order_id=event.broker_order_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=fill_price,
            requested_quantity=event.quantity,
            remaining_quantity=0.0,
            commission=commission,
            order_type=event.order_type,
        )
        self.filled_events.append(filled)
        await self._eventbus.publish(filled)


class SimpleDataProvider(DataProvider):
    """테스트용 단순 DataProvider."""

    def __init__(self, prices: dict[str, float] | None = None) -> None:
        self._prices = prices or {"005930": 70000.0}

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> Any:
        return []

    async def get_current_price(self, symbol: str) -> float:
        return self._prices.get(symbol, 50000.0)

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return []


class SimplePortfolioView(PortfolioView):
    """테스트용 PortfolioView. Trade 모듈의 PositionHistory를 사용."""

    def __init__(self, position_history: PositionHistory, treasury: Treasury) -> None:
        self._positions = position_history
        self._treasury = treasury

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        # 동기 호출이므로 DB 조회 불가 — 빈 dict 반환 (E2E에서는 on_step에 직접 주입)
        return {}

    def get_balance(self, bot_id: str) -> dict[str, float]:
        budget = self._treasury._budgets.get(bot_id)
        if budget:
            return {
                "total": budget.allocated,
                "available": budget.available,
                "reserved": budget.reserved,
            }
        return {"total": 0.0, "available": 0.0, "reserved": 0.0}


class SimpleOrderView(OrderView):
    """테스트용 OrderView."""

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        return []


# ── Fixture ──────────────────────────────────────────────


@pytest.fixture
async def system(tmp_path: Path):
    """전체 시스템을 Composition Root 패턴으로 조립한다."""
    # Config
    toml = tmp_path / "system.toml"
    toml.write_text(
        '[db]\npath = "{db}"\n\n'
        "[web]\nenabled = false\n\n"
        "[treasury]\ncommission_rate = 0.00015\n\n"
        '[data]\npath = "{data}"\n'.format(
            db=str(tmp_path / "ante.db"),
            data=str(tmp_path / "data"),
        )
    )
    config = Config.load(config_dir=tmp_path)
    config.validate()

    # Database
    db = Database(str(tmp_path / "ante.db"))
    await db.connect()

    # EventBus
    eventbus = EventBus(history_size=1000)
    event_history = EventHistoryStore(db=db)
    await event_history.initialize()
    eventbus.use(event_history.record)

    # SystemState
    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()

    # DynamicConfig
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()

    # StrategyRegistry
    strategy_registry = StrategyRegistry(db=db)
    await strategy_registry.initialize()

    # RuleEngine
    rule_engine = RuleEngine(eventbus=eventbus, system_state=system_state)
    rule_engine.start()

    # Treasury
    treasury = Treasury(db=db, eventbus=eventbus, commission_rate=0.00015)
    await treasury.initialize()

    # Trade
    position_history = PositionHistory(db=db)
    await position_history.initialize()
    trade_recorder = TradeRecorder(db=db, position_history=position_history)
    await trade_recorder.initialize()
    trade_recorder.subscribe(eventbus)
    performance_tracker = PerformanceTracker(db=db)
    trade_service = TradeService(
        recorder=trade_recorder,
        position_history=position_history,
        performance=performance_tracker,
    )

    # BotManager
    bot_manager = BotManager(eventbus=eventbus, db=db)
    await bot_manager.initialize()

    # MockBroker + APIGateway
    broker = MockBrokerAdapter()
    api_gateway = APIGateway(broker=broker, eventbus=eventbus)
    api_gateway.start()

    # AutoFill 시뮬레이터
    auto_fill = AutoFillSimulator(eventbus=eventbus, broker=broker)
    auto_fill.subscribe()

    # ReportStore
    report_store = ReportStore(db=db)
    await report_store.initialize()

    yield {
        "config": config,
        "db": db,
        "eventbus": eventbus,
        "system_state": system_state,
        "strategy_registry": strategy_registry,
        "rule_engine": rule_engine,
        "treasury": treasury,
        "position_history": position_history,
        "trade_recorder": trade_recorder,
        "trade_service": trade_service,
        "bot_manager": bot_manager,
        "broker": broker,
        "api_gateway": api_gateway,
        "auto_fill": auto_fill,
        "report_store": report_store,
        "tmp_path": tmp_path,
    }

    # Teardown
    await bot_manager.stop_all()
    api_gateway.stop()
    await db.close()


def _write_test_strategy(path: Path, *, buy_symbol: str = "005930") -> Path:
    """테스트용 전략 파일 생성."""
    code = f'''"""테스트 전략."""

from ante.strategy.base import Signal, Strategy, StrategyMeta


class BuyOnceStrategy(Strategy):
    """한 번만 매수하는 단순 전략."""

    meta = StrategyMeta(
        name="buy_once",
        version="1.0",
        description="E2E 테스트용 단일 매수 전략",
        symbols=["{buy_symbol}"],
        timeframe="1d",
    )

    def on_start(self) -> None:
        self._bought = False

    async def on_step(self, context: dict) -> list[Signal]:
        if not self._bought:
            self._bought = True
            return [
                Signal(
                    symbol="{buy_symbol}",
                    side="buy",
                    quantity=10.0,
                    order_type="market",
                    price=70000.0,
                    reason="E2E test buy",
                )
            ]
        return []
'''
    filepath = path / "buy_once_strategy.py"
    filepath.write_text(code)
    return filepath


# ── E2E 테스트 ───────────────────────────────────────────


class TestE2EStrategySubmission:
    """E2E 흐름 1: 전략 검증 → 로딩 → 등록."""

    async def test_validate_load_register(self, system, tmp_path: Path):
        """전략 파일을 검증하고 로딩한 후 레지스트리에 등록한다."""
        filepath = _write_test_strategy(tmp_path)

        # 1. 정적 검증
        validator = StrategyValidator()
        result = validator.validate(filepath)
        assert result.valid, f"Validation errors: {result.errors}"

        # 2. 동적 로딩
        strategy_cls = StrategyLoader.load(filepath)
        assert strategy_cls.meta.name == "buy_once"
        assert strategy_cls.meta.version == "1.0"

        # 3. 레지스트리 등록
        registry = system["strategy_registry"]
        record = await registry.register(
            filepath=filepath,
            meta=strategy_cls.meta,
            warnings=result.warnings,
        )
        assert record.strategy_id == "buy_once_v1.0"
        assert record.name == "buy_once"

        # 4. 등록 확인
        stored = await registry.get("buy_once_v1.0")
        assert stored is not None
        assert stored.strategy_id == record.strategy_id


class TestE2EBacktest:
    """E2E 흐름 2: 백테스트 실행."""

    async def test_backtest_with_parquet_data(self, system, tmp_path: Path):
        """Parquet 테스트 데이터로 백테스트를 실행한다."""
        pytest.importorskip("polars", reason="polars required for backtest")

        import polars as pl

        from ante.backtest import BacktestService
        from ante.data import ParquetStore

        # 테스트 데이터 생성
        data_path = tmp_path / "bt_data"
        data_path.mkdir()
        store = ParquetStore(base_path=data_path)

        dates = [datetime(2025, 1, i + 1, tzinfo=UTC) for i in range(20)]
        prices = [70000.0 + i * 100 for i in range(20)]
        df = pl.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": [p + 200 for p in prices],
                "volume": [1000.0] * 20,
            }
        )
        store.write("005930", "1d", df)

        # 전략 파일
        filepath = _write_test_strategy(tmp_path)

        # 백테스트 실행
        service = BacktestService(data_path=str(data_path))
        result = await service.run(
            {
                "strategy_path": str(filepath),
                "start_date": "2025-01-01",
                "end_date": "2025-01-20",
                "symbols": ["005930"],
                "timeframe": "1d",
                "initial_balance": 10_000_000.0,
                "commission_rate": 0.00015,
                "slippage_rate": 0.0,
            }
        )

        assert result.strategy_name == "buy_once"
        assert result.initial_balance == 10_000_000.0
        assert len(result.trades) > 0
        assert result.trades[0].symbol == "005930"
        assert result.trades[0].side == "buy"


class TestE2EReportSubmission:
    """E2E 흐름 3: 백테스트 결과 → 리포트 제출."""

    async def test_submit_and_adopt_report(self, system):
        report_store = system["report_store"]

        report = StrategyReport(
            report_id=str(uuid4()),
            strategy_name="buy_once",
            strategy_version="1.0",
            strategy_path="/strategies/buy_once.py",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
            submitted_by="agent",
            backtest_period="2025-01-01 ~ 2025-01-20",
            total_return_pct=2.5,
            total_trades=1,
            sharpe_ratio=1.2,
            max_drawdown_pct=0.5,
            win_rate=1.0,
            summary="E2E 테스트 전략",
            rationale="테스트 목적",
        )

        # 제출
        report_id = await report_store.submit(report)
        assert report_id == report.report_id

        # 조회
        stored = await report_store.get(report_id)
        assert stored is not None
        assert stored.strategy_name == "buy_once"
        assert stored.total_return_pct == 2.5

        # 사용자 채택
        await report_store.update_status(
            report_id,
            ReportStatus.ADOPTED,
            user_notes="테스트 통과, 실전 배포",
        )
        adopted = await report_store.get(report_id)
        assert adopted.status == ReportStatus.ADOPTED
        assert adopted.user_notes == "테스트 통과, 실전 배포"


class TestE2EOrderFlow:
    """E2E 흐름 4: 봇 생성 → 거래 이벤트 체인.

    전체 흐름:
    Bot.on_step() → Signal
      → OrderRequestEvent
      → RuleEngine (검증 통과) → OrderValidatedEvent
      → Treasury (자금 예약) → OrderApprovedEvent
      → APIGateway (브로커 제출) → OrderSubmittedEvent
      → AutoFill 시뮬레이터 → OrderFilledEvent
      → Treasury (결산) + TradeRecorder (기록) + Bot (전략 통보)
    """

    async def test_full_order_chain(self, system, tmp_path: Path):
        """봇이 매수 시그널을 발행하면 전체 이벤트 체인을 거쳐 체결된다."""
        eventbus: EventBus = system["eventbus"]
        treasury: Treasury = system["treasury"]
        bot_manager: BotManager = system["bot_manager"]
        trade_service: TradeService = system["trade_service"]
        auto_fill: AutoFillSimulator = system["auto_fill"]
        position_history: PositionHistory = system["position_history"]

        # 이벤트 추적
        events_log: list[tuple[str, object]] = []

        def _make_tracker(name: str):
            def handler(event: object) -> None:
                events_log.append((name, event))

            return handler

        for evt_cls, name in [
            (OrderRequestEvent, "request"),
            (OrderValidatedEvent, "validated"),
            (OrderApprovedEvent, "approved"),
            (OrderSubmittedEvent, "submitted"),
            (OrderFilledEvent, "filled"),
        ]:
            eventbus.subscribe(evt_cls, _make_tracker(name), priority=-100)

        # Treasury 자금 설정
        await treasury.set_account_balance(10_000_000.0)
        assert treasury.account_balance == 10_000_000.0

        # 봇 자금 할당
        bot_id = "e2e_bot_001"
        strategy_id = "buy_once_v1.0"
        success = await treasury.allocate(bot_id, 5_000_000.0)
        assert success

        # 전략 로딩
        filepath = _write_test_strategy(tmp_path)
        strategy_cls = StrategyLoader.load(filepath)

        # StrategyContext 구성
        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=SimpleDataProvider(),
            portfolio=SimplePortfolioView(position_history, treasury),
            order_view=SimpleOrderView(),
        )

        # 봇 생성 + 시작
        config = BotConfig(
            bot_id=bot_id,
            strategy_id=strategy_id,
            bot_type="paper",
            interval_seconds=3600,  # 1시간 — 한 번만 실행 후 대기
        )
        await bot_manager.create_bot(config, strategy_cls, ctx)
        await bot_manager.start_bot(bot_id)

        # 봇이 on_step 한 번 실행될 때까지 대기
        await asyncio.sleep(0.2)

        # 봇 중지
        await bot_manager.stop_bot(bot_id)

        # ── 검증 ──

        # 1. 이벤트 체인의 모든 단계가 발생했는지
        # 참고: EventBus의 동기 재귀 발행으로 인해 추적기의 기록 순서는
        # 발행 순서와 다를 수 있음 (깊은 이벤트가 먼저 기록됨)
        event_names = [name for name, _ in events_log]
        expected = {"request", "validated", "approved", "submitted", "filled"}
        missing = expected - set(event_names)
        assert not missing, f"미발행 이벤트: {missing}, 기록: {event_names}"

        # 3. AutoFill이 체결을 생성했는지
        assert len(auto_fill.filled_events) == 1
        fill = auto_fill.filled_events[0]
        assert fill.symbol == "005930"
        assert fill.side == "buy"
        assert fill.quantity == 10.0

        # 4. TradeRecorder가 거래를 기록했는지
        trades = await trade_service.get_trades(bot_id=bot_id)
        assert len(trades) == 1
        assert trades[0].symbol == "005930"
        assert trades[0].side == "buy"
        assert trades[0].quantity == 10.0
        assert trades[0].status.value == "filled"

        # 5. PositionHistory가 포지션을 갱신했는지
        positions = await trade_service.get_positions(bot_id)
        assert len(positions) == 1
        assert positions[0].symbol == "005930"
        assert positions[0].quantity == 10.0

        # 6. Treasury 자금 변동 확인
        budget = treasury.get_budget(bot_id)
        assert budget is not None
        assert budget.spent > 0

    async def test_order_rejected_by_insufficient_funds(self, system, tmp_path: Path):
        """자금 부족 시 Treasury가 주문을 거부한다."""
        treasury: Treasury = system["treasury"]
        bot_manager: BotManager = system["bot_manager"]
        trade_service: TradeService = system["trade_service"]
        position_history: PositionHistory = system["position_history"]

        # 아주 적은 자금만 할당
        await treasury.set_account_balance(100.0)
        bot_id = "e2e_bot_poor"
        await treasury.allocate(bot_id, 100.0)

        filepath = _write_test_strategy(tmp_path)
        strategy_cls = StrategyLoader.load(filepath)

        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=SimpleDataProvider(),
            portfolio=SimplePortfolioView(position_history, treasury),
            order_view=SimpleOrderView(),
        )

        config = BotConfig(
            bot_id=bot_id,
            strategy_id="buy_once_v1.0",
            bot_type="paper",
            interval_seconds=3600,
        )
        await bot_manager.create_bot(config, strategy_cls, ctx)
        await bot_manager.start_bot(bot_id)
        await asyncio.sleep(0.2)
        await bot_manager.stop_bot(bot_id)

        # 자금 부족으로 체결이 없어야 함
        trades = await trade_service.get_trades(bot_id=bot_id)
        rejected = [t for t in trades if t.status.value == "rejected"]
        assert len(rejected) == 1
        assert "insufficient_budget" in rejected[0].reason


class TestE2EPerformance:
    """E2E 흐름 5: 거래 후 성과 지표 조회."""

    async def test_performance_after_trades(self, system, tmp_path: Path):
        """매수 후 성과 지표를 산출한다."""
        treasury: Treasury = system["treasury"]
        bot_manager: BotManager = system["bot_manager"]
        trade_service: TradeService = system["trade_service"]
        position_history: PositionHistory = system["position_history"]

        await treasury.set_account_balance(10_000_000.0)
        bot_id = "e2e_bot_perf"
        await treasury.allocate(bot_id, 5_000_000.0)

        filepath = _write_test_strategy(tmp_path)
        strategy_cls = StrategyLoader.load(filepath)

        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=SimpleDataProvider(),
            portfolio=SimplePortfolioView(position_history, treasury),
            order_view=SimpleOrderView(),
        )

        config = BotConfig(
            bot_id=bot_id,
            strategy_id="buy_once_v1.0",
            bot_type="paper",
            interval_seconds=3600,
        )
        await bot_manager.create_bot(config, strategy_cls, ctx)
        await bot_manager.start_bot(bot_id)
        await asyncio.sleep(0.2)
        await bot_manager.stop_bot(bot_id)

        # 성과 지표 — 매수만 했으므로 total_trades(매도 기준)=0, 커미션은 존재
        perf = await trade_service.get_performance(bot_id=bot_id)
        assert perf.total_commission > 0
        assert perf.first_trade_at is not None

        # 요약
        summary = await trade_service.get_summary(bot_id)
        assert "positions" in summary
        assert "performance" in summary
        assert "recent_trades" in summary


class TestE2EFullPipeline:
    """E2E 전체 파이프라인: 전략 제출 → 백테스트 → 리포트 → 봇 거래 → 성과."""

    async def test_complete_pipeline(self, system, tmp_path: Path):
        """Agent 워크플로우 전체를 시뮬레이션한다."""
        pytest.importorskip("polars", reason="polars required for backtest")

        import polars as pl

        from ante.backtest import BacktestService
        from ante.data import ParquetStore

        treasury: Treasury = system["treasury"]
        bot_manager: BotManager = system["bot_manager"]
        trade_service: TradeService = system["trade_service"]
        report_store: ReportStore = system["report_store"]
        strategy_registry: StrategyRegistry = system["strategy_registry"]
        position_history: PositionHistory = system["position_history"]

        # ═══ Phase 1: 전략 제출 ═══
        filepath = _write_test_strategy(tmp_path)
        validator = StrategyValidator()
        val_result = validator.validate(filepath)
        assert val_result.valid

        strategy_cls = StrategyLoader.load(filepath)
        record = await strategy_registry.register(
            filepath=filepath,
            meta=strategy_cls.meta,
            warnings=val_result.warnings,
        )
        assert record.strategy_id == "buy_once_v1.0"

        # ═══ Phase 2: 백테스트 ═══
        data_path = tmp_path / "bt_data"
        data_path.mkdir()
        store = ParquetStore(base_path=data_path)

        dates = [datetime(2025, 1, i + 1, tzinfo=UTC) for i in range(20)]
        prices = [70000.0 + i * 100 for i in range(20)]
        df = pl.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": [p + 500 for p in prices],
                "low": [p - 500 for p in prices],
                "close": [p + 200 for p in prices],
                "volume": [1000.0] * 20,
            }
        )
        store.write("005930", "1d", df)

        bt_service = BacktestService(data_path=str(data_path))
        bt_result = await bt_service.run(
            {
                "strategy_path": str(filepath),
                "start_date": "2025-01-01",
                "end_date": "2025-01-20",
                "symbols": ["005930"],
                "timeframe": "1d",
                "initial_balance": 10_000_000.0,
            }
        )
        assert bt_result.strategy_name == "buy_once"
        assert len(bt_result.trades) > 0

        # ═══ Phase 3: 리포트 제출 ═══
        report = StrategyReport(
            report_id=str(uuid4()),
            strategy_name=bt_result.strategy_name,
            strategy_version=bt_result.strategy_version,
            strategy_path=str(filepath),
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
            backtest_period=f"{bt_result.start_date} ~ {bt_result.end_date}",
            total_return_pct=bt_result.total_return,
            total_trades=len(bt_result.trades),
            summary="백테스트 통과",
        )
        await report_store.submit(report)
        await report_store.update_status(report.report_id, ReportStatus.ADOPTED)

        # ═══ Phase 4: 봇 생성 + 거래 ═══
        await treasury.set_account_balance(10_000_000.0)
        bot_id = "e2e_pipeline_bot"
        await treasury.allocate(bot_id, 5_000_000.0)

        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=SimpleDataProvider(),
            portfolio=SimplePortfolioView(position_history, treasury),
            order_view=SimpleOrderView(),
        )

        bot_config = BotConfig(
            bot_id=bot_id,
            strategy_id=record.strategy_id,
            bot_type="paper",
            interval_seconds=3600,
        )
        await bot_manager.create_bot(bot_config, strategy_cls, ctx)
        await bot_manager.start_bot(bot_id)
        await asyncio.sleep(0.2)
        await bot_manager.stop_bot(bot_id)

        # ═══ Phase 5: 성과 확인 ═══
        trades = await trade_service.get_trades(bot_id=bot_id)
        assert len(trades) == 1
        assert trades[0].symbol == "005930"
        assert trades[0].status.value == "filled"

        positions = await trade_service.get_positions(bot_id)
        assert len(positions) == 1
        assert positions[0].quantity == 10.0

        perf = await trade_service.get_performance(bot_id=bot_id)
        assert perf.total_commission > 0
        assert perf.first_trade_at is not None

        # 리포트 최종 확인
        final_report = await report_store.get(report.report_id)
        assert final_report.status == ReportStatus.ADOPTED
