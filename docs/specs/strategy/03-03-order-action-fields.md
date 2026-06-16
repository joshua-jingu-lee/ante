# Strategy 모듈 세부 설계 - 설계 결정 - OrderAction 핵심 필드

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# OrderAction 핵심 필드

구현: `src/ante/strategy/base.py` 참조

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `action` | `str` | (필수) | `"cancel"` \| `"modify"` (단, `"modify"`는 broker-level 미구현/deferred — 아래 근거 참고) |
| `order_id` | `str` | (필수) | 대상 주문 ID |
| `quantity` | `float \| None` | `None` | modify 시 변경할 수량 |
| `price` | `float \| None` | `None` | modify 시 변경할 가격 |
| `reason` | `str` | `""` | 액션 사유 (로깅용) |

**근거**:
- Signal(신규 주문)과 OrderAction(기존 주문 관리)을 분리 — 역할이 다르므로 타입도 분리
- 전략이 `ctx.cancel_order()` / `ctx.modify_order()` 호출 시 내부 큐에 쌓이고, Bot이 on_step() 종료 후 일괄 처리
- 취소/정정도 EventBus를 통해 RuleEngine 검증을 거침
- **`action="modify"` deferred caveat**: 정정 액션은 필드 스키마로 존재하나 **broker-level 정정이 현재 미구현(deferred)**이다. 룰 통과 여부와 무관하게 Gateway가 즉시 `OrderModifyRejectedEvent`(`reason="modify_not_implemented"`)로 terminal reject 처리하므로, 정정이 필요하면 `cancel` 후 재주문으로 대체한다. 실 KIS 정정취소(`order-rvsecncl`) 연동은 후속 작업(#2391).
