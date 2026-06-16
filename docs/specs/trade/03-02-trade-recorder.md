# Trade 모듈 세부 설계 - 설계 결정 - TradeRecorder — 이벤트 기반 자동 기록

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# TradeRecorder — 이벤트 기반 자동 기록

구현: `src/ante/trade/recorder.py` 참조

> **체결(fill) 권위 일원화 (#1946)**: `_on_filled`는 더 이상 fill 경로의 포지션을
> 갱신하지 않는다. fill의 durable 적용(`TradeRecord` + `positions`)은 **FillApplier
> 단일 권위자**(단일 트랜잭션)가 수행해 스트림+폴 이중 경로의 이중 적용을 방지한다.
> TradeRecorder는 rejected/failed/cancelled 등 비-fill 상태 기록과 체결 알림을
> 유지한다. 상세: [03-08-fill-recovery.md](03-08-fill-recovery.md).

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + exchange 컬럼 마이그레이션 |
| `subscribe` | `eventbus: EventBus` | `None` | 이벤트 구독 등록. 시스템 초기화 시 호출 |
| `get_trades` | `account_id: str \| None`, `bot_id: str \| None`, `strategy_id: str \| None`, `symbol: str \| None`, `status: TradeStatus \| None`, `from_date: datetime \| None`, `to_date: datetime \| None`, `limit: int = 100`, `offset: int = 0` | `list[TradeRecord]` | 거래 기록 조회. 다양한 필터 지원 |
| `save` | `record: TradeRecord` | `None` | 거래 기록 저장 (Reconciler용 public wrapper) |
| `save_adjustment` | `bot_id: str`, `symbol: str`, `old_quantity: float`, `new_quantity: float`, `reason: str` | `None` | 대사 보정 이력 기록 |

`save_adjustment`는 `timestamp`를 `datetime.now(UTC).isoformat()`(UTC-aware ISO 8601)
으로 저장한다 — `save`/`_save`와 동일 포맷이며 `trades.timestamp` 단일 포맷
invariant([03-05-sqlite-schema.md](03-05-sqlite-schema.md))를 따른다.

**설계 근거**:

1. **이벤트 구독 방식 (EventBus 자동 기록)**
   - Bot이 직접 기록하지 않음 — 관심사 분리
   - Bot은 전략 실행에 집중, 기록은 TradeRecorder가 전담
   - 체결뿐 아니라 거부/실패/취소/정정완료도 기록 — 전략 효과 분석에 "시도했으나 실패한" 주문도 필요. 정정 완료(`OrderModifyExecutedEvent`, v1=price-only)는 `MODIFIED` 별도 row(`_on_modified`, trade_id PK 멱등, price=신규 정정가)로 기록한다(#2391)

2. **priority=10 (낮은 우선순위)**
   - 주문 흐름 핸들러(RuleEngine, Treasury 등)보다 낮은 우선순위
   - 기록은 주문 처리가 끝난 후 수행

3. **조회 시 필터 조합**
   - 봇별, 전략별, 종목별, 상태별, 기간별 필터링
   - CLI/리포트에서 다양한 관점의 조회 지원
   - 페이지네이션(limit/offset) 지원
