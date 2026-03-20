# Strategy Guide

Ante에서 전략을 작성하고, 백테스트하고, 실제 거래에 투입하기까지의 과정을 안내합니다.

## 전략이란?

전략은 **"언제, 무엇을, 얼마나 사고팔 것인가"를 코드로 표현한 것**입니다. Ante에서 전략은 하나의 Python 파일(`.py`)이며, `Strategy` 기본 클래스를 상속하여 작성합니다.

전략 파일의 핵심은 `on_step()` 메서드입니다. Ante가 주기적으로 이 메서드를 호출하면, 전략은 현재 시장 상황을 판단하여 매매 시그널을 반환합니다. 시그널이 없으면 빈 리스트를 반환합니다.

```python
from ante.strategy.base import Strategy, StrategyMeta, Signal


class MyStrategy(Strategy):
    meta = StrategyMeta(
        name="my_strategy",
        version="1.0.0",
        description="간단한 전략 예시",
        symbols=["005930"],
        timeframe="1d",
    )

    async def on_step(self, context: dict) -> list[Signal]:
        price = await self.ctx.get_current_price("005930")

        if price < 50000:
            return [Signal(symbol="005930", side="buy", quantity=10, reason="저가 매수")]

        return []
```

### 전략 메타데이터

모든 전략은 `meta` 클래스 변수에 메타데이터를 선언해야 합니다.

| 필드 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `name` | O | — | 전략 고유 이름 |
| `version` | O | — | 시맨틱 버전 (예: `1.0.0`) |
| `description` | O | — | 전략 설명 |
| `author` | - | `"agent"` | 작성자 |
| `symbols` | - | `None` | 대상 종목 코드 (`None`이면 봇 설정에서 지정) |
| `timeframe` | - | `"1d"` | 기본 타임프레임 |
| `exchange` | - | `"KRX"` | 거래소 |
| `accepts_external_signals` | - | `False` | 외부 시그널 수신 여부 |

### 시그널

`on_step()`이 반환하는 `Signal`은 하나의 주문 의도를 표현합니다.

| 필드 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `symbol` | O | — | 종목 코드 |
| `side` | O | — | `"buy"` 또는 `"sell"` |
| `quantity` | O | — | 수량 |
| `order_type` | - | `"market"` | `"market"`, `"limit"`, `"stop"`, `"stop_limit"` |
| `price` | - | `None` | 지정가 (limit/stop_limit) |
| `stop_price` | - | `None` | 트리거 가격 (stop/stop_limit) |
| `reason` | - | `""` | 매매 사유 (로깅·리포트용) |

### 전략에서 사용할 수 있는 API

전략은 `self.ctx`를 통해 데이터를 조회하고 주문을 관리합니다. 시스템 내부에는 직접 접근할 수 없습니다.

**데이터 조회:**

```python
ohlcv = await self.ctx.get_ohlcv("005930", timeframe="1d", limit=100)
price = await self.ctx.get_current_price("005930")
indicator = await self.ctx.get_indicator("005930", "rsi", {"timeperiod": 14})
```

**포트폴리오 조회:**

```python
positions = self.ctx.get_positions()       # {"005930": {"quantity": 10, "avg_price": 58200, ...}}
balance = self.ctx.get_balance()           # {"total": ..., "available": ..., "reserved": ...}
orders = self.ctx.get_open_orders()        # 미체결 주문 목록
history = await self.ctx.get_trade_history(symbol="005930", limit=50)
```

**주문 관리:**

```python
self.ctx.cancel_order(order_id="ORD-001", reason="전략 조건 변경")
self.ctx.modify_order(order_id="ORD-001", price=59000, reason="지정가 수정")
```

**기술 지표:** `get_indicator()`로 15종의 기술 지표를 사용할 수 있습니다.

| 지표 | 이름 | 주요 파라미터 |
|------|------|-------------|
| SMA | 단순이동평균 | `timeperiod` |
| EMA | 지수이동평균 | `timeperiod` |
| RSI | 상대강도지수 | `timeperiod` |
| MACD | 이동평균수렴확산 | `fast`, `slow`, `signal` |
| BBANDS | 볼린저밴드 | `timeperiod`, `nbdev` |
| ATR | 평균진폭 | `timeperiod` |
| STOCH | 스토캐스틱 | `fastk`, `slowk`, `slowd` |
| ADX | 평균방향지수 | `timeperiod` |
| CCI | 상품채널지수 | `timeperiod` |
| OBV | 거래량잔고 | — |
| WMA | 가중이동평균 | `timeperiod` |
| DEMA | 이중지수이동평균 | `timeperiod` |
| TEMA | 삼중지수이동평균 | `timeperiod` |
| WILLR | 윌리엄스 %R | `timeperiod` |
| MFI | 자금흐름지수 | `timeperiod` |

### 라이프사이클 메서드

`on_step()` 외에 선택적으로 구현할 수 있는 메서드입니다.

| 메서드 | 호출 시점 | 반환 |
|--------|----------|------|
| `on_start()` | 봇 시작 시 1회 | — |
| `on_stop()` | 봇 중지 시 1회 | — |
| `on_fill(fill)` | 주문 체결 시 | `list[Signal]` (후속 주문 가능) |
| `on_order_update(update)` | 주문 상태 변경 시 (접수/거부/취소) | — |
| `on_data(data)` | 외부 시그널 수신 시 (`accepts_external_signals=True`) | `list[Signal]` |
| `get_rules()` | 전략별 거래 룰 반환 | `dict` |
| `get_params()` | 백테스트 최적화 파라미터 | `dict` |

## 전략이 거래로 연결되는 흐름

전략 파일이 실제 매매로 이어지는 전체 과정입니다.

```
전략 파일 (.py)
  ↓ ante strategy submit — 검증 후 Registry에 등록
  ↓
봇 생성 (ante bot create --strategy <strategy_id>)
  ↓ ante bot start — 봇 가동
  ↓
주기적 루프 (interval_seconds마다)
  ├─ on_step(context) 호출
  ├─ 반환된 Signal → OrderRequestEvent 발행
  ├─ Rule Engine 검증 (전역 룰 + 전략별 룰)
  └─ 통과 시 → 증권사 API로 실제 주문 실행
         ↓
    체결 통보 → on_fill() 호출 → 후속 주문 가능
```

핵심은 **전략은 시그널만 반환하고, 실제 주문은 시스템이 처리한다**는 점입니다. 전략이 반환한 시그널은 Rule Engine을 거치며, 전역 손실 한도, 포지션 크기 제한 등의 안전 규칙에 위배되면 주문이 차단됩니다.

봇은 `live`(실투자)와 `paper`(모의투자) 두 가지 타입이 있습니다. 전략 코드는 동일하게 동작하며, 봇 타입에 따라 실제 주문이 나가거나 가상으로 체결됩니다.

## 백테스팅

작성한 전략을 과거 데이터로 시뮬레이션하여 성과를 검증합니다. 전략 코드 수정 없이 그대로 사용합니다.

### 실행

```bash
ante backtest run strategies/my_strategy.py \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --symbols 005930,000660 \
  --balance 10000000 \
  --timeframe 1d
```

| 옵션 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `<strategy_path>` | O | — | 전략 파일 경로 |
| `--start` | O | — | 시작일 (YYYY-MM-DD) |
| `--end` | O | — | 종료일 (YYYY-MM-DD) |
| `--symbols` | - | 전략 meta | 종목 코드 (쉼표 구분) |
| `--balance` | - | 10,000,000 | 초기 자금 (원) |
| `--timeframe` | - | 전략 meta | 타임프레임 |

백테스트는 별도 프로세스에서 실행되어 운영 중인 시스템에 영향을 주지 않습니다. 미래 데이터 참조가 구조적으로 차단되어 있어, 라이브 환경과 동일한 조건으로 시뮬레이션됩니다.

### 성과 지표

백테스트가 완료되면 다음 지표가 산출됩니다.

| 지표 | 설명 |
|------|------|
| 총 수익률 | 전체 기간 수익률 (%) |
| 연환산 수익률 | 252 거래일 기준 연환산 (%) |
| Sharpe Ratio | 위험 대비 수익 (일간 수익률 기준) |
| 최대 낙폭 (MDD) | 고점 대비 최대 하락폭 (%) |
| MDD 지속 기간 | 최대 낙폭이 지속된 일수 |
| 총 거래 횟수 | 매도 기준 |
| 승률 | 수익 거래 / 전체 거래 (%) |
| Profit Factor | 총 수익 / 총 손실 |
| 평균 수익·손실 | 거래당 평균 금액 (원) |
| 총 수수료 | 시뮬레이션 중 발생한 수수료 합계 (원) |

### 이력 조회

```bash
ante backtest history my_strategy --limit 10
```

이전 백테스트 결과를 조회합니다. 파라미터를 바꿔가며 반복 실행한 뒤 결과를 비교할 수 있습니다.

## 예제 전략

### 기본 전략 — 자체 로직으로 매매

전략이 시장 데이터를 직접 분석하고 매매 시그널을 생성합니다.

```python
from ante.strategy.base import Strategy, StrategyMeta, Signal


class MomentumBreakout(Strategy):
    meta = StrategyMeta(
        name="momentum_breakout",
        version="1.0.0",
        description="전일 고가 돌파 시 매수, RSI 과매수 시 매도",
        symbols=["005930"],
        timeframe="1d",
    )

    async def on_step(self, context: dict) -> list[Signal]:
        ohlcv = await self.ctx.get_ohlcv("005930", limit=20)
        rsi = await self.ctx.get_indicator("005930", "rsi", {"timeperiod": 14})
        positions = self.ctx.get_positions()

        current_close = ohlcv.iloc[-1]["close"]
        yesterday_high = ohlcv.iloc[-2]["high"]

        # 전일 고가 돌파 → 매수
        if current_close > yesterday_high and "005930" not in positions:
            return [Signal(
                symbol="005930",
                side="buy",
                quantity=10,
                order_type="market",
                reason=f"전일 고가({yesterday_high}) 돌파",
            )]

        # RSI 70 이상 → 매도
        if "005930" in positions and rsi["rsi"][-1] > 70:
            qty = positions["005930"]["quantity"]
            return [Signal(
                symbol="005930",
                side="sell",
                quantity=qty,
                order_type="market",
                reason=f"RSI {rsi['rsi'][-1]:.1f} 과매수",
            )]

        return []

    def get_rules(self) -> dict:
        return {
            "max_position_size": 1_000_000,
            "max_loss_per_trade": 500_000,
        }

    def get_params(self) -> dict:
        return {"rsi_period": 14, "rsi_threshold": 70}

    def get_param_schema(self) -> dict:
        return {
            "rsi_period": "RSI 계산 기간",
            "rsi_threshold": "매도 트리거 RSI 값",
        }
```

### 외부 시그널 중계 전략 — AI 에이전트 연동

전략 자체는 판단하지 않고, 외부 AI 에이전트가 보낸 시그널을 그대로 주문으로 전환합니다.

```python
from ante.strategy.base import Strategy, StrategyMeta, Signal


class AgentRelay(Strategy):
    meta = StrategyMeta(
        name="agent_relay",
        version="1.0.0",
        description="외부 에이전트 시그널을 주문으로 중계",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []  # 자체 판단 없음

    async def on_data(self, data: dict) -> list[Signal]:
        return [Signal(
            symbol=data["symbol"],
            side=data["side"],
            quantity=data["quantity"],
            order_type=data.get("order_type", "market"),
            reason=data.get("reason", "external_signal"),
        )]
```

이 전략을 사용하면 AI 에이전트가 시그널 채널(`ante signal connect`)을 통해 직접 매매 지시를 내릴 수 있습니다.

#### 시나리오: AI 에이전트가 뉴스를 분석해 매매하기

리서치 에이전트가 뉴스와 공시를 실시간으로 분석하고, 투자 판단이 서면 Ante에 시그널을 보내 매매를 실행하는 시나리오입니다.

**준비: 전략 등록 → 봇 생성**

```bash
# 1. 중계 전략 등록
ante strategy submit strategies/agent_relay.py

# 2. 모의투자 봇 생성 (시그널 키 자동 발급)
ante bot create \
  --id news-trader-01 \
  --name "뉴스 트레이더" \
  --strategy agent_relay_v1.0.0 \
  --type paper \
  --interval 60

# 3. 시그널 키 확인
ante bot signal-key news-trader-01
# sk_a1b2c3d4e5f6...
```

**에이전트 동작: 뉴스 분석 → 시그널 전송**

에이전트는 별도 프로세스에서 실행되며, 시그널 채널에 접속하여 Ante와 양방향 통신합니다.

```bash
# 에이전트가 시그널 채널에 연결 (stdin/stdout JSON Lines)
ante signal connect --key sk_a1b2c3d4e5f6...
```

연결이 수립되면 에이전트는 다음과 같은 흐름으로 동작합니다.

```
에이전트                              Ante
  │                                    │
  │  ── 현재 보유 포지션 조회 ──────→  │
  │  {"type":"query",                  │
  │   "method":"positions"}            │
  │                                    │
  │  ←── 포지션 응답 ──────────────   │
  │  {"type":"result",                 │
  │   "method":"positions",            │
  │   "data":{"005930":{...}}}         │
  │                                    │
  │  (뉴스 분석: "삼성전자 반도체       │
  │   수주 역대 최대" → 매수 판단)     │
  │                                    │
  │  ── 매수 시그널 전송 ──────────→  │
  │  {"type":"signal",                 │
  │   "symbol":"005930",               │
  │   "side":"buy",                    │
  │   "quantity":50,                   │
  │   "reason":"반도체 수주 호재"}      │
  │                                    │
  │  ←── 시그널 접수 확인 ─────────   │
  │  {"type":"ack",                    │
  │   "signal_id":"sig-abc123"}        │
  │                                    │
  │  ←── 체결 통보 ────────────────   │
  │  {"type":"fill",                   │
  │   "order_id":"ORD-001",            │
  │   "symbol":"005930",               │
  │   "side":"buy",                    │
  │   "quantity":50,                   │
  │   "price":58200,                   │
  │   "commission":873}                │
  │                                    │
  │  (다음 뉴스 대기...)               │
```

에이전트가 사용할 수 있는 메시지 타입을 정리하면 다음과 같습니다.

**에이전트 → Ante:**

| 타입 | 용도 | 예시 |
|------|------|------|
| `signal` | 매수/매도 지시 | `{"type":"signal", "symbol":"005930", "side":"buy", "quantity":10}` |
| `query` | 데이터 조회 | `{"type":"query", "method":"positions"}` |
| `ping` | 연결 상태 확인 | `{"type":"ping"}` |

조회 가능한 `query` method: `positions`, `balance`, `open_orders`, `current_price`, `ohlcv`

**Ante → 에이전트:**

| 타입 | 용도 |
|------|------|
| `ack` | 시그널 접수 확인 |
| `fill` | 주문 체결 통보 (종목, 수량, 체결가, 수수료) |
| `order_update` | 주문 상태 변경 (접수, 거부, 취소, 실패) |
| `result` | query 응답 |
| `pong` | ping 응답 |

이 구조에서 에이전트의 역할은 **시장 분석과 판단**에 집중하고, 주문 실행·포지션 관리·리스크 통제는 Ante 시스템이 담당합니다. 에이전트가 보낸 시그널도 Rule Engine을 거치므로, 전역 손실 한도나 포지션 크기 제한에 위배되면 주문이 차단됩니다.

## 전략 제출 및 승인

### 1단계: 검증

전략 파일의 안전성을 정적 분석으로 검증합니다. 코드를 실행하지 않고 AST를 분석합니다.

```bash
ante strategy validate strategies/my_strategy.py
```

**검증 항목:**

- `Strategy` 클래스를 상속하고 있는가
- `meta` 클래스 변수와 `on_step()` 메서드가 있는가
- 금지된 모듈을 import하지 않는가 (`os`, `sys`, `subprocess`, `socket`, `requests` 등)
- `eval()`, `exec()` 같은 위험한 함수를 호출하지 않는가
- import·클래스·함수 정의 외의 최상위 실행 코드가 없는가

금지 모듈 목록은 시스템 접근(`os`, `sys`, `subprocess`), 네트워크(`socket`, `requests`, `aiohttp`), DB 직접 접근(`sqlite3`, `sqlalchemy`) 등을 포함합니다. 반면 `numpy`, `polars`, `pandas-ta` 같은 데이터 분석 라이브러리는 자유롭게 사용할 수 있습니다.

### 2단계: 제출

검증을 통과한 전략을 Registry에 등록합니다.

```bash
ante strategy submit strategies/my_strategy.py
```

제출 시 검증이 자동으로 다시 실행되고, 이어서 실제 import 테스트까지 수행합니다. 모두 통과하면 `{name}_v{version}` 형식의 ID로 등록됩니다.

```
✅ 전략 등록 완료
  전략 ID: momentum_breakout_v1.0.0
  이름: momentum_breakout
  버전: 1.0.0
```

동일 이름의 다른 버전을 등록할 수 있어, 여러 버전이 공존할 수 있습니다.

### 3단계: 봇에 배정

등록된 전략을 봇에 연결하여 실행합니다.

```bash
# 모의투자 봇으로 먼저 검증
ante bot create \
  --id bot-momentum-01 \
  --name "모멘텀 봇 1호" \
  --strategy momentum_breakout_v1.0.0 \
  --type paper \
  --interval 60
```

| 옵션 | 설명 |
|------|------|
| `--strategy` | 등록된 전략 ID |
| `--type paper` | 모의투자 (실제 주문 없음) |
| `--type live` | 실투자 (실제 주문 발생) |
| `--interval` | `on_step()` 호출 주기 (초, 10~3600) |

### 4단계: 실투자 전환

모의투자로 충분히 검증한 뒤, 실투자 봇을 만들어 투입합니다. 실투자 전환은 결재(Approval)를 거칩니다.

```bash
# 에이전트가 결재 요청
ante approval request \
  --type strategy_adopt \
  --title "momentum_breakout v1.0.0 실투자 채택" \
  --body "paper 봇 30일 운용 결과: 수익률 +12.3%, MDD -3.1%"

# 사용자가 승인
ante approval approve <approval_id>
```

`strategy_adopt` 결재는 자동 승인이 불가능하며, 반드시 사용자가 직접 판단해야 합니다.

### 전략 상태

| 상태 | 설명 |
|------|------|
| `REGISTERED` | 검증 통과, Registry에 등록됨 |
| `ACTIVE` | 봇에 배정되어 운영 중 |
| `INACTIVE` | 비활성화 |
| `ARCHIVED` | 보관 (더 이상 사용 안 함) |

```bash
# 전략 목록 조회
ante strategy list --status active

# 전략 상세 정보
ante strategy info momentum_breakout

# 전략 성과 조회 (모든 봇 합산)
ante strategy performance momentum_breakout
```
