# Strategy 모듈 세부 설계 - 설계 결정 - OrderAction 핵심 필드

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# OrderAction 핵심 필드

구현: `src/ante/strategy/base.py` 참조

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `action` | `str` | (필수) | `"cancel"` \| `"modify"` |
| `order_id` | `str` | (필수) | 대상 주문 ID |
| `quantity` | `float \| None` | `None` | modify 시 변경할 수량 |
| `price` | `float \| None` | `None` | modify 시 변경할 가격 |
| `reason` | `str` | `""` | 액션 사유 (로깅용) |

**근거**:
- Signal(신규 주문)과 OrderAction(기존 주문 관리)을 분리 — 역할이 다르므로 타입도 분리
- 전략이 `ctx.cancel_order()` / `ctx.modify_order()` 호출 시 내부 큐에 쌓이고, Bot이 on_step() 종료 후 일괄 처리
- 취소/정정도 EventBus를 통해 RuleEngine 검증을 거침
