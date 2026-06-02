"""Strategy 모듈 단위 테스트."""

from pathlib import Path

import pytest

import ante.strategy as strategy_pkg
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
from ante.strategy import Strategy

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
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")
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

    def test_forbidden_builtins_subscript_open_bypass(self, validator, tmp_path):
        """#2023 재현: __builtins__["open"](...) subscript 우회를 검출."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        f = __builtins__["open"]("/tmp/x", "w")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden built-in call: open()" in e for e in result.errors)

    def test_forbidden_builtins_attribute_eval_bypass(self, validator, tmp_path):
        """#2023: __builtins__.eval(...) attribute 우회를 검출."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        __builtins__.eval("1")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden built-in call: eval()" in e for e in result.errors)

    def test_forbidden_builtins_direct_call_regression(self, validator, tmp_path):
        """회귀: 직접 open()/eval() 호출은 기존대로 검출(메시지 포맷 불변)."""
        code = """
class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        eval("1+1")
        open("/tmp/x", "w")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden built-in call: eval()" in e for e in result.errors)
        assert any("Forbidden built-in call: open()" in e for e in result.errors)

    def test_forbidden_builtins_no_false_positive(self, validator, tmp_path):
        """오탐 없음: 정상 전략 + 비-__builtins__ subscript/attribute는 미검출."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        config = {"open": "value"}
        x = config["open"]
        obj = context
        obj.open()
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("Forbidden built-in call" in e for e in result.errors)

    def test_forbidden_builtins_non_forbidden_subscript_key(self, validator, tmp_path):
        """__builtins__["print"](비금지)은 FORBIDDEN_BUILTINS 한정으로 미검출."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        __builtins__["print"]("hi")
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("Forbidden built-in call" in e for e in result.errors)

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

    def test_toplevel_if_body_call_detected(self, validator, tmp_path):
        """#2018: 최상위 if 본문의 실행문(함수 호출)을 검출한다.

        `if True:` 등 조건이 무엇이든 if-body는 import-time에 실행되므로
        top-level 규칙으로 재귀 검사되어야 한다. 과거에는 if 전체를 skip해
        side effect가 우회되었다.
        """
        code = """
if True:
    foo()

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_if_else_call_detected(self, validator, tmp_path):
        """#2018: 최상위 if의 else 본문 실행문도 검출한다 (elif/else 분기)."""
        code = """
if SOME_FLAG:
    pass
else:
    bar()

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_if_elif_call_detected(self, validator, tmp_path):
        """#2018: 최상위 if의 elif 본문(orelse에 중첩된 If)도 재귀 검출한다."""
        code = """
if A:
    pass
elif B:
    baz()

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_if_type_checking_import_allowed(self, validator, tmp_path):
        """#2018 회귀: `if TYPE_CHECKING:` 본문의 import는 오탐 없이 통과한다.

        AST 정적 검사라 TYPE_CHECKING이 정의되지 않아도 무관(실행하지 않음).
        if-body의 import는 기존 top-level import 허용 규칙으로 통과해야 한다.
        """
        code = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.strategy import Signal

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_if_literal_assign_allowed(self, validator, tmp_path):
        """#2018 회귀: if 본문의 리터럴 상수 할당은 오탐 없이 통과한다."""
        code = """
if FLAG:
    CONST = "a"
else:
    CONST = "b"

class TestStrategy(Strategy):
    meta = None
    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_class_decorator_bare_name_forbidden(self, validator, tmp_path):
        """#2032 재현: top-level class의 bare Name decorator를 금지한다.

        `@run_on_import` 는 정의 시점(import-time)에 `run_on_import(S)` 를
        실행하므로 부작용 우회 경로다. run_on_import 자체는 같은 파일의
        decorator 없는 top-level def라 그 자체로는 통과해야 한다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def run_on_import(cls):
    return cls


@run_on_import
class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden top-level decorator" in e for e in result.errors)

    def test_toplevel_class_decorator_with_call_forbidden(self, validator, tmp_path):
        """#2032: 호출형 class decorator(`@deco()`)도 금지한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def deco(arg=None):
    def wrap(cls):
        return cls
    return wrap


@deco()
class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden top-level decorator" in e for e in result.errors)

    def test_toplevel_function_decorator_forbidden(self, validator, tmp_path):
        """#2033: top-level function decorator를 금지한다.

        `@deco\\ndef f(): ...` 는 정의 시점에 `deco(f)` 를 실행한다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def deco(fn):
    return fn


@deco
def helper():
    return 1


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Forbidden top-level decorator" in e for e in result.errors)

    def test_toplevel_default_argument_call_forbidden(self, validator, tmp_path):
        """#2033: top-level 함수의 default argument 식 호출을 금지한다.

        `def f(x=helper()): ...` 의 `helper()` 는 def 평가 시점(import-time)에
        실행되어 부작용을 일으킬 수 있다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def helper():
    return 1


def f(x=helper()):
    return x


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("default argument call" in e for e in result.errors)

    def test_toplevel_kw_default_argument_call_forbidden(self, validator, tmp_path):
        """#2033: keyword-only default 식 호출도 금지한다 (kw_defaults)."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def helper():
    return 1


def f(*, x=helper()):
    return x


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("default argument call" in e for e in result.errors)

    def test_toplevel_method_decorator_no_false_positive(self, validator, tmp_path):
        """#2032/#2033 회귀: 메서드 내부 decorator는 오탐하지 않는다.

        클래스 body 는 _check_toplevel_body 가 순회하지 않으므로
        `@property`/`@staticmethod` 같은 메서드 decorator는 영향이 없어야 한다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    @property
    def name(self):
        return "test"

    @staticmethod
    def util():
        return 1

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("decorator" in e.lower() for e in result.errors)

    def test_toplevel_literal_default_no_false_positive(self, validator, tmp_path):
        """#2033 회귀: 리터럴/Name default(`x=1`, `x=CONST`)는 통과한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


CONST = 5


def f(x=1, y=CONST):
    return x + y


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_plain_def_no_false_positive(self, validator, tmp_path):
        """#2032/#2033 회귀: decorator 없는 top-level def는 통과한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal


def helper(a, b):
    return a + b


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("top-level" in e.lower() for e in result.errors)

    @pytest.mark.parametrize(
        "expr",
        [
            "1 / 0",  # BinOp — import-time ZeroDivisionError
            "[1][2]",  # Subscript — import-time IndexError
            "[x for x in [1, 2, 3]]",  # ListComp — import-time 실행식
        ],
    )
    def test_toplevel_nonliteral_assign_forbidden(self, validator, tmp_path, expr):
        """#2043 재현: 호출이 없어도 비리터럴 실행식 최상위 할당을 금지한다.

        과거에는 `not self._contains_call(value)` 만 검사해 BinOp/Subscript/
        comprehension 같은 import-time 실행식이 그대로 통과했다.
        """
        code = f"""
from ante.strategy import Strategy, StrategyMeta, Signal

CRASH = {expr}


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_call_assign_still_forbidden(self, validator, tmp_path):
        """#2043 회귀: 호출 할당은 변경 후에도 여전히 금지(불변)."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

X = foo()


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    @pytest.mark.parametrize(
        "expr",
        [
            "5",  # Constant int
            '"s"',  # Constant str
            '["005930", "000660"]',  # literal list
            '{"a": 1}',  # literal dict
            "-1",  # UnaryOp on Constant
            "OTHER_CONST",  # Name 참조(부작용 없는 lookup)
            "(1, 2)",  # literal tuple
            "{1, 2}",  # literal set
        ],
    )
    def test_toplevel_literal_assign_no_false_positive(self, validator, tmp_path, expr):
        """#2043 회귀: 리터럴/Name/리터럴 컬렉션 할당은 오탐 없이 통과한다."""
        code = f"""
from ante.strategy import Strategy, StrategyMeta, Signal

X = {expr}


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_annassign_nonliteral_forbidden(self, validator, tmp_path):
        """#2043: AnnAssign 값이 비리터럴 실행식이면 금지한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

X: int = 1 / 0


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("top-level" in e.lower() for e in result.errors)

    def test_toplevel_annassign_literal_allowed(self, validator, tmp_path):
        """#2043 회귀: 리터럴 값 AnnAssign은 통과한다."""
        code = """
from ante.strategy import Strategy, StrategyMeta, Signal

X: list = [1, 2]


class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""
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
from ante.strategy import Strategy, StrategyMeta

class A(Strategy):
    meta = StrategyMeta(name="a", version="1.0.0", description="a")
    async def on_step(self, context):
        return []

class B(Strategy):
    meta = StrategyMeta(name="b", version="1.0.0", description="b")
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
        await registry.update_status("momentum_v1.0.0", StrategyStatus.ADOPTED)

        adopted = await registry.list_strategies(status=StrategyStatus.ADOPTED)
        assert len(adopted) == 1

        registered = await registry.list_strategies(status=StrategyStatus.REGISTERED)
        assert len(registered) == 0

    async def test_update_status(self, registry, meta, tmp_path):
        """전략 상태를 변경한다."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        await registry.update_status("momentum_v1.0.0", StrategyStatus.ADOPTED)

        record = await registry.get("momentum_v1.0.0")
        assert record is not None
        assert record.status == StrategyStatus.ADOPTED

    async def test_update_status_invalid_transition(self, registry, meta, tmp_path):
        """허용되지 않은 상태 전환 시 ValueError."""
        filepath = tmp_path / "test.py"
        filepath.write_text("")

        await registry.register(filepath, meta)
        await registry.update_status("momentum_v1.0.0", StrategyStatus.ARCHIVED)

        with pytest.raises(ValueError, match="전환 불가"):
            await registry.update_status("momentum_v1.0.0", StrategyStatus.ADOPTED)

    async def test_update_status_not_found(self, registry):
        """존재하지 않는 전략 상태 변경 시 StrategyError."""
        from ante.strategy.exceptions import StrategyError

        with pytest.raises(StrategyError, match="not found"):
            await registry.update_status("nonexistent_v1.0.0", StrategyStatus.ADOPTED)

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

    def test_invalid_exchange_via_module_constant(self, validator, tmp_path):
        """모듈 상수로 전달된 invalid exchange도 검출한다 (#2022 재현).

        `EXCHANGE = "INVALID"` 모듈 상수를 `exchange=EXCHANGE`로 전달하면
        예전에는 literal이 아니라서 None 반환 → 검사 skip(보안 우회)이었다.
        이제 모듈 레벨 문자열 상수를 정적 해석해 거부해야 한다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta

EXCHANGE = "INVALID"

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange=EXCHANGE,
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("Invalid exchange value: 'INVALID'" in e for e in result.errors)

    def test_invalid_exchange_literal_regression(self, validator, tmp_path):
        """literal invalid exchange는 기존대로 거부(불변, 회귀)."""
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
        assert any("Invalid exchange value: 'INVALID'" in e for e in result.errors)

    def test_valid_exchange_via_module_constant(self, validator, tmp_path):
        """valid 모듈 상수 exchange는 통과한다(오탐 없음, 회귀)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

EX = "NYSE"

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange=EX,
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("Invalid exchange" in e for e in result.errors)

    def test_valid_exchange_literal_regression(self, validator, tmp_path):
        """literal valid exchange는 기존대로 통과(불변, 회귀)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange="KRX",
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("Invalid exchange" in e for e in result.errors)

    def test_unresolvable_exchange_no_error(self, validator, tmp_path):
        """해석 불가(계산식/import 이름) exchange는 검사 skip(None, 기존 동작).

        비리터럴 실행식 해석은 본 이슈 비목표(#2043). 모듈 문자열 상수가
        아닌 Name(여기서는 함수 호출 결과)은 exchange 에러를 내지 않는다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta

def pick():
    return "INVALID"

class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test", version="1.0.0",
        description="test", exchange=pick(),
    )

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not any("Invalid exchange" in e for e in result.errors)


# ── #2040 validator: async hook 계약 ──────────────────────────────────


class TestValidatorAsyncHookContract:
    """#2040 — 런타임 await hook 이 sync `def` 면 error."""

    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def _write_strategy(self, tmp_path: Path, code: str) -> Path:
        filepath = tmp_path / "test_strategy.py"
        filepath.write_text(code)
        return filepath

    def test_sync_on_step_rejected(self, validator, tmp_path):
        """필수 on_step 이 sync `def` 면 'must be async' error."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "on_step() must be async (use 'async def')" in e for e in result.errors
        )

    def test_async_on_step_passes(self, validator, tmp_path):
        """async on_step 은 통과(async 위반 없음)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("must be async" in e for e in result.errors)

    def test_sync_on_fill_rejected(self, validator, tmp_path):
        """정의된 on_fill 이 sync `def` 면 error(런타임 await 시 TypeError)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []

    def on_fill(self, fill):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "on_fill() must be async (use 'async def')" in e for e in result.errors
        )

    def test_async_on_fill_passes(self, validator, tmp_path):
        """async def on_fill override 는 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []

    async def on_fill(self, fill):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("must be async" in e for e in result.errors)

    def test_sync_on_data_order_update_position_corrected_rejected(
        self, validator, tmp_path
    ):
        """on_data/on_order_update/on_position_corrected sync 도 각각 error."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []

    def on_data(self, data):
        return []

    def on_order_update(self, update):
        return None

    def on_position_corrected(self, correction):
        return None
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("on_data() must be async" in e for e in result.errors)
        assert any("on_order_update() must be async" in e for e in result.errors)
        assert any("on_position_corrected() must be async" in e for e in result.errors)

    def test_sync_on_start_on_stop_unaffected(self, validator, tmp_path):
        """on_start/on_stop 은 sync 계약 → sync `def` 여도 영향 없음(통과)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    def on_start(self):
        pass

    def on_stop(self):
        pass

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("must be async" in e for e in result.errors)


# ── #2041 validator: meta=StrategyMeta(...) 타입 ─────────────────────


class TestValidatorMetaTypeContract:
    """#2041 — meta 할당 값이 StrategyMeta(...) 호출이어야 한다."""

    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def _write_strategy(self, tmp_path: Path, code: str) -> Path:
        filepath = tmp_path / "test_strategy.py"
        filepath.write_text(code)
        return filepath

    def test_meta_dict_rejected(self, validator, tmp_path):
        """meta = {...} (dict) 는 타입 불일치 error."""
        code = """
from ante.strategy import Strategy

class TestStrategy(Strategy):
    meta = {"name": "t", "version": "1.0.0", "description": "t"}

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "'meta' must be a StrategyMeta(...) instance" in e for e in result.errors
        )

    def test_meta_none_rejected(self, validator, tmp_path):
        """meta = None 은 타입 불일치 error."""
        code = """
from ante.strategy import Strategy

class TestStrategy(Strategy):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "'meta' must be a StrategyMeta(...) instance" in e for e in result.errors
        )

    def test_meta_other_call_rejected(self, validator, tmp_path):
        """다른 호출(dict(...))은 StrategyMeta 호출이 아니므로 error."""
        code = """
from ante.strategy import Strategy

class TestStrategy(Strategy):
    meta = dict(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "'meta' must be a StrategyMeta(...) instance" in e for e in result.errors
        )

    def test_meta_strategy_meta_call_passes(self, validator, tmp_path):
        """meta = StrategyMeta(...) Name 호출은 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("StrategyMeta(...) instance" in e for e in result.errors)

    def test_meta_strategy_meta_attribute_call_passes(self, validator, tmp_path):
        """meta = base.StrategyMeta(...) Attribute 호출도 통과."""
        code = """
import ante.strategy.base as base
from ante.strategy import Strategy

class TestStrategy(Strategy):
    meta = base.StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("StrategyMeta(...) instance" in e for e in result.errors)

    def test_meta_reassigned_last_strategy_meta_passes(self, validator, tmp_path):
        """meta=None 후 meta=StrategyMeta(...) 재할당 → 마지막 값 기준 통과(핵심)."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = None
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("StrategyMeta(...) instance" in e for e in result.errors)

    def test_meta_reassigned_last_none_rejected(self, validator, tmp_path):
        """meta=StrategyMeta(...) 후 meta=None 재할당 → 마지막이 None 이라 error."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "'meta' must be a StrategyMeta(...) instance" in e for e in result.errors
        )

    def test_meta_annotation_only_rejected(self, validator, tmp_path):
        """annotation-only `meta: StrategyMeta`(값 없음) → 값 할당 없음 → error.

        런타임에 클래스 속성을 만들지 않으므로 StrategyMeta 인스턴스가 아니다.
        ``_has_class_var`` 는 AnnAssign 을 True 로 보지만(존재), 마지막 값-할당이
        없으므로 must-be-StrategyMeta error 로 귀결되어 두 검사가 정합한다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta: StrategyMeta

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any(
            "'meta' must be a StrategyMeta(...) instance" in e for e in result.errors
        )

    def test_meta_annotated_assign_strategy_meta_passes(self, validator, tmp_path):
        """annotated 값-할당 `meta: StrategyMeta = StrategyMeta(...)` 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class TestStrategy(Strategy):
    meta: StrategyMeta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid
        assert not any("StrategyMeta(...) instance" in e for e in result.errors)


# ── #2042 validator: 실제 ante Strategy 상속만 (import 별칭 추적) ──────


class TestValidatorStrategyImportAware:
    """#2042 — import alias 추적으로 실제 ante Strategy 상속만 인정."""

    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def _write_strategy(self, tmp_path: Path, code: str) -> Path:
        filepath = tmp_path / "test_strategy.py"
        filepath.write_text(code)
        return filepath

    def test_local_strategy_shadow_not_counted(self, validator, tmp_path):
        """파일 내 로컬 `class Strategy` 정의 → 그 base 상속은 ante Strategy 아님."""
        code = """
class Strategy:
    pass

class X(Strategy):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        # 실제 ante Strategy subclass 0개 → "No class inheriting from Strategy".
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_direct_import_strategy_passes(self, validator, tmp_path):
        """from ante.strategy import Strategy; class X(Strategy) → 인정·통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class X(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_import_strategy_base_passes(self, validator, tmp_path):
        """from ante.strategy.base import Strategy 도 인정·통과."""
        code = """
from ante.strategy.base import Strategy, StrategyMeta

class X(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_aliased_import_strategy_passes(self, validator, tmp_path):
        """from ante.strategy import Strategy as S; class X(S) → 인정·통과."""
        code = """
from ante.strategy import Strategy as S, StrategyMeta

class X(S):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_module_alias_attribute_strategy_passes(self, validator, tmp_path):
        """import ante.strategy as astg; class X(astg.Strategy) → 인정·통과."""
        code = """
import ante.strategy as astg
from ante.strategy import StrategyMeta

class X(astg.Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_dotted_module_attribute_strategy_passes(self, validator, tmp_path):
        """import ante.strategy; class X(ante.strategy.Strategy) → 인정·통과."""
        code = """
import ante.strategy
from ante.strategy import StrategyMeta

class X(ante.strategy.Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_unrelated_base_not_counted(self, validator, tmp_path):
        """import 안 한 임의 base 이름은 ante Strategy 로 인식 안 함."""
        code = """
class X(SomeOtherBase):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_function_local_import_not_counted(self, validator, tmp_path):
        """함수-로컬 `from ante.strategy import Strategy` → module-scope
        `class X(Strategy)` 를 Strategy subclass 로 인정하지 않음 (#2042 scope).

        module-scope 에는 Strategy import 가 없으므로 런타임 module
        네임스페이스에도 Strategy 가 없다(`class X(Strategy)` 는 NameError).
        validator 가 `ast.walk` 로 함수 내부 import 까지 바인딩 수집하면
        false positive 로 통과시켜 loader 와 불일치하므로, module-scope
        한정으로 "No class inheriting from Strategy" 로 귀결돼야 한다.
        """
        code = """
def _helper():
    from ante.strategy import Strategy  # noqa: F401
    return Strategy

class X(Strategy):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_module_level_import_still_passes(self, validator, tmp_path):
        """정상 module-level import 회귀: module-scope import + class → 통과."""
        code = """
from ante.strategy import Strategy, StrategyMeta

class X(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_nested_class_not_counted_as_module_strategy(self, validator, tmp_path):
        """함수/클래스 내부에 nested 정의된 Strategy subclass 는 module
        attribute 가 아니므로 module strategy 로 카운트하지 않음.

        module-scope 에 실제 Strategy subclass 가 없으면 nested 정의가
        있더라도 loader(`vars(module)`)가 못 보는 것과 정합하게 "No class
        inheriting from Strategy" 로 귀결된다.
        """
        code = """
from ante.strategy import Strategy, StrategyMeta  # noqa: F401

def _factory():
    class Inner(Strategy):
        meta = StrategyMeta(name="inner", version="1.0.0", description="i")

        async def on_step(self, context):
            return []

    return Inner
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_import_as_used_before_local_redefine_passes(self, validator, tmp_path):
        """import-as 후 class 사용, 그 뒤 local 재정의 → 사용 시점 바인딩으로 인정.

        Python 은 정의 순서로 이름을 바인딩한다. `class X(S)` 시점의 S 는 import
        된 ante Strategy 이므로(런타임 유효·loader 가 X 카운트) X 를 **인정**해야
        한다. 이후 `class S` 의 local 재정의는 X 판정에 영향을 주지 않는다.
        (3차 Codex FAIL 케이스 — 정의 순서를 무시한 false negative 회귀 락.)
        """
        code = """
from ante.strategy import Strategy as S, StrategyMeta

class X(S):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []

class S:
    pass
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_local_redefine_before_use_not_counted(self, validator, tmp_path):
        """import 후 local 재정의가 사용보다 먼저 → 사용 시점엔 local shadow → 미인정.

        `from ante.strategy import Strategy` 로 ante 바인딩 후, `class Strategy`
        가 그 이름을 local 로 재바인딩한 다음 `class X(Strategy)` 가 온다. X 정의
        시점의 Strategy 는 local 클래스이므로 미인정(loader 도 X 는 ante 비상속이라
        비카운트, 정합).
        """
        code = """
from ante.strategy import Strategy

class Strategy:
    pass

class X(Strategy):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_original_2042_bug_strategy_meta_only_not_counted(
        self, validator, tmp_path
    ):
        """원래 #2042 버그: StrategyMeta 만 import + local `class Strategy` → 미인정.

        Strategy 라는 이름은 ante 로 바인딩된 적이 없고(StrategyMeta 만 import),
        `class Strategy` 가 local 정의이므로 `class X(Strategy)` 는 미인정.
        """
        code = """
from ante.strategy import StrategyMeta

class Strategy:
    pass

class X(Strategy):
    meta = None

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_module_alias_rebind_before_use_not_counted(self, validator, tmp_path):
        """module-alias 재바인딩 후 사용 → 미인정 (#2042 4차 Codex FAIL 락).

        `import ante.strategy as astg` 로 module-alias 등록 후 `astg = object()`
        가 그 이름을 재바인딩한 다음 `class X(astg.Strategy)` 가 온다. X 정의
        시점의 astg 는 ante.strategy 모듈이 아닌 다른 객체이므로 미인정해야
        한다(loader 도 `astg.Strategy` AttributeError 로 X 정의 자체가 실패).
        name_binding 의 재바인딩 무효화와 대칭으로 module_aliases 도 무효화돼야
        한다. (재바인딩 값은 top-level 허용 리터럴을 써 forbidden-toplevel 검사와
        직교하게 둔다.)
        """
        code = """
import ante.strategy as astg
from ante.strategy import StrategyMeta

astg = 0

class X(astg.Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_module_alias_used_before_rebind_passes(self, validator, tmp_path):
        """module-alias 사용 후 재바인딩 → 인정 (정의 순서 보존).

        `class X(astg.Strategy)` 시점의 astg 는 아직 ante.strategy module 이므로
        인정(런타임 유효·loader 가 X 카운트). 그 뒤 `astg = object()` 재바인딩은
        X 판정에 영향을 주지 않는다. 재바인딩 무효화가 order-aware 임을 락.
        (재바인딩 값은 top-level 허용 리터럴을 써 forbidden-toplevel 검사와
        직교하게 둔다.)
        """
        code = """
import ante.strategy as astg
from ante.strategy import StrategyMeta

class X(astg.Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []

astg = 0
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert result.valid

    def test_dotted_module_root_rebind_before_use_not_counted(
        self, validator, tmp_path
    ):
        """dotted alias root 이름 재바인딩 후 사용 → 미인정 (#2042).

        `import ante.strategy` 로 module-alias("ante.strategy") 등록 후 root
        이름 `ante` 를 재바인딩하면 `ante.strategy.Strategy` 경로가 더 이상 ante
        모듈을 가리키지 않으므로 미인정해야 한다. dotted alias 무효화는 root
        이름 기준이다. (재바인딩 값은 top-level 허용 리터럴을 써
        forbidden-toplevel 검사와 직교하게 둔다.)
        """
        code = """
import ante.strategy
from ante.strategy import StrategyMeta

ante = 0

class X(ante.strategy.Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)

    def test_star_import_strategy_not_counted(self, validator, tmp_path):
        """`from ante.strategy import *` star-import → 미인정 (known-limitation).

        star-import 는 Strategy 를 명시 바인딩명으로 추적하지 않으므로 보수적
        으로 strategy_names 에 추가하지 않는다(미인정). loader 보다 약하지만
        흔치 않은 의도된 known-limitation 범위다. authoritative gate 는 loader
        의 런타임 issubclass.
        """
        code = """
from ante.strategy import *

class X(Strategy):
    meta = StrategyMeta(name="t", version="1.0.0", description="t")

    async def on_step(self, context):
        return []
"""
        result = validator.validate(self._write_strategy(tmp_path, code))
        assert not result.valid
        assert any("No class inheriting from Strategy" in e for e in result.errors)


# ── #2052 loader: 파일 정의 subclass만 카운트 ────────────────────────


class TestLoaderFileDefinedOnly:
    """#2052 — import 된 Strategy subclass 제외, 파일 정의 subclass만 카운트."""

    def test_imported_subclass_not_counted(self, tmp_path):
        """helper 의 ImportedStrategy 를 import 한 main → MainStrategy 만 카운트."""
        helper = tmp_path / "helper_mod.py"
        helper.write_text(
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class ImportedStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="imp", version="1.0.0", description="i")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        main = tmp_path / "main_strategy.py"
        main.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(tmp_path)!r})\n"
            "from helper_mod import ImportedStrategy  # noqa: F401\n"
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class MainStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="main", version="1.0.0", description="m")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        cls = StrategyLoader.load(main)
        assert cls.__name__ == "MainStrategy"
        assert issubclass(cls, Strategy)

    def test_two_local_subclasses_rejected(self, tmp_path):
        """같은 파일에 2개 정의 → Multiple Strategy subclasses error."""
        main = tmp_path / "two_strategy.py"
        main.write_text(
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class AStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="a", version="1.0.0", description="a")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
            "\n"
            "class BStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="b", version="1.0.0", description="b")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        with pytest.raises(StrategyLoadError, match="Multiple Strategy subclasses"):
            StrategyLoader.load(main)


# ── validate ↔ load 패리티 (#2040 번들) ──────────────────────────────


class TestValidateLoadParity:
    """validate(파일 정의 실제 Strategy subclass 1개) ↔ load(module-origin 1개)."""

    @pytest.fixture
    def validator(self):
        return StrategyValidator()

    def test_imported_subclass_parity(self, tmp_path):
        """helper import + main 1개 정의: validate 통과 ⟺ load 성공."""
        helper = tmp_path / "helper_mod.py"
        helper.write_text(
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class ImportedStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="imp", version="1.0.0", description="i")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        # validate 대상은 main 파일만 본다(AST 파일-scope). import 된
        # ImportedStrategy 는 main AST 에 클래스 정의가 없으므로 카운트 안 됨.
        main = tmp_path / "main_strategy.py"
        main.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(tmp_path)!r})\n"
            "from helper_mod import ImportedStrategy  # noqa: F401\n"
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class MainStrategy(Strategy):\n"
            '    meta = StrategyMeta(name="main", version="1.0.0", description="m")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        result = StrategyValidator().validate(main)
        # validate: 'import sys'/sys.path 호출 등 top-level 제약은 본 케이스가
        # 패리티 집합 동형 확인 목적이므로 Strategy-count 측면만 검증한다.
        assert not any("Multiple Strategy" in e for e in result.errors)
        assert not any("No class inheriting" in e for e in result.errors)
        # load: import 된 subclass 제외 → 정상 1개 로드.
        cls = StrategyLoader.load(main)
        assert cls.__name__ == "MainStrategy"

    def test_local_shadow_parity(self, tmp_path):
        """로컬 `class Strategy` shadow: validate 0개 ⟺ load 0개(둘 다 실패)."""
        f = tmp_path / "shadow_strategy.py"
        f.write_text(
            "class Strategy:\n"
            "    pass\n"
            "\n"
            "class X(Strategy):\n"
            "    meta = None\n"
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        result = StrategyValidator().validate(f)
        assert any("No class inheriting from Strategy" in e for e in result.errors)
        with pytest.raises(StrategyLoadError, match="No Strategy subclass"):
            StrategyLoader.load(f)

    def test_import_as_then_redefine_parity(self, tmp_path):
        """import-as 후 사용, 그 뒤 local 재정의: validate 인정 ⟺ load 성공.

        X 정의 시점의 S 는 import 된 ante Strategy 이므로 X 는 실제 ante
        Strategy subclass(`__module__ == module.__name__`)다. 이후 `class S`
        local 재정의는 X 의 base 에 영향을 주지 않는다. validate 가 X 를
        인정하면 load 도 X 하나를 반환해야 한다.
        """
        f = tmp_path / "import_as_redefine_strategy.py"
        f.write_text(
            "from ante.strategy import Strategy as S, StrategyMeta\n"
            "\n"
            "class X(S):\n"
            '    meta = StrategyMeta(name="t", version="1.0.0", description="t")\n'
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
            "\n"
            "class S:\n"
            "    pass\n"
        )
        result = StrategyValidator().validate(f)
        assert result.valid
        cls = StrategyLoader.load(f)
        assert cls.__name__ == "X"
        assert issubclass(cls, Strategy)

    def test_local_redefine_before_use_parity(self, tmp_path):
        """local 재정의가 사용보다 먼저: validate 미인정 ⟺ load 실패.

        `class X(Strategy)` 시점의 Strategy 는 local 클래스로 재바인딩된 뒤이므로
        X 는 ante 비상속. validate 가 0개로 판정하면 load 도 0개로 실패해야 한다.
        """
        f = tmp_path / "local_first_strategy.py"
        f.write_text(
            "from ante.strategy import Strategy\n"
            "\n"
            "class Strategy:\n"
            "    pass\n"
            "\n"
            "class X(Strategy):\n"
            "    meta = None\n"
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        result = StrategyValidator().validate(f)
        assert any("No class inheriting from Strategy" in e for e in result.errors)
        with pytest.raises(StrategyLoadError, match="No Strategy subclass"):
            StrategyLoader.load(f)


# ── ante.strategy lazy attribute access 회귀 (#1463) ──────────────────


def test_strategy_package_lazy_indicator_calculator() -> None:
    """`from ante.strategy import IndicatorCalculator`가 lazy로 정상 동작한다.

    `ante.strategy.__init__`의 PEP 562 ``__getattr__`` 패턴이 외부 호출자에게
    backward-compatible한 import surface를 제공하는지 확인한다 (#1463).
    같은 객체를 두 번 가져와도 ``ante.strategy.indicators.IndicatorCalculator``
    와 동일해야 한다.
    """
    from ante.strategy import IndicatorCalculator as Lazy1
    from ante.strategy import IndicatorCalculator as Lazy2
    from ante.strategy.indicators import IndicatorCalculator as Direct

    assert Lazy1 is Direct
    assert Lazy1 is Lazy2
    # 패키지 attribute 접근 경로도 동일 객체.
    assert strategy_pkg.IndicatorCalculator is Direct


def test_strategy_package_unknown_attribute_raises() -> None:
    """`__getattr__`은 알 수 없는 attribute에 대해 ``AttributeError``를 던진다."""
    import pytest as _pytest

    with _pytest.raises(AttributeError, match="no attribute 'NotARealSymbol'"):
        _ = strategy_pkg.NotARealSymbol  # type: ignore[attr-defined]
