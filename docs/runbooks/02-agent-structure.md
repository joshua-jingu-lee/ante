# 02. 에이전트 구조 및 `.agent/` 디렉토리

> Claude 측 역할 정의와 `.agent/` 디렉토리 구성을 정의한다.
> Codex는 `.agent/` 내부 에이전트가 아니라 GitHub 이벤트 또는 Codex plugin 명령에 반응하는 외부 리뷰 워커로 취급한다.

---

## 1. 역할 구성

### 1.1 Claude 오케스트레이터

**담당**: 사용자와 직접 대화하는 메인 에이전트

**판단 기준**:
1. GitHub 이슈
2. `docs/specs/`
3. `AGENTS.md`

**역할**:
- 작업 분석과 분해
- Plan Preflight 산출물 확인, `plan-preflight:started`/`plan-preflight:done` 라벨 관리, Codex Plan Review 요청/결과 조율
- 야간 `/autopilot` 배치에서 이슈 큐 snapshot, Plan Preflight, 구현 위임, merge 모니터링 조율
- 적절한 Claude 서브에이전트 위임
- 이슈/브랜치/PR GitHub 기록 관리
- Codex 브랜치 리뷰 결과를 받아 수정 루프 조율
- PR 생성 후 최종 상태를 사용자에게 보고

**하지 않는 일**:
- 기본 운영 모델에서는 직접 머지하지 않는다.
- 모든 PR마다 `@code-reviewer`를 자동 호출하지 않는다.
  - 다만 고위험 변경이나 반복 failure가 나오면 명시적으로 호출한다.

### 1.2 백엔드 개발자 (`@backend-dev`)

**담당**: Python 백엔드 구현

- `docs/specs/` 설계 문서를 따라 구현, 테스트 작성, 로컬 검증, 브랜치 push까지 수행
- Codex Plan Review verdict가 나기 전까지 구현을 시작하지 않음
- Codex 브랜치 리뷰 또는 PR 승인 실패 시 같은 브랜치에서 수정

### 1.3 프론트엔드 개발자 (`@frontend-dev`)

**담당**: 대시보드(React) 구현

- `docs/dashboard/architecture.md` 기준으로 구현
- API 계약은 백엔드 OpenAPI와 자동 생성 타입을 기준으로 사용

### 1.4 DevOps 엔지니어 (`@devops`)

**담당**: Docker, GitHub Actions, CI/CD, 배포 환경 관리

- 리뷰 게이트와 merge automation을 포함한 GitHub Actions 구성 관리
- `pyproject.toml` dependencies 변경 시 사용자 확인 필수

### 1.5 전략 개발자 (`@strategy-dev`)

**담당**: 매매 전략 개발, 데이터 탐색, 백테스트

### 1.6 코드 리뷰어 (`@code-reviewer`)

**담당**: 구조 리스크 메타 리뷰, 반복 review failure 원인 분석

- `review-pr.md`와 역할이 겹치지 않는다.
- PR 승인 워커처럼 approve / fail 게이트를 직접 집행하지 않는다.
- 대신 아래 상황에서 오케스트레이터가 호출한다.
  - 캐시, 세션, 연결, long-lived adapter, mutable config 변경
  - OpenAPI, 생성 타입, 생성 문서, schema drift 위험
  - 같은 `risk class` failure가 2회 반복
  - PR 자동 재수정 전에 "무엇을 먼저 고쳐야 하는지"가 불명확

### 1.7 Codex 외부 워커

Codex는 `.agent/` 내부 에이전트가 아니라 GitHub 이벤트에 반응하는 외부 자동화 워커다.

| 역할 | 트리거 | 책임 |
|------|--------|------|
| **Codex Plan Review 워커** | `plan-preflight:started` 라벨 또는 구현 전 계획 검증 필요 | `/codex:adversarial-review`로 구현계획의 가정, 위험, 대안을 검토하고 이슈 코멘트에 verdict 기록 |
| **Codex 브랜치 리뷰어** | `/implement-issue`의 PR 생성 전 내부 `/codex:review --base <ref>` 실행 | PR 전 blocking issue 식별, 이슈 코멘트에 PASS/FAIL 기록 |
| **Codex PR 승인 워커** | `pull_request` opened/synchronize/ready_for_review | advisory check, branch protection required 아님. `codex-pr-approve` 상태 기록 |

### 1.8 Claude PR 승인 워커

Claude도 PR 단계에서는 독립 승인 워커로 동작한다.

| 역할 | 트리거 | 책임 |
|------|--------|------|
| **Claude PR 승인 워커** | `pull_request` opened/synchronize/ready_for_review | advisory check, branch protection required 아님. `claude-pr-approve` 상태 기록 |

## 2. `.agent/` 및 `.claude/` 디렉토리 구조

### 2.1 전체 구조

```
.agent/
├── agents/                # Claude 측 역할 정의 (정식 위치)
│   ├── backend-dev.md         # @backend-dev
│   ├── frontend-dev.md        # @frontend-dev
│   ├── devops.md              # @devops
│   ├── strategy-dev.md        # @strategy-dev
│   └── code-reviewer.md       # @code-reviewer — 구조 리스크 메타 리뷰
├── commands/              # 커스텀 슬래시 명령어 (작업 절차 SSOT)
│   ├── plan-preflight.md      # /plan-preflight
│   ├── implement-issue.md     # /implement-issue
│   ├── autopilot.md           # /autopilot
│   ├── release.md             # /release
│   └── api-docs.md            # /api-docs
└── skills/                # 도메인 지식 스킬
    ├── module-conventions.md
    ├── asyncio-patterns.md
    ├── sqlite-patterns.md
    ├── frontend-conventions.md
    ├── review-pr.md           # PR 승인 공통 체크리스트 계약
    ├── receive-review.md
    ├── github-auth.md
    ├── github-ops.md
    ├── lifecycle-review.md    # 캐시/세션/연결/설정 변경 리뷰
    ├── contract-drift-review.md
    └── generated-artifact-sync.md

.claude/
├── settings.json
├── settings.local.json
├── settings.local.example.json
├── hooks/
├── agents -> ../.agent/agents
├── commands -> ../.agent/commands
└── skills -> ../.agent/skills
```

### 2.2 에이전트 정의 (agents/)

`.agent/agents/*.md`는 Claude 서브에이전트 정의의 SSOT이다. Codex 워커는 Codex plugin 명령 또는 GitHub 이벤트에 반응하는 외부 워커이므로 이 디렉토리에 포함하지 않는다.

### 2.2.1 모델 및 추론 강도 정책

- frontmatter의 `model:`은 **단일 기본 모델**만 기록한다. 현재 운영 기준으로 복수 모델 배열은 지원하지 않는다.
- `reasoning effort`는 frontmatter에 고정하지 않고, **오케스트레이터가 호출 시점에 작업 위험도에 따라 선택**한다.
- 즉, 에이전트 문서는 "역할"을 정의하고, 모델/effort는 "운영 정책"으로 관리한다.
- 문서에서 쓰는 `xhigh`는 **최고 추론 단계**를 뜻한다. 실행 환경이나 모델별 UI에서는 `max`로 보일 수 있다.
- 특정 모델이 `xhigh`라는 정확한 라벨을 지원하지 않으면, **그 모델이 지원하는 최고 단계**로 해석한다.

| 에이전트 | 기본 effort | 높여야 하는 경우 | 낮춰도 되는 경우 |
|------|------|------|------|
| `@backend-dev` | `high` | 캐시/세션/연결/설정 변경, 계약 rename, 2개 이상 모듈 소비자 영향, Codex Plan Review 고위험 판정 | 리뷰 finding이 매우 구체적이고 1~2파일 follow-up인 경우 |
| `@frontend-dev` | `high` | API 계약 변경, 생성 타입 동기화, 다중 페이지 상태 흐름, 대규모 화면 리팩터링 | 스타일·문구·단일 컴포넌트 수정 |
| `@devops` | `high` | CI/CD, 인증, secret, release, merge automation, 운영 스크립트 변경 | 문서성 변경, 작은 경로 수정 |
| `@strategy-dev` | `xhigh` (`max`) | 새 전략 설계, 파라미터 탐색, 지표 해석, 백테스트 결과 비교 | 단순 validation rerun, 리포트 포맷 정리 |
| `@code-reviewer` | `xhigh` (`max`) | 반복 risk class failure, lifecycle/contract drift, 범위 축소/이슈 분할/사람 에스컬레이션 판단 | finding이 매우 국소적인 경우 |

- `@code-reviewer`만 항상 더 무겁게 두는 것이 아니라, **고위험 백엔드/DevOps 작업도 `xhigh`까지 올릴 수 있다.**
- 반대로 `low`는 품질 게이트 판단보다는 **정형 실행·수집 작업**에 한정한다.

### 2.3 커스텀 명령어 (commands/)

반복적인 개발 작업을 슬래시 명령으로 정의한다:

- `/plan-preflight #{번호}` — 이슈 본문 구현계획 작성/정비 → Codex Plan Review → `plan-preflight:done` 확정
- `/implement-issue #{번호}` — 분석 → Plan Preflight 확인 → Codex Plan Review → 구현 → Codex 브랜치 리뷰 → PR 생성
- `/autopilot` — 오픈 이슈 큐 snapshot → 필요 시 Plan Preflight → `/implement-issue` → merge/post-merge 순차 모니터링
- `/release` — prepare로 release PR 생성, publish로 GitHub Release/PyPI/Docker image 배포
- `/api-docs` — OpenAPI 스키마 조회

### 2.4 도메인 스킬 (skills/)

- **백엔드**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
- **프론트엔드**: `frontend-conventions`
- **리뷰 공통 규약**: `review-pr`
- **GitHub 운용 공통 스킬**:
  - `github-auth`
  - `github-ops`
- **구현 품질 보조 스킬**:
  - `receive-review`
- **리뷰 세부 플레이북**:
  - `lifecycle-review`
  - `contract-drift-review`
  - `generated-artifact-sync`

`review-pr.md`는 Claude/Codex PR 승인 워커가 공유하는 최종 승인 계약 문서다.
Codex Plan Review는 `.agent/skills/`가 아니라 `openai/codex-plugin-cc`의 `/codex:adversarial-review` 외부 명령으로 수행한다.
`code-reviewer.md`는 구조 리스크 메타 리뷰 정의다.

### 2.5 권한 및 Hooks (settings.json)

- **permissions**: Claude 측 에이전트가 실행 가능한 도구와 명령을 제한
- **hooks**: 파일 수정 시 자동 포맷팅(`auto-format.sh`), 보호 파일 검사(`protect-files.sh`)

## 3. 운영 상 주의사항

- Codex는 PR 전 브랜치 리뷰와 PR 후 승인 체크를 모두 담당하지만, 두 단계의 목적은 다르다.
  - PR 전 브랜치 리뷰는 GitHub Actions가 아니라 Claude 세션의 `/codex:review --base <ref>` 내부 루프로 수행한다.
  - PR 후 승인 체크는 GitHub status check로 수행한다.
- `@code-reviewer`는 PR 승인 워커가 아니라 반복 failure 메타 리뷰를 담당한다.
- PR 단계의 승인 결과는 GitHub PR review보다 **status check**를 기준으로 merge gate에 반영한다.
- 로컬 worktree 정리는 Codex가 아니라 Claude 측 구현 머신이 담당한다.
- 고위험 변경에서는 diff만 읽고 끝내지 않는다.
  - 생성자, 팩토리, 캐시 저장소, 소비자, 생성 산출물까지 넓혀 본다.
