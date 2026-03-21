# Ante 프론트엔드 코딩 컨벤션

> 대시보드(React + TypeScript) 구현 시 이 컨벤션을 따른다.
> 설계 문서: `docs/dashboard/architecture.md`

## 1. 디자인 충실도

**가장 중요한 원칙**: 설계 문서와 목업을 충실히 구현한다.

- `docs/dashboard/architecture.md`의 화면 구성표(§3)를 **반드시** 읽고 구현한다
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
│   ├── dashboard/    # 대시보드 전용 컴포넌트
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
│   ├── Dashboard.tsx
│   ├── Treasury.tsx
│   └── Bots.tsx
├── types/            # TypeScript 타입 (도메인별 1파일)
│   ├── auth.ts
│   ├── treasury.ts
│   └── bot.ts
└── utils/            # 유틸리티 (포맷터, 상수 등)
    ├── formatters.ts
    └── constants.ts
```

### 파일 배치 규칙

- **페이지**: `pages/` — 라우트와 1:1 대응, 레이아웃만 조합하는 얇은 파일
- **컴포넌트**: `components/{도메인}/` — 페이지에서 사용하는 UI 조각
- **API**: `api/` — Axios 호출 함수. `client.ts`를 import하여 사용
- **훅**: `hooks/` — Tanstack Query 래퍼. API 함수를 호출
- **타입**: `types/` — API 요청/응답 타입. 컴포넌트 props 타입은 컴포넌트 파일 내 정의

## 3. 컴포넌트 패턴

### 페이지 컴포넌트 (pages/)

페이지는 얇게 유지한다. 레이아웃과 하위 컴포넌트 조합만 담당:

```tsx
// pages/Treasury.tsx
export default function Treasury() {
  return (
    <>
      <AccountSummary />
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

export default function AccountSummary() {
  const { data, isLoading } = useTreasurySummary()

  if (isLoading) return <Skeleton className="h-32" />

  return (
    <div className="rounded-lg border bg-card p-6">
      <h3 className="text-sm font-medium text-muted-foreground">총 자산</h3>
      <p className="text-2xl font-bold">{formatCurrency(data.total)}</p>
    </div>
  )
}
```

**원칙**:
- 컴포넌트 내부에서 직접 훅을 호출 (props drilling 최소화)
- 로딩 상태는 반드시 Skeleton으로 처리
- 에러 상태도 고려 (ErrorBoundary 또는 인라인)
- `export default function` 사용 (named export 아님)

## 4. 데이터 흐름

```
API 함수 (api/)  →  커스텀 훅 (hooks/)  →  컴포넌트 (components/)
     ↑                    ↑
  client.ts          Tanstack Query
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

- `queryKey`는 `[도메인, 리소스, ...파라미터]` 형태
- mutation 훅도 같은 파일에 위치

## 5. 스타일링

### Tailwind CSS + shadcn/ui

- shadcn/ui 컴포넌트를 **우선** 사용한다
- 커스텀 CSS는 `tailwind.config.ts`의 확장으로만 추가
- 인라인 스타일 사용 금지
- `className`에 Tailwind 유틸리티 클래스를 직접 적용

### 색상/간격 일관성

```tsx
// 좋음: 시맨틱 색상 사용
<span className="text-muted-foreground">부가 정보</span>
<span className="text-destructive">에러</span>

// 나쁨: 하드코딩 색상
<span className="text-gray-500">부가 정보</span>
<span className="text-red-600">에러</span>
```

### 금액/숫자 표시

```tsx
// utils/formatters.ts의 포맷터를 사용
import { formatCurrency, formatPercent } from '../utils/formatters'

// 금액: ₩1,234,567
<span>{formatCurrency(amount)}</span>

// 수익률: +12.34% (초록) / -5.67% (빨강)
<span className={value >= 0 ? 'text-green-600' : 'text-red-600'}>
  {formatPercent(value)}
</span>
```

## 6. 타입 안전성

### API 응답 타입 (types/)

```tsx
// types/treasury.ts
export interface TreasurySummary {
  total_cash: number
  total_allocated: number
  available: number
  currency: string
}
```

- API 응답 구조와 1:1 대응하는 인터페이스를 정의한다
- 백엔드 스펙(`docs/specs/`)의 응답 스키마를 참조한다
- `any` 사용 금지

### Props 타입

```tsx
// 컴포넌트 파일 내에서 정의
interface BotCardProps {
  bot: Bot
  onStop: (botId: string) => void
}

export default function BotCard({ bot, onStop }: BotCardProps) {
  // ...
}
```

## 7. API 계약 기준 개발

프론트엔드의 API 호출 코드는 반드시 백엔드의 OpenAPI 스키마(`/openapi.json`, Swagger UI `/docs`)를 기준으로 작성한다. 엔드포인트 경로, HTTP 메서드, 요청 파라미터, 응답 구조를 추측하지 않고, OpenAPI 문서에 정의된 계약을 그대로 따른다. API 구조가 불분명하면 `/api-docs` 커맨드로 스키마를 조회한다.

API 응답 타입은 `openapi-typescript`로 자동 생성된 것만 사용한다. 수동으로 API 타입을 정의하는 것은 금지한다.

**규칙**:
- `frontend/src/types/` 내 API 응답 타입은 OpenAPI 스키마에서 자동 생성한다
- 수동으로 API 응답 인터페이스를 작성하지 않는다
- 스키마 변경 이슈가 머지되면 `openapi-typescript`를 실행하여 타입을 재생성한다
- 컴포넌트 Props 등 프론트엔드 전용 타입은 수동 정의 허용 (API 응답 타입만 자동 생성 대상)
- 참조: `docs/runbooks/01-development-process.md` §10 (API 스키마 변경 규칙)

```bash
# 타입 재생성 (백엔드 서버 실행 상태에서)
npx openapi-typescript http://localhost:8000/openapi.json -o src/types/api.generated.ts
```

## 8. 설계 문서 참조 의무

이슈 구현 시 반드시 다음을 확인한다:

1. `docs/dashboard/architecture.md` §3의 해당 화면 구성표
2. 구성 요소 테이블의 **모든 항목**이 구현되었는지 체크
3. API 의존성(`**API**:` 행)이 올바르게 연결되었는지 확인
4. 데이터 흐름(`**데이터 흐름**:` 행)이 설계대로인지 확인

**체크리스트** (PR 전 자가 검증):
- [ ] 설계 문서의 구성 요소를 하나도 빠뜨리지 않았는가?
- [ ] 레이아웃 순서가 설계와 동일한가?
- [ ] 로딩/에러/빈 상태를 모두 처리했는가?
- [ ] API 타입이 백엔드 스펙과 일치하는가?
- [ ] shadcn/ui 컴포넌트를 우선 활용했는가?
