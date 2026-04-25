# DataStore 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/data/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) §7 데이터 저장소, [data-feed.md](../data-feed/data-feed.md) 배치 수집, [api-gateway.md](../api-gateway/api-gateway.md) DataProvider

이 문서는 분할된 `data-pipeline` 스펙의 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
최신 계약 SSOT는 [README.md](README.md)의 문서 목록과 주제별 하위 문서다.
새 계약, 결정, 미결 사항은 이 파일에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-write-ownership.md](02-write-ownership.md) | 쓰기 소유권 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-dependencies.md](04-dependencies.md) | 의존 관계 |
| [05-datafeed-relationship.md](05-datafeed-relationship.md) | DataFeed와의 관계 |
| [07-cross-module-notes.md](07-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 쓰기 소유권

상세 내용: [02-write-ownership.md](02-write-ownership.md)

## 설계 결정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 데이터 스키마 (정규화된 형태)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Normalizer — 스키마 정규화

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Parquet 파일 구조

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### DataCollector — 실시간 데이터 수집

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### ParquetStore — Parquet 파일 관리

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 데이터 보존 정책

상세 내용: [03-design-decisions.md](03-design-decisions.md)

## 의존 관계

상세 내용: [04-dependencies.md](04-dependencies.md)

## DataFeed와의 관계

상세 내용: [05-datafeed-relationship.md](05-datafeed-relationship.md)


## 타 모듈 설계 시 참고

상세 내용: [07-cross-module-notes.md](07-cross-module-notes.md)
