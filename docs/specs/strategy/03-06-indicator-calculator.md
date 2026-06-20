# Strategy 모듈 세부 설계 - 설계 결정 - IndicatorCalculator — pandas-ta 기반 기술 지표 계산

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# IndicatorCalculator — pandas-ta 기반 기술 지표 계산

구현: `src/ante/strategy/indicators.py` 참조

pandas-ta를 래핑하여 15종의 기술 지표를 계산한다. pandas-ta는 **정규 의존성**으로, 모든 환경에서 지표 계산이 가능하다.

**지원 지표** (15종):

파라미터 키는 pandas-ta 규약을 따른다 (TA-Lib의 `timeperiod`/`nbdev`/`fastk`/`slowk`/`slowd`가 아니다).

| 지표 | 함수 | 입력 | 기본 파라미터 |
|------|------|------|-------------|
| SMA | `sma` | close | length=20 |
| EMA | `ema` | close | length=20 |
| RSI | `rsi` | close | length=14 |
| MACD | `macd` | close | fast=12, slow=26, signal=9 |
| BBands | `bbands` | close | length=20, lower_std=2.0, upper_std=2.0 |
| ATR | `atr` | hlc | length=14 |
| Stochastic | `stoch` | hlc | k=14, d=3, smooth_k=3 |
| ADX | `adx` | hlc | length=14 |
| CCI | `cci` | hlc | length=14 |
| OBV | `obv` | close+volume | — |
| WMA | `wma` | close | length=20 |
| DEMA | `dema` | close | length=20 |
| TEMA | `tema` | close | length=20 |
| WILLR | `willr` | hlc | length=14 |
| MFI | `mfi` | hlcv | length=14 |

**주요 인터페이스**:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `is_available` | — | `bool` | pandas-ta 사용 가능 여부 |
| `supported_indicators` | — | `list[str]` | 지원 지표 목록 |
| `compute` | `name: str, ohlcv: dict[str, ndarray], **params` | `dict[str, ndarray]` | 지표 계산. 단일 출력: `{"sma": array}`, 다중: `{"macd": array, "signal": array, "hist": array}` |

데이터 부족 등으로 지표를 계산할 수 없으면(pandas-ta가 `None` 반환) `compute`는 빈 dict `{}`를 반환한다 (`LiveDataProvider.get_indicator`의 빈 OHLCV 동작과 동일 sentinel). 이 계약은 단일·다중 출력 지표 모두에 적용되며, 세 소비자(`StrategyContext` / `LiveDataProvider` / `BacktestDataProvider`)가 동일하게 안정적인 빈 결과를 받는다.

**compute 에러 계약**:

- 미지원 지표 이름 → `ValueError` (`Unknown indicator: ...`).
- legacy/미인식 파라미터 키 거부 → `ValueError`. pandas-ta가 조용히 무시하는 TA-Lib 규약 키(`timeperiod`, `nbdev`, `std`, `fastk`, `slowk`, `slowd`)를 사용자가 `params`로 전달하면, silent-drop을 막기 위해 정정 키 힌트를 담은 `ValueError`를 발생시킨다. 이 블랙리스트 키는 15종 지표 어디에서도 유효하지 않다. 단, 블랙리스트에 없는 임의 오타 키(예: `lenght`)는 여전히 silent-drop되며, 1차 방어는 위 파라미터 표와 계약 테스트(`tests/unit/contracts/test_indicator_param_drift.py`)다.

`ohlcv_to_numpy()` 유틸리티: polars DataFrame 또는 `list[dict]`를 numpy 배열 딕셔너리로 변환.

**설계 근거**:
- pandas-ta는 순수 Python 패키지로 C 라이브러리 설치가 불필요 — 환경 구성 단순화
- `StrategyContext.get_indicator()`가 내부에서 IndicatorCalculator를 사용하므로 전략 코드 변경 불필요
