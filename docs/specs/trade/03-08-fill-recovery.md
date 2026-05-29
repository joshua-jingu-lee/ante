# Trade 모듈 세부 설계 - 설계 결정 - OrderTracker / FillApplier — 체결 durability 권위자

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)
> 참조: [broker-adapter/18-fill-recovery.md](../broker-adapter/18-fill-recovery.md) 체결 반영 경로 전체 흐름

# OrderTracker / FillApplier — 체결 durability 권위자

구현: `src/ante/trade/order_tracker.py`, `src/ante/trade/fill_applier.py` 참조

체결(fill)의 durable 적용 — `recorded_filled_qty` advance + `TradeRecord` insert +
`PositionHistory.on_trade`(positions) — 은 **`FillApplier` 단일 권위자**가 단일
DB 트랜잭션으로 수행한다. 빠른 경로(실시간 체결 통보 스트림)와 백스톱 경로(REST
`get_order_history` 폴)가 모두 `FillApplier`로 수렴하여 같은 체결을 몇 번
관측하든 포지션은 정확히 한 번 반영된다 (#1946).

## OrderTracker

추적 주문을 DB(`order_tracker` 테이블)에 영속하여 재기동 후에도 open/partial
주문이 생존하고, 관측된 누적 체결량을 단조(monotonic) advance한다.

### identity

- **PK = 내부 `order_id`** (`OrderSubmittedEvent`의 ante `uuid4` — 생성상 전역
  유일). CAS는 `WHERE order_id=:oid` 단일 행이라 모호성 없음.
- `(account_id, broker_order_id, submitted_date)` = UNIQUE 인덱스 + 조회 키.
  KIS `odno`(broker_order_id)가 계좌 간/paper·live/영업일 재사용으로 충돌할 수
  있어 broker_order_id 단독 키는 쓰지 않는다. 조회는 non-terminal/same-day로
  한정해 일자 재사용 충돌을 닫는다.

### 퍼블릭 메서드

| 메서드 | 반환값 | 설명 |
|---|---|---|
| `initialize` | `None` | 스키마 생성 |
| `open(order_id, account_id, bot_id, strategy_id, broker_order_id, symbol, side, order_type, ordered_qty, submitted_date)` | `None` | `OrderSubmittedEvent`로 추적 주문 seed |
| `record_fill(order_id, new_cumulative, avg_price)` | `applied_delta: float` | 원자 CAS advance. `delta = new_cumulative - 이전 recorded`; `<=0`이면 0(no-op), `>0`이면 recorded 갱신 후 delta. **FillApplier 트랜잭션 내에서만 호출** |
| `mark_terminal(order_id, status)` | `None` | 취소·거부·실패·만료 종료 표기 |
| `get_open_orders(account_id)` | `list[OrderTrackerRecord]` | 계좌의 non-terminal 주문 |
| `lookup_order_id(account_id, broker_order_id, submitted_date)` | `str \| None` | 관측 → 내부 order_id 매핑(non-terminal/same-day) |
| `expire_stale(account_id, before_date)` | `int` | EOD 경과 open → `expired`, 만료 건수 반환 |

### 불변식

- `recorded_filled_qty`는 order별 **단조 비감소**.
- 각 증가(delta>0)는 정확히 1개 `OrderFilledEvent(delta)`와 1쌍.
- 포지션 = Σdelta = 최종 누적 체결량.

## FillApplier — 단일 멱등 choke point

단일 인스턴스이며 `asyncio.Lock`이 **read → delta → txn → publish 전체**를 감싼다.

`apply_cumulative(account_id, broker_order_id, observed_cumulative, avg_price, submitted_date)`:

1. `lookup_order_id`로 추적 주문 확인. 없으면 **무시**(self/external 경계 — 진짜
   외부 포지션은 reconciler 영역).
2. `Database.transaction()` 단일 트랜잭션 안에서: CAS advance(delta 산출) →
   `delta<=0`이면 no-op → `delta>0`이면 `TradeRecord` insert +
   `PositionHistory.on_trade` → commit.
3. commit 이후 `OrderFilledEvent`(quantity=delta, price=avg_price,
   order_id/bot_id/strategy_id/account_id는 tracker에서 복원) 1회 발행.

### crash 원자성

CAS advance와 trade insert·position update가 단일 트랜잭션으로 묶이므로, 적용
도중 crash하면 rollback되어 recorded가 advance되지 않고 재기동 후 다음 폴이
동일 delta를 재적용한다. → positions/trades는 **crash-safe exactly-once**.

`OrderFilledEvent`는 **커밋 이후 발행되는 알림**(strategy `on_fill`, Treasury
정산, notification)이다. commit↔publish 사이 narrow crash window의 이벤트 전달
유실은 재기동 catch-up + reconcile로 재정합되며, 완전한 exactly-once 이벤트
전달은 별도 후속(transactional outbox)으로 분리한다.

## TradeRecorder와의 관계 (권위 일원화)

`TradeRecorder._on_filled`는 더 이상 fill 경로의 position을 갱신하지 않는다.
fill의 position 갱신은 **FillApplier(트랜잭션 내)가 단일 권위자**로 수행한다
(이중 적용 방지). TradeRecorder는 rejected/failed/cancelled 등 비-fill 상태
기록과 알림을 유지한다.

position 소유는 Trade 모듈 내(FillApplier도 `trade/`)에 유지된다 — position
ownership invariant.
