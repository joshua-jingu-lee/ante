# DataFeed 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/feed/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) §8 데이터 피드, [data-pipeline.md](../data-pipeline/data-pipeline.md) DataStore

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [data-feed.md](data-feed.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [data-feed.md](data-feed.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-collection-scope.md](03-collection-scope.md) | 수집 범위 |
| [04-schema.md](04-schema.md) | 스키마 |
| [05-data-sources.md](05-data-sources.md) | 데이터 소스 |
| [06-cli.md](06-cli.md) | CLI |
| [07-execution-modes.md](07-execution-modes.md) | 실행 모드 |
| [08-resource-protection.md](08-resource-protection.md) | 리소스 보호 |
| [09-failure-recovery.md](09-failure-recovery.md) | 장애 대응 |
| [10-checkpoints-and-reports.md](10-checkpoints-and-reports.md) | 체크포인트 및 리포트 |
| [11-module-structure.md](11-module-structure.md) | 모듈 구조 |
| [12-open-issues.md](12-open-issues.md) | 미결 사항 |
| [13-cross-module-notes.md](13-cross-module-notes.md) | 타 모듈 설계 시 참고 |
