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
| `account_id` | `str` | (필수) | 소속 계좌 ID. **생성 후 불변** — `update_bot`으로 변경할 수 없다(아래 `update_bot` 항목 참조) |
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
- `virtual_initial_balance`: 가상 자금은 Account 레벨에서 관리한다.

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
   - 이전 초안은 Bot을 ABC로 정의하고 LiveBot/VirtualBot이 상속
   - 실제로 실행 루프는 동일 — 차이는 StrategyContext에 주입되는 DataProvider와 PortfolioView
   - LIVE/VIRTUAL 차이는 Bot이 아니라 ContextFactory가 Account의 trading_mode를 참조하여 결정

2. **Signal → OrderRequestEvent 변환은 Bot의 책임**
   - 전략은 Signal만 반환 (시스템 이벤트를 모름)
   - Bot이 Signal을 EventBus 이벤트로 변환하여 발행
   - 이로써 전략 코드가 EventBus에 의존하지 않음

3. **OrderAction → EventBus 이벤트 변환 (`_publish_actions`)**
   - `_run_loop()`에서 매 스텝 후 `StrategyContext._drain_actions()`로 주문 취소/정정 액션을 수집
   - `action == "cancel"` → `OrderCancelEvent`, `action == "modify"` → `OrderModifyEvent`로 변환하여 발행
   - **modify v1=price-only (#2391)**: Bot은 `OrderModifyEvent`를 발행만 하며(`action.quantity or 0.0`로 수량을 접음 — `0.0`=price-only 미지정), broker-level 정정 v1은 `open` 주문의 가격 정정(수량 불변)을 지원한다. 룰/Gateway fail-closed 통과 시 `OrderModifyExecutedEvent` → Bot이 `on_order_update` status=`modified`로 전략에 통보한다. 고급 케이스(수량변경 등)는 fail-closed 거부되므로 그 경우 `cancel` 후 재주문으로 대체한다(후속 #2393).

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
| `update_bot` | `bot_id: str, updates: dict` | `Bot` | 봇 설정 수정. **중지 상태에서만 가능** — RUNNING이면 `BotError` 발생. BotConfig는 frozen dataclass이므로 재생성 패턴 적용: 기존 config를 dict로 풀고 → updates 병합 → 새 BotConfig 생성 → Bot.config 교체 → DB 갱신. `budget` 키가 포함되면 `Treasury.deallocate()` + `Treasury.allocate()`로 예산 재조정. `strategy_id` 변경 시 StrategyRegistry 존재 확인 + exchange 호환성 검증. **`account_id`는 불변 필드** — updates에 현재 값과 다른 `account_id`가 포함되면 `BotImmutableFieldError`(안정 코드 `BOT_IMMUTABLE_FIELD`, validation 카테고리) 발생. 같은 값(no-op)·미포함은 통과 |

**`account_id` 불변 정책 (#2282)**: 봇의 `account_id`는 생성 후 변경할 수 없다. treasury 예산은 옛 account 아래에 할당되고, broker credential도 옛 account에 바인딩되며, 포지션 격리도 account-bound이므로, `account_id`를 변경하면 이 자원들이 새 account로 재배치되지 않아 불일치가 발생한다. 단일 사용자 홈서버에서 복잡한 re-isolation(예산 이전·credential 재바인딩·포지션 마이그레이션)을 구현하는 대신, `account_id`를 `update_bot`의 불변 필드로 제약한다(YAGNI 안전 기본). 변경이 필요하면 **봇을 삭제 후 재생성**한다. 이는 Account의 불변 필드(`exchange`/`currency`/`trading_mode`/`broker_type`, `AccountImmutableFieldError`) 정책과 정합한다([account/04-account-service.md](../account/04-account-service.md) 참조). `_save_bot_config`의 UPSERT가 `account_id` 컬럼을 갱신하는 것(#2274, create/load 경로 persistence 일관성)은 그대로 유지되며, 제약은 `update_bot` ingress에서만 적용된다.
| `delete_bot` | `bot_id: str, handle_positions: str = "keep"` | `None` | 봇 삭제. 실행 중이면 먼저 중지. `handle_positions="liquidate"` 시 TradeService를 통해 보유 종목 시장가 매도 주문 발행 후 삭제 진행. `"keep"`(기본)은 포지션 유지한 채 봇만 삭제. 이벤트 구독 해제 + VIRTUAL 계좌 봇의 VirtualExecutor 해제 + 시그널 키 폐기 + DB 레코드 삭제. `remove_bot`은 동일 기능의 별칭(alias) |
| `stop_all` | — | `None` | 모든 실행 중 봇 중지 + 재시작 태스크 취소. 시스템 셧다운 시 호출 |
| `list_bots` | — | `list[dict[str, Any]]` | 봇 목록 조회 |
| `get_bot` | `bot_id: str` | `Bot \| None` | 봇 조회. 없으면 None |
| `rotate_signal_key` | `bot_id: str` | `str` | 기존 시그널 키 폐기 + 새 키 발급. DB rotate 커밋 직후 해당 봇의 활성 시그널 채널을 teardown한다 — **커밋 후 NEW signal은 admit되지 않으며, 옛 키로 이미 진입한 in-flight signal은 최대 1개까지 정상 완료**(in-flight abort 아님). enforcement 메커니즘은 아래 `### 채널 teardown enforcement (#2334)` 참조. 구현 PR 머지 후 적용(동기 버그 #2333 unblock) |
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
| PortfolioView | Treasury(잔고) + Trade(포지션) 경유 | VirtualPortfolioView, 가상 자금 인메모리 관리 |
| 주문 처리 | OrderRequestEvent → RuleEngine → BrokerAdapter → 실제 주문 | OrderRequestEvent → RuleEngine → VirtualExecutor → 가상 체결 |
| 데이터 | 실시간 시세 (API Gateway 경유) | 실시간 시세 (동일) |
| 자금 | Treasury에서 할당받은 실제 자금 | Account 레벨에서 설정된 가상 자금 |
| 체결 | BrokerAdapter가 실제 체결 후 OrderFilledEvent 발행 | VirtualExecutor가 즉시 가상 체결 후 OrderFilledEvent 발행 |
| 브로커 접근 | `AccountService.get_broker(account_id)` | — (VirtualExecutor 사용) |
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
사용자: CLI에서 봇 생성 + 전략 로드 + 활성화
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

CLI의 `bot create/start/stop`과 `bot signal-key --rotate`는 위 흐름을 서버
프로세스 안에서 실행해야 하므로 런타임 IPC 전용이다. 직접 DB 수정으로 봇 status나
signal key를 바꾸면 `_bots`, 실행 task, EventBus 구독, 외부 signal channel이
어긋나므로 허용하지 않는다.

`ante bot start/stop/status`의 CLI/IPC 계약은 서버 BotManager 동작과 정렬된다.
CLI/IPC가 같은 BotManager 인스턴스를 통해 같은 검증·실행·이벤트·감사 경로를
사용해야 모든 호출자가 같은 봇에 대해 같은 결과를 얻고 같은 audit trail을 남긴다.
`start`의 `app_key` 사전 검증, `BotError` → state conflict 매핑,
`bot.start`/`bot.stop` audit action 이름, `{"bot": ...}` envelope는 모두 CLI/IPC
계약에서 가져온다. cold-path fallback이나 직접 DB 수정으로 봇을 시작/중지하는
경로는 허용하지 않는다.

`bot remove`는 예외적으로 서버 실행 중에는 런타임 IPC, 서버 정지 상태에서는
cold-path cleanup을 허용한다. cold-path 삭제는 BotManager를 만들지 않고 DB에
남은 persisted state만 정리하며, 의미는 hot-path `handle_positions="keep"`과
같다. 즉 broker live 연결이 필요한 포지션 청산은 하지 않고, `signal_keys` 폐기,
`strategies/.running/{bot_id}` 스냅샷 삭제, Treasury budget 환수, `bots.status =
'deleted'` 갱신만 수행한다. DB에 `running`/`stopping` 상태가 남아 있어도 서버가
정지된 상태에서는 실행 task와 EventBus observer가 이미 부재하므로 stale status로
보고 정리한다. 다음 서버 부팅 시 BotManager는 `deleted` 봇을 로드하지 않는다.

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
  → rotate_signal_key(bot_id) — 키 갱신 (커밋 후 NEW signal 미admit; in-flight at-most-one 완료, abort 아님 — ↓ 채널 teardown enforcement)
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

### 채널 teardown enforcement (#2334)

> wire/transport 세부(3-phase upgrade, 1:1 framing, `closed.reason` vocab 등)는 [ipc.md](../ipc/ipc.md) streaming 절이 SSOT다. 본 절은 채널 생명주기 **계약**만 정의한다.
> **적용 시점**: 본 enforcement는 **구현 PR 머지 후(동기 버그 #2333 unblock)** 동작한다. 그 전까지 `ante signal connect`는 데몬이 아닌 CLI-프로세스의 `BotManager`를 보므로 데몬에서 RUNNING 중인 봇 채널에 닿지 못한다(현 동작 = #2333 dead-end). 따라서 아래 "즉시 끊김" 계약은 **현재 실행 가능 동작이 아니라 채택된 목표 계약**이다.

기존 스펙은 "키 갱신 시 기존 채널은 즉시 끊긴다"고 단언했으나 **enforcement 메커니즘은 명세되지 않았다**. #2334로 다음을 정규화한다.

**`SignalChannelRegistry`**: 데몬에 상주하는 활성 채널 레지스트리. `bot_id → {session_id → ChannelHandle}` 구조로 활성 시그널 채널을 추적하며, `rotate_signal_key`/`delete_bot`/봇 상태 전이/데몬 shutdown이 봇 단위로 채널을 강제 종료(`close_bot(bot_id, reason)` / `close_all(reason)`)할 수 있게 한다. 데몬 부팅 시 단일 인스턴스를 BotManager·IPC 서버에 공유 주입한다(미사용 환경은 None 허용).

**단일 active connect 정책**: 본 릴리스는 **bot_id당 동시 active 시그널 채널 1개**만 허용한다. 같은 봇에 대한 두 번째 `signal connect` 핸드셰이크는 stable code **`BOT_SIGNAL_CHANNEL_BUSY`**로 거부된다(동시 same-bot 구독의 fan-out·dedup 경합 클래스 제거). 레지스트리는 미래 multi-connect 대비 `session_id` 키를 유지하되, 정책은 현 릴리스에서 single로 잠근다. (코드 분류 SSOT는 [error-taxonomy.md](../contracts/error-taxonomy.md).)

**teardown 트리거**: 오직 rotate/delete만 거는 대신, **봇이 RUNNING을 이탈하는 모든 경로**를 단일 메커니즘으로 덮는다.

| 트리거 | 메커니즘 | `closed.reason` |
|--------|----------|------------------|
| 키 회전 | `rotate_signal_key` — DB rotate **커밋 성공 직후** `close_bot(bot_id, "rotated")`. ROLLBACK 시 teardown 안 함(옛 키 유효) | `rotated` |
| 봇 삭제 | `delete_bot` — `bot.stop()` **호출 전**에 `close_bot(bot_id, "deleted")`(채널이 dead ctx를 pump하지 않도록) | `deleted` |
| 봇 RUNNING 이탈(graceful stop·자율 ERROR·account-suspend·rule-engine stop·auto-restart·`stop_all`) | `BotStoppedEvent`/`BotErrorEvent`를 `bot_id` 필터로 **이벤트-구동** 구독 → 수신 시 `close_bot(bot_id, "bot_stopped")` | `bot_stopped` |
| 데몬 shutdown | shutdown sweep에서 봇 stop·DB close **이전에** `close_all("draining")`(channels-before-bots-before-db 불변) | `draining` |

- teardown hook은 **BotManager 계층**(rotate/delete 메서드·이벤트 구독)에만 둔다. pure-DB primitive(`SignalKeyManager.rotate/revoke`)에는 두지 않는다 — cold-path(서버 정지 상태)에서도 도달하는 경로이기 때문이다.

**rotate→teardown 정밀 보장**: rotate 커밋이 active signal 처리 중에 발생해도 in-flight `strategy.on_data` 체인을 mid-chain cancel하면 전략 상태가 손상된다. 따라서 보장을 다음과 같이 정밀화한다.

1. teardown은 먼저 `accepting=False`를 set하여 이후 inbound signal admit을 거부한다.
2. in-flight publish/`on_data` span은 shield되어 완료된다(mid-chain cancel 금지).
3. 결과 보장 = **"커밋 후 NEW signal은 admit되지 않으며, 옛 키로 진입한 in-flight signal은 최대 1개(at-most-one)까지 정상 완료된다"** — **"in-flight signal abort"가 아니다.** 즉 rotate/delete 직후 새 주문을 유발하는 신규 시그널 주입은 불가능하고, 옛 키로 이미 진입한 trailing signal 1개와 그에 따른 trailing fill만 관측될 수 있다.

이 enforcement는 "직접 DB 수정으로 봇 status/signal key를 바꾸면 `_bots`·실행 task·EventBus 구독·외부 signal channel이 어긋나므로 허용하지 않는다"는 본 문서의 런타임 IPC 위임 원칙(위 참조)과 정합한다.

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
