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

import json
from unittest.mock import MagicMock, patch

import pytest

from ante.backtest import runner
from ante.backtest.config import BacktestConfig
from ante.backtest.exceptions import BacktestConfigError
from ante.backtest.result import BacktestResult
from ante.backtest.service import BACKTEST_RESULT_SENTINEL, BacktestService
from ante.strategy.validator import ValidationResult


def _bypass_validator():
    """service.run의 StrategyValidator 게이트(#2039)를 우회한다.

    유효 config가 data load까지 진행하는 회귀 테스트는 StrategyLoader를 mock해
    실제 전략 파일 없이 ``s.py`` 경로로 run을 구동하므로, load 직전 추가된 정적
    검증도 valid 결과로 대체한다. invalid-config 거부 테스트는 _validate_config
    단계에서 더 일찍 raise되므로 이 우회의 영향을 받지 않는다.
    """
    return patch(
        "ante.backtest.service.StrategyValidator.validate",
        return_value=ValidationResult(valid=True),
    )


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
            # runner가 결과 라인을 sentinel prefix로 출력(#2065)하는 것을
            # 모사한다. parent run_subprocess는 sentinel 라인만 파싱한다.
            line = f"{BACKTEST_RESULT_SENTINEL}{json.dumps({'ok': True})}\n"
            return (line.encode(), b"")

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


# ── exchange canonical 검증 (#2034) ──────────────────────────────────────


class TestValidateConfigRejectsInvalidExchange:
    """``_validate_config`` 가 canonical 아닌 exchange를 BacktestConfigError로.

    core.md ``## Canonical Exchange Vocabulary`` / D-016. programmatic dict는
    임의 값이 유입되므로 KRX-shape 블록이 읽기 전에 SSOT ``is_canonical`` 로
    canonical 5종을 강제한다. ``*`` 는 strategy 전용 wildcard라 거부.
    """

    @pytest.mark.parametrize("bad", ["INVALID", "*", "krx", "nyse"])
    def test_non_canonical_str_exchange_rejected(self, bad):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid exchange"):
            svc._validate_config(_cfg(exchange=bad))

    @pytest.mark.parametrize("bad", [123, None, ["KRX"], 1.5])
    def test_non_str_exchange_rejected(self, bad):
        """non-str(임의 타입)도 BacktestConfigError (TypeError 아님)."""
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid exchange"):
            svc._validate_config(_cfg(exchange=bad))

    @pytest.mark.parametrize("good", ["NYSE", "NASDAQ", "AMEX", "TEST"])
    def test_canonical_non_krx_exchange_passes(self, good):
        """canonical 5종 중 비-KRX → 통과 (symbol shape 미검증)."""
        svc = BacktestService()
        validated = svc._validate_config(_cfg(exchange=good, symbols=["AAPL"]))
        assert isinstance(validated, BacktestConfig)
        assert validated.exchange == good

    def test_canonical_krx_exchange_passes_with_valid_symbol(self):
        """KRX → 통과(회귀; 기존 KRX symbol shape 검증 유지되게 valid 6자리)."""
        svc = BacktestService()
        validated = svc._validate_config(_cfg(exchange="KRX", symbols=["005930"]))
        assert isinstance(validated, BacktestConfig)
        assert validated.exchange == "KRX"
        assert validated.symbols == ["005930"]


# ── date vocabulary 검증 (#2035) ─────────────────────────────────────────


class TestValidateConfigRejectsInvalidDate:
    """``_validate_config`` 가 invalid start_date/end_date를 BacktestConfigError로.

    required 검사가 존재를 보장하므로 shape(YYYY-MM-DD)·실재성·순서만 검증한다.
    """

    @pytest.mark.parametrize(
        "bad",
        [
            "20260510",  # 구분자 없음
            "2026-W19-1",  # ISO week shape (non-canonical)
            "2026/05/10",  # 잘못된 구분자
            "2026-5-1",  # zero-pad 안됨
            "2026-13-40",  # shape은 맞지만 비실재 월/일
        ],
    )
    def test_invalid_start_date_shape_rejected(self, bad):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid start_date"):
            svc._validate_config(_cfg(start_date=bad))

    @pytest.mark.parametrize("bad", [123, None, ["2026-01-01"]])
    def test_non_str_start_date_rejected(self, bad):
        """non-str(임의 타입)도 BacktestConfigError (TypeError 아님)."""
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid start_date"):
            svc._validate_config(_cfg(start_date=bad))

    def test_invalid_end_date_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid end_date"):
            svc._validate_config(_cfg(end_date="2026-13-40"))

    def test_start_after_end_rejected(self):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="is after"):
            svc._validate_config(_cfg(start_date="2026-05-20", end_date="2026-05-10"))

    def test_valid_date_range_passes(self):
        svc = BacktestService()
        validated = svc._validate_config(
            _cfg(start_date="2026-05-10", end_date="2026-05-20", symbols=["005930"])
        )
        assert validated.start_date == "2026-05-10"
        assert validated.end_date == "2026-05-20"

    def test_same_start_end_date_passes(self):
        """start == end 는 허용 (단일 날짜 백테스트)."""
        svc = BacktestService()
        validated = svc._validate_config(
            _cfg(start_date="2026-05-10", end_date="2026-05-10")
        )
        assert validated.start_date == "2026-05-10"


# ── numeric 검증 (#2036) ─────────────────────────────────────────────────


class TestValidateConfigRejectsInvalidNumeric:
    """``_validate_config`` 가 invalid 숫자 필드를 BacktestConfigError로.

    config에 **존재하는** 숫자 키만 검사하고 미존재는 BacktestConfig
    기본값(valid)을 따른다. bool은 int subclass라 명시 제외.
    """

    @pytest.mark.parametrize(
        "bad",
        [float("nan"), float("inf"), float("-inf"), 0, -1, "x", None, True],
    )
    def test_invalid_initial_balance_rejected(self, bad):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="initial_balance"):
            svc._validate_config(_cfg(initial_balance=bad))

    def test_valid_initial_balance_passes(self):
        svc = BacktestService()
        validated = svc._validate_config(_cfg(initial_balance=5_000_000.0))
        assert validated.initial_balance == 5_000_000.0

    @pytest.mark.parametrize(
        "bad",
        [-0.1, float("nan"), float("inf"), "x", None, True],
    )
    def test_invalid_buy_commission_rate_rejected(self, bad):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="buy_commission_rate"):
            svc._validate_config(_cfg(buy_commission_rate=bad))

    @pytest.mark.parametrize(
        "rate_key",
        ["buy_commission_rate", "sell_commission_rate", "slippage_rate"],
    )
    def test_zero_rate_passes(self, rate_key):
        """rate=0 은 허용 (allow_zero=True)."""
        svc = BacktestService()
        validated = svc._validate_config(_cfg(**{rate_key: 0}))
        assert getattr(validated, rate_key) == 0

    @pytest.mark.parametrize(
        "rate_key",
        ["sell_commission_rate", "slippage_rate"],
    )
    def test_negative_rate_rejected(self, rate_key):
        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match=rate_key):
            svc._validate_config(_cfg(**{rate_key: -0.1}))

    def test_missing_numeric_keys_use_defaults(self):
        """숫자 키 미존재 → BacktestConfig 기본값(valid) → 통과."""
        svc = BacktestService()
        validated = svc._validate_config(_cfg())
        assert validated.initial_balance == 10_000_000.0
        assert validated.buy_commission_rate == 0.00015
        assert validated.sell_commission_rate == 0.00195
        assert validated.slippage_rate == 0.001


# ── run_subprocess: invalid 3축 → subprocess 미기동 (#2034/#2035/#2036) ──


class TestRunSubprocessEarlyFailsOnNewAxes:
    """run_subprocess(): 신규 3축 invalid → BacktestConfigError, subprocess 미기동."""

    @pytest.mark.asyncio
    async def test_invalid_exchange_no_subprocess(self):
        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec"
        ) as mock_spawn:
            svc = BacktestService()
            with pytest.raises(BacktestConfigError, match="Invalid exchange"):
                await svc.run_subprocess(_cfg(exchange="INVALID"))

        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_date_no_subprocess(self):
        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec"
        ) as mock_spawn:
            svc = BacktestService()
            with pytest.raises(BacktestConfigError, match="Invalid start_date"):
                await svc.run_subprocess(_cfg(start_date="20260510"))

        mock_spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_initial_balance_no_subprocess(self):
        with patch(
            "ante.backtest.service.asyncio.create_subprocess_exec"
        ) as mock_spawn:
            svc = BacktestService()
            with pytest.raises(BacktestConfigError, match="initial_balance"):
                await svc.run_subprocess(_cfg(initial_balance=float("nan")))

        mock_spawn.assert_not_called()
