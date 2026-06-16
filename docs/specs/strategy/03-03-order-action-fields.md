# Strategy 모듈 세부 설계 - 설계 결정 - OrderAction 핵심 필드

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# OrderAction 핵심 필드

구현: `src/ante/strategy/base.py` 참조

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `action` | `str` | (필수) | `"cancel"` \| `"modify"` (`"modify"`는 v1=price-only 지원 — 아래 근거 참고) |
| `order_id` | `str` | (필수) | 대상 주문 ID |
| `quantity` | `float \| None` | `None` | modify 시 변경할 수량. **v1(price-only)에서는 미지정(`None`→이벤트 `0.0`)이거나 원주문 수량과 같아야 한다 — 수량 변경은 fail-closed(#2393)** |
| `price` | `float \| None` | `None` | modify 시 변경할 가격. **v1은 필수 finite 양수**(price-only). buy는 신규가 ≤ 원주문가만 허용 |
| `reason` | `str` | `""` | 액션 사유 (로깅용) |

**근거**:
- Signal(신규 주문)과 OrderAction(기존 주문 관리)을 분리 — 역할이 다르므로 타입도 분리
- 전략이 `ctx.cancel_order()` / `ctx.modify_order()` 호출 시 내부 큐에 쌓이고, Bot이 on_step() 종료 후 일괄 처리
- 취소/정정도 EventBus를 통해 RuleEngine 검증을 거침
- **`action="modify"` v1=price-only (#2391)**: 정정 액션은 **`open` 주문의 가격 정정(수량 불변)을 지원**한다. 룰 위반·v1 가격 preflight 실패 시 RuleEngine(priority=100)이 사유로 먼저 거부(`_consumed` 설정)하고, 룰 통과 시 Gateway(priority=50)가 fail-closed 게이트 후 broker 위임 → 성공 시 `OrderModifyExecutedEvent`(`on_order_update` status=`modified`), 거부 시 사유별 `OrderModifyRejectedEvent`. **고급 케이스는 fail-closed로 거부(후속 #2393)**: 수량 변경(`modify_qty_change_unsupported`), 예산증가 buy 가격↑(`modify_budget_increase_unsupported`), 부분체결/터미널(`modify_partial_or_terminal_unsupported`), 무효 인자(`modify_invalid_args`), orgno 미상(`modify_orgno_unavailable`). 이들 케이스가 필요하면 `cancel` 후 재주문으로 대체한다. 실 KIS 정정(`order-rvsecncl` `RVSE_CNCL_DVSN_CD='01'`) live A/B 검증은 사용자 oracle 후속(pending).
