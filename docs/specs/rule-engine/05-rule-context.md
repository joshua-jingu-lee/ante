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
| `quantity` | `float` | — | 주문 수량 |
| `order_type` | `str` | — | 주문 유형 |
| `price` | `float \| None` | `None` | 주문 가격 |
| `exchange` | `str` | `"KRX"` | 거래소 코드 |
| `currency` | `str` | `"KRW"` | 통화 코드 |
| **시장/포지션 정보** | | | |
| `current_price` | `float` | `0.0` | 현재 시장가 |
| `current_position` | `float` | `0.0` | 현재 포지션 수량 |
| `available_balance` | `float` | `0.0` | 가용 잔고 |
| `bot_allocated_budget` | `float` | `0.0` | 봇 할당 예산 (Treasury에서 주입). PositionSizeRule, UnrealizedLossLimitRule의 분모 |
| **계좌 정보** | | | |
| `account_status` | `str` | `"active"` | 계좌 상태 (Account.status 기반) |
| `trading_hours_start` | `str` | `"09:00"` | 거래 시작 시각 (Account에서 주입). TradingHoursRule 사용 |
| `trading_hours_end` | `str` | `"15:30"` | 거래 종료 시각 (Account에서 주입). TradingHoursRule 사용 |
| `timezone` | `str` | `"Asia/Seoul"` | 거래소 시간대 (Account에서 주입). TradingHoursRule 사용 |
| `daily_pnl` | `float` | `0.0` | 일일 손익 |
| `total_pnl` | `float` | `0.0` | 총 손익 |
| **확장** | | | |
| `metadata` | `dict[str, Any]` | `{}` | 추가 메타데이터 (`unrealized_pnl`, `allocated_budget`, `recent_trade_count`, `current_time` 등) |

### EvaluationResult (dataclass)

> 소스: `src/ante/rule/base.py`

전체 룰 평가 종합 결과.

| 필드 | 타입 | 설명 |
|------|------|------|
| `overall_result` | `RuleResult` | 최종 판정 결과 |
| `evaluations` | `list[RuleEvaluation]` | 개별 룰 평가 결과 목록 |
| `rejection_reason` | `str` | 거부 사유 (BLOCK/REJECT 시) |
| `actions` | `list[RuleAction]` | 실행할 조치 목록 |
