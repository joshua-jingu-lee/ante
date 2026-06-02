"""backtest run --symbols/--timeframe 생략 시 StrategyMeta fallback (#2060/#2096).

`backtest run` 이 ``--symbols``/``--timeframe`` 를 생략하면 ``StrategyMeta.symbols``/
``StrategyMeta.timeframe`` 로 fallback 하지 않아, 종목을 가진 전략도 데이터셋
0개·0-step·0% 성공으로 끝났다(#2060). ``guide/strategy.md`` L172/174 는 이미
기본값을 "전략 meta" 로 안내하므로, 코드를 meta fallback 하도록 고치면 가이드
주장이 참이 되어 #2096 도 동시 해결된다.

설계(effective-only):
- ``_validate_config`` 는 load 전이라 meta 를 모름 → ``timeframe=None`` (CLI 생략
  신호) 은 early vocab 검증을 deferred 한다. 명시값은 기존대로 early 거부.
- ``run()`` 은 load 후 ``StrategyMeta`` 로 effective symbols/timeframe 을
  resolve·재검증하고, downstream(provider/executor/data load/result.config) 에는
  None 이 아닌 effective ``BacktestConfig`` 만 흘린다.

검증 6축:
- (a) --symbols 생략 + meta.symbols=["005930"] → 005930 로드.
- (b) --timeframe 생략 + meta.timeframe="1m" → 1m 사용(provider 캐시 키 1m).
- (c) --symbols/--timeframe 명시 → 명시값 우선(meta 무시).
- (d) CLI+meta symbols 모두 없음 → warning + 0-step(에러 아님).
- (e) meta invalid timeframe → BacktestConfigError.
- (f) subprocess(runner) 동일 동작.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ante.backtest.config import BacktestConfig
from ante.backtest.exceptions import BacktestConfigError
from ante.backtest.result import BacktestResult
from ante.backtest.service import BacktestService
from ante.strategy.base import StrategyMeta
from ante.strategy.validator import ValidationResult

_BASE: dict = {
    "strategy_path": "s.py",
    "start_date": "2026-01-01",
    "end_date": "2026-01-02",
}


def _cfg(**overrides) -> dict:
    return {**_BASE, **overrides}


def _bypass_validator():
    """service.run 의 StrategyValidator 게이트(#2039)를 우회한다."""
    return patch(
        "ante.backtest.service.StrategyValidator.validate",
        return_value=ValidationResult(valid=True),
    )


def _strategy_cls_with_meta(
    *,
    symbols: list[str] | None = None,
    timeframe: str = "1d",
) -> MagicMock:
    """``StrategyLoader.load`` 가 반환할 strategy_cls 모사.

    ``.meta`` 만 실제 ``StrategyMeta`` 로 채워 run() 의 meta fallback resolve 가
    실 동작과 같게 한다(MagicMock 의 ``.meta.symbols`` 자동-attr 회피).
    """
    cls = MagicMock()
    cls.meta = StrategyMeta(
        name="s",
        version="1.0",
        description="test",
        symbols=symbols,
        timeframe=timeframe,
    )
    return cls


def _patched_run_components():
    """run() 내부 provider/executor 를 mock — load/effective 흐름 추적."""
    provider_instance = MagicMock()
    provider_instance.loaded_datasets = []
    executor_instance = MagicMock()

    async def _fake_run(progress_callback=None):
        return BacktestResult(
            strategy_name="S",
            strategy_version="1",
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_balance=1.0,
            final_balance=1.0,
            total_return=0.0,
        )

    executor_instance.run = _fake_run
    return provider_instance, executor_instance


@contextlib.contextmanager
def _run_env(strategy_cls: MagicMock):
    """provider/executor/loader patch 컨텍스트. (provider, executor) yield."""
    provider_instance, executor_instance = _patched_run_components()
    with (
        _bypass_validator(),
        patch("ante.backtest.service.StrategyLoader") as mock_loader,
        patch("ante.backtest.service.ParquetStore"),
        patch(
            "ante.backtest.service.BacktestDataProvider",
            return_value=provider_instance,
        ) as mock_provider_cls,
        patch(
            "ante.backtest.service.BacktestExecutor",
            return_value=executor_instance,
        ) as mock_executor_cls,
    ):
        mock_loader.load.return_value = strategy_cls
        yield provider_instance, mock_provider_cls, mock_executor_cls


# ── (a) --symbols 생략 + meta.symbols=["005930"] → 005930 로드 ────────────


class TestSymbolsOmittedFallbackToMeta:
    """CLI ``--symbols`` 생략(=[]) → StrategyMeta.symbols 로 fallback."""

    @pytest.mark.asyncio
    async def test_symbols_empty_falls_back_to_meta_symbols(self):
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"])
        with _run_env(strategy_cls) as (provider, _pcls, mock_executor_cls):
            svc = BacktestService()
            # CLI 생략은 symbols=[] (현행 유지). timeframe 도 생략(None).
            await svc.run(_cfg(symbols=[], timeframe=None))

        # meta.symbols 로 fallback 하여 005930 를 1d(meta 기본)로 로드.
        provider.load.assert_called_once_with("005930", "1d")
        # executor universe 도 effective symbols 로 채워진다.
        assert mock_executor_cls.call_args.kwargs["symbols"] == ["005930"]

    @pytest.mark.asyncio
    async def test_symbols_missing_key_falls_back_to_meta_symbols(self):
        """``symbols`` 키 자체 누락도 [] 정규화 → meta fallback."""
        strategy_cls = _strategy_cls_with_meta(symbols=["005930", "000660"])
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            await svc.run(_cfg(timeframe=None))

        assert provider.load.call_count == 2
        loaded = {c.args[0] for c in provider.load.call_args_list}
        assert loaded == {"005930", "000660"}


# ── (b) --timeframe 생략 + meta.timeframe="1m" → 1m 사용 ──────────────────


class TestTimeframeOmittedFallbackToMeta:
    """CLI ``--timeframe`` 생략(None) → StrategyMeta.timeframe 로 fallback."""

    @pytest.mark.asyncio
    async def test_timeframe_none_uses_meta_timeframe(self):
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"], timeframe="1m")
        with _run_env(strategy_cls) as (provider, mock_provider_cls, _ecls):
            svc = BacktestService()
            await svc.run(_cfg(symbols=["005930"], timeframe=None))

        # provider 캐시 키 timeframe 이 meta 의 1m 으로 흘러야 한다.
        provider.load.assert_called_once_with("005930", "1m")
        assert mock_provider_cls.call_args.kwargs["timeframe"] == "1m"

    @pytest.mark.asyncio
    async def test_timeframe_missing_key_uses_meta_timeframe(self):
        """``timeframe`` 키 누락 시에는 _validate_config 기본 1d 가 쓰인다.

        CLI 는 항상 키를 None 으로 넣으므로 이 경로는 programmatic 호환 회귀.
        키가 아예 없으면 ``config.get("timeframe", "1d")`` 기본 1d → meta 무시.
        """
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"], timeframe="1m")
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            await svc.run(_cfg(symbols=["005930"]))  # timeframe 키 없음

        provider.load.assert_called_once_with("005930", "1d")


# ── (c) --symbols/--timeframe 명시 → 명시값 우선(meta 무시) ────────────────


class TestExplicitValuesOverrideMeta:
    """명시된 symbols/timeframe 은 meta 를 무시하고 우선한다."""

    @pytest.mark.asyncio
    async def test_explicit_symbols_override_meta(self):
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"], timeframe="1m")
        with _run_env(strategy_cls) as (provider, mock_provider_cls, _ecls):
            svc = BacktestService()
            await svc.run(_cfg(symbols=["000660"], timeframe="5m"))

        # 명시 000660/5m 이 meta(005930/1m)를 덮어쓴다.
        provider.load.assert_called_once_with("000660", "5m")
        assert mock_provider_cls.call_args.kwargs["timeframe"] == "5m"

    @pytest.mark.asyncio
    async def test_explicit_timeframe_with_meta_symbols(self):
        """timeframe 명시 + symbols 생략 → 명시 tf + meta symbols 혼합."""
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"], timeframe="1m")
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            await svc.run(_cfg(symbols=[], timeframe="15m"))

        provider.load.assert_called_once_with("005930", "15m")


# ── (d) CLI+meta symbols 모두 없음 → warning + 0-step (에러 아님) ──────────


class TestNoSymbolsAtAllWarns:
    """CLI 생략 + meta.symbols 미설정 → warning 기록 + 0 load (에러 아님)."""

    @pytest.mark.asyncio
    async def test_no_symbols_warns_and_zero_load(self, caplog):
        strategy_cls = _strategy_cls_with_meta(symbols=None, timeframe="1d")
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            with caplog.at_level(logging.WARNING, logger="ante.backtest.service"):
                result = await svc.run(_cfg(symbols=[], timeframe=None))

        # 에러 없이 result 반환 (0-step 성공). data load 0회.
        assert isinstance(result, BacktestResult)
        provider.load.assert_not_called()
        # silent 0-step 완화 — 사유 warning 기록.
        assert any("대상 종목이 없습니다" in r.message for r in caplog.records), (
            caplog.records
        )


# ── (e) meta invalid timeframe / symbol → BacktestConfigError ─────────────


class TestMetaInvalidVocabRejected:
    """전략 meta 가 invalid timeframe/symbol 선언 시 effective 재검증으로 차단."""

    @pytest.mark.asyncio
    async def test_meta_invalid_timeframe_rejected(self):
        strategy_cls = _strategy_cls_with_meta(
            symbols=["005930"], timeframe="oracle-invalid"
        )
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
                await svc.run(_cfg(symbols=["005930"], timeframe=None))

        # 재검증 실패 → data load 미도달.
        provider.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_meta_invalid_krx_symbol_rejected(self):
        strategy_cls = _strategy_cls_with_meta(symbols=["ABCDEF"], timeframe="1d")
        with _run_env(strategy_cls) as (provider, _pcls, _ecls):
            svc = BacktestService()
            with pytest.raises(BacktestConfigError, match="Invalid KRX symbol"):
                await svc.run(_cfg(symbols=[], timeframe=None))

        provider.load.assert_not_called()


# ── effective-only: result.config 에 None 미누수, effective 값 반영 ────────


class TestEffectiveConfigNoNoneLeak:
    """result.config 가 None 이 아닌 effective BacktestConfig 인지 확인."""

    @pytest.mark.asyncio
    async def test_result_config_holds_effective_values(self):
        strategy_cls = _strategy_cls_with_meta(symbols=["005930"], timeframe="1m")
        provider_instance, executor_instance = _patched_run_components()
        captured: dict = {}

        async def _capturing_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _capturing_run

        with (
            _bypass_validator(),
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore"),
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ),
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ),
        ):
            mock_loader.load.return_value = strategy_cls
            svc = BacktestService()
            result = await svc.run(_cfg(symbols=[], timeframe=None))
            captured["config"] = result.config

        cfg = captured["config"]
        assert isinstance(cfg, BacktestConfig)
        # None 미누수 — effective 값으로 채워짐.
        assert cfg.timeframe == "1m"
        assert cfg.symbols == ["005930"]


# ── _validate_config: timeframe None deferred (early 검증 skip) ───────────


class TestValidateConfigTimeframeNoneDeferred:
    """timeframe=None 은 _validate_config 에서 early vocab 검증 deferred."""

    def test_timeframe_none_does_not_early_raise(self):
        svc = BacktestService()
        # None 이면 early 검증을 건너뛰고 placeholder "1d" 로 BacktestConfig 빌드.
        validated = svc._validate_config(_cfg(timeframe=None, symbols=["005930"]))
        assert isinstance(validated, BacktestConfig)
        assert validated.timeframe == "1d"  # None 미누수 (placeholder)

    def test_explicit_invalid_timeframe_still_early_rejected(self):
        """명시(비-None) invalid timeframe 은 기존대로 early 거부."""
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
            svc._validate_config(_cfg(timeframe="oracle-invalid"))


# ── (f) subprocess(runner) 동일 동작: 실제 데이터 + meta fallback ──────────

_META_SYMBOLS_STRATEGY = """\
from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class MetaSymbolsStrategy(Strategy):
    meta = StrategyMeta(
        name="metasym",
        version="1.0",
        description="meta symbols fallback",
        symbols=["005930"],
        timeframe="1d",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []
"""


def _write_strategy(tmp_path: Path, source: str) -> Path:
    strat = tmp_path / "strat.py"
    strat.write_text(source, encoding="utf-8")
    return strat


def _write_ohlcv(data_dir: Path, symbol: str, *, n: int = 5) -> None:
    """``data_dir`` 에 ``symbol`` 1d OHLCV 적재 (런타임 step 발생용)."""
    from datetime import UTC, datetime, timedelta

    import polars as pl

    from ante.data.store import ParquetStore

    start = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(days=n - 1),
        interval="1d",
        eager=True,
        time_zone="UTC",
    )
    df = pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [50000.0 + i * 100 for i in range(n)],
            "high": [50000.0 + i * 100 + 50 for i in range(n)],
            "low": [50000.0 + i * 100 - 50 for i in range(n)],
            "close": [50000.0 + i * 100 + 25 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )
    ParquetStore(base_path=data_dir).write(symbol, "1d", df)


class TestSubprocessMetaFallback:
    """subprocess(runner→service.run) 도 meta fallback 동일 적용 (#2060)."""

    @pytest.mark.asyncio
    async def test_subprocess_symbols_timeframe_omitted_falls_back_to_meta(
        self, tmp_path: Path
    ) -> None:
        """--symbols/--timeframe 생략(None) → meta.symbols=["005930"] 로드·≥1 step."""
        strat = _write_strategy(tmp_path, _META_SYMBOLS_STRATEGY)
        _write_ohlcv(tmp_path / "data", "005930")
        svc = BacktestService(data_path=str(tmp_path / "data"))

        # CLI 생략 신호 모사: symbols=[] (현행 유지), timeframe=None.
        cfg = {
            "strategy_path": str(strat),
            "symbols": [],
            "timeframe": None,
            "exchange": "KRX",
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "data_path": str(tmp_path / "data"),
        }
        out = await svc.run_subprocess(cfg)

        assert isinstance(out, dict)
        # meta.symbols 로 fallback → 005930 데이터셋 로드(0개 아님).
        datasets = out.get("datasets", [])
        loaded_symbols = {d.get("symbol") for d in datasets}
        assert "005930" in loaded_symbols, out
        assert any(d.get("row_count", 0) >= 1 for d in datasets), out


class TestRunInProcessMetaFallbackEndToEnd:
    """in-process run() end-to-end: meta fallback 으로 실제 데이터 로드·≥1 step."""

    @pytest.mark.asyncio
    async def test_in_process_meta_symbols_loaded_and_stepped(
        self, tmp_path: Path
    ) -> None:
        strat = _write_strategy(tmp_path, _META_SYMBOLS_STRATEGY)
        _write_ohlcv(tmp_path / "data", "005930")
        svc = BacktestService(data_path=str(tmp_path / "data"))

        cfg = {
            "strategy_path": str(strat),
            "symbols": [],
            "timeframe": None,
            "exchange": "KRX",
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "data_path": str(tmp_path / "data"),
        }
        result = await svc.run(cfg)

        # 데이터셋 1개 이상 + row_count ≥ 1 (0-step 0% 성공이 아님).
        assert result.datasets, "meta fallback 으로 005930 가 로드되어야 함"
        assert any(d.row_count >= 1 for d in result.datasets)
        # result.config 는 effective 값(005930/1d) 보유, None 미누수.
        assert isinstance(result.config, BacktestConfig)
        assert result.config.symbols == ["005930"]
        assert result.config.timeframe == "1d"
