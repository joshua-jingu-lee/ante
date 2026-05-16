# DataFeed 모듈 세부 설계 - 수집 범위

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 수집 범위

### Phase 1 — 국내 백테스트 기반 확보

> canonical symbol/timeframe 계약 SSOT: [core.md `## Canonical Symbol/Timeframe Vocabulary`](../core/core.md#canonical-symboltimeframe-vocabulary).
> 아래 표의 `API가 제공하는 모든 타임프레임`은 data.go.kr **source 가용성(source-capability)**
> 축이며 OHLCV bar timeframe vocabulary(축 A) 계약과 별개 차원이다(값 재정의 아님).

| 데이터 | 소스 | 비고 |
|--------|------|------|
| OHLCV + 거래대금 | data.go.kr | 주 소스 (일봉, API가 제공하는 모든 타임프레임) |
| 시가총액 + 상장주식수 | data.go.kr | OHLCV와 동시 수집 |
| 재무제표 (순이익, 자본총계 등) | DART OpenAPI | PER/PBR/EPS/BPS 계산용 |

### Phase 2 — 전략 다양화

| 데이터 | 소스 |
|--------|------|
| 수급 (투자자별/공매도/외국인) | pykrx |
| 기업 이벤트 (액면분할, 상장폐지 등) | DART OpenAPI |
