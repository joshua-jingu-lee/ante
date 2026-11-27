# Rule Engine 모듈 세부 설계 - RuleContext

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# RuleContext

> 소스: `src/ante/rule/base.py`

RuleEngine이 OrderRequestEvent와 Account 상태를 조합하여 생성하는 룰 평가 컨텍스트.

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| **주문 정보** | | | |
| `bot_id` | `str` | — | 봇 ID |
| `account_id` | `str` | — | 계좌 ID |
| `strategy_id` | `str` | — | 전략 ID |
| `symbol` | `str` | — | 종목 코드 |
| `side` | `str` | — | 매수/매도 (`"buy"` \| `"sell"`) |
| `quantity` | `float` | — | 주문 수량 (preflight 이후 finite positive) |
| `order_type` | `str` | — | 주문 유형 |
| `price` | `float \| None` | `None` | 주문 가격 (preflight 이후 limit/stop_limit은 finite positive, market은 None 허용) |
| `exchange` | `str` | `"KRX"` | 거래소 코드 |
| `currency` | `str` | `"KRW"` | 통화 코드 |
| **시장/포지션 정보** | | | |
| `current_price` | `float` | `0.0` | 평가에 쓰는 현재가. 시장가 매수는 주입된 시세 조회의 값이다(게이트웨이 캐시·실시간 틱의 값이라 최대 5초 낡을 수 있다, [07 #3097](07-rule-engine-core.md)). 그 밖의 주문은 주문 가격이다(지정가·`stop_limit`은 지정가). 가격이 없는 주문(시장가 매도, `stop` 등록)은 `0.0`이다. 주문 정정 평가에서는 정정 가격이다 |
| `current_position` | `float` | `0.0` | 주문 종목의 봇 보유 수량. 미실현 손익 계산과 같은 `TradeService.get_positions` 결과에서 채운다. TradeService가 주입되지 않았거나 조회가 실패하면 `0.0`(실패 시 매수는 [07 #3047](07-rule-engine-core.md)에 따라 거부). 주문 정정 평가에서는 채우지 않는다 |
| `available_balance` | `float` | `0.0` | 가용 잔고 |
| `bot_allocated_budget` | `float` | `0.0` | 봇 할당 예산 (Treasury에서 주입). PositionSizeRule, UnrealizedLossLimitRule의 분모 |
| **계좌 정보** | | | |
| `account_status` | `str` | `"active"` | 계좌 상태 (Account.status 기반). **현재 어떤 룰도 읽지 않는 dead field** — 아래 caveat 참조 |
| `trading_hours_start` | `str` | `"09:00"` | 거래 시작 시각 (Account에서 주입). TradingHoursRule 사용 |
| `trading_hours_end` | `str` | `"15:30"` | 거래 종료 시각 (Account에서 주입). TradingHoursRule 사용 |
| `timezone` | `str` | `"Asia/Seoul"` | 거래소 시간대 (Account에서 주입). TradingHoursRule 사용 |
| `daily_pnl` | `float` | `0.0` | 계좌의 당일(KST) 실현 손익 합. DailyLossLimitRule의 분자 ([06-rule-catalog.md](06-rule-catalog.md) 「용어 산식」) |
| `prev_day_total_asset` | `float` | `0.0` | KST 오늘 이전의 가장 최근 일별 스냅샷의 `total_asset`. DailyLossLimitRule의 분모 |
| `total_pnl` | `float` | `0.0` | 총 손익 |
| **확장** | | | |
| `metadata` | `dict[str, Any]` | `{}` | 추가 메타데이터 (`unrealized_pnl`, `allocated_budget`, `recent_trade_count`, `current_time` 등) |

### `account_status` dead field caveat (#2396)

> 계약 확정: #2396. 실제 active-order gate 동작은 구현 #2398(축 ii) 머지 후.

`RuleContext.account_status`는 룰 평가 context 필드이나, **현재 어떤 룰도 이 필드를 읽지 않는 dead field**다. active-order readiness gate(`account_not_ready` 거부)는 룰 catalog가 아니라 **별도 preflight 게이트**로 구현한다 — `RuntimeReadinessRegistry`([account/02-design-decisions.md — D-ACC-09](../account/02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다)) + `RuleEngine._on_order_request` preflight 계층1([07-rule-engine-core.md](07-rule-engine-core.md) "account readiness gate" 참조). 즉 `account_not_ready` 거부는 룰 평가 결과가 아니라 preflight 게이트의 직접 거부다.

`account_status` dead field 정리(제거 vs 유지)는 본 readiness gate 작업과 별개이며 **별 PR로 권고**한다(open question).

### EvaluationResult (dataclass)

> 소스: `src/ante/rule/base.py`

전체 룰 평가 종합 결과.

| 필드 | 타입 | 설명 |
|------|------|------|
| `overall_result` | `RuleResult` | 최종 판정 결과 |
| `evaluations` | `list[RuleEvaluation]` | 개별 룰 평가 결과 목록 |
| `rejection_reason` | `str` | 거부 사유 (BLOCK/REJECT 시) |
| `actions` | `list[RuleAction]` | 실행할 조치 목록 |
