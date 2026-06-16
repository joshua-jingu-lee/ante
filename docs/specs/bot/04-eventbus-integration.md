# Bot 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 이벤트 버스 연동 (EventBus Integration)

**발행하는 이벤트**:

| 이벤트 | 페이로드 | 발행 시점 |
|--------|----------|-----------|
| `BotStartedEvent` | `bot_id, account_id` | 봇 시작 시 |
| `BotStoppedEvent` | `bot_id, account_id` | 봇 중지 시 |
| `BotErrorEvent` | `bot_id, account_id, error_message` | 봇 에러 발생 시 |
| `BotStepCompletedEvent` | `bot_id, account_id, result, message, signal_count, duration_ms` | `_run_loop()` 매 사이클 완료 시 |
| `BotRestartExhaustedEvent` | `bot_id, account_id, restart_attempts, last_error` | 재시작 한도 소진 시 |
| `OrderRequestEvent` | `bot_id, account_id, strategy_id, symbol, side, quantity, order_type, price, stop_price, reason, exchange` | 전략 Signal → 신규 주문 요청. `exchange`는 Account에서 주입 |
| `OrderCancelEvent` | `bot_id, account_id, order_id, reason` | 전략 `ctx.cancel_order()` → 주문 취소 요청 |
| `OrderModifyEvent` | `bot_id, account_id, order_id, quantity, price, reason` | 전략 `ctx.modify_order()` → 주문 정정 요청. Bot은 이벤트를 발행하나 **broker-level 정정은 현재 미구현(deferred)**이라 룰 통과 시 Gateway가 `OrderModifyRejectedEvent`(`modify_not_implemented`)로 거부 (실 정정 연동은 #2391) |
| `NotificationEvent` | `level, title, message, category="bot"` | 봇 시작/중지/에러/재시작 한도 소진 시 |

### BotStepCompletedEvent

`_run_loop()`의 매 실행 사이클(on_step) 완료 시 발행한다. EventHistoryStore가 `event_log` 테이블에 자동 영속화하므로, 봇 실행 로그의 데이터 소스로 활용된다.

```python
@dataclass(frozen=True)
class BotStepCompletedEvent(Event):
    """Bot → EventBus: on_step() 1회 실행 완료."""
    account_id: str = ""
    bot_id: str = ""
    result: str = ""          # "success" | "timeout" | "signal_overflow" | "error"
    message: str = ""         # 실행 내역 설명
    signal_count: int = 0     # 발생한 시그널 수
    duration_ms: int = 0      # on_step() 실행 시간 (밀리초)
```

**발행 시나리오**:

| 시나리오 | result | message 예시 | signal_count |
|----------|--------|-------------|-------------|
| 정상 완료, 시그널 있음 | `success` | `시그널 분석 완료 — 매수 시그널 2건 감지` | 2 |
| 정상 완료, 시그널 없음 | `success` | `실행 사이클 완료 — 시그널 없음` | 0 |
| on_step 타임아웃 | `timeout` | `on_step 타임아웃 ({step_timeout_seconds}초 초과)` | 0 |
| 시그널 수 초과 | `signal_overflow` | `Signal 수 초과: {actual} > {max}` | actual |
| 예외 발생 | `error` | `예외: {error_message}` | 0 |

**구독하는 이벤트**:

| 이벤트 | 처리 | 전략 콜백 |
|--------|------|-----------|
| `OrderFilledEvent` | 체결 통보 수신 | `on_fill()` → 후속 Signal(손절/익절) 발행 |
| `OrderSubmittedEvent` | 주문 접수 통보 | `on_order_update()` (status="submitted") |
| `OrderRejectedEvent` | 주문 거부 통보 | `on_order_update()` (status="rejected") |
| `OrderCancelledEvent` | 주문 취소 통보 | `on_order_update()` (status="cancelled") |
| `OrderFailedEvent` | 주문 실패 통보 | `on_order_update()` (status="failed") |
| `OrderCancelFailedEvent` | 주문 취소 실패 통보 | `on_order_update()` (status="cancel_failed") |
| `OrderModifyRejectedEvent` | 주문 정정 거부 통보 (#1331) | `on_order_update()` (status="modify_rejected") |
| `StopOrderRegisteredEvent` | 스탑 주문 등록 통보 (#1336) | `on_order_update()` (status="stop_registered") |
| `StopOrderTriggeredEvent` | 스탑 주문 발동 통보 (#1336) | `on_order_update()` (status="stop_triggered") |
| `StopOrderExpiredEvent` | 스탑 주문 만료 통보 (#1336) | `on_order_update()` (status="stop_expired") |
| `ExternalSignalEvent` | 외부 AI Agent 시그널 | `on_data()` → Signal 발행 |
| `BotStopEvent` | RuleEngine 등에서 발행한 봇 중지 요청 | — (BotManager가 `stop_bot()` 호출) |
| `AccountSuspendedEvent` | 계좌 정지 시 해당 계좌의 봇만 중지 | — (BotManager가 계좌별 `stop_bot()` 호출) |
| `AccountActivatedEvent` | 계좌 재활성화 시 계좌 상태 변화 인지 | — (BotManager가 로깅만 수행; 자동 재시작은 수행하지 않음) |
| `BotErrorEvent` | 봇 에러 시 자동 재시작 정책 수행 | — (BotManager가 `_on_bot_error()` 처리) |

### 데몬-side SignalChannel 구독 (`signal.connect`, #2334)

`ante signal connect`(데몬-위임 스트리밍, #2334)가 활성화되면, 위 `OrderFilledEvent` 및 9종 `order_update` 이벤트(`OrderSubmittedEvent`/`OrderRejectedEvent`/`OrderCancelledEvent`/`OrderFailedEvent`/`OrderCancelFailedEvent`/`OrderModifyRejectedEvent`/`StopOrderRegisteredEvent`/`StopOrderTriggeredEvent`/`StopOrderExpiredEvent`)는 **데몬-resident `SignalChannel`이 동일한 `svc.eventbus` 인스턴스에서 추가로 구독**하여 connect된 외부 AI Agent에게 outbound 프레임(`fill`/`order_update`)으로 중계한다. 봇 본체의 전략 콜백(`on_fill()`/`on_order_update()`) 구독과 **같은 단일 데몬 EventBus** 위에서 병렬로 동작하며, 구독 위치만 데몬-side로 명시될 뿐 **이벤트 vocab·`order_update` 9종 status·`ExternalSignalEvent` flow는 변경 없다**(SSOT 재확인).

- 구독 대상(불변): `OrderFilledEvent → fill`, 9종 `order_update`(status vocab `submitted｜rejected｜cancelled｜failed｜cancel_failed｜modify_rejected｜stop_registered｜stop_triggered｜stop_expired`). `event.bot_id`가 connect된 봇과 일치하는 프레임만 중계.
- 인바운드 `ExternalSignalEvent`(위 표 참조)는 데몬 `svc.eventbus`에 publish되어 `bot.on_external_signal` → `strategy.on_data` 경로로 동일하게 처리된다.
- outbound 프레임 shape·delivery·backpressure 계약의 SSOT는 [`docs/specs/ipc/ipc.md`](../ipc/ipc.md)의 스트리밍 절이다(본 문서는 구독 대상 이벤트의 정합만 재확인).

> 이 데몬-side 구독 경로는 **구현 PR 머지 후(동기 버그 #2333 unblock)에만 실제 동작**한다. 본 절은 스펙 정합 재확인이며, 머지 전 `ante signal connect`는 아직 RUNNING 봇으로 연결되지 않는다.
