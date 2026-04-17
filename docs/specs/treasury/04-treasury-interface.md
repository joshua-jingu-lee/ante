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
| `sync_balance` | balance_data: dict[str, float] | `None` | KIS 잔고 데이터로 Treasury 상태 동기화 |
| `start_sync` | broker, position_history, interval_seconds=300 | `None` | KIS 계좌 잔고 주기적 동기화 시작 |
| `stop_sync` | — | `None` | 잔고 동기화 중지 |
| `update_commission_rates` | buy_commission_rate: float, sell_commission_rate: float | `None` | 수수료율 업데이트 (DynamicConfig 변경 시) |
| `release_budget` | bot_id: str | float | 봇 예산 전액 환수. 반환값은 환수된 금액 |
| `update_budget` | bot_id: str, target_amount: float | `None` | 봇 예산 변경. 증가분은 미할당에서 차감, 감소분은 미할당으로 환수 |
| `set_account_info` | account_number: str, is_demo_trading: bool | `None` | KIS 계좌 메타 정보 설정 (계좌번호, 모의투자 여부) |

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
