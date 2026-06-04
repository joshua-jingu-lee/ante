# Rule Engine 모듈 세부 설계 - RuleEngine 코어

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# RuleEngine 코어

> 소스: `src/ante/rule/engine.py`

RuleEngine은 룰을 로드하고 평가하는 메인 엔진입니다.

### 생성자

```python
RuleEngine(
    eventbus: EventBus,
    *,
    account_id: str,
    account_service: AccountService | None = None,
    bot_strategy_resolver: Callable[[str], str | None] | None = None,
    treasury: Treasury | None = None,
    trade_service: TradeService | None = None,
    account: Account | None = None,
    order_tracker: OrderTracker | None = None,
    unrecovered_buy_guard_min_age: float = 60.0,
    allow_unrecovered_buy_overlap: bool = False,
)
```

`eventbus`는 positional이고, 그 외 인자는 모두 keyword-only(`*,` 이후)입니다. `account_id`는 default fallback 없이 **필수**이며, 생성자 내부에서 `require_account_id(account_id, context="rule_engine.__init__")`로 즉시 검증됩니다 — 빈 값이나 `"default"` 같은 fallback은 거부됩니다.

### 의존성

- `EventBus`: 이벤트 구독/발행
- `AccountService`: 계좌 상태 조회/변경 (SUSPENDED 전환)

### 이벤트 구독

- `OrderRequestEvent` (priority=100): 주문 평가 — `event.account_id` 필터링 → **OrderRequestEvent preflight** (아래 소절 참조) → RuleContext 생성 → 계좌/전략별 룰 평가 → 결과 이벤트 발행
- `OrderModifyEvent` (priority=100): 주문 정정 평가 — `event.account_id` 필터링 → RuleContext 생성 → 계좌/전략별 룰 평가 → 결과 이벤트 발행. 거부 시 `OrderModifyRejectedEvent` 발행
- `ConfigChangedEvent`: 룰 설정 변경 감지. `category="rule"` + `key="accounts.{account_id}.rules"`이면 해당 계좌 엔진만 계좌 룰을 재로드하고, `category="strategy_rule"`이면 해당 전략 룰을 재로드한다.

### 룰 레지스트리

`RULE_REGISTRY`는 룰 타입 문자열을 클래스에 매핑한다:

| 타입 문자열 | 클래스 |
|------------|--------|
| `daily_loss_limit` | `DailyLossLimitRule` |
| `total_exposure_limit` | `TotalExposureLimitRule` |
| `trading_hours` | `TradingHoursRule` |
| `position_size` | `PositionSizeRule` |
| `unrealized_loss_limit` | `UnrealizedLossLimitRule` |
| `trade_frequency` | `TradeFrequencyRule` |

### 퍼블릭 메서드

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `start` | `(self) -> None` | EventBus 구독 등록 |
| `add_account_rule` | `(self, rule: Rule) -> None` | 계좌 룰 추가 (우선순위 정렬) |
| `add_strategy_rule` | `(self, strategy_id: str, rule: Rule) -> None` | 전략별 룰 추가 (우선순위 정렬) |
| `clear_rules` | `(self) -> None` | 모든 룰 제거 |
| `load_rules_from_config` | `(self, rule_configs: list[dict[str, Any]]) -> None` | 설정 리스트에서 계좌 룰 인스턴스 생성 |
| `load_strategy_rules_from_config` | `(self, strategy_id: str, rule_configs: list[dict[str, Any]]) -> None` | 설정 리스트에서 전략별 룰 인스턴스 생성 |
| `evaluate` | `(self, context: RuleContext) -> EvaluationResult` | 주문에 대한 룰 평가. 계좌 룰 → 전략별 순서 |
| `set_bot_strategy_resolver` | `(self, resolver: Callable[[str], str \| None]) -> None` | 봇 ID → 전략 ID 변환 콜백 설정. 초기화 후 BotManager 연결 시 호출 |
| `set_unrecovered_buy_overlap` | `(self, bot_id: str, allow: bool) -> None` | 봇 단위 `allow_unrecovered_buy_overlap` opt-out 등록 (#2315). 미등록 봇은 계좌 기본값 사용 |
| `update_rules` | `(self, bot_id: str, rules: list[dict]) -> None` | 봇의 거래 규칙 갱신. bot_strategy_resolver로 전략 ID 조회 후 룰 교체 |
| `remove_strategy_rules` | `(self, strategy_id: str) -> None` | 특정 전략의 룰 제거 |

### 주요 동작

- **이벤트 필터링**: `event.account_id != self._account_id`인 이벤트는 무시
- **평가 흐름**: RuleContext 생성 → 계좌 룰 평가 → 전략별 룰 평가 → 결과 통합 → 이벤트 발행
- **결과 발행**: PASS/WARN → `OrderValidatedEvent` 발행 (WARN 시 `NotificationEvent` 추가), BLOCK/REJECT → `OrderRejectedEvent` 발행 + 조치 실행
- **조치 실행**: `NOTIFY` → NotificationEvent, `STOP_BOT` → BotStopEvent, `HALT_ACCOUNT` → `AccountService.suspend(account_id)` 호출
- **에러 처리**: 평가 중 예외 발생 시 안전하게 `OrderRejectedEvent` 발행 (fail-closed)

### OrderRequestEvent preflight

RuleEngine은 RuleContext 생성과 룰 평가 이전에 `OrderRequestEvent` payload의 도메인 invariant를 검증한다. invalid payload는 Treasury 예약 호출 이전에 `OrderRejectedEvent`로 fail-closed 거부되며, 룰 평가/Treasury 조회는 호출되지 않는다.

검증 항목:
- `side`: `"buy"` | `"sell"`만 허용 (그 외 거부)
- `order_type`: 허용 집합(`limit` / `market` / `stop` / `stop_limit`) 외 거부
- `symbol`: KRX numeric 형식 (6자리 숫자) 검증
- `price`: `limit` / `stop_limit`은 finite positive (`None` / `0` / `-x` / `NaN` / `±inf` 거부). `market`은 `None` 허용
- `stop_price`: `stop` / `stop_limit`은 `None` 거부; 제공된 `stop_price`는 finite positive (`0` / 음수 / `NaN` / `±inf` / non-number 거부)
- `quantity`: finite positive (`0` / `-x` / `NaN` / `±inf` 거부)

Reject payload 정규화 (`_build_safe_rejected_event`):
- finite numeric `price` / `quantity`는 원본 부호와 값을 보존한다 (audit trail).
- non-finite/non-number `quantity`는 `0.0`으로 정규화 (sqlite `trades.quantity REAL NOT NULL` 호환).
- non-finite/non-number `price`는 `None`으로 정규화 (sqlite `trades.price REAL nullable` 호환).
- reason 문자열은 `_safe_repr`로 안전 조립하며 `0` / `0.0` / `-0.0` 부호와 값을 그대로 보존한다.

### 미복구 매수 가드 (#2315)

> 소스: `RuleEngine._check_unrecovered_buy_guard` (`src/ante/rule/engine.py`)
> 배경: #2314 캐스케이드 방어 (defense-in-depth). 부모 #2314의 fill-recovery 근본수정과 **독립**이다.

OrderRequestEvent preflight 도메인 검증(`side`/`order_type`/`symbol`/`price`/`stop_price`/`quantity`)을 모두 통과한 뒤, RuleContext 생성과 룰 평가 **이전에** 미복구 self-order 반복 매수 가드를 평가한다.

매수 주문이 제출됐으나 내부 체결 복구가 지연/실패해 `positions`가 0으로 고정되면(#2314), 전략 컨텍스트가 계속 `quantity=0`을 관측해 동일 매수를 반복 제출할 수 있다. 이는 #1945 인시던트의 핵심 캐스케이드(반복매수 → 예산 소진 → 외부매수 오분류 → 재매도)의 진입 경로다. 본 가드는 미복구 self-order가 잔존하는 동안 동일 매수의 중복 제출을 차단한다.

**차단룰 (normative)**: 새 `buy` `OrderRequestEvent`를 다음 **4개 조건 모두(AND)** 성립 시 `OrderRejectedEvent`로 거부한다.

1. 같은 `(account_id, bot_id, symbol, side="buy")`에 대해 `OrderTracker`의 **non-terminal**(`open` / `partially_filled`) buy 주문 중 `remaining = ordered_qty - recorded_filled_qty > 0`인 주문이 존재한다. (`OrderTracker.get_open_orders_for(...)` — reconciler self-submitted 판정(#1950)과 동형 기준.)
2. 그 미복구 주문의 `submitted_at` age ≥ `unrecovered_buy_guard_min_age`(기본 `60.0`초 = `max(fill_poll_interval 60s, 60s)` — fill-recovery 폴이 최소 1회 미복구 잔량을 복구할 기회를 보장). `submitted_at`이 `None`/비문자열/파싱 불가/naive(tz 미인지)면 **age 산정 불가**로 보아 조건②를 미충족 처리한다(과대차단 회피 — 음수 age는 0으로 클램프).
3. RuleEngine이 `self._trade_service.get_positions(bot_id, account_id=self._account_id)`로 조회한 **해당 symbol 내부 position 수량 합 == 0** (전략이 보유를 인지하지 못한 #2314 증상).
4. opt-out `allow_unrecovered_buy_overlap`(봇/전략 단위 override → 계좌 기본값) 가 `false`(기본).

4조건이 모두 성립할 때에만 차단하며, 그 외에는 통과시킨다. 즉 **합법적 분할매수/피라미딩은 비차단**이다: 내부 position > 0(이미 보유 인지)이거나, 미복구 outstanding의 age < threshold(빠른 연속 주문)이거나, opt-out = true이거나, 다른 키(account/bot/symbol 또는 `side="sell"`)면 통과한다.

복구가 완료되거나(`recorded_filled_qty == ordered_qty` → `remaining = 0`) 주문이 terminal(`cancelled`/`rejected`/`failed`/`expired`/`filled`)로 전이되면 조건①이 깨져 차단이 자동 해제된다.

**활성 조건 / opt-out 배선**:
- `self._order_tracker is None`(또는 `self._trade_service is None`)이면 가드는 **비활성**(허용)이다. reconciler #1950 패턴과 동형으로, tracker 미주입 시 self-check를 생략한다.
- `unrecovered_buy_guard_min_age`(기본 `60.0`)와 `allow_unrecovered_buy_overlap`(계좌 기본, 기본 `false`)은 `RuleEngine` 생성자 인자이며 `RuleEngineManager`를 통해 전파된다. 봇/전략 단위 opt-out은 `RuleEngine.set_unrecovered_buy_overlap(bot_id, allow)`로 등록하며, 미등록 봇은 계좌 기본값을 따른다.

**fail-closed (audit trail 보존, #1302 invariant)**: 가드 활성 중 `OrderTracker.get_open_orders_for` 또는 `get_positions` 조회가 **예외**를 던지면, 가드 게이트는 이를 try/except로 삼켜 허용(silent-pass)하지 **않는다**. 예외는 `_on_order_request`의 catch-all로 전파되어 fail-closed generic `OrderRejectedEvent`로 audit trail이 잠긴다. 정상 DB의 일시적 조회 예외에서도 정상 주문이 보수적으로 reject될 수 있으나(과도 거부 trade-off), #2314 캐스케이드 회피를 외부 검출/통과 완전성보다 우선하는 의도적 안전 선택이다.
