# Ante 대시보드 아키텍처

> 대시보드의 기술 스택, 데이터 흐름, API 의존성을 정의한다.
> 화면 구성은 [mockups/](mockups/) 목업과 [user-stories/](user-stories/) 유저스토리를 참조한다.

## 사용자 정의

Ante의 대시보드는 **단일 사용자(운영자)**를 위한 화면이다.
운영자는 이 시스템의 최종 의사결정자로서, AI Agent가 제안한 전략을 검토하고 채택 여부를 결정하며, 자금을 배분하고, 시스템의 안전한 운영을 감독한다.

운영자가 대시보드에서 하는 일은 크게 네 가지다:

1. **감독** — 자산 현황, 봇 상태, 전략 성과를 한눈에 파악한다
2. **의사결정** — Agent가 제출한 전략 리포트를 검토하고, 예산 할당을 승인/거부한다
3. **운영** — 봇을 생성·제어하고, 자금을 배분하고, Agent를 관리한다
4. **안전 관리** — 리스크 규칙을 설정하고, 이상 상황 시 킬스위치로 즉시 개입한다

### 메뉴별 유저스토리

| 메뉴 | 유저스토리 | 목업 |
|------|-----------|------|
| 로그인 | [login.md](user-stories/login.md) | [login.html](mockups/login.html) |
| 자금 관리 | [treasury.md](user-stories/treasury.md) | [treasury.html](mockups/treasury.html), [treasury-history.html](mockups/treasury-history.html) |
| 결재함 | [approvals.md](user-stories/approvals.md) | [approvals.html](mockups/approvals.html), approval-detail-*.html (5종) |
| 봇 관리 | [bots.md](user-stories/bots.md) | [bots.html](mockups/bots.html), [bot-detail.html](mockups/bot-detail.html), [bot-detail-stopped.html](mockups/bot-detail-stopped.html) |
| 전략과 성과 | [strategies.md](user-stories/strategies.md) | [strategies.html](mockups/strategies.html), [strategy-detail.html](mockups/strategy-detail.html), [performance.html](mockups/performance.html), [trades.html](mockups/trades.html) |
| 에이전트 관리 | [agents.md](user-stories/agents.md) | [agents.html](mockups/agents.html), [agent-detail.html](mockups/agent-detail.html) |
| 백테스트 데이터 | [backtest-data.md](user-stories/backtest-data.md) | [backtest-data.html](mockups/backtest-data.html) |
| 리포트 상세 | [report-detail.md](user-stories/report-detail.md) | [report-detail.html](mockups/report-detail.html) |
| 설정 | [settings.md](user-stories/settings.md) | [settings.html](mockups/settings.html) |

## 1. 기술 스택

| 영역 | 선택 | 근거 |
|------|------|------|
| 프레임워크 | React 19 + TypeScript | D-008 결정, AI 코드 생성 품질 최고 |
| 빌드 도구 | Vite | 빠른 HMR, 경량 번들 |
| 차트 | TradingView Lightweight Charts | D-008 결정, 금융 특화 경량 차트 |
| UI 컴포넌트 | Tailwind CSS 4 + 시맨틱 디자인 토큰 | 커스터마이징 용이, 번들 경량 |
| 상태 관리 | Tanstack Query | REST API 캐싱 + 자동 갱신 |
| 라우팅 | React Router v6 | 표준 SPA 라우팅 |
| HTTP | Axios | 세션 쿠키 인터셉터, 에러 핸들링 |

**배포**: React 빌드 → `frontend/dist/` → FastAPI에서 정적 파일로 서빙
- 개발 머신/CI에서 빌드, 홈서버에는 빌드 결과만 배포
- N100 서버에 Node.js 불필요

## 2. 인증

대시보드는 사용자(human)만 이용한다. 패스워드 로그인 → 세션 쿠키 기반 인증.

- 인증 메서드: Member 스펙 `authenticate_password`
- 세션: 서버사이드 SQLite 저장, 24시간 타임아웃, `HttpOnly` + `SameSite=Strict` 쿠키

**인증 흐름:**
1. member_id + 패스워드 → `POST /api/auth/login`
2. 서버에서 `authenticate_password` 호출
3. 성공: 세션 쿠키 발급 → 대시보드 리다이렉트
4. 실패: 에러 메시지 표시 (구체적 실패 사유 비노출)
5. Axios 인터셉터: 401 응답 시 자동으로 `/login` 이동

## 3. API 의존성

> **SSOT**: 백엔드 OpenAPI 스키마 (`/openapi.json`)가 API 계약의 단일 진실 원천이다.
> 프론트엔드 타입은 `npm run generate-types`로 자동 생성한다 ([generate-types.sh](../../frontend/scripts/generate-types.sh)).

### 라우터별 구현 현황

대시보드가 의존하는 백엔드 라우터와 프론트엔드 연동 상태.

| 라우터 | 백엔드 | 프론트 API 클라이언트 | 비고 |
|--------|:------:|:--------------------:|------|
| auth | ✅ | ✅ | login, logout, me |
| approvals | ✅ | ✅ | 목록, 상세, 상태 변경 |
| bots | ✅ | ✅ | CRUD, start/stop |
| config | ✅ | ✅ | 동적 설정 조회/변경 |
| data | ✅ | ✅ | datasets, storage, feed-status, 삭제 |
| members | ✅ | ✅ | CRUD, 상태 전환, 토큰, 패스워드, scopes |
| portfolio | ✅ | ✅ | 총 자산, 추이 |
| reports | ✅ | ✅ | 상세 조회 |
| strategies | ✅ | ✅ | 목록, 상세, 성과, 일/주/월 요약, 거래 내역 |
| system | ✅ | ✅ | status, health, kill-switch |
| treasury | ✅ | ✅ | 요약, 예산, 할당/회수, 거래 이력 |
| trades | ✅ | — | 프론트에서 strategies/:id/trades로 대체 |
| audit | ✅ | — | 대시보드 미사용 (CLI/Agent용) |
| notifications | ✅ | — | 대시보드 미사용 (Telegram 알림용) |

### 미구현 사항

| 항목 | 설명 | 상태 |
|------|------|:----:|
| 세션 미들웨어 | 대시보드용 서버사이드 세션 (SQLite 저장, 쿠키 발급) | ⬜ 확인 필요 |
| treasury `POST /balance` | 계좌 잔고 초기 설정 | ⬜ 확인 필요 |
| 프론트 타입 현행화 | 백엔드 변경 후 `openapi.json` 재생성 → `generate-types` 실행 필요 | ⬜ 미동기화 |

## 4. 데이터 페이지네이션

| 대상 | 방식 | 파라미터 |
|------|------|----------|
| 결재 목록 | 오프셋 기반 | `offset`, `limit` (기본 20) |
| 전략 거래 내역 | 커서 기반 | `cursor=<last_trade_id>`, `limit` (기본 100) |
| 봇 목록 | 커서 기반 | `cursor`, `limit` |
| 백테스트 데이터 | 오프셋 기반 | `offset`, `limit` (기본 15) |

## 5. 차트 라이브러리 활용

| 차트 종류 | 사용 위치 | TradingView 차트 타입 |
|-----------|-----------|----------------------|
| 포트폴리오 가치 | 대시보드 | Area Series |
| 에쿼티 커브 | 전략 상세, 결재 상세 (전략 리포트) | Area Series |
| 드로우다운 | 결재 상세 (전략 리포트) | Area Series (음의 영역) |
| 봇별 예산 비중 | 자금 관리 | 파이 차트 (별도 구현 또는 CSS) |

## 6. 프론트엔드 공통 규칙

### 데이터 흐름

```
api/ → hooks/ → pages/ → components/
```

- `api/` 모듈은 Axios `client`를 통해 HTTP 호출만 수행
- `hooks/`는 React Query로 캐싱·리페치·뮤테이션을 캡슐화, api 모듈과 1:1 대응
- `pages/`는 hooks를 조합하여 데이터를 가져오고 컴포넌트에 전달
- `components/`는 props만 받아 렌더링 (API 직접 호출 금지)

### 포맷터 (`utils/formatters.ts`)

모든 표시 값은 포맷터를 경유한다. 컴포넌트에서 직접 `toLocaleString()` 등을 호출하지 않는다.

| 함수 | 용도 | 출력 예시 |
|------|------|-----------|
| `formatKRW` | 원화 금액 | `1,000,000 원` |
| `formatPercent` | 수익률/비율 | `+1.23%` |
| `formatNumber` | 천 단위 콤마 | `12,345` |
| `formatDate` | 날짜 | `2026. 03. 20.` |
| `formatDateTime` | 날짜+시간 | `2026. 03. 20. 14:30` |

### 상태 라벨 (`utils/constants.ts`)

백엔드 enum 값 → 한글 라벨 매핑을 상수로 관리한다.

| 상수 | 대상 |
|------|------|
| `BOT_STATUS_LABELS` | 봇 상태 (created, running, stopped, error 등) |
| `STRATEGY_STATUS_LABELS` | 전략 상태 (registered, active, inactive, archived) |
| `APPROVAL_STATUS_LABELS` | 결재 상태 (pending, approved, rejected) |
| `MEMBER_STATUS_LABELS` | 멤버 상태 (active, suspended, revoked) |
| `TRANSACTION_TYPE_LABELS` | 자금 변동 유형 (allocate, deallocate, fill 등) |

### 공용 컴포넌트 (`components/common/`)

| 컴포넌트 | 역할 |
|----------|------|
| `DataTable` | 제네릭 테이블. Column 정의 기반 렌더링, 행 클릭, 빈 상태 메시지 |
| `Pagination` | 오프셋 기반 페이지네이션. "총 N건 중 M-K" + 페이지 번호 |
| `StatusBadge` | 색상 variant 기반 상태 뱃지 (positive, negative, warning, info, muted) |
| `Modal` | 오버레이 모달. ESC/외부 클릭으로 닫기 |
| `HintTooltip` | `?` 아이콘 호버 시 설명 표시 |
| `Toast` | 전역 토스트 알림. `showToast(message, type)` 함수로 호출 |
| `Skeleton` | 로딩 플레이스홀더 (Table, Chart, Card, Page 변형 제공) |
| `ErrorBoundary` | React 에러 바운더리. 미처리 에러 시 복구 UI |
| `ServiceUnavailable` | 서버 연결 불가 시 안내 화면 |
| `LoadingSpinner` | 전체 화면 로딩 인디케이터 |

### 에러 핸들링

| 계층 | 처리 방식 |
|------|-----------|
| HTTP 401 | Axios 인터셉터 → `/login` 리다이렉트 |
| HTTP 4xx/5xx (detail 포함) | Axios 인터셉터 → Toast 에러 메시지 |
| 네트워크 오류 | Axios 인터셉터 → "서버에 연결할 수 없습니다" Toast |
| 렌더링 오류 | ErrorBoundary → "예기치 않은 오류" 복구 UI |

### 인증 가드

- `ProtectedRoute`가 `GET /api/auth/me`로 세션 유효성 검증
- 미인증 시 `/login`으로 리다이렉트
- 검증 중 `LoadingSpinner` 표시

### 코딩 컨벤션

#### 컴포넌트 구조

```typescript
// 1. import 순서: React → Router → Hooks → Components → Utils → Types
import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useBotDetail } from '../hooks/useBots'
import StatusBadge from '../components/common/StatusBadge'
import { formatKRW } from '../utils/formatters'
import type { BotDetail } from '../types/bot'

// 2. 페이지 컴포넌트: export default function (named function)
export default function BotDetail() {
  // 3. hooks → 로딩 체크 → 렌더링
  const { data, isLoading } = useBotDetail(id)
  if (isLoading) return <PageSkeleton />
  // ...
}
```

- **페이지**: `export default function PageName()` — named function + default export
- **컴포넌트**: Props 인터페이스를 명시적으로 정의. `[Component]Props` 네이밍
- **파일 내 보조 컴포넌트**: `function SubComponent({ prop }: { prop: Type })` — export 없이 같은 파일에 정의

#### 네이밍 규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 파일 (페이지·컴포넌트) | PascalCase | `BotDetail.tsx`, `StatusBadge.tsx` |
| 파일 (훅·API·타입·유틸) | camelCase | `useBots.ts`, `bots.ts`, `bot.ts` |
| 컴포넌트 | PascalCase | `function BotCard()` |
| 훅 | `use` + PascalCase | `useBotDetail()`, `useCreateBot()` |
| API 함수 | 동사 + PascalCase | `getBots()`, `createBot()`, `deleteBot()` |
| 타입/인터페이스 | PascalCase, 접두사 없음 | `interface Bot`, `type BotStatus` |
| 상태 유니온 | 소문자 snake_case (백엔드 일치) | `'running' \| 'stopped' \| 'error'` |

#### 타입 정의 규칙

- **`interface`**: 객체 형태 정의 (`interface Bot { ... }`)
- **`type`**: 유니온·별칭 (`type BotStatus = 'running' | 'stopped'`)
- **`enum` 미사용**: 백엔드 enum은 string literal union으로 표현
- **자동 생성 타입**: `api.generated.ts`는 직접 수정 금지. 수동 타입에서 re-export하여 사용

#### React Query 규칙

- **Query key**: 계층 배열 — `['resource']`, `['resource', id]`, `['resource', id, 'sub']`
- **파라미터 포함**: `['resource', params]` (params 객체가 key에 포함되어 자동 리페치)
- **뮤테이션 후**: `queryClient.invalidateQueries({ queryKey: ['resource'] })` 로 관련 쿼리 무효화
- **조건부 페칭**: `enabled: !!id` 패턴
- **useState**: UI 상태(모달, 필터, 폼 입력)에만 사용. 서버 데이터에 useState 사용 금지

#### 디자인 토큰 사용 규칙

**색상** — `index.css`에 정의된 시맨틱 토큰만 사용한다. Tailwind 기본 색상(`text-white`, `text-purple-400` 등)이나 임의 색상값(`bg-[#xxx]`, `bg-[rgba(...)]`) 직접 사용을 금지한다.

| 용도 | 사용할 토큰 | 사용 금지 |
|------|------------|-----------|
| 배경 | `bg-bg`, `bg-surface`, `bg-surface-hover` | `bg-white`, `bg-gray-900` |
| 텍스트 | `text-text`, `text-text-muted` | `text-white`, `text-gray-400` |
| 테두리 | `border-border` | `border-gray-700` |
| 수익/긍정 | `text-positive`, `bg-positive-bg` | `text-blue-500` |
| 손실/부정 | `text-negative`, `bg-negative-bg` | `text-red-500` |
| 경고 | `text-warning`, `bg-warning-bg` | `text-yellow-500` |
| 정보 | `text-info`, `bg-info-bg` | `text-purple-400` |
| 뮤트 | `text-text-muted`, `bg-surface-hover` | `text-gray-500` |
| 버튼/배지 위 텍스트 | `text-on-primary` | `text-white` |
| 모달 오버레이 | `bg-overlay` | `bg-black/50`, `bg-black/60` |
| 뱃지/툴팁 배경 | `bg-muted-bg` | `bg-[rgba(139,143,163,...)]` |
| 코드/상태 패널 배경 | `bg-code-bg` | `bg-[rgba(255,255,255,...)]` |

> 새로운 시맨틱 색상이 필요하면 `index.css`의 `@theme`에 토큰을 추가한 후 사용한다.

**타이포그래피** — 목업 기준 폰트 크기 체계. Tailwind 임의값(`text-[Npx]`)으로 사용한다.

| 역할 | 크기 | 용도 |
|------|------|------|
| caption | `text-[11px]` | 보조 설명, 산정 기준일, 힌트 |
| label | `text-[12px]` | 필드 라벨, 뱃지 텍스트 |
| body-sm | `text-[13px]` | 테이블 셀, 카드 부가 정보 |
| body | `text-[14px]` | 기본 본문, 입력 필드 |
| subtitle | `text-[15px]` | 카드 헤더, 항목 제목 |
| heading | `text-[18px]` | 섹션 제목 |
| metric | `text-[22px]` | 대형 수치 (금액, 수익률) |

> **장식 예외**: 이모지 아바타, 에러 페이지 아이콘, 404 숫자 등 **비텍스트 장식 요소**는 위 7단계 체계 밖의 임의 크기(`text-[45px]`, `text-[48px]`, `text-[64px]` 등)를 허용한다.

**카드 레이아웃** — 모든 카드는 동일한 기본 클래스를 사용한다.

```
bg-surface border border-border rounded-lg
```

- 내부 패딩: `p-5` (기본), `p-6` (모달·폼)
- 섹션 구분: `border-b border-border` (수평선) 또는 `border-t border-border`
- 카드 간 간격: `mb-6`

**인라인 스타일 금지** — CSS 애니메이션 참조(`animation: 'name ...'`)를 제외하고 `style={}` 속성 사용을 금지한다. 모든 스타일링은 Tailwind 클래스로 처리한다.

## 7. 프론트엔드 디렉토리 구조

> 파일 단위 상세 구조는 [project-structure.md](../architecture/generated/project-structure.md)의 `frontend/` 섹션 참조.

| 디렉토리 | 역할 |
|---|---|
| `src/api/` | Axios 기반 API 클라이언트. 도메인별 모듈 분리, 세션 쿠키 + 401 인터셉터 |
| `src/hooks/` | React Query 훅. API 모듈과 1:1 대응, 캐싱·리페치 전략 캡슐화 |
| `src/pages/` | 라우트별 페이지 컴포넌트. 데이터 페칭은 hooks에 위임 |
| `src/components/` | 도메인별 UI 컴포넌트 (`layout/`, `dashboard/`, `approvals/`, `charts/` 등) + `common/` 공용 |
| `src/types/` | API 응답·도메인 모델 TypeScript 타입 정의 |
| `src/utils/` | 포맷터, 상수 등 유틸리티 |
| `public/` | 파비콘, 로고 SVG 등 정적 에셋 |

## 7. N100 홈서버 제약 고려

- TradingView Lightweight Charts는 클라이언트 사이드 렌더링 → 서버 부하 없음
- React 빌드는 개발 머신/CI에서 수행, 서버에는 정적 파일만 배포
- API 응답은 페이지네이션으로 제한하여 메모리 사용 통제
