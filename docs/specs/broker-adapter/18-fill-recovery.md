# Broker Adapter 모듈 세부 설계 - 체결 반영 경로 (Fill Recovery)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)
> 참조: [11-order-flow.md](11-order-flow.md) 주문 처리 흐름, [15-reconciliation.md](15-reconciliation.md) 대사, [trade/03-08-fill-recovery.md](../trade/03-08-fill-recovery.md) OrderTracker/FillApplier 권위

# 체결 반영 경로 (Fill Recovery)

## 1. 문제 정의

ante가 제출한 주문은 (모의투자·실전투자, 스트림 유무와 무관하게) 내부 체결·
포지션에 일관되게 반영되어야 한다. 그렇지 않으면 `positions`가 0으로 고정되고, 전략이
보유를 인지하지 못해 동일 주문을 반복 제출하며, 대사(reconciler)가 미복구
체결을 "외부 매수"로 오분류하는 연쇄가 발생한다 (#1945 인시던트).

기존 설계는 체결→`OrderFilledEvent`를 **실시간 체결 통보 스트림(KIS `H0STCNI0`)
경로로만** 발행했다. 스트림 구독이 실패하거나(HTS ID 부재 등) 모의투자 환경에서
체결 통보가 오지 않으면 체결이 영구히 내부에 반영되지 않았다. REST 폴백은
가격만 복구하고 체결은 복구하지 않았다.

## 2. 설계 원칙

체결 반영은 **두 경로를 가진 단일 멱등 수렴 모델**이다.

- **빠른 경로 (fast path)**: 실시간 체결 통보 스트림 (`H0STCNI0`). 저지연. 선택적.
- **백스톱 경로 (backstop)**: REST `get_order_history` 폴. 정합성 보증. 항상.

두 경로는 모두 **단일 멱등 choke point(`FillApplier`)** 로 수렴한다. 어느
경로로 같은 체결을 몇 번 관측하든 포지션은 **정확히 한 번** 반영된다.

```
OrderApproved → submit_order → place_order(broker_order_id)
  → OrderSubmittedEvent → OrderTracker.open(order_id, broker_order_id, …)

빠른경로 : H0STCNI0 → StreamIntegration._on_execution ─┐
백스톱   : FillReconcileScheduler (open 있을 때만,        ├→ FillApplier.apply_cumulative(
           get_order_history 1콜/사이클)              ─┘     account_id, broker_order_id,
                                                              observed_cumulative, avg_price,
                                                              submitted_date)

FillApplier (단일 인스턴스 · asyncio.Lock):
  lookup_order_id(account_id, broker_order_id, submitted_date) → order_id | None
    └ None 이면 무시 (self/external 경계 — 추적되지 않는 주문)
  Database.transaction() 안에서:
    (a) CAS advance: UPDATE … SET recorded_filled_qty=:c WHERE order_id=:oid AND recorded_filled_qty<:c
        → applied_delta = observed_cumulative - 이전 recorded
    (b) delta<=0 이면 no-op
    (c) delta>0 이면 TradeRecord insert + PositionHistory.on_trade(=positions)
    → commit
  commit 이후: OrderFilledEvent(quantity=delta, price=avg_price, order_id/bot_id/
               strategy_id/account_id 는 tracker 에서 복원) 1회 발행
  → TradeRecorder(알림) · Treasury(정산) · Bot.on_fill(전략) 수신
```

## 3. 컴포넌트

체결 반영의 코어 컴포넌트는 **브로커 무관(broker-agnostic)** 이며, 브로커별
차이는 기존 `BrokerAdapter` 인터페이스(`get_order_history`, 정규화 dict 반환)로
흡수한다. 신규 어댑터 추상화는 도입하지 않는다.

| 컴포넌트 | 위치 | 역할 |
|---|---|---|
| `OrderTracker` | `trade/order_tracker.py` | 추적 주문 영속(DB `order_tracker`), 누적 체결 단조 advance(CAS), 매핑 조회, EOD 만료 |
| `FillApplier` | `trade/fill_applier.py` | 단일 멱등 choke point. 관측 누적 → delta 산출 → 단일 트랜잭션 적용 → 이벤트 발행 |
| `FillReconcileScheduler` | `broker/fill_scheduler.py` | 계좌별 event-gated 백스톱 폴러. open 있을 때만 `get_order_history` 1콜/사이클 → `FillApplier` |

`OrderTracker`와 `FillApplier`는 `trade/` 모듈에 둔다. 체결의 durable 적용
(recorded + trade + position)은 FillApplier가 단일 권위자로 수행하므로,
포지션 소유가 Trade 모듈 내에 유지된다 (position ownership invariant).

## 4. OrderTracker

### 4.1 identity (구조적 종결)

KIS `odno`(broker_order_id)는 **시스템 전역 유일 키가 아니다** — 계좌 간 /
paper·live 간 / 영업일 재사용으로 충돌할 수 있다. 따라서:

- **PK = 내부 `order_id`** (`OrderSubmittedEvent`의 ante `uuid4` 주문 ID — 생성상
  전역 유일). CAS는 `WHERE order_id=:oid` 단일 행이라 모호성이 없다.
- `(account_id, broker_order_id, submitted_date)` = **UNIQUE 인덱스 + 조회 키**
  (poll/stream 관측 → 내부 `order_id` 매핑용). 조회는 non-terminal(또는 동일
  영업일) scope로 한정해 영업일 재사용 충돌을 닫는다.

이 구조로 cross-account / paper·live / 일자 재사용 충돌이 **구조적으로 불가**하다.

### 4.2 컬럼

| 컬럼 | 의미 |
|---|---|
| `order_id` (PK) | 내부 주문 ID (ante uuid4) |
| `account_id` | 계좌 |
| `bot_id`, `strategy_id` | 라우팅 정체성 (이벤트 복원용) |
| `broker_order_id` | 브로커 주문번호 (KIS `odno`) |
| `symbol`, `side`, `order_type` | 주문 메타 |
| `ordered_qty` | 주문 수량 |
| `recorded_filled_qty` | 내부 반영 완료된 누적 체결량 (**단조 비감소**) |
| `avg_fill_price` | 최근 관측 평균 체결가 |
| `status` | `open` \| `partially_filled` \| `filled` \| `cancelled` \| `rejected` \| `failed` \| `expired` |
| `submitted_at`, `submitted_date` | 제출 시각·영업일 |
| `last_polled_at` | 마지막 폴 관측 시각 |
| `terminal_at` | 종료 시각 |

### 4.3 메서드

- `open(order_id, account_id, bot_id, strategy_id, broker_order_id, symbol, side, order_type, ordered_qty, submitted_date)`:
  `OrderSubmittedEvent`로 추적 주문 seed.
- `record_fill(order_id, new_cumulative, avg_price) → applied_delta`:
  원자 CAS advance. `delta = new_cumulative - 이전 recorded`. `delta<=0`이면 0
  반환(no-op), `delta>0`이면 `recorded=new_cumulative`로 갱신 후 delta 반환.
  status를 부분/완료로 갱신. **FillApplier의 트랜잭션 안에서만 호출**.
- `mark_terminal(order_id, status)`: 취소·거부·실패·만료 종료 표기.
- `get_open_orders(account_id)`: 계좌의 non-terminal(open/partially_filled) 주문.
- `lookup_order_id(account_id, broker_order_id, submitted_date) → order_id | None`:
  관측 → 내부 주문 매핑(non-terminal/same-day scope).
- `expire_stale(...)`: EOD 경과한 open 주문을 `expired`로 표기.

### 4.4 멱등 불변식

- `recorded_filled_qty`는 order별 **단조 비감소**.
- 각 증가(delta>0)는 **정확히 1개 `OrderFilledEvent(delta)`** 와 1쌍.
- 포지션 = Σdelta = 최종 누적 체결량.

## 5. FillApplier — 단일 멱등 choke point

`FillApplier`는 단일 인스턴스이며 `asyncio.Lock`이 **read → delta → txn →
publish 전체**를 감싼다.

`apply_cumulative(account_id, broker_order_id, observed_cumulative, avg_price, submitted_date)`:

1. `lookup_order_id`로 추적 주문 확인. 없으면 **무시**(self/external 경계 —
   진짜 외부 포지션은 reconciler 영역).
2. `Database.transaction()` 단일 트랜잭션 안에서:
   - (a) CAS advance `recorded_filled_qty` (`WHERE order_id=:oid AND
     recorded_filled_qty<:c`) → `applied_delta` 산출.
   - (b) `applied_delta <= 0`이면 no-op (이미 반영됨/관측 역전).
   - (c) `applied_delta > 0`이면 `TradeRecord` insert + `PositionHistory.on_trade`
     적용.
   - → commit.
3. **commit 이후** `OrderFilledEvent`(quantity=delta, price=avg_price,
   order_id/bot_id/strategy_id/account_id는 tracker에서 복원) 1회 발행.

### 5.1 crash 원자성 (positions exactly-once)

`recorded_filled_qty` advance(CAS)와 TradeRecord insert·position update가 **단일
`Database.transaction()`** 으로 묶인다. 적용 도중 프로세스가 crash하면 rollback이
되어 recorded가 advance되지 않으므로, 재기동 후 다음 폴이 **동일 delta를 재적용**
한다. → positions/trades는 **crash-safe exactly-once**.

`asyncio.Lock`은 프로세스 내 동시성만 막는다. crash 원자성은 단일 트랜잭션이
보장한다.

### 5.2 bounded limitation — 이벤트 전달 (후속)

commit ↔ event-publish 사이 narrow crash window에서 다운스트림 이벤트 전달
(Treasury 정산·strategy `on_fill` 알림)이 유실될 수 있다. 이는 (i) 재기동
catch-up + 기존 position/treasury reconcile로 재정합되며, (ii) 완전한
transactional-outbox 기반 exactly-once **이벤트 전달**은 별도 후속 이슈(#1949)로
분리한다. **positions durability는 본 스펙에서 종결**한다.

## 6. FillReconcileScheduler — 백스톱 폴러

- 계좌별 인스턴스. running 동안 동작.
- **event-gated**: `OrderTracker.get_open_orders(account_id)`가 비면 폴하지 않고
  idle(0콜). open이 있을 때만 `get_order_history`를 **사이클당 1콜** 호출.
- cadence **≥60s**. KIS rate budget(paper 5/min·live 20/min, 주문제출·가격
  fallback·잔고 reconcile·fill poll이 동일 큐 공유)을 보호한다. 주문 제출이
  starve되지 않도록 가격 fallback 루프와 우선순위/상호배타를 둔다.
- `get_order_history` window는 **EOD 만료 전** 추적 open 주문의 가장 이른
  `submitted_date` 이후를 덮도록 잡고 pagination·당일 필터를 처리한다
  (stream-before-seed race도 폴이 멱등 흡수). 만료가 이 open을 먼저 제거해
  window를 좁히지 않는다 (§6.1 poll-first, §8 참조).

### 6.1 기동 카치업 (catch_up_once)

재기동 시 `OrderTracker`는 영속이므로 open/partial 주문이 생존한다. 계좌별
`catch_up_once()`는 open이 있으면 `get_order_history`(submitted_at 이후,
pagination)를 **1회** 폴해 다운타임 중 발생한 체결을 `FillApplier`로 멱등
따라잡는다.

#### poll-first 순서 (복구가 EOD 만료보다 선행 — 정합성 invariant)

폴 사이클(`catch_up_once`·주기 루프 공통 코어 `_poll_and_apply`)은 **반드시**
다음 순서를 지킨다:

1. `get_open_orders`로 추적 open(non-terminal)을 **EOD 만료 전에** 읽고,
   `from_date`를 그 중 가장 이른 `submitted_date`로 잡는다(전일 open이 있으면
   window가 그 영업일까지 거슬러 올라간다 — §8 window invariant).
2. open이 있으면 `get_order_history` 1콜로 다운타임 체결을 `FillApplier`로 멱등
   **복구**한다. 복구된 주문은 `filled`/`partially_filled`로 전이된다.
3. **복구가 끝난 뒤에만** §8의 EOD 만료(`expire_stale`)를 돌린다.

이 순서는 §7 barrier(fill 복구가 reconcile보다 선행)와 **하나의 순서
invariant**다. EOD 만료를 폴 **앞**에 두면, 전일 open이 다운타임 중 체결됐어도
복구 전에 `expired`로 전이되어 폴이 0콜로 끝나고, `catch_up_once`가
`succeeded=True`(applied=0)를 반환해 barrier의 external-buy 차단이 무력화된다.
그 결과 미복구 ante 체결(internal=0, broker>0)이 "외부 매수"로 오분류된다
(#1945 회귀). poll-first는 이를 구조적으로 막는다. `succeeded=True`는 폴이 실제
실행돼 다운타임 체결을 흡수했음을 의미하며, "만료로 open이 비어 0콜"은 성공으로
취급하지 않는다.

## 7. barrier ordering (재기동 무오분류)

기존 `ReconcileScheduler.start()`는 즉시 `run_once()`로 position 대사를 돈다.
fill 복구가 position reconcile보다 **반드시 선행**해야, reconciler가 미복구
ante 체결을 "외부 매수"로 오분류하지 않는다.

main 기동에서 각 계좌 `FillReconcileScheduler.catch_up_once()` **await 완료
후에만** `ReconcileScheduler.start()`를 시작한다. 단순 순서가 아니라 **awaited
hard barrier**다.

## 8. EOD 만료

유효기간이 지난 open 주문(일중 주문이 EOD 경과, pending에도 없고 **history
체결도 없는** genuinely-dead 주문)만 `mark_terminal(expired)`로 표기한다. 무한
폴과 phantom pending을 방지한다.

만료 조건과 순서를 다음으로 못박는다(§6.1 poll-first의 한 축):

- **대상은 `open` 상태만**이다. 부분 체결(`partially_filled`)은 체결이 관측·진행
  중이므로 genuinely-dead가 아니며 만료하지 않는다.
- 만료는 같은 폴 사이클에서 **history 폴(복구)이 끝난 뒤에** 실행한다. 다운타임
  중 체결된 open은 그 폴에서 `filled`/`partially_filled`로 전이되어 이 만료에서
  **자동 제외**된다. 즉 "EOD 경과 open 중 history 체결이 관측되지 않은" 주문만
  남아 만료되므로, 미복구 체결분을 영구 만료하거나 "외부 매수"로 오분류하지
  않는다.
- 만료가 폴 window를 좁히지 않는다: window의 `from_date`는 만료 **전** open의
  가장 이른 `submitted_date`로 잡혀, 전일 open의 다운타임 체결을 덮는다(§6.1
  window invariant). 폴이 실패하면 만료도 실행되지 않아, 미복구 체결분은 다음
  성공 사이클의 폴 window에 그대로 남는다.

## 9. 경계 (out of scope)

- tracker에 없는 broker 포지션(DB wipe·기능 배포 이전 주문)은 본 복구 대상이
  아니다 → reconciler 영역.
- 부분 체결의 Treasury **비례 정산**(filled 비용만 차감)은 pre-existing 한계로
  별도 후속 이슈. 본 스펙은 단일/전량 체결 정산을 정상 유지하며 이를 악화시키지
  않는다.
- 전략 `ctx.get_open_orders()`(live) 백엔드 연결은 별도 후속 이슈(유저스토리 #2).
- 스트림 `H0STCNI0` HTS ID 복원은 선택적 지연 최적화 — 정합성은 REST 백스톱이
  보장한다.
