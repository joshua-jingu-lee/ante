# DataStore 모듈 세부 설계 - 쓰기 소유권

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 쓰기 소유권

같은 Parquet 파티션에 복수 모듈이 동시에 쓰면 데이터 유실 위험이 있다.
타임프레임·데이터 유형별로 **쓰기 소유권을 단일 모듈에 고정**하여 충돌을 원천 차단한다.

| 데이터 | 쓰기 소유자 | 쓰기 모드 | 근거 |
|--------|-----------|----------|------|
| OHLCV 일봉 (`1d`) | DataFeed | overwrite (파티션 덮어쓰기) | data.go.kr에서 완전한 일봉을 수집, 더 높은 신뢰도 |
| OHLCV 분봉 (`1m`, `5m` 등, 1d 미만) | Collector | append | 실시간으로만 수집 가능, KIS API 경유 |
| `fundamental` | DataFeed | overwrite (파티션 덮어쓰기) | 외부 API 배치 수집 전용 |
| `flow`, `event` | DataFeed | overwrite | Phase 2 (pykrx 도입과 함께 결정) |
| `tick` | Collector | append | 실시간 전용 |

> **쓰기 모드 정의**:
> - **overwrite**: 파티션 단위로 기존 데이터를 완전 교체. DataFeed가 사용. 멱등성을 보장하므로 재시도 시 안전하다.
> - **append**: 기존 데이터에 새 행을 추가. Collector가 사용. 중복 제거는 flush 시점에 수행.

**읽기는 제한 없음** — 모든 소비자(Backtest, DataProvider, Strategy, CLI)가 `ParquetStore.read()`로 통합 조회한다.
