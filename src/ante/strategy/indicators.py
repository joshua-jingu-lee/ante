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
        "params": {"length": 20, "lower_std": 2.0, "upper_std": 2.0},
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

# legacy/오명명 파라미터 키 블랙리스트 (#2404).
#
# pandas-ta 도입 이전 TA-Lib 규약의 키(timeperiod, nbdev, fastk/slowk/slowd)는
# pandas-ta 함수 시그니처에 존재하지 않아 `**kwargs`로 흡수된 뒤 조용히 무시된다
# (silent-drop). 사용자가 정식 키 대신 이 키를 전달하면 의도한 파라미터가
# 반영되지 않으므로, compute()가 pandas-ta 호출 전에 명시적으로 거부한다.
#
# 블랙리스트 방식 채택 근거: pandas-ta 15개 함수가 전부 `**kwargs`를 보유하고
# 일부 정당 파라미터(예: macd/rsi의 signal_indicators)가 named param이 아닌
# `kwargs.pop()`으로 처리되므로, allowlist는 정당 입력을 false-reject한다.
# 아래 키는 현재 15개 지표 어디에서도 유효하지 않아 전역 거부가 안전하다.
#
# 값: 정정 키 힌트 (에러 메시지에 노출).
_LEGACY_PARAM_KEYS: dict[str, str] = {
    "timeperiod": "length",
    "nbdev": "lower_std/upper_std (bbands)",
    "std": "lower_std/upper_std (bbands)",
    "fastk": "k (stoch)",
    "slowk": "smooth_k (stoch)",
    "slowd": "d (stoch)",
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
            데이터 부족 등으로 계산 불가 시(pandas-ta가 None 반환) 빈 dict ``{}``.

        Raises:
            ValueError: 미지원 지표, 필수 입력 누락, 또는 legacy/미인식
                파라미터 키(예: ``timeperiod``) 전달 (#2404 silent-drop 차단).
        """
        name_lower = name.lower()
        if name_lower not in INDICATOR_REGISTRY:
            supported = ", ".join(sorted(INDICATOR_REGISTRY.keys()))
            raise ValueError(f"Unknown indicator: {name}. Supported: {supported}")

        # legacy-key 블랙리스트 가드 (#2404): 사용자 전달 params에 pandas-ta가
        # 조용히 무시하는 TA-Lib 규약 키가 있으면 silent-drop 전에 거부한다.
        # 레지스트리 기본값(spec["params"])은 전부 정식 키이므로 검사 대상 아님.
        legacy = [key for key in params if key in _LEGACY_PARAM_KEYS]
        if legacy:
            hints = ", ".join(f"{key} -> {_LEGACY_PARAM_KEYS[key]}" for key in legacy)
            raise ValueError(
                f"Unrecognized indicator parameter key(s) for '{name}': "
                f"{', '.join(legacy)}. These keys are silently ignored by "
                f"pandas-ta. Use the correct key(s): {hints}."
            )

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

        # 데이터 부족 등으로 pandas-ta가 None을 반환하면 계산 불가 → 빈 dict.
        # 이 가드가 다중/단일 출력 두 None 경우를 한 곳에서 처리한다
        # (LiveDataProvider.get_indicator의 빈 OHLCV 동작과 동일 sentinel).
        if result is None:
            logger.warning("지표 계산 불가(데이터 부족/None 결과): %s", name_lower)
            return {}

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
