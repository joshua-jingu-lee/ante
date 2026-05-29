# Strategy 모듈 세부 설계 - 설계 결정 - DataProvider / PortfolioView / OrderView ABC

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# DataProvider / PortfolioView / OrderView ABC

구현: `src/ante/strategy/base.py` 참조

StrategyContext에 주입되는 인터페이스. 라이브/백테스트/모의투자 모드에 따라 구현체가 달라진다.

#### DataProvider 메서드 시그니처

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_ohlcv` | `symbol: str, timeframe: str = "1d", limit: int = 100` | `DataFrame` | OHLCV 데이터 조회. columns: [timestamp, open, high, low, close, volume] |
| `get_current_price` | `symbol: str` | `float` | 현재가 조회 |
| `get_indicator` | `symbol: str, indicator: str, params: dict \| None = None` | `dict[str, Any]` | 기술 지표 데이터 조회 (sma, rsi, macd 등). pandas-ta 기반 계산 |

#### TradeHistoryView 메서드 시그니처

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_trade_history` | `bot_id: str, symbol: str \| None = None, limit: int = 50` | `list[dict[str, Any]]` | 봇의 거래 이력 조회. 최신순 반환 |

#### PortfolioView 메서드 시그니처

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_positions` | `bot_id: str` | `dict[str, Any]` | 현재 보유 포지션 조회. `{symbol: {"quantity", "avg_price", "current_price", "unrealized_pnl"}}` |
| `get_balance` | `bot_id: str` | `dict[str, float]` | 봇 할당 자금 현황. `{"total", "available", "reserved"}` |

#### OrderView 메서드 시그니처

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_open_orders` | `bot_id: str` | `list[dict[str, Any]]` | 미체결 주문 목록 조회. dict 필드는 아래 **OpenOrder dict 스키마** 참조 |

##### OpenOrder dict 스키마 (SSOT)

`get_open_orders`가 반환하는 dict의 필드 스키마. 세 구현체(live/virtual/backtest)가 동일 스키마를 따른다. IPC `signal_channel`의 `open_orders` query도 이 dict를 `data`로 그대로 pass-through하므로(envelope 일관성), 전략·telegram·IPC 세 소비자가 공통으로 의존한다.

| 필드 | 타입 | 설명 |
|------|------|------|
| `order_id` | `str` | ante 내부 주문 ID (전역 유일) |
| `symbol` | `str` | 종목 코드 |
| `side` | `str` | `buy` / `sell` |
| `ordered_qty` | `float` | 주문 수량 |
| `recorded_filled_qty` | `float` | 기록된 누적 체결 수량 |
| `remaining_qty` | `float` | 미체결 잔량 (`ordered_qty - recorded_filled_qty`, 음수면 0) |
| `status` | `str` | `open` / `partially_filled` (terminal은 목록에서 제외됨) |
| `submitted_at` | `str \| None` | 주문 제출 시각 (ISO8601, nullable) |

- **`amount`(예약 금액) 제외**: 예약 금액은 Treasury 도메인(`treasury` reserved)이지 주문 가시성(OrderView)이 아니다. OpenOrder 스키마는 **수량 기반**이다.
- **scope = ante 제출 한정**: LIVE는 OrderTracker(ante 제출 미체결/체결 SSOT)를 경유하므로, 수동/외부 주문은 반영되지 않는다. 전략의 "미체결" 정의 = ante가 제출한 주문 한정.
- **가시성 한계 (known-limitation)**:
  - **cross-step만 보장**: 이전 step에서 제출돼 `OrderSubmittedEvent`로 OrderTracker에 seed된 주문만 가시. 같은 step 안에서 이벤트 발행 전 연속 제출하는 intra-step 중복은 미가시(전략 책임, submit-side pending guard는 별도 후속 범위).
  - **cold-cache best-effort**: LIVE는 OrderTracker의 sync 인메모리 캐시(commit된 DB 미러)에서 조회한다. startup warm 완료 전에는 빈 결과가 가능하다. DB가 진리원이며 잔여 안전망은 reconciler.

**구현체 매핑**:

| ABC | live 봇 | virtual 봇 | 백테스트 |
|-----|---------|---------|---------|
| DataProvider | LiveDataProvider (API Gateway 경유) | LiveDataProvider (동일) | BacktestDataProvider (Parquet) |
| PortfolioView | LivePortfolioView (Treasury + Trade) | VirtualPortfolioView (인메모리) | BacktestPortfolioView |
| OrderView | LiveOrderView (**OrderTracker SSOT 경유** — sync open 캐시, account scope) | VirtualOrderView (인메모리, OrderTracker 미사용 — 즉시 체결로 open window 없음) | BacktestOrderView (`[]`, 미체결 미지원) |

**OrderView 미체결 가시성 데이터 흐름** (LIVE):

```
OrderSubmittedEvent → OrderTracker.open() (DB INSERT + open 캐시 upsert)
체결 관측(스트림/폴) → FillApplier 트랜잭션 (record_fill CAS)
                    → commit 직후 OrderTracker.mirror_fill_to_cache() (확정값 미러, filled면 evict)
terminal(취소/거부/실패) → OrderTracker.mark_terminal() (DB UPDATE + 캐시 evict)
EOD 만료 → OrderTracker.expire_stale() (DB UPDATE + 캐시 evict)
전략/telegram/IPC → ctx.get_open_orders() → LiveOrderView → OrderTracker sync 캐시 (account scope, OPEN_STATUSES만)
```

캐시는 **commit된 DB 상태의 미러**일 뿐 진리원이 아니다. 체결 미러는 FillApplier 트랜잭션이 정상 COMMIT된 직후에만 일어나므로, rollback 시 캐시는 DB와 일관되게 불변이다.
