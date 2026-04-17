# Trade 모듈 세부 설계 - 설계 결정 - TradeService — 통합 인터페이스

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# TradeService — 통합 인터페이스

구현: `src/ante/trade/service.py` 참조

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `get_trades` | `account_id: str \| None`, `bot_id: str \| None`, `strategy_id: str \| None`, `symbol: str \| None`, `status: TradeStatus \| None`, `from_date: datetime \| None`, `to_date: datetime \| None`, `limit: int = 100`, `offset: int = 0` | `list[TradeRecord]` | 거래 기록 조회 |
| `get_positions` | `bot_id: str`, `include_closed: bool = False` | `list[PositionSnapshot]` | 봇의 현재 포지션 조회 |
| `get_all_positions` | — | `list[PositionSnapshot]` | 전체 봇의 모든 포지션 조회 (대사 계좌 합산 검증용) |
| `get_position_history` | `bot_id: str`, `symbol: str \| None` | `list[dict]` | 포지션 변동 이력 조회 |
| `get_performance` | `account_id: str`, `bot_id: str \| None`, `strategy_id: str \| None`, `from_date: datetime \| None`, `to_date: datetime \| None` | `PerformanceMetrics` | 성과 지표 조회. account_id 필수 |
| `get_summary` | `bot_id: str` | `dict` | 봇 요약 정보 (현재 포지션 + 성과 지표 + 최근 거래). 대시보드용 |
| `correct_position` | `bot_id: str`, `symbol: str`, `quantity: float`, `avg_price: float \| None`, `reason: str = ""` | `dict` | 포지션을 브로커 기준으로 강제 보정. Reconciler가 호출. 보정 내역(old/new 값) 반환 |
| `insert_adjustment` | `bot_id: str`, `strategy_id: str`, `fill: dict`, `reason: str = "reconciliation"` | `None` | 누락된 체결 기록을 보정 추가. status='adjusted'로 표시하여 일반 체결과 구분 |

**근거**:
- 파사드 패턴 — 외부에서는 TradeService만 사용, 내부 구현(Recorder/History/Tracker) 은닉
- Web API와 CLI가 동일한 인터페이스로 접근
- `get_summary()`: 대시보드에서 봇 상세 페이지 렌더링 시 한 번의 호출로 필요 데이터 수집
- `correct_position()`, `insert_adjustment()`: Reconciler 전용 보정 API — 보정 이력을 기록하여 감사 추적 가능
