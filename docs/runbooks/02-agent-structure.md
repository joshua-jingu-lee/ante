# 02. 에이전트 구조 및 `.agent/` 디렉토리

> Claude 측 역할 정의와 `.agent/` 디렉토리 구성을 정의한다.
> Codex는 `.agent/` 내부 에이전트가 아니라 GitHub 이벤트에 반응하는 외부 리뷰 워커로 취급한다.

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
- 경량 계획 체크리스트 작성과 조건부 계획 리뷰 여부 판단
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
- 조건부 계획 리뷰가 required면 verdict가 나기 전까지 구현을 시작하지 않음
- Codex 브랜치 리뷰 또는 PR 승인 실패 시 같은 브랜치에서 수정

### 1.3 프론트엔드 개발자 (`@frontend-dev`)

**담당**: 대시보드(React) 구현

- `docs/dashboard/architecture.md` 기준으로 구현
- API 계약은 백엔드 OpenAPI와 자동 생성 타입을 기준으로 사용

### 1.4 QA 엔지니어 (`@qa-engineer`)

**담당**: Gherkin TC 실행, Docker QA 환경 테스트, 버그 리포트

### 1.5 DevOps 엔지니어 (`@devops`)

**담당**: Docker, GitHub Actions, CI/CD, QA 환경 관리

- 리뷰 게이트와 merge automation을 포함한 GitHub Actions 구성 관리
- `pyproject.toml` dependencies 변경 시 사용자 확인 필수

### 1.6 전략 개발자 (`@strategy-dev`)

**담당**: 매매 전략 개발, 데이터 탐색, 백테스트

### 1.7 코드 리뷰어 (`@code-reviewer`)

**담당**: 조건부 계획 리뷰, 계획 정합성 검토, 구조 리스크 메타 리뷰, 반복 review failure 원인 분석

- `review-pr.md`와 역할이 겹치지 않는다.
- PR 승인 워커처럼 approve / fail 게이트를 직접 집행하지 않는다.
- 대신 아래 상황에서 오케스트레이터가 호출한다.
  - 구현 시작 전 경량 계획 체크리스트에서 고위험 조건이 감지
  - 캐시, 세션, 연결, long-lived adapter, mutable config 변경
  - OpenAPI, 생성 타입, 생성 문서, schema drift 위험
  - 같은 `risk class` failure가 2회 반복
  - PR 자동 재수정 전에 "무엇을 먼저 고쳐야 하는지"가 불명확
- 조건부 계획 리뷰 verdict:
  - `approve-implement`
  - `narrow-scope`
  - `split-issue`
  - `invoke-human`

### 1.8 Codex 외부 워커

Codex는 `.agent/` 내부 에이전트가 아니라 GitHub 이벤트에 반응하는 외부 자동화 워커다.

| 역할 | 트리거 | 책임 |
|------|--------|------|
| **Codex 브랜치 리뷰어** | feature/fix/refactor 브랜치 push | PR 전 blocking issue 식별, `codex-branch-review` 상태 기록 |
| **Codex PR 승인 워커** | `pull_request` opened/synchronize/ready_for_review | 최종 승인 체크, `codex-pr-approve` 상태 기록 |

### 1.9 Claude PR 승인 워커

Claude도 PR 단계에서는 독립 승인 워커로 동작한다.

| 역할 | 트리거 | 책임 |
|------|--------|------|
| **Claude PR 승인 워커** | `pull_request` opened/synchronize/ready_for_review | 최종 승인 체크, `claude-pr-approve` 상태 기록 |

## 2. `.agent/` 및 `.claude/` 디렉토리 구조

### 2.1 전체 구조

```
.agent/
├── agents/                # Claude 측 역할 정의 (정식 위치)
│   ├── backend-dev.md         # @backend-dev
│   ├── frontend-dev.md        # @frontend-dev
│   ├── qa-engineer.md         # @qa-engineer
│   ├── devops.md              # @devops
│   ├── strategy-dev.md        # @strategy-dev
│   └── code-reviewer.md       # @code-reviewer — 조건부 계획 리뷰 / 구조 리스크 메타 리뷰
├── commands/              # 커스텀 슬래시 명령어 (작업 절차 SSOT)
│   ├── implement-issue.md     # /implement-issue
│   ├── qa-test.md             # /qa-test
│   ├── qa-sweep.md            # /qa-sweep
│   ├── api-docs.md            # /api-docs
│   ├── arch-review.md         # /arch-review
│   └── qa-review.md           # /qa-review
└── skills/                # 도메인 지식 스킬
    ├── module-conventions.md
    ├── asyncio-patterns.md
    ├── sqlite-patterns.md
    ├── frontend-conventions.md
    ├── review-pr.md           # PR 승인 공통 체크리스트 계약
    ├── lightweight-planning.md
    ├── receive-review.md
    ├── lifecycle-review.md    # 캐시/세션/연결/설정 변경 리뷰
    ├── contract-drift-review.md
    ├── generated-artifact-sync.md
    └── qa-tester/

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

`.agent/agents/*.md`는 Claude 서브에이전트 정의의 SSOT이다. Codex 워커는 GitHub Actions/Webhook 구성의 일부이므로 이 디렉토리에 포함하지 않는다.

### 2.3 커스텀 명령어 (commands/)

반복적인 개발 작업을 슬래시 명령으로 정의한다:

- `/implement-issue #{번호}` — 분석 → 경량 계획 → 조건부 계획 리뷰(필요 시) → 구현 → Codex 브랜치 리뷰 → PR 생성
- `/qa-test {카테고리}` — 지정 TC 실행
- `/qa-sweep` — 전체 TC 전수 검사
- `/api-docs` — OpenAPI 스키마 조회
- `/arch-review`, `/qa-review` — 이슈 사전 점검용 보조 커맨드

### 2.4 도메인 스킬 (skills/)

- **백엔드**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
- **프론트엔드**: `frontend-conventions`
- **리뷰 공통 규약**: `review-pr`
- **구현 품질 보조 스킬**:
  - `lightweight-planning`
  - `receive-review`
- **리뷰 세부 플레이북**:
  - `lifecycle-review`
  - `contract-drift-review`
  - `generated-artifact-sync`
- **QA**: `qa-tester/`

`review-pr.md`는 Claude/Codex PR 승인 워커가 공유하는 최종 승인 계약 문서다.
`code-reviewer.md`는 그보다 앞단의 조건부 계획 리뷰 / 구조 리스크 메타 리뷰 정의다.

### 2.5 권한 및 Hooks (settings.json)

- **permissions**: Claude 측 에이전트가 실행 가능한 도구와 명령을 제한
- **hooks**: 파일 수정 시 자동 포맷팅(`auto-format.sh`), 보호 파일 검사(`protect-files.sh`)

## 3. 운영 상 주의사항

- Codex는 PR 전 브랜치 리뷰와 PR 후 승인 체크를 모두 담당하지만, 두 단계의 목적은 다르다.
- `@code-reviewer`는 PR 승인 워커가 아니라, 구현 시작 전 계획 게이트와 반복 failure 메타 리뷰를 담당한다.
- PR 단계의 승인 결과는 GitHub PR review보다 **status check**를 기준으로 merge gate에 반영한다.
- 로컬 worktree 정리는 Codex가 아니라 Claude 측 구현 머신이 담당한다.
- 고위험 변경에서는 diff만 읽고 끝내지 않는다.
  - 생성자, 팩토리, 캐시 저장소, 소비자, 생성 산출물까지 넓혀 본다.
