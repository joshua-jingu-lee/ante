"""전략 파일 접근 공용 helper + BacktestStrategyContext parity 테스트 (#2083).

라이브 ``StrategyContext`` 와 ``BacktestStrategyContext`` 가 동일한 보안 경계
(strategies/ 샌드박스, 절대경로/탈출/symlink escape 차단, 미존재 거부)를
공유하는지 검증한다. 보안 경계 SSOT 는 ``ante.strategy.file_access`` 다.

라이브 ``StrategyContext.load_file/load_text`` 의 동작 회귀는
``tests/unit/test_strategy.py::TestStrategyContextFileAccess`` 가 lock 한다
(helper 추출 이후에도 동작 불변).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from ante.backtest.context import BacktestStrategyContext
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.executor import BacktestExecutor
from ante.data.store import ParquetStore
from ante.strategy.base import Signal, Strategy, StrategyMeta
from ante.strategy.exceptions import StrategyFileAccessError
from ante.strategy.file_access import (
    STRATEGIES_ROOT,
    load_strategy_file,
    load_strategy_text,
    resolve_strategy_path,
)

# ── 공용 helper 직접 테스트 ────────────────────────


class TestStrategyFileAccessHelper:
    @pytest.fixture
    def strategies_dir(self, tmp_path):
        d = tmp_path / "strategies"
        d.mkdir()
        return d

    def test_default_root_constant(self):
        """STRATEGIES_ROOT 기본 상수가 strategies/ 로 정렬돼 있다."""
        assert str(STRATEGIES_ROOT) == "strategies"

    def test_load_file_success(self, strategies_dir):
        """strategies_dir 하위 바이너리 파일을 읽는다."""
        (strategies_dir / "data.bin").write_bytes(b"\x00\x01\x02")
        assert load_strategy_file(strategies_dir, "data.bin") == b"\x00\x01\x02"

    def test_load_text_success(self, strategies_dir):
        """strategies_dir 하위 텍스트 파일을 읽는다."""
        (strategies_dir / "config.txt").write_text("hello", encoding="utf-8")
        assert load_strategy_text(strategies_dir, "config.txt") == "hello"

    def test_load_text_subdirectory(self, strategies_dir):
        """하위 디렉토리 파일도 읽는다."""
        sub = strategies_dir / "sub"
        sub.mkdir()
        (sub / "data.csv").write_text("a,b,c", encoding="utf-8")
        assert load_strategy_text(strategies_dir, "sub/data.csv") == "a,b,c"

    @pytest.mark.parametrize("encoding", ["cp949", "euc-kr", "utf-8"])
    def test_load_text_encoding(self, strategies_dir, encoding):
        """다양한 인코딩으로 디코딩한다."""
        (strategies_dir / "kr.txt").write_text("한글", encoding=encoding)
        assert load_strategy_text(strategies_dir, "kr.txt", encoding=encoding) == "한글"

    def test_absolute_path_rejected(self, strategies_dir):
        """절대 경로는 StrategyFileAccessError 로 거부한다."""
        with pytest.raises(StrategyFileAccessError, match="Absolute paths"):
            load_strategy_file(strategies_dir, "/etc/passwd")

    def test_path_escape_rejected(self, strategies_dir):
        """`../` 탈출은 StrategyFileAccessError 로 거부한다."""
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            load_strategy_file(strategies_dir, "../../etc/passwd")

    def test_symlink_escape_rejected(self, strategies_dir, tmp_path):
        """symlink 를 통한 탈출도 StrategyFileAccessError 로 거부한다.

        strategies_dir 안에 strategies_dir 밖(tmp_path/secret) 을 가리키는
        symlink 를 두고, 그 링크 너머의 파일을 읽으려 하면 base/candidate 를
        모두 resolve() 후 비교하므로 escape 로 차단된다.
        """
        outside = tmp_path / "secret"
        outside.mkdir()
        (outside / "secret.txt").write_text("top-secret", encoding="utf-8")
        link = strategies_dir / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink 미지원 플랫폼")
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            load_strategy_file(strategies_dir, "link/secret.txt")

    def test_not_found_rejected(self, strategies_dir):
        """미존재 파일은 StrategyFileAccessError 로 거부한다."""
        with pytest.raises(StrategyFileAccessError, match="File not found"):
            load_strategy_file(strategies_dir, "nonexistent.txt")

    def test_resolve_returns_under_base(self, strategies_dir):
        """resolve 결과는 strategies_dir(resolve) 하위 절대 경로다."""
        resolved = resolve_strategy_path(strategies_dir, "sub/data.csv")
        assert resolved.is_relative_to(strategies_dir.resolve())


# ── BacktestStrategyContext.load_file / load_text ──


class TestBacktestStrategyContextFileAccess:
    @pytest.fixture
    def strategies_dir(self, tmp_path):
        d = tmp_path / "strategies"
        d.mkdir()
        return d

    @pytest.fixture
    def ctx(self, strategies_dir):
        # data_provider / portfolio 는 파일 접근 테스트에서 호출하지 않으므로
        # None placeholder 로 충분하다(타입 무관 단위 테스트).
        return BacktestStrategyContext(
            bot_id="bt",
            data_provider=None,  # type: ignore[arg-type]
            portfolio=None,  # type: ignore[arg-type]
            strategies_dir=strategies_dir,
        )

    def test_load_file_success(self, ctx, strategies_dir):
        (strategies_dir / "data.bin").write_bytes(b"\x00\x01\x02")
        assert ctx.load_file("data.bin") == b"\x00\x01\x02"

    def test_load_text_success(self, ctx, strategies_dir):
        (strategies_dir / "config.txt").write_text("hello", encoding="utf-8")
        assert ctx.load_text("config.txt") == "hello"

    def test_load_text_subdirectory(self, ctx, strategies_dir):
        sub = strategies_dir / "sub"
        sub.mkdir()
        (sub / "data.csv").write_text("a,b,c", encoding="utf-8")
        assert ctx.load_text("sub/data.csv") == "a,b,c"

    def test_load_text_encoding(self, ctx, strategies_dir):
        (strategies_dir / "kr.txt").write_text("한글", encoding="cp949")
        assert ctx.load_text("kr.txt", encoding="cp949") == "한글"

    def test_absolute_path_rejected(self, ctx):
        with pytest.raises(StrategyFileAccessError, match="Absolute paths"):
            ctx.load_file("/etc/passwd")

    def test_path_escape_rejected(self, ctx):
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            ctx.load_file("../../etc/passwd")

    def test_symlink_escape_rejected(self, ctx, strategies_dir, tmp_path):
        outside = tmp_path / "secret"
        outside.mkdir()
        (outside / "secret.txt").write_text("top-secret", encoding="utf-8")
        link = strategies_dir / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink 미지원 플랫폼")
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            ctx.load_file("link/secret.txt")

    def test_not_found_rejected(self, ctx):
        with pytest.raises(StrategyFileAccessError, match="File not found"):
            ctx.load_file("nonexistent.txt")

    def test_default_strategies_dir(self):
        """strategies_dir 미지정 시 기본 STRATEGIES_ROOT(resolve)로 정렬된다."""
        ctx = BacktestStrategyContext(
            bot_id="bt",
            data_provider=None,  # type: ignore[arg-type]
            portfolio=None,  # type: ignore[arg-type]
        )
        assert ctx._strategies_dir == STRATEGIES_ROOT.resolve()


# ── executor-level 재현(#2083) ─────────────────────


def _make_ohlcv_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [
                datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
                datetime(2026, 1, 3, 0, 0, tzinfo=UTC),
            ],
            "symbol": ["005930", "005930"],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [10, 20],
            "source": ["test", "test"],
        }
    )


class UsesLoadText(Strategy):
    """ctx.load_text 로 전략 전용 파일을 읽는 재현 전략."""

    meta = StrategyMeta(name="uses_load_text", version="1.0.0", description="repro")

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.loaded: str | None = None

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        if self.loaded is None:
            self.loaded = self.ctx.load_text("config.txt")
        return []


class TestExecutorLoadTextRepro:
    @pytest.fixture
    def data_provider(self, tmp_path):
        store = ParquetStore(base_path=tmp_path / "data")
        store.write("005930", "1d", _make_ohlcv_df())
        provider = BacktestDataProvider(
            store=store,
            start_date="2026-01-02",
            end_date="2026-01-03",
        )
        provider.load("005930", "1d")
        return provider

    @pytest.fixture
    def strategies_dir(self, tmp_path):
        d = tmp_path / "strategies"
        d.mkdir()
        (d / "config.txt").write_text("threshold=42", encoding="utf-8")
        return d

    async def test_run_with_strategies_dir_no_attribute_error(
        self, data_provider, strategies_dir
    ):
        """strategies_dir 주입 시 ctx.load_text 가 AttributeError 없이 동작한다.

        수정 전에는 BacktestStrategyContext 에 load_text 가 없어
        ``AttributeError: 'BacktestStrategyContext' object has no attribute
        'load_text'`` 로 실패했다(#2083 재현).
        """
        executor = BacktestExecutor(
            strategy_cls=UsesLoadText,
            data_provider=data_provider,
            strategies_dir=strategies_dir,
        )
        result = await executor.run()
        assert result.strategy_name == "uses_load_text"

    async def test_run_load_text_escape_rejected(self, data_provider, strategies_dir):
        """주입된 strategies_dir 밖을 읽으려는 전략은 StrategyFileAccessError.

        executor.run 경로에서도 보안 경계가 라이브와 동일하게 적용된다.
        """

        class UsesEscapingLoadText(Strategy):
            meta = StrategyMeta(name="escaping", version="1.0.0", description="escape")

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self.ctx.load_text("../../etc/passwd")
                return []

        executor = BacktestExecutor(
            strategy_cls=UsesEscapingLoadText,
            data_provider=data_provider,
            strategies_dir=strategies_dir,
        )
        with pytest.raises(StrategyFileAccessError, match="escapes"):
            await executor.run()
