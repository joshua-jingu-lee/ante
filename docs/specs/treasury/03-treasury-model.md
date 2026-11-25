# Treasury 모듈 세부 설계 - 자금 관리 모델

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 자금 관리 모델

### 계층 구조

```
전체 계좌 잔고 (Account Balance)
├── 봇별 할당 예산 (Bot Allocation)
│   ├── 봇 A: 500만원 (활성)
│   ├── 봇 B: 300만원 (활성)
│   └── 봇 C: 200만원 (중지)
└── 미할당 자금 (Unallocated)
```

### BotBudget 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| bot_id | str | 봇 고유 ID |
| account_id | str | 소속 계좌 ID |
| allocated | float | 할당된 총 예산 |
| available | float | 가용 예산 |
| reserved | float | 주문 대기 중 예약된 금액 |
| spent | float | 체결로 투입된 금액 (누적) |
| returned | float | 매도 체결로 회수된 금액 (누적) |
| last_updated | datetime | 마지막 갱신 시각 |

**핵심 원리**: `available = allocated - reserved - spent + returned`

- `reserve_for_order()`: 주문 제출 시 available → reserved 이동
- `on_buy_filled()`: reserved → spent 이동 (실제 체결 금액 기준)
- `on_sell_filled()`: returned 증가, available 증가
- `release_reservation()`: 주문 취소/실패 시 **잔여 예약**을 reserved → available 복원

소스: `src/ante/treasury/models.py`

### 매수 부분체결 비례 정산 (#1947)

스트림/폴 fill-recovery 경로(`FillApplier`)는 **체결 delta마다** `OrderFilledEvent`를
발행한다. 따라서 한 주문이 여러 번에 나눠 체결되면 Treasury는 fill마다 그 delta의
실비용만큼만 예약을 차감하고, **주문이 terminal(전량 체결/취소/실패)에 도달한
경우에만** 잔여 예약을 회수한다. 첫 partial 체결이 전체 예약을 통째로 해제하지 않는다.

주문별로 **잔여 예약**(`remaining_reserved`)을 추적한다. `reserve_for_order()`가 예약
총액 `R`로 초기화하고, 매수 fill마다 아래와 같이 정산한다.

- `actual_cost = quantity * price + commission`
- `covered = min(remaining_reserved, actual_cost)`
- `reserved -= covered` ; `remaining_reserved -= covered` ; `spent += actual_cost`
- `shortfall = actual_cost - covered`; `shortfall > 0`이면 `available -= shortfall`
  (체결가가 잔여 예약분을 초과 — 시장가 가격 변동 등. 기존 시장가 reserve shortfall
  동작 보존, audit warning 유지)

**terminal 판정**은 `OrderTracker`(`recorded_filled_qty >= ordered_qty`)로 한다.
`FillApplier`가 `record_fill()` 커밋 후 `OrderFilledEvent`를 발행하므로 Treasury가
보는 tracker 상태는 이번 fill을 이미 포함한다. terminal이면 잔여 예약(`remaining_
reserved`, under-fill surplus)을 `reserved → available`로 회수하고 추적 entry를
제거한다. 중간 partial이면 entry를 유지해 다음 fill 정산에 이월한다.

**OrderTracker 부재 fallback**: `OrderTracker.get(order_id)`가 `None`인 주문(예:
`VirtualProvider`가 OrderTracker에 seed 없이 직접 발행하는 단일 full-fill 이벤트)은
기존 full-fill pop-once semantics(전액 예약 차감 + surplus/shortfall 1회 정산)로
fallback한다. 단일 full-fill엔 pop-once가 정확하다.

**취소/실패**: 부분체결 후 취소/실패 시 이미 체결된 분은 위 per-fill
정산으로 `spent`에 반영되어 `reserved`에서 빠진 상태이므로, **잔여 예약만** 회수해
기체결분을 보존한다. 봇 정지는 추적기에서 열린(`open`·`partially_filled`) 주문의 잔여
예약을 남기고, 추적 기록이 없거나 이미 종결된 주문의 잔여 예약만 회수한다.

이 전 구간에서 불변식 `available = allocated - reserved - spent + returned`가 유지된다.

**범위**: buy 한정. 매도는 예약을 하지 않고 fill마다 `actual_proceeds = quantity*price
- commission`을 `returned`/`available`에 독립 누적 가산하므로 부분 매도가 이미 정확하다
(`on_sell_filled()`). 따라서 sell-side는 변경 대상이 아니다.

소스: `src/ante/treasury/treasury.py` (`_on_order_filled` buy 분기 · `_settle_buy_fill`),
`src/ante/trade/order_tracker.py`

### 재시작 뒤의 예약 (#2770)

주문별 잔여 예약(`remaining_reserved`)은 Treasury 소유 테이블 `treasury_reservations`에
계좌별로 영속되고, `initialize()`가 `bot_budgets`와 함께 복원한다. 재시작 뒤에도 미종결
매수 주문의 취소·실패·체결·봇 정지의 회수(열린 주문 제외)가 재시작 전과 같은 잔여 예약을 정산한다.

- 예약·체결 정산·취소/실패 회수·봇 정지의 회수(열린 주문 제외)는 예약 표의 변경을 그 행에 쓰는 일과
  `bot_budgets` 저장을 한 트랜잭션으로 한다. 실패하면 그 연산의 증감과 그 주문의 예약 항목만
  되돌려 그 사이 다른 연산의 변경은 남긴다. 예약 항목을 바꾼 연산은 그 항목이 이 연산이 남긴
  그대로일 때만 되돌리고, 다른 연산이 그 주문의 예약을 이미 바꾸거나 회수했으면 되돌리지 않는다.
- 잔여 예약이 0이 된 항목이나 예산이 없는 봇의 항목도 회수 때 행을 지운다.
- 봇 삭제(`release_budget()`)는 `bot_budgets` 행과 그 봇의 예약 행을 한 트랜잭션에서
  지운다. 트랜잭션이 실패하면 미할당 잔액에 더한 할당액을 빼고, 메모리에서 꺼낸 예산은
  그 자리가 비어 있으면 되돌려 넣는다.
- 이 테이블이 생기기 전에 걸린 예약은 행이 없어 주문별로 귀속되지 않는다. 부팅 때 봇의
  `reserved`와 그 봇 행의 합이 다르면 경고 로그를 남기고 값은 바꾸지 않는다(회수하지
  않는다).
- EOD 만료는 Treasury에 통지되지 않아 만료된 주문의 예약과 그 행은 남는다(#2842).
