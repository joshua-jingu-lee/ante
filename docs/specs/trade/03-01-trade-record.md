# Trade 모듈 세부 설계 - 설계 결정 - 거래 기록 (TradeRecord)

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 거래 기록 (TradeRecord)

구현: `src/ante/trade/models.py` 참조

#### TradeType

| 값 | 설명 |
|----|------|
| `BUY` | 매수 |
| `SELL` | 매도 |
| `ADJUSTMENT` | 대사 보정 (포지션 수량/단가 조정 기록) |

#### TradeStatus

| 값 | 설명 |
|----|------|
| `FILLED` | 체결 완료 |
| `CANCELLED` | 취소됨 |
| `REJECTED` | 거부됨 (룰 위반 등) |
| `FAILED` | 실행 실패 |
| `ADJUSTED` | 대사 보정으로 추가된 기록 |

#### TradeRecord 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `trade_id` | `UUID` | 고유 ID (OrderFilledEvent.event_id 활용) |
| `account_id` | `str` | 계좌 ID |
| `bot_id` | `str` | 실행 봇 ID |
| `strategy_id` | `str` | 전략 ID |
| `symbol` | `str` | 종목 코드 |
| `symbol_name` | `str` | 종목명 (체결 시점 기록) |
| `side` | `str` | `"buy"` \| `"sell"` |
| `quantity` | `float` | 체결 수량 |
| `price` | `float` | 체결 가격 |
| `status` | `TradeStatus` | 거래 상태 |
| `order_type` | `str` | `"market"` \| `"limit"` \| `"stop"` \| `"stop_limit"` |
| `reason` | `str` | Signal의 reason 전달 |
| `commission` | `float` | 수수료 (기본값 0.0) |
| `currency` | `str` | 결제 통화 (기본값 `"KRW"`) |
| `timestamp` | `datetime \| None` | 체결 시각 |
| `order_id` | `str \| None` | 증권사 주문 ID (추적용) |
| `exchange` | `str` | 거래소 코드 (기본값 `"KRX"`) |

**근거**:
- `reason` 필드: AI Agent가 생성한 전략의 판단 근거가 체결까지 전달되어 추후 분석 가능
- `commission`: 수수료 포함으로 정확한 순수익 계산
- CANCELLED, REJECTED, FAILED 상태도 기록 — "주문했으나 체결되지 않은" 이력도 분석 대상
