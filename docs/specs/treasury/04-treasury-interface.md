# Treasury 모듈 세부 설계 - Treasury 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# Treasury 인터페이스

### 생성자

```python
Treasury(
    db: Database,
    eventbus: EventBus,
    account_id: str,
    currency: str = "KRW",
    buy_commission_rate: float = 0.00015,
    sell_commission_rate: float = 0.00195,
    bot_status_checker: Callable[[str], str] | None = None,
)
```

- `account_id`: 이 Treasury가 관리하는 계좌의 ID. 이벤트 필터링 및 DB 데이터 격리에 사용된다.
- `currency`: 계좌의 통화 단위. Account에서 주입된다.
- `buy_commission_rate`: 매수 수수료율. `filled_value × buy_commission_rate`로 계산된다.
- `sell_commission_rate`: 매도 수수료율. `filled_value × sell_commission_rate`로 계산된다.
- `bot_status_checker`: 봇의 현재 상태를 조회하는 콜백. 주입 시 `deallocate()` 호출 전 봇이 정지 상태인지 검증하여, 실행 중인 봇의 예산을 회수하는 실수를 방지한다. 별도로 `set_bot_status_checker()` 메서드로도 주입 가능.

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + DB 복원 + EventBus 구독 |
| `set_account_balance` | balance: float | `None` | 계좌 잔고 설정. 미할당 자금 자동 재계산 |
| `get_available` | bot_id: str | float | 봇의 가용 예산 조회 |
| `get_budget` | bot_id: str | BotBudget \| None | 봇의 예산 상태 조회 |
| `get_budget_sync` | bot_id: str | BotBudget \| None | 봇의 예산 상태 동기 조회 (인메모리). PortfolioView용 |
| `allocate` | bot_id: str, amount: float | bool | 봇에 예산 할당 (미할당 자금에서 차감) |
| `deallocate` | bot_id: str, amount: float | bool | 봇에서 예산 회수 (가용 예산 범위 내) |
| `reserve_for_order` | bot_id: str, order_id: str, amount: float | bool | 주문 제출 시 자금 예약 |
| `release_reservation` | bot_id: str, order_id: str | `None` | 주문 취소/실패 시 예약 해제 |
| `get_reservations` | bot_id: str | dict[str, float] | 봇의 미체결 예약 내역 조회 (`{order_id: amount}`) |
| `list_budgets` | — | list[BotBudget] | 모든 봇의 예산 상태 목록 조회 |
| `set_bot_status_checker` | checker: Callable[[str], str] | None | 봇 상태 조회 콜백 주입. deallocate 시 봇 정지 상태 검증에 사용 |
| `get_summary` | — | dict | 자금 현황 요약 (아래 상세 참조) |
| `sync_balance` | balance_data: dict[str, float] | `None` | 브로커 잔고 데이터로 Treasury 상태 동기화 |
| `start_sync` | broker: BrokerAdapter \| None, position_history: PositionHistory, interval_seconds=300, trading_mode="live", price_resolver=None | `None` | 자산 평가 주기적 동기화 시작. Live는 브로커 기반, Virtual은 Trade DB 기반 |
| `stop_sync` | — | `None` | 잔고 동기화 중지 |
| `update_commission_rates` | buy_commission_rate: float, sell_commission_rate: float | `None` | 수수료율 재주입. 1.0 런타임 DynamicConfig 경로가 아니며, Account cold-path 재초기화/테스트 보조 경로에서만 사용 |
| `release_budget` | bot_id: str | float | 봇 예산 전액 환수. 반환값은 환수된 금액 |
| `update_budget` | bot_id: str, target_amount: float | `None` | 봇 예산 변경. 증가분은 미할당에서 차감, 감소분은 미할당으로 환수 |
| `set_account_info` | account_number: str, is_demo_trading: bool | `None` | KIS 계좌 메타 정보 설정 (계좌번호, 모의투자 여부) |

`set_account_balance(balance)` 입력 invariant: balance는 finite이며 `>=0`. 위반 시 ValueError. POST /api/treasury/balance도 동일 invariant를 ValidationError로 거부한다.

### Reserve 정책 (`_on_order_validated`)

`OrderValidatedEvent` 수신 시 Treasury가 자금을 잠그는지 여부는 주문 종류에 따라 다르다. 본 정책은 한국 증권사 예약주문 표준(예약주문 등록 시점에 잔고를 체크하지 않고, 본주문 전환 시점에 자금 검증)과 일치한다.

| `side` | `order_type` / `price` | 등록 시점 동작 | 비고 |
|--------|------------------------|---------------|------|
| `buy` | `limit` (price 명시) | `reserve_for_order(...)` 호출 후 `OrderApprovedEvent(reserved_amount>0)` 발행 | `quantity * price * (1 + buy_commission_rate)` 만큼 잠금 (기존 산식). |
| `buy` | `market` + `price=None` | account-scoped quote resolver 호출 → reserve 산정 후 `OrderApprovedEvent(price=None, reserved_amount>0)` 발행 (#1333) | resolver 가 반환한 현재가에 `market_order_reserve_buffer_rate` 와 `buy_commission_rate` 를 함께 반영해 보수적으로 잠근다. resolved quote 는 `OrderApprovedEvent.price` 에 넣지 않고 reserve estimate 로만 사용한다. resolver 미주입/예외 시 terminal `OrderRejectedEvent(reason="market_buy_quote_unavailable: ...")` 로 종료. |
| `buy` | `market` (price 명시) | `reserve_for_order(...)` 호출 후 `OrderApprovedEvent(reserved_amount>0)` 발행 | 기존 산식 (`quantity * price * (1 + buy_commission_rate)`). |
| `buy` | `stop`, `stop_limit` | **자금 잠금 없이** `OrderApprovedEvent(reserved_amount=0.0)` 발행 (#1337) | 트리거 발동 후 변환된 일반 매수 주문이 정상 reserve 절차를 거친다. `price=None` 이어도 거부하지 않는다. **분기 우선순위 1** — market buy quote resolver 분기보다 먼저 평가된다. |
| `sell` | 모든 타입 | 자금 잠금 없이 즉시 `OrderApprovedEvent(reserved_amount=0.0)` | 매도는 보유 포지션 기반이므로 reserve 대상이 아님. |

**매수 stop / stop_limit no-reserve invariant (#1337)**:

- 매수 stop / stop_limit 주문은 등록 시점에 자금을 잠그지 않는다. 따라서 사용자(또는 다른 봇)는 같은 자금에 대해 다른 매수 주문을 자유롭게 걸 수 있다.
- 트리거 시점에 StopOrderManager가 발행하는 변환된 `OrderRequestEvent`(market/limit)가 RuleEngine → Treasury를 거치며 그때 처음 reserve가 호출된다. 자금 부족이면 일반 매수 주문 실패와 동일하게 거부된다.
- 등록 단계에서 자금을 잠그지 않았으므로 stop 주문 취소·만료 시 Treasury 호출은 불필요하다. StopOrderManager는 stop 주문 목록에서 항목 제거만 수행한다.
- Treasury가 stop 주문에 대해 reserve 계산 로직을 갖지 않는다. 트리거 변환 이벤트에 "이미 reserved" 플래그 같은 새 필드도 도입하지 않는다 — 등록 시점에 reserve 자체를 안 하므로 플래그가 불필요하다.
- StopOrderManager는 Treasury를 직접 호출하지 않는다. 두 모듈은 자금 처리상 직교한다.

배경 및 사용자 정책 결정 근거는 GitHub 이슈 #1337 본문 "정책 결정 (사용자 승인, 2026-05-08)" 섹션을 참조한다.

**시장가 매수 quote resolver invariant (#1333)**:

- 시장가 매수 (`order_type="market"`, `price=None`) 는 즉시 실행 주문이므로 stop
  처럼 trigger 대기 없이 제출 전 자금을 잠가야 한다.
- Treasury 는 account-scoped resolver
  (`Callable[[str], Awaitable[float]]`) 를 통해 현재가를 조회한다. 기본 경로는
  `APIGateway.get_current_price(symbol, account_id=...)` 이며 `_init_gateway()`
  끝에서 `TreasuryManager.set_order_reserve_price_resolver` 로 후속 주입된다.
  자산 평가 sync 용 `start_sync(price_resolver=...)` 와는 **별도 객체** 다.
- reserve 산식 (Decimal 정밀도):

  ```text
  reserve_basis = quantity * quote * (1 + market_order_reserve_buffer_rate)
  commission_estimate = reserve_basis * buy_commission_rate
  total_reserve = reserve_basis + commission_estimate
  ```

  Decimal 연산 결과는 `OrderApprovedEvent.reserved_amount` / Treasury budget 의
  float 경계에서만 `float` 로 변환한다 (기존 commission/budget float 계약과 일관).
- resolved quote 는 reserve estimate 일 뿐 주문 가격이 아니다. Treasury 는
  `OrderApprovedEvent.price` 를 `None` 그대로 유지하며, BrokerAdapter 는 시장가
  주문 계약을 그대로 사용한다 (KIS 국내: `ORD_DVSN="01"`, `ORD_UNPR="0"`).
- resolver 미주입 또는 resolver 호출이 예외를 raise 하면 Treasury 는 broker
  호출 전 terminal `OrderRejectedEvent(reason="market_buy_quote_unavailable: ...")`
  를 발행한다. EventBus handler 예외로 삼키면 안 된다.
- `market_order_reserve_buffer_rate` 는 Account-level 정책 (`Account` 필드,
  cold-path) 이며 broker_config 에 들어가지 않는다. 기본값은 BrokerPreset 이
  제공한다 (`kis-domestic=0.005`, `test=0`).

**시장가 매수 shortfall 정산 invariant (#1333)**:

- `OrderFilledEvent` 수신 시 Treasury 는 실제 체결 비용
  (`event.price * event.quantity + event.commission`) 으로 정산한다.
- `actual_cost <= reserved_amount` 면 잔여 reserve 를 `available` 로 환수한다
  (기존 거동).
- `actual_cost > reserved_amount` 면 초과분을 `available` 에서 추가 차감한다 —
  결과적으로 `available` 이 음수가 될 수 있다. 음수는 정상 운영 상태가 아니지만
  시장가 매수의 가격 변동을 정확히 정산하기 위해 허용한다. 다음 매수 reserve 가
  거부되는 것은 자연스러운 결과 (insufficient funds) 다.
- shortfall 발생 시 `logger.warning("market_order_reserve_shortfall: ...")` 가
  남고, 별도 EventBus 이벤트는 신설하지 않는다 (Stop Condition 명시).

### 자산 평가 동기화 계약

`start_sync`는 `Account.trading_mode`에 따라 자산 평가 소스를 분기한다.
`trading_mode`는 계좌 생성 후 불변인 Account 속성이며, Treasury는 이 값을 변경하지 않는다.

| 모드 | `broker` | 평가 소스 | 외부 보유종목 | 설명 |
|------|----------|-----------|--------------|------|
| `live` | 필수 | `BrokerAdapter.get_account_balance()` + `BrokerAdapter.get_positions()` | 브로커 포지션과 Trade 포지션 대조로 산정 | 실계좌/모의투자 브로커 상태를 신뢰한다 |
| `virtual` | `None` 허용 | `PositionHistory` + `price_resolver` | 항상 0 | Ante 주문만 존재하므로 Trade DB가 포지션 SSOT다 |

Virtual 모드에서 Treasury는 포지션을 소유하지 않는다. `PositionHistory`에서
`Treasury.account_id`에 속한 미청산 포지션을 조회하여 다음 값만 계산한다.

```text
purchase_amount = SUM(avg_entry_price * quantity)
eval_amount     = SUM(current_price * quantity)
external_*      = 0
```

`current_price`는 `price_resolver(symbol)`로 조회한다. 조회 실패 또는
`price_resolver` 미주입 시 `avg_entry_price`를 fallback으로 사용할 수 있다.
이 fallback은 평가액을 0으로 만들지 않기 위한 보수적 동작이며, 정확한 평가를 위해
서버 초기화 시 Gateway/DataProvider 기반 `price_resolver`를 주입하는 것을 기본 경로로 둔다.

초기화 순서는 다음을 따른다.

1. AccountService가 계좌를 로드한다.
2. TreasuryManager가 계좌별 Treasury를 생성하고 초기화한다.
3. Broker/Gateway/Trade 서비스가 준비된다.
4. 각 계좌의 `trading_mode`에 따라 `start_sync`를 호출한다.

상세 배경은 [09-virtual-asset-sync.md](09-virtual-asset-sync.md)를 참조한다.

### 프로퍼티

| 프로퍼티 | 타입 | 설명 |
|---------|------|------|
| `account_balance` | float | 현재 계좌 잔고 |
| `unallocated` | float | 미할당 자금 |
| `buy_commission_rate` | float | 매수 수수료율 |
| `sell_commission_rate` | float | 매도 수수료율 |

### get_summary() 반환값

| 키 | 설명 |
|----|------|
| `currency` | 통화 단위 (예: "KRW", "USD") |
| `account_balance` | 계좌 예수금 |
| `purchasable_amount` | 매수 가능 금액 |
| `total_evaluation` | 총 자산 평가액 |
| `purchase_amount` | 총 매입 금액 |
| `eval_amount` | 총 평가 금액 |
| `total_profit_loss` | 총 손익 |
| `total_allocated` | 봇별 할당 예산 합계 |
| `total_reserved` | 봇별 예약 금액 합계 |
| `unallocated` | 미할당 자금 |
| `bot_count` | 등록된 봇 수 |
| `external_purchase_amount` | 외부(Ante 미관리) 종목 매입 금액 |
| `external_eval_amount` | 외부 종목 평가 금액 |
| `ante_purchase_amount` | Ante 관리 종목 매입 금액 |
| `ante_eval_amount` | Ante 관리 종목 평가 금액 |
| `ante_profit_loss` | Ante 관리 종목 손익 |
| `total_available` | 봇별 가용 예산 합계 (allocated - reserved) |
| `budget_exceeds_purchasable` | 봇 가용 예산 합계가 매수 가능 금액을 초과하는지 여부 (bool) |
| `account_number` | KIS 계좌번호 |
| `is_demo_trading` | 모의투자 여부 (bool) |
| `last_sync_time` | 마지막 잔고 동기화 시각 |

소스: `src/ante/treasury/treasury.py`
