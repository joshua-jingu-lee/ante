# Treasury 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/treasury/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 자금 관리, [trade.md](../trade/trade.md) 포지션 관리

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [treasury.md](treasury.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [treasury.md](treasury.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-treasury-model.md](03-treasury-model.md) | 자금 관리 모델 |
| [04-treasury-interface.md](04-treasury-interface.md) | Treasury 인터페이스 |
| [05-treasury-manager.md](05-treasury-manager.md) | TreasuryManager |
| [06-database-schema.md](06-database-schema.md) | 데이터베이스 스키마 |
| [07-cli.md](07-cli.md) | CLI 인터페이스 |
| [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md) | 일별 자산 스냅샷 (Daily Asset Snapshot) |
| [09-virtual-asset-sync.md](09-virtual-asset-sync.md) | Virtual 모드 자산 평가 동기화 (D-TRS-01) |
| [10-open-issues.md](10-open-issues.md) | 미결 사항 |
| [11-cross-module-notes.md](11-cross-module-notes.md) | 타 모듈 설계 시 참고 |
