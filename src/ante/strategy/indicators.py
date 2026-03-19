"""pandas-ta 기반 기술 지표 계산기.

pandas-ta는 정규 의존성 — 항상 설치되어 있다.
지원 지표: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic,
           ADX, CCI, OBV, WMA, DEMA, TEMA, WILLR, MFI (15종).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)

# 지표별 pandas-ta 함수명, 입력 타입, 기본 파라미터
INDICATOR_REGISTRY: dict[str, dict[str, Any]] = {
    "sma": {"func": "sma", "input": "close", "params": {"length": 20}},
    "ema": {"func": "ema", "input": "close", "params": {"length": 20}},
    "rsi": {"func": "rsi", "input": "close", "params": {"length": 14}},
    "macd": {
        "func": "macd",
        "input": "close",
        "params": {"fast": 12, "slow": 26, "signal": 9},
    },
    "bbands": {
        "func": "bbands",
        "input": "close",
        "params": {"length": 20, "std": 2.0},
    },
    "atr": {"func": "atr", "input": "hlc", "params": {"length": 14}},
    "stoch": {
        "func": "stoch",
        "input": "hlc",
        "params": {
            "k": 14,
            "d": 3,
            "smooth_k": 3,
        },
    },
    "adx": {"func": "adx", "input": "hlc", "params": {"length": 14}},
    "cci": {"func": "cci", "input": "hlc", "params": {"length": 14}},
    "obv": {"func": "obv", "input": "close_volume", "params": {}},
    "wma": {"func": "wma", "input": "close", "params": {"length": 20}},
    "dema": {"func": "dema", "input": "close", "params": {"length": 20}},
    "tema": {"func": "tema", "input": "close", "params": {"length": 20}},
    "willr": {"func": "willr", "input": "hlc", "params": {"length": 14}},
    "mfi": {"func": "mfi", "input": "hlcv", "params": {"length": 14}},
}

# 다중 출력 지표의 결과 키 매핑
_MULTI_OUTPUT: dict[str, list[str]] = {
    "macd": ["macd", "signal", "hist"],
    "bbands": ["lower", "middle", "upper"],
    "stoch": ["slowk", "slowd"],
}


class IndicatorCalculator:
    """pandas-ta 래핑 기술 지표 계산기.

    사용법::

        calc = IndicatorCalculator()
        result = calc.compute("sma", ohlcv, length=50)
        # result == {"sma": np.ndarray}
    """

    @staticmethod
    def is_available() -> bool:
        """pandas-ta 설치 여부. 정규 의존성이므로 항상 True."""
        return True

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
            **params: pandas-ta 파라미터 오버라이드.

        Returns:
            결과 키 → numpy 배열 딕셔너리.
            단일 출력: ``{"sma": array}``.
            다중 출력: ``{"macd": array, "signal": array, "hist": array}``.

        Raises:
            ValueError: 미지원 지표 또는 필수 입력 누락.
        """
        name_lower = name.lower()
        if name_lower not in INDICATOR_REGISTRY:
            supported = ", ".join(sorted(INDICATOR_REGISTRY.keys()))
            raise ValueError(f"Unknown indicator: {name}. Supported: {supported}")

        spec = INDICATOR_REGISTRY[name_lower]
        merged_params = {**spec["params"], **params}

        input_type = spec["input"]
        func = getattr(ta, spec["func"])

        # pandas-ta 함수 호출
        if input_type == "close":
            close = pd.Series(ohlcv["close"], dtype=float)
            result = func(close, **merged_params)
        elif input_type == "hlc":
            high = pd.Series(ohlcv["high"], dtype=float)
            low = pd.Series(ohlcv["low"], dtype=float)
            close = pd.Series(ohlcv["close"], dtype=float)
            result = func(high, low, close, **merged_params)
        elif input_type == "close_volume":
            close = pd.Series(ohlcv["close"], dtype=float)
            volume = pd.Series(ohlcv["volume"], dtype=float)
            result = func(close, volume, **merged_params)
        elif input_type == "hlcv":
            high = pd.Series(ohlcv["high"], dtype=float)
            low = pd.Series(ohlcv["low"], dtype=float)
            close = pd.Series(ohlcv["close"], dtype=float)
            volume = pd.Series(ohlcv["volume"], dtype=float)
            result = func(high, low, close, volume, **merged_params)
        else:
            raise ValueError(f"Unknown input type: {input_type}")

        # 결과 포맷팅
        if name_lower in _MULTI_OUTPUT:
            keys = _MULTI_OUTPUT[name_lower]
            if isinstance(result, pd.DataFrame):
                arrays = [result.iloc[:, i].to_numpy() for i in range(len(keys))]
                return dict(zip(keys, arrays))
            return dict(zip(keys, [np.asarray(r) for r in result]))

        if isinstance(result, pd.DataFrame):
            # adx 등은 DataFrame으로 반환 — 첫 번째 컬럼 사용
            return {name_lower: result.iloc[:, 0].to_numpy()}

        if isinstance(result, pd.Series):
            return {name_lower: result.to_numpy()}

        return {name_lower: np.asarray(result)}


def ohlcv_to_dataframe(data: Any) -> dict[str, np.ndarray]:
    """OHLCV 데이터를 numpy 배열 딕셔너리로 변환.

    지원 입력 형식:
    - pandas DataFrame (columns: open, high, low, close, volume)
    - polars DataFrame (columns: open, high, low, close, volume)
    - list[dict] (각 dict에 open, high, low, close, volume 키)

    Returns:
        {"open": array, "high": array, "low": array,
         "close": array, "volume": array}

    Raises:
        ValueError: 변환 불가한 데이터 형식 또는 빈 데이터.
    """
    # pandas DataFrame
    if isinstance(data, pd.DataFrame):
        return {
            col: data[col].to_numpy().astype(float)
            for col in ("open", "high", "low", "close", "volume")
            if col in data.columns
        }

    # polars DataFrame
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

    # list[dict]
    if isinstance(data, list):
        if not data:
            raise ValueError("Empty OHLCV data")
        arrays: dict[str, Any] = {}
        for col in ("open", "high", "low", "close", "volume"):
            arrays[col] = np.array([float(row.get(col, 0.0)) for row in data])
        return arrays

    raise ValueError(
        f"Unsupported OHLCV data type: {type(data).__name__}. "
        "Expected pandas/polars DataFrame or list[dict]."
    )


# 하위 호환성을 위한 별칭
ohlcv_to_numpy = ohlcv_to_dataframe
