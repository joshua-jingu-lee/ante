# Strategy 모듈 세부 설계 - 설계 결정 - IndicatorCalculator — pandas-ta 기반 기술 지표 계산

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# IndicatorCalculator — pandas-ta 기반 기술 지표 계산

구현: `src/ante/strategy/indicators.py` 참조

pandas-ta를 래핑하여 15종의 기술 지표를 계산한다. pandas-ta는 **정규 의존성**으로, 모든 환경에서 지표 계산이 가능하다.

**지원 지표** (15종):

| 지표 | 함수 | 입력 | 기본 파라미터 |
|------|------|------|-------------|
| SMA | `SMA` | close | timeperiod=20 |
| EMA | `EMA` | close | timeperiod=20 |
| RSI | `RSI` | close | timeperiod=14 |
| MACD | `MACD` | close | fast=12, slow=26, signal=9 |
| BBands | `BBANDS` | close | timeperiod=20, nbdev=2.0 |
| ATR | `ATR` | hlc | timeperiod=14 |
| Stochastic | `STOCH` | hlc | fastk=14, slowk=3, slowd=3 |
| ADX | `ADX` | hlc | timeperiod=14 |
| CCI | `CCI` | hlc | timeperiod=14 |
| OBV | `OBV` | close+volume | — |
| WMA | `WMA` | close | timeperiod=20 |
| DEMA | `DEMA` | close | timeperiod=20 |
| TEMA | `TEMA` | close | timeperiod=20 |
| WILLR | `WILLR` | hlc | timeperiod=14 |
| MFI | `MFI` | hlcv | timeperiod=14 |

**주요 인터페이스**:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `is_available` | — | `bool` | pandas-ta 사용 가능 여부 |
| `supported_indicators` | — | `list[str]` | 지원 지표 목록 |
| `compute` | `name: str, ohlcv: dict[str, ndarray], **params` | `dict[str, ndarray]` | 지표 계산. 단일 출력: `{"sma": array}`, 다중: `{"macd": array, "signal": array, "hist": array}` |

`ohlcv_to_numpy()` 유틸리티: polars DataFrame 또는 `list[dict]`를 numpy 배열 딕셔너리로 변환.

**설계 근거**:
- pandas-ta는 순수 Python 패키지로 C 라이브러리 설치가 불필요 — 환경 구성 단순화
- `StrategyContext.get_indicator()`가 내부에서 IndicatorCalculator를 사용하므로 전략 코드 변경 불필요
