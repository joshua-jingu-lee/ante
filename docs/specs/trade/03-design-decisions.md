# Trade 모듈 세부 설계 - 설계 결정


> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 설계 결정

이 문서는 분할된 `설계 결정` 섹션의 인덱스다.
세부 설계는 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [03-01-trade-record.md](03-01-trade-record.md) | 거래 기록 (TradeRecord) |
| [03-02-trade-recorder.md](03-02-trade-recorder.md) | TradeRecorder — 이벤트 기반 자동 기록 |
| [03-03-position-history.md](03-03-position-history.md) | PositionHistory — 포지션 변동 추적 |
| [03-04-performance-tracker.md](03-04-performance-tracker.md) | PerformanceTracker — 성과 지표 산출 |
| [03-05-sqlite-schema.md](03-05-sqlite-schema.md) | SQLite 스키마 |
| [03-06-trade-service.md](03-06-trade-service.md) | TradeService — 통합 인터페이스 |
| [03-07-position-reconciler.md](03-07-position-reconciler.md) | PositionReconciler — 포지션 정합성 검증 및 보정 |

### 거래 기록 (TradeRecord)

상세 내용: [03-01-trade-record.md](03-01-trade-record.md)

#### TradeType

상세 내용: [03-01-trade-record.md](03-01-trade-record.md)

#### TradeStatus

상세 내용: [03-01-trade-record.md](03-01-trade-record.md)

#### TradeRecord 필드

상세 내용: [03-01-trade-record.md](03-01-trade-record.md)

### TradeRecorder — 이벤트 기반 자동 기록

상세 내용: [03-02-trade-recorder.md](03-02-trade-recorder.md)

#### 퍼블릭 메서드

상세 내용: [03-02-trade-recorder.md](03-02-trade-recorder.md)

### PositionHistory — 포지션 변동 추적

상세 내용: [03-03-position-history.md](03-03-position-history.md)

#### PositionSnapshot 필드

상세 내용: [03-03-position-history.md](03-03-position-history.md)

#### 퍼블릭 메서드

상세 내용: [03-03-position-history.md](03-03-position-history.md)

### PerformanceTracker — 성과 지표 산출

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

#### PerformanceMetrics 필드

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

#### DailySummary 필드 (frozen dataclass)

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

#### MonthlySummary 필드 (frozen dataclass)

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

#### WeeklySummary 필드 (frozen dataclass)

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

#### 퍼블릭 메서드

상세 내용: [03-04-performance-tracker.md](03-04-performance-tracker.md)

### SQLite 스키마

상세 내용: [03-05-sqlite-schema.md](03-05-sqlite-schema.md)

### TradeService — 통합 인터페이스

상세 내용: [03-06-trade-service.md](03-06-trade-service.md)

#### 퍼블릭 메서드

상세 내용: [03-06-trade-service.md](03-06-trade-service.md)

### PositionReconciler — 포지션 정합성 검증 및 보정

상세 내용: [03-07-position-reconciler.md](03-07-position-reconciler.md)
