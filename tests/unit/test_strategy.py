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
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyError,
    StrategyFileAccessError,
    StrategyLoadError,
)
from ante.strategy.validator import validate_exchange

# ── Test fixtures ─────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

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

    def test_meta_author_backward_compat(self):
        """author 키워드가 author_name/author_id로 매핑된다."""
        m = StrategyMeta(name="x", version="1.0.0", description="x", author="alice")
        assert m.author_name == "alice"
        assert m.author_id == "alice"

    def test_meta_author_name_id_explicit(self):
        """author_name/author_id를 직접 지정할 수 있다."""
        m = StrategyMeta(
            name="x",
            version="1.0.0",
            description="x",
            author_name="Alice",
            author_id="alice",
        )
        assert m.author_name == "Alice"
        assert m.author_id == "alice"

    def test_meta_immutable(self):
        """StrategyMeta는 불변 객체이다."""
        m = StrategyMeta(name="x", version="1.0.0", description="x")
        with pytest.raises(AttributeError):
            m.name = "y"  # type: ignore[misc]

    def test_meta_defaults(self):
        """StrategyMeta 기본값."""
        m = StrategyMeta(name="x", version="1.0.0", description="x")
        assert m.author_name == "agent"
        assert m.author_id == "agent"
        assert m.timeframe == "1d"
        assert m.exchange == "KRX"

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

    def test_default_get_param_schema_returns_empty(self):
        """get_param_schema 기본 구현은 빈 dict 반환."""

        class S(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

            async def on_step(self, context):
                return []

        s = S(ctx=None)
        assert s.get_param_schema() == {}

    def test_get_param_schema_with_descriptions(self):
        """전략이 파라미터 설명을 제공할 수 있다."""

        class S(Strategy):
            meta = StrategyMeta(name="x", version="1.0.0", description="x")

            async def on_step(self, context):
                return []

            def get_params(self):
                return {"lookback": 20, "atr_mul": 2.5}

            def get_param_schema(self):
                return {
                    "lookback": "고점 탐색 기간 (일)",
                    "atr_mul": "ATR 배수",
                }

        s = S(ctx=None)
        schema = s.get_param_schema()
        assert schema["lookback"] == "고점 탐색 기간 (일)"
        assert schema["atr_mul"] == "ATR 배수"
        # params와 schema 키가 일치
        assert set(s.get_params().keys()) == set(schema.keys())


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


# ── StrategyContext.load_file / load_text ────────


class TestStrategyContextFileAccess:
    @pytest.fixture
    def strategies_dir(self, tmp_path):
        d = tmp_path / "strategies"
        d.mkdir()
        return d

    @pytest.fixture
    def ctx(self, strategies_dir):
        return StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
            strategies_dir=strategies_dir,
        )

    def test_load_file_success(self, ctx, strategies_dir):
        """strategies/ 하위 파일을 읽는다."""
        (strategies_dir / "data.bin").write_bytes(b"\x00\x01\x02")
        result = ctx.load_file("data.bin")
        assert result == b"\x00\x01\x02"

    def test_load_text_success(self, ctx, strategies_dir):
        """strategies/ 하위 텍스트 파일을 읽는다."""
        (strategies_dir / "config.txt").write_text("hello", encoding="utf-8")
        result = ctx.load_text("config.txt")
        assert result == "hello"

    def test_load_file_subdirectory(self, ctx, strategies_dir):
        """strategies/ 하위 디렉토리의 파일을 읽는다."""
        sub = strategies_dir / "sub"
        sub.mkdir()
        (sub / "data.csv").write_text("a,b,c")
        result = ctx.load_text("sub/data.csv")
        assert result == "a,b,c"

    def test_load_file_absolute_path_rejected(self, ctx):
        """절대 경로는 차단된다."""
        with pytest.raises(StrategyFileAccessError, match="Absolute paths"):
            ctx.load_file("/etc/passwd")

    def test_load_file_path_escape_rejected(self, ctx):
        """경로 탈출 시도는 차단된다."""
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            ctx.load_file("../../etc/passwd")

    def test_load_file_not_found(self, ctx):
        """파일 미존재 시 명확한 에러."""
        with pytest.raises(StrategyFileAccessError, match="File not found"):
            ctx.load_file("nonexistent.txt")

    def test_load_text_encoding(self, ctx, strategies_dir):
        """인코딩 지정이 동작한다."""
        (strategies_dir / "kr.txt").write_text("한글", encoding="euc-kr")
        result = ctx.load_text("kr.txt", encoding="euc-kr")
        assert result == "한글"


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

    def test_forbidden_eval_error(self, validator, tmp_path):
        """eval 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        eval("1+1")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("eval" in e for e in result.errors)

    def test_forbidden_exec_error(self, validator, tmp_path):
        """exec 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        exec("x = 1")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("exec" in e for e in result.errors)

    def test_forbidden_compile_error(self, validator, tmp_path):
        """compile 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        compile("x = 1", "<string>", "exec")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("compile" in e for e in result.errors)

    def test_forbidden_dunder_import_error(self, validator, tmp_path):
        """__import__ 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        __import__("os")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("__import__" in e for e in result.errors)

    def test_forbidden_toplevel_function_call_assign(self, validator, tmp_path):
        """최상위 함수 호출 할당은 에러."""
        code = """
data = load_model("path/to/model")

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_forbidden_toplevel_standalone_call(self, validator, tmp_path):
        """최상위 독립 표현식(함수 호출)은 에러."""
        code = """
print("hello")

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_literal_assign_allowed(self, validator, tmp_path):
        """최상위 리터럴 상수 할당은 허용."""
        code = """
X = [1, 2, 3]
Y = "hello"

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        # 리터럴 할당은 top-level 에러가 아님
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_docstring_allowed(self, validator, tmp_path):
        """모듈 docstring은 허용."""
        code = '''
"""This is a strategy module."""

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
'''
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_open_error(self, validator, tmp_path):
        """open 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        open("file.txt")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("open" in e for e in result.errors)

    def test_forbidden_globals_error(self, validator, tmp_path):
        """globals 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        globals()
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("globals" in e for e in result.errors)

    def test_forbidden_locals_error(self, validator, tmp_path):
        """locals 호출은 에러."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        locals()
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("locals" in e for e in result.errors)

    @pytest.mark.parametrize(
        "module",
        [
            "multiprocessing",
            "threading",
            "signal",
            "io",
            "tempfile",
            "glob",
            "builtins",
        ],
    )
    def test_forbidden_module_import(self, validator, tmp_path, module):
        """새로 추가된 금지 모듈 import 시 실패."""
        code = f"""
import {module}

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(module in e for e in result.errors)

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

    async def test_register_with_rationale_risks(self, registry, meta, tmp_path):
        """rationale, risks를 포함하여 등록한다 (#802)."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        record = await registry.register(
            filepath,
            meta,
            rationale="모멘텀 팩터 기반 전략",
            risks=["급락장 리스크", "유동성 리스크"],
        )
        assert record.rationale == "모멘텀 팩터 기반 전략"
        assert record.risks == ["급락장 리스크", "유동성 리스크"]

        # DB에서 다시 읽어도 동일
        loaded = await registry.get("momentum_v1.0.0")
        assert loaded is not None
        assert loaded.rationale == "모멘텀 팩터 기반 전략"
        assert loaded.risks == ["급락장 리스크", "유동성 리스크"]

    async def test_register_without_rationale_risks(self, registry, meta, tmp_path):
        """rationale, risks 미지정 시 기본값 (#802)."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        record = await registry.register(filepath, meta)
        assert record.rationale == ""
        assert record.risks == []


# ── Exchange 호환성 검증 테스트 ──────────────────────


class TestValidateExchange:
    """validate_exchange() 런타임 검증 테스트."""

    def test_same_exchange_allowed(self):
        """동일 exchange는 허용."""
        validate_exchange("KRX", "KRX")  # should not raise

    def test_wildcard_allows_any(self):
        """전략 exchange='*'이면 모든 계좌 허용."""
        validate_exchange("*", "KRX")
        validate_exchange("*", "NYSE")
        validate_exchange("*", "TEST")

    def test_different_exchange_rejected(self):
        """다른 exchange 조합은 거부."""
        with pytest.raises(IncompatibleExchangeError):
            validate_exchange("KRX", "NYSE")

    def test_different_exchange_rejected_reverse(self):
        """NYSE 전략 + KRX 계좌 거부."""
        with pytest.raises(IncompatibleExchangeError):
            validate_exchange("NYSE", "KRX")

    def test_error_message_includes_names(self):
        """에러 메시지에 전략명·계좌명 포함."""
        with pytest.raises(IncompatibleExchangeError, match="momentum") as exc_info:
            validate_exchange(
                "KRX",
                "NYSE",
                strategy_name="momentum",
                account_name="미국계좌",
            )
        assert "미국계좌" in str(exc_info.value)

    def test_invalid_strategy_exchange(self):
        """유효하지 않은 전략 exchange → ValueError."""
        with pytest.raises(ValueError, match="유효하지 않은 전략"):
            validate_exchange("INVALID", "KRX")

    def test_invalid_account_exchange(self):
        """유효하지 않은 계좌 exchange → ValueError."""
        with pytest.raises(ValueError, match="유효하지 않은 계좌"):
            validate_exchange("KRX", "INVALID")

    def test_account_wildcard_rejected(self):
        """계좌 exchange에 '*'는 허용하지 않음."""
        with pytest.raises(ValueError, match="유효하지 않은 계좌"):
            validate_exchange("KRX", "*")

    def test_all_valid_exchanges(self):
        """모든 유효한 exchange 조합 테스트."""
        for exchange in ("KRX", "NYSE", "NASDAQ", "AMEX", "TEST"):
            validate_exchange(exchange, exchange)  # same → OK
            validate_exchange("*", exchange)  # wildcard → OK


class TestValidatorExchangeCheck:
    """StrategyValidator AST 기반 exchange 유효성 검증 테스트."""

    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def _write_strategy(self, tmp_path: Path, code: str) -> Path:
        filepath = tmp_path / "test_strategy.py"
        filepath.write_text(code)
        return filepath

    def test_valid_exchange(self, validator, tmp_path):
        """유효한 exchange 값은 검증 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange="NYSE",
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_invalid_exchange(self, validator, tmp_path):
        """유효하지 않은 exchange 값 → 에러."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange="INVALID",
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Invalid exchange" in e for e in result.errors)

    def test_wildcard_exchange(self, validator, tmp_path):
        """exchange='*' 범용 전략은 검증 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test", exchange="*")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_no_exchange_specified(self, validator, tmp_path):
        """exchange 미지정 시 기본값(KRX) 사용 — 검증 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
