# Trade 모듈 세부 설계 - 설계 결정 - PositionReconciler — 포지션 정합성 검증 및 보정

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# PositionReconciler — 포지션 정합성 검증 및 보정

구현: `src/ante/trade/reconciler.py` 참조

브로커 실제 포지션과 내부 포지션의 불일치를 감지하고 브로커 기준으로 자동 보정한다.

**생성자 파라미터:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `trade_service` | TradeService | 포지션 조회/보정 대상 |
| `eventbus` | EventBus | 이벤트 발행용 |

**퍼블릭 메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `reconcile` | `bot_id: str`, `broker_positions: list[dict]` | `list[dict]` | 봇의 내부 포지션과 브로커 포지션을 대조하여 보정. 불일치가 없으면 빈 리스트 |

**동작 흐름:**
1. TradeService에서 봇의 내부 포지션 조회
2. 브로커 실제 보유와 심볼별 수량 비교
3. 불일치 감지 시 `PositionMismatchEvent` 발행 + `TradeService.correct_position()` 호출로 보정
4. 보정 건이 있으면 `ReconcileEvent` 발행

**불일치 유형:** 외부 청산, 외부 일부 매도, 외부 매수, 수량 불일치
