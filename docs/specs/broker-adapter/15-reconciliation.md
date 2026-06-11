# Broker Adapter 모듈 세부 설계 - 대사 (Reconciliation)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 대사 (Reconciliation)

### PositionReconciler — 포지션 정합성 검증·보정

> **구현 완료** — Trade 모듈(`src/ante/trade/reconciler.py`)에 `PositionReconciler`로 구현되었다.
> Broker 모듈이 아닌 Trade 모듈에 배치된 이유: 포지션의 단일 소유자가 Trade 모듈이므로,
> 포지션 보정 로직도 Trade 모듈에 포함하는 것이 자연스럽다.

PositionReconciler는 `TradeService`, `EventBus`를 주입받아 동작한다.
봇의 내부 포지션과 브로커 실제 포지션을 대조하여 불일치를 감지하고,
`PositionMismatchEvent` + `ReconcileEvent`를 발행하며, `TradeService.correct_position()`으로 자동 보정한다.

상세: [trade.md](../trade/trade.md) PositionReconciler 참조

### OrderRegistry — order_id → bot_id 매핑

구현: `src/ante/broker/order_registry.py` 참조

복수 봇이 같은 계좌에서 거래할 때, 브로커가 반환하는 order_id가 어느 봇의 주문인지 추적하기 위한 매핑 테이블이다. 주문 제출 시 `register(order_id, account_id, bot_id, symbol)`로 등록하고, 대사 시 `get_bot_id(order_id, account_id)`로 조회한다.

**SQLite 스키마**:
```sql
CREATE TABLE IF NOT EXISTS order_registry (
    order_id    TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL,
    bot_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_order_registry_bot
    ON order_registry(bot_id);
CREATE INDEX IF NOT EXISTS idx_order_registry_account
    ON order_registry(account_id);
CREATE INDEX IF NOT EXISTS idx_order_registry_account_bot
    ON order_registry(account_id, bot_id);
```

**마이그레이션**: 1.0 이전 fresh schema 기준으로 `account_id`는 필수값이며 fallback default를 두지 않는다. 기존 invalid dev DB 데이터 자동 보존/마이그레이션은 이 계약의 범위가 아니다.

**추가 메서드**:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `get_orders_by_bot` | `account_id: str`, `bot_id: str` | `list[dict]` | 특정 계좌 안에서 봇의 모든 주문 조회 |
| `remove` | `order_id: str`, `account_id: str` | `None` | 특정 계좌의 매핑 삭제 |

**등록 시점**: BrokerAdapter가 주문을 증권사에 제출하고 order_id를 받은 직후, OrderSubmittedEvent 발행 전에 등록한다. 또는 OrderSubmittedEvent를 구독하여 자동 등록한다.

**근거**:
- 브로커 API는 계좌 단위로만 데이터를 제공 — 봇 구분 정보 없음
- order_id → bot_id 매핑이 있어야 체결 이력을 정확한 봇에 귀속 가능
- 대사 시 "이 체결은 어느 봇의 것인가"를 판단하는 유일한 방법
- `account_id` 컬럼으로 멀티 계좌 환경에서 주문이 어느 계좌에서 발생했는지 추적

### ReconcileScheduler — 주기적 대사

> **구현 완료** — `src/ante/broker/scheduler.py`에 `ReconcileScheduler`로 구현되었다.

구현: `src/ante/broker/scheduler.py`

ReconcileScheduler는 `PositionReconciler`(Trade 모듈), `BrokerAdapter`(실제 잔고 조회), `BotManager`(활성 봇 목록), `EventBus`를 positional 인자로 주입받는다. 추가로 keyword-only 인자를 받는다:

- `broker_account_id`(필수): 이 스케줄러 인스턴스가 바인딩된 broker 계좌의 account_id. 빈 값이면 `ValueError`. `run_once()`는 이 account_id에 일치하는 봇만 대사 대상으로 삼고, 다른 계좌의 봇은 명시적으로 skip한다(SPLIT-1 단일 broker 바인딩 가드). multi-broker pool은 SPLIT-3에서 도입한다(`src/ante/main.py`의 `_init_reconcile_scheduler`가 활성 broker별 스케줄러를 생성·관리).
- `interval_seconds`(기본 `DEFAULT_INTERVAL_SECONDS` = 1800초 = 30분): 대사 반복 주기.
- `skip_initial_external_buy`(기본 `False`): True면 `start()`의 **기동 즉시 1회 대사에서만** "외부 매수" 분류 보정을 건너뛴다(이후 주기 대사는 정상 처리). 단일봇+running 보정 경로에만 적용된다.

`start()`는 시작 즉시 1회 대사(`run_once(skip_external_buy=self._skip_initial_external_buy)`)를 수행한 뒤 `interval_seconds` 주기로 대사 루프를 돈다. 불일치 감지 시 로그 경고와 함께 `NotificationEvent`를 발행한다.

**`run_once()` 라우팅 (`bot_count==1` vs `2+`, normative):** `run_once()`는 자기
`broker_account_id` 계좌의 broker 총합을 1회 조회한 뒤, **봇 귀속 ambiguity(status 무관 봇
count)** 와 **correction 실행 범위(running 봇)** 를 분리해 분기한다(#2118/#2119/#2270). 과거
스펙의 "활성(running) 봇만 대사하는 단일 경로" 기술은 stale 이며, 실제 라우팅은 다음과 같다:

| 계좌 봇 수(status 무관) | 봇 상태 | 동작 |
|---|---|---|
| 1봇 | `running` | `reconcile(dry_run=False)` — self-check/skip_external_buy/external-buy 분류 그대로 보정(#1946/#1950). 단, **미귀속 보유(internal_qty==0 && capacity==0)는 detect-only** 로 보정 제외([../trade/03-07-position-reconciler.md](../trade/03-07-position-reconciler.md), #2352). |
| 1봇 | `stopped`/`error`(미-running) | `reconcile(dry_run=True)` detect-only — scheduler 가 비활성 봇을 자동 보정하지 않는다(lifecycle 범위 보존, #2118 v4). |
| 2+봇 | (무관) | `detect_account_level` — `correct_position` 미호출. 계좌 총합 vs 전 봇 합산 비교로 #2118/#2120 false external-buy 제거. bot-scoped `PositionMismatchEvent`/`ReconcileEvent` 대신 account-scoped `NotificationEvent` 만 발행. |

ambiguity 판정 count 는 **status 무관**이다(#2119). 즉 `stopped`/`error` 봇도 count 에
포함되므로, 2+봇이면 일부만 running 이어도 detect-only 로 귀결된다. 다른 계좌의 봇과
`account_id` 누락 봇은 count 에서 제외된다(WARNING). 수동 대사(IPC `broker reconcile`)도
동일한 count 분기를 쓰되, user-initiated 라 봇 상태와 무관하게 단일봇 귀속이 자명하므로
`dry_run = not fix` 로 동작한다([../ipc/ipc.md](../ipc/ipc.md) Broker 절).

**#1946 fill 복구 barrier**: 서버 기동 시(`src/ante/main.py`) 각 계좌의 `FillReconcileScheduler.catch_up_once()`가 await 완료된 뒤에야 `ReconcileScheduler.start()`가 호출된다. fill 복구가 position 대사에 선행해야 미복구 ante 체결이 "외부 매수"로 오분류되지 않기 때문이다. fill 카치업에 **실패한** 계좌(`s.fill_catch_up_failed_accounts`)는 `skip_initial_external_buy=True`로 생성되어, 그 계좌의 기동 즉시 1회 대사에서만 external-buy 분류 보정을 건너뛴다.

### 대사 실행 시점

| 시점 | 트리거 | 목적 |
|------|--------|------|
| 봇 시작 시 | `BotManager.start_bot()` | 시스템 재시작 후 누락 체결 복구 |
| 주기적 (30분) | `ReconcileScheduler` | 운영 중 데이터 드리프트 감지 |
| 수동 요청 | CLI `ante broker reconcile --account <id> [--fix]` | 사용자가 의심 시 즉시 확인 |

수동 대사는 런타임 IPC로 서버 프로세스의 `PositionReconciler`와 BrokerAdapter를
사용한다. 서버 밖에서 별도 BrokerAdapter를 직접 생성해 대사하면 서버가 보유한
연결 상태, circuit breaker, TradeService 인메모리 상태와 어긋날 수 있다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
