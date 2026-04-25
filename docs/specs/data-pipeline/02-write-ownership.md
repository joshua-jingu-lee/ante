# DataStore 모듈 세부 설계 - 쓰기 소유권

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 쓰기 소유권

같은 Parquet 파티션에 복수 모듈이 동시에 쓰면 데이터 유실 위험이 있다.
타임프레임·데이터 유형별로 **쓰기 소유권을 단일 모듈에 고정**하여 충돌을 원천 차단한다.

| 데이터 | 쓰기 소유자 | 쓰기 모드 | 근거 |
|--------|-----------|----------|------|
| OHLCV 일봉 (`1d`) | DataFeed | merge/dedup | data.go.kr에서 완전한 일봉을 수집, 더 높은 신뢰도 |
| OHLCV 분봉 (`1m`, `5m` 등, 1d 미만) | Collector | append | 실시간으로만 수집 가능, KIS API 경유 |
| `fundamental` | DataFeed | merge/dedup | 외부 API 배치 수집 전용 |
| `tick` | Collector | append | 실시간 전용 |

`flow`와 `event`는 1.0 쓰기 소유권 계약에 포함하지 않는다. `flow`는 pykrx Phase 2에서
수집 소스, 파티션 구조, 보존 정책을 함께 정의한다. `event`는 후속 데이터 확장 단계에서
별도 계약으로 정의한다.

> **쓰기 모드 정의**:
> - **merge/dedup**: 기존 월별 파티션과 새 데이터를 병합한 뒤 natural key
>   (`timestamp` 또는 `date`) 기준으로 중복을 제거하고 정렬한다. DataFeed가 사용한다.
>   같은 데이터를 재수집해도 중복 행이 누적되지 않으므로 재시도 시 안전하다.
>   값 정정을 위한 true partition replace는 1.0 계약에 포함하지 않는다.
> - **append**: 기존 데이터에 새 행을 추가. Collector가 사용. 중복 제거는 flush 시점에 수행.

**읽기는 제한 없음** — 모든 소비자(Backtest, DataProvider, Strategy, CLI)가 `ParquetStore.read()`로 통합 조회한다.
