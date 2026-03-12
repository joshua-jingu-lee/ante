# Ante — AI Agent 온보딩 가이드

> 이 문서는 Ante 시스템에서 전략을 개발·검증하는 AI Agent를 위한 가이드이다.

## 1. 개요

**Ante**는 AI Agent가 주식 매매 전략을 개발·검증하고, 사용자가 그 전략을 운용하는 자동 거래 시스템이다.

### Agent의 역할

```
데이터 탐색 → 전략 작성 → 정적 검증 → 백테스트 → 리포트 제출
```

Agent는 여기까지만 담당한다. 봇 생성, 자금 할당, 실전 운용은 **사용자 영역**이다.

### 시스템 구조

- 단일 asyncio 프로세스 (이벤트 드리븐)
- CLI 인터페이스(`ante` 커맨드)를 통해 시스템과 상호작용
- 모든 CLI 출력은 `--format json` 옵션으로 구조화 가능

## 2. 빠른 시작

```bash
# 1. 보유 데이터 확인
ante data list --format json

# 2. 전략 작성
cp strategies/_template.py strategies/my_strategy.py
# ... 전략 로직 구현 ...

# 3. 정적 검증
ante strategy validate strategies/my_strategy.py --format json

# 4. 백테스트
ante backtest run strategies/my_strategy.py \
  --start 2024-01-01 --end 2026-03-01 \
  --symbols 005930 --balance 10000000 \
  --format json

# 5. 리포트 제출
ante report submit report.json --format json
```

## 3. 전략 작성 가이드

### 3.1 필수 구조

```python
from ante.strategy.base import Signal, Strategy, StrategyMeta


class MyStrategy(Strategy):
    meta = StrategyMeta(
        name="my_strategy",           # 고유 이름 (영문 snake_case)
        version="1.0",                # 시맨틱 버전
        description="전략 한 줄 설명",
        author="agent",               # 기본값
        symbols=["005930", "000660"], # 대상 종목 (None이면 봇 설정 사용)
        timeframe="1d",               # 기본 타임프레임
    )

    async def on_step(self, context: dict) -> list[Signal]:
        """매 주기마다 호출. 매매 시그널 리스트를 반환한다."""
        signals = []

        # context 활용
        # context["timestamp"]  — 현재 시각 (datetime, UTC)
        # context["portfolio"]  — 현재 보유 포지션 (dict)
        # context["balance"]    — 자금 상태 {"total", "available", "reserved"}

        # StrategyContext API 활용
        # price = await self.ctx.get_current_price("005930")
        # ohlcv = await self.ctx.get_ohlcv("005930", timeframe="1d", limit=20)
        # positions = self.ctx.get_positions()
        # balance = self.ctx.get_balance()

        return signals
```

### 3.2 Signal 객체

```python
Signal(
    symbol="005930",           # 종목코드
    side="buy",                # "buy" | "sell"
    quantity=10.0,             # 수량
    order_type="market",       # "market" | "limit"
    price=None,                # limit 주문 시 가격
    stop_price=None,           # stop 주문 시 가격
    reason="SMA20 골든크로스",  # 매매 사유 (기록용)
)
```

### 3.3 선택적 메서드

```python
class MyStrategy(Strategy):
    meta = StrategyMeta(...)

    def on_start(self) -> None:
        """봇 시작 시 1회 호출. 상태 초기화."""
        self._position_opened = False

    def on_stop(self) -> None:
        """봇 중지 시 1회 호출. 정리 작업."""
        pass

    async def on_fill(self, fill: dict) -> list[Signal]:
        """주문 체결 통보. 후속 주문 발행 가능.

        fill = {
            "order_id": str,
            "symbol": str,
            "side": "buy" | "sell",
            "quantity": float,
            "price": float,
            "timestamp": datetime,
        }
        """
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        """외부 시그널 수신 시 호출."""
        return []

    def get_rules(self) -> dict:
        """전략별 거래 룰 반환."""
        return {
            "max_position_pct": 0.1,  # 종목당 최대 비중 10%
        }

    def get_params(self) -> dict:
        """백테스트 최적화용 파라미터."""
        return {
            "sma_short": 5,
            "sma_long": 20,
        }
```

### 3.4 StrategyContext API

`self.ctx`를 통해 접근 가능한 API:

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `await ctx.get_ohlcv(symbol, timeframe, limit)` | DataFrame/list | OHLCV 데이터 |
| `await ctx.get_current_price(symbol)` | float | 현재가 |
| `await ctx.get_indicator(symbol, indicator, params)` | Any | 기술 지표 |
| `ctx.get_positions()` | dict | 보유 포지션 |
| `ctx.get_balance()` | dict | 자금 현황 |
| `ctx.get_open_orders()` | list[dict] | 미체결 주문 |
| `ctx.cancel_order(order_id, reason)` | None | 주문 취소 |
| `ctx.modify_order(order_id, ...)` | None | 주문 정정 |
| `ctx.log(message, level)` | None | 전략 로그 |

### 3.5 금지 사항

**금지된 임포트** (검증 시 자동 차단):

```python
# 시스템 접근
import os, sys, subprocess, shutil, pathlib

# 네트워크
import socket, http, urllib, requests, aiohttp, httpx

# DB 직접 접근
import sqlite3, sqlalchemy

# 코드 실행/로딩
import importlib, ctypes, pickle
```

**위험 패턴** (경고 발생):

```python
eval(...)     # 동적 코드 실행
exec(...)     # 동적 코드 실행
open(...)     # 파일 직접 접근
```

**허용되는 라이브러리**: numpy, polars, ta-lib 등 순수 계산 라이브러리

### 3.6 전략 파일 위치

```
strategies/
├── _template.py      # 뼈대 템플릿 (복사하여 사용)
├── _examples/        # 참조용 예제 전략
└── my_strategy.py    # Agent가 생성하는 전략 파일
```

## 4. CLI 명령어 참고서

모든 커맨드에 `--format json` 추가 가능.

### 4.1 전략 검증

```bash
ante strategy validate <파일경로>
```

검증 항목:
1. Python 문법 오류
2. Strategy 클래스 상속 (정확히 1개)
3. `meta` 클래스 변수 존재
4. `on_step()` 메서드 존재
5. 금지 모듈 임포트 차단
6. 위험 패턴 경고

### 4.2 데이터 탐색

```bash
# 보유 데이터셋 목록
ante data list --format json

# OHLCV 스키마
ante data schema --format json

# 저장 용량
ante data storage --format json

# 외부 CSV 데이터 주입
ante data inject <csv경로> --symbol 005930 --timeframe 1d
```

**데이터 목록 응답 예시 (JSON):**
```json
{
  "datasets": [
    {
      "symbol": "005930",
      "timeframe": "1d",
      "start": "2020-01-02",
      "end": "2026-03-12",
      "rows": 1530
    }
  ]
}
```

**OHLCV 스키마:**
```json
{
  "timestamp": "Datetime(time_unit='ns', time_zone=None)",
  "open": "Float64",
  "high": "Float64",
  "low": "Float64",
  "close": "Float64",
  "volume": "Float64"
}
```

### 4.3 백테스트

```bash
ante backtest run <전략파일> \
  --start 2024-01-01 \
  --end 2026-03-01 \
  --symbols 005930,000660 \
  --balance 10000000 \
  --timeframe 1d \
  --format json
```

**결과 예시 (JSON):**
```json
{
  "strategy_name": "momentum_breakout",
  "strategy_version": "1.0",
  "start_date": "2024-01-01",
  "end_date": "2026-03-01",
  "initial_balance": 10000000,
  "final_balance": 11530000,
  "total_return": 15.3,
  "trades": [
    {
      "timestamp": "2024-01-15",
      "symbol": "005930",
      "side": "buy",
      "quantity": 100,
      "price": 75000.0,
      "commission": 11.25
    }
  ],
  "equity_curve": [...],
  "metrics": {
    "total_trades": 42,
    "buy_trades": 21,
    "sell_trades": 21,
    "total_commission": 1530
  }
}
```

### 4.4 리포트 제출

```bash
# 제출 스키마 확인
ante report schema --format json

# 리포트 제출
ante report submit <json파일> --format json

# 리포트 목록 조회
ante report list [--status submitted|adopted|rejected]

# 리포트 상세 조회
ante report info <report_id>
```

**리포트 JSON 구조:**
```json
{
  "strategy_name": "momentum_breakout",
  "strategy_version": "1.0",
  "strategy_path": "strategies/momentum_breakout.py",
  "backtest_period": "2024-01 ~ 2026-03",
  "total_return_pct": 15.3,
  "total_trades": 42,
  "sharpe_ratio": 1.8,
  "max_drawdown_pct": 5.2,
  "win_rate": 0.62,
  "summary": "20일 이동평균 돌파 기반 모멘텀 전략",
  "rationale": "한국 대형주의 추세 추종 특성을 활용",
  "risks": "횡보장에서 잦은 손절 가능",
  "recommendations": "변동성 필터 추가 검토"
}
```

## 5. 워크플로우 예시

### 시나리오: 이동평균 돌파 전략 개발

```bash
# 1단계: 데이터 확인
ante data list --format json
# → 005930 (1d, 2020~2026, 1530건) 확인

# 2단계: 전략 작성
cat > strategies/sma_crossover.py << 'EOF'
from ante.strategy.base import Signal, Strategy, StrategyMeta


class SMACrossover(Strategy):
    meta = StrategyMeta(
        name="sma_crossover",
        version="1.0",
        description="SMA 5/20 골든크로스/데드크로스 전략",
        symbols=["005930"],
        timeframe="1d",
    )

    def on_start(self):
        self._prev_short = None
        self._prev_long = None

    async def on_step(self, context):
        ohlcv = await self.ctx.get_ohlcv("005930", limit=25)
        if len(ohlcv) < 20:
            return []

        closes = [row["close"] for row in ohlcv]
        short_ma = sum(closes[-5:]) / 5
        long_ma = sum(closes[-20:]) / 20

        signals = []
        if self._prev_short and self._prev_long:
            positions = self.ctx.get_positions()
            has_position = "005930" in positions

            # 골든크로스 → 매수
            if self._prev_short <= self._prev_long and short_ma > long_ma:
                if not has_position:
                    price = await self.ctx.get_current_price("005930")
                    balance = self.ctx.get_balance()
                    qty = int(balance["available"] * 0.9 / price)
                    if qty > 0:
                        signals.append(Signal(
                            symbol="005930", side="buy",
                            quantity=float(qty), order_type="market",
                            reason="SMA 5/20 골든크로스",
                        ))

            # 데드크로스 → 매도
            elif self._prev_short >= self._prev_long and short_ma < long_ma:
                if has_position:
                    qty = positions["005930"]["quantity"]
                    signals.append(Signal(
                        symbol="005930", side="sell",
                        quantity=qty, order_type="market",
                        reason="SMA 5/20 데드크로스",
                    ))

        self._prev_short = short_ma
        self._prev_long = long_ma
        return signals
EOF

# 3단계: 검증
ante strategy validate strategies/sma_crossover.py --format json

# 4단계: 백테스트
ante backtest run strategies/sma_crossover.py \
  --start 2024-01-01 --end 2026-03-01 \
  --symbols 005930 --balance 10000000 \
  --format json > backtest_result.json

# 5단계: 리포트 작성 및 제출
ante report schema --format json > report.json
# ... 백테스트 결과로 report.json 작성 ...
ante report submit report.json --format json
```

## 6. 자주 묻는 질문

**Q: 검증에서 "forbidden import" 오류가 나와요.**
A: `os`, `requests` 등 시스템/네트워크 모듈은 금지입니다. 데이터는 `self.ctx` API를 통해서만 접근하세요.

**Q: 백테스트에서 "No data found" 오류가 나와요.**
A: `ante data list`로 보유 데이터를 확인하세요. 해당 종목/타임프레임의 데이터가 있어야 합니다.

**Q: 전략에서 외부 API를 호출할 수 있나요?**
A: 불가합니다. 보안상 네트워크 접근이 차단됩니다. 필요한 데이터는 시스템 데이터 파이프라인을 통해 사전에 적재해야 합니다.

**Q: 여러 종목을 동시에 거래할 수 있나요?**
A: 가능합니다. `meta.symbols`에 종목 목록을 지정하고, `on_step`에서 각 종목에 대한 Signal을 반환하면 됩니다.

**Q: 리포트가 채택되면 자동으로 봇이 생성되나요?**
A: 아닙니다. 리포트 채택 후 봇 생성과 자금 할당은 사용자가 수동으로 진행합니다.

**Q: 실전 운용 중 전략을 수정할 수 있나요?**
A: 새 버전(`version` 변경)의 전략을 제출하세요. 기존 봇은 영향받지 않으며, 사용자가 새 전략으로 봇을 교체할 수 있습니다.
