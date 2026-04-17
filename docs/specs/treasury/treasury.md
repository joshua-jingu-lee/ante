# Treasury 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/treasury/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 자금 관리, [trade.md](../trade/trade.md) 포지션 관리

이 문서는 분할된 `treasury` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
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

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 역할 범위

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## 자금 관리 모델

상세 내용: [03-treasury-model.md](03-treasury-model.md)

### 계층 구조

상세 내용: [03-treasury-model.md](03-treasury-model.md)

### BotBudget 필드

상세 내용: [03-treasury-model.md](03-treasury-model.md)

## Treasury 인터페이스

상세 내용: [04-treasury-interface.md](04-treasury-interface.md)

### 생성자

상세 내용: [04-treasury-interface.md](04-treasury-interface.md)

### 퍼블릭 메서드

상세 내용: [04-treasury-interface.md](04-treasury-interface.md)

### 프로퍼티

상세 내용: [04-treasury-interface.md](04-treasury-interface.md)

### get_summary() 반환값

상세 내용: [04-treasury-interface.md](04-treasury-interface.md)

## TreasuryManager

상세 내용: [05-treasury-manager.md](05-treasury-manager.md)

### 이벤트 연동

상세 내용: [05-treasury-manager.md](05-treasury-manager.md)

## 데이터베이스 스키마

상세 내용: [06-database-schema.md](06-database-schema.md)

## CLI 인터페이스

상세 내용: [07-cli.md](07-cli.md)

## 일별 자산 스냅샷 (Daily Asset Snapshot)

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 배경

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 데이터 정의

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 스냅샷 생성 시점

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 동일 날짜 중복 방지

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 일별 성과 필드

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 화면 연동

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 인터페이스

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 설계 결정

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

### 조회 인터페이스

상세 내용: [08-daily-asset-snapshots.md](08-daily-asset-snapshots.md)

## Virtual 모드 자산 평가 동기화 (D-TRS-01)

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### 배경

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### Live 모드가 브로커 API를 쓰는 이유

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### 해결 방향

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### 영향 범위

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### 스펙 변경

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

### 설계 원칙

상세 내용: [09-virtual-asset-sync.md](09-virtual-asset-sync.md)

## 미결 사항

상세 내용: [10-open-issues.md](10-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [11-cross-module-notes.md](11-cross-module-notes.md)
