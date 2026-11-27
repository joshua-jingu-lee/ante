# Rule Engine 모듈 세부 설계 - RuleEngine 코어

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# RuleEngine 코어

> 소스: `src/ante/rule/engine.py`

RuleEngine은 룰을 로드하고 평가하는 메인 엔진입니다.

### 생성자

정의: `ante.rule.engine.RuleEngine` (코드가 정본이다).

`eventbus`는 positional이고, 그 외 인자는 모두 keyword-only(`*,` 이후)입니다. `account_id`는 default fallback 없이 **필수**이며, 생성자 내부에서 `require_account_id(account_id, context="rule_engine.__init__")`로 즉시 검증됩니다 — 빈 값이나 `"default"` 같은 fallback은 거부됩니다.

### 의존성

- `EventBus`: 이벤트 구독/발행
- `AccountService`: 계좌 상태 조회/변경 (SUSPENDED 전환)

### 이벤트 구독

- `OrderRequestEvent` (priority=100): 주문 평가 — `event.account_id` 필터링 → **OrderRequestEvent preflight** (아래 소절 참조) → RuleContext 생성 → 계좌/전략별 룰 평가 → 결과 이벤트 발행
- `OrderModifyEvent` (priority=100): 주문 정정 평가 — `event.account_id` 필터링 → symbol/side enrich → **v1 가격 preflight**(finite `price>0` 아니면 `modify_invalid_args` 거부 + `_consumed` 설정; #2391 — 기존 `event.price or 0.0` 추론 제거, 정정은 항상 지정가이므로 `order_type="limit"` 고정) → RuleContext 생성 → 계좌/전략별 룰 평가(`TradeFrequencyRule`은 빼고 평가한다, #3099) → 결과 이벤트 발행. 룰 거부 시 `OrderModifyRejectedEvent` + `_consumed`. **룰 통과 시**: broker-level 정정 v1(price-only)이 지원되므로 Gateway(priority=50)가 fail-closed 게이트 후 broker 위임 → `OrderModifyExecutedEvent`(성공) 또는 사유별 `OrderModifyRejectedEvent`. 고급 케이스(수량변경 등)=#2393.
- `ConfigChangedEvent`: 룰 설정 변경 감지. `category="rule"` + `key="accounts.{account_id}.rules"`이면 해당 계좌 엔진만 계좌 룰을 재로드하고, `category="strategy_rule"`이면 해당 전략 룰을 재로드한다. `rules_unavailable` 엔진은 `category="rule"`·자기 key의 리스트 재로드가 성공하면 그 상태를 푼다. 재로드가 실패하면 해제하지 않는다.

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

### Account readiness gate (계층 1, #2396)

> 계약 확정: #2396. 실제 동작은 구현 #2397(축 i readiness 모델, 선행) + #2398(축 ii active-order gate) 머지 후. 구현 #2397만 머지된 중간 상태에서는 registry만 채워질 뿐 gate가 켜지지 않아 기존 주문 동작이 불변이다.

RuleEngine은 `OrderRequestEvent` 처리 시 active-order readiness gate(계층 1)를 적용한다. 이는 [account/02-design-decisions.md — D-ACC-09](../account/02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다)의 3계층 defense-in-depth(단일 EventBus 파이프라인이지만 단일 chokepoint 가정을 금지) 중 가장 상류다.

- **위치**: `account_id` 필터(`event.account_id != self._account_id`) 직후, 기존 preflight 게이트 군(#1297~#1318)과 동형 위치에서 `runtime_readiness.active_trading_ready(account_id)`를 체크한다(아래 OrderRequestEvent preflight 도메인 검증보다 먼저, RuleContext 생성·Treasury 조회 이전).
- **거부**: `not_ready`이거나 **`AccountStatus.SUSPENDED`(user kill-switch)**면 `_build_safe_rejected_event(reason="account_not_ready: <missing_flags>" | "account_suspended")`를 발행하고 return한다(try/catch-all + safe-builder로 audit trail 보장). **SUSPENDED 동반 조회 필수(P1)**: `StopOrderManager._trigger_order` 변환 `OrderRequestEvent` 등 봇 상태(BotManager 중지)를 우회하는 경로가 있어, readiness가 ready여도 suspended 계좌 주문이 승인되는 kill-switch 우회를 계층1에서 차단한다(`RuleContext.account_status`는 dead field라 `account_service`에서 직접 status 조회).
- **규칙 로드 실패**: 기동 때 계좌 룰 저장값을 읽지 못했거나 그 항목으로 룰을 만들지 못한 엔진(`rules_unavailable`)은 같은 위치에서 `_build_safe_rejected_event(reason="account_not_ready: rules_unavailable")`와 `build_not_ready_notification`을 발행하고 return한다. readiness registry의 플래그가 아니라 엔진의 상태이며, 계층 2·3은 이 사유를 보지 않는다(신규 주문 승인은 이 엔진의 `OrderValidatedEvent`를 거쳐야만 한다). **registry의 not_ready와 달리 정정도 막는다** — `OrderModifyEvent`를 같은 사유의 `OrderModifyRejectedEvent` + `_consumed`로 거부한다(룰이 빈 엔진은 정정을 평가 없이 통과시키기 때문이다). 청산 SELL은 아래 청산 SELL 비대칭 정책과 같이 거부한다.
- **룰 목록을 만들지 못함**: 계좌 룰 목록은 broker_type 기본 룰과 합치고, 항목마다 룰을 만들고, `priority`로 정렬하는 것을 끝까지 마친 뒤에만 엔진에 넣는다. 그 도중에 예외가 나면(사전이 아닌 항목, 정수와 비교할 수 없는 `priority`, 해시할 수 없는 `type`, 규칙이 읽지 않는 key, 범위 밖·NaN·Inf 값, 문자열이 아닌 `id`, 없거나 등록된 문자열이 아닌 `type` 등 — 마지막 넷은 `enabled`와 무관하게 검사한다) 기동에서는 그 계좌만 계좌 룰 없이 `rules_unavailable`(원인 `invalid_item`)로 두고, 다른 계좌와 데몬은 뜬다. 실행 중 재로드에서는 이전 목록을 그대로 두고(이미 `rules_unavailable`인 엔진은 막힌 채로) 오류 로그와 운영자 알림(`NotificationEvent(level="error", category="system")`, 제목 「계좌 규칙을 다시 읽지 못함 — 이전 규칙 유지」, 저장값 원문 없음)을 낸다. 해제: 비교할 수 없는 `priority`, 규칙이 읽지 않는 key, 범위 밖 값, 문자열이 아닌 `id`로 막힌 계좌는 그 항목의 type으로 `ante rule update`를 한 번 하면(그런 type이 여럿이면 type마다 한 번) 풀린다. `rule update`는 저장하기 전에 룰로 만들 수 없고 `rule update`로도 고칠 수 없는 항목을 저장값에서 버린다. 사전이 아닌 항목, `type`이 없거나 등록된 문자열이 아닌 항목(해시할 수 없는 `type` 포함, 첫 항목이어도), 등록된 같은 type의 둘째 이후 항목 가운데 룰로 만들다 예외가 나거나 만든 룰의 `priority`가 정수·실수가 아닌 것이다(`enabled`와 무관). 그래서 이 셋으로 막힌 계좌는 어느 type으로든 `rule update`를 한 번 하면 풀린다. 등록된 type마다 첫 항목은 깨져 있어도 버리지 않고(그 type으로 `rule update`를 하면 풀린다), 같은 type의 멀쩡한 둘째 이후 항목도 버리지 않는다. 버린 항목이 있으면 저장이 성공한 뒤에 위치와 타입 이름만 담은(값 없음) 경고 로그를 남기고, 데몬을 거친 `rule update`(IPC)에서는 운영자 알림(`NotificationEvent(level="warning", category="system")`)을 한 건 낸다. 버린 항목의 위치와 유형 이름은 CLI·IPC 응답의 `dropped_items`에도 실린다(모양은 [09-rule-management.md — Static TOML seed](09-rule-management.md#static-toml-seed)). 버린 항목의 원문은 dynamic 저장값에서 읽었으면 `ante config history accounts.<account_id>.rules`의 이전 값에, 정적 config의 seed에서 읽었으면 설정 파일에 남는다.
- **효과**: Treasury `reserve_for_order` 이전 차단이라 reserve 누수가 없다(가장 깨끗한 차단).
- **fail-closed**: registry 미주입 / 조회 예외도 `not_ready`로 취급해 차단한다. 멀티계좌 중 1개만 ready면 그 계좌만 통과한다.
- **stop order 재진입**: `_trigger_order` → 변환 `OrderRequestEvent`도 계층1을 통과하므로 트리거 시점 readiness로 재평가된다(별도 처리 불요).

**청산 SELL 비대칭 정책 ([must_fix D], R4 확정, normative)**: 봇 삭제 시 `_liquidate_positions`(시장가 매도)도 계층1을 통과한다. broker `not_ready` 시 청산 SELL은 **거부**한다 — 체결 추적이 불가하면 #2395와 동일 위험이므로 SELL을 면제하지 않는다. 단 반드시 다음을 보장한다.

1. terminal update(계층별 `OrderRejectedEvent` 등) 발행.
2. 운영자 alert: `NotificationEvent(level=error, category=system, "청산 차단: account not_ready — 수동 청산 필요")`.
3. 봇 삭제 / 포지션 state semantics 보존: 봇 삭제는 **진행**하되 **미청산 포지션을 운영자에게 명시 노출**한다.

reserve를 사용하지 않는 SELL이므로 release는 불요하나, 거부 가시성은 필수다(BUY 차단은 안전, SELL 차단은 미청산 포지션 잔존 리스크 — 비대칭을 normative로 명시).

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

### 판정 입력 조회 실패 (#3047)

> 소스: `RuleEngine._on_order_request` (`src/ante/rule/engine.py`)

미복구 매수 가드 뒤, RuleContext를 만들기 전에 엔진은 룰 판정 입력을 조회한다. Treasury에서 `get_summary`·`get_budget(bot_id)`(`bot_id`가 있을 때)·`get_prev_day_snapshot(KST 오늘)`을, TradeService에서 봇 포지션(`get_positions`)과 계좌의 KST 오늘 실현 손익(`get_realized_pnl`)을 읽는다. 이 조회는 `buy`·`sell` 모두 수행한다. 최근 체결 주문 수(`count_filled_orders`, [06](06-rule-catalog.md) 「용어 산식」)는 앞의 조회와 시세 조회(#3097)가 모두 실패하지 않은 매수에서, 켜진 `TradeFrequencyRule`이 있는 계층(계좌 룰이면 계좌 범위, 그 전략의 룰이면 전략 범위)만 읽는다.

- **매수 거부**: `side == "buy"`이고 Treasury가 주입되지 않았거나 Treasury 조회 중 하나라도 예외를 던지면 `_build_safe_rejected_event(reason="account_not_ready: treasury_unavailable")`와 `build_not_ready_notification`을 한 건씩 발행하고 룰 평가 없이 return한다. 포지션·실현 손익·최근 체결 주문 수 조회가 예외를 던지면(최근 체결 주문 수는 `bool`이 아닌 0 이상의 `int`가 아니어도) 같은 모양으로 사유가 `account_not_ready: positions_unavailable`이다. 둘 다 실패하면 사유는 `treasury_unavailable`이다.
- **룰 구성과 무관**: 최근 체결 주문 수를 뺀 조회는 계좌·전략에 켜진 룰이 그 값을 읽는지와 상관없이 거부한다. 손실 룰을 하나도 켜지 않은 계좌와 가상 계좌도 조회 장애 동안 매수가 막히고, 그 순간 트리거된 스탑 매수는 다시 걸리지 않는다(readiness 차단과 같은 성질).
- **사유 토큰은 둘뿐**: 어느 조회가 실패했는지는 사유에 담지 않고 warning 로그로 남긴다. 알림의 중복 묶음 키가 장애 동안 바뀌지 않게 하기 위해서다.
- **매도·정정은 불변**: `side == "sell"`(청산 매도·스탑 매도 트리거 포함)과 `OrderModifyEvent`는 실패한 값을 `0.0`으로 채워 룰을 평가하고, 최근 체결 주문 수는 조회하지 않는다.
- **실패가 아닌 것**: 조회가 성공했지만 값이 없는 경우(오늘 이전 스냅샷 없음, 봇 예산 없음)와 TradeService 미주입은 지금처럼 `0.0`으로 채우며 거부 사유가 아니다. 오늘 이전 스냅샷이 없거나 그 `total_asset`이 0 이하·비유한이면 일일 손실 판정은 건너뛰고, 계좌에 켜진 `DailyLossLimitRule`이 있을 때만 주문마다 warning 로그(계좌·스냅샷 날짜·값)를 남긴다. 대체 분모는 #2621에서 정한다.

### 시장가 매수 시세 (#3097)

> 소스: `RuleEngine._on_order_request`, `RuleEngine.set_market_price_resolver`, `RuleEngine.aclose` (`src/ante/rule/engine.py`)

`side == "buy"`이고 `order_type == "market"`인 주문은 평가 입력의 현재가를 주입된 시세 조회로 채운다. 운영 조립은 계좌마다 Treasury가 시장가 예약에 쓰는 것과 같은 게이트웨이 현재가 조회(`APIGateway.get_current_price(symbol, account_id=)`)를 `RuleEngineManager.set_market_price_resolver(account_id, resolver)`로 넣는다.

- **조회하지 않는 주문**: 매도(청산·손절·스탑 매도 발동 포함), 지정가·`stop_limit`, `stop` 등록, 정정은 조회하지 않고 [05](05-rule-context.md)의 `current_price` 행대로 채운다. `stop` 매수는 등록 때 조회하지 않고, 발동 때 나가는 시장가 주문이 다시 평가될 때 조회한다.
- **판정 순서**: Treasury 조회가 실패하지 않았을 때만 시세를 조회하고, 그다음 포지션·실현 손익을 조회하고, 그때까지 실패가 없는 매수에서만 최근 체결 주문 수(#3099)를 조회한다. #3047의 실패가 하나라도 있으면 그 거부(`account_not_ready: <토큰>`과 알림)가 이긴다. 그렇지 않고 시세 조회가 실패했으면 룰 평가 없이 `market_buy_quote_unavailable: <상세>`로 거부하고 알림은 내지 않는다.
- **사유**: Treasury가 같은 실패에 쓰는 접두와 같다. 이 사유는 `account_not_ready:` 토큰이 아니다. 거부되면 `OrderValidatedEvent`가 나가지 않아 Treasury는 조회하지 않으므로, 사유는 전략에 한 번만 보인다.

| 실패 | 상세 |
|---|---|
| 시세 조회 미주입 | `resolver not configured` |
| 엔진이 닫힌 뒤 | `engine closed` |
| 시간 초과 | `timeout` |
| 예외 | 예외의 문자열. 비면 예외 타입 이름 |
| 수가 아닌 값·`bool`·0 이하·비유한 값 | `non-finite or non-positive quote <값의 repr>` |

- **시간 제한**: 한 번의 조회를 기다리는 시간은 조회가 시작된 때부터 10초다. 넘으면 그 주문은 `timeout`으로 거부되지만 조회는 취소하지 않는다(취소가 증권사 토큰 발급 요청 도중에 걸리면 재발급 대기로 같은 앱 키의 매도까지 막힐 수 있다). 조회는 뒤에서 끝나 게이트웨이 캐시를 채운다.
- **같은 종목의 진행 중 조회**: 엔진은 종목마다 진행 중인 조회를 하나만 두고, 그동안 같은 종목의 주문은 그 조회에 합류해 남은 시간만 기다린다. 끝난 조회의 결과는 재사용하지 않는다(다음 주문은 새로 조회하고, 보통 캐시에 적중한다). 아무도 기다리지 않는 조회가 예외로 끝나면 warning 로그를 남긴다.
- **종료**: `RuleEngineManager.aclose()`가 모든 엔진의 `aclose()`를 부른다. 엔진은 닫힘 상태가 된 뒤 진행 중인 조회를 취소하고 끝나기를 기다린다. 그 뒤의 시장가 매수는 조회 없이 거부된다. 서버 종료 경로는 실시간 스트림을 멈춘 뒤, 브로커 연결을 끊기 전에 이를 부른다.
