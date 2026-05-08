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
| `price` | `float \| None` | `None` | limit/stop_limit 의 지정가. `order_type="market"` + `price=None` 은 "가격을 지정하지 않는 시장가 주문" 을 의미하며, 전략 작성자가 별도 limit hint 를 넣지 않아도 공식 지원된다 (#1333). |
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

### 시장가 매수 자금 처리 약속 (#1333)

`Signal(order_type="market", side="buy", price=None)` 은 즉시 실행을 우선하는
공식 지원 시그니처다. 전략 작성자는 시장가 매수에 임의 limit hint 를 넣을
필요가 없다.

- **즉시 실행 주문은 제출 전에 자금이 잠긴다.** stop 주문 처럼 trigger 대기 단계가
  없으므로 `OrderApprovedEvent` 발행 전에 Treasury 가 reserve 금액을 산정한다.
- **현재가는 reserve estimate 일 뿐 주문가가 아니다.** Treasury 는 account-scoped
  resolver (`APIGateway.get_current_price`) 로 현재가를 조회해 `quantity * quote *
  (1 + market_order_reserve_buffer_rate)` 식으로 보수적으로 잠근다. resolved
  quote 는 `OrderApprovedEvent.price` 에 들어가지 않고, BrokerAdapter 는 시장가
  주문 계약 그대로 제출한다.
- **체결 가격은 보장되지 않는다.** Treasury 는 체결 후 실제 체결 금액으로 정산하며,
  reserve 부족분은 `available` 음수까지 허용해 정확히 차감하고
  `market_order_reserve_shortfall` warning 을 logged 한다.
- **quote 조회 실패는 terminal reject.** resolver 미주입/예외 시 broker 호출 전
  `OrderRejectedEvent(reason="market_buy_quote_unavailable: ...")` 가 한 번
  발행되고, 동일 fingerprint 의 무한 반복은 별도 운영/리포팅 이슈에서 다룬다.

매도 시장가는 보유 포지션 기반이므로 reserve 대상이 아니며 본 약속과 무관하다.

상세 invariant 는 [`treasury/04-treasury-interface.md`](../treasury/04-treasury-interface.md) 의 "시장가 매수 quote resolver invariant" 섹션을 참조한다.
