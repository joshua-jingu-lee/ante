# DataFeed 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/feed/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) §8 데이터 피드, [data-pipeline.md](../data-pipeline/data-pipeline.md) DataStore

이 문서는 분할된 `data-feed` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
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

## 개요

상세 내용: [01-overview.md](01-overview.md)

### DataStore와의 관계

상세 내용: [01-overview.md](01-overview.md)

### BrokerAdapter와의 관계

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 운영 모델 — DataStore 경유 저장

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 쓰기 소유권

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 활성화 모델

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 저장소 구조

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 설정 관리 — FeedConfig

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 설정 파일 형식

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 소스-거래소 관계 (N:N)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## 수집 범위

상세 내용: [03-collection-scope.md](03-collection-scope.md)

### Phase 1 — 국내 백테스트 기반 확보

상세 내용: [03-collection-scope.md](03-collection-scope.md)

### Phase 2 — 전략 다양화

상세 내용: [03-collection-scope.md](03-collection-scope.md)

## 스키마

상세 내용: [04-schema.md](04-schema.md)

### 파일 규격

상세 내용: [04-schema.md](04-schema.md)

## 데이터 소스

상세 내용: [05-data-sources.md](05-data-sources.md)

### data.go.kr — Phase 1 주력

상세 내용: [05-data-sources.md](05-data-sources.md)

### DART OpenAPI — 재무제표

상세 내용: [05-data-sources.md](05-data-sources.md)

### pykrx — 백업 / Phase 2

상세 내용: [05-data-sources.md](05-data-sources.md)

## CLI

상세 내용: [06-cli.md](06-cli.md)

### `ante feed init <data_path>`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed start`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed run backfill`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed run daily`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed status`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed config set <KEY> <VALUE>`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed config list`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed config check`

상세 내용: [06-cli.md](06-cli.md)

### `ante feed inject <path> --symbol <종목> [--timeframe <주기>] [--source <소스>]`

상세 내용: [06-cli.md](06-cli.md)

## 실행 모드

상세 내용: [07-execution-modes.md](07-execution-modes.md)

### `ante feed start` — 내장 스케줄러 (상주 프로세스)

상세 내용: [07-execution-modes.md](07-execution-modes.md)

### `ante feed run backfill` / `ante feed run daily` — one-shot 실행

상세 내용: [07-execution-modes.md](07-execution-modes.md)

### Backfill — 과거 데이터 대량 수집

상세 내용: [07-execution-modes.md](07-execution-modes.md)

### Daily Incremental — 일일 증분 수집

상세 내용: [07-execution-modes.md](07-execution-modes.md)

## 리소스 보호

상세 내용: [08-resource-protection.md](08-resource-protection.md)

### 1. 시간대 제한 (Trading Window Guard)

상세 내용: [08-resource-protection.md](08-resource-protection.md)

### 2. 프로세스 우선순위 (Nice)

상세 내용: [08-resource-protection.md](08-resource-protection.md)

### 3. 동시 실행 방지

상세 내용: [08-resource-protection.md](08-resource-protection.md)

## 장애 대응

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

### 재시도 전략

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

### Rate Limiting

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

### 데이터 검증 (4계층)

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

### 중복 제거

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

### 날짜/시간 처리

상세 내용: [09-failure-recovery.md](09-failure-recovery.md)

## 체크포인트 및 리포트

상세 내용: [10-checkpoints-and-reports.md](10-checkpoints-and-reports.md)

### 체크포인트

상세 내용: [10-checkpoints-and-reports.md](10-checkpoints-and-reports.md)

### 리포트

상세 내용: [10-checkpoints-and-reports.md](10-checkpoints-and-reports.md)

### 로깅

상세 내용: [10-checkpoints-and-reports.md](10-checkpoints-and-reports.md)

## 모듈 구조

상세 내용: [11-module-structure.md](11-module-structure.md)

### 의존성 흐름

상세 내용: [11-module-structure.md](11-module-structure.md)

### 모듈별 역할

상세 내용: [11-module-structure.md](11-module-structure.md)

## 미결 사항

상세 내용: [12-open-issues.md](12-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [13-cross-module-notes.md](13-cross-module-notes.md)
