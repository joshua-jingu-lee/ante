# Backtest Engine 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [backtest.md](backtest.md)

# 설계 결정

### Subprocess 격리 (D-004)

> 소스: [`src/ante/backtest/runner.py`](../../../src/ante/backtest/runner.py)

백테스트는 `python -m ante.backtest.runner` 형태로 subprocess에서 실행된다.
설정은 stdin으로 JSON을 전달하고, 결과는 stdout으로 JSON을 반환한다.

**실행 흐름**:
```
메인 프로세스 (BacktestService)
  └→ subprocess: python -m ante.backtest.runner
       ├→ stdin: JSON config
       ├→ 1. StrategyLoader.load() — 파일에서 전략 클래스 직접 로드
       ├→ 2. BacktestDataProvider 구성 — Parquet에서 과거 데이터 준비
       ├→ 3. BacktestExecutor.run() — 시뮬레이션 실행
       ├→ 4. 결과를 JSON 파일로 저장
       └→ stdout: JSON result
```

**격리 근거** (D-004):
- subprocess 분리로 메모리 독립 — 백테스트가 수 GB 메모리 사용해도 라이브 봇에 무영향
- CPU 격리 — N100의 4코어 중 백테스트가 1코어 점유해도 라이브 봇은 다른 코어 사용
- 크래시 격리 — 백테스트 중 OOM/segfault 발생해도 메인 프로세스 안전

### BacktestDataProvider — Parquet 기반 과거 데이터

> 소스: [`src/ante/backtest/data_provider.py`](../../../src/ante/backtest/data_provider.py)

백테스트용 DataProvider. StrategyContext에 주입되어 전략이 라이브와 동일한 인터페이스로 데이터를 조회할 수 있게 한다.

| 메서드 | 설명 |
|--------|------|
| `load(symbol, timeframe) → int` | 데이터를 캐시에 로드. 로드된 행 수 반환 |
| `get_ohlcv(symbol, timeframe, limit) → DataFrame` | 과거 OHLCV 반환. **현재 시점까지만 노출** (미래 참조 방지) |
| `get_current_price(symbol) → float` | 현재 시점의 종가 반환 |
| `get_indicator(symbol, indicator, params) → DataFrame` | 기술 지표 계산 (현재는 원본 OHLCV 데이터 반환) |
| `advance() → bool` | 시뮬레이션을 1스텝 전진. `False`면 데이터 끝 |
| `get_current_timestamp() → datetime \| None` | 현재 시뮬레이션 시각 |
| `get_total_steps() → int` | 전체 시뮬레이션 스텝 수 |
| `reset() → None` | 인덱스 초기화 |
| `loaded_datasets → list[DatasetInfo]` | 로드된 데이터셋 이력 (속성) |

`load()` 호출 시마다 `DatasetInfo`를 내부 `_loaded_datasets` 리스트에 추가한다. 실행 완료 후 `BacktestService`가 `result.datasets = data_provider.loaded_datasets`로 결과에 주입한다.

> **ParquetStore.resolve_path()**: 기존 `_resolve_path()`를 public `resolve_path()`로 노출하여 DataProvider에서 데이터 디렉토리 경로를 조회할 수 있게 한다.

**미래 참조 방지 설계**:
- 전체 기간 데이터를 초기에 캐시하되, `_current_idx`로 현재 시점까지만 슬라이싱하여 노출
- `advance()` 호출 시 인덱스가 1씩 증가, 전략은 항상 "현재까지의 데이터"만 볼 수 있음
- 라이브 DataProvider와 동일한 인터페이스 → 전략 코드 변경 없이 라이브/백테스트 전환 가능

**커서 계약 (cursor contract)**:
- **초기 커서는 첫 row 이전(`_current_idx = -1`)에 위치한다.** `reset()`도 `-1`로 되돌린다.
- **첫 `advance()`가 커서를 row 0으로 전진**시킨다. 따라서 백테스트 루프(`while advance():`)는 row 0부터 row N-1까지 전 행을 처리하며, `on_step()` 호출 횟수 == `equity_curve` 길이 == `get_total_steps()` == N으로 일관된다.
- **pre-advance 상태(`_current_idx = -1`, 첫 `advance()` 이전)**에서의 조회 계약:
  - `get_ohlcv()` → empty DataFrame (`head(0)`)
  - `get_current_timestamp()` → `None` (음수 인덱스로 마지막 행을 반환하지 않도록 명시적 가드)
  - `get_current_price()` → empty OHLCV에서 `BacktestDataError` (현재가 unavailable)
- **implicit warm-up 없음**: 시스템은 row 0을 건너뛰지 않으며 별도의 warm-up 구간을 두지 않는다. row 0에서 lookback이 필요한 전략은 그 시점에 history가 1개 봉뿐이므로, 충분한 history 확보는 전략의 책임이다(정책상 의도된 노출).

### BacktestExecutor — 시뮬레이션 실행

> 소스: [`src/ante/backtest/executor.py`](../../../src/ante/backtest/executor.py)

가상 체결 시뮬레이션 엔진. 슬리피지, 수수료를 포함하여 현실적인 시뮬레이션을 제공한다.

`run(progress_callback=None)` 메서드는 선택적 진행률 콜백을 받는다. 이 콜백은
in-process `BacktestService.run()` 을 임베드 호출하는 경우(프로그래매틱/IPC
임베드)에만 진행률을 스트리밍한다. `ante backtest run` CLI 는 D-004 격리 계약대로
`run_subprocess()`(`python -m ante.backtest.runner`) 경로를 사용하며, 자식
프로세스 stdout 은 단일 결과 라인이라 진행률 스트리밍을 지원하지 않는다(progress
bar 없음 — 격리 우선, #2001).

**시뮬레이션 루프**:
```
strategy.on_start()
while data_provider.advance():
  → context 구성 (timestamp, portfolio, balance)
  → signals = strategy.on_step(context)
  → 각 signal에 대해 가상 체결 (_execute_signal)
  → equity curve 기록
strategy.on_stop()
→ BacktestResult 생성
```

**가상 체결 로직**:
- 매수: `exec_price = price × (1 + slippage_rate)`, `commission = exec_price × qty × buy_commission_rate`, 잔고에서 `exec_price × quantity + commission` 차감
- 매도: `exec_price = price × (1 - slippage_rate)`, `commission = exec_price × qty × sell_commission_rate`, 잔고에 `exec_price × quantity - commission` 가산
- 잔고 부족 시 매수 스킵, 보유 수량 초과 매도 시 보유분만 매도

### BacktestResult — 결과 데이터

> 소스: [`src/ante/backtest/result.py`](../../../src/ante/backtest/result.py)

**BacktestResult 핵심 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `strategy_name` | `str` | 전략 이름 |
| `strategy_version` | `str` | 전략 버전 |
| `start_date` | `str` | 백테스트 시작일 |
| `end_date` | `str` | 백테스트 종료일 |
| `initial_balance` | `float` | 초기 자금 |
| `final_balance` | `float` | 최종 자산 가치 |
| `total_return` | `float` | 총 수익률 (%) |
| `trades` | `list[BacktestTrade]` | 거래 기록 목록 |
| `equity_curve` | `list[dict]` | 자산 곡선 (timestamp, equity, balance) |
| `metrics` | `dict` | 성과 지표 (아래 metrics.py 참조) |
| `config` | `BacktestConfig` | 실행 설정 (기본값: 빈 BacktestConfig) |
| `datasets` | `list[DatasetInfo]` | 로드된 데이터셋 정보 (기본값: `[]`) |

#### BacktestConfig — 실행 설정

> **파일 위치**: `src/ante/backtest/config.py` (result.py → executor.py 순환 의존 방지를 위해 별도 모듈)

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `strategy_path` | `str` | `""` | 전략 파일 경로 |
| `symbols` | `list[str]` | `[]` | 대상 종목 코드 목록 |
| `timeframe` | `str` | `"1d"` | 봉 주기 |
| `start_date` | `str` | `""` | 백테스트 시작일 |
| `end_date` | `str` | `""` | 백테스트 종료일 |
| `initial_balance` | `float` | `10_000_000` | 초기 자금 |
| `buy_commission_rate` | `float` | `0.00015` | 매수 수수료율 (Account 모듈 기준, KRX: 0.00015) |
| `sell_commission_rate` | `float` | `0.00195` | 매도 수수료율 (Account 모듈 기준, KRX: 0.00195) |
| `slippage_rate` | `float` | `0.001` | 슬리피지율 |
| `data_paths` | `list[str]` | `[resolved data.path]` | Parquet 저장 경로 목록. 기본값은 Config resolver가 정규화한 canonical data root |

#### DatasetInfo — 로드된 데이터셋 정보

> **파일 위치**: `src/ante/backtest/config.py`

| 필드 | 타입 | 설명 |
|------|------|------|
| `symbol` | `str` | 종목 코드 (예: `"005930"`) |
| `timeframe` | `str` | 봉 주기 (예: `"1d"`) |
| `row_count` | `int` | 로드된 행 수 |
| `start_date` | `str` | 데이터 시작일 |
| `end_date` | `str` | 데이터 종료일 |
| `data_dir` | `str` | Parquet 디렉토리 경로 (예: `"{data.path}/ohlcv/1d/KRX/005930"`) |
| `file_count` | `int` | 해당 디렉토리의 parquet 파일 수 |

> **참고**: ParquetStore는 종목당 월별 파티션 파일(`YYYY-MM.parquet`)을 사용한다.
> `load("005930", "1d")` 호출 시 `{data.path}/ohlcv/1d/KRX/005930/*.parquet` 전체를 concat하여 로드.
> `data_dir`은 이 디렉토리 경로, `file_count`는 읽힌 파일 수를 기록한다.

#### to_dict() 직렬화

`to_dict()`는 기존 필드에 더해 `config`와 `datasets`를 직렬화한다:

```python
def to_dict(self) -> dict:
    return {
        # ... 기존 필드 ...
        "config": {
            "strategy_path": self.config.strategy_path,
            "symbols": self.config.symbols,
            "timeframe": self.config.timeframe,
            "start_date": self.config.start_date,
            "end_date": self.config.end_date,
            "initial_balance": self.config.initial_balance,
            "buy_commission_rate": self.config.buy_commission_rate,
            "sell_commission_rate": self.config.sell_commission_rate,
            "slippage_rate": self.config.slippage_rate,
            "data_paths": self.config.data_paths,
        },
        "datasets": [
            {
                "symbol": d.symbol,
                "timeframe": d.timeframe,
                "row_count": d.row_count,
                "start_date": d.start_date,
                "end_date": d.end_date,
                "data_dir": d.data_dir,
                "file_count": d.file_count,
            }
            for d in self.datasets
        ],
    }
```

**BacktestTrade 핵심 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `timestamp` | `datetime` | 체결 시각 |
| `symbol` | `str` | 종목 코드 |
| `side` | `str` | `"buy"` / `"sell"` |
| `quantity` | `float` | 체결 수량 |
| `price` | `float` | 체결 가격 (슬리피지 적용 후) |
| `commission` | `float` | 수수료 |
| `slippage` | `float` | 슬리피지 금액 |
| `reason` | `str` | Signal의 reason (기본값: `""`) |
| `exchange` | `str` | 거래소 (기본값: `"KRX"`) |

### 성과 지표 계산 (metrics.py)

> 소스: [`src/ante/backtest/metrics.py`](../../../src/ante/backtest/metrics.py)

`calculate_metrics()` 함수가 trades + equity_curve로부터 13개 성과 지표를 산출한다.

**산출 지표**:

| 지표 | 키 | 산출 방식 |
|------|------|-----------|
| 총 수익률 | `total_return` | `(final - initial) / initial × 100` |
| 연환산 수익률 | `annual_return` | `((1+r)^(252/days) - 1) × 100` |
| Sharpe Ratio | `sharpe_ratio` | 일간 수익률 기준, `√252` 연환산, 무위험 이자율 0 |
| 최대 낙폭 (MDD) | `max_drawdown` | peak-to-trough 비율 (%) |
| MDD 지속 기간 | `max_drawdown_duration` | drawdown 지속 일수 |
| 총 거래 횟수 | `total_trades` | 매도 거래 기준 |
| 승리 거래 | `winning_trades` | PnL > 0 |
| 패배 거래 | `losing_trades` | PnL < 0 |
| 승률 | `win_rate` | `winning / total × 100` |
| Profit Factor | `profit_factor` | `총 수익 / 총 손실` (손실 0이면 ∞) |
| 평균 수익 | `avg_profit` | 승리 거래 평균 PnL |
| 평균 손실 | `avg_loss` | 패배 거래 평균 PnL |
| 총 수수료 | `total_commission` | 전 거래 수수료 합산 |

**거래 PnL 추정** (`_estimate_trade_pnl`): 종목별 FIFO 방식으로 buy 평균 단가를 추적하고, sell 시 `(매도가 - 평균단가) × 수량 - 수수료`로 PnL 계산.

### BacktestService — 메인 프로세스 측 관리

> 소스: [`src/ante/backtest/service.py`](../../../src/ante/backtest/service.py)

메인 프로세스에서 백테스트를 관리하는 서비스. in-process 실행과 subprocess 격리 실행 두 모드를 지원한다.

| 메서드 | 설명 |
|--------|------|
| `run(config, progress_callback=None) → BacktestResult` | 백테스트를 in-process로 실행. 진행률 콜백은 in-process 임베드 호출 한정 (CLI subprocess 경로는 미지원) |
| `run_subprocess(config) → dict` | 백테스트를 subprocess로 격리 실행 (D-004). `ante backtest run` CLI 의 격리 경로. `runner.run_backtest` 가 emit 하는 additive envelope(`to_dict()` superset + 런타임 `result_path`/`strategy_name`/`strategy_version`)를 반환해 `result_path` 를 `backtest_runs` 이력으로 전파한다 (#1998/#2001) |

**설정 필수 키**: `strategy_path`, `start_date`, `end_date`
**선택 키**: `symbols` (list[str]), `timeframe` (기본 `"1d"`), `initial_balance` (기본 10,000,000), `buy_commission_rate` (기본 0.00015), `sell_commission_rate` (기본 0.00195), `slippage_rate` (기본 0.001), `data_paths` (기본 Config resolver의 `data.path`), `data_path` (하위호환, 단수)

`data_paths`/`data_path`는 백테스트 실행 단위의 데이터셋 override이다. 값이 없으면 Ante
인스턴스의 `data.path`를 사용한다. 명시적 override는 백테스트 입력 데이터만 바꾸며
인증 DB나 서버 IPC 경계를 바꾸지 않는다.

**`_validate_config()` → BacktestConfig 통합**:

`_validate_config()`는 required keys 검증과 BacktestConfig 생성을 한 곳에서 수행한다. `run()` 실행 완료 후 `result.config = validated`, `result.datasets = data_provider.loaded_datasets`로 결과에 실행 설정을 주입한다.

```python
def _validate_config(self, config: dict[str, Any]) -> BacktestConfig:
    try:
        return BacktestConfig(
            strategy_path=config["strategy_path"],
            start_date=config["start_date"],
            end_date=config["end_date"],
            symbols=config.get("symbols", []),
            timeframe=config.get("timeframe", "1d"),
            initial_balance=config.get("initial_balance", 10_000_000),
            buy_commission_rate=config.get("buy_commission_rate", 0.00015),
            sell_commission_rate=config.get("sell_commission_rate", 0.00195),
            slippage_rate=config.get("slippage_rate", 0.001),
            data_paths=config.get("data_paths", [config.get("data_path", self._data_path)]),  # self._data_path = resolved data.path
        )
    except KeyError as e:
        raise BacktestConfigError(f"Missing required config key: {e}")
```

**유관 모듈 호환성**:

| 모듈 | 영향 | 조치 |
|------|------|------|
| **ReportDraftGenerator** | 자동 호환 — `detail = dict(result_data)` 로 전체 복사하므로 config/datasets 자동 포함 | 수정 불필요 |
| **BacktestRunner** (subprocess) | `run_backtest()` 는 `result.to_dict()` superset envelope(+ 런타임 `result_path`/`strategy_name`/`strategy_version`)를 emit한다. config/datasets 는 to_dict 키로 그대로 포함. `output_path` 파일 아티팩트는 to_dict 그대로 유지 (#2001) | 수정 불필요 |
| **BacktestRunStore** | params_json에 입력 config만 저장 중 | 선택: resolved config 저장으로 개선 가능 |
| **CLI** (`backtest run`) | `run_subprocess()` 의 envelope dict 를 소비 — to_dict 키 유지 + 런타임 `result_path`/`strategy_name`/`strategy_version` 직접 사용. `_save_backtest_run` 은 combined `strategy` 를 split 파싱하지 않는다 (#2001) | 선택: 결과 출력에 config 요약 추가 |
| **to_dict() 소비자** | 기존 필드 불변, 추가 키만 — **backward compatible** | 기존 코드 수정 불필요 |

### BacktestStrategyContext

> 소스: [`src/ante/backtest/context.py`](../../../src/ante/backtest/context.py)

백테스트 모드 전용 StrategyContext. 라이브 StrategyContext와 동일한 인터페이스를 제공하되, BacktestDataProvider와 BacktestExecutor의 포지션/잔고를 주입한다.

| 메서드 | 설명 |
|--------|------|
| `get_ohlcv(symbol, timeframe, limit) → Any` | OHLCV 데이터 조회 (BacktestDataProvider 위임) |
| `get_current_price(symbol) → float` | 현재가 조회 |
| `get_indicator(symbol, indicator, params) → Any` | 기술 지표 데이터 조회 |
| `get_positions() → dict[str, Any]` | 현재 보유 포지션 |
| `get_balance() → dict[str, float]` | 가용 자금 현황 |
| `get_open_orders() → list[dict]` | 미체결 주문 (백테스트에서는 항상 빈 리스트) |
| `cancel_order(order_id, reason) → None` | 주문 취소 (백테스트에서는 무시) |
| `modify_order(order_id, quantity, price, reason) → None` | 주문 정정 (백테스트에서는 무시) |
| `load_file(path) → bytes` | 전략 전용 파일 읽기 (바이너리). 라이브와 동일하게 `strategies/` 하위만 허용하고 절대경로/탈출/symlink escape는 `StrategyFileAccessError`로 거부 (#2083) |
| `load_text(path, encoding="utf-8") → str` | 전략 전용 파일 읽기 (텍스트). `load_file` 위임 후 디코딩 (#2083) |
| `log(message, level) → None` | 전략 로그 출력 |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
