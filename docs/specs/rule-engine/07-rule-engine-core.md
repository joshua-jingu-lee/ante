# Rule Engine 모듈 세부 설계 - RuleEngine 코어

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# RuleEngine 코어

> 소스: `src/ante/rule/engine.py`

RuleEngine은 룰을 로드하고 평가하는 메인 엔진입니다.

### 생성자

```python
RuleEngine(
    eventbus: EventBus,
    account_id: str = "default",
    account_service: AccountService | None = None,
)
```

### 의존성

- `EventBus`: 이벤트 구독/발행
- `AccountService`: 계좌 상태 조회/변경 (SUSPENDED 전환)

### 이벤트 구독

- `OrderRequestEvent` (priority=100): 주문 평가 — `event.account_id` 필터링 → RuleContext 생성 → 계좌/전략별 룰 평가 → 결과 이벤트 발행
- `OrderModifyEvent` (priority=100): 주문 정정 평가 — `event.account_id` 필터링 → RuleContext 생성 → 계좌/전략별 룰 평가 → 결과 이벤트 발행. 거부 시 `OrderModifyRejectedEvent` 발행
- `ConfigChangedEvent`: 룰 설정 변경 감지 (category가 `"rule"`, `"global_rule"`, `"strategy_rule"` 중 하나일 때)

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
| `update_rules` | `(self, bot_id: str, rules: list[dict]) -> None` | 봇의 거래 규칙 갱신. bot_strategy_resolver로 전략 ID 조회 후 룰 교체 |
| `remove_strategy_rules` | `(self, strategy_id: str) -> None` | 특정 전략의 룰 제거 |

### 주요 동작

- **이벤트 필터링**: `event.account_id != self._account_id`인 이벤트는 무시
- **평가 흐름**: RuleContext 생성 → 계좌 룰 평가 → 전략별 룰 평가 → 결과 통합 → 이벤트 발행
- **결과 발행**: PASS/WARN → `OrderValidatedEvent` 발행 (WARN 시 `NotificationEvent` 추가), BLOCK/REJECT → `OrderRejectedEvent` 발행 + 조치 실행
- **조치 실행**: `NOTIFY` → NotificationEvent, `STOP_BOT` → BotStopEvent, `HALT_ACCOUNT` → `AccountService.suspend(account_id)` 호출
- **에러 처리**: 평가 중 예외 발생 시 안전하게 `OrderRejectedEvent` 발행 (fail-closed)
