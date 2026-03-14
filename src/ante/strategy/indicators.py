"""TA-Lib 기반 기술 지표 계산기.

TA-Lib 선택 의존성 — 미설치 시 ImportError를 명확히 안내한다.
지원 지표: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic,
           ADX, CCI, OBV, WMA, DEMA, TEMA, WILLR, MFI (15종).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import talib

    TALIB_AVAILABLE = True
except ImportError:
    np = None  # type: ignore[assignment]
    talib = None  # type: ignore[assignment]
    TALIB_AVAILABLE = False

# 지표별 TA-Lib 함수명, 입력 타입, 기본 파라미터
INDICATOR_REGISTRY: dict[str, dict[str, Any]] = {
    "sma": {"func": "SMA", "input": "close", "params": {"timeperiod": 20}},
    "ema": {"func": "EMA", "input": "close", "params": {"timeperiod": 20}},
    "rsi": {"func": "RSI", "input": "close", "params": {"timeperiod": 14}},
    "macd": {
        "func": "MACD",
        "input": "close",
        "params": {"fastperiod": 12, "slowperiod": 26, "signalperiod": 9},
    },
    "bbands": {
        "func": "BBANDS",
        "input": "close",
        "params": {"timeperiod": 20, "nbdevup": 2.0, "nbdevdn": 2.0},
    },
    "atr": {"func": "ATR", "input": "hlc", "params": {"timeperiod": 14}},
    "stoch": {
        "func": "STOCH",
        "input": "hlc",
        "params": {
            "fastk_period": 14,
            "slowk_period": 3,
            "slowd_period": 3,
        },
    },
    "adx": {"func": "ADX", "input": "hlc", "params": {"timeperiod": 14}},
    "cci": {"func": "CCI", "input": "hlc", "params": {"timeperiod": 14}},
    "obv": {"func": "OBV", "input": "close_volume", "params": {}},
    "wma": {"func": "WMA", "input": "close", "params": {"timeperiod": 20}},
    "dema": {"func": "DEMA", "input": "close", "params": {"timeperiod": 20}},
    "tema": {"func": "TEMA", "input": "close", "params": {"timeperiod": 20}},
    "willr": {"func": "WILLR", "input": "hlc", "params": {"timeperiod": 14}},
    "mfi": {"func": "MFI", "input": "hlcv", "params": {"timeperiod": 14}},
}

# 다중 출력 지표의 결과 키 매핑
_MULTI_OUTPUT: dict[str, list[str]] = {
    "macd": ["macd", "signal", "hist"],
    "bbands": ["upper", "middle", "lower"],
    "stoch": ["slowk", "slowd"],
}


class IndicatorCalculator:
    """TA-Lib 래핑 기술 지표 계산기.

    사용법::

        calc = IndicatorCalculator()
        result = calc.compute("sma", ohlcv, timeperiod=50)
        # result == {"sma": np.ndarray}
    """

    @staticmethod
    def is_available() -> bool:
        """TA-Lib 설치 여부."""
        return TALIB_AVAILABLE

    @staticmethod
    def supported_indicators() -> list[str]:
        """지원 지표 이름 목록."""
        return sorted(INDICATOR_REGISTRY.keys())

    @staticmethod
    def compute(
        name: str,
        ohlcv: dict[str, np.ndarray],
        **params: Any,
    ) -> dict[str, np.ndarray]:
        """지표 계산.

        Args:
            name: 지표 이름 (예: "sma", "rsi", "macd").
            ohlcv: OHLCV numpy 배열 딕셔너리.
                   키: "open", "high", "low", "close", "volume".
            **params: TA-Lib 파라미터 오버라이드.

        Returns:
            결과 키 → numpy 배열 딕셔너리.
            단일 출력: ``{"sma": array}``.
            다중 출력: ``{"macd": array, "signal": array, "hist": array}``.

        Raises:
            ImportError: TA-Lib 미설치.
            ValueError: 미지원 지표 또는 필수 입력 누락.
        """
        if not TALIB_AVAILABLE:
            raise ImportError(
                "TA-Lib is not installed. "
                "Run 'scripts/install-talib.sh' to install the C library, "
                "then 'pip install TA-Lib'."
            )

        name_lower = name.lower()
        if name_lower not in INDICATOR_REGISTRY:
            supported = ", ".join(sorted(INDICATOR_REGISTRY.keys()))
            raise ValueError(f"Unknown indicator: {name}. Supported: {supported}")

        spec = INDICATOR_REGISTRY[name_lower]
        func = getattr(talib, spec["func"])
        merged_params = {**spec["params"], **params}

        input_type = spec["input"]
        if input_type == "close":
            result = func(ohlcv["close"], **merged_params)
        elif input_type == "hlc":
            result = func(ohlcv["high"], ohlcv["low"], ohlcv["close"], **merged_params)
        elif input_type == "close_volume":
            result = func(
                ohlcv["close"],
                ohlcv["volume"].astype(float),
                **merged_params,
            )
        elif input_type == "hlcv":
            result = func(
                ohlcv["high"],
                ohlcv["low"],
                ohlcv["close"],
                ohlcv["volume"].astype(float),
                **merged_params,
            )
        else:
            raise ValueError(f"Unknown input type: {input_type}")

        # 결과 포맷팅
        if name_lower in _MULTI_OUTPUT:
            keys = _MULTI_OUTPUT[name_lower]
            return dict(zip(keys, result))
        if isinstance(result, tuple):
            return {f"{name_lower}_{i}": r for i, r in enumerate(result)}
        return {name_lower: result}


def ohlcv_to_numpy(data: Any) -> dict[str, Any]:
    """OHLCV 데이터를 numpy 배열 딕셔너리로 변환.

    지원 입력 형식:
    - polars DataFrame (columns: open, high, low, close, volume)
    - list[dict] (각 dict에 open, high, low, close, volume 키)

    Returns:
        {"open": array, "high": array, "low": array,
         "close": array, "volume": array}

    Raises:
        ImportError: numpy 미설치.
        ValueError: 변환 불가한 데이터 형식 또는 빈 데이터.
    """
    if np is None:
        raise ImportError(
            "numpy is required for indicator computation. "
            "Install TA-Lib: scripts/install-talib.sh"
        )

    try:
        import polars as pl

        if isinstance(data, pl.DataFrame):
            return {
                col: data[col].to_numpy().astype(float)
                for col in ("open", "high", "low", "close", "volume")
                if col in data.columns
            }
    except ImportError:
        pass

    if isinstance(data, list):
        if not data:
            raise ValueError("Empty OHLCV data")
        arrays: dict[str, Any] = {}
        for col in ("open", "high", "low", "close", "volume"):
            arrays[col] = np.array([float(row.get(col, 0.0)) for row in data])
        return arrays

    raise ValueError(
        f"Unsupported OHLCV data type: {type(data).__name__}. "
        "Expected polars DataFrame or list[dict]."
    )
