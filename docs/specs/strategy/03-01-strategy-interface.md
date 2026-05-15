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

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> `StrategyMeta.exchange`는 `*`가 허용되는 **유일한** 표면이다. 표면별 enforcement 정렬은 #1578에서 다룬다.

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
| `async on_order_update` | `update: dict[str, Any]` | `None` | 주문 상태 변경(접수/거부/취소/정정거부/스탑 등록·발동·만료) 통보 (선택). 상태값과 키 명세는 아래 ["on_order_update 알림 명세"](#on_order_update-알림-명세) 참고 |
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

#### on_order_update 알림 명세

`Bot.on_order_update`가 변환하여 전략에 전달하는 `update: dict[str, Any]`의
`status` 값과 dict 키 명세는 다음과 같다. 일반 주문과 스탑 주문 모두 동일한
콜백으로 전달되며, 별도 콜백(`on_stop_order_update` 등)은 신설하지 않는다
(시장 표준 패턴 + 전략 작성자 부담 최소화).

##### 일반 주문 상태값

| `status` | 발생 시점 | 변환 원본 이벤트 | 필수 키 |
|---|---|---|---|
| `submitted` | 브로커가 주문 접수 | `OrderSubmittedEvent` | `order_id`, `status`, `symbol`, `side` |
| `rejected` | 신규 주문 거부 (룰 / 브로커) | `OrderRejectedEvent` | `order_id`, `status`, `symbol`, `side`, `reason` |
| `cancelled` | 주문 취소 완료 | `OrderCancelledEvent` | `order_id`, `status`, `symbol`, `side`, `reason` |
| `failed` | 주문 발행 실패 (네트워크/시스템 오류) | `OrderFailedEvent` | `order_id`, `status`, `symbol`, `side`, `reason` |
| `cancel_failed` | 취소 실패 | `OrderCancelFailedEvent` | `order_id`, `status`, `symbol`, `side`, `reason` |
| `modify_rejected` | 정정 거부 (룰 거부 / 룰 예외 / 미구현) | `OrderModifyRejectedEvent` | `order_id`, `status`, `symbol`, `side`, `reason` |

##### 스탑 주문 상태값 (#1336)

스탑 주문 (`stop` / `stop_limit`)은 KRX가 네이티브 지원하지 않으므로
`StopOrderManager`가 에뮬레이션한다. 등록·발동·만료 세 시점 모두
`on_order_update`로 전달된다 (정책: 일반 주문과 동일 채널, 별도 콜백
신설 금지).

| `status` | 발생 시점 | 변환 원본 이벤트 | 필수 키 |
|---|---|---|---|
| `stop_registered` | 등록 직후 (가격 조건이 시스템에 잡힘) | `StopOrderRegisteredEvent` | `order_id` (= `stop_order_id`), `stop_order_id`, `status`, `symbol`, `side`, `quantity`, `stop_price`, `limit_price` |
| `stop_triggered` | 가격 조건 충족 → 일반 주문으로 변환 | `StopOrderTriggeredEvent` | `order_id` (= `stop_order_id`), `stop_order_id`, `status`, `symbol`, `side`, `quantity`, `trigger_price`, `converted_order_type` |
| `stop_expired` | 자동 해제 (세션 종료 또는 매니저 중지) | `StopOrderExpiredEvent` | `order_id` (= `stop_order_id`), `stop_order_id`, `status`, `symbol`, `reason` |

스탑 알림에서:

- `order_id`에는 `stop_order_id`를 그대로 채워 일반 주문 알림과 dict shape를
  맞춘다 (전략이 후속 `cancel/modify`에 그대로 사용 가능). `stop_order_id`
  키도 명시 식별자로 함께 노출한다.
- 발동(`stop_triggered`) 알림은 변환된 일반 주문이 자체 라이프사이클 이벤트
  (`OrderSubmittedEvent` 등)를 별도로 발행하므로, 스탑 식별 단위로 받고 싶은
  경우 본 알림으로 분기한다.
- 만료(`stop_expired`) 알림의 `reason` 허용 값: `"session_ended"`,
  `"manager_stopped"` (현재 코드 기준). 추후 `manual_cancel` 등 도입은 별도
  이슈로 분리한다.
- 스탑 알림에는 자금 reserve 정보가 포함되지 않는다 (#1337 정책: 매수 stop은
  등록 시점 자금 잠금 없음, 트리거 시점 잠금).

활용 예시 — "스탑 주문 재등록":

```python
async def on_order_update(self, update):
    if update["status"] == "stop_expired" and update["reason"] == "session_ended":
        # 다음 세션에서 동일 stop 주문 다시 등록
        ...
    elif update["status"] == "stop_triggered":
        # 발동된 stop의 변환 주문 자체 라이프사이클은
        # 별도 OrderSubmittedEvent 등으로 통보된다
        ...
```
