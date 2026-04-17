# Strategy 모듈 세부 설계 - 설계 결정


> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 설계 결정

이 문서는 분할된 `설계 결정` 섹션의 인덱스다.
세부 설계는 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [03-01-strategy-interface.md](03-01-strategy-interface.md) | 전략 인터페이스 (Strategy ABC) |
| [03-02-signal-fields.md](03-02-signal-fields.md) | Signal 핵심 필드 |
| [03-03-order-action-fields.md](03-03-order-action-fields.md) | OrderAction 핵심 필드 |
| [03-04-provider-and-views.md](03-04-provider-and-views.md) | DataProvider / PortfolioView / OrderView ABC |
| [03-05-strategy-context.md](03-05-strategy-context.md) | StrategyContext — 전략에 노출되는 제한된 API |
| [03-06-indicator-calculator.md](03-06-indicator-calculator.md) | IndicatorCalculator — pandas-ta 기반 기술 지표 계산 |
| [03-07-strategy-snapshot.md](03-07-strategy-snapshot.md) | StrategySnapshot — 전략 파일 스냅샷 관리 |
| [03-08-dynamic-loading.md](03-08-dynamic-loading.md) | 전략 파일 동적 로딩 |
| [03-09-strategy-validator.md](03-09-strategy-validator.md) | AST 기반 정적 검증 (StrategyValidator) |
| [03-10-strategy-registry.md](03-10-strategy-registry.md) | Strategy Registry |
| [03-11-registration-flow.md](03-11-registration-flow.md) | 전략 등록 플로우 |
| [03-12-runtime-model.md](03-12-runtime-model.md) | 전략 운용 방식 |
| [03-13-bot-execution-flow.md](03-13-bot-execution-flow.md) | 봇의 전략 실행 흐름 |
| [03-14-performance-scoping.md](03-14-performance-scoping.md) | 성과 추적의 scoping |
| [03-15-backtest-relationship.md](03-15-backtest-relationship.md) | 백테스트와의 관계 |

### 전략 인터페이스 (Strategy ABC)

상세 내용: [03-01-strategy-interface.md](03-01-strategy-interface.md)

#### StrategyMeta 핵심 필드

상세 내용: [03-01-strategy-interface.md](03-01-strategy-interface.md)

#### exchange 필드 의미

상세 내용: [03-01-strategy-interface.md](03-01-strategy-interface.md)

#### Strategy ABC 메서드 시그니처

상세 내용: [03-01-strategy-interface.md](03-01-strategy-interface.md)

### Signal 핵심 필드

상세 내용: [03-02-signal-fields.md](03-02-signal-fields.md)

### OrderAction 핵심 필드

상세 내용: [03-03-order-action-fields.md](03-03-order-action-fields.md)

### DataProvider / PortfolioView / OrderView ABC

상세 내용: [03-04-provider-and-views.md](03-04-provider-and-views.md)

#### DataProvider 메서드 시그니처

상세 내용: [03-04-provider-and-views.md](03-04-provider-and-views.md)

#### TradeHistoryView 메서드 시그니처

상세 내용: [03-04-provider-and-views.md](03-04-provider-and-views.md)

#### PortfolioView 메서드 시그니처

상세 내용: [03-04-provider-and-views.md](03-04-provider-and-views.md)

#### OrderView 메서드 시그니처

상세 내용: [03-04-provider-and-views.md](03-04-provider-and-views.md)

### StrategyContext — 전략에 노출되는 제한된 API

상세 내용: [03-05-strategy-context.md](03-05-strategy-context.md)

#### StrategyContext 추가 메서드

상세 내용: [03-05-strategy-context.md](03-05-strategy-context.md)

### IndicatorCalculator — pandas-ta 기반 기술 지표 계산

상세 내용: [03-06-indicator-calculator.md](03-06-indicator-calculator.md)

### StrategySnapshot — 전략 파일 스냅샷 관리

상세 내용: [03-07-strategy-snapshot.md](03-07-strategy-snapshot.md)

### 전략 파일 동적 로딩

상세 내용: [03-08-dynamic-loading.md](03-08-dynamic-loading.md)

### AST 기반 정적 검증 (StrategyValidator)

상세 내용: [03-09-strategy-validator.md](03-09-strategy-validator.md)

#### ValidationResult 필드

상세 내용: [03-09-strategy-validator.md](03-09-strategy-validator.md)

### Strategy Registry

상세 내용: [03-10-strategy-registry.md](03-10-strategy-registry.md)

#### StrategyStatus (StrEnum)

상세 내용: [03-10-strategy-registry.md](03-10-strategy-registry.md)

#### StrategyRecord 필드

상세 내용: [03-10-strategy-registry.md](03-10-strategy-registry.md)

### 전략 등록 플로우

상세 내용: [03-11-registration-flow.md](03-11-registration-flow.md)

### 전략 운용 방식

상세 내용: [03-12-runtime-model.md](03-12-runtime-model.md)

#### 외부 시그널 채널

상세 내용: [03-12-runtime-model.md](03-12-runtime-model.md)

#### 아웃소싱 전략 예시

상세 내용: [03-12-runtime-model.md](03-12-runtime-model.md)

### 봇의 전략 실행 흐름

상세 내용: [03-13-bot-execution-flow.md](03-13-bot-execution-flow.md)

### 성과 추적의 scoping

상세 내용: [03-14-performance-scoping.md](03-14-performance-scoping.md)

### 백테스트와의 관계

상세 내용: [03-15-backtest-relationship.md](03-15-backtest-relationship.md)
