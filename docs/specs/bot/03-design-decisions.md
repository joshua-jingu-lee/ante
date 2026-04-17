# Bot 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [bot.md](bot.md)

# 설계 결정

### 봇 상태 머신

BotStatus는 다음 6가지 상태를 갖는 StrEnum이다: `CREATED`, `RUNNING`, `STOPPING`, `STOPPED`, `ERROR`, `DELETED`.

**상태 전이**:
```
CREATED → RUNNING → STOPPING → STOPPED → DELETED
                  ↘ ERROR           ↗
```

**근거**:
- NautilusTrader는 INITIALIZED/RUNNING/STOPPED/DEGRADED/FAULTING/DISPOSED 6단계
- Ante는 6단계 — DELETED 상태를 추가하여 삭제된 봇의 상태를 명시적으로 구분
- STOPPING 상태로 graceful shutdown 지원 (열린 주문 정리 등)

### BotConfig

> 소스: `src/ante/bot/config.py`

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `bot_id` | `str` | (필수) | 고유 ID |
| `strategy_id` | `str` | (필수) | 등록된 전략 ID (또는 파일 경로) |
| `account_id` | `str` | (필수) | 소속 계좌 ID |
| `name` | `str` | `""` | 봇 표시 이름 |
| `interval_seconds` | `int` | `60` | `on_step()` 호출 주기 (초) |
| `auto_restart` | `bool` | `True` | 에러 시 자동 재시작 여부 |
| `max_restart_attempts` | `int` | `3` | 최대 재시작 시도 횟수 |
| `restart_cooldown_seconds` | `int` | `60` | 재시작 쿨다운 (초) |
| `step_timeout_seconds` | `int` | `30` | `on_step()` 호출 타임아웃 (초). 초과 시 경고 로그 기록 |
| `max_signals_per_step` | `int` | `50` | 한 스텝에서 허용하는 최대 시그널 수. 초과 시 전체 거부 + BotErrorEvent 발행. 연속 `max_consecutive_failures`회 초과 시 봇 중지 |

**제거된 필드**:
- `bot_type`: Bot은 trading_mode를 직접 알지 못한다. Account의 `trading_mode`(LIVE/VIRTUAL)에 따라 ContextFactory가 실행 경로를 결정한다.
- `exchange`: Account의 속성이다. 봇이 독립적으로 exchange를 가지면 Account와 불일치할 수 있으므로 제거. 필요 시 `AccountService.get(account_id).exchange`로 조회한다.
- `paper_initial_balance`: 가상 자금은 Account 레벨에서 관리한다.

**실행 간격 제한**: `interval_seconds`는 `MIN_INTERVAL_SECONDS`(10초) 이상 `MAX_INTERVAL_SECONDS`(3600초) 이하여야 한다. 범위 밖이면 `ValueError` 발생. `validate_interval()` 함수로 검증.

### Bot 클래스

> 소스: `src/ante/bot/bot.py`

**퍼블릭 메서드**:

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `start` | — | `None` | 봇 시작. 전략 인스턴스화 + 실행 루프 Task 생성 |
| `stop` | — | `None` | 봇 중지. 실행 루프 취소 + 전략 정리 |
| `on_order_filled` | `event: object` | `None` | 체결 통보를 전략에 전달. `OrderFilledEvent`만 처리하고 자기 bot_id만 필터링. 후속 Signal(손절/익절)을 즉시 발행 |
| `on_order_update` | `event: object` | `None` | 주문 상태 변경 통보를 전략의 `on_order_update()`에 전달. `OrderSubmittedEvent`, `OrderRejectedEvent`, `OrderCancelledEvent`, `OrderFailedEvent`, `OrderCancelFailedEvent` 처리 |
| `on_external_signal` | `event: object` | `None` | 외부 시그널 채널에서 수신한 데이터를 전략의 `on_data()`에 전달. `accepts_external_signals=True`인 전략만 처리 |
| `get_info` | — | `dict[str, Any]` | 봇 상태 정보(bot_id, account_id, trading_mode, exchange, currency, status, config 등) 반환 |

**설계 근거**:

1. **Bot은 구체 클래스 (ABC 아닌)**
   - 이전 초안은 Bot을 ABC로 정의하고 LiveBot/PaperBot이 상속
   - 실제로 실행 루프는 동일 — 차이는 StrategyContext에 주입되는 DataProvider와 PortfolioView
   - LIVE/VIRTUAL 차이는 Bot이 아니라 ContextFactory가 Account의 trading_mode를 참조하여 결정

2. **Signal → OrderRequestEvent 변환은 Bot의 책임**
   - 전략은 Signal만 반환 (시스템 이벤트를 모름)
   - Bot이 Signal을 EventBus 이벤트로 변환하여 발행
   - 이로써 전략 코드가 EventBus에 의존하지 않음

3. **OrderAction → EventBus 이벤트 변환 (`_publish_actions`)**
   - `_run_loop()`에서 매 스텝 후 `StrategyContext._drain_actions()`로 주문 취소/정정 액션을 수집
   - `action == "cancel"` → `OrderCancelEvent`, `action == "modify"` → `OrderModifyEvent`로 변환하여 발행

4. **체결 통보 전달 (`on_order_filled`)**
   - Bot이 EventBus에서 OrderFilledEvent를 구독
   - 자기 bot_id인 이벤트만 필터링하여 전략의 `on_fill()`에 전달
   - 전략은 dict로만 받으므로 EventBus 이벤트 타입에 의존하지 않음

5. **주기적 루프 (interval_seconds)**
   - 타임프레임별 호출 주기는 봇 설정으로 관리
   - 1분봉 전략: 60초, 5분봉: 300초, 일봉: 장 마감 후 1회
   - 전략은 호출 주기를 모르고, 호출될 때마다 판단만 수행

### BotManager

> 소스: `src/ante/bot/manager.py`

**퍼블릭 메서드**:

| 메서드명 | 파라미터 | 반환값 | 설명 |
|----------|----------|--------|------|
| `create_bot` | `config: BotConfig, strategy_cls: type[Strategy], ctx: StrategyContext \| None = None` | `Bot` | 봇 생성. ctx가 주입되면 그대로 사용하고, None이면 context_factory로 자동 생성. 이벤트 구독 등록 + DB 저장. `accepts_external_signals=True`이면 시그널 키 자동 발급 |
| `start_bot` | `bot_id: str` | `None` | 봇 시작. `bot.start()` 호출 |
| `stop_bot` | `bot_id: str` | `None` | 봇 중지 |
| `update_bot` | `bot_id: str, updates: dict` | `Bot` | 봇 설정 수정. **중지 상태에서만 가능** — RUNNING이면 `BotError` 발생. BotConfig는 frozen dataclass이므로 재생성 패턴 적용: 기존 config를 dict로 풀고 → updates 병합 → 새 BotConfig 생성 → Bot.config 교체 → DB 갱신. `budget` 키가 포함되면 `Treasury.deallocate()` + `Treasury.allocate()`로 예산 재조정. `strategy_id` 변경 시 StrategyRegistry 존재 확인 + exchange 호환성 검증 |
| `delete_bot` | `bot_id: str, handle_positions: str = "keep"` | `None` | 봇 삭제. 실행 중이면 먼저 중지. `handle_positions="liquidate"` 시 TradeService를 통해 보유 종목 시장가 매도 주문 발행 후 삭제 진행. `"keep"`(기본)은 포지션 유지한 채 봇만 삭제. 이벤트 구독 해제 + VIRTUAL 계좌 봇의 PaperExecutor 해제 + 시그널 키 폐기 + DB 레코드 삭제. `remove_bot`은 동일 기능의 별칭(alias) |
| `stop_all` | — | `None` | 모든 실행 중 봇 중지 + 재시작 태스크 취소. 시스템 셧다운 시 호출 |
| `list_bots` | — | `list[dict[str, Any]]` | 봇 목록 조회 |
| `get_bot` | `bot_id: str` | `Bot \| None` | 봇 조회. 없으면 None |
| `rotate_signal_key` | `bot_id: str` | `str` | 기존 시그널 키 폐기 + 새 키 발급. 연결 중인 채널은 즉시 끊김 |
| `get_signal_key` | `bot_id: str` | `str \| None` | 봇의 시그널 키 조회. `accepts_external_signals=False`이면 `None` |
| `get_restart_count` | `bot_id: str` | `int` | 봇의 현재 재시작 시도 횟수 |
| `assign_strategy` | `bot_id: str, strategy_id: str` | `None` | 봇에 전략 배정. RUNNING이면 중지→전략 교체→재시작. STOPPED/CREATED이면 전략 ID만 교체 |
| `change_strategy` | `bot_id: str, strategy_id: str` | `None` | 중지 상태 봇의 전략 교체. RUNNING이면 `BotError` 발생 |
| `resume_bot` | `bot_id: str` | `None` | STOPPED/ERROR 상태 봇 재시작. 에러 카운터 리셋 후 `start()` 호출. RUNNING이면 `BotError` 발생 |
| `load_from_db` | — | `int` | DB에서 봇 설정을 읽어 메모리에 로드. deleted 제외. 반환값은 로드된 봇 수 |

**설계 근거**:

1. **봇 유형 차이는 StrategyContext 주입으로 해결**
   - LIVE 계좌 봇: 실제 계좌 연동 PortfolioView (Treasury + Trade 경유)
   - VIRTUAL 계좌 봇: 가상 자금 PortfolioView (독립 인메모리)
   - DataProvider는 동일 — VIRTUAL 계좌도 실시간 시세 데이터를 사용
   - Bot 클래스는 하나, 주입되는 의존성만 다름
   - ContextFactory가 Account의 trading_mode를 참조하여 적절한 의존성을 주입

2. **봇 생성 시 계좌 검증**
   - Account 존재 및 상태(active) 확인
   - Strategy.meta.exchange와 Account.exchange 호환성 검증
   - Account가 정지(suspended) 상태이면 `AccountSuspendedError` 발생

3. **체결 통보 구독은 BotManager가 관리**
   - Bot 생성 시 EventBus 구독 등록, 삭제 시 해제
   - Bot이 직접 EventBus를 구독/해제하지 않음 → 생명주기 관리 일원화

4. **봇 설정 영속화 (SQLite)**
   - 봇 설정을 DB에 저장하여 이력 관리
   - `auto_start` 플래그로 자동 재시작 여부 제어

### 봇 유형별 차이: LIVE vs VIRTUAL (Account.trading_mode 기준)

| 측면 | LIVE 계좌 봇 | VIRTUAL 계좌 봇 |
|------|-------------|----------------|
| PortfolioView | Treasury(잔고) + Trade(포지션) 경유 | PaperPortfolioView, 가상 자금 인메모리 관리 |
| 주문 처리 | OrderRequestEvent → RuleEngine → BrokerAdapter → 실제 주문 | OrderRequestEvent → RuleEngine → PaperExecutor → 가상 체결 |
| 데이터 | 실시간 시세 (API Gateway 경유) | 실시간 시세 (동일) |
| 자금 | Treasury에서 할당받은 실제 자금 | Account 레벨에서 설정된 가상 자금 |
| 체결 | BrokerAdapter가 실제 체결 후 OrderFilledEvent 발행 | PaperExecutor가 즉시 가상 체결 후 OrderFilledEvent 발행 |
| 브로커 접근 | `AccountService.get_broker(account_id)` | — (PaperExecutor 사용) |
| 예산 접근 | `TreasuryManager.get(account_id)` | 가상 자금 관리 |

**근거**:
- Bot 자체는 trading_mode를 모른다. Account의 trading_mode에 따라 ContextFactory가 실행 경로를 결정
- Bot 코드는 동일, 주입되는 PortfolioView와 주문 실행 경로만 다름
- 전략 입장에서는 LIVE/VIRTUAL 구분 없이 동일한 StrategyContext API 사용

### SQLite 스키마

```sql
CREATE TABLE IF NOT EXISTS bots (
    bot_id       TEXT PRIMARY KEY,
    strategy_id  TEXT NOT NULL,
    account_id   TEXT NOT NULL,                  -- 소속 계좌 ID
    config_json  TEXT NOT NULL,                  -- BotConfig 직렬화
    auto_start   BOOLEAN DEFAULT 0,              -- 시스템 시작 시 자동 재시작
    status       TEXT DEFAULT 'created',
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bots_account_id ON bots(account_id);
```

### 봇 실행 흐름 (전체)

```
사용자: 웹 대시보드 또는 CLI에서 봇 생성 + 전략 로드 + 활성화
  ↓  (CLI: IPC를 통해 서버 프로세스에 위임 → `docs/specs/ipc/ipc.md` 참조)
BotManager.create_bot(config, strategy_cls, ctx?)
  → Account 존재 및 상태(active) 확인
  → Strategy.meta.exchange와 Account.exchange 호환성 검증
  → ctx가 None이면 context_factory로 StrategyContext 자동 생성
    (ContextFactory가 Account.trading_mode로 LIVE/VIRTUAL 분기)
  → Bot 인스턴스 생성 + 이벤트 구독 등록 (체결/주문상태/외부시그널)
  → accepts_external_signals=True이면 시그널 키 자동 발급
  → DB에 봇 설정 저장 (account_id 포함)
  ↓
BotManager.start_bot(bot_id)
  → bot.start()
    → Strategy(ctx) 인스턴스화
    → strategy.on_start() 호출
    → asyncio.Task로 _run_loop() 시작
    → BotStartedEvent 발행
  ↓
[주기적 루프]
  → step_context 구성 (timestamp, portfolio, balance)
  → strategy.on_step(step_context) 호출
  → signals: list[Signal] 반환
  → Signal → OrderRequestEvent 변환 + EventBus 발행
  → ctx._drain_actions() → OrderCancelEvent/OrderModifyEvent 발행
  → asyncio.sleep(interval_seconds)
  ↓
[체결 시]
  → OrderFilledEvent 수신
  → bot.on_order_filled() → strategy.on_fill() 호출
  ↓
[봇 중지 시]
  → bot.stop()
    → Task 취소
    → strategy.on_stop() 호출
    → BotStoppedEvent 발행
```

### 외부 시그널 채널

> 참조: [strategy.md](../strategy/strategy.md) 전략 운용 방식, 외부 시그널 채널

아웃소싱/하이브리드 전략을 위해, 외부 에이전트와 봇 사이에 **CLI 파이프 기반 양방향 시그널 채널**을 제공한다.

**시그널 키 생명주기**:
```
create_bot(config)
  → 전략의 meta.accepts_external_signals 확인
    ├─ True  → signal_key 발급 + DB 저장 + 출력
    └─ False → signal_key 없음
  ↓
[운영 중]
  → rotate_signal_key(bot_id) — 키 갱신 (기존 채널 즉시 끊김)
  ↓
remove_bot(bot_id)
  → signal_key 폐기
```

**시그널 키 SQLite 스키마**:
```sql
CREATE TABLE IF NOT EXISTS signal_keys (
    key_id       TEXT PRIMARY KEY,          -- "sk_" + 32자 hex (128-bit entropy)
    bot_id       TEXT NOT NULL UNIQUE,      -- 1 봇 = 1 키
    created_at   TEXT DEFAULT (datetime('now'))
);
```

**CLI 파이프 채널 동작**:

```bash
ante signal connect --key sk_a1b2c3d4
```

1. 키 유효성 검증 → 바인딩된 bot_id 확인
2. 봇의 전략이 `accepts_external_signals=True`인지 확인
3. 봇이 RUNNING 상태인지 확인
4. 양방향 JSON Lines 스트림 수립 (stdin/stdout)

**채널이 봇에 전달하는 이벤트**:
- 외부 → Ante: `{"type": "signal", ...}` → ExternalSignalEvent 발행 → `on_data()` 호출
- 외부 → Ante: `{"type": "query", "method": "positions"}` → StrategyContext 경유 조회 → 결과 반환
- 외부 → Ante: `{"type": "ping"}` → `{"type": "pong"}` 응답 (연결 상태 확인)

**채널이 외부에 전달하는 이벤트**:
- Ante → 외부: 체결 통보 (`{"type": "fill", ...}`)
- Ante → 외부: 주문 상태 변경 (`{"type": "order_update", ...}`)
- Ante → 외부: 데이터 조회 응답 (`{"type": "result", ...}`)

**`on_external_signal()` 구현**:

Bot이 ExternalSignalEvent를 수신하면:
1. `event.bot_id`가 자기 것인지 확인
2. 전략의 `meta.accepts_external_signals` 확인 (이중 검증)
3. `strategy.on_data(event.data)` 호출
4. 반환된 Signal을 `_publish_signals()`로 발행
5. 체결/상태 변경 시 채널을 통해 외부에 통보

### 예외 격리 (D-003)

각 Bot은 별도 `asyncio.Task`로 실행되므로, 한 봇에서 예외가 발생해도 다른 봇에 영향을 주지 않는다.

- `_run_loop()` 내부에서 예외 발생 시 해당 봇만 `ERROR` 상태로 전환
- `BotErrorEvent`를 발행하여 알림 트리거
- 다른 봇의 Task는 독립적으로 계속 실행
- `CancelledError`는 재발생시켜 정상 중지 흐름(`stop()`) 유지

### 봇 자동 재시작 정책

BotManager는 봇 에러 발생 시 `BotErrorEvent`를 구독하여 자동 재시작을 수행한다.

**정책**:
- `auto_restart` 설정이 `True`인 봇만 대상
- 쿨다운(`restart_cooldown_seconds`) 대기 후 재시작 시도
- 최대 `max_restart_attempts`회까지 시도
- 한도 소진 시 `BotRestartExhaustedEvent` 발행 → 알림 트리거
- 재시작 성공 후 `cooldown × max_restart_attempts`초 동안 정상 운행하면 카운터 리셋

**관련 메서드**:
- `_on_bot_error()` — 에러 감지 + 재시작 스케줄링
- `_restart_after_cooldown()` — 쿨다운 대기 후 `bot.start()` 재호출
- `_schedule_restart_reset()` — 정상 운행 유지 시 카운터 리셋 타이머
- `_on_restart_exhausted()` — 한도 소진 이벤트 발행
- `get_restart_count(bot_id)` — 현재 재시작 시도 횟수 조회
