# CLI 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/cli/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) CLI 인터페이스, D-007, D-010

이 문서는 분할된 `cli` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-commands.md](03-commands.md) | 커맨드 상세 |
| [04-agent-workflows.md](04-agent-workflows.md) | Agent 워크플로우 예시 |
| [05-open-issues.md](05-open-issues.md) | 미결 사항 |
| [06-cross-module-notes.md](06-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### CLI 프레임워크

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### OutputFormatter

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 인증 미들웨어

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 시스템 통신

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## 커맨드 상세

상세 내용: [03-commands.md](03-commands.md)

### `ante system` — 시스템 제어

상세 내용: [03-commands.md](03-commands.md)

### `ante account` — 계좌 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante bot` — 봇 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante trade` — 거래 이력

상세 내용: [03-commands.md](03-commands.md)

### `ante strategy` — 전략 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante treasury` — 자금 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante rule` — 거래 룰 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante broker` — 증권사 연동

상세 내용: [03-commands.md](03-commands.md)

### `ante data` — 데이터 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante backtest` — 백테스트

상세 내용: [03-commands.md](03-commands.md)

### `ante report` — 리포트

상세 내용: [03-commands.md](03-commands.md)

### `ante feed` — 데이터 피드 (DataFeed)

상세 내용: [03-commands.md](03-commands.md)

### `ante config` — 설정 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante approval` — 승인 요청 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante init` — 시스템 초기 설정

상세 내용: [03-commands.md](03-commands.md)

### `ante member` — 멤버(에이전트) 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante instrument` — 종목 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante notification` — 알림 관리

상세 내용: [03-commands.md](03-commands.md)

### `ante signal` — 외부 시그널 채널

상세 내용: [03-commands.md](03-commands.md)

## Agent 워크플로우 예시

상세 내용: [04-agent-workflows.md](04-agent-workflows.md)

## 미결 사항

상세 내용: [05-open-issues.md](05-open-issues.md)

### 스펙 미구현

상세 내용: [05-open-issues.md](05-open-issues.md)

### 백테스트·리포트 플로우 개선

상세 내용: [05-open-issues.md](05-open-issues.md)

### `ante init` 통합 초기 설정

상세 내용: [05-open-issues.md](05-open-issues.md)

### 구현되었으나 스펙 미반영

상세 내용: [05-open-issues.md](05-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [06-cross-module-notes.md](06-cross-module-notes.md)
