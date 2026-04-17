# DataStore 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 개요

DataStore는 **시세·재무 데이터의 저장·정규화·조회·관리를 담당하는 유일한 Parquet 접근 계층**이다.
모든 데이터 쓰기(실시간 수집, 배치 수집, 수동 주입)와 읽기(백테스트, 전략, CLI)는 이 계층을 경유한다.

```
                          DataStore (ante.data)
                    ┌─────────────────────────────┐
  쓰기              │  schemas    (스키마 원본)     │              읽기
  ───────────────→  │  normalizer (정규화 통합)     │  ←───────────────
                    │  store      (ParquetStore)   │
  · Collector       │  retention  (보존 정책)       │  · Backtest Engine
    (실시간)        │  collector  (실시간 수집)     │  · LiveDataProvider
  · DataFeed        └─────────────────────────────┘  · Strategy
    (배치+수동주입)                                    · CLI
```

**주요 기능**:
- **ParquetStore**: Parquet 파일 읽기/쓰기/검증 — 모든 데이터 접근의 단일 진입점. `data_type` 파라미터로 OHLCV/fundamental/tick 등 다중 스키마 지원
- **Normalizer**: 모든 소스(KIS, Yahoo, DataGoKr, DART 등)의 데이터를 통일된 스키마로 정규화
- **DataCollector**: 봇 운영 중 APIGateway 경유 실시간 시세 수집 → ParquetStore 적재 (1d 미만만)

- **RetentionPolicy**: 보존 정책 기반 용량 관리
