# DataStore 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/data/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) §7 데이터 저장소, [data-feed.md](../data-feed/data-feed.md) 배치 수집, [api-gateway.md](../api-gateway/api-gateway.md) DataProvider

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [data-pipeline.md](data-pipeline.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [data-pipeline.md](data-pipeline.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-write-ownership.md](02-write-ownership.md) | 쓰기 소유권 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-dependencies.md](04-dependencies.md) | 의존 관계 |
| [05-datafeed-relationship.md](05-datafeed-relationship.md) | DataFeed와의 관계 |
| [06-open-issues.md](06-open-issues.md) | 미결 사항 |
| [07-cross-module-notes.md](07-cross-module-notes.md) | 타 모듈 설계 시 참고 |
