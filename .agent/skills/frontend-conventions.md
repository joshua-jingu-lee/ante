# Ante 프론트엔드 코딩 컨벤션

> 대시보드(React 19 + TypeScript + Tailwind CSS 4) 구현 시 이 컨벤션을 따른다.
> 설계 문서: `docs/dashboard/architecture.md`
> 디자인 가이드: `docs/dashboard/architecture.md` § 코딩 컨벤션 (디자인 토큰, 타이포그래피, 카드 레이아웃)
> 유저스토리: `docs/dashboard/user-stories/`
> 목업: `docs/dashboard/mockups/`
> 디자인 토큰 정의: `frontend/src/index.css` (`@theme` 블록)

## 1. 디자인 충실도

**가장 중요한 원칙**: 설계 문서와 목업을 충실히 구현한다.

- `docs/dashboard/architecture.md`의 화면 구성표를 **반드시** 읽고 구현한다
- 구성 요소 테이블에 명시된 항목을 빠뜨리지 않는다
- 레이아웃 순서(상단/하단, 좌/우 배치)를 설계와 동일하게 유지한다
- 이슈에 목업 파일(HTML)이나 스크린샷이 첨부되어 있으면 **반드시** 열어보고 픽셀 단위로 맞춘다
  - 목업 HTML은 `docs/dashboard/mockups/` 디렉토리에 페이지별로 관리된다
  - 이슈 본문의 목업 링크가 최우선 디자인 기준이다
- 임의로 UI를 "개선"하거나 구성 요소를 생략하지 않는다

## 2. 디렉토리 구조

```
frontend/src/
├── api/              # API 호출 함수 (모듈별 1파일)
│   ├── client.ts     # Axios 인스턴스 (공통)
│   ├── auth.ts
│   ├── treasury.ts
│   └── bots.ts
├── components/       # 재사용 컴포넌트 (도메인별 분류)
│   ├── common/       # 범용 (DataTable, Modal, StatusBadge 등)
│   ├── layout/       # Layout, Sidebar, Header
│   ├── charts/       # 차트 공용 컴포넌트 (LightweightChart, EquityCurveChart, AssetTrendChart)
│   ├── treasury/     # 자금관리 전용
│   ├── bots/         # 봇 관리 전용
│   ├── strategies/   # 전략 전용
│   ├── approvals/    # 결재함 전용
│   └── agents/       # 에이전트 관리 전용
├── hooks/            # 커스텀 훅 (도메인별 1파일)
│   ├── useAuth.ts
│   ├── useTreasury.ts
│   └── useBots.ts
├── pages/            # 라우트 대응 페이지 (얇은 컴포넌트)
│   ├── Treasury.tsx
│   ├── Bots.tsx
│   └── Strategies.tsx
├── types/            # TypeScript 타입 (도메인별 1파일)
│   ├── api.generated.ts  # 자동 생성 (직접 수정 금지)
│   ├── treasury.ts
│   └── bot.ts
└── utils/            # 유틸리티 (포맷터, 상수 등)
    ├── formatters.ts
    └── constants.ts
```

### 파일 배치 규칙

- **페이지**: `pages/` — 라우트와 1:1 대응, 레이아웃만 조합하는 얇은 파일
- **컴포넌트**: `components/{도메인}/` — 페이지에서 사용하는 UI 조각
- **차트**: `components/charts/` — TradingView Lightweight Charts 래퍼와 도메인 차트
- **API**: `api/` — Axios 호출 함수. `client.ts`를 import하여 사용
- **훅**: `hooks/` — Tanstack Query 래퍼. API 함수를 호출
- **타입**: `types/` — API 응답 타입 (자동생성 + 수동 보강). 컴포넌트 props 타입은 컴포넌트 파일 내 정의

## 3. 컴포넌트 패턴

### 페이지 컴포넌트 (pages/)

페이지는 얇게 유지한다. 레이아웃과 하위 컴포넌트 조합만 담당:

```tsx
// pages/Treasury.tsx
export default function Treasury() {
  return (
    <>
      <AccountSummary />
      <AssetTrendChart />
      <BudgetPieChart />
      <RecentTransactions />
    </>
  )
}
```

### UI 컴포넌트 (components/)

```tsx
// components/treasury/AccountSummary.tsx
import { useTreasurySummary } from '../../hooks/useTreasury'
import Skeleton from '../common/Skeleton'
import { formatKRW } from '../../utils/formatters'

export default function AccountSummary() {
  const { data, isLoading } = useTreasurySummary()

  if (isLoading) return <Skeleton className="h-32" />

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[12px] font-medium text-text-muted">총 자산</h3>
      <p className="text-[22px] font-bold text-text">{formatKRW(data.total)}</p>
    </div>
  )
}
```

**원칙**:
- 컴포넌트 내부에서 직접 훅을 호출 (props drilling 최소화)
- 로딩 상태는 반드시 Skeleton으로 처리
- 에러 상태도 고려 (ErrorBoundary 또는 인라인)
- `export default function` 사용 (named function + default export)

## 4. 데이터 흐름

```
API 함수 (api/)  →  커스텀 훅 (hooks/)  →  페이지 (pages/)  →  컴포넌트 (components/)
     ↑                    ↑
  client.ts          Tanstack Query v5
  (Axios)            (캐싱, 갱신)
```

### API 함수 (api/)

```tsx
// api/treasury.ts
import client from './client'
import type { TreasurySummary } from '../types/treasury'

export async function getTreasurySummary(): Promise<TreasurySummary> {
  const { data } = await client.get('/api/treasury/summary')
  return data
}
```

- 반환 타입을 명시한다
- `client` 인스턴스를 사용한다 (직접 axios 사용 금지)

### 커스텀 훅 (hooks/)

```tsx
// hooks/useTreasury.ts
import { useQuery } from '@tanstack/react-query'
import { getTreasurySummary } from '../api/treasury'

export function useTreasurySummary() {
  return useQuery({
    queryKey: ['treasury', 'summary'],
    queryFn: getTreasurySummary,
  })
}
```

- `queryKey`는 계층 배열 — `['resource']`, `['resource', id]`, `['resource', id, 'sub']`
- mutation 훅도 같은 파일에 위치
- 뮤테이션 후: `queryClient.invalidateQueries({ queryKey: ['resource'] })`로 관련 쿼리 무효화
- 조건부 페칭: `enabled: !!id` 패턴
- `useState`는 UI 상태(모달, 필터, 폼 입력)에만 사용. 서버 데이터에 useState 사용 금지

## 5. 디자인 토큰

### 색상

`index.css`에 정의된 시맨틱 토큰만 사용한다. **Tailwind 기본 색상이나 임의 색상값 사용을 금지한다.**

| 용도 | 사용할 토큰 | 사용 금지 |
|------|------------|-----------|
| 배경 | `bg-bg`, `bg-surface`, `bg-surface-hover` | `bg-white`, `bg-gray-900` |
| 텍스트 | `text-text`, `text-text-muted` | `text-white`, `text-gray-400` |
| 테두리 | `border-border` | `border-gray-700` |
| 수익/긍정 | `text-positive`, `bg-positive-bg` | `text-green-600`, `text-blue-500` |
| 손실/부정 | `text-negative`, `bg-negative-bg` | `text-red-600`, `text-red-500` |
| 경고 | `text-warning`, `bg-warning-bg` | `text-yellow-500` |
| 정보 | `text-info`, `bg-info-bg` | `text-purple-400` |
| 뮤트 | `text-text-muted`, `bg-surface-hover` | `text-gray-500` |
| 버튼/배지 위 텍스트 | `text-on-primary` | `text-white` |
| 모달 오버레이 | `bg-overlay` | `bg-black/50`, `bg-black/60` |
| 뱃지/툴팁 배경 | `bg-muted-bg` | `bg-[rgba(139,143,163,...)]` |
| 코드/상태 패널 배경 | `bg-code-bg` | `bg-[rgba(255,255,255,...)]` |

> 새로운 시맨틱 색상이 필요하면 `index.css`의 `@theme`에 토큰을 추가한 후 사용한다.

### 타이포그래피

목업 기준 폰트 크기 체계. Tailwind 임의값(`text-[Npx]`)으로 사용한다.

| 역할 | 크기 | 용도 |
|------|------|------|
| caption | `text-[11px]` | 보조 설명, 산정 기준일, 힌트 |
| label | `text-[12px]` | 필드 라벨, 뱃지 텍스트 |
| body-sm | `text-[13px]` | 테이블 셀, 카드 부가 정보 |
| body | `text-[14px]` | 기본 본문, 입력 필드 |
| subtitle | `text-[15px]` | 카드 헤더, 항목 제목 |
| heading | `text-[18px]` | 섹션 제목 |
| metric | `text-[22px]` | 대형 수치 (금액, 수익률) |

> **장식 예외**: 이모지 아바타, 에러 페이지 아이콘, 404 숫자 등 **비텍스트 장식 요소**는 위 7단계 체계 밖의 임의 크기를 허용한다.

### 카드 레이아웃

모든 카드는 동일한 기본 클래스를 사용한다:

```
bg-surface border border-border rounded-lg
```

- 내부 패딩: `p-5` (기본), `p-6` (모달·폼)
- 섹션 구분: `border-b border-border` (수평선) 또는 `border-t border-border`
- 카드 간 간격: `mb-6`

### 금액/수익률 색상

```tsx
// 수익률 색상 — 디자인 토큰 사용
<span className={value >= 0 ? 'text-positive' : 'text-negative'}>
  {formatPercent(value)}
</span>
```

### 인라인 스타일

CSS 애니메이션 참조(`animation: 'name ...'`)를 제외하고 `style={}` 속성 사용을 금지한다.
모든 스타일링은 Tailwind 클래스로 처리한다.

## 6. 타입 안전성

### 타입 시스템 (자동 생성 전용)

**API 응답 타입은 `api.generated.ts`에서만 import한다. 수동 타입 파일(`types/*.ts`)에 API 응답 인터페이스를 정의하지 않는다.**

- **`api.generated.ts`**: OpenAPI 스키마에서 `npm run generate-types`로 자동 생성 — 직접 수정 금지
- **수동 타입 허용 범위**: 컴포넌트 Props, UI 상태, 프론트엔드 전용 유틸리티 타입만
- 백엔드 스키마 변경 시 `npm run generate-types`로 재생성하여 동기화

```bash
# 타입 재생성
npm run generate-types
```

### import 패턴

```tsx
// API 응답 타입: api.generated.ts에서 import
import type { BotDetailResponse, BotListResponse } from '../types/api.generated'

// 프론트엔드 전용 타입: 컴포넌트 파일 내 정의
interface BotCardProps {
  bot: BotDetailResponse
  onStop: (botId: string) => void
}
```

### 타입 정의 규칙

- **`type`**: 자동 생성 타입의 re-export, 유니온, 별칭에 사용 (`type BotStatus = BotDetailResponse['status']`)
- **`interface`**: 컴포넌트 Props 등 프론트엔드 전용 객체 정의
- **`enum` 미사용**: 백엔드 enum은 string literal union으로 표현
- **`I` 접두사 금지**: `IBotProps` ✕ → `BotCardProps` ✓
- **`any` 사용 금지**

## 7. 네이밍 규칙

| 대상 | 규칙 | 예시 |
|------|------|------|
| 파일 (페이지·컴포넌트) | PascalCase | `BotDetail.tsx`, `StatusBadge.tsx` |
| 파일 (훅·API·타입·유틸) | camelCase | `useBots.ts`, `bots.ts`, `bot.ts` |
| 컴포넌트 | PascalCase | `function BotCard()` |
| 훅 | `use` + PascalCase | `useBotDetail()`, `useCreateBot()` |
| API 함수 | 동사 + PascalCase | `getBots()`, `createBot()`, `deleteBot()` |
| 타입/인터페이스 | PascalCase, 접두사 없음 | `interface Bot`, `type BotStatus` |
| 상태 유니온 | 소문자 snake_case (백엔드 일치) | `'running' \| 'stopped' \| 'error'` |

## 8. 차트 컴포넌트

TradingView Lightweight Charts를 사용한다 (`lightweight-charts` 패키지).

### 컴포넌트 구조

```
components/charts/
├── LightweightChart.tsx    ← createChart 래퍼 (ResizeObserver, cleanup)
├── EquityCurveChart.tsx    ← Area Series (전략 상세, 리포트 상세 공유)
└── AssetTrendChart.tsx     ← Area + Histogram 듀얼 축 (자금관리 전용)
```

### 데이터 흐름

```
api/treasury.ts (fetchSnapshots)
  → hooks/useTreasurySnapshots.ts (React Query)
    → pages/Treasury.tsx (데이터 가져오기)
      → components/charts/AssetTrendChart.tsx (props만 받아 렌더링)
```

- `LightweightChart.tsx`: `useRef` + `useEffect`로 chart 인스턴스 관리. ResizeObserver로 반응형. unmount 시 `chart.remove()` cleanup
- 차트 컴포넌트는 props만 받아 렌더링 (API 직접 호출 금지)

## 9. API 계약 기준 개발

**핵심 원칙: 프론트엔드는 백엔드에 존재하는 API만 호출한다. 없는 API를 임의로 만들어 호출하지 않는다.**

프론트엔드의 API 호출 코드는 반드시 백엔드의 OpenAPI 스키마(`/openapi.json`, Swagger UI `/docs`)를 기준으로 작성한다. 엔드포인트 경로, HTTP 메서드, 요청 파라미터, 응답 구조를 추측하지 않고, OpenAPI 문서에 정의된 계약을 그대로 따른다. API 구조가 불분명하면 `/api-docs` 커맨드로 스키마를 조회한다.

**금지 사항**:
- 백엔드에 존재하지 않는 엔드포인트를 `api/*.ts`에 작성하는 것
- OpenAPI 스키마에 없는 쿼리 파라미터, 요청 바디 필드를 추가하는 것
- 백엔드 응답에 없는 필드를 프론트엔드 타입에 정의하고 사용하는 것

**API가 부족할 때의 대응**:
1. 필요한 API가 백엔드에 없으면 → **프론트 구현을 중단**하고 백엔드 이슈를 등록한다
2. 기존 API의 응답 필드가 부족하면 → **백엔드 응답 확장 이슈**를 등록한다
3. 이슈에 `blocked` 라벨을 붙이고 해당 프론트 작업을 백엔드 이슈에 의존으로 연결한다

## 10. 설계 문서 참조 의무

이슈 구현 시 반드시 다음을 확인한다:

1. `docs/dashboard/architecture.md`의 해당 화면 구성표
2. `docs/dashboard/user-stories/` 해당 유저스토리의 **모든 항목**이 구현되었는지 체크
3. `docs/dashboard/mockups/` 해당 목업과 레이아웃이 일치하는지 확인
4. API 의존성이 올바르게 연결되었는지 확인
5. 데이터 흐름이 `api/ → hooks/ → pages/ → components/` 패턴을 따르는지 확인

**체크리스트** (PR 전 자가 검증):
- [ ] 유저스토리의 구성 요소를 하나도 빠뜨리지 않았는가?
- [ ] 레이아웃 순서가 목업과 동일한가?
- [ ] 로딩/에러/빈 상태를 모두 처리했는가?
- [ ] API 타입이 백엔드 스펙과 일치하는가?
- [ ] 디자인 토큰만 사용했는가? (Tailwind 기본 색상 금지)
- [ ] 타이포그래피가 폰트 크기 체계를 따르는가?
- [ ] 카드 레이아웃이 `bg-surface border border-border rounded-lg` 패턴인가?
- [ ] 인라인 스타일을 사용하지 않았는가?
