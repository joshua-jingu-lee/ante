# 전략과 성과

> ⚠️ 이 문서는 이 화면을 이용하는 사용자의 시나리오와 행동에 따른 제약 조건 및 기대 결과를 기술 합니다.
> 이 문서와 목업화면을 바탕으로 기획 의도를 파악해서 프론트 화면과 기능을 구현해야 합니다.

## 개요

전략과 성과는 운영자가 **어떤 전략이 돈을 벌고 있나**를 파악하는 화면이다.
전략 목록 조회, 전략 상세(정보·파라미터·성과 지표·에쿼티 커브), 기간별 성과 분석, 개별 거래 내역을 제공한다.

**목업**: [strategies.html](../mockups/strategies.html) · [strategy-detail.html](../mockups/strategy-detail.html) · [performance.html](../mockups/performance.html) · [trades.html](../mockups/trades.html)

## 유저스토리

| ID | 스토리 | 완료 조건 |
|----|--------|----------|
| S-1 | 운영자가 모든 전략의 현황을 한눈에 파악한다 | 제목(전략명+버전), 제출자, 상태, 실행 봇, 누적 수익률, 백테스트 수익률이 포함된 테이블 + 페이지네이션 |
| S-2 | 운영자가 상태별로 전략을 필터링하고 제목으로 검색한다 | 전체/운용중/대기/비활성/보관 탭 필터 + 제목 검색 |
| S-3 | 운영자가 전략의 기본 정보와 파라미터를 확인한다 | 전략 정보 카드(제출자, 버전, 설명, 투자 근거, 리스크) + 파라미터 카드 |
| S-4 | 운영자가 전략의 에쿼티 커브를 확인한다 | 자산 추이 차트 (기간 선택: 1주/1개월/3개월/전체) |
| S-5 | 운영자가 전략의 핵심 성과 지표를 확인한다 | 12개 지표 카드 (순손익, 거래 수, 승률, 활성 거래일, 수익 팩터, Sharpe, MDD, 수수료, 평균 수익/손실, 실현/미실현 손익) + 힌트 툴팁 |
| S-6 | 운영자가 전략 상세에서 기간별 성과 미리보기와 최근 거래를 확인한다 | 2열 레이아웃: 기간별 성과 카드(일별/주별/월별 탭 + "더 보기 →") + 최근 거래 카드("전체 보기 →") |
| S-7 | 운영자가 기간별 성과를 분석한다 | 기간별 성과 페이지에서 전략·기간·날짜 필터 → 일별/주별/월별 성과 테이블 + 요약 카드 |
| S-8 | 운영자가 개별 거래 내역을 확인한다 | 거래 내역 페이지에서 전략·매매방향·날짜 필터 → 거래 테이블 (시각, 종목, 매매, 수량, 단가, 금액, 수수료, 손익) + 페이지네이션 |

---

### S-1: 전략 목록

**기획 의도**: 운영자가 등록된 모든 전략의 상태와 성과를 한눈에 파악한다.

**화면 구성** — 레이아웃은 [목업](../mockups/strategies.html) 참조

| 컬럼 | 설명 | key |
|------|------|-----|
| 제목 | 전략명 + 버전 (예: `모멘텀 돌파 전략 v2`) | `strategy.name`, `strategy.version` |
| 제출자 | Agent 이름 + ID | `strategy.author_name`, `strategy.author_id` |
| 상태 | 채택 / 대기 / 보관 뱃지 (아래 상태 매핑 참조) | `strategy.status` |
| 실행 봇 | 해당 전략을 사용 중인 봇, 없으면 `-` | `bot.bot_id` |
| 누적 수익률 | (실현 + 미실현 손익) / 배정예산 × 100 (positive/negative, bold). 실거래 기반 | `performance.net_pnl`, `budget.allocated` |
| 백테스트 수익률 | 가장 최근 백테스트 결과의 누적 수익률 (positive/negative). 백테스트 미실행 시 `-` | `backtest.total_return` |

**상태 매핑** — 스펙: [strategy.md StrategyStatus](../../specs/strategy/strategy.md)

| 화면 표시 | `StrategyStatus` | 뱃지 색상 | 설명 |
|-----------|-----------------|----------|------|
| 채택 | `ADOPTED` | positive | 결재 승인, 봇 배정 가능 |
| 대기 | `REGISTERED` | warning | 검증 통과·등록됨, 결재 대기 |
| 보관 | `ARCHIVED` | muted (outline) | 폐기·보관 처리됨 |

**상태 전환** — 스펙: [strategy.md StrategyStatus](../../specs/strategy/strategy.md)

```
REGISTERED ──결재 승인──▷ ADOPTED ──폐기──▷ ARCHIVED
     └──────────────────폐기──────────────▷ ARCHIVED
```

| 전환 | 트리거 | 대시보드 진입점 |
|------|--------|----------------|
| REGISTERED → ADOPTED | `strategy_adopt` 결재 승인 | 결재함에서 승인 또는 텔레그램 `/approve` |
| REGISTERED → ARCHIVED | `strategy_retire` 결재 승인 또는 운영자가 보관 | 전략 상세 헤더 "보관" 버튼, 결재함 |
| ADOPTED → ARCHIVED | `strategy_retire` 결재 승인 또는 운영자가 보관 | 전략 상세 헤더 "보관" 버튼, 결재함 |

> 상태 전환은 사용자가 명시적으로 수행한다. 동일 name의 새 version 등록 시 이전 version의 상태를 자동 변경하지 않는다.
> 봇은 전략 배정 시 전략 파일을 복제(snapshot)하여 독립 관리하므로, 전략이 ARCHIVED되어도 운영 중인 봇에는 영향이 없다.

**전략 상세 헤더 — 상태별 액션 버튼**

| 상태 | 버튼 |
|------|------|
| REGISTERED (대기) | 보관 (outline, muted) |
| ADOPTED (채택) | 보관 (outline, muted) |
| ARCHIVED (보관) | — (액션 없음) |

**인터랙션**
- 행 클릭: 해당 전략 상세 페이지로 이동

**동작 규칙**
- 페이지네이션: 페이지당 최대 15행 표시, "N건 중 M-K" 형식으로 현재 위치 표시, 이전/다음 버튼 제공
- 해당 전략을 사용 중인 봇이 없으면 실행 봇 컬럼에 `-` (muted) 표시
- 누적 수익률이 없는 대기 전략은 `-` (muted) 표시

---

### S-2: 상태 필터 및 제목 검색

**기획 의도**: 운영자가 관심 있는 상태의 전략만 빠르게 조회하거나, 제목 키워드로 특정 전략을 빠르게 찾을 수 있다.

**화면 구성** — 테이블 상단 필터 바

| 필터 | 유형 | 옵션 |
|------|------|------|
| 상태 | 탭 버튼 | 전체 · 운용중 · 대기 · 비활성 · 보관 |
| 제목 검색 | 텍스트 입력 | 제목 키워드 검색 |

**동작 규칙**
- 필터 초기값은 "전체"이다
- 탭 클릭 시 해당 상태의 전략만 필터링하여 테이블 갱신
- 필터 변경 시 페이지네이션 1페이지로 리셋
- 필터 결과가 0건이면 빈 상태 메시지를 표시한다

---

### S-3: 전략 정보 · 파라미터

**기획 의도**: 운영자가 특정 전략의 기본 정보와 투자 로직 설정을 확인한다.

**화면 구성** — [전략 상세 목업](../mockups/strategy-detail.html) 참조, detail-grid 2열 레이아웃

#### 전략 정보 카드 (좌측)

**헤더**: 전략명 + 상태 뱃지 + 버전 + 실행 봇

| 필드 | 설명 | key |
|------|------|-----|
| 제출자 | Agent 이름 + ID | `strategy.author_name`, `strategy.author_id` |
| 버전 | 전략 버전 (예: `2.1.0`) | `strategy.version` |
| 설명 | 전략 요약 설명 (muted, 12px) | `strategy.description` |
| 투자 근거 | 전략의 투자 논거 (줄바꿈 보존, `white-space: pre-line`) | `strategy.rationale` |
| 리스크 | 전략의 위험 요인 (border-top 구분, 줄바꿈 보존) | `strategy.risks` |

#### 전략 파라미터 카드 (우측)

- `get_params()` 반환값을 key-value 형태로 표시 | `strategy.get_params()`
- `get_param_schema()` 반환값으로 각 파라미터 설명 표시 | `strategy.get_param_schema()`
- key: `info-label`, value: `text-mono` + 설명 (muted, 11px)

---

### S-4: 자산 추이 차트 (Equity Curve)

**기획 의도**: 운영자가 전략의 자산 가치 변화를 시각적으로 파악한다.

**화면 구성** — 전략 성과 영역 상단

- 카드 헤더: "자산 추이 (Equity Curve)" + 기간 선택 버튼
- Area Chart로 전략 자산 가치 변화 표시

**데이터 소스**: `GET /api/strategies/{id}/performance` → `equity_curve[]` (timestamp, equity, balance) — 실거래 기반

**기간 선택**

| 버튼 | 설명 |
|------|------|
| 1주 | 최근 1주 |
| 1개월 | 최근 1개월 (기본 선택) |
| 3개월 | 최근 3개월 |
| 전체 | 전체 기간 |

**동작 규칙**
- API 호출: `start_date`, `end_date` 파라미터로 기간 지정
- 기간 버튼 클릭 시 차트 갱신
- 호버 시 해당 날짜의 자산 가치 툴팁 표시

---

### S-5: 성과 지표

**기획 의도**: 운영자가 전략의 핵심 성과 지표를 통해 전략의 품질을 판단한다.

**화면 구성** — 3행 × 4열 stat-card 그리드

**1행**

| 지표 | 설명 | key | 힌트 |
|------|------|-----|------|
| 순손익 | 실현 + 미실현 손익 합계. 금액: `performance.total_pnl` + `position.unrealized_pnl`, 수익률: (`total_pnl` + `unrealized_pnl`) / `budget.allocated` × 100 | `performance.total_pnl`, `position.unrealized_pnl`, `budget.allocated` | "실현 손익 + 미실현 손익의 합계" |
| 총 거래 수 | 전체 거래 건수 | `performance.total_trades` | — |
| 승률 | 수익 거래 / 전체 거래 × 100 | `performance.win_rate` | "수익을 낸 거래 수 / 전체 거래 수" |
| 활성 거래일 | 실제 매매가 발생한 날 수 | `performance.active_days` | "실제 매매가 발생한 날의 수" |

**2행**

| 지표 | 설명 | key | 힌트 |
|------|------|-----|------|
| 수익 팩터 | 총 수익 / 총 손실 | `performance.profit_factor` | "총 수익 / 총 손실. 1 이상이면 수익 우위" |
| Sharpe Ratio | 위험 대비 수익 효율 | `performance.sharpe_ratio` | "위험 대비 수익 효율. 높을수록 안정적인 수익" |
| MDD | 최대 낙폭 (% + 금액) | `performance.max_drawdown`, `performance.max_drawdown_amount` | "최대 낙폭. 고점 대비 가장 크게 떨어진 비율" |
| 수수료 합계 | 전체 거래 수수료 합계 (muted) | `performance.total_commission` | — |

**3행**

| 지표 | 설명 | key | 힌트 |
|------|------|-----|------|
| 평균 수익 | 수익 거래의 평균 이익 금액 | `performance.avg_profit` | "수익 거래의 평균 이익 금액" |
| 평균 손실 | 손실 거래의 평균 손실 금액 | `performance.avg_loss` | "손실 거래의 평균 손실 금액" |
| 실현 손익 | 매도 완료 거래의 확정 손익 | `performance.total_pnl` | "매도 완료된 거래의 확정 손익" |
| 미실현 손익 | 보유 중 종목의 평가 손익 | `position.unrealized_pnl` | "보유 중인 종목의 평가 손익 (미확정)" |

**동작 규칙**
- 손익·수익률 양수는 positive, 음수는 negative 색상
- MDD는 negative 색상으로 고정
- 힌트가 있는 지표는 `?` 아이콘 표시, 호버 시 툴팁

---

### S-6: 기간별 성과 미리보기 · 최근 거래

**기획 의도**: 운영자가 전략 상세 페이지에서 기간별 성과 요약과 최근 거래를 빠르게 확인하고, 상세 페이지로 진입한다.

**화면 구성** — [전략 상세 목업](../mockups/strategy-detail.html) 참조, 성과 지표 하단 2열 레이아웃

#### 기간별 성과 카드 (좌측)

- 카드 헤더: "기간별 성과" + "더 보기 →" 링크 (performance.html로 이동)
- 일별/주별/월별 탭 전환 (기본: 월별)

| 컬럼 | 설명 | key |
|------|------|-----|
| 기간 | 일자·주간·월 (탭에 따라 변경) | `daily_summary.date`, `monthly_summary.year`+`month` |
| 거래 수 | 해당 기간 거래 건수 | `daily_summary.trade_count`, `monthly_summary.trade_count` |
| 승률 | 해당 기간 승률 | `daily_summary.win_rate`, `monthly_summary.win_rate` |
| 실현 손익 | 해당 기간 실현 손익 (positive/negative) | `daily_summary.realized_pnl`, `monthly_summary.realized_pnl` |

#### 최근 거래 카드 (우측)

- 카드 헤더: "최근 거래" + "전체 보기 →" 링크 (trades.html로 이동)
- 최근 거래 12건을 간략 테이블로 표시

| 컬럼 | 설명 | key |
|------|------|-----|
| 시각 | 체결 시각 (`MM-DD HH:mm`, mono) | `trade.timestamp` |
| 종목 | 종목명 | `trade.symbol_name` |
| 매매 | 매수(negative 뱃지) / 매도(positive 뱃지) | `trade.side` |
| 수량 | 체결 수량 | `trade.quantity` |
| 단가 | 체결 단가 | `trade.price` |
| 손익 | 매도 시 실현 손익 (positive/negative), 매수 시 `—` (muted) | `position.realized_pnl` |

**동작 규칙**
- 기간별 성과 탭 클릭 시 테이블 전환
- "더 보기 →" 클릭 시 해당 전략이 선택된 performance.html로 이동
- "전체 보기 →" 클릭 시 해당 전략이 선택된 trades.html로 이동

---

### S-7: 기간별 성과

**기획 의도**: 운영자가 전략의 일별/주별/월별 성과를 분석한다.

**화면 구성** — [기간별 성과 목업](../mockups/performance.html) 참조

#### 진입 경로
- 전략 상세 → 기간별 성과 카드 "더 보기 →" 링크
- 전략 상세 내에서도 일별/주별/월별 탭으로 최근 데이터 미리보기 가능

#### 필터 바

| 필터 | 설명 |
|------|------|
| 전략 | 전략명 검색 (datalist 자동완성) |
| 기간 | 일별 / 주별 / 월별 (기본: 월별) |
| 시작일 | 조회 시작일 |
| 종료일 | 조회 종료일 |

#### 요약 카드 (4열)

| 지표 | 설명 | key |
|------|------|-----|
| 조회 기간 실현 손익 | 필터 기간 내 실현 손익 합계 | `performance.total_pnl` |
| 총 거래 수 | 필터 기간 내 전체 거래 건수 | `performance.total_trades` |
| 승률 | 필터 기간 내 승률 | `performance.win_rate` |
| 수익 팩터 | 필터 기간 내 수익 팩터 | `performance.profit_factor` |

#### 성과 테이블

| 컬럼 | 일별 | 주별 | 월별 | key |
|------|------|------|------|-----|
| 기간 | 일자 (`YYYY-MM-DD`) | 주간 (`MM/DD ~ MM/DD`) | 월 (`YYYY-MM`) | `daily_summary.date`, `monthly_summary.year`+`month` |
| 거래 수 | 해당 기간 거래 건수 | 〃 | 〃 | `daily_summary.trade_count`, `monthly_summary.trade_count` |
| 승률 | 해당 기간 승률 | 〃 | 〃 | `daily_summary.win_rate`, `monthly_summary.win_rate` |
| 실현 손익 | 해당 기간 실현 손익 (positive/negative) | 〃 | 〃 | `daily_summary.realized_pnl`, `monthly_summary.realized_pnl` |

**동작 규칙**
- 기간 선택 변경 시 테이블 전환 (일별은 페이지네이션 포함)
- "조회" 버튼 클릭 시 필터 적용 → 요약 카드 + 테이블 갱신

---

### S-8: 거래 내역

**기획 의도**: 운영자가 전략의 개별 거래를 상세하게 확인한다.

**화면 구성** — [거래 내역 목업](../mockups/trades.html) 참조

#### 진입 경로
- 전략 상세 → 최근 거래 카드 "전체 보기 →" 링크

#### 필터 바

| 필터 | 설명 |
|------|------|
| 전략 | 전략명 검색 (datalist 자동완성) |
| 매매 | 전체 / 매수 / 매도 |
| 시작일 | 조회 시작일 |
| 종료일 | 조회 종료일 |

#### 거래 테이블

| 컬럼 | 설명 | key |
|------|------|-----|
| 시각 | 체결 시각 (`YYYY-MM-DD HH:mm`, mono) | `trade.timestamp` |
| 종목 | 종목명 (종목코드) | `trade.symbol_name`, `trade.symbol` |
| 매매 | 매수(negative 뱃지) / 매도(positive 뱃지) | `trade.side` |
| 수량 | 체결 수량 | `trade.quantity` |
| 단가 | 체결 단가 | `trade.price` |
| 금액 | 체결 금액 (수량 × 단가) | `trade.quantity` × `trade.price` |
| 수수료 | 해당 거래 수수료 (muted) | `trade.commission` |
| 손익 | 매도 시 실현 손익 (positive/negative), 매수 시 `—` (muted) | `position.realized_pnl` |

**동작 규칙**
- 페이지네이션: 페이지당 15건, 하단에 총 건수 + 페이지 버튼
- "조회" 버튼 클릭 시 필터 적용 → 테이블 갱신
- 매수 거래의 손익은 `—`으로 표시 (미확정)
