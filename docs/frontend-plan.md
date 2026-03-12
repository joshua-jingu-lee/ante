# Ante Frontend 구현 계획

> React 기반 웹 대시보드 구현 계획서

## 1. 기술 스택

| 영역 | 선택 | 근거 |
|------|------|------|
| 프레임워크 | React 18 + TypeScript | D-008 결정, AI 코드 생성 품질 최고 |
| 빌드 도구 | Vite | 빠른 HMR, 경량 번들 |
| 차트 | TradingView Lightweight Charts | D-008 결정, 금융 특화 경량 차트 |
| UI 컴포넌트 | shadcn/ui + Tailwind CSS | 커스터마이징 용이, 번들 경량 |
| 상태 관리 | Tanstack Query (서버) + Zustand (클라이언트) | REST 캐싱 + WebSocket 상태 |
| 라우팅 | React Router v6 | 표준 SPA 라우팅 |
| HTTP | Axios | API Key 인터셉터, 에러 핸들링 |

**배포**: React 빌드 → `frontend/dist/` → FastAPI에서 정적 파일로 서빙
- 개발 머신/CI에서 빌드, 홈서버에는 빌드 결과만 배포
- N100 서버에 Node.js 불필요

## 2. 화면 구성

### 2.1 레이아웃

```
┌────────────────────────────────────────────────────┐
│  Header: Ante 로고 | 시스템 상태 표시등 | 설정     │
├─────────┬──────────────────────────────────────────┤
│         │                                          │
│ Sidebar │          메인 콘텐츠 영역                │
│  (네비) │                                          │
│         │                                          │
│ - 대시보드│                                          │
│ - 봇 관리│                                          │
│ - 거래내역│                                          │
│ - 자금관리│                                          │
│ - 리포트 │                                          │
│ - 데이터 │                                          │
│ - 설정   │                                          │
│         │                                          │
├─────────┴──────────────────────────────────────────┤
│  Toast: 실시간 알림 (체결, 오류, 시스템 경고)       │
└────────────────────────────────────────────────────┘
```

### 2.2 대시보드 (Dashboard)

시스템 전체 현황을 한눈에 보여주는 메인 화면.

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 시스템 상태 카드 | 거래 상태 (ACTIVE/HALTED), 버전, 업타임 |
| 봇 요약 카드 | 실행 중/중지된 봇 수, 전체 수익률 |
| 자금 요약 카드 | 총 잔고, 할당액, 미할당액, 예약액 |
| 포트폴리오 가치 차트 | 전체 자산 가치 추이 (Area Chart) |
| 최근 거래 테이블 | 최근 10건 체결 내역 (실시간 갱신) |
| 활성 봇 리스트 | 실행 중인 봇 상태 + 간략 성과 |

**API 의존성**: `/api/system/status`, `/api/bots` (신규), `/api/treasury/summary` (신규), `/api/trades` (신규)

### 2.3 봇 관리 (Bots)

#### 봇 목록 화면

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 봇 테이블 | ID, 전략명, 상태(실행/중지/오류), 봇 유형(실전/모의) |
| 상태 필터 | 전체 / 실행 중 / 중지됨 / 오류 |
| 봇 생성 버튼 | 봇 생성 모달 열기 |
| 빠른 제어 | 각 행에 시작/중지/삭제 버튼 |
| 실시간 갱신 | WebSocket으로 상태 변경 즉시 반영 |

#### 봇 상세 화면 (`/bots/:id`)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 봇 정보 헤더 | ID, 전략, 상태, 시작/중지 시각, 실행 간격 |
| 시작/중지 버튼 | 봇 제어 |
| 자산 추이 차트 | 봇 할당 자금의 가치 변화 (TradingView Area Chart) |
| 보유 포지션 | 종목, 수량, 평균 단가, 현재가, 평가 손익, 수익률 |
| 성과 지표 패널 | 총 거래 수, 승률, 수익 팩터, MDD, 실현 손익 |
| 최근 거래 | 해당 봇의 체결 내역 (필터링된 테이블) |
| 전략 파라미터 | 전략의 `get_params()` 결과 표시 |

#### 봇 생성 모달

| 입력 항목 | 설명 |
|-----------|------|
| 봇 ID | 고유 식별자 (영문+숫자) |
| 전략 선택 | 등록된 전략 드롭다운 (StrategyRegistry) |
| 봇 유형 | 실전투자 / 모의투자 토글 |
| 실행 간격 | 초 단위 (기본 60초) |
| 예산 할당 | 금액 입력 + 슬라이더 (미할당 잔고 범위) |
| 대상 종목 | 종목코드 다중 입력 (선택) |

**API 의존성**: `/api/bots` CRUD (신규), `/api/bots/:id/start`, `/api/bots/:id/stop`

### 2.4 거래 내역 (Trades)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 거래 테이블 | 일시, 봇ID, 종목, 매수/매도, 수량, 가격, 상태, 수수료, 사유 |
| 필터 | 봇 선택, 종목, 기간, 상태(체결/거부/취소) |
| 정렬 | 시간순(기본), 종목, 금액 |
| 페이지네이션 | 커서 기반 무한 스크롤 |
| 실시간 추가 | WebSocket `order_filled` 이벤트로 새 행 추가 |
| 거래 상세 | 행 클릭 → 주문ID, 브로커 주문ID, 이벤트 타임라인 |

**API 의존성**: `/api/trades` (신규)

### 2.5 자금 관리 (Treasury)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 계좌 요약 | 총 잔고, 할당됨, 미할당, 예약됨 |
| 봇별 할당 차트 | 파이 차트 — 봇별 예산 비중 |
| 봇별 예산 테이블 | 봇ID, 할당액, 가용액, 예약액, 사용액, 회수액 |
| 할당 관리 | 봇 선택 → 금액 입력 → 할당/회수 버튼 |
| 거래 이력 | 할당/회수/체결 등 자금 변동 로그 |

**API 의존성**: `/api/treasury/summary`, `/api/treasury/allocate`, `/api/treasury/deallocate` (모두 신규)

### 2.6 리포트 (Reports)

#### 리포트 목록

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 리포트 카드/테이블 | 전략명, 버전, 수익률, 거래 수, 상태, 제출일 |
| 상태 필터 | 전체 / 대기(submitted) / 채택(adopted) / 거부(rejected) |
| 검색 | 전략명 검색 |

#### 리포트 상세 (`/reports/:id`)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 전략 정보 | 이름, 버전, 작성자, 파일 경로 |
| 백테스트 요약 | 기간, 초기/최종 자산, 수익률, 거래 수 |
| 성과 지표 | 샤프 비율, MDD, 승률, 수익 팩터 |
| 자산 추이 차트 | 백테스트 에쿼티 커브 (TradingView Area Chart) |
| 드로우다운 차트 | MDD 시각화 (TradingView Area Chart, 음의 영역) |
| Agent 분석 | 요약, 근거, 리스크, 권장 사항 (텍스트) |
| 채택/거부 | 버튼 + 사용자 메모 입력 → 상태 변경 |

**API 의존성**: `GET /api/reports`, `GET /api/reports/:id`, `PATCH /api/reports/:id/status` (일부 신규)

### 2.7 데이터 탐색 (Data)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 데이터셋 목록 | 종목, 타임프레임, 시작/종료일, 행 수 |
| 스키마 정보 | OHLCV 컬럼 타입 표시 |
| 저장 용량 | 전체 용량, 타임프레임별 용량 |
| 캔들 차트 미리보기 | 선택한 종목의 최근 데이터 시각화 (TradingView Candlestick) |

**API 의존성**: `/api/data/datasets`, `/api/data/schema`, `/api/data/storage` (구현 완료)

### 2.8 설정 (Settings)

| 구성 요소 | 주요 기능 |
|-----------|-----------|
| 시스템 상태 | 킬 스위치 토글 (ACTIVE/HALTED) |
| 동적 설정 | key-value 설정 편집 (DynamicConfigService) |
| 브로커 연결 | KIS 연결 상태, 모의/실전 모드 표시 |
| 알림 설정 | Telegram 알림 레벨 조정 |

**API 의존성**: `/api/system/kill-switch` (신규), `/api/config` (신규)

## 3. 실시간 기능 (WebSocket)

### WebSocket 엔드포인트

`ws://서버주소/ws/events`

### 이벤트 타입

| 이벤트 | 용도 | 갱신 대상 |
|--------|------|-----------|
| `bot_started` | 봇 시작 | 봇 목록, 대시보드 |
| `bot_stopped` | 봇 중지 | 봇 목록, 대시보드 |
| `bot_error` | 봇 오류 | 봇 목록 + Toast 경고 |
| `order_filled` | 체결 완료 | 거래 내역 + Toast 알림 |
| `order_rejected` | 주문 거부 | Toast 경고 |
| `trading_state_changed` | 킬 스위치 변경 | Header 상태등 |
| `notification` | 시스템 알림 | Toast 알림 |

### 프론트엔드 처리 패턴

```
WebSocket 연결
  → Zustand Store 업데이트
    → React 컴포넌트 자동 리렌더링
    → Toast 알림 표시
```

## 4. 신규 API 엔드포인트 (구현 필요)

현재 구현된 API 4개 라우터 외에 Frontend가 필요로 하는 신규 엔드포인트:

### 4.1 봇 관리 API (`/api/bots`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/bots` | 봇 목록 조회 |
| POST | `/api/bots` | 봇 생성 |
| GET | `/api/bots/:id` | 봇 상세 조회 |
| POST | `/api/bots/:id/start` | 봇 시작 |
| POST | `/api/bots/:id/stop` | 봇 중지 |
| DELETE | `/api/bots/:id` | 봇 삭제 |
| GET | `/api/bots/:id/positions` | 봇 포지션 조회 |
| GET | `/api/bots/:id/performance` | 봇 성과 지표 |

### 4.2 거래 API (`/api/trades`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/trades` | 거래 내역 조회 (필터, 페이지네이션) |
| GET | `/api/trades/:id` | 거래 상세 |

### 4.3 자금 관리 API (`/api/treasury`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/treasury/summary` | 전체 자금 요약 |
| GET | `/api/treasury/budgets` | 봇별 예산 목록 |
| POST | `/api/treasury/allocate` | 자금 할당 |
| POST | `/api/treasury/deallocate` | 자금 회수 |
| POST | `/api/treasury/balance` | 계좌 잔고 설정 |

### 4.4 시스템 API 확장

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/system/kill-switch` | 킬 스위치 제어 |
| GET | `/api/config` | 동적 설정 조회 |
| PUT | `/api/config/:key` | 동적 설정 변경 |

### 4.5 WebSocket

| 경로 | 설명 |
|------|------|
| `ws://서버/ws/events` | 실시간 이벤트 스트리밍 |

## 5. 프로젝트 디렉토리 구조

```
frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── .env.local                    # API_URL, API_KEY (gitignore)
├── public/
│   └── favicon.svg
├── src/
│   ├── main.tsx                  # 진입점
│   ├── App.tsx                   # 라우터 루트
│   ├── index.css                 # Tailwind 기본 스타일
│   │
│   ├── api/                      # API 클라이언트
│   │   ├── client.ts             # Axios 인스턴스 (API Key 인터셉터)
│   │   ├── system.ts
│   │   ├── bots.ts
│   │   ├── trades.ts
│   │   ├── treasury.ts
│   │   ├── reports.ts
│   │   ├── strategies.ts
│   │   ├── data.ts
│   │   └── websocket.ts          # WebSocket 매니저
│   │
│   ├── hooks/                    # React Query 훅
│   │   ├── useSystemStatus.ts
│   │   ├── useBots.ts
│   │   ├── useTrades.ts
│   │   ├── useTreasury.ts
│   │   ├── useReports.ts
│   │   └── useWebSocket.ts
│   │
│   ├── store/                    # Zustand 스토어
│   │   └── useEventStore.ts      # WebSocket 이벤트 상태
│   │
│   ├── pages/                    # 페이지 컴포넌트
│   │   ├── Dashboard.tsx
│   │   ├── Bots.tsx
│   │   ├── BotDetail.tsx
│   │   ├── Trades.tsx
│   │   ├── Treasury.tsx
│   │   ├── Reports.tsx
│   │   ├── ReportDetail.tsx
│   │   ├── Data.tsx
│   │   └── Settings.tsx
│   │
│   ├── components/               # 재사용 컴포넌트
│   │   ├── layout/
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── Layout.tsx
│   │   ├── dashboard/
│   │   │   ├── StatusCard.tsx
│   │   │   ├── BotSummaryCard.tsx
│   │   │   ├── TreasurySummaryCard.tsx
│   │   │   └── RecentTrades.tsx
│   │   ├── bots/
│   │   │   ├── BotTable.tsx
│   │   │   ├── BotCreateForm.tsx
│   │   │   ├── BotControls.tsx
│   │   │   └── PositionTable.tsx
│   │   ├── charts/
│   │   │   ├── EquityCurveChart.tsx
│   │   │   ├── CandleChart.tsx
│   │   │   ├── DrawdownChart.tsx
│   │   │   └── AllocationPieChart.tsx
│   │   ├── reports/
│   │   │   ├── ReportCard.tsx
│   │   │   ├── BacktestMetrics.tsx
│   │   │   └── ReviewControls.tsx
│   │   ├── treasury/
│   │   │   ├── AccountSummary.tsx
│   │   │   ├── BudgetTable.tsx
│   │   │   └── AllocationForm.tsx
│   │   └── common/
│   │       ├── Toast.tsx
│   │       ├── StatusBadge.tsx
│   │       ├── LoadingSpinner.tsx
│   │       └── DataTable.tsx
│   │
│   ├── types/                    # TypeScript 타입
│   │   ├── bot.ts
│   │   ├── trade.ts
│   │   ├── treasury.ts
│   │   ├── report.ts
│   │   └── system.ts
│   │
│   └── utils/
│       ├── formatters.ts         # 숫자/날짜 포맷
│       └── constants.ts          # 상수값
└── dist/                         # 빌드 결과 (gitignore)
```

## 6. 구현 단계

### Phase F-1: 프로젝트 셋업 + 기본 레이아웃

- Vite + React + TypeScript 프로젝트 초기화
- Tailwind CSS + shadcn/ui 설정
- Layout (Header, Sidebar, 라우팅) 구현
- API 클라이언트 (Axios 인스턴스) 설정
- 대시보드 기본 화면 (시스템 상태 카드)

### Phase F-2: 데이터 + 리포트 화면 (기존 API 활용)

- 데이터 탐색 페이지 (datasets, schema, storage)
- 리포트 목록 + 상세 페이지
- TradingView Lightweight Charts 통합 (에쿼티 커브)
- 리포트 채택/거부 UI

### Phase F-3: 백엔드 API 확장 + 봇 관리

- `/api/bots` CRUD 엔드포인트 구현
- `/api/trades` 엔드포인트 구현
- `/api/treasury` 엔드포인트 구현
- 봇 목록 + 상세 페이지
- 봇 생성 폼
- 거래 내역 페이지

### Phase F-4: 자금 관리 + 설정

- 자금 관리 페이지 (요약, 할당)
- 설정 페이지 (킬 스위치, 동적 설정)
- 캔들 차트 미리보기 (데이터 탐색)

### Phase F-5: 실시간 기능

- WebSocket 엔드포인트 구현 (FastAPI 측)
- WebSocket 매니저 (프론트엔드)
- Zustand 스토어 연동
- Toast 알림 시스템
- 실시간 봇 상태/거래 갱신

### Phase F-6: 마무리

- 에러 핸들링, 로딩 상태
- 반응형 디자인 (모바일/태블릿)
- 빌드 최적화 + FastAPI 정적 파일 서빙 설정
- E2E 테스트 (Playwright 또는 Cypress)

## 7. 핵심 고려사항

### N100 홈서버 제약

- TradingView Lightweight Charts는 클라이언트 사이드 렌더링 → 서버 부하 없음
- WebSocket 메시지는 최소한의 페이로드 (필요한 필드만 전송)
- React 빌드는 개발 머신에서 수행, 서버에는 정적 파일만 배포

### 인증

- 홈서버 단일 사용자 환경 → 단순 API Key 인증
- `X-API-Key` 헤더 기반
- 향후 JWT로 확장 가능 (외부 Agent REST API 개방 시)

### 데이터 페이지네이션

- 거래 내역: 커서 기반 (`cursor=<last_trade_id>`, `limit=100`)
- 리포트: 오프셋 기반 (`offset=0`, `limit=20`)
- 무한 스크롤 또는 "더 보기" 버튼

### 차트 라이브러리 활용

| 차트 종류 | 사용 위치 | TradingView 차트 타입 |
|-----------|-----------|----------------------|
| 에쿼티 커브 | 봇 상세, 리포트 상세 | Area Series |
| 캔들 차트 | 데이터 미리보기 | Candlestick Series |
| 드로우다운 | 리포트 상세 | Area Series (음의 영역) |
| 포트폴리오 가치 | 대시보드 | Area Series |
| 봇별 할당 비중 | 자금 관리 | (별도 파이 차트 라이브러리) |
