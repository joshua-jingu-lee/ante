# Treasury 모듈 세부 설계 - Virtual 모드 자산 평가 동기화 배경 (D-TRS-01)

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# Virtual 모드 자산 평가 동기화 배경 (D-TRS-01)

> 기본 인터페이스 계약은 [04-treasury-interface.md](04-treasury-interface.md#자산-평가-동기화-계약)가 SSOT다.
> 이 문서는 Virtual 모드 동기화 계약을 채택한 배경과 영향 범위를 설명한다.

### 배경

Live 모드에서 `_do_sync()`는 브로커 API(`get_account_balance()`, `get_positions()`)를 호출하여 `_purchase_amount`, `_eval_amount`를 갱신한다. 이 값들이 `get_summary()`의 `ante_purchase_amount`, `ante_eval_amount`, `ante_profit_loss`를 결정한다.

Virtual 모드에서는 브로커 동기화가 없으므로 이 필드들이 **항상 0.0**에 머문다. 결과적으로 대시보드 "Ante 관리자산 평가/손익"과 DailyReport의 unrealized_pnl이 0으로 표출된다.

### Live 모드가 브로커 API를 쓰는 이유

| 요인 | Live (브로커 API) | Virtual (Trade DB) |
|------|:---:|:---:|
| 외부 매매 반영 (증권사 앱 직접 매매) | O | X — Ante 주문만 기록 |
| 현재가 평가 정확도 | 높음 (증권사 실시간) | 별도 시세 조회 필요 |
| 비거래 변동 (배당, 증자, 분할) | O | X |

Virtual 모드에는 외부 매매와 비거래 변동이 존재하지 않으므로, Trade DB가 유일하고 정확한 포지션 소스다.

### 채택된 해결 방향

Treasury 동기화는 `trading_mode`에 따라 분기한다:

- **Live**: 기존대로 `broker.get_account_balance()` + `broker.get_positions()` 사용
- **Virtual**: Trade DB(`PositionHistory`)에서 해당 `account_id`의 미청산 virtual 포지션을 조회하여 `_purchase_amount`, `_eval_amount` 계산

```
Virtual 모드 동기화 흐름:

PositionHistory(account_id의 미청산 포지션)
  → SUM(avg_entry_price × quantity) → _purchase_amount
  → SUM(current_price × quantity)   → _eval_amount
  → _external_* = 0 (외부 종목 없음)
```

현재가(`current_price`) 조회는 서버 초기화 시 주입된 Gateway/DataProvider 기반
`price_resolver`를 활용한다. 조회 실패 또는 `price_resolver` 미주입 시
`avg_entry_price` fallback을 허용한다.

### 영향 범위

- `get_summary()`: 수정 없음 — 입력 값(`_purchase_amount`, `_eval_amount`)이 갱신되면 기존 산식 그대로 동작
- `DailyReportScheduler`: 수정 없음 — `get_summary()` 값에 의존
- `take_snapshot()`: 수정 없음 — `get_summary()` 값에 의존
- 대시보드 T-1/T-2: 수정 없음 — 스냅샷 데이터에 의존

### 기본 계약 위치

`start_sync`의 퍼블릭 계약은 [04-treasury-interface.md](04-treasury-interface.md)에 둔다.
이 문서는 더 이상 별도 변경안이 아니며, 기본 인터페이스에 반영된 설계 배경이다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `start_sync` | broker \| None, position_history, interval_seconds=300, trading_mode, price_resolver=None | `None` | 자산 평가 주기적 동기화 시작. Live: 브로커 API 기반. Virtual: Trade DB(PositionHistory) + Gateway/DataProvider 기반 |

### 설계 원칙

- **Treasury는 포지션을 소유하지 않는다** — 이 원칙은 유지된다. Virtual 동기화에서도 PositionHistory를 *조회만* 하며, 포지션 관리 책임은 Trade 모듈에 있다.
- **get_summary() 하위 로직은 모드 무관** — 동기화 경로만 다르고, 산출 로직은 동일하다.
