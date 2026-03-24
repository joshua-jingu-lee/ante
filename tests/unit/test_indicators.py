"""IndicatorCalculator 단위 테스트 (pandas-ta 기반)."""

import numpy as np
import pandas as pd
import polars as pl
import pytest

from ante.strategy.indicators import (
    INDICATOR_REGISTRY,
    IndicatorCalculator,
    ohlcv_to_dataframe,
    ohlcv_to_numpy,
)

# ── 테스트용 OHLCV 데이터 (50봉) ──


@pytest.fixture
def ohlcv_arrays() -> dict[str, np.ndarray]:
    """충분한 길이의 OHLCV numpy 배열."""
    rng = np.random.default_rng(42)
    n = 50
    close = 50000.0 + np.cumsum(rng.normal(0, 100, n))
    high = close + rng.uniform(50, 200, n)
    low = close - rng.uniform(50, 200, n)
    open_ = close + rng.normal(0, 50, n)
    volume = rng.uniform(1000, 10000, n)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


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


def test_is_available_always_true():
    """pandas-ta는 정규 의존성이므로 항상 True."""
    assert IndicatorCalculator.is_available() is True


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


def test_compute_unknown_indicator_raises(ohlcv_arrays: dict[str, np.ndarray]):
    """미지원 지표명에 ValueError를 발생시킨다."""
    with pytest.raises(ValueError, match="Unknown indicator"):
        IndicatorCalculator.compute("nonexistent", ohlcv_arrays)


# ── 단일 출력 지표 계산 ──


def test_compute_sma(ohlcv_arrays: dict[str, np.ndarray]):
    """SMA 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("sma", ohlcv_arrays, length=10)
    assert "sma" in result
    assert isinstance(result["sma"], np.ndarray)
    assert len(result["sma"]) == len(ohlcv_arrays["close"])


def test_compute_ema(ohlcv_arrays: dict[str, np.ndarray]):
    """EMA 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("ema", ohlcv_arrays, length=10)
    assert "ema" in result
    assert isinstance(result["ema"], np.ndarray)


def test_compute_rsi(ohlcv_arrays: dict[str, np.ndarray]):
    """RSI 계산이 0~100 범위 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("rsi", ohlcv_arrays, length=14)
    assert "rsi" in result
    valid = result["rsi"][~np.isnan(result["rsi"])]
    assert np.all(valid >= 0) and np.all(valid <= 100)


def test_compute_atr(ohlcv_arrays: dict[str, np.ndarray]):
    """ATR 계산이 양수 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("atr", ohlcv_arrays, length=14)
    assert "atr" in result
    valid = result["atr"][~np.isnan(result["atr"])]
    assert np.all(valid >= 0)


def test_compute_adx(ohlcv_arrays: dict[str, np.ndarray]):
    """ADX 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("adx", ohlcv_arrays, length=14)
    assert "adx" in result
    assert isinstance(result["adx"], np.ndarray)


def test_compute_cci(ohlcv_arrays: dict[str, np.ndarray]):
    """CCI 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("cci", ohlcv_arrays, length=14)
    assert "cci" in result
    assert isinstance(result["cci"], np.ndarray)


def test_compute_obv(ohlcv_arrays: dict[str, np.ndarray]):
    """OBV 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("obv", ohlcv_arrays)
    assert "obv" in result
    assert isinstance(result["obv"], np.ndarray)


def test_compute_wma(ohlcv_arrays: dict[str, np.ndarray]):
    """WMA 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("wma", ohlcv_arrays, length=10)
    assert "wma" in result
    assert isinstance(result["wma"], np.ndarray)


def test_compute_dema(ohlcv_arrays: dict[str, np.ndarray]):
    """DEMA 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("dema", ohlcv_arrays, length=10)
    assert "dema" in result


def test_compute_tema(ohlcv_arrays: dict[str, np.ndarray]):
    """TEMA 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("tema", ohlcv_arrays, length=10)
    assert "tema" in result


def test_compute_willr(ohlcv_arrays: dict[str, np.ndarray]):
    """Williams %R 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("willr", ohlcv_arrays, length=14)
    assert "willr" in result


def test_compute_mfi(ohlcv_arrays: dict[str, np.ndarray]):
    """MFI 계산이 numpy 배열을 반환한다."""
    result = IndicatorCalculator.compute("mfi", ohlcv_arrays, length=14)
    assert "mfi" in result


# ── 다중 출력 지표 계산 ──


def test_compute_macd(ohlcv_arrays: dict[str, np.ndarray]):
    """MACD 계산이 macd, signal, hist 키를 반환한다."""
    result = IndicatorCalculator.compute("macd", ohlcv_arrays)
    assert set(result.keys()) == {"macd", "signal", "hist"}
    for key in ("macd", "signal", "hist"):
        assert isinstance(result[key], np.ndarray)


def test_compute_bbands(ohlcv_arrays: dict[str, np.ndarray]):
    """Bollinger Bands 계산이 lower, middle, upper 키를 반환한다."""
    result = IndicatorCalculator.compute("bbands", ohlcv_arrays, length=20)
    assert set(result.keys()) == {"lower", "middle", "upper"}
    for key in ("lower", "middle", "upper"):
        assert isinstance(result[key], np.ndarray)


def test_compute_stoch(ohlcv_arrays: dict[str, np.ndarray]):
    """Stochastic 계산이 slowk, slowd 키를 반환한다."""
    result = IndicatorCalculator.compute("stoch", ohlcv_arrays)
    assert set(result.keys()) == {"slowk", "slowd"}


# ── ohlcv_to_dataframe / ohlcv_to_numpy ──


def test_ohlcv_from_list_of_dicts():
    """list[dict] -> numpy 변환이 정상 동작한다."""
    data = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
        {"open": 105, "high": 115, "low": 95, "close": 110, "volume": 1200},
    ]
    result = ohlcv_to_dataframe(data)
    assert set(result.keys()) == {"open", "high", "low", "close", "volume"}
    np.testing.assert_array_equal(result["close"], [105.0, 110.0])
    np.testing.assert_array_equal(result["volume"], [1000.0, 1200.0])


def test_ohlcv_from_polars_dataframe():
    """polars DataFrame -> numpy 변환이 정상 동작한다."""
    df = pl.DataFrame(
        {
            "open": [100.0, 105.0],
            "high": [110.0, 115.0],
            "low": [90.0, 95.0],
            "close": [105.0, 110.0],
            "volume": [1000.0, 1200.0],
        }
    )
    result = ohlcv_to_dataframe(df)
    assert set(result.keys()) == {"open", "high", "low", "close", "volume"}
    np.testing.assert_array_equal(result["close"], [105.0, 110.0])


def test_ohlcv_from_pandas_dataframe():
    """pandas DataFrame -> numpy 변환이 정상 동작한다."""
    df = pd.DataFrame(
        {
            "open": [100.0, 105.0],
            "high": [110.0, 115.0],
            "low": [90.0, 95.0],
            "close": [105.0, 110.0],
            "volume": [1000.0, 1200.0],
        }
    )
    result = ohlcv_to_dataframe(df)
    assert set(result.keys()) == {"open", "high", "low", "close", "volume"}
    np.testing.assert_array_equal(result["close"], [105.0, 110.0])


def test_ohlcv_empty_list_raises():
    """빈 리스트는 ValueError를 발생시킨다."""
    with pytest.raises(ValueError, match="Empty OHLCV data"):
        ohlcv_to_dataframe([])


def test_ohlcv_unsupported_type_raises():
    """지원하지 않는 타입은 ValueError를 발생시킨다."""
    with pytest.raises(ValueError, match="Unsupported OHLCV data type"):
        ohlcv_to_dataframe("invalid")


def test_ohlcv_to_numpy_is_alias():
    """ohlcv_to_numpy가 ohlcv_to_dataframe의 별칭이다."""
    assert ohlcv_to_numpy is ohlcv_to_dataframe


# ── StrategyContext.get_indicator (pandas-ta 기반) ──


async def test_context_get_indicator_computes_directly():
    """StrategyContext가 pandas-ta로 지표를 직접 계산한다."""

    class FakeDataProvider:
        async def get_ohlcv(
            self, symbol: str, timeframe: str = "1d", limit: int = 100
        ) -> pl.DataFrame:
            rng = np.random.default_rng(42)
            n = limit
            close = 50000.0 + np.cumsum(rng.normal(0, 100, n))
            high = close + rng.uniform(50, 200, n)
            low = close - rng.uniform(50, 200, n)
            open_ = close + rng.normal(0, 50, n)
            volume = rng.uniform(1000, 10000, n)
            return pl.DataFrame(
                {
                    "open": open_.tolist(),
                    "high": high.tolist(),
                    "low": low.tolist(),
                    "close": close.tolist(),
                    "volume": volume.tolist(),
                }
            )

        async def get_current_price(self, symbol: str) -> float:
            return 50000.0

        async def get_indicator(
            self, symbol: str, indicator: str, params: dict | None = None
        ) -> dict:
            return {"fallback": True}

    class FakePortfolio:
        def get_positions(self, bot_id: str) -> dict:
            return {}

        def get_balance(self, bot_id: str) -> dict:
            return {}

    class FakeOrderView:
        def get_open_orders(self, bot_id: str) -> list:
            return []

    from ante.strategy.context import StrategyContext

    ctx = StrategyContext(
        bot_id="test-bot",
        data_provider=FakeDataProvider(),  # type: ignore[arg-type]
        portfolio=FakePortfolio(),  # type: ignore[arg-type]
        order_view=FakeOrderView(),  # type: ignore[arg-type]
    )
    result = await ctx.get_indicator("005930", "sma", {"length": 10})
    assert "sma" in result
    assert isinstance(result["sma"], np.ndarray)


# ── LiveDataProvider 지표 계산 통합 테스트 ──


async def test_live_data_provider_get_indicator():
    """LiveDataProvider.get_indicator()가 pandas-ta로 지표를 계산한다."""

    class FakeGateway:
        async def get_ohlcv(
            self,
            symbol: str,
            timeframe: str = "1d",
            limit: int = 100,
        ) -> list[dict[str, float]]:
            rng = np.random.default_rng(42)
            n = limit
            close = 50000.0 + np.cumsum(rng.normal(0, 100, n))
            high = close + rng.uniform(50, 200, n)
            low = close - rng.uniform(50, 200, n)
            open_ = close + rng.normal(0, 50, n)
            volume = rng.uniform(1000, 10000, n)
            return [
                {
                    "open": float(open_[i]),
                    "high": float(high[i]),
                    "low": float(low[i]),
                    "close": float(close[i]),
                    "volume": float(volume[i]),
                }
                for i in range(n)
            ]

        async def get_current_price(self, symbol: str) -> float:
            return 50000.0

    from ante.gateway.data_provider import LiveDataProvider

    provider = LiveDataProvider(gateway=FakeGateway())  # type: ignore[arg-type]
    result = await provider.get_indicator("005930", "rsi", {"length": 14})
    assert "rsi" in result
    assert isinstance(result["rsi"], np.ndarray)


async def test_live_data_provider_get_indicator_empty_ohlcv():
    """OHLCV 데이터 없을 때 빈 딕셔너리를 반환한다."""

    class FakeGateway:
        async def get_ohlcv(
            self,
            symbol: str,
            timeframe: str = "1d",
            limit: int = 100,
        ) -> list:
            return []

        async def get_current_price(self, symbol: str) -> float:
            return 50000.0

    from ante.gateway.data_provider import LiveDataProvider

    provider = LiveDataProvider(gateway=FakeGateway())  # type: ignore[arg-type]
    result = await provider.get_indicator("005930", "sma")
    assert result == {}


async def test_live_data_provider_get_ohlcv():
    """LiveDataProvider.get_ohlcv()가 gateway를 경유하고 pl.DataFrame을 반환한다."""
    expected_data = [
        {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}
    ]

    class FakeGateway:
        async def get_ohlcv(
            self,
            symbol: str,
            timeframe: str = "1d",
            limit: int = 100,
        ) -> list:
            return expected_data

        async def get_current_price(self, symbol: str) -> float:
            return 50000.0

    from ante.gateway.data_provider import LiveDataProvider

    provider = LiveDataProvider(gateway=FakeGateway())  # type: ignore[arg-type]
    result = await provider.get_ohlcv("005930")
    assert isinstance(result, pl.DataFrame)
    assert result.to_dicts() == expected_data
