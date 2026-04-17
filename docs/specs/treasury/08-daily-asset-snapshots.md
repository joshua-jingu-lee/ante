# Treasury 모듈 세부 설계 - 일별 자산 스냅샷 (Daily Asset Snapshot)

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 일별 자산 스냅샷 (Daily Asset Snapshot)

### 배경

자금 관리 화면 T-1(총 자산·당일 손익)과 T-2(자산 추이 차트)를 지원하려면 일별 자산 평가액의 시계열 데이터가 필요하다. 현재 `treasury_state`는 최신 상태를 덮어쓰기(`ON CONFLICT DO UPDATE`)하므로 과거 이력이 보존되지 않는다. 거래 기록만으로는 미실현 손익 변동(보유 종목 시세 변화)을 복원할 수 없어, 별도의 일별 스냅샷이 필요하다.

### 데이터 정의

```sql
CREATE TABLE treasury_daily_snapshots (
    account_id           TEXT    NOT NULL,
    snapshot_date        TEXT    NOT NULL,  -- ISO 날짜 (YYYY-MM-DD, KST 기준)
    -- 자산 현황
    total_asset          REAL    NOT NULL,  -- ante_eval_amount + unallocated
    ante_eval_amount     REAL    NOT NULL,  -- Ante 관리 종목 평가액
    ante_purchase_amount REAL    NOT NULL,  -- Ante 관리 종목 매입액
    unallocated          REAL    NOT NULL,  -- 미할당 현금
    account_balance      REAL    NOT NULL,  -- 계좌 예수금
    total_allocated      REAL    NOT NULL,  -- 봇 할당 합계
    bot_count            INTEGER NOT NULL,  -- 활성 봇 수
    -- 일별 성과 (DailyReportEvent에서 수신, Treasury는 저장만)
    daily_pnl            REAL    DEFAULT 0.0,  -- 당일 손익
    daily_return         REAL    DEFAULT 0.0,  -- 당일 수익률
    net_trade_amount     REAL    DEFAULT 0.0,  -- 당일 순매수금액
    unrealized_pnl       REAL    DEFAULT 0.0,  -- 미실현 손익
    --
    created_at           TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, snapshot_date)
);
```

### 스냅샷 생성 시점

Account 모듈의 `trading_hours_end` + 여유 시간(30분)을 기준으로 한다.

| 프리셋 | `trading_hours_end` | timezone | 스냅샷 시각 |
|--------|--------------------|-----------|-----------|
| kis-domestic | 15:30 | Asia/Seoul | 16:00 KST |
| kis-overseas | 16:00 | America/New_York | 16:30 ET |

현재 `DailyReportScheduler`가 하드코딩된 16:00 KST에 실행되고 있으나, Account의 거래시간 정보를 참조하도록 개선하여 계좌별로 적절한 스냅샷 시각을 결정해야 한다.

```
DailyReportScheduler (Trade, account.trading_hours_end + 30min)
  → DailyReportEvent 발행 (성과 필드 포함: daily_pnl, daily_return, net_trade_amount, unrealized_pnl)
    → Treasury 구독 (priority 80)
      → get_summary() 호출 (자산 현황만)
      → 성과 필드는 이벤트에서 그대로 수신
      → treasury_daily_snapshots UPSERT (INSERT OR REPLACE) — 동일 날짜는 항상 덮어쓰기
```

### 동일 날짜 중복 방지

**원칙: 하나의 계좌에 대해 같은 날짜의 스냅샷은 반드시 1행만 존재한다.**

- `PRIMARY KEY (account_id, snapshot_date)`로 DB 레벨에서 유니크 보장
- `take_snapshot`은 **INSERT OR REPLACE** — 동일 날짜에 이미 스냅샷이 존재하면 최신 데이터로 덮어쓰기
- 스케줄러 재시작, 수동 재실행, 이벤트 중복 수신 등 어떤 경우에도 2행이 생기지 않음
- 덮어쓰기를 통해 늦은 체결 반영, 데이터 보정 등 상황에서도 최신 상태가 유지됨

### 일별 성과 필드

**Treasury는 성과 필드를 직접 계산하지 않는다.** DailyReportEvent에 포함된 값을 그대로 저장한다.

- 산식 정의 및 산출 주체: [trade.md — DailyReportScheduler 일별 성과 산식](../trade/trade.md#일별-성과-산식)
- 수익률 기준: `ante_eval_amount` 기반 (미할당 현금 제외)
- 기간 수익률: 일별 수익률의 기하평균 `(1 + r₁) × (1 + r₂) × ... × (1 + rₙ) - 1` — 프론트엔드 계산

### 화면 연동

| 화면 | 계산 | 데이터 소스 |
|------|------|------------|
| T-1 총 자산 | 가장 최근 스냅샷의 `total_asset` | `treasury_daily_snapshots` (최신 1행) |
| T-1 당일 손익 | 최근 스냅샷의 `daily_pnl` | `treasury_daily_snapshots` (최신 1행) |
| T-1 당일 수익률 | 최근 스냅샷의 `daily_return` × 100 | `treasury_daily_snapshots` (최신 1행) |
| T-1 산정 기준일 | 최근 스냅샷의 `snapshot_date` | `treasury_daily_snapshots` (최신 1행) |
| T-2 자산 추이 | 기간별 `total_asset` 시계열 | `treasury_daily_snapshots` 조회 |
| T-2 일별 수익률 | 기간별 `daily_return` 시계열 | `treasury_daily_snapshots` 조회 |
| T-2 기간 수익률 | `daily_return` 기하평균 | 프론트엔드 계산 |

> 유저스토리: [자금 관리 T-1, T-2](../../dashboard/user-stories/treasury.md)
> 자금 관리 화면은 실시간 조회 없이 **가장 최근 스냅샷 기준**으로 표시한다. 장 마감 후 스냅샷이 기록되면 화면에 반영된다.

### 인터페이스

Treasury 퍼블릭 메서드:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `take_snapshot` | event: DailyReportEvent | dict | 이벤트의 성과 필드 + get_summary() 자산 현황을 합쳐 스냅샷 기록. INSERT OR REPLACE. 저장한 스냅샷 dict 반환 |
| `get_daily_snapshot` | snapshot_date: str | dict \| None | 특정일 스냅샷 조회 |
| `get_snapshots` | start_date: str, end_date: str | list[dict] | 기간 내 스냅샷 목록 조회 (차트용) |

### 설계 결정

- 이벤트 타입 → **`DailyReportEvent` 신설**. Trade 스펙 참조.
- 비거래일 처리 → **매일 기록** (비거래일 포함). 비거래일에는 전일과 동일한 값이 기록됨. 차트에서 빈 날짜 처리 로직 불필요.
- 대시보드 실시간성 → **실시간 조회 없음**. 대시보드는 가장 최근 스냅샷 기준으로 표시. `get_summary()` 실시간 호출 불필요.
- 보존 정책 → **최대 5년**. 연간 ~365행 × 5년 = ~1,825행. 5년 초과 데이터는 자동 삭제.

### 조회 인터페이스

스냅샷 데이터는 CLI와 Web API를 통해 외부에 제공한다.

**Web API**:

| 엔드포인트 | 메서드 | 파라미터 | 설명 |
|-----------|--------|---------|------|
| `/treasury/snapshots/latest` | GET | `account_id` | 가장 최근 스냅샷 조회 (T-1) |
| `/treasury/snapshots` | GET | `account_id`, `start_date`, `end_date` | 기간별 스냅샷 목록 조회 (T-2 차트) |
| `/treasury/snapshots/{date}` | GET | `account_id`, `date` | 특정일 스냅샷 조회 |

**CLI**:

```bash
# 최근 스냅샷 조회
ante treasury snapshot --format json

# 기간별 스냅샷 조회 (차트 데이터)
ante treasury snapshot --from 2026-01-01 --to 2026-03-21 --format json

# 특정일 스냅샷 조회
ante treasury snapshot --date 2026-03-20 --format json
```
