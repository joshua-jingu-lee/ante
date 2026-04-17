# Trade 모듈 세부 설계 - 설계 결정 - PerformanceTracker — 성과 지표 산출

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# PerformanceTracker — 성과 지표 산출

구현: `src/ante/trade/performance.py` 참조

#### PerformanceMetrics 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| **기본 지표** | | |
| `total_trades` | `int` | 총 거래 수 |
| `winning_trades` | `int` | 수익 거래 수 |
| `losing_trades` | `int` | 손실 거래 수 |
| `win_rate` | `float` | 승률 (winning / total) |
| **수익 지표** | | |
| `total_pnl` | `float` | 총 실현 손익 |
| `total_commission` | `float` | 총 수수료 |
| `net_pnl` | `float` | 순 손익 (total_pnl - total_commission) |
| `avg_profit` | `float` | 평균 수익 (수익 거래만) |
| `avg_loss` | `float` | 평균 손실 (손실 거래만) |
| `profit_factor` | `float` | 수익 팩터 (총 수익 / 총 손실) |
| **리스크 지표** | | |
| `max_drawdown` | `float` | MDD — 고점 대비 최대 하락률 |
| `max_drawdown_amount` | `float` | MDD 금액 |
| `sharpe_ratio` | `float \| None` | 샤프 비율 (데이터 충분 시) |
| **기간 지표** | | |
| `first_trade_at` | `datetime \| None` | 첫 거래 시각 |
| `last_trade_at` | `datetime \| None` | 마지막 거래 시각 |
| `active_days` | `int` | 거래일 수 |

#### DailySummary 필드 (frozen dataclass)

| 필드 | 타입 | 설명 |
|------|------|------|
| `date` | `str` | 날짜 (YYYY-MM-DD) |
| `realized_pnl` | `float` | 일 실현 손익 |
| `trade_count` | `int` | 거래 수 |
| `win_rate` | `float` | 승률 |

#### MonthlySummary 필드 (frozen dataclass)

| 필드 | 타입 | 설명 |
|------|------|------|
| `year` | `int` | 연도 |
| `month` | `int` | 월 |
| `realized_pnl` | `float` | 월 실현 손익 |
| `trade_count` | `int` | 거래 수 |
| `win_rate` | `float` | 승률 |

#### WeeklySummary 필드 (frozen dataclass)

| 필드 | 타입 | 설명 |
|------|------|------|
| `week_start` | `str` | 주 시작일 (YYYY-MM-DD, 월요일) |
| `week_end` | `str` | 주 종료일 (YYYY-MM-DD, 일요일) |
| `realized_pnl` | `float` | 주간 실현 손익 |
| `trade_count` | `int` | 거래 수 |
| `win_rate` | `float` | 승률 |

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `calculate` | `account_id: str`, `bot_id: str \| None`, `strategy_id: str \| None`, `from_date: datetime \| None`, `to_date: datetime \| None` | `PerformanceMetrics` | 성과 지표 계산. account_id 필수, bot_id·strategy_id는 선택 필터 |
| `get_daily_summary` | `bot_id: str \| None`, `start_date: str \| None`, `end_date: str \| None` | `list[DailySummary]` | 일별 성과 집계. 날짜는 YYYY-MM-DD 형식 |
| `get_monthly_summary` | `bot_id: str \| None`, `year: int \| None` | `list[MonthlySummary]` | 월별 성과 집계 |
| `get_weekly_summary` | `bot_id: str \| None` | `list[WeeklySummary]` | 주별 성과 집계. ISO 주 단위(월요일 시작) |

**설계 근거**:

1. **조회 시 계산 (캐싱 없음)**
   - 거래 빈도가 높지 않음 (분 단위, 일 수십~수백 건 수준)
   - SQLite 쿼리로 충분한 성능 — N100 환경에서도 수만 건 수준은 밀리초 내 처리
   - 캐싱 도입 시 무효화 로직이 복잡해짐 → YAGNI(You Aren't Gonna Need It) 원칙
   - 향후 성능 문제 발생 시 결과 캐싱 또는 사전 집계 테이블 추가

2. **핵심 지표 선정**
   - 승률(win_rate): 전략의 방향성 정확도
   - 수익 팩터(profit_factor): 수익/손실 비율 — 1 초과면 기대값 양수
   - MDD: 리스크 관리의 핵심 지표
   - 샤프 비율: 리스크 대비 수익률 (데이터 충분 시에만 계산)
   - FreqTrade도 유사한 지표를 사용 (profit_total, winrate, max_drawdown 등)

3. **매도 거래 기준 승/패 판정**
   - 매수는 포지션 진입, 매도가 실현 손익을 확정
   - 매도 시 (체결가 - 평균매입가) × 수량으로 손익 계산
