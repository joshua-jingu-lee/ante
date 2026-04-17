# Config 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/config/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, D-011

이 문서는 분할된 `config` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-system-initialization.md](04-system-initialization.md) | 시스템 초기화 순서에서의 위치 |
| [05-broker-to-account-migration.md](05-broker-to-account-migration.md) | Broker → Account 마이그레이션 |
| [06-open-issues.md](06-open-issues.md) | 미결 사항 |
| [07-cross-module-notes.md](07-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 설계 결정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 계층별 역할

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 1. 정적 설정 — TOML 파일 (`config/system.toml`)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 2. 비밀값 — `.env` 파일 (`config/secrets.env`)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 3. 동적 설정 — SQLite (`dynamic_config` 테이블)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### SystemState — 킬 스위치(Trading State) 관리

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### TradingState Enum

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 동적 설정 변경 알림 흐름

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Config 클래스

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### resolve_config_dir()

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### DynamicConfigService

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 설정 유효성 검증

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 기본값 전략

상세 내용: [03-design-decisions.md](03-design-decisions.md)

## 시스템 초기화 순서에서의 위치

상세 내용: [04-system-initialization.md](04-system-initialization.md)

## Broker → Account 마이그레이션

상세 내용: [05-broker-to-account-migration.md](05-broker-to-account-migration.md)

## 미결 사항

상세 내용: [06-open-issues.md](06-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [07-cross-module-notes.md](07-cross-module-notes.md)
