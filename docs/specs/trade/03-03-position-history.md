# Trade 모듈 세부 설계 - 설계 결정 - PositionHistory — 포지션 변동 추적

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# PositionHistory — 포지션 변동 추적

구현: `src/ante/trade/position.py` 참조

#### PositionSnapshot 필드

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `account_id` | `str` | — | 계좌 ID |
| `bot_id` | `str` | — | 봇 ID |
| `symbol` | `str` | — | 종목 코드 |
| `quantity` | `float` | — | 보유 수량 (0이면 청산 완료) |
| `avg_entry_price` | `float` | — | 평균 매입 가격 |
| `realized_pnl` | `float` | `0.0` | 실현 손익 (누적) |
| `updated_at` | `str` | `""` | 마지막 갱신 시각 |
| `exchange` | `str` | `"KRX"` | 거래소 코드 |

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `initialize` | — | `None` | 스키마 생성 + exchange 컬럼 마이그레이션 + 캐시 워밍 |
| `on_trade` | `record: TradeRecord` | `None` | 체결 기록을 반영하여 포지션 상태 갱신 |
| `get_positions` | `bot_id: str`, `include_closed: bool = False` | `list[PositionSnapshot]` | 봇의 현재 포지션 조회. include_closed=True이면 청산 완료 포지션도 포함 |
| `get_all_positions` | — | `list[PositionSnapshot]` | 전체 봇의 모든 포지션 조회 (대사 계좌 합산 검증용) |
| `get_positions_sync` | `bot_id: str` | `list[PositionSnapshot]` | 봇의 현재 포지션 동기 조회 (인메모리 캐시). PortfolioView용 |
| `get_current` | `bot_id: str`, `symbol: str` | `dict` | 현재 포지션 조회. 없으면 빈 포지션 반환 |
| `get_history` | `bot_id: str`, `symbol: str \| None` | `list[dict]` | 포지션 변동 이력 조회 |
| `force_update` | `bot_id: str`, `symbol: str`, `quantity: float`, `avg_entry_price: float` | `None` | Reconciler 전용: 포지션을 브로커 기준 값으로 강제 덮어쓰기 |

**근거**:
- 체결 기록(TradeRecord)과 포지션 상태는 별도 관리 — 체결은 개별 이벤트, 포지션은 누적 상태
- 평균 매입 가격(avg_entry_price) 추적으로 실현 손익 정확 계산
- 포지션 변동 이력으로 "진입 → 추가 매수 → 일부 청산 → 전량 청산" 전체 경로 추적
