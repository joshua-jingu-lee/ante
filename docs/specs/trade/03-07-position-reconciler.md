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

**불일치 유형:** 외부 청산, 외부 일부 매도, 외부 매수, 수량 불일치, **ante 미반영 체결(self-submitted)**, **미귀속 보유(unattributed-holding, #2352 detect-only)**

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

**sell-side 대칭 분기(#2351):** 외부 청산(`broker_qty == 0 && internal_qty > 0`)·외부
일부 매도(`0 < broker_qty < internal_qty`)도 아래 "sell-side self / external 분류 정책
(#2351)" 절의 self-check 대상이다(buy-side #1950 의 정확 대칭). 그 외 수량 불일치는
self-check 대상이 아니며 기존 동작을 유지한다.

> **정정(#2351):** 종전 본 절은 외부 청산/외부 일부 매도를 "self-check 대상이 아니며
> 기존 동작 유지"로 기술했으나, **단일봇 + running(`dry_run=False`) 경로에서 외부
> 청산/일부 매도 분류도 `correct_position(quantity=broker_qty)` force-write 를 호출**한다
> (`dry_run=True` 에서만 보정 보류). 즉 이 분기는 detect-only 가 아니라 보정을 유발하는
> 분기였고, KIS 모의 ccld 지연창에서 self 매도가 이 분기로 오라벨링되면 원장(trade
> record/PnL)이 force-write 로 우회 수렴되는 결함이 있었다(#2314/#2351). 아래 sell-side
> self-check 가 그 순수 self-sell 구간을 보정에서 제외해 이 결함을 닫는다.

## sell-side self / external 분류 정책 (#2351, normative)

`broker_qty < internal_qty`(외부 청산·외부 일부 매도 후보) 불일치는 **항상**
self-submitted vs external 을 구분한다. **buy-side(#1950)의 정확한 방향 대칭**이다.

KIS 모의투자에서 ante 가 직접 제출한 **매도(self 매도)**가 체결되면 잔고
(`get_positions`, 체결기준)는 즉시 감소하나, 모의 `inquire-daily-ccld`
(`get_order_history`)는 당일 0건을 주는 지연창 동안 내부 매도가 미반영
(`internal_qty` 유지)된다. 그 결과 `broker_qty < internal_qty` 가 되어 reconciler 가
이를 외부 청산/외부 일부 매도로 **오라벨링**하고, 단일봇 + running 경로에서
`correct_position` force-write 로 원장을 우회 수렴시키는 결함(#2314)이 발생했다.

**분류 규칙(normative):**

- `deficit = internal_qty - broker_qty`.
- `sell_capacity = Σ(ordered_qty - recorded_filled_qty)` — OrderTracker 에서
  `(account_id, bot_id, symbol, side="sell")` 의 **non-terminal**(`open`·
  `partially_filled`) 주문을 조회한 미체결 잔량 합. ante 미반영 self 매도는
  FillApplier 가 아직 기록 못 한 상태이므로 해당 ante 매도 주문이 정확히 이 범위에
  든다. (buy-side capacity 와는 `side` 로 분리되어 혼입되지 않는다.)
- `deficit <= sell_capacity` (매칭 self 매도 존재) → **`self_submitted`** (사유:
  `ante 미반영 체결` — 기존 `REASON_SELF_SUBMITTED` 재사용. 이 문구는 **방향 중립**
  이며, 방향은 `internal_qty > broker_qty`(sell) vs `broker_qty > internal_qty`(buy) +
  capacity side 로 판별된다).
  - `correct_position` 자동 보정(force-write down)을 **skip** 한다.
  - `PositionMismatchEvent`(reason=`ante 미반영 체결`) + `NotificationEvent`(level=
    **info**)만 발행한다(buy-side self_submitted 분기와 **동일 계층**).
  - 실제 포지션/체결 복구는 **FillApplier(#1946) 단일 권위 경로(ccld 백스톱)**가
    수행한다. reconciler 는 복구하지 않는다 — **순수 self-sell 구간
    (`deficit <= sell_capacity`)에 한해** 원장 우회·이중 차감 면을 제거한다.
- `deficit > sell_capacity`·**매칭 sell 주문 없음**(진짜 외부 거래)·`order_tracker
  is None`/조회 실패 → 기존 **외부 청산**(`broker_qty == 0`) / **외부 일부 매도**
  (`0 < broker_qty < internal_qty`) 분류·보정을 그대로 유지한다(무회귀, level=critical).

**self-check 와 `skip_external_buy` 의 직교(normative):** sell-side self-check 는
`skip_external_buy`(#1946 기동 barrier, external-**buy** 타겟)와 **무관하게 항상**
수행된다. 그 플래그는 external-buy 분류만 억제하므로 sell-side 분기에 영향을 주지
않는다.

**혼재 케이스 `0 < sell_capacity < deficit` 의 bounded known-limitation(normative):**
self 매도와 진짜 외부 매도가 혼재하면(예: internal 50, ante 미체결 sell 20, 숨은 외부
매도 30 → `deficit 50 > sell_capacity 20`) 잔고 **총량**만으로 self 매도분과 외부
매도분을 분리 보정할 수 없다. 따라서 **분리 알고리즘(비례 배분·부분 귀속 등)은
비채택**하고 기존 외부 분류(force-write down)를 유지한다. 이때 그 self 매도분이 이후
ccld 로 적용되면 같은 매도를 ccld 가 다시 차감(이중 차감)하거나 force-write 가 PnL 을
누락하는 면이 **잔존**한다. 이는 buy-side §11.7 협소 외부 흡수와 **동형**인 bounded
known-limitation 이다. 위험창이 협소한 근거: 동일 종목 self 매도가 pending 인 동안
**동시에** 같은 종목 외부 매도가 발생해야 하는 **이중 조건**이라 드물고, ccld 지연창
자체가 신 tr_id(`VTTC0081R`, #2349) 적용 후 **모의 관측상** 폴 주기 수준으로
축소된다(모의 한정 — 실전 `TTTC0081R` 지연 폭은 미검증). 완전 분해는
broker fill-level 데이터 계약이 필요한 out-of-scope 다.

**bounded known-limitation(총량 기반 검출 지연, normative):** broker 포지션은 **총량**
만 제공하므로 "self 매도 vs 진짜 외부 청산"을 총량만으로 완전 분해할 수 없다 —
buy-side #1950 R2-1 과 동형이다. `deficit <= sell_capacity` 로 self 로 분류된 구간 안에
숨은 진짜 외부 매도(`internal_qty > broker_qty` + sell capacity 로 판별)는 즉시 external
로 검출되지 않고, 매칭 ante 매도 주문이 해소(완전 체결 → `get_open_orders` 이탈, 또는
EOD `expire_stale` → terminal)되는 시점까지 검출이 **지연**된다(bounded — 지연 ≤ EOD).
이는 #1945 류 캐스케이드 회피·원장 우회 차단을 external-detection 완전성보다 우선하는
보수적 trade-off 다. 포지션 총량 기반 분류의 한계는 본 bounded 선언으로 종결한다.

## 미귀속 보유 detect-only (#2352, normative)

`broker_qty > internal_qty` 분기에서 self-check 가 self_submitted 로 매칭되지 **않은**
뒤, 추가로 **`internal_qty == 0` 이고 `capacity == 0`**(= `(account_id, bot_id, symbol,
side="buy")` 의 non-terminal open buy 가 **전무**)인 보유는 **미귀속 보유**(사유:
`미귀속 보유`)로 분류하고 **detect-only** 처리한다.

**분류 규칙(normative):**

- 판정: self-check 미매칭(self_submitted 아님) → `internal_qty == 0` → `(account_id,
  bot_id, symbol, side="buy")` 의 non-terminal open buy 가 **하나도 없음**(capacity == 0).
  세 조건을 모두 만족하면 미귀속 보유다.
- `correct_position` 자동 보정을 **호출하지 않는다**(force-write 없음). 단일봇이라는
  이유만으로 그 봇이 거래(추적)한 적 없는 보유를 그 봇 소유로 단정하지 않는다.
- `PositionMismatchEvent`(reason=`미귀속 보유`) + `NotificationEvent`(level=**critical**)는
  **기존대로 발행**한다. 운영자 관측 가능성을 줄이지 않는다(detect-only ≠ 침묵). 경고
  로그에 미귀속(force-write 보류)을 명시한다.
- `skip_external_buy` 와 **직교**한다: 미귀속 보유는 외부 매수(`is_external_buy`)가
  아니므로 #1946 barrier 가 그 이벤트 발행을 억제하지 않는다. `dry_run` 여부와도
  무관하게(보정 모드에서도) `correct_position` 을 호출하지 않는다 — 보정 정책 자체가
  "귀속 불가 보유는 보정하지 않는다"이기 때문이다.

**근거(결함 판정, #2317 canary):** 단일봇 force-write 경로(#2118/#2119/#2270)의 설계
근거는 "봇 **간** 귀속 ambiguity 부재"이지 "어느 봇도 거래하지 않은 보유를 그 봇 소유로
단정"이 아니다. 미거래 carryover(영업일 이월·계좌 원래 잔고)를 그 봇의 외부 매수로
force-write 하면 전략이 미보유 종목을 자기 포지션으로 인식해 **실거래 오매도**를 접수한다
(#2317 런타임에서 입증: `069500` 내부 0 → 브로커 2 force-write → 전략 'sell all' → KIS
모의 `sell market 069500 2`). #1945/#1950 의 보수적 trade-off("해로운 자동 매도 회피 >
external-detection 완전성")와 동일 방향이며, 보정 skip + 관측(이벤트/알림) 유지는 침묵
결함이 아니다.

**reason 명칭의 보수적 분류 성격:** "미귀속 보유"는 "이월"이 아닌 보수적 분류명이다 —
현재 자료(internal 0, 추적 open buy 전무)로 **귀속 불가**한 보유를 가리키며, 영업일
이월뿐 아니라 ante 가 추적하지 않은 외부 신규 매수까지 포함한다. 어느 쪽이든 그 봇
소유라는 보장이 없으므로 동일하게 detect-only 로 둔다.

**#1950 경계 보존(normative):** `capacity > 0`(추적 open buy 존재)인 모든 케이스는 #1950
normative 를 그대로 따른다 — `excess <= capacity` → self_submitted(보정 skip + info
이벤트), `excess > capacity` → **외부 매수 force-write**(`internal_qty == 0` 이어도). 즉
미귀속 보유 분기는 #1950 이 규정하지 않은 `capacity == 0 && internal_qty == 0` 부분집합만
변경한다. `internal_qty > 0`(잔존 보유 위 외부 매수)인 케이스도 기존 외부 매수 force-write
를 유지한다.

**#1950 bounded invariant 재서술(normative):** #1950 의 "매칭 ante 주문이 해소되면 다음
reconcile 에서 잔여 excess 가 external 로 **검출·보정**된다"는 보장은 `internal_qty > 0 ||
capacity > 0` 케이스에 **한정**된다. 주문이 해소된 뒤에도 `internal_qty == 0 && capacity
== 0` 이면 그 보유는 미귀속 보유로 **영구 detect-only**(자동 보정 없음, critical 알림
반복)로 전환된다. 이는 자동 귀속보다 **안전을 우선**하는 normative 결정이다(잘못된
force-write 로 인한 실거래 오매도를 영구 방지). carryover 의 수동 채택(봇 귀속) UX 는
정의되지 않은 별도 경로이며 필요 시 후속 이슈로 다룬다.

**`order_tracker is None` 하위 호환(normative):** OrderTracker 미주입이면 capacity 를
판정할 수 없으므로 미귀속 보유 분기를 적용하지 않고 **기존 외부 매수 동작을 유지**한다.
`main.py` 의 두 배선 경로(ReconcileScheduler·IPC 수동 reconcile)는 항상 OrderTracker 를
주입하므로 실제 운영 경로에서는 미귀속 보유 detect-only 가 항상 활성이다.

**적용 경로:** 본 규칙은 `reconcile()` 내부 분류에서 적용되므로, 주기 대사
(`ReconcileScheduler`)와 수동 대사(IPC `broker reconcile --fix`, `src/ante/ipc/registry.py`
단일봇 경로) **모두** 동일하게 미귀속 보유를 보정에서 제외한다. 수동 대사의 `--fix` 에서도
미귀속 보유는 `adjustments`(보정 내역)에 포함되지 않고 `mismatches` 에는 미보정 불일치로
남아 보고된다.

## position-derived fallback 과의 관계 (#2314, normative)

KIS 모의 당일 체결은 레거시 tr_id `VTTC8001R` 의 `get_order_history`(결제기준)가
0건을 주는 동안 잔고(`get_positions`, 체결기준)만 즉시 반영된다(신 tr_id
`VTTC0081R`(#2349)은 **모의** 당일 체결을 반환함이 모의 라이브(#2317 + #2353)로
확인됨 — **모의 한정·실전 `TTTC0081R` 미검증**; 단, position-derived fallback 은
KIS 공식 일별 원장 지연 가능성에 대해 백스톱 지연/유실에 무관히 멱등 백업으로
유지된다).
이 모의 당일 gap을 닫기 위해
broker-adapter 측에 **잔고-역도출 fallback**(position-derived bounded fallback,
[`../broker-adapter/18-fill-recovery.md`](../broker-adapter/18-fill-recovery.md) §11)이 정의된다. 이 fallback 은 reconciler 의
self/external 분류 정책과 **충돌하지 않으며**, 다음 경계를 유지한다:

- **복구 권위는 여전히 FillApplier 단일**이다. reconciler 는 self_submitted 분기
  에서 복구하지 않고(보정 skip + info 이벤트만), 잔고-역도출 fallback **역시**
  `FillApplier.apply_cumulative` 경로로만 수렴한다([`../broker-adapter/18-fill-recovery.md`](../broker-adapter/18-fill-recovery.md) §11.8).
  reconciler 도 fallback 도 `positions`/`trades`/`recorded_filled_qty` 를 직접
  수정하지 않는다 — position ownership 은 Trade 모듈 단일 소유로 유지된다.
- **self/external 경계 공유(#1950)와 정직한 한계**: fallback 의 귀속은 본 문서의
  `capacity = Σ(ordered_qty - recorded_filled_qty)`(non-terminal open buy) 한도
  안에서, 그리고 `(account, symbol, side=buy)` 의 추적 open buy 가 **유일하고
  미복구(`recorded_filled_qty == 0`)이며 잔고 excess 가 그 주문의 `ordered_qty`
  와 정확히 일치(full-fill 정확매칭)** 할 때만 일어난다(broker-adapter §11.3).
  partial·모호한 excess 는 fallback 미적용으로 D+1 ccld 백스톱에 위임한다. 다만
  fallback 은 "외부 매수를 self 로 흡수하지 않는다"를 **단정하지 않는다**: 외부
  매수가 **정확히** 주문 수량을 보충하는 협소 케이스(self 부분 + 외부 =
  `ordered_qty`)에서는 그 외부분이 self 로 **비가역 흡수**될 수 있다. 이는
  broker-adapter §11.7 **paper-only bounded known-limitation**이며, late-ccld
  reconcile alert(§11.4)로 관측 가능하게 한다. 같은 미반영 체결에 본 문서의
  self_submitted **가역 skip**(보정 skip · 원장 미advance · 재검출 가능)이 적용
  가능한 경로면 그 가역 경로를 우선한다. 이 보수적 귀속은 본 문서의 bounded
  known-limitation(총량 기반 분류 한계)과 동형이다.
- **수렴 순서**: fallback 이 잔고 excess 를 self 미반영 체결로 advance 하면, 다음
  reconcile 에서 internal_qty 가 그만큼 올라 `broker_qty > internal_qty` excess 가
  해소되어 self_submitted 분류 자체가 줄어든다. 즉 fallback 과 reconciler 는 같은
  미반영 체결을 **이중 보정하지 않고**(FillApplier 멱등), fallback 이 빠른 수렴을,
  reconciler 가 분류·경계 보존을 담당한다.
