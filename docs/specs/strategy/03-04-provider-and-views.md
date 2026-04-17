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
| `get_open_orders` | `bot_id: str` | `list[dict[str, Any]]` | 미체결 주문 목록 조회 |

**구현체 매핑**:

| ABC | live 봇 | paper 봇 | 백테스트 |
|-----|---------|---------|---------|
| DataProvider | LiveDataProvider (API Gateway 경유) | LiveDataProvider (동일) | BacktestDataProvider (Parquet) |
| PortfolioView | LivePortfolioView (Treasury + Trade) | PaperPortfolioView (인메모리) | BacktestPortfolioView |
| OrderView | LiveOrderView (BrokerAdapter 경유) | PaperOrderView (인메모리) | BacktestOrderView |
