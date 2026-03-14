"""IndicatorCalculator 단위 테스트."""

import polars as pl
import pytest

from ante.strategy.indicators import (
    INDICATOR_REGISTRY,
    TALIB_AVAILABLE,
    IndicatorCalculator,
    ohlcv_to_numpy,
)

# ── IndicatorCalculator ──


def test_supported_indicators_returns_all_registered():
    """지원 지표 목록이 레지스트리와 일치한다."""
    supported = IndicatorCalculator.supported_indicators()
    assert set(supported) == set(INDICATOR_REGISTRY.keys())
    assert len(supported) >= 15


def test_supported_indicators_sorted():
    """지원 지표 목록이 정렬되어 있다."""
    supported = IndicatorCalculator.supported_indicators()
    assert supported == sorted(supported)


def test_is_available_matches_import():
    """is_available()이 실제 import 상태와 일치한다."""
    assert IndicatorCalculator.is_available() == TALIB_AVAILABLE


def test_registry_has_required_indicators():
    """대표 10종 지표가 레지스트리에 포함되어 있다."""
    required = {
        "sma",
        "ema",
        "rsi",
        "macd",
        "bbands",
        "atr",
        "stoch",
        "adx",
        "cci",
        "obv",
    }
    assert required.issubset(set(INDICATOR_REGISTRY.keys()))


def test_registry_entries_have_required_keys():
    """레지스트리 각 항목에 func, input, params 키가 존재한다."""
    for name, spec in INDICATOR_REGISTRY.items():
        assert "func" in spec, f"{name} missing 'func'"
        assert "input" in spec, f"{name} missing 'input'"
        assert "params" in spec, f"{name} missing 'params'"


def test_registry_input_types_valid():
    """레지스트리 input 타입이 유효한 값이다."""
    valid_types = {"close", "hlc", "close_volume", "hlcv"}
    for name, spec in INDICATOR_REGISTRY.items():
        msg = f"{name} has invalid input type: {spec['input']}"
        assert spec["input"] in valid_types, msg


# ── ohlcv_to_numpy ──


@pytest.mark.skipif(not TALIB_AVAILABLE, reason="numpy/TA-Lib not installed")
def test_ohlcv_from_list_of_dicts():
    """list[dict] → numpy 변환이 정상 동작한다."""
    import numpy as np_

    data = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1200},
    ]
    result = ohlcv_to_numpy(data)
    assert set(result.keys()) == {"open", "high", "low", "close", "volume"}
    np_.testing.assert_array_equal(result["close"], [105.0, 110.0])
    np_.testing.assert_array_equal(result["volume"], [1000.0, 1200.0])


@pytest.mark.skipif(not TALIB_AVAILABLE, reason="numpy/TA-Lib not installed")
def test_ohlcv_from_polars_dataframe():
    """polars DataFrame → numpy 변환이 정상 동작한다."""
    import numpy as np_

    df = pl.DataFrame(
        {
            "open": [100.0, 105.0],
            "high": [110.0, 115.0],
            "low": [90.0, 95.0],
            "close": [105.0, 110.0],
            "volume": [1000.0, 1200.0],
        }
    )
    result = ohlcv_to_numpy(df)
    assert set(result.keys()) == {"open", "high", "low", "close", "volume"}
    np_.testing.assert_array_equal(result["close"], [105.0, 110.0])


@pytest.mark.skipif(not TALIB_AVAILABLE, reason="numpy/TA-Lib not installed")
def test_ohlcv_empty_list_raises():
    """빈 리스트는 ValueError를 발생시킨다."""
    with pytest.raises(ValueError, match="Empty OHLCV data"):
        ohlcv_to_numpy([])


def test_ohlcv_without_numpy_raises_import_error():
    """numpy 미설치 시 ImportError를 발생시킨다."""
    if TALIB_AVAILABLE:
        pytest.skip("numpy is installed")
    with pytest.raises(ImportError, match="numpy is required"):
        ohlcv_to_numpy([{"close": 1.0}])


def test_compute_without_talib_raises_import_error():
    """TA-Lib 미설치 시 compute()가 ImportError를 발생시킨다."""
    if TALIB_AVAILABLE:
        pytest.skip("TA-Lib is installed")
    with pytest.raises(ImportError, match="TA-Lib is not installed"):
        IndicatorCalculator.compute("sma", {"close": []})


# ── StrategyContext.get_indicator fallback ──


async def test_context_get_indicator_fallback_without_talib():
    """TA-Lib 미설치 시 DataProvider에 위임한다."""
    if TALIB_AVAILABLE:
        pytest.skip("TA-Lib is installed")

    class FakeDataProvider:
        async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
            return []

        async def get_current_price(self, symbol):
            return 50000.0

        async def get_indicator(self, symbol, indicator, params=None):
            return {"fallback": True}

    class FakePortfolio:
        def get_positions(self, bot_id):
            return {}

        def get_balance(self, bot_id):
            return {}

    class FakeOrderView:
        def get_open_orders(self, bot_id):
            return []

    from ante.strategy.context import StrategyContext

    ctx = StrategyContext(
        bot_id="test-bot",
        data_provider=FakeDataProvider(),  # type: ignore[arg-type]
        portfolio=FakePortfolio(),  # type: ignore[arg-type]
        order_view=FakeOrderView(),  # type: ignore[arg-type]
    )
    result = await ctx.get_indicator("005930", "sma")
    assert result == {"fallback": True}
