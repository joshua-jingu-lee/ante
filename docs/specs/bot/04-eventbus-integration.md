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
| `OrderModifyEvent` | `bot_id, account_id, order_id, quantity, price, reason` | 전략 `ctx.modify_order()` → 주문 정정 요청 |
| `NotificationEvent` | `level, title, message, category="bot"` | 봇 시작/중지/에러/재시작 한도 소진 시 |

### BotStepCompletedEvent

`_run_loop()`의 매 실행 사이클(on_step) 완료 시 발행한다. EventHistoryStore가 `event_log` 테이블에 자동 영속화하므로, 대시보드 봇 실행 로그의 데이터 소스로 활용된다.

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
| `ExternalSignalEvent` | 외부 AI Agent 시그널 | `on_data()` → Signal 발행 |
| `BotStopEvent` | RuleEngine 등에서 발행한 봇 중지 요청 | — (BotManager가 `stop_bot()` 호출) |
| `TradingStateChangedEvent` | 킬 스위치 HALTED 시 전체 봇 중지 | — (BotManager가 `stop_all()` 호출) |
| `AccountSuspendedEvent` | 계좌 정지 시 해당 계좌의 봇만 중지 | — (BotManager가 계좌별 `stop_bot()` 호출) |
| `BotErrorEvent` | 봇 에러 시 자동 재시작 정책 수행 | — (BotManager가 `_on_bot_error()` 처리) |
