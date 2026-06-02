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
| `order_tracker` | OrderTracker \| None | self-submitted fill 분류용 권위 저장소(#1950). 미주입 시 self-check 생략(기존 "외부 매수" 동작). `main.py` 의 두 배선 경로(ReconcileScheduler·IPC 수동 reconcile)는 항상 주입한다. |

**퍼블릭 메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `reconcile` | `bot_id: str`, `broker_positions: list[dict]`, `account_id: str`, `skip_external_buy: bool = False` | `list[dict]` | 봇의 내부 포지션과 브로커 포지션을 대조하여 보정. 불일치가 없으면 빈 리스트 |

**동작 흐름:**
1. TradeService에서 봇의 내부 포지션 조회
2. 브로커 실제 보유와 심볼별 수량 비교
3. 불일치 감지 시 분류(아래) 후 `PositionMismatchEvent` 발행 + (외부 거래만) `TradeService.correct_position()` 호출로 보정
4. 보정 건이 있으면 `ReconcileEvent` 발행

**불일치 유형:** 외부 청산, 외부 일부 매도, 외부 매수, 수량 불일치, **ante 미반영 체결(self-submitted)**

## self / external 분류 정책 (#1950, normative)

`broker_qty > internal_qty`(외부 매수 후보) 불일치는 **항상** self-submitted vs external
을 구분한다. ante 가 제출했으나 아직 내부에 반영되지 않은 체결(self-submitted-unrecorded
-fill)을 "외부 매수" 로 오분류해 roundtrip 전략이 즉시 매도하는 캐스케이드(#1945)를 막기
위함이다.

**분류 규칙(normative):**

- `excess = broker_qty - internal_qty`.
- `capacity = Σ(ordered_qty - recorded_filled_qty)` — OrderTracker 에서
  `(account_id, bot_id, symbol, side="buy")` 의 **non-terminal**(`open`·`partially_filled`)
  주문을 조회한 미체결 잔량 합. self-submitted-unrecorded-fill 은 FillApplier 가 아직
  기록 못 한 상태이므로 해당 ante 주문은 정확히 이 범위에 든다.
- `excess <= capacity` (매칭 주문 존재) → **`self_submitted`** (사유: `ante 미반영 체결`).
  - `correct_position` 자동 보정을 **skip** 한다(자동 매도 유발 X).
  - `PositionMismatchEvent`(reason=`ante 미반영 체결`) + `NotificationEvent`(level=**info**)만
    발행한다.
  - 실제 포지션/체결 복구는 **FillApplier(#1946)** 가 단일 권위자로 수행한다(reconciler 는
    복구하지 않는다).
- `excess > capacity` 또는 **매칭 주문 없음** → 기존 **"외부 매수"** 로 정상 보정·알림
  (level=critical). 단 `skip_external_buy=True` 면 그 보정 **및 `PositionMismatchEvent`/
  `NotificationEvent` 발행**이 모두 억제되고 경고 로그만 남는다(아래 layering).
  self_submitted 분기(보정 skip + info 이벤트는 **발행**)와 달리, external-buy+skip 은
  불일치 이벤트 자체를 발행하지 않는다.

**self-check 와 `skip_external_buy` 의 layering(R1-1, normative):** self-check 는
`skip_external_buy` 와 **무관하게 항상** 수행된다. `skip_external_buy`(#1946 기동 barrier)는
분류 결과 중 **external-buy 분류의 보정 + 불일치 이벤트(`PositionMismatchEvent`/
`NotificationEvent`) 발행을 억제**(경고 로그만 남김)하는 별도 계층이다. 이는 보정은 skip 하되
info 이벤트는 발행하는 self_submitted 분기와 다르다 — external-buy+skip 은 그 1회의 불일치
관측 자체를 다음 주기로 연기한다. 따라서 주기 reconcile(`skip_external_buy=False`)에서도
self 는 보정되지 않고, self 가 "외부 매수"로 재오분류되지 않는다.

**bounded known-limitation(R2-1, normative):** broker 포지션은 **총량**만 제공하므로
self+external 혼재를 원천적으로 분해할 수 없다(예: ante 미체결 100, self 미기록 50, 숨은
외부 매수 10 → `excess 60 <= capacity 100` → 전량 self 로 분류). 즉 **ante 미체결 capacity
안에 숨은 진짜 외부 매수는 즉시 external 로 보정되지 않는다.** 이는 #1945 auto-sell
캐스케이드 회피를 external-detection 완전성보다 우선하는 보수적 trade-off다(그 동안 포지션은
understated — 해로운 자동 매도 없음). 이 masking 은 **bounded**(무한 아님)다: 매칭 ante 주문이
해소되면(완전 체결 → `get_open_orders` 이탈, 또는 EOD `expire_stale` → terminal) 다음
reconcile 에서 잔여 excess 가 **external 로 검출·보정**된다. → 외부 검출 지연 = **최대 ante
주문 해소 시점(≤ EOD)** 까지. 포지션 총량 기반 분류의 한계는 본 bounded 선언으로 종결한다
(완전 분해는 broker fill-level 데이터 계약이 필요한 out-of-scope).

**무변경 분기:** 외부 청산(`broker_qty == 0 && internal_qty > 0`), 외부 일부 매도
(`broker_qty < internal_qty`), 수량 불일치는 self-check 대상이 아니며 기존 동작을 유지한다.
