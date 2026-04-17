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

복수 봇이 같은 계좌에서 거래할 때, 브로커가 반환하는 order_id가 어느 봇의 주문인지 추적하기 위한 매핑 테이블이다. 주문 제출 시 `register(order_id, bot_id, symbol)`로 등록하고, 대사 시 `get_bot_id(order_id)`로 조회한다.

**SQLite 스키마**:
```sql
CREATE TABLE IF NOT EXISTS order_registry (
    order_id    TEXT PRIMARY KEY,
    bot_id      TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    account_id  TEXT DEFAULT 'default',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_order_registry_bot
    ON order_registry(bot_id);
CREATE INDEX IF NOT EXISTS idx_order_registry_account
    ON order_registry(account_id);
```

**마이그레이션**: `initialize()` 시 `exchange TEXT DEFAULT 'KRX'` 컬럼 자동 추가 (v0.2). `account_id TEXT DEFAULT 'default'` 컬럼 자동 추가 (v0.3).

**추가 메서드**:

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `get_orders_by_bot` | `bot_id: str` | `list[dict]` | 봇의 모든 주문 조회 |
| `remove` | `order_id: str` | `None` | 매핑 삭제 |

**등록 시점**: BrokerAdapter가 주문을 증권사에 제출하고 order_id를 받은 직후, OrderSubmittedEvent 발행 전에 등록한다. 또는 OrderSubmittedEvent를 구독하여 자동 등록한다.

**근거**:
- 브로커 API는 계좌 단위로만 데이터를 제공 — 봇 구분 정보 없음
- order_id → bot_id 매핑이 있어야 체결 이력을 정확한 봇에 귀속 가능
- 대사 시 "이 체결은 어느 봇의 것인가"를 판단하는 유일한 방법
- `account_id` 컬럼으로 멀티 계좌 환경에서 주문이 어느 계좌에서 발생했는지 추적

### ReconcileScheduler — 주기적 대사

> ⏳ **미구현** — 아래 설계는 확정되었으나, 코드가 아직 작성되지 않았다.

구현 예정: `src/ante/broker/scheduler.py`

ReconcileScheduler는 `PositionReconciler`(Trade 모듈), `BotManager`, `EventBus`를 주입받아, 설정된 간격(기본 30분)으로 모든 활성 봇의 대사를 수행한다. 불일치 감지 시 로그 경고와 함께 `NotificationEvent`를 발행한다.

### 대사 실행 시점

| 시점 | 트리거 | 목적 |
|------|--------|------|
| 봇 시작 시 | `BotManager.start_bot()` | 시스템 재시작 후 누락 체결 복구 |
| 주기적 (30분) | `ReconcileScheduler` | 운영 중 데이터 드리프트 감지 |
| 수동 요청 | CLI `ante broker reconcile --bot <id>` | 사용자가 의심 시 즉시 확인 |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
