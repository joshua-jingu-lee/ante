"""programmatic backtest ingress symbol/timeframe vocabulary 검증 (#1604).

#1590 Plan Review가 "CLI(#1603)만 고치면 ``service.run``/
``run_subprocess``/``runner`` 직접 config 경로에 invalid symbol/timeframe
**fake-success 잔존**"으로 판정 → 전용 결정 이슈로 분리. 정책 Option A:
``BacktestService._validate_config()`` 단일 chokepoint에 #1613 public
SSOT(`is_valid_timeframe`/`is_krx_symbol`/`CANONICAL_TIMEFRAMES`) 검증을
추가하고 invalid는 ``BacktestConfigError`` 로 backtest 실행 전 early-fail.

레이어 분리: CLI(#1603)는 ingress에서 ``BACKTEST_INVALID_*`` exit code로
거부(다른 계층). 본 모듈은 service 경계 ``BacktestConfigError`` 회귀 —
CLI 우회 programmatic 직접 호출의 fake-success를 닫는다.

핵심 경계:
- raw programmatic ``dict[str, Any]`` 는 CLI(Click 타입 협소화)와 달리
  임의 타입 유입 — 모든 invalid는 ``TypeError`` 가 아니라
  ``BacktestConfigError``. [R1-F1]
- ``{"symbols": None}`` /누락/``[]`` → no-symbols 정상,
  ``BacktestConfig.symbols == []`` 정규화. [R2-F1]
- exchange != "KRX" 면 symbol shape 미검증 (core.md ``### KRX symbol
  shape`` resolved exchange==KRX 한정 — NYSE+AAPL 비거부).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ante.backtest import runner
from ante.backtest.config import BacktestConfig
from ante.backtest.exceptions import BacktestConfigError
from ante.backtest.result import BacktestResult
from ante.backtest.service import BacktestService

_BASE: dict = {
    "strategy_path": "s.py",
    "start_date": "2026-01-01",
    "end_date": "2026-01-02",
}


def _cfg(**overrides) -> dict:
    return {**_BASE, **overrides}


# ── _validate_config 직접 단위: vocabulary 거부 ────────────────────────


class TestValidateConfigRejectsInvalidVocabulary:
    """``_validate_config`` 단일 chokepoint가 invalid를 BacktestConfigError로."""

    def test_invalid_timeframe_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
            svc._validate_config(_cfg(timeframe="oracle-invalid"))

    def test_invalid_krx_symbol_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid KRX symbol"):
            svc._validate_config(_cfg(symbols=["ABCDEF"], exchange="KRX"))

    def test_krx_symbol_default_exchange_rejected(self):
        """exchange 미지정 → KRX 기본 → KRX shape 검증."""
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid KRX symbol"):
            svc._validate_config(_cfg(symbols=["12345"]))  # 5자리

    def test_empty_segment_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="empty/blank"):
            svc._validate_config(_cfg(symbols=["005930", ""]))

    def test_blank_segment_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="empty/blank"):
            svc._validate_config(_cfg(symbols=["005930", "   "]))


class TestValidateConfigNonKrxExchangeNotShapeValidated:
    """exchange != "KRX" 면 symbol shape 미검증 (core.md KRX 한정)."""

    def test_nyse_aapl_not_rejected(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(exchange="NYSE", symbols=["AAPL"]))
        assert isinstance(validated, BacktestConfig)
        assert validated.symbols == ["AAPL"]
        assert validated.exchange == "NYSE"


class TestValidateConfigValidVocabularyRegression:
    """유효 config 회귀: 통과 + BacktestConfig 빌드."""

    def test_valid_timeframe_and_krx_symbol_pass(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(timeframe="1d", symbols=["005930"]))
        assert isinstance(validated, BacktestConfig)
        assert validated.timeframe == "1d"
        assert validated.symbols == ["005930"]

    @pytest.mark.parametrize("tf", ["1m", "5m", "15m", "1h", "1d"])
    def test_all_canonical_timeframes_pass(self, tf):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(timeframe=tf, symbols=["005930"]))
        assert validated.timeframe == tf

    def test_multiple_krx_symbols_pass(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(symbols=["005930", "000660", "035420"]))
        assert validated.symbols == ["005930", "000660", "035420"]


# ── [R1-F1] programmatic-only malformed 타입: TypeError 아닌 BacktestConfigError ──


class TestMalformedTypesEarlyFailAsConfigError:
    """raw dict 임의 타입 → BacktestConfigError (TypeError 아님)."""

    def test_timeframe_list_unhashable_rejected(self):
        """timeframe=[] (unhashable) → is_valid_timeframe 호출 전 차단."""
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
            svc._validate_config(_cfg(timeframe=[]))

    def test_timeframe_int_non_str_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
            svc._validate_config(_cfg(timeframe=1))

    def test_symbols_str_not_list_rejected(self):
        """symbols='005930' (str, list 아님) → BacktestConfigError."""
        svc = BacktestService()
        with pytest.raises(
            BacktestConfigError, match=r"Invalid symbols \(expected list"
        ):
            svc._validate_config(_cfg(symbols="005930"))

    def test_symbols_int_element_rejected_no_str_cast(self):
        """symbols=[593000] (int 원소) → BacktestConfigError.

        ``str(593000)="593000"`` 6자리 통과 우회가 없어야 한다 —
        SSOT non-str 가드 보존(str() 캐스팅 금지).
        """
        svc = BacktestService()
        with pytest.raises(
            BacktestConfigError, match=r"Invalid symbols \(expected list"
        ):
            svc._validate_config(_cfg(symbols=[593000]))


# ── [R2-F1] symbols None/누락/[] 정규화: no-symbols 정상 ─────────────────


class TestSymbolsNoneNormalization:
    """``{"symbols": None}`` /누락/``[]`` → BacktestConfig.symbols == []."""

    def test_explicit_none_normalized_to_empty(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(symbols=None))
        assert validated.symbols == []

    def test_missing_key_normalized_to_empty(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg())
        assert validated.symbols == []

    def test_explicit_empty_list_preserved(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(symbols=[]))
        assert validated.symbols == []


# ── invalid 시 backtest 실행/data load 미도달 (service.run early-raise) ────


def _patched_run_components():
    """run() 내부 data load 컴포넌트 patch — 도달 시 호출 추적."""
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


class TestServiceRunEarlyFailsBeforeDataLoad:
    """service.run(): invalid config → BacktestConfigError, data load 미도달."""

    @pytest.mark.asyncio
    async def test_invalid_timeframe_no_data_load(self):
        provider_instance, executor_instance = _patched_run_components()
        with (
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
            svc = BacktestService()
            with pytest.raises(BacktestConfigError):
                await svc.run(_cfg(timeframe="oracle-invalid"))

        mock_loader.load.assert_not_called()
        provider_instance.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_symbols_str_no_data_load(self):
        provider_instance, executor_instance = _patched_run_components()
        with (
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
            svc = BacktestService()
            with pytest.raises(BacktestConfigError):
                await svc.run(_cfg(symbols="005930"))

        mock_loader.load.assert_not_called()
        provider_instance.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_malformed_symbols_int_element_no_data_load(self):
        provider_instance, executor_instance = _patched_run_components()
        with (
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
            svc = BacktestService()
            with pytest.raises(BacktestConfigError):
                await svc.run(_cfg(symbols=[593000]))

        mock_loader.load.assert_not_called()
        provider_instance.load.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_config_reaches_data_load(self):
        """유효 config 회귀: run()이 정상적으로 data load까지 진행."""
        provider_instance, executor_instance = _patched_run_components()
        with (
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
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            result = await svc.run(_cfg(timeframe="1d", symbols=["005930"]))

        assert isinstance(result, BacktestResult)
        provider_instance.load.assert_called_once_with("005930", "1d")

    @pytest.mark.asyncio
    async def test_symbols_none_run_no_symbols_ok(self):
        """[R2-F1] {"symbols": None} → run() no-symbols 정상, data load 0."""
        provider_instance, executor_instance = _patched_run_components()
        with (
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
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            result = await svc.run(_cfg(symbols=None))

        assert isinstance(result, BacktestResult)
        # symbols None → [] 정규화 → 순회 0회 (TypeError 없음)
        provider_instance.load.assert_not_called()


class TestRunSubprocessEarlyFailsBeforeSpawn:
    """run_subprocess(): invalid → BacktestConfigError, subprocess 미기동."""

    @pytest.mark.asyncio
    async def test_invalid_krx_symbol_no_subprocess(self):
        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec"
        ) as mock_spawn:
            svc = BacktestService()
            with pytest.raises(BacktestConfigError):
                await svc.run_subprocess(_cfg(symbols=["ABCDEF"], exchange="KRX"))

        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_timeframe_no_subprocess(self):
        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec"
        ) as mock_spawn:
            svc = BacktestService()
            with pytest.raises(BacktestConfigError):
                await svc.run_subprocess(_cfg(timeframe="oracle-invalid"))

        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_symbols_none_run_subprocess_no_symbols_ok(self):
        """[R2-F1] {"symbols": None} → run_subprocess() 검증 통과(부모 prevalidate).

        부모 ``_validate_config`` 가 ``symbols=None`` 을 ``[]`` 로
        정규화하므로 ``BacktestConfigError`` /``TypeError`` 없이
        subprocess 기동 단계로 진행한다. (subprocess 자체는 무거우므로
        spawn을 patch해 검증 통과만 확인 — 부모-자식 경계 회귀.)
        """
        mock_proc = MagicMock()

        async def _fake_communicate(input=None):
            return (b'{"ok": true}', b"")

        mock_proc.communicate = _fake_communicate
        mock_proc.returncode = 0

        async def _fake_spawn(*args, **kwargs):
            return mock_proc

        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec",
            side_effect=_fake_spawn,
        ) as mock_spawn:
            svc = BacktestService()
            out = await svc.run_subprocess(_cfg(symbols=None))

        # 검증 통과 → subprocess 기동까지 도달 (early-raise 아님)
        mock_spawn.assert_called_once()
        assert out == {"ok": True}


# ── runner.run_backtest() → service.run() 동일 chokepoint ────────────────


class TestRunnerForwardsToValidateConfig:
    """runner.run_backtest()도 동일 _validate_config chokepoint 경유."""

    @pytest.mark.asyncio
    async def test_empty_segment_rejected_via_runner(self):
        with pytest.raises(BacktestConfigError, match="empty/blank"):
            await runner.run_backtest(_cfg(symbols=["005930", ""]))

    @pytest.mark.asyncio
    async def test_invalid_timeframe_rejected_via_runner(self):
        with pytest.raises(BacktestConfigError, match="Invalid timeframe"):
            await runner.run_backtest(_cfg(timeframe="oracle-invalid"))
