# DataFeed 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 개요

DataFeed는 **외부 공공 API에서 과거 시세·재무 데이터를 배치 수집하는 ETL 파이프라인**이다.
자체 Parquet 구현 없이 DataStore(`ante.data`)를 통해 저장하며, 정규화도 DataStore의 Normalizer를 사용한다.

`pip install ante`에 항상 포함되며, `ante feed init`으로 활성화하기 전까지 비활성 상태이다.

```
[data.go.kr] ─┐                ┌───────────────────┐
[DART API]  ──┤── DataFeed ──→ │ DataStore          │
[pykrx]     ──┘   (Phase 2)   │  · ParquetStore    │
                               │  · Normalizer      │
                               └───────────────────┘
```

1.0 DataFeed 범위는 data.go.kr와 DART 기반의 국내 OHLCV 일봉·기초 재무 데이터 수집이다.
pykrx 기반 수급 데이터(`flow`)는 Phase 2 범위이며, DataStore의 쓰기·보존 계약도 그때 함께 확정한다.

### DataStore와의 관계

DataFeed는 DataStore의 **소비자**다. 저장과 정규화를 DataStore에 위임하고, 자체 책임은 수집·검증·오케스트레이션에 한정한다.

| 영역 | DataFeed 자체 책임 | DataStore에 위임 |
|------|-------------------|-----------------|
| 외부 API 호출 | sources/ (1.0: data.go.kr, DART / Phase 2: pykrx) | — |
| 정규화 | — | `ante.data.normalizer` (DataGoKrNormalizer, DARTNormalizer) |
| 데이터 검증 | transform/validate.py (4계층 검증) | — |
| Parquet 저장 | — | `ante.data.store.ParquetStore.write()` |
| 스키마 정의 | — | `ante.data.schemas` (OHLCV_SCHEMA, FUNDAMENTAL_SCHEMA) |
| ETL 오케스트레이션 | pipeline/orchestrator.py | — |
| 체크포인트 | pipeline/checkpoint.py | — |
| 리포트 | report/generator.py | — |
| Rate Limiting | sources/base.py (공공 API 전용) | — |

### BrokerAdapter와의 관계

DataFeed는 증권사 API(KIS)를 사용하지 않으며 APIGateway를 경유하지 않는다.
공공 데이터 API(data.go.kr, DART) 전용 Rate Limiter를 자체 보유한다.
