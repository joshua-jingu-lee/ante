# Config 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/config/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, D-011

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[config.md](config.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [config.md](config.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [config.md](config.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-system-initialization.md](04-system-initialization.md) | 시스템 초기화 순서에서의 위치 |
| [05-broker-to-account-migration.md](05-broker-to-account-migration.md) | Broker → Account 마이그레이션 |
| [07-cross-module-notes.md](07-cross-module-notes.md) | 타 모듈 설계 시 참고 |
