# Trade 모듈 세부 설계 - 설계 결정 - TradeRecorder — 이벤트 기반 자동 기록

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# TradeRecorder — 이벤트 기반 자동 기록

구현: `src/ante/trade/recorder.py` 참조

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + exchange 컬럼 마이그레이션 |
| `subscribe` | `eventbus: EventBus` | `None` | 이벤트 구독 등록. 시스템 초기화 시 호출 |
| `get_trades` | `account_id: str \| None`, `bot_id: str \| None`, `strategy_id: str \| None`, `symbol: str \| None`, `status: TradeStatus \| None`, `from_date: datetime \| None`, `to_date: datetime \| None`, `limit: int = 100`, `offset: int = 0` | `list[TradeRecord]` | 거래 기록 조회. 다양한 필터 지원 |
| `save` | `record: TradeRecord` | `None` | 거래 기록 저장 (Reconciler용 public wrapper) |
| `save_adjustment` | `bot_id: str`, `symbol: str`, `old_quantity: float`, `new_quantity: float`, `reason: str` | `None` | 대사 보정 이력 기록 |

**설계 근거**:

1. **이벤트 구독 방식 (EventBus 자동 기록)**
   - Bot이 직접 기록하지 않음 — 관심사 분리
   - Bot은 전략 실행에 집중, 기록은 TradeRecorder가 전담
   - 체결뿐 아니라 거부/실패/취소도 기록 — 전략 효과 분석에 "시도했으나 실패한" 주문도 필요

2. **priority=10 (낮은 우선순위)**
   - 주문 흐름 핸들러(RuleEngine, Treasury 등)보다 낮은 우선순위
   - 기록은 주문 처리가 끝난 후 수행

3. **조회 시 필터 조합**
   - 봇별, 전략별, 종목별, 상태별, 기간별 필터링
   - 웹 대시보드에서 다양한 관점의 조회 지원
   - 페이지네이션(limit/offset) 지원
