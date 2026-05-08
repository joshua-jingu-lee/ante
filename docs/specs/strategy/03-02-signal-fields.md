# Strategy 모듈 세부 설계 - 설계 결정 - Signal 핵심 필드

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# Signal 핵심 필드

구현: `src/ante/strategy/base.py` 참조

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `symbol` | `str` | (필수) | 종목 코드 |
| `side` | `str` | (필수) | `"buy"` \| `"sell"` |
| `quantity` | `float` | (필수) | 수량 |
| `order_type` | `str` | `"market"` | `"market"` \| `"limit"` \| `"stop"` \| `"stop_limit"` |
| `price` | `float \| None` | `None` | limit/stop_limit의 지정가 |
| `stop_price` | `float \| None` | `None` | stop/stop_limit의 트리거 가격 |
| `reason` | `str` | `""` | 시그널 생성 사유 (로깅/리포트용) |
| `trading_session` | `str` | `"regular"` | `"regular"` \| `"extended"` — 거래 세션 구분 |

**근거**:
- `reason` 필드로 AI Agent가 생성한 전략의 판단 근거를 추적 가능
- 불변(frozen) 객체로 핸들러 간 전달 시 안전
- `stop` 주문으로 폴링 간격과 무관하게 손절 동작 — 브로커에 주문이 걸려 있으므로 on_step() 호출 사이에도 체결 가능
- `stop_limit`은 스탑 트리거 후 시장가가 아닌 지정가로 체결 — 슬리피지 방지용

### 매수 stop / stop_limit 자금 처리 약속 (#1337)

매수 `stop` / `stop_limit` 주문은 가격 조건이 충족되어야 실제 매수가 시작된다. 이는 한국 증권사 예약주문 표준 처리 방식과 일치한다.

- **등록만으로는 자금이 잠기지 않는다.** 사용자(또는 다른 봇)는 같은 자금에 대해 다른 매수 주문을 자유롭게 걸 수 있다.
- **트리거 시점에 처음 자금이 검증된다.** 시세가 `stop_price`를 건드리면 stop 주문은 일반 매수 주문(시장가 또는 지정가)으로 변환되고, 이때부터 보통의 매수 주문과 동일한 자금 검증·잠금 절차를 거친다.
- **여러 매수 주문을 동시에 걸어두면**, 가장 먼저 발동되는 주문부터 처리되고 그 시점에 자금이 부족하면 나머지는 거부될 수 있다.
- **취소·만료 시 별도 자금 해제 작업이 없다.** 잠근 게 없으므로 풀 것도 없다.

매도 stop은 보유 포지션 기반이므로 본 약속과 무관하다.

상세 invariant 및 모듈 분담은 [`treasury/04-treasury-interface.md`](../treasury/04-treasury-interface.md)의 "Reserve 정책" 섹션과 [`api-gateway/api-gateway.md`](../api-gateway/api-gateway.md)의 "StopOrderManager — 자금 처리 정책 (#1337)" 섹션을 참조한다.
