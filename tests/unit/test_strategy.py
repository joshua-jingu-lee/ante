"""Strategy 모듈 단위 테스트."""

from pathlib import Path

import pytest

from ante.core import Database
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Signal,
    Strategy,
    StrategyContext,
    StrategyLoader,
    StrategyMeta,
    StrategyRegistry,
    StrategyStatus,
    StrategyValidator,
)
from ante.strategy.exceptions import StrategyError, StrategyLoadError

# ── Test fixtures ─────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        return [{"close": 100.0}]

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0, "reserved": 500000.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


# ── Signal ────────────────────────────────────────


class TestSignal:
    def test_signal_frozen(self):
        """Signal은 불변 객체이다."""
        s = Signal(symbol="005930", side="buy", quantity=10.0)
        with pytest.raises(AttributeError):
            s.symbol = "other"  # type: ignore[misc]

    def test_signal_defaults(self):
        """Signal 기본값."""
        s = Signal(symbol="005930", side="buy", quantity=10.0)
        assert s.order_type == "market"
        assert s.price is None
        assert s.stop_price is None
        assert s.reason == ""


# ── Strategy ABC ──────────────────────────────────


class TestStrategyABC:
    def test_cannot_instantiate_without_on_step(self):
        """on_step 미구현 시 인스턴스화 불가."""

        class Incomplete(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

        with pytest.raises(TypeError):
            Incomplete(ctx=None)

    def test_can_instantiate_with_on_step(self):
        """on_step 구현 시 인스턴스화 가능."""

        class Complete(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

            async def on_step(self, context):
                return []

        s = Complete(ctx=None)
        assert s.meta.name == "x"

    async def test_default_on_fill_returns_empty(self):
        """on_fill 기본 구현은 빈 리스트 반환."""

        class S(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

            async def on_step(self, context):
                return []

        s = S(ctx=None)
        result = await s.on_fill({})
        assert result == []

    async def test_default_on_data_returns_empty(self):
        """on_data 기본 구현은 빈 리스트 반환."""

        class S(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

            async def on_step(self, context):
                return []

        s = S(ctx=None)
        result = await s.on_data({})
        assert result == []


# ── StrategyContext ────────────────────────────────


class TestStrategyContext:
    @pytest.fixture
    def ctx(self):
        return StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )

    async def test_get_ohlcv(self, ctx):
        result = await ctx.get_ohlcv("005930")
        assert len(result) > 0

    async def test_get_current_price(self, ctx):
        price = await ctx.get_current_price("005930")
        assert price == 100.0

    def test_get_positions(self, ctx):
        assert ctx.get_positions() == {}

    def test_get_balance(self, ctx):
        balance = ctx.get_balance()
        assert "total" in balance

    def test_get_open_orders(self, ctx):
        assert ctx.get_open_orders() == []

    def test_cancel_order(self, ctx):
        """cancel_order가 pending_actions에 추가된다."""
        ctx.cancel_order("ord1", reason="test")
        actions = ctx._drain_actions()
        assert len(actions) == 1
        assert actions[0].action == "cancel"
        assert actions[0].order_id == "ord1"

    def test_modify_order(self, ctx):
        """modify_order가 pending_actions에 추가된다."""
        ctx.modify_order("ord1", quantity=5.0, price=1000.0)
        actions = ctx._drain_actions()
        assert len(actions) == 1
        assert actions[0].action == "modify"
        assert actions[0].quantity == 5.0

    def test_drain_clears_actions(self, ctx):
        """drain 후 pending_actions가 비워진다."""
        ctx.cancel_order("ord1")
        ctx._drain_actions()
        assert ctx._drain_actions() == []


# ── StrategyValidator ─────────────────────────────


class TestStrategyValidator:
    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def _write_strategy(self, tmp_path: Path, code: str) -> Path:
        filepath = tmp_path / "test_strategy.py"
        filepath.write_text(code)
        return filepath

    def test_valid_strategy(self, validator, tmp_path):
        """정상 전략 파일이 검증을 통과한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert len(result.errors) == 0

    def test_syntax_error(self, validator, tmp_path):
        """문법 오류 파일은 검증 실패."""
        code = "def broken(\n"
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Syntax error" in e for e in result.errors)

    def test_no_strategy_class(self, validator, tmp_path):
        """Strategy 상속 클래스가 없으면 실패."""
        code = "class NotAStrategy:\n    pass\n"
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class" in e for e in result.errors)

    def test_missing_meta(self, validator, tmp_path):
        """meta 클래스 변수가 없으면 실패."""
        code = """
class TestStrategy(Strategy):
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("meta" in e for e in result.errors)

    def test_missing_on_step(self, validator, tmp_path):
        """on_step 메서드가 없으면 실패."""
        code = """
class TestStrategy(Strategy):
    meta = None
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("on_step" in e for e in result.errors)

    def test_forbidden_import_os(self, validator, tmp_path):
        """금지 모듈 import 시 실패."""
        code = """
import os

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden import: os" in e for e in result.errors)

    def test_forbidden_from_import(self, validator, tmp_path):
        """from X import Y 형태의 금지 모듈."""
        code = """
from subprocess import call

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("subprocess" in e for e in result.errors)

    def test_dangerous_eval_warning(self, validator, tmp_path):
        """eval 호출은 경고."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        eval("1+1")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert len(result.warnings) > 0
        assert any("eval" in w for w in result.warnings)

    def test_open_warning(self, validator, tmp_path):
        """open 호출은 경고."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        open("file.txt")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert len(result.warnings) > 0
        assert any("open" in w for w in result.warnings)

    def test_multiple_strategy_classes(self, validator, tmp_path):
        """복수 Strategy 클래스는 실패."""
        code = """
class A(Strategy):
    meta = None
    async def on_step(self, context):
        return []

class B(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Multiple" in e for e in result.errors)


# ── StrategyLoader ────────────────────────────────


class TestStrategyLoader:
    def test_load_valid_strategy(self, tmp_path):
        """정상 전략 파일을 로드한다."""
        code = """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class MyStrategy(Strategy):
    meta = StrategyMeta(name="my", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        filepath = tmp_path / "my_strategy.py"
        filepath.write_text(code)

        cls = StrategyLoader.load(filepath)
        assert cls.__name__ == "MyStrategy"
        assert issubclass(cls, Strategy)

    def test_load_no_strategy(self, tmp_path):
        """Strategy 클래스가 없는 파일은 에러."""
        filepath = tmp_path / "empty.py"
        filepath.write_text("x = 1\n")

        with pytest.raises(StrategyLoadError, match="No Strategy subclass"):
            StrategyLoader.load(filepath)

    def test_load_file_not_found(self, tmp_path):
        """파일이 없으면 에러."""
        with pytest.raises(StrategyLoadError, match="File not found"):
            StrategyLoader.load(tmp_path / "nonexistent.py")

    def test_load_syntax_error(self, tmp_path):
        """문법 오류 파일은 에러."""
        filepath = tmp_path / "broken.py"
        filepath.write_text("def broken(\n")

        with pytest.raises(StrategyLoadError, match="Failed to execute"):
            StrategyLoader.load(filepath)


# ── StrategyRegistry ──────────────────────────────


class TestStrategyRegistry:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    async def registry(self, db):
        r = StrategyRegistry(db=db)
        await r.initialize()
        return r

    @pytest.fixture
    def meta(self):
        return StrategyMeta(
            name="momentum",
            version="1.0.0",
            description="test strategy",
        )

    async def test_register(self, registry, meta, tmp_path):
        """전략을 등록한다."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        record = await registry.register(filepath, meta)
        assert record.strategy_id == "momentum_v1.0.0"
        assert record.status == StrategyStatus.REGISTERED

    async def test_register_duplicate_raises(self, registry, meta, tmp_path):
        """중복 등록 시 에러."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        with pytest.raises(StrategyError, match="already registered"):
            await registry.register(filepath, meta)

    async def test_get(self, registry, meta, tmp_path):
        """전략 레코드를 조회한다."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        record = await registry.get("momentum_v1.0.0")
        assert record is not None
        assert record.name == "momentum"

    async def test_get_nonexistent(self, registry):
        """존재하지 않는 전략은 None."""
        assert await registry.get("nonexistent") is None

    async def test_list_strategies(self, registry, tmp_path):
        """전략 목록을 조회한다."""
        for i in range(3):
            meta = StrategyMeta(name=f"stg{i}", version="1.0.0", description="test")
            filepath = tmp_path / f"stg{i}.py"
            filepath.write_text("")
            await registry.register(filepath, meta)

        result = await registry.list_strategies()
        assert len(result) == 3

    async def test_list_by_status(self, registry, meta, tmp_path):
        """상태별 필터링 조회."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        await registry.update_status("momentum_v1.0.0", StrategyStatus.ACTIVE)

        active = await registry.list_strategies(status=StrategyStatus.ACTIVE)
        assert len(active) == 1

        registered = await registry.list_strategies(status=StrategyStatus.REGISTERED)
        assert len(registered) == 0

    async def test_update_status(self, registry, meta, tmp_path):
        """전략 상태를 변경한다."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        await registry.update_status("momentum_v1.0.0", StrategyStatus.ACTIVE)

        record = await registry.get("momentum_v1.0.0")
        assert record is not None
        assert record.status == StrategyStatus.ACTIVE

    async def test_exists(self, registry, meta, tmp_path):
        """존재 여부 확인."""
        assert not await registry.exists("momentum_v1.0.0")

        filepath = tmp_path / "test.py"
        filepath.write_text("")
        await registry.register(filepath, meta)

        assert await registry.exists("momentum_v1.0.0")
