# Account 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/account/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 계좌 관리, [bot.md](../bot/bot.md) 봇 모듈, [treasury.md](../treasury/treasury.md) 자금 관리, [broker-adapter.md](../broker-adapter/broker-adapter.md) 브로커 어댑터

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[account.md](account.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [account.md](account.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [account.md](account.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-data-model.md](03-data-model.md) | 데이터 모델 |
| [04-account-service.md](04-account-service.md) | AccountService 인터페이스 |
| [05-eventbus-integration.md](05-eventbus-integration.md) | EventBus 연동 |
| [06-database-schema.md](06-database-schema.md) | 데이터베이스 스키마 |
| [07-account-layout-v1.md](07-account-layout-v1.md) | 1.0 시점 계좌 구성 |
| [08-config-migration.md](08-config-migration.md) | config/defaults.py 마이그레이션 |
| [09-cli.md](09-cli.md) | CLI 인터페이스 |
| [10-web-api.md](10-web-api.md) | Web API 엔드포인트 |
| [11-scope-out.md](11-scope-out.md) | Scope Out (1.0에서 제외) |
| [13-cross-module-notes.md](13-cross-module-notes.md) | 타 모듈 설계 시 참고 |
| [14-account-id-contract.md](14-account-id-contract.md) | Account ID 형식·정책 계약 (helper SSOT) |
