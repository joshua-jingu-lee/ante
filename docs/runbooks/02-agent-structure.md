# 02. 에이전트 구조 및 `.agent/` 디렉토리

> 선택적 내부 adapter인 Claude 측 역할 정의와 `.agent/` 디렉토리 구성을 정의한다. `.agent/`와 `.claude/`는 maintainer/collaborator 내부 lane에서만 사용한다.
> 계획 리뷰(`@plan-reviewer`)와 이슈 검증(`@issue-reviewer`)은 `.agent/agents/`의 Claude 서브에이전트이고, PR 전 브랜치 리뷰는 Claude Code 네이티브 `/code-review`가 담당한다.

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
- Plan Preflight 산출물 확인, `plan-preflight:started`/`plan-preflight:done` 라벨 관리, Plan Review(`@plan-reviewer`) 요청/결과 조율
- 야간 `/autopilot` 배치에서 이슈 큐 snapshot, Plan Preflight, 구현 위임, merge 모니터링 조율
- 적절한 Claude 서브에이전트 위임
- 이슈/브랜치/PR GitHub 기록 관리
- 브랜치 리뷰(`/code-review`) 결과를 받아 수정 루프 조율
- PR 생성 후 최종 상태를 사용자에게 보고

**하지 않는 일**:
- 기본 운영 모델에서는 직접 머지하지 않는다.
- 모든 PR마다 `@code-reviewer`를 자동 호출하지 않는다.
  - 다만 고위험 변경이나 반복 failure가 나오면 명시적으로 호출한다.

### 1.2 백엔드 개발자 (`@backend-dev`)

**담당**: Python 백엔드 구현

- `docs/specs/` 설계 문서를 따라 구현, 테스트 작성, 로컬 검증, 브랜치 push까지 수행
- Plan Review verdict가 나기 전까지 구현을 시작하지 않음
- 브랜치 리뷰(`/code-review`) 실패 시 같은 브랜치에서 수정

### 1.3 DevOps 엔지니어 (`@devops`)

**담당**: Docker, GitHub Actions, CI/CD, 배포 환경 관리

- 리뷰 게이트와 merge automation을 포함한 GitHub Actions 구성 관리
- `pyproject.toml` dependencies 변경 시 사용자 확인 필수

### 1.4 전략 개발자 (`@strategy-dev`)

**담당**: 매매 전략 개발, 데이터 탐색, 백테스트

### 1.5 코드 리뷰어 (`@code-reviewer`)

**담당**: 구조 리스크 메타 리뷰, 반복 review failure 원인 분석

- `review-pr.md`와 역할이 겹치지 않는다.
- 자동 PR 승인 게이트를 집행하지 않는다.
- 대신 아래 상황에서 오케스트레이터 또는 사용자가 명시적으로 호출한다.
  - 캐시, 세션, 연결, long-lived adapter, mutable config 변경
  - OpenAPI, 생성 타입, 생성 문서, schema drift 위험
  - 같은 `risk class` failure가 2회 반복
  - 다음 시도 전에 "무엇을 먼저 검증해야 하는지"가 불명확

### 1.6 계획 리뷰어 (`@plan-reviewer`)

**담당**: 구현 착수 전 Plan Review (Gate 0)

- 구현 세션과 격리된 별도 컨텍스트에서 이슈 본문 Implementation Plan을 read-only로 검토한다.
- verdict(`approve-implement` / `narrow-scope` / `revise-plan` / `split-issue` / `invoke-human`)와 근거를 반환하고, 오케스트레이터가 `Plan Review` 이슈 코멘트로 증적을 남긴다.
- 명시적 반려 권한을 가지지만 코드·이슈 본문·라벨을 직접 수정하지 않는다. 정의는 `.agent/agents/plan-reviewer.md`.

### 1.7 이슈 검증 에이전트 (`@issue-reviewer`)

**담당**: 협업자 또는 내부 자동화가 등록한 미검증 버그 후보의 진실성·재현 가능성 검증

- 협업자 또는 내부 자동화가 등록한 미검증 버그 후보(예: `source:ante-oracle` 자동 리포트)에 한해, 구현 착수 전 루트원인이 실제 코드와 일치하는지와 재현 가능성을 read-only로 검토한다. 상시 게이트가 아니며 내부 기획 이슈에는 적용하지 않는다.
- `@issue-reviewer`는 read-only로 verdict(`confirmed` / `not-reproduced` / `invalid` / `needs-info`)와 근거를 반환하고, 오케스트레이터가 그 verdict에 따라 `이슈 검증` 이슈 코멘트를 남기고 `confirmed`가 아니면 `needs-triage`를 부착한다(자동 close 없음). `@issue-reviewer` 자신은 코드·이슈 본문·라벨을 직접 수정하지 않는다. 정의는 `.agent/agents/issue-reviewer.md`.

### 1.8 브랜치 리뷰와 머지 게이트

- PR 전 브랜치 리뷰(Gate A)는 `.agent/` 에이전트가 아니라 Claude Code 네이티브 `/code-review`로 수행한다. `/implement-issue`의 PR 생성 전 내부 루프로 돌며, PASS/FAIL 판정·시도 횟수 누적·반복 실패 시 `blocked:review-loop` 차단 계약을 그대로 유지한다. PR 후 추가 변경은 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출한다.
- PR 단계의 자동 AI 승인/재수정 워커(과거 운영하던 PR 승인·자동 수정 봇)는 운영하지 않는다. 머지 게이트는 required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT)와 `merge-gate`만 본다.

## 2. `.agent/` 및 `.claude/` 디렉토리 구조

### 2.1 전체 구조

```
.agent/
├── agents/                # Claude 측 역할 정의 (정식 위치)
│   ├── backend-dev.md         # @backend-dev
│   ├── devops.md              # @devops
│   ├── strategy-dev.md        # @strategy-dev
│   ├── code-reviewer.md       # @code-reviewer — 구조 리스크 메타 리뷰
│   ├── plan-reviewer.md       # @plan-reviewer — 구현 전 Plan Review (Gate 0)
│   └── issue-reviewer.md      # @issue-reviewer — 내부 생성 미검증 버그 후보 검증
├── commands/              # 커스텀 슬래시 명령어 (작업 절차 SSOT)
│   ├── plan-preflight.md      # /plan-preflight
│   ├── implement-issue.md     # /implement-issue
│   ├── autopilot.md           # /autopilot
│   └── release.md             # /release
└── skills/                # 도메인 지식 스킬
    ├── module-conventions.md
    ├── asyncio-patterns.md
    ├── sqlite-patterns.md
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
├── agents -> ../.agent/agents
├── commands -> ../.agent/commands
└── skills -> ../.agent/skills
```

### 2.2 에이전트 정의 (agents/)

`.agent/agents/*.md`는 Claude 서브에이전트 정의의 SSOT이며, `@plan-reviewer`·`@issue-reviewer`도 여기 포함된다. PR 전 브랜치 리뷰는 에이전트가 아니라 Claude Code 네이티브 `/code-review` 커맨드이므로 이 디렉토리에 정의하지 않는다.

### 2.2.1 모델 및 추론 강도 정책

- frontmatter의 `model:`은 **단일 기본 모델**만 기록한다. 현재 운영 기준으로 복수 모델 배열은 지원하지 않는다.
- `reasoning effort`는 frontmatter에 고정하지 않고, **오케스트레이터가 호출 시점에 작업 위험도에 따라 선택**한다.
- 즉, 에이전트 문서는 "역할"을 정의하고, 모델/effort는 "운영 정책"으로 관리한다.
- 문서에서 쓰는 `xhigh`는 **최고 추론 단계**를 뜻한다. 실행 환경이나 모델별 UI에서는 `max`로 보일 수 있다.
- 특정 모델이 `xhigh`라는 정확한 라벨을 지원하지 않으면, **그 모델이 지원하는 최고 단계**로 해석한다.

| 에이전트 | 기본 effort | 높여야 하는 경우 | 낮춰도 되는 경우 |
|------|------|------|------|
| `@backend-dev` | `high` | 캐시/세션/연결/설정 변경, 계약 rename, 2개 이상 모듈 소비자 영향, Plan Review 고위험 판정 | 리뷰 finding이 매우 구체적이고 1~2파일 follow-up인 경우 |
| `@devops` | `high` | CI/CD, 인증, secret, release, merge automation, 운영 스크립트 변경 | 문서성 변경, 작은 경로 수정 |
| `@strategy-dev` | `xhigh` (`max`) | 새 전략 설계, 파라미터 탐색, 지표 해석, 백테스트 결과 비교 | 단순 validation rerun, 리포트 포맷 정리 |
| `@code-reviewer` | `xhigh` (`max`) | 반복 risk class failure, lifecycle/contract drift, 범위 축소/이슈 분할/사람 에스컬레이션 판단 | finding이 매우 국소적인 경우 |

- `@code-reviewer`만 항상 더 무겁게 두는 것이 아니라, **고위험 백엔드/DevOps 작업도 `xhigh`까지 올릴 수 있다.**
- 반대로 `low`는 품질 게이트 판단보다는 **정형 실행·수집 작업**에 한정한다.

### 2.3 커스텀 명령어 (commands/)

반복적인 개발 작업을 슬래시 명령으로 정의한다:

- `/plan-preflight #{번호}` — 이슈 본문 구현계획 작성/정비 → Plan Review → `plan-preflight:done` 확정
- `/implement-issue #{번호}` — 분석 → Plan Preflight 확인 → Plan Review → 구현 → 브랜치 리뷰 → PR 생성
- `/autopilot` — 오픈 이슈 큐 snapshot → 필요 시 Plan Preflight → `/implement-issue` → merge/post-merge 순차 모니터링
- `/release` — prepare로 release PR 생성, publish로 GitHub Release/PyPI/Docker image 배포

### 2.4 도메인 스킬 (skills/)

- **백엔드**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
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

`review-pr.md`는 수동 PR 검토와 브랜치 리뷰(`/code-review`)가 공유하는 체크리스트 계약 문서다.
Plan Review는 `.agent/skills/`가 아니라 `.agent/agents/plan-reviewer.md` 서브에이전트로 수행한다.
`code-reviewer.md`는 구조 리스크 메타 리뷰 정의다.

### 2.5 권한 (settings.json)

- **permissions.deny**: 보호 파일 쓰기를 차단한다. 현재 `CLAUDE.md`/`AGENTS.md`
  (및 `**/CLAUDE.md`·`**/AGENTS.md`)에 대한 `Edit`/`Write`를 deny로 막는다.
- **permissions.allow**: Claude 측 에이전트가 실행 가능한 도구·Bash 명령을
  allowlist로 제한한다.
- hooks(auto-format/protect-files)와 `.claude/hooks/` 디렉토리는 현재 사용하지
  않는다 — 파일 보호는 위 `permissions.deny`로 구현한다.

## 3. 운영 상 주의사항

- 리뷰 게이트: PR 전 코드 품질 게이트(브랜치 리뷰, Gate A)는 네이티브 `/code-review`가, 구현 전 계획 검증(Plan Review, Gate 0)은 `@plan-reviewer`가 담당한다.
  - PR 전 브랜치 리뷰는 GitHub Actions가 아니라 Claude 세션의 `/code-review` 내부 루프로 수행한다.
  - Plan Review는 구현 세션과 격리된 별도 컨텍스트 `@plan-reviewer` 서브에이전트로 호출하는 read-only 리뷰다.
- PR 후 자동 AI 승인/감사 워커는 운영하지 않는다. 추가 검증이 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출한다.
- `@code-reviewer`는 자동 PR 승인 워커가 아니라 반복 failure와 구조 리스크에 대한 메타 리뷰를 담당한다.
- 머지 게이트는 GitHub PR review나 AI status check가 아니라 **required status checks(`ci`, `lint`, `test` — 집합은 [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate`** 결과를 기준으로 한다.
- 로컬 worktree 정리는 리뷰 게이트가 아니라 Claude 측 구현 머신이 담당한다.
- 고위험 변경에서는 diff만 읽고 끝내지 않는다.
  - 생성자, 팩토리, 캐시 저장소, 소비자, 생성 산출물까지 넓혀 본다.
