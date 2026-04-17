# PR 코드 리뷰 스킬

> PR head SHA에 대해 구조화된 체크리스트 기반 승인 판정을 수행하는 공통 기준 문서다.
> Claude PR 승인 워커와 Codex PR 승인 워커가 같은 체크리스트 계약을 공유한다.

## 트리거

- `pull_request` opened / synchronize / ready_for_review
- 수동 재검증이 필요한 경우 해당 PR 번호를 입력으로 실행

## 인자

$ARGUMENTS — PR 번호 (예: 42)

## 실행 절차

### 1단계: PR 정보 수집

```bash
# PR 메타데이터
gh pr view #{PR번호} --json title,body,baseRefName,headRefName,labels,files

# 변경된 파일 목록
gh pr diff #{PR번호} --name-only

# 전체 diff
gh pr diff #{PR번호}
```

연관 이슈 번호를 PR 본문에서 추출한다 ("Closes #N", "Refs #N" 패턴).

### 2단계: 컨텍스트 로딩

PR의 변경 영역에 따라 필요한 문서를 읽는다:

| 변경 영역 | 로딩 대상 |
|-----------|----------|
| `src/ante/web/` | `docs/specs/web-api/web-api.md`, `.agent/skills/module-conventions.md` |
| `src/ante/{모듈}/` | `docs/specs/{모듈}/{모듈}.md`, `.agent/skills/module-conventions.md` |
| `frontend/` | `docs/dashboard/architecture.md`, `.agent/skills/frontend-conventions.md` |
| `tests/` | `docs/runbooks/04-testing.md` |
| async 코드 포함 | `.agent/skills/asyncio-patterns.md` |
| DB 코드 포함 | `.agent/skills/sqlite-patterns.md` |

연관 이슈의 유저스토리와 수용 조건도 읽는다:
```bash
gh issue view #{이슈번호}
```

### 3단계: 체크리스트 검증

아래 체크리스트를 **순서대로** 검증한다. 각 항목은 PASS / FAIL / N/A 중 하나로 판정한다.

---

#### A. 이슈 정합성

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| A1 | 유저스토리 충족 | 이슈의 모든 US가 구현되었는가 |
| A2 | 수용 조건 충족 | 이슈의 완료 조건이 모두 만족되었는가 |
| A3 | 범위 초과 변경 없음 | 이슈에 명시되지 않은 변경이 포함되어 있지 않은가 |

#### B. API 계약

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| B1 | response_model 존재 | 새 엔드포인트에 `response_model`이 명시되어 있는가 |
| B2 | 스키마 무단 변경 없음 | `schemas.py`의 기존 Pydantic 모델이 변경되었는가 → 변경 시 별도 이슈 필요 |
| B3 | 프론트엔드 타입 동기화 | API 응답 변경이 있다면 프론트엔드 타입도 함께 갱신되었는가 |

#### C. 설계 문서 정합성

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| C1 | 스펙 문서 일치 | 변경 내용이 `docs/specs/{모듈}/{모듈}.md`와 일치하는가. **스펙이 SSOT**이므로 불일치 시 FAIL 처리. 리뷰 중 스펙을 수정하지 않는다 |
| C2 | 생성 문서 갱신 | DDL 변경 → `db-schema.md`, API 변경 → `api-reference.md`, CLI 변경 → `cli-reference.md` 갱신 여부 |

#### D. 코드 품질

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| D1 | 컨벤션 준수 | 대상 영역의 skills/ 컨벤션을 따르는가 (모듈 구조, DI, 타입 힌트 등) |
| D2 | 사이드이펙트 | 변경이 다른 모듈에 의도하지 않은 영향을 주는가 (공유 import, 공유 스키마 등) |
| D3 | 에러 처리 | 새 코드의 에러 처리가 적절한가 (모듈별 예외 계층 사용, 적절한 HTTP 상태 코드) |
| D4 | 보안 | SQL 인젝션, XSS, 인증 우회 등 OWASP 취약점이 없는가 |

#### E. 테스트

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| E1 | 테스트 존재 | 새 기능/수정에 대응하는 테스트가 있는가 |
| E2 | 엣지 케이스 | 경계값, 에러 경로 등 엣지 케이스가 커버되는가 |
| E3 | 기존 테스트 영향 | 기존 테스트가 불필요하게 수정/삭제되지 않았는가 |

#### F. PR 형식

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| F1 | 커밋 메시지 | Conventional Commits 형식 준수 (`feat(scope): ...`) |
| F2 | PR 크기 | 변경 라인 수 300줄 이하 (테스트 제외). 500줄 초과 시 분할 권고 |
| F3 | base 브랜치 | 에픽 소속이면 에픽 브랜치, 독립이면 main이 base인가 |

#### G. 프론트엔드 (frontend/ 변경 시에만 적용)

> `frontend/` 하위 파일이 변경된 경우에만 이 섹션을 검증한다. 백엔드만 변경된 PR은 G 전체를 N/A로 처리한다.
> 참조: `.agent/skills/frontend-conventions.md`, `docs/dashboard/architecture.md` § 코딩 컨벤션

| # | 검증 항목 | 판정 기준 |
|---|----------|----------|
| G1 | 디자인 토큰 준수 | Tailwind 기본 색상(`text-white`, `text-green-600`, `bg-gray-900` 등)이나 임의 색상값(`bg-[#xxx]`)을 사용하지 않고, `index.css` `@theme`에 정의된 시맨틱 토큰(`text-text`, `text-positive`, `bg-surface` 등)만 사용하는가 |
| G2 | 타이포그래피 체계 | 목업 기준 폰트 크기 체계(`text-[11px]`~`text-[22px]`)를 따르는가. Tailwind 기본 크기(`text-sm`, `text-2xl` 등) 사용 시 FAIL |
| G3 | API 임의 생성 금지 | `api/*.ts`에 백엔드 OpenAPI 스키마에 없는 엔드포인트를 작성하지 않았는가. 확인 방법: 새로 추가된 API 함수의 경로가 `/openapi.json`에 존재하는지 `/api-docs` 커맨드로 검증 |
| G4 | 자동 생성 타입 사용 | API 응답 타입을 `api.generated.ts`에서 import하는가. `types/*.ts`에 새로운 API 응답 인터페이스를 수동 정의하지 않았는가 |
| G5 | 데이터 흐름 | `api/ → hooks/ → pages/ → components/` 패턴을 따르는가. 컴포넌트에서 API를 직접 호출하거나, pages를 건너뛰고 hooks를 사용하지 않는가 |
| G6 | 유저스토리·목업 일치 | 이슈에 연결된 유저스토리(`docs/dashboard/user-stories/`)와 목업(`docs/dashboard/mockups/`)의 구성 요소가 빠짐없이 구현되었는가. 레이아웃 순서가 목업과 일치하는가 |
| G7 | 인라인 스타일 금지 | CSS 애니메이션 참조를 제외하고 `style={}` 속성을 사용하지 않았는가 |
| G8 | 빌드 통과 | `npm run build`가 에러 없이 완료되는가 (프론트엔드에는 별도 테스트 프레임워크가 없으므로 빌드 통과가 검증 기준) |

### 4단계: 판정

| 판정 | 조건 |
|------|------|
| **APPROVE** | FAIL 항목 0개 |
| **REQUEST_CHANGES** | FAIL 항목 1개 이상 |

### 5단계: PR 코멘트 게시

판정 결과를 `gh pr review`로 제출한다:

```bash
# APPROVE인 경우
gh pr review #{PR번호} --approve --body "{리뷰 코멘트}"

# REQUEST_CHANGES인 경우
gh pr review #{PR번호} --request-changes --body "{리뷰 코멘트}"
```

코멘트 포맷:

```markdown
## Code Review — {APPROVE | REQUEST_CHANGES}

> PR #{PR번호} | 이슈 #{이슈번호} | 리뷰 일시: {YYYY-MM-DD HH:MM}

### A. 이슈 정합성
- [x] A1 유저스토리 충족
- [x] A2 수용 조건 충족
- [ ] A3 범위 초과 변경 없음 — ⚠️ {설명}

### B. API 계약
- [x] B1 response_model 존재
- N/A B2
- N/A B3

### C. 설계 문서 정합성
- [x] C1 스펙 문서 일치
- [x] C2 생성 문서 갱신

### D. 코드 품질
- [x] D1 컨벤션 준수
- [x] D2 사이드이펙트 없음
- [x] D3 에러 처리 적절
- [x] D4 보안 취약점 없음

### E. 테스트
- [x] E1 테스트 존재
- [ ] E2 엣지 케이스 — ⚠️ {설명}
- [x] E3 기존 테스트 무영향

### F. PR 형식
- [x] F1 커밋 메시지
- [x] F2 PR 크기
- [x] F3 base 브랜치

### G. 프론트엔드 (frontend/ 변경 시)
- [x] G1 디자인 토큰 준수
- [ ] G2 타이포그래피 체계 — ⚠️ {설명}
- [x] G3 API 임의 생성 금지
- [x] G4 자동 생성 타입 사용
- [x] G5 데이터 흐름
- [x] G6 유저스토리·목업 일치
- [x] G7 인라인 스타일 금지
- [x] G8 빌드 통과

---

### 수정 요청 (REQUEST_CHANGES인 경우)

1. **A3**: {구체적 수정 사항과 이유}
2. **G2**: {구체적 수정 사항과 이유}

---

🤖 Reviewed by Claude Code (`/review-pr`)
```

### 반환값

승인 워커는 호출자에게 다음을 반환한다:

```
{
  "verdict": "APPROVE" | "REQUEST_CHANGES",
  "fail_items": ["A3", "E2"],           // REQUEST_CHANGES인 경우
  "details": {                           // 각 FAIL 항목의 수정 지침
    "A3": "범위 초과: {설명}",
    "E2": "엣지 케이스 누락: {설명}"
  }
}
```

**승인 워커는 여기서 끝난다.** 수정은 Claude 개발 에이전트가 수행하고, 머지는 GitHub merge gate가 담당한다.

## 판정 원칙

1. **객관적 기준만 적용**: "더 좋은 방법이 있을 것 같다" 같은 주관적 의견은 FAIL 사유가 되지 않는다. 체크리스트에 정의된 기준만으로 판정한다.
2. **현재 이슈 범위만 검증**: 기존 코드의 문제를 이 PR에서 고치라고 요구하지 않는다. 발견 시 별도 이슈로 등록한다.
3. **스펙이 SSOT**: 구현과 스펙이 불일치하면 구현이 틀린 것이다. 스펙을 수정하라고 권고하지 않는다.
