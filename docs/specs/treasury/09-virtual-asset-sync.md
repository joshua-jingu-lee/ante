# Treasury 모듈 세부 설계 - Virtual 모드 자산 평가 동기화 (D-TRS-01)

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# Virtual 모드 자산 평가 동기화 (D-TRS-01)

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

### 해결 방향

`_do_sync()`에서 `trading_mode`에 따라 분기한다:

- **Live**: 기존대로 `broker.get_account_balance()` + `broker.get_positions()` 사용
- **Virtual**: Trade DB(`PositionHistory`)에서 Paper 포지션을 조회하여 `_purchase_amount`, `_eval_amount` 계산

```
Virtual 모드 동기화 흐름:

PositionHistory.get_positions(account_id)
  → SUM(avg_entry_price × quantity) → _purchase_amount
  → SUM(current_price × quantity)   → _eval_amount
  → _external_* = 0 (외부 종목 없음)
```

현재가(`current_price`) 조회는 PaperExecutor의 시뮬레이션 시세(DataProvider)를 활용한다.

### 영향 범위

- `get_summary()`: 수정 없음 — 입력 값(`_purchase_amount`, `_eval_amount`)이 갱신되면 기존 산식 그대로 동작
- `DailyReportScheduler`: 수정 없음 — `get_summary()` 값에 의존
- `take_snapshot()`: 수정 없음 — `get_summary()` 값에 의존
- 대시보드 T-1/T-2: 수정 없음 — 스냅샷 데이터에 의존

### 스펙 변경

퍼블릭 메서드 테이블의 `start_sync` 설명을 아래와 같이 변경한다:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `start_sync` | broker \| None, position_history, interval_seconds=300, trading_mode=VIRTUAL | `None` | 자산 평가 주기적 동기화 시작. Live: 브로커 API 기반. Virtual: Trade DB(PositionHistory) + DataProvider 기반 |

### 설계 원칙

- **Treasury는 포지션을 소유하지 않는다** — 이 원칙은 유지된다. Virtual 동기화에서도 PositionHistory를 *조회만* 하며, 포지션 관리 책임은 Trade 모듈에 있다.
- **get_summary() 하위 로직은 모드 무관** — 동기화 경로만 다르고, 산출 로직은 동일하다.
