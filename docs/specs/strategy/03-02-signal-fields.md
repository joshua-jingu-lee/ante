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
