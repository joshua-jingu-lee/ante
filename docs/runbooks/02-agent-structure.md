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
- 적절한 Claude 서브에이전트 위임
- 이슈/브랜치/PR GitHub 기록 관리
- Codex 브랜치 리뷰 결과를 받아 수정 루프 조율
- PR 생성 후 최종 상태를 사용자에게 보고

**하지 않는 일**:
- 기본 운영 모델에서는 직접 머지하지 않는다.
- 기본 운영 모델에서는 `.agent/agents/code-reviewer.md`를 호출하지 않는다.

### 1.2 백엔드 개발자 (`@backend-dev`)

**담당**: Python 백엔드 구현

- `docs/specs/` 설계 문서를 따라 구현, 테스트 작성, 로컬 검증, 브랜치 push까지 수행
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

### 1.7 Codex 외부 워커

Codex는 `.agent/` 내부 에이전트가 아니라 GitHub 이벤트에 반응하는 외부 자동화 워커다.

| 역할 | 트리거 | 책임 |
|------|--------|------|
| **Codex 브랜치 리뷰어** | feature/fix/refactor 브랜치 push | PR 전 blocking issue 식별, `codex-branch-review` 상태 기록 |
| **Codex PR 승인 워커** | `pull_request` opened/synchronize/ready_for_review | 최종 승인 체크, `codex-pr-approve` 상태 기록 |

### 1.8 Claude PR 승인 워커

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
│   └── code-reviewer.md       # deprecated — legacy Claude PR reviewer
├── commands/              # 커스텀 슬래시 명령어 (작업 절차 SSOT)
│   ├── implement-issue.md     # /implement-issue
│   ├── qa-test.md             # /qa-test
│   ├── qa-sweep.md            # /qa-sweep
│   ├── api-docs.md            # /api-docs
│   ├── arch-review.md         # /arch-review
│   ├── qa-review.md           # /qa-review
│   └── autopilot.md           # deprecated — legacy command
└── skills/                # 도메인 지식 스킬
    ├── module-conventions.md
    ├── asyncio-patterns.md
    ├── sqlite-patterns.md
    ├── frontend-conventions.md
    ├── review-pr.md           # PR 승인 공통 체크리스트 계약
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

- `/implement-issue #{번호}` — 분석 → 구현 → Codex 브랜치 리뷰 → PR 생성
- `/qa-test {카테고리}` — 지정 TC 실행
- `/qa-sweep` — 전체 TC 전수 검사
- `/api-docs` — OpenAPI 스키마 조회
- `/arch-review`, `/qa-review` — 이슈 사전 점검용 보조 커맨드

`/autopilot`은 더 이상 기본 워크플로우에 포함되지 않으며 삭제 예정이다.

### 2.4 도메인 스킬 (skills/)

- **백엔드**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
- **프론트엔드**: `frontend-conventions`
- **리뷰 공통 규약**: `review-pr`
- **QA**: `qa-tester/`

`review-pr.md`는 특정 에이전트 전용이 아니라, Claude/Codex PR 승인 워커가 공유하는 체크리스트 계약 문서로 취급한다.

### 2.5 권한 및 Hooks (settings.json)

- **permissions**: Claude 측 에이전트가 실행 가능한 도구와 명령을 제한
- **hooks**: 파일 수정 시 자동 포맷팅(`auto-format.sh`), 보호 파일 검사(`protect-files.sh`)

## 3. 운영 상 주의사항

- Codex는 PR 전 브랜치 리뷰와 PR 후 승인 체크를 모두 담당하지만, 두 단계의 목적은 다르다.
- PR 단계의 승인 결과는 GitHub PR review보다 **status check**를 기준으로 merge gate에 반영한다.
- 로컬 worktree 정리는 Codex가 아니라 Claude 측 구현 머신이 담당한다.
