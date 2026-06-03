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

### Account-scoped 이벤트 marker (#1217 → #1240 SPLIT-1, #1242 SPLIT-3)

> 계약: [`docs/specs/account/14-account-id-contract.md`](../account/14-account-id-contract.md)

`Event` 기본 클래스에는 `_requires_account_id: ClassVar[bool] = False` marker가
있다. 하위 이벤트 클래스에서 `_requires_account_id: ClassVar[bool] = True` 로
override하면, `Event.__post_init__` 이 다음을 수행한다:

1. 인스턴스의 `account_id` 필드 값을 가져온다.
2. `ante.account.scoping.is_invalid_account_id` 로 검증한다.
3. invalid (`""`, `None`, `"default"`, 형식 위반) 면 `InvalidAccountIdError`
   를 raise한다.

**대상 (account-scoped event)**:
- 주문 흐름 전체: `OrderRequestEvent`, `OrderCancelEvent`, `OrderModifyEvent`,
  `OrderModifyRejectedEvent`, `OrderValidatedEvent`, `OrderRejectedEvent`,
  `OrderApprovedEvent`, `OrderSubmittedEvent`, `OrderFilledEvent`,
  `OrderCancelledEvent`, `OrderFailedEvent`
- Stop order / 취소 실패: `OrderCancelFailedEvent`, `StopOrderRegisteredEvent`,
  `StopOrderTriggeredEvent`, `StopOrderExpiredEvent`
- 봇 lifecycle: `BotStartedEvent`, `BotStopEvent`, `BotStoppedEvent`,
  `BotErrorEvent`, `BotStepCompletedEvent`, `BotRestartExhaustedEvent` —
  `BotStopEvent` (#2145) 는 봇 중지 요청으로, 발행자(`RuleEngine`)가
  봇 계좌(`RuleEngine._account_id`)를 명시 전달하며 `_requires_account_id`
  로 invalid fallback 을 차단한다.
- 계좌/잔고/리포트: `AccountSuspendedEvent`, `AccountActivatedEvent`,
  `BalanceSyncedEvent`, `DailyReportEvent`
- 실시간 스트림 (#1242 SPLIT-3): `StreamConnectedEvent`,
  `StreamDisconnectedEvent` — KIS multi-account 환경에서 각 계좌마다 별도의
  ``KISStreamClient`` 인스턴스가 발행하므로 `account_id` 가 명시 전달되어야
  한다 (한 계좌 disconnect 가 다른 계좌의 fallback 을 켜지 않도록 격리).
- 외부 시그널 (#2146): `ExternalSignalEvent` — 외부 AI Agent 시그널은
  대상 봇 계좌(`bot.config.account_id`)에 귀속된다. `SignalChannel` 이 봇
  계좌를 명시 전달하며, multi-account 환경에서 시그널을 account 기준으로
  감사/필터링/추적할 수 있도록 `_requires_account_id` 로 invalid fallback 을
  차단한다.
- 대사 (#2058): `PositionMismatchEvent`, `ReconcileEvent` — 포지션 대사
  결과는 대사 대상 계좌에 귀속된다. 발행자(`PositionReconciler.reconcile`)가
  reconcile 입력 `account_id` 를 명시 전달하며, multi-account 환경에서 불일치·
  보정 알림을 account 기준으로 추적할 수 있도록 `_requires_account_id` 로
  invalid fallback 을 차단한다. `reconcile()` 진입부에서
  `require_account_id` 로 valid 를 확정하므로 invalid account_id 는 이벤트
  발행 이전에 차단된다.

**비대상 (system-wide event)**:
- `SystemStartedEvent`, `SystemShutdownEvent`, `NotificationEvent`,
  `BacktestCompleteEvent`, `ConfigChangedEvent`, `ApprovalCreatedEvent`,
  `ApprovalResolvedEvent`, `MemberRegisteredEvent`, `MemberSuspendedEvent`,
  `MemberReactivatedEvent`, `MemberRevokedEvent`, `MemberAuthFailedEvent`,
  `MemberTokenRotatedEvent`, `MemberPasswordChangedEvent`,
  `MemberRecoveryKeyRegeneratedEvent`, `CircuitBreakerEvent`
- 멤버 보안 이벤트(`MemberTokenRotatedEvent`, `MemberPasswordChangedEvent`,
  `MemberRecoveryKeyRegeneratedEvent`)는 다른 Member 이벤트와 동일하게
  member-scoped 다 (`member_id` ≠ `account_id`). account marker
  (`_requires_account_id`) 를 적용하지 않으며, 발행자는 `MemberService` 다.

**구현 노트**:
- dataclass field ordering 제약 때문에 `account_id` 필드는 default `""` 를
  유지하지만, `__post_init__` 에서 strict 검증으로 빈 값/fallback 차단.
- 발행자가 명시적으로 `account_id=` 를 전달하지 않으면 즉시 raise되어
  silent fallback 제거.

### 이벤트 타입 전체 정의

D-005에서 정의한 EventBus 대상 이벤트. 모든 이벤트는 `Event`를 상속하며, `event_id`와 `timestamp`는 자동 생성된다.

> **order_id 규칙**: 내부 주문 ID = `str(OrderRequestEvent.event_id)`.
> 주문 흐름 전체에서 이 값이 `order_id`로 전달되며, 주문의 라이프사이클을 추적하는 키로 사용.
> 증권사가 반환하는 주문번호는 별도로 `broker_order_id` 필드에 저장.

> **구독자 열 표기**: 구독자 열은 해당 이벤트를 직접 `subscribe`하는 모듈을 나열한다. 단 `Notification`은 도메인 이벤트 자체를 구독한다는 뜻이 아니라, 그 이벤트가 **NotificationEvent 발행 경로를 통해 사용자 알림 대상이 됨**을 표기한 것이다(`NotificationService`는 `NotificationEvent`/`ConfigChangedEvent`만 직접 구독한다).

#### 주문 흐름 (Order Flow)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `OrderRequestEvent` | Bot | RuleEngine | `account_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `order_type`, `price?`, `stop_price?`, `reason`, `exchange` |
| `OrderCancelEvent` | Bot | APIGateway | `account_id`, `bot_id`, `strategy_id`, `order_id`, `reason` |
| `OrderModifyEvent` | Bot | RuleEngine | `account_id`, `bot_id`, `strategy_id`, `order_id`, `symbol`, `side`, `quantity`, `price?`, `reason` |
| `OrderModifyRejectedEvent` | RuleEngine | Bot | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `reason` |
| `OrderValidatedEvent` | RuleEngine | Treasury | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `stop_price?`, `reason`, `exchange` |
| `OrderRejectedEvent` | RuleEngine / Treasury | Bot, Notification | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `reason`, `exchange` |
| `OrderApprovedEvent` | Treasury | APIGateway | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price?`, `order_type`, `stop_price?`, `reserved_amount`, `exchange` |
| `OrderSubmittedEvent` | APIGateway | Bot, Trade | `account_id`, `order_id`, `bot_id`, `strategy_id`, `broker_order_id`, `symbol`, `side`, `quantity`, `order_type`, `exchange` |
| `OrderFilledEvent` | BrokerAdapter / FillApplier(outbox) | Bot, Treasury, Trade, Notification | `account_id`, `order_id`, `broker_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `requested_quantity`, `remaining_quantity`, `commission`, `order_type`, `reason`, `exchange`, `fill_dedup_key` |
| `OrderCancelledEvent` | BrokerAdapter | Bot, Treasury | `account_id`, `order_id`, `broker_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `reason`, `exchange` |
| `OrderFailedEvent` | BrokerAdapter | Bot, Treasury | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `order_type`, `error_message`, `error_code`, `exchange` |

**참고**: `OrderUpdateEvent`는 EventBus 발행 대상이 아닌, Bot 내부에서 `OrderSubmitted/Rejected/Cancelled/Failed` 이벤트를 전략의 `on_order_update()`에 통합 전달하기 위한 변환용 데이터 클래스이다.
핵심 필드: `order_id`, `bot_id`, `strategy_id`, `status` (`"submitted"` / `"rejected"` / `"cancelled"` / `"failed"`), `symbol`, `side`, `order_type`, `quantity`, `reason`, `exchange`.

#### 시스템 이벤트 (System)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `BotStartedEvent` | BotManager | — | `account_id`, `bot_id` |
| `BotStopEvent` | RuleEngine / 사용자 | BotManager | `account_id`, `bot_id`, `reason` |
| `BotStoppedEvent` | BotManager | — | `account_id`, `bot_id` |
| `BotErrorEvent` | BotManager | Notification | `account_id`, `bot_id`, `error_message` |
| `BotStepCompletedEvent` | Bot | — | `account_id`, `bot_id`, `result`, `message`, `signal_count`, `duration_ms` |
| `BotRestartExhaustedEvent` | BotManager | Notification | `account_id`, `bot_id`, `restart_attempts`, `last_error` |
| `SystemStartedEvent` | Main | — | `auto_started_bots` |
| `SystemShutdownEvent` | Main | 전체 | `reason` |

`TradingStateChangedEvent`는 legacy 이벤트이며 1.0 런타임 계약에서는 사용하지 않는다.
계좌별/전체 킬 스위치는 `AccountSuspendedEvent`와 `AccountActivatedEvent`로 표현한다.

#### 알림 (Notification)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `NotificationEvent` | 각 모듈 | NotificationService | `level` (`"critical"` / `"error"` / `"warning"` / `"info"`), `title`, `message`, `category`, `buttons?` |

#### 백테스트 (Backtest)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `BacktestCompleteEvent` | BacktestEngine | CLI, Notification | `backtest_id`, `strategy_id`, `status` (`"completed"`, 백테스트 성공 완료 시 발행), `result_path`, `error_message` |

#### 대사 (Reconciliation)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `PositionMismatchEvent` | PositionReconciler | Notification | `account_id`, `bot_id`, `symbol`, `internal_qty`, `broker_qty`, `reason` |
| `ReconcileEvent` | PositionReconciler | Notification | `account_id`, `bot_id`, `discrepancy_count`, `corrections` |

#### 외부 시그널 (External Signal)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ExternalSignalEvent` | SignalChannel | Bot | `account_id`, `bot_id`, `signal_id`, `symbol`, `action` (`"buy"` / `"sell"`), `reason`, `confidence`, `metadata`, `exchange` |

#### 설정 변경 (Config)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ConfigChangedEvent` | DynamicConfigService | 각 모듈 | `category`, `key`, `old_value`, `new_value`, `changed_by` |

#### 결재 (Approval)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `ApprovalCreatedEvent` | ApprovalService | Notification | `approval_id`, `approval_type`, `requester`, `title`, `auto_approved` |
| `ApprovalResolvedEvent` | ApprovalService | Bot, Notification | `approval_id`, `approval_type`, `resolution`, `resolved_by` |

#### 계좌 (Account)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `AccountSuspendedEvent` | AccountService | RuleEngine, Bot, Notification | `account_id`, `reason`, `suspended_by` |
| `AccountActivatedEvent` | AccountService | RuleEngine, Bot, Notification | `account_id`, `activated_by` |

`AccountCreatedEvent`와 `AccountDeletedEvent`는 1.0 런타임 EventBus 계약에 포함하지 않는다.
계좌 생성/삭제는 cold-path structural operation이며, 서버 실행 중 consumer topology를 hot wiring하지 않는다.

#### 멤버 (Member)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `MemberRegisteredEvent` | MemberService | Audit | `member_id`, `member_type`, `role`, `registered_by` |
| `MemberSuspendedEvent` | MemberService | SessionService, Notification | `member_id`, `suspended_by` |
| `MemberReactivatedEvent` | MemberService | Audit | `member_id`, `reactivated_by` |
| `MemberRevokedEvent` | MemberService | SessionService, Notification | `member_id`, `revoked_by` |
| `MemberTokenRotatedEvent` | MemberService | Audit | `member_id`, `rotated_by` |
| `MemberPasswordChangedEvent` | MemberService | SessionService, Notification | `member_id`, `changed_by`, `reason` |
| `MemberRecoveryKeyRegeneratedEvent` | MemberService | Notification | `member_id`, `regenerated_by` |
| `MemberAuthFailedEvent` | MemberService | Notification | `member_id`, `reason` |

Member 변경 이벤트는 서버 실행 중 CLI IPC 런타임 경로에서 발행한다.
서버 정지 상태의 maintenance fallback은 EventBus consumer를 호출하지 않으며, 감사 기록과
canonical DB 상태를 남긴 뒤 서버 재시작 시 반영된다.

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

### 체결 이벤트 전달 시맨틱: at-least-once (transactional outbox — #1949)

`EventBus.publish`는 fire-and-forget(인메모리, 핸들러 예외 swallow)이라 발행 직후
crash하면 이벤트가 유실된다. 체결(`OrderFilledEvent`)은 Treasury 정산·전략
`on_fill`·notification 등 다운스트림 효과가 있어, FillApplier 경로의 발행을
**transactional outbox**로 durable하게 만든다(#1949).

- **원자 기록**: `FillApplier`는 체결 적용 `Database.transaction()` 안에서
  `OrderFilledEvent` payload를 `fill_outbox` 테이블에 함께 커밋한다(recorded
  advance + trade + position과 동일 원자 경계). commit 성공 = 이벤트 영속 보장
  → commit↔publish 사이 crash window가 닫힌다(이벤트 무손실).
- **at-least-once 발행**: `FillOutboxPublisher` 워커가 미발행 row를 읽어
  **publish 성공 → mark published 순서**(역순 금지)로 발행하고, 기동 시 미발행분을
  재전달한다. publish↔mark 사이 micro-window에서 같은 이벤트가 **두 번 발행될 수
  있다**(at-least-once).
- **결정적 `fill_dedup_key`**: 모든 outbox 발행 이벤트는
  `fill_dedup_key = order_id:canonical(confirmed_cumulative)`(CAS로 확정된 누적
  체결량 기준)를 싣는다. 소비자가 at-least-once 재전달을 식별·멱등 처리하는 키다.
  outbox 미경유 직접 발행 경로(VirtualProvider)는 dedup 비대상이며 빈키(`""`)다.
- **소비자 멱등화 (#1957 완료)**: at-least-once 재전달 시 비멱등 소비자의
  이중처리는 #1957에서 `fill_dedup_key`를 소비해 소비자별로 해소했다. 정책은
  소비자 효과의 reversibility에 따라 두 단계로 나뉜다.
  - **Treasury = 진짜 exactly-once-effect**: `_on_order_filled`가 정산
    `Database.transaction()` **안에서** 전용 `treasury_fill_dedup`
    테이블(PK=`fill_dedup_key`)에 `INSERT OR IGNORE ... RETURNING`으로
    dedup-insert를 **가장 먼저** 수행하고, 행이 반환될 때만(신규) 정산한다
    (충돌=이미 처리=정산 0회 추가). dedup-insert ⟺ 정산이 단일 트랜잭션으로
    원자 결합되며, rollback 시 인메모리 `_budgets`/`_reservations`를
    진입 전 snapshot으로 복원해 메모리+DB split-brain을 막는다. DB-persisted라
    재기동 후에도 동작한다.
  - **Bot / SignalChannel / TradeRecorder = bounded dedup (best-effort)**:
    전략 follow-up·외부 JSON write·NotificationEvent 재발행은 외부/사용자 코드
    효과라 공유 `FillDedupGuard`(in-memory `deque(maxlen=512)` + `set` 미러)로
    비빈키 재전달을 억제한다. **known-limitation**: 프로세스 재기동 시 가드
    소실, `maxlen` 윈도우를 벗어난 재전달은 식별 못 함(이중 처리 가능).
    DB-persisted exactly-once로의 승격은 #1957 비목표이며 **follow-up 후보**다.
  - **Gateway = 무변경**: cache invalidate는 멱등이라 dedup 불필요.
  - **빈키(`""`) = dedup 비대상**: VirtualProvider 직접발행·FillApplier outbox
    미주입 fallback은 단발 in-memory 발행(재전달 없음)이라 네 소비자 모두
    빈키는 항상 처리한다(비빈키만 dedup).
  - #1949는 소비자 무변경(무손실 전달 + 결정적 키 제공까지)이었고, 소비는 #1957.

상세: `docs/specs/broker-adapter/18-fill-recovery.md` §10.

### Transient `_consumed` marker (Gateway-only stop, OrderModifyEvent — #1331)

`OrderModifyEvent`의 정정 라이프사이클에서 RuleEngine이 거부 결정을 내린 뒤
같은 이벤트를 후속 `APIGateway._on_order_modify`(priority=50)가 다시 처리하면
동일 정정 요청에 대해 `OrderModifyRejectedEvent`가 두 번(룰 거부 사유 +
`"modify_not_implemented"`) 발행되어 audit trail이 깨진다. 이를 막기 위해
RuleEngine은 거부/예외 경로에서 다음 marker를 set한다.

```python
object.__setattr__(event, "_consumed", True)
```

- **dataclass field가 아니다.** `Event`/`OrderModifyEvent`는 frozen
  dataclass이며 `_consumed`는 정의된 필드가 아니다. 따라서 `__setattr__`은
  `object.__setattr__`로 우회 주입해야 하고, dataclass 직렬화 경로
  (영속 history `event_log` payload, msgspec 기반 직렬화 등)에는
  노출되지 않는다.
- **본 PR의 적용 범위는 `OrderModifyEvent`의 gateway pass-through 차단에
  한정한다.** cancel 경로의 동일 결함은 별도 이슈에서 같은 패턴으로
  다룬다 (#1332).
- **Gateway-only stop marker 의미.** RuleEngine이 거부한 뒤 marker를
  set하면 `APIGateway._on_order_modify`(priority=50)는 추가 terminal
  event 발행을 건너뛴다. priority 50~100 사이의 audit/모니터링 subscriber
  (예: TradeRecorder, NotificationService 등)는 본 marker의 영향을 받지
  않으며, 자기 책임 영역에서 동일 이벤트를 정상 처리한다.
- **인메모리 history 노출 가능성.** `EventBus._history`는 같은 객체 참조를
  보존하므로, `_consumed=True`가 set된 이벤트가 `get_history()` 결과에서
  marker가 붙은 채 보일 수 있다. 영속 history(SQLite/middleware 직렬화)에는
  dataclass 필드가 아니므로 직렬화되지 않는다.
- **`EventBus.publish` 자체는 marker를 인식하지 않는다.** consumer가 직접
  `getattr(event, "_consumed", False)`로 확인할 책임이 있다. 새로운
  실행성 subscriber를 50~100 priority 대역에 추가할 때는, 거부된 이벤트도
  본인에게 도달할 수 있음을 인지하고 필요 시 marker를 명시적으로 확인
  하도록 설계한다.

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
- CLI/리포트에서 이벤트 타임라인 조회
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

#### 일일 리포트 (DailyReport)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `DailyReportEvent` | DailyReportScheduler | Treasury | `account_id`, `report_date`, `trade_count`, `has_trades`, `daily_pnl`, `daily_return`, `net_trade_amount`, `unrealized_pnl` |

#### Circuit Breaker

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `CircuitBreakerEvent` | KISAdapter | Notification | `broker`, `old_state`, `new_state`, `failure_count`, `reason` |

#### 주문 취소 실패

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `OrderCancelFailedEvent` | APIGateway | Bot | `account_id`, `order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `error_message` |

#### Stop Order

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `StopOrderRegisteredEvent` | StopOrderManager | Bot, SignalChannel | `account_id`, `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `order_type`, `stop_price`, `limit_price?` |
| `StopOrderTriggeredEvent` | StopOrderManager | Bot, SignalChannel | `account_id`, `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `side`, `quantity`, `trigger_price`, `converted_order_type` |
| `StopOrderExpiredEvent` | StopOrderManager | Bot, SignalChannel | `account_id`, `stop_order_id`, `bot_id`, `strategy_id`, `symbol`, `reason` |

> #1336: 위 세 이벤트는 모두 `_requires_account_id: ClassVar[bool] = True`
> 마커를 갖는 account-scoped 이벤트로, `account_id` 가 첫 데이터 필드이며
> `Event.__post_init__` 이 invalid fallback (`""`, `"default"`, 형식 위반)
> 을 거부한다. `BotManager` 가 본 이벤트들을 `Bot.on_order_update` 에
> 구독하여 전략 콜백 (`status="stop_registered" | "stop_triggered" |
> "stop_expired"`) 으로 변환하고, `SignalChannel` 도 외부 채널에 동일한
> `{type:"order_update", ...}` 메시지로 전달한다.
>
> `StopOrderExpiredEvent.reason` 허용 값 (현재 코드 기준):
>
> - `"session_ended"`: `check_session_expiry()` 가 거래 세션 종료를 감지하고
>   미트리거 주문을 만료시킬 때.
> - `"manager_stopped"`: `StopOrderManager.stop()` 이 매니저를 중지시키며
>   활성 주문을 일괄 만료시킬 때.
>
> 추후 `"manual_cancel"` 등 다른 reason 도입은 별도 이슈로 분리한다 (현재
> `cancel()` 은 expired event 를 발행하지 않음).

#### 실시간 스트림 (Stream)

| 이벤트 타입 | 발행자 | 구독자 | 핵심 필드 |
|------------|--------|--------|----------|
| `StreamConnectedEvent` | KISStreamClient | StreamIntegration | `account_id`, `broker`, `url` |
| `StreamDisconnectedEvent` | KISStreamClient | StreamIntegration | `account_id`, `broker`, `reason` |

> #1242 SPLIT-3: KIS multi-account 환경에서 각 계좌마다 별도의
> `KISStreamClient` 인스턴스가 만들어지고, 발행자는 자신의 `account_id` 를
> 명시 전달해야 한다. `StreamIntegration` 은 `event.account_id ==
> self._account_id` 일 때만 fallback toggle 을 변경하므로, 한 계좌의
> disconnect 가 다른 계좌의 stream 을 fallback 으로 끌고 가지 않는다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
