# Strategy 모듈 세부 설계 - 설계 결정 - 전략 인터페이스 (Strategy ABC)

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 전략 인터페이스 (Strategy ABC)

구현: `src/ante/strategy/base.py` 참조

#### StrategyMeta 핵심 필드

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `name` | `str` | (필수) | 전략 고유 이름 (예: `"momentum_breakout"`) |
| `version` | `str` | (필수) | 시맨틱 버전 (예: `"1.0.0"`) |
| `description` | `str` | (필수) | 전략 설명 (한 줄) |
| `author_name` | `str` | `"agent"` | 작성자 표시 이름 (예: `"전략 리서치 1호"`) |
| `author_id` | `str` | `"agent"` | 작성자 ID (예: `"strategy-dev-01"`) |
| `symbols` | `list[str] \| None` | `None` | 대상 종목 (`None`이면 봇 설정에서 지정) |
| `timeframe` | `str` | `"1d"` | 기본 타임프레임 (`1m`, `5m`, `15m`, `1h`, `1d` 등) |
| `exchange` | `str` | `"KRX"` | 대상 거래소. 유효 값: `"KRX"`, `"NYSE"`, `"NASDAQ"`, `"AMEX"`, `"TEST"`, `"*"`. `"*"`는 시장 무관(범용) 전략 |
| `accepts_external_signals` | `bool` | `False` | 외부 시그널 수신 가능 여부. `True`인 전략만 시그널 채널 연결 허용 |

#### exchange 필드 의미

| exchange 값 | 의미 | 배정 가능 계좌 |
|------------|------|--------------|
| `"KRX"` | 한국 주식 전용 | exchange=KRX인 계좌만 |
| `"NYSE"` | NYSE 전용 | exchange=NYSE인 계좌만 |
| `"NASDAQ"` | NASDAQ 전용 | exchange=NASDAQ인 계좌만 |
| `"AMEX"` | AMEX 전용 | exchange=AMEX인 계좌만 |
| `"TEST"` | 테스트 전용 | exchange=TEST인 계좌만 |
| `"*"` | 시장 무관 | 모든 계좌 |

`exchange="*"`는 OHLCV 데이터만 있으면 어떤 시장에서든 동작하는 범용 전략에 사용한다. 예: 이동평균 크로스 전략, RSI 기반 전략 등.

봇 배정 시 전략의 `exchange`와 계좌의 `exchange` 호환성을 검증한다. 호환되지 않으면 `IncompatibleExchangeError`를 발생시킨다.

**호환성 검증 매트릭스**:

| 전략 exchange | 계좌 exchange | 결과 |
|--------------|--------------|------|
| `"KRX"` | `KRX` | 허용 |
| `"KRX"` | `NYSE` | **거부** — IncompatibleExchangeError |
| `"NYSE"` | `NYSE` | 허용 |
| `"NYSE"` | `KRX` | **거부** |
| `"*"` | `KRX` | 허용 |
| `"*"` | `NYSE` | 허용 |
| `"*"` | `TEST` | 허용 |

#### Strategy ABC 메서드 시그니처

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `__init__` | `ctx: Any` | `None` | 생성자. Bot이 StrategyContext 주입. 타입은 `Any`로 선언하여 순환 참조 방지 |
| `on_start` | — | `None` | 봇 시작 시 1회 호출. 초기화 로직 (선택) |
| `on_stop` | — | `None` | 봇 중지 시 1회 호출. 정리 로직 (선택) |
| `async on_step` **(필수)** | `context: dict[str, Any]` | `list[Signal]` | 주기적 호출. 매매 시그널 반환. context에 timestamp, portfolio, balance 등 포함 |
| `async on_fill` | `fill: dict[str, Any]` | `list[Signal]` | 주문 체결 통보. 후속 주문(손절/익절) 발행 가능 (선택) |
| `async on_order_update` | `update: dict[str, Any]` | `None` | 주문 상태 변경(접수/거부/취소) 통보 (선택) |
| `async on_data` | `data: dict[str, Any]` | `list[Signal]` | 외부 데이터(뉴스, 이벤트, AI 시그널) 수신 시 호출. 즉시 주문 발행 가능 (선택) |
| `async on_position_corrected` | `correction: dict[str, Any]` | `None` | 대사(Reconciliation) 포지션 보정 통보 (선택) |
| `get_rules` | — | `dict[str, Any]` | 전략별 거래 룰 반환. Rule Engine이 전역 룰과 함께 검증 (선택) |
| `get_params` | — | `dict[str, Any]` | 백테스트 최적화 가능 파라미터 반환 (선택) |
| `get_param_schema` | — | `dict[str, str]` | 파라미터별 설명 반환 (선택). Bot CLI에서 `--param` 힌트로 사용 |

**설계 근거**:

1. **`on_step()` 단일 진입점 (NautilusTrader의 on_bar 패턴 단순화)**
   - NautilusTrader는 on_bar, on_tick, on_quote_tick 등 데이터 타입별 콜백이 분리됨
   - Ante는 봇이 주기적으로 `on_step()`을 호출하는 단일 진입점 방식 채택
   - 전략은 `ctx`를 통해 필요한 데이터를 직접 조회 → 더 유연함
   - 타임프레임(분봉, 일봉 등)에 따른 호출 주기는 봇이 관리

2. **Signal 반환 방식 (FreqTrade의 DataFrame 컬럼 방식 대신)**
   - FreqTrade는 DataFrame 전체를 반환하고 enter/exit 컬럼을 확인
   - Ante는 명시적 Signal 객체를 반환 → 의도가 명확하고 다양한 주문 유형 표현 가능
   - 빈 리스트 반환 = 아무 행동 안 함 (명시적)

3. **`on_fill()`, `on_order_update()`, `on_position_corrected()`, `on_data()` 선택적 이벤트 핸들러**
   - `on_fill()`: 체결 통보로 포지션 추적 + **후속 주문 발행** (매수 체결 → 손절/익절 즉시 등록)
   - `on_order_update()`: 주문 접수 시 order_id 획득, 거부/취소 시 대응 (예: 스탑 주문 재등록)
   - `on_position_corrected()`: 대사(Reconciliation)에 의한 포지션 보정 통보 — 전략 내부 상태 갱신
   - `on_data()`: 외부 시그널 채널을 통해 수신된 데이터/주문 지시로 **즉시 주문 발행**. 아웃소싱 전략의 핵심 진입점
   - `on_fill()`과 `on_data()`는 `list[Signal]`을 반환 — 빈 리스트면 후속 주문 없음
   - 구현은 선택 사항 — 필요한 전략만 오버라이드

4. **`get_rules()` 전략별 룰 선언**
   - Rule Engine이 전역 룰과 함께 검증할 수 있도록 전략이 자체 룰을 선언
   - architecture.md의 2중 룰 구조(전역 + 전략별) 구현
