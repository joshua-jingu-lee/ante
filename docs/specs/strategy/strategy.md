# Strategy 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/strategy/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, D-007, D-009, D-010

이 문서는 분할된 `strategy` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-examples.md](04-examples.md) | 사용 예시 |
| [05-testing.md](05-testing.md) | 테스트 고려사항 |
| [06-open-issues.md](06-open-issues.md) | 미결 사항 |
| [07-cross-module-notes.md](07-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 설계 결정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 전략 인터페이스 (Strategy ABC)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### StrategyMeta 핵심 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### exchange 필드 의미

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### Strategy ABC 메서드 시그니처

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Signal 핵심 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### OrderAction 핵심 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### DataProvider / PortfolioView / OrderView ABC

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### DataProvider 메서드 시그니처

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### TradeHistoryView 메서드 시그니처

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### PortfolioView 메서드 시그니처

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### OrderView 메서드 시그니처

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### StrategyContext — 전략에 노출되는 제한된 API

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### StrategyContext 추가 메서드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### IndicatorCalculator — pandas-ta 기반 기술 지표 계산

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### StrategySnapshot — 전략 파일 스냅샷 관리

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 전략 파일 동적 로딩

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### AST 기반 정적 검증 (StrategyValidator)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### ValidationResult 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Strategy Registry

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### StrategyStatus (StrEnum)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### StrategyRecord 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 전략 등록 플로우

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 전략 운용 방식

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 외부 시그널 채널

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 아웃소싱 전략 예시

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 봇의 전략 실행 흐름

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 성과 추적의 scoping

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 백테스트와의 관계

상세 내용: [03-design-decisions.md](03-design-decisions.md)

## 사용 예시

상세 내용: [04-examples.md](04-examples.md)

### CLI 사용 (Agent 워크플로우)

상세 내용: [04-examples.md](04-examples.md)

## 테스트 고려사항

상세 내용: [05-testing.md](05-testing.md)

## 미결 사항

상세 내용: [06-open-issues.md](06-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [07-cross-module-notes.md](07-cross-module-notes.md)
