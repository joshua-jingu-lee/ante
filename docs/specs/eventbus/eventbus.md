# EventBus 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/eventbus/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) EventBus 섹션, D-002, D-005

## 개요

EventBus는 Ante의 **핵심 이벤트 발행/구독 인프라**로, 모듈 간 느슨한 결합을 제공한다.
단일 asyncio 프로세스 내에서 동작하며, 1:N 브로드캐스트 성격의 이벤트를 처리한다.

**주요 기능**:
- **타입 기반 이벤트 라우팅**: frozen dataclass 이벤트를 타입으로 매칭하여 구독 핸들러에 전달
- **우선순위 기반 순차 실행**: 핸들러별 우선순위를 지정하여 실행 순서 제어 (예: RuleEngine → Treasury)
- **핸들러 에러 격리**: 한 핸들러의 예외가 다른 핸들러 실행을 차단하지 않음
- **이벤트 히스토리**: 인메모리 링버퍼(최근 N건) + SQLite 영속화로 감사/디버깅 지원

## 참고 구현체 분석

| 구현체 | 이벤트 정의 | 디스패치 | 우선순위 | 와일드카드 | 에러 처리 |
|--------|-----------|---------|---------|-----------|---------|
| NautilusTrader | Cython 타입 + 문자열 토픽 | 동기 콜백 | O (정수) | O (`*`, `?`) | 로깅 후 계속 |
| FreqTrade | StrEnum + dict | 브로드캐스트 | X | X | try/except per handler |
| pyee | 문자열 | 동기/비동기 혼합 | X | X | error 이벤트로 재발행 |

## 설계 결정

### 이벤트 기본 클래스: frozen dataclass

> 소스: [`src/ante/eventbus/events.py`](../../../src/ante/eventbus/events.py)

모든 이벤트는 `Event`를 상속하는 frozen dataclass이다. 기본 필드로 `event_id: UUID`와 `timestamp: datetime`이 자동 생성된다.

**근거**:
- `frozen=True`로 불변 보장 — 이벤트가 여러 핸들러에 전달되므로 변경 방지
- 타입 힌트로 IDE/Agent 자동완성 지원
- UUID + timestamp로 이벤트 추적/디버깅 용이
- dataclass는 외부 의존성 없음 (msgspec 등 도입은 성능 필요 시 전환)

### 이벤트 타입 전체 정의

D-005에서 정의한 EventBus 대상 이벤트. 모든 이벤트는 `Event`를 상속하며, `event_id`와 `timestamp`는 자동 생성된다.

> **order_id 규칙**: 내부 주문 ID = `str(OrderRequestEvent.event_id)`.
> 주문 흐름 전체에서 이 값이 `order_id`로 전달되며, 주문의 라이프사이클을 추적하는 키로 사용.
> 증권사가 반환하는 주문번호는 별도로 `broker_order_id` 필드에 저장.

#### 주문 흐름 (Order Flow)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `OrderRequestEvent` | Bot | RuleEngine | `account_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `order_type`, `price?`, `stop_price?`, `reason`, `exchange` |
| `OrderCancelEvent` | Bot | APIGateway | `account_id`, `bot_id`, `strategy_id`, `order_id`, `reason` |
| `OrderModifyEvent` | Bot | RuleEngine | `account_id`, `bot_id`, `strategy_id`, `order_id`, `quantity`, `price?`, `reason` |
| `OrderModifyRejectedEvent` | RuleEngine | Bot | `account_id`, `bot_id`, `strategy_id`, `order_id`, `reason` |
| `OrderValidatedEvent` | RuleEngine | Treasury | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `stop_price?`, `reason`, `exchange` |
| `OrderRejectedEvent` | RuleEngine / Treasury | Bot, Notification | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `reason`, `exchange` |
| `OrderApprovedEvent` | Treasury | APIGateway | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `stop_price?`, `reserved_amount`, `exchange` |
| `OrderSubmittedEvent` | APIGateway | Bot, Trade | `account_id`, `order_id`, `bot_id`, `strategy_id`, `broker_order_id`, `symbol`, `side`, `quantity`, `order_type`, `exchange` |
| `OrderFilledEvent` | BrokerAdapter | Bot, Treasury, Trade, Notification | `account_id`, `order_id`, `broker_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `requested_quantity`, `remaining_quantity`, `commission`, `order_type`, `reason`, `exchange` |
| `OrderCancelledEvent` | BrokerAdapter | Bot, Treasury | `account_id`, `order_id`, `broker_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `reason`, `exchange` |
| `OrderFailedEvent` | BrokerAdapter | Bot, Treasury | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `order_type`, `error_message`, `exchange` |

**참고**: `OrderUpdateEvent`는 EventBus 발행 대상이 아닌, Bot 내부에서 `OrderSubmitted/Rejected/Cancelled/Failed` 이벤트를 전략의 `on_order_update()`에 통합 전달하기 위한 변환용 데이터 클래스이다.
핵심 필드: `order_id`, `bot_id`, `strategy_id`, `status` (`"submitted"` / `"rejected"` / `"cancelled"` / `"failed"`), `symbol`, `side`, `order_type`, `quantity`, `reason`, `exchange`.

#### 시스템 이벤트 (System)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `BotStartedEvent` | BotManager | — | `account_id`, `bot_id` |
| `BotStopEvent` | RuleEngine / 사용자 | BotManager | `account_id`, `bot_id`, `reason` |
| `BotStoppedEvent` | BotManager | — | `account_id`, `bot_id` |
| `BotErrorEvent` | BotManager | Notification | `account_id`, `bot_id`, `error_message` |
| `BotRestartExhaustedEvent` | BotManager | Notification | `account_id`, `bot_id`, `restart_attempts`, `last_error` |
| `TradingStateChangedEvent` | AccountService | RuleEngine, Bot, Notification | `account_id`, `old_state`, `new_state` (`"active"` / `"halted"`), `reason`, `changed_by` |
| `SystemShutdownEvent` | Main | 전체 | `reason` |

#### 알림 (Notification)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `NotificationEvent` | 각 모듈 | NotificationService | `level` (`"critical"` / `"error"` / `"warning"` / `"info"`), `message`, `detail`, `metadata` |

#### 백테스트 (Backtest)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `BacktestCompleteEvent` | BacktestEngine | CLI, Notification | `backtest_id`, `strategy_id`, `status` (`"success"` / `"error"`), `result_path`, `error_message` |

#### 대사 (Reconciliation)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `PositionMismatchEvent` | PositionReconciler | Notification | `bot_id`, `symbol`, `internal_qty`, `broker_qty`, `reason` |
| `ReconcileEvent` | PositionReconciler | Notification | `bot_id`, `discrepancy_count`, `corrections` |

#### 외부 시그널 (External Signal)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ExternalSignalEvent` | REST API | Bot | `account_id`, `bot_id`, `signal_id`, `symbol`, `action` (`"buy"` / `"sell"`), `reason`, `confidence`, `metadata`, `exchange` |

#### 설정 변경 (Config)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ConfigChangedEvent` | WebAPI / CLI | 각 모듈 | `category`, `key`, `old_value`, `new_value`, `changed_by` |

#### 결재 (Approval)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ApprovalCreatedEvent` | ApprovalService | Notification | `approval_id`, `approval_type`, `requester`, `title` |
| `ApprovalResolvedEvent` | ApprovalService | Bot, Notification | `approval_id`, `approval_type`, `resolution`, `resolved_by` |

#### 계좌 (Account)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `AccountCreatedEvent` | AccountService | Notification | `account_id`, `exchange`, `currency`, `broker_type` |
| `AccountSuspendedEvent` | AccountService | RuleEngine, Bot, Notification | `account_id`, `reason` |
| `AccountActivatedEvent` | AccountService | RuleEngine, Bot, Notification | `account_id` |

#### 멤버 (Member)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `MemberRegisteredEvent` | MemberService | Notification | `member_id`, `member_type`, `role`, `registered_by` |
| `MemberSuspendedEvent` | MemberService | Notification | `member_id`, `suspended_by` |
| `MemberRevokedEvent` | MemberService | Notification | `member_id`, `revoked_by` |
| `MemberAuthFailedEvent` | MemberService | Notification | `member_id`, `reason` |

### 디스패치 방식: 타입 기반 동기 콜백

> 소스: [`src/ante/eventbus/bus.py`](../../../src/ante/eventbus/bus.py)

**EventBus 인터페이스**:

| 메서드 | 설명 |
|--------|------|
| `use(middleware)` | 글로벌 미들웨어 등록. 모든 이벤트에 대해 핸들러보다 먼저 호출 (로깅, SQLite 영속화 등) |
| `subscribe(event_type, handler, priority=0)` | 이벤트 타입에 핸들러 등록. priority가 높을수록 먼저 실행 |
| `unsubscribe(event_type, handler)` | 핸들러 등록 해제 |
| `publish(event)` | 이벤트를 모든 구독 핸들러에 순차 전달 + 히스토리 기록. 미들웨어 → 핸들러 순서 |
| `get_history(event_type=None, limit=100)` | 인메모리 이벤트 히스토리 조회. 특정 타입 필터링 가능, 최신순 반환 |
| `get_handlers(event_type)` | 특정 이벤트 타입의 등록된 핸들러 목록 반환 (`list[tuple[int, EventHandler]]`) |

**핵심 설계 결정:**

1. **타입 기반 라우팅 (NautilusTrader의 토픽 대신)**
   - 이벤트 수가 30여 개로 관리 가능한 수준 → 와일드카드/토픽 계층 불필요
   - Python 타입으로 매칭하면 IDE 자동완성, 타입 체크 지원
   - 필요 시 토픽 기반으로 전환 가능 (인터페이스 동일)

2. **동기 순차 실행 (fire-and-forget 아닌)**
   - 주문 흐름에서 순서 보장이 중요 (Request → Validated → Approved → Filled)
   - 핸들러가 await되므로 backpressure 유지
   - 단일 이벤트 루프에서 동작하므로 동시성 이슈 없음

3. **우선순위 지원**
   - RuleEngine이 Treasury보다 먼저 검증해야 하는 등 실행 순서 제어 필요
   - 정수 기반, 높을수록 먼저 실행 (NautilusTrader 패턴)
   - **권장 priority 대역**:

     | 대역 | 역할 | 모듈 예시 |
     |------|------|----------|
     | 100 | 룰 검증 (주문 차단 판단) | RuleEngine |
     | 80 | 자금 정산 (예약/해제/투입) | Treasury |
     | 60 | 거래 기록 + 포지션 갱신 | TradeRecorder |
     | 50 | 주문 실행 (증권사 전달) | APIGateway |
     | 40 | 전략 통보 (후속 주문 판단) | Bot |
     | 20 | 알림 발송 (부작용 없음) | NotificationService |
     | 0 | 기본값 (로깅, 모니터링) | — |

4. **핸들러별 에러 격리 (FreqTrade 패턴)**
   - 한 핸들러의 예외가 다른 핸들러 실행을 막지 않음
   - 예외 발생 시 로깅 후 다음 핸들러 계속 실행

### 와일드카드/토픽 계층은 도입하지 않음

**근거**:
- 현재 이벤트 수가 30여 개로 타입 매칭으로 충분
- 토픽 계층은 문자열 비교 오버헤드 + 오타 위험
- NautilusTrader는 수백 종목의 시세 이벤트를 처리하므로 와일드카드 필요, Ante는 그 규모가 아님
- 향후 이벤트가 크게 늘어나면 도입 검토

### 이벤트 히스토리 저장

> 소스: [`src/ante/eventbus/history.py`](../../../src/ante/eventbus/history.py)

디버깅 및 감사 목적으로 모든 이벤트를 기록한다.

**저장 전략**:
- **인메모리 링버퍼**: 최근 N건 (예: 1000건) 유지, 빠른 조회
- **SQLite 영속화**: `EventHistoryStore`를 EventBus 미들웨어(`bus.use(store.record)`)로 연결하여 모든 발행 이벤트를 `event_log` 테이블에 비동기 기록
  - 컬럼: `id` (PK), `event_id`, `event_type`, `timestamp`, `payload` (JSON), `created_at`
  - 인덱스: `idx_event_log_type` (event_type), `idx_event_log_timestamp` (timestamp)
  - 주문 관련 이벤트는 주문 추적/감사에 필수
- **보존 정책**: 30일 이상 이벤트는 주기적 삭제 (설정 가능)

**EventHistoryStore 인터페이스**:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | `None` | 스키마 생성 |
| `record` | `event: Event` | `None` | 이벤트를 event_log 테이블에 기록 (미들웨어로 등록) |
| `query` | `event_type: str? = None, since: datetime? = None, limit: int = 100` | `list[dict]` | 이벤트 로그 조회 (최신순) |
| `cleanup` | `retention_days: int = 30` | `int` | 보존 기간 초과 이벤트 삭제, 삭제 건수 반환 |

**활용**:
- 웹 대시보드에서 이벤트 타임라인 조회
- 주문 흐름 추적 (OrderRequest → ... → OrderFilled 전체 경로)
- 장애 분석 시 이벤트 재현

## 주문 흐름과 EventBus 상호작용

```
Bot.on_signal()
  └→ publish(OrderRequestEvent)              ← account_id 포함
       └→ RuleEngine.on_order_request()     [priority=100]
            ├→ 검증 실패: publish(OrderRejectedEvent)        ← account_id 전파
            └→ 검증 통과: publish(OrderValidatedEvent)       ← account_id 전파
                 └→ Treasury.on_order_validated()  [priority=50]
                      ├→ 자금 부족: publish(OrderRejectedEvent)    ← account_id 전파
                      └→ 자금 확보: publish(OrderApprovedEvent)    ← account_id 전파
                           └→ APIGateway.on_order_approved()
                                └→ BrokerAdapter.execute()         ← account_id로 계좌 식별
                                     └→ publish(OrderFilledEvent)  ← account_id 전파
                                          ├→ Bot.on_order_filled()
                                          ├→ Treasury.on_order_filled()
                                          └→ Notification.on_order_filled()
```

> **account_id 전파 규칙**: `OrderRequestEvent`에서 시작된 `account_id`는 주문 흐름의 모든 후속 이벤트에 그대로 전파된다. 각 핸들러는 수신한 이벤트의 `account_id`를 변경 없이 다음 이벤트로 전달한다.

#### 잔고 동기화 (Treasury)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `BalanceSyncedEvent` | Treasury | — | `account_id`, `account_balance`, `purchasable_amount`, `total_evaluation`, `external_purchase_amount`, `external_eval_amount` |

#### Circuit Breaker

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `CircuitBreakerEvent` | KISAdapter | Notification | `broker`, `old_state`, `new_state`, `failure_count`, `reason` |

#### 주문 취소 실패

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `OrderCancelFailedEvent` | APIGateway | Bot | `account_id`, `order_id`, `bot_id`, `strategy_id`, `error_message` |

#### Stop Order

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `StopOrderRegisteredEvent` | StopOrderManager | — | `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `order_type`, `stop_price`, `limit_price?` |
| `StopOrderTriggeredEvent` | StopOrderManager | — | `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `trigger_price`, `converted_order_type` |
| `StopOrderExpiredEvent` | StopOrderManager | — | `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `reason` |

#### 실시간 스트림 (Stream)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `StreamConnectedEvent` | KISStreamClient | — | `broker`, `url` |
| `StreamDisconnectedEvent` | KISStreamClient | — | `broker`, `reason` |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## 미결 사항

- [ ] `SystemStartedEvent` 신규 생성 ([#539](https://github.com/joshua-jingu-lee/ante/issues/539)) — 시스템 시작 완료 시 발행. 자동 재개 봇 수 등 포함 ([core.md](../core/core.md) 미결 사항 참조)
- [x] `NotificationEvent` 필드 확장 — `category` 필드 추가 완료. bot/trade/broker/approval/member/system 카테고리 사용 중
