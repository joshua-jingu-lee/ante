# 01. AI 에이전트 기반 개발 프로세스

> 에이전트 및 서브에이전트를 활용한 개발 체계를 정의한다.

---

## 1. 개발 철학

- 주 개발은 AI 에이전트(Claude Code)와 함께 진행
- AGENTS.md는 핵심 규칙만 간결하게 유지, 세부 사항은 docs/specs/로 분리하여 참조
- 스펙 문서(`docs/specs/`)가 설계의 단일 출처(SSOT)다. 변경이 필요하면 **스펙 최신화 → 이슈 발행 → 코드 반영** 순서를 따른다. 코드를 먼저 고치고 스펙을 나중에 맞추지 않는다.
- 단순한 구조에서 시작하여 필요에 따라 점진적으로 확장
- 에이전트는 자기 영역 안에서 자율적으로 구현 판단을 내림
- 엔지니어는 "코드 작성자"가 아닌 "에이전트 오케스트레이터" 역할에 집중

## 2. 에이전트 역할 구성

> 에이전트 역할, `.agent/` 구조와 `.claude/` 호환 레이어 상세: [02-agent-structure.md](02-agent-structure.md)

7개 에이전트 — 오케스트레이터, `@backend-dev`, `@frontend-dev`, `@code-reviewer`, `@qa-engineer`, `@devops`, `@strategy-dev` — 가 역할별로 분담한다. 에이전트 정의 파일(`.agent/agents/*.md`)이 각 에이전트의 SSOT이다.

## 3. 에이전트 간 상호작용 흐름

```
사용자 (요구사항/이슈)
  │
  ▼
오케스트레이터 (메인 세션)
  │  ◄──── AGENTS.md + docs/specs/* (설계 문서 참조)
  │
  ├── 분석: 이슈 읽기 → 스펙 확인 → 에이전트 결정
  │         스펙 불일치 시 → 이슈에 스킵 코멘트, 중단
  │
  ├── 착수 기록: 이슈에 코멘트 (담당 에이전트, 변경 대상)
  │
  ├──▶ @backend-dev / @frontend-dev / @devops / @strategy-dev (worktree 격리)
  │         │
  │         ▼ 구현 + 테스트 + PR 생성
  │
  ├──▶ @code-reviewer (읽기 전용)
  │         │
  │         ▼ 체크리스트 검증 → gh pr review (APPROVE / REQUEST_CHANGES)
  │
  ├── 수정 루프 (오케스트레이터 조율, 최대 2회):
  │         개발 에이전트 수정 → 리뷰 에이전트 재리뷰
  │
  ├── CI 확인
  │         │
  │         ├── 통과 → 머지 진행
  │         │
  │         └── 실패 → 원인 분류
  │               ├── 코드 문제 → 개발 에이전트에 수정 위임
  │               └── 인프라 문제 → @devops에 해결 위임
  │                     → 수정 후 CI 재실행 → 통과 시 속행
  │
  ├── APPROVE + CI 통과 → 머지 (모드에 따라 자동/수동)
  │
  ├── 이슈 체크박스 갱신 + close
  │
  ▼
결과 보고

--- QA 흐름 (qa-test / qa-sweep) ---

오케스트레이터
  │
  ├── Docker QA 환경 기동
  │         │
  │         └── 빌드/기동 실패 → @devops에 해결 위임
  │               → 수정 후 재빌드·기동하여 속행
  │
  ├──▶ @qa-engineer (TC 실행 + 판정)
  │         │
  │         ▼ PASS/FAIL/ERROR/SKIP 리포트 반환
  │
  ├── FAIL → 버그 이슈 등록 (오케스트레이터)
  │         └── --fix 시 → /implement-issue → 재검증
  │
  ▼
QA 리포트
```

**GitHub 기록 포인트**: 각 단계의 결정과 결과가 이슈 코멘트 또는 PR 리뷰로 남는다. 에이전트 간 대화는 GitHub에 기록되어 사후 추적이 가능하다.

## 4. 작업 실행 체계

에이전트의 구체적인 작업 절차는 `.agent/commands/`에 정의된 커맨드가 단일 출처(SSOT)다.

| 커맨드 | 역할 | 파일 |
|--------|------|------|
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → 구현 → 리뷰 → 머지) | `.agent/commands/implement-issue.md` |
| `/autopilot` | 완전 자동 모드 (구현 → QA → 수정 루프, 무확인) | `.agent/commands/autopilot.md` |
| `/qa-test` | 지정 TC 실행 (`@qa-engineer` 위임) | `.agent/commands/qa-test.md` |
| `/qa-sweep` | 전체 TC 순차 실행 (전수 검사) | `.agent/commands/qa-sweep.md` |
| `/api-docs` | OpenAPI 스키마 조회 | `.agent/commands/api-docs.md` |

Runbook 문서(이 파일 포함)는 "왜, 무엇을"에 대한 **정책**을 정의한다.
Commands는 "어떻게"에 대한 **절차**를 정의한다.
**절차가 중복 기술되지 않도록, 이 문서에서는 commands를 참조만 한다.**

### 4.1 브랜치 전략

> Git 컨벤션 상세: [03-git-workflow.md](03-git-workflow.md)

**독립 이슈**: main에서 분기하여 작업 후 main으로 PR.

```
main
  └─ {type}/#{issue번호}-{짧은설명} → PR → main (squash merge)
```

**에픽 이슈**: 에픽 통합 브랜치에서 하위 이슈를 묶은 뒤 main으로 한 번에 PR.

```
main
  └─ epic/#{에픽번호}-{짧은설명}
       ├─ feat/#{하위1} → PR → epic 브랜치
       ├─ feat/#{하위2} → PR → epic 브랜치
       └─ feat/#{하위3} → PR → epic 브랜치
     epic 브랜치 → PR → main
```

> 구체적 절차: `/implement-issue`의 "에픽 이슈 처리 절차(E1~E5)" 참조.

### 4.2 Worktree 격리

모든 구현 작업은 **git worktree**로 격리하여 로컬 main을 보호한다.

| 상황 | Worktree 사용 |
|------|:------------:|
| 독립 모듈 병렬 구현 | O |
| 에픽 하위 이슈 병렬 구현 | O |
| 의존성 있는 순차 구현 | O (각각 별도 worktree) |
| 에픽 통합 브랜치 검증 (E4) | O |

> 구체적 절차: `/implement-issue`의 6단계, E4단계 참조.

## 5. `.agent/` 및 `.claude/` 디렉토리 활용

> 디렉토리 구조, 에이전트/커맨드/스킬 상세: [02-agent-structure.md](02-agent-structure.md)

- **agents/**: 역할별 에이전트 정의 (YAML frontmatter → 자동 적용)
- **commands/**: 슬래시 명령 — 작업 절차의 SSOT
- **skills/**: 도메인 지식 — 에이전트 정의의 `skills:` 필드로 자동 연결
- **settings.json**: 권한 제한 + hooks (포맷팅, 보호 파일 검사)

## 6. 에이전트 실패 시 복구 루프

오케스트레이터는 실패 원인을 분류하여 적절한 에이전트에 해결을 위임하고, 해결 후 원래 흐름을 속행한다. 구체적 절차는 `/implement-issue`, `/qa-test` 커맨드가 SSOT이며, 이 섹션은 정책만 정의한다.

### 6.1 실패 유형별 복구 경로

| 실패 유형 | 원인 분류 | 복구 담당 | 복구 후 |
|-----------|----------|----------|--------|
| 구현 실패 (빌드/테스트 오류) | 코드 문제 | 개발 에이전트 자체 수정 | 원래 구현 흐름 속행 |
| 코드 리뷰 REQUEST_CHANGES | 코드 품질 | 개발 에이전트 수정 → `@code-reviewer` 재리뷰 | 머지 흐름 속행 |
| CI 실패 — 코드 문제 | 테스트/lint 실패 | 개발 에이전트 수정 → CI 재실행 | 머지 흐름 속행 |
| CI 실패 — 인프라 문제 | Docker 빌드, 의존성, CI 설정 | `@devops` 수정 → CI 재실행 | 머지 흐름 속행 |
| QA Docker 기동 실패 | 이미지 빌드/컨테이너 실패 | `@devops` 수정 → 재빌드·기동 | TC 실행 속행 |
| QA TC FAIL | 기능 버그 | 오케스트레이터가 이슈 등록 → 개발 에이전트 수정 | 재검증 속행 |

### 6.2 자동 복구 (에이전트 자율)

| 단계 | 행동 | 조건 |
|------|------|------|
| 1차 시도 | 에러 로그 분석 → 원인 파악 → 코드 수정 | 에러 메시지가 명확한 경우 |
| 2차 시도 | 다른 접근법으로 재구현 시도 | 동일 에러 반복 시 |
| 3차 시도 | 문제 범위 축소 (최소 재현 케이스 작성) | 2차까지 실패 시 |

### 6.3 스킵 및 에스컬레이션

**동일 원인** 실패가 반복될 때의 처리:

| 실패 횟수 | autopilot 모드 | 일반 모드 |
|-----------|---------------|----------|
| 1~2회 | 자동 복구 시도 | 자동 복구 시도 |
| 3회 | 스킵 처리 + 이슈에 실패 사유 코멘트 | 사용자에게 에스컬레이션 |

에스컬레이션 보고서 형식:

```
[에스컬레이션 보고서]
- 작업: {무엇을 하려 했는지}
- 실패 유형: {코드 문제 / 인프라 문제 / 스펙 불일치}
- 시도한 접근법: {1차, 2차, 3차 각각}
- 실패 원인 분석: {근본 원인 추정}
- 제안: {사용자에게 요청하는 사항}
```

**원인이 다르면 새 시도로 카운트한다.** 코드 변경에 의한 인프라 깨짐은 빈번하므로, 매번 다른 원인이면 횟수를 리셋한다.

## 7. Autopilot 모드

오픈 이슈 구현 → QA 검증 → 버그 수정을 이슈가 없어질 때까지 **사용자 확인 없이** 자율 반복하는 완전 자동 모드.

> 실행 절차: `/autopilot` 커맨드 참조.

### 7.1 메인 루프

```
Phase 1: 오픈 이슈 전부 구현 → @code-reviewer APPROVE → 자동 머지
    ↓
Phase 2: /qa-sweep --fix → @qa-engineer TC 실행 → FAIL 시 버그 이슈 등록
    ↓ 새 버그 있으면
Phase 1로 복귀 (최대 5라운드)
    ↓ 새 버그 없으면
Phase 3: 정리 + 최종 리포트 (docs/temp/autopilot-report-날짜시간.md)
```

### 7.2 적용 조건

- **개발 단계 한정**: 프로덕션 배포가 없는 초기 개발 기간에만 적용
- **배포 시작 후 전환**: 실전 배포가 시작되면 PR 생성까지만 자동, main 머지는 사용자 승인으로 복귀

### 7.3 자율 범위

| 행동 | 허용 |
|------|:----:|
| 코드 작성 + 테스트 | O |
| 커밋 + 푸시 + PR 생성 | O |
| `@code-reviewer` APPROVE + CI 통과 시 자동 머지 | O (개발 단계 한정) |
| 버그 이슈 자동 등록 + close | O |
| 프로덕션 배포 | X (항상 수동) |
| docs/specs/ 변경 | X (SSOT — 스펙 불일치 시 스킵) |
| 의존성 추가/변경 | X (사용자 확인 필요) |

### 7.4 안전장치

- **자동 머지 조건**: `@code-reviewer` APPROVE + 모든 CI Gate 통과 후에만 머지
- **3회 스킵**: 동일 이슈에서 3회 이상 실패 시 스킵, 이슈에 실패 사유 코멘트
- **변경 금지 영역**: AGENTS.md, docs/specs/, pyproject.toml의 의존성 섹션
- **브랜치 보호**: main에 직접 push 금지, 반드시 PR을 통해서만 머지
- **최종 리포트**: `docs/temp/autopilot-report-YYYYMMDD-HHMM.md`에 기록

## 8. 코드 리뷰 프로세스

모든 PR은 머지 전에 `@code-reviewer` 에이전트의 체크리스트 기반 리뷰를 거친다. 리뷰어는 **판정만** 수행하고, 수정 루프는 오케스트레이터가 조율한다.

### 8.1 리뷰 흐름

```
PR 생성 (개발 에이전트)
  │
  ▼
@code-reviewer 위임 (체크리스트 A~F 검증)
  │
  ├── APPROVE → 머지 단계로
  │     ├── autopilot: 자동 squash merge
  │     └── 일반 모드: 사용자에게 머지 승인 요청
  │
  └── REQUEST_CHANGES → 오케스트레이터가 수정 루프 조율 (최대 2회)
        ├── 개발 에이전트에 FAIL 항목 수정 위임 → 새 커밋 → 푸시
        ├── @code-reviewer에 재리뷰 위임
        └── 2회 초과 실패 → autopilot: 스킵 / 일반: 에스컬레이션
```

### 8.2 리뷰 기준

체크리스트 기반으로 객관적 판정만 수행한다 (주관적 "더 나은 방법" 의견은 FAIL 사유 아님):

| 영역 | 검증 항목 |
|------|----------|
| **A. 이슈 정합성** | 유저스토리 충족, 수용 조건 충족, 범위 초과 변경 없음 |
| **B. API 계약** | response_model 존재, 스키마 무단 변경 없음, FE 타입 동기화 |
| **C. 설계 문서** | 스펙 일치 (SSOT), 생성 문서 갱신 여부 |
| **D. 코드 품질** | 컨벤션 준수, 사이드이펙트, 에러 처리, 보안 |
| **E. 테스트** | 테스트 존재, 엣지 케이스, 기존 테스트 무영향 |
| **F. PR 형식** | 커밋 메시지, PR 크기(≤300줄), base 브랜치 |
| **G. 프론트엔드** | `frontend/` 변경 시에만 적용: 디자인 토큰, 타이포그래피, API 임의 생성 금지, 자동 생성 타입 사용, 데이터 흐름, 유저스토리·목업 일치, 인라인 스타일 금지, 빌드 통과 |

**핵심 원칙:**
- **스펙이 SSOT**: 구현과 스펙이 불일치하면 구현이 틀린 것이다. 리뷰어는 `docs/specs/`를 기준으로 판정한다.
- **판정만, 수정은 안 함**: 리뷰어는 APPROVE/REQUEST_CHANGES를 게시하고 끝난다. 수정과 머지는 오케스트레이터가 조율한다.
- **이슈에도 기록**: 리뷰 판정 결과(APPROVE/REQUEST_CHANGES + FAIL 항목)를 원본 GitHub 이슈에 코멘트로 남긴다.

> 체크리스트 항목별 상세 기준과 판정 예시: `.agent/skills/review-pr.md`

### 8.3 리뷰 결과 게시

리뷰 결과는 `gh pr review`로 PR에 공식 리뷰로 게시된다. 각 항목별 PASS/FAIL/N/A 판정과, FAIL 시 구체적 수정 사항이 포함된다.

### 8.4 적용 범위

| 상황 | 리뷰 적용 |
|------|:--------:|
| `/implement-issue` (일반) | O — PR 생성 후 자동 실행 |
| `/autopilot` | O — 자동 실행, APPROVE 시 자동 머지 |
| 사용자 수동 PR | O — `/review-pr #{번호}`로 수동 실행 |
| 오타/포매팅 등 사소한 변경 | X — 이슈 없이 직접 커밋하는 경우 |

## 9. 생성 문서 동기화 규칙

`docs/architecture/generated/` 하위 문서는 소스 코드에서 추출한 정보를 정리한 것이다. 해당 소스가 변경되면 반드시 생성 문서도 함께 갱신한다.

| 생성 문서 | 갱신 트리거 | 대상 소스 | 갱신 방법 |
|-----------|-----------|----------|----------|
| `guide/cli.md` | 명령어 추가/삭제, 인자·옵션·scope 변경 | `src/ante/cli/commands/` | `python scripts/generate_cli_reference.py` |
| `docs/architecture/generated/db-schema.md` | CREATE TABLE / CREATE INDEX 변경, 테이블 추가/삭제 | `src/ante/**/` 내 `_DDL` 상수 | `python scripts/generate_db_schema.py` |
| `docs/architecture/generated/project-structure.md` | 디렉토리·모듈 추가/삭제/이동 | 프로젝트 디렉토리 트리 | 수동 편집 |

### 9.1 자동 생성 스크립트

| 문서 | 스크립트 | 비고 |
|------|---------|------|
| `guide/cli.md` | `python scripts/generate_cli_reference.py` | Click 명령어 트리를 자동 순회하여 전체 문서를 재생성한다. 수동 편집 금지. |
| `docs/architecture/generated/db-schema.md` | `python scripts/generate_db_schema.py` | 모듈별 `_DDL` 상수를 파싱하여 전체 문서를 재생성한다. 수동 편집 금지. |
| `docs/architecture/generated/project-structure.md` | 미구현 | 디렉토리 구조 변경 시 수동 편집으로 유지한다. |

### 9.2 갱신 규칙

- **CLI 변경 시**: `src/ante/cli/commands/` 파일을 수정한 뒤 반드시 `python scripts/generate_cli_reference.py`를 실행하여 `guide/cli.md`를 재생성한다. 스크립트가 SSOT이므로 `guide/cli.md`를 직접 편집하지 않는다.
- **DDL 변경 시**: 모듈의 `_DDL` 상수를 수정한 뒤 반드시 `python scripts/generate_db_schema.py`를 실행하여 `db-schema.md`를 재생성한다. 스크립트가 SSOT이므로 `db-schema.md`를 직접 편집하지 않는다.
- **디렉토리 구조 변경 시**: 모듈·패키지가 추가/삭제/이동되면 `project-structure.md`를 갱신한다.
- **API 엔드포인트**: Swagger UI(`/docs`)에 자동 반영되므로 별도 문서 갱신 불필요.
- autopilot 모드에서도 이 규칙 적용.

## 10. API 스키마 변경 규칙

API 응답 스키마(`src/ante/web/schemas.py`의 Pydantic 모델)는 백엔드와 프론트엔드 양쪽에 영향을 미치는 계약(contract)이다. 스키마 변경은 별도 이슈로 분리하여 양쪽 영향을 통제한다.

### 10.1 스키마 변경 = 별도 이슈

- `src/ante/web/schemas.py`의 Pydantic 모델을 추가·수정·삭제하는 작업은 **구현 이슈와 분리하여 별도 이슈로 등록**한다.
- 구현 이슈 진행 중 스키마 변경이 필요하다고 판단되면, 해당 이슈 안에서 직접 변경하지 않고 새 이슈를 발행한다.
- 스키마 변경 이슈와 구현 이슈 사이에 의존성을 명시한다 (예: "선행: #NNN").

### 10.2 오케스트레이터 검증

- 오케스트레이터는 구현 요청에 API 스키마 변경이 포함되어 있는지 감지한다.
- 스키마 변경이 감지되면, 스키마 변경을 별도 이슈로 분리하도록 안내한다.
- API 스키마 변경 이슈는 오케스트레이터가 **백엔드·프론트엔드 양쪽 영향을 판단**한 뒤 승인한다.

### 10.3 백엔드 규칙

- 모든 새 엔드포인트는 반드시 `response_model`을 명시한다.
- `dict`를 직접 반환하는 것은 금지한다. Pydantic 모델을 통해 응답 구조를 보장한다.
- 기존 `response_model`을 변경하려면 별도 스키마 변경 이슈를 거친다.

### 10.4 프론트엔드 규칙

- API 응답 타입은 `openapi-typescript`로 자동 생성된 `api.generated.ts`에서만 import한다.
- 수동으로 API 응답 인터페이스를 정의하지 않는다 (`types/*.ts`에 API 응답 타입 작성 금지).
- 수동 타입은 컴포넌트 Props, UI 상태 등 프론트엔드 전용 타입에만 허용된다.
- 스키마 변경 이슈가 머지되면 `npm run generate-types`로 타입을 재생성하여 동기화한다.
- **백엔드에 존재하지 않는 API를 프론트엔드에서 임의로 만들어 호출하지 않는다.** 필요한 API가 없으면 백엔드 이슈를 등록한다.

## 11. AGENTS.md 경량화 원칙

AGENTS.md는 모든 세션에 주입되므로 비대하면 오히려 지시를 무시하게 됨.

**원칙**:
- 각 줄에 대해 "이걸 삭제하면 에이전트가 실수할까?"를 자문 — 아니면 삭제
- 핵심 설계 원칙, 기술 스택, 디렉토리 구조만 유지
- 모듈별 세부 설계는 `docs/specs/`에 분리하고 필요 시 참조
- 상세 가이드는 `.agent/skills/`로 분리

## 관련 문서

| 문서 | 내용 |
|------|------|
| [00-issue-management.md](00-issue-management.md) | 이슈 등록, 분류, 추적 규칙 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션, PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인 (Gate 모델) |
| [05-testing.md](05-testing.md) | 테스트 전략, 커버리지 기준 |
