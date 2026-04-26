# 01. AI 에이전트 기반 개발 프로세스

> Claude Code가 구현을 담당하고, Codex가 구현 전 계획 리뷰와 내부 사전 브랜치 리뷰를 담당하며, PR 단계에서는 두 모델이 독립적으로 승인하는 개발 체계를 정의한다.

---

## 1. 개발 철학

- 주 개발은 Claude Code가 담당한다.
- 스펙 문서(`docs/specs/`)가 설계의 단일 출처(SSOT)다. 변경이 필요하면 **스펙 최신화 → 이슈 발행 → 코드 반영** 순서를 따른다.
- PR은 구현 완료 사실을 알리는 문서가 아니라, **이미 한 차례 Codex 사전 리뷰를 통과한 변경**을 통합 후보로 올리는 단계다.
- 최종 머지 결정은 사람 감각이 아니라 **명시적인 게이트 상태**로 판단한다.
- `docs/specs/`와 `docs/architecture/`는 코드보다 앞선 계약이며, 리뷰와 승인 단계 모두 이 문서를 기준으로 판정한다.
- 구현 전 계획은 **Plan Preflight로 작성**하고, **Codex Plan Review로 검증**한다.
- 리뷰는 수정된 파일 목록만으로 끝내지 않는다.
  - 캐시, 연결, 생성 산출물, 소비자 경로가 보이면 호출자와 후속 경로까지 넓혀 본다.

## 2. 역할 구성

> Claude 측 역할과 `.agent/` 구조 상세: [02-agent-structure.md](02-agent-structure.md)
> CI/CD와 리뷰/승인/머지 게이트 상세: [04-ci-cd.md](04-ci-cd.md)

- **Claude 오케스트레이터**: 이슈 분석, 스펙 확인, 구현 에이전트 위임, GitHub 기록 관리
- **Claude 개발 에이전트**: 구현, 로컬 검증, 브랜치 푸시, Codex 피드백 반영
- **Codex Plan Review 워커**: `/codex:adversarial-review`로 구현 전 계획의 가정, 위험, 대안을 외부 검증
- **Claude 코드 리뷰어**: 구조 리스크 메타 리뷰, 반복 failure 원인 분석
- **Codex 브랜치 리뷰어**: `/codex:review --base <ref>`로 PR 전 브랜치 단위 사전 리뷰와 blocking issue 식별
- **Claude PR 승인 워커**: PR head SHA 기준 최종 승인 체크
- **Codex PR 승인 워커**: PR head SHA 기준 최종 승인 체크
- **GitHub merge gate**: 두 모델 승인과 CI 성공 여부를 기준으로 auto-merge 실행

## 3. 상호작용 흐름

```
사용자 (요구사항/이슈)
  │
  ▼
Claude 오케스트레이터
  │  ◄──── AGENTS.md + docs/specs/* + docs/architecture/*
  │
  ├── 분석: 이슈 읽기 → 스펙 확인 → 스펙 경로(1A/1B) 판단
  │     └── 구현 분석 완료 또는 보류 사유: 이슈 코멘트
  │
  ├──▶ /plan-preflight (Claude 오케스트레이터, `superpowers:writing-plans`)
  │     │
  │     ├── `plan-preflight:started` 라벨 부착 + 시작: 이슈 코멘트
  │     ├── 이슈 본문 구현계획 작성/정비
  │     │    ├── 파일 맵 / 작업 순서 / risk flags
  │     │    ├── 구현 체크리스트 / 검증 체크리스트
  │     │    └── stop conditions / 비목표
  │     │        └── 계획 정비 완료: 이슈 코멘트
  │     │
  │     ├──▶ Codex Plan Review (`/codex:adversarial-review`)
  │     │     ├── 결과 기록: 이슈 코멘트
  │     │     ├── approve-implement → 이슈 본문 구현계획 확정
  │     │     ├── narrow-scope → 축소 범위로 이슈 본문 구현계획 확정
  │     │     ├── revise-plan → Claude가 피드백 반영 후 Codex Plan Review 재요청
  │     │     └── split-issue / invoke-human → 구현 중단 또는 사람 판단
  │     │
  │     ├── needs-spec-first / blocked → 구현 중단 + 보류 사유: 이슈 코멘트
  │     └── 확정 → `plan-preflight:started` 제거 + `plan-preflight:done` 라벨 부착 + 완료: 이슈 코멘트
  │
  ├──▶ /implement-issue (Claude 오케스트레이터)
  │     │
  │     ├── `plan-preflight:done` 및 최신 이슈 본문 구현계획 확인
  │     │    └── 구현 분석 완료: 이슈 코멘트
  │     │
  │     ├──▶ Claude 개발 에이전트 (`@backend-dev` / `@frontend-dev` / `@devops` / `@strategy-dev`)
  │     │     ├── 워크트리 격리
  │     │     ├── 착수 기록: 이슈 코멘트
  │     │     ├── 구현 + 로컬 lint/test
  │     │     └── 로컬 커밋 + 로컬 구현 완료: 이슈 코멘트
  │     │
  │     ├──▶ Codex 브랜치 리뷰 (`/codex:review --base <base>`)
  │     │     ├── 결과 기록: 이슈 코멘트
  │     │     ├── FAIL → Claude 개발 에이전트가 같은 워크트리에서 수정 후 재검토
  │     │     ├── 반복 risk class → Claude `@code-reviewer` 메타 리뷰
  │     │     └── PASS → 브랜치 push
  │     │
  │     └── PR 생성 (`Closes #이슈`) + PR 생성 완료: 이슈 코멘트
  │
  ├──▶ PR 게이트 (GitHub Actions)
  │     ├── CI (`ci`) — required, 머지 차단 게이트
  │     ├── Claude PR 승인 (`claude-pr-approve`) — advisory
  │     ├── Codex PR 승인 (`codex-pr-approve`) — advisory
  │     ├── content FAIL → Claude PR repair 후 같은 PR에서 재검증 (advisory 신호)
  │     └── `ci` green + 충돌 없음 + 대화 해결 → GitHub auto-merge
  │        └── `/autopilot` 실행 중이면 사이클 상태: 이슈 코멘트
  │
  ├──▶ post-merge automation
  │     ├── 이슈 체크박스 갱신 + close + post-merge 완료: 이슈 코멘트
  │     └── 원격 head branch 삭제 (GitHub 설정)
  │
  ├──▶ /release (수동 릴리스 운영, 이슈 기반 흐름 아님)
  │     ├── prepare: release/vX.Y.Z PR 생성 + Docker build 검증
  │     └── publish: release PR merge 후 GitHub Release + PyPI + Docker image 배포
  │
  ├──▶ /autopilot side lane (Claude 오케스트레이터)
  │     └── implementation lane이 바쁠 때 다른 후보 이슈의 `/plan-preflight`만 수행
  │         (코드 수정, 브랜치 생성, PR 생성 금지)
  │         └── Plan Preflight 코멘트 + Autopilot 사이클 상태 코멘트
  │
  ▼
결과 보고
```

**핵심 차이**:
- 구현 전 Plan Preflight는 `/plan-preflight`가 담당하며, `superpowers:writing-plans` 원칙으로 이슈 본문에 구현계획을 작성하거나 정비하고 Codex Plan Review를 외부 게이트로 요청한 뒤 피드백을 반영해 확정한다.
- 이슈 기반 단계의 공식 증적은 이슈 본문, 라벨, 이슈 코멘트에 남긴다. 단계 전환이 코멘트 없이 로컬 메모로만 남으면 안 된다.
- Plan Preflight가 시작된 이슈는 `plan-preflight:started`, 구현계획이 확정된 이슈는 `plan-preflight:done` 라벨로 구분한다.
- `plan-preflight:done`은 최신 이슈 본문 구현계획과 Codex Plan Review의 `approve-implement` 또는 `narrow-scope` verdict가 맞물려 구현 착수 가능한 상태라는 뜻이다.
- 착수 기록은 Codex Plan Review 피드백이 반영된 구현계획이 이슈 본문에 남은 뒤, `/implement-issue` 과정에서 선택된 개발 에이전트가 첫 작업으로 작성한다.
- `/autopilot`은 구현 병렬화를 열지 않고, 구현 lane이 바쁠 때 다른 이슈의 Plan Preflight만 병렬 수행할 수 있다.
- Codex의 첫 리뷰는 **구현 전 Codex Plan Review**이며, 첫 코드 리뷰는 **PR 전 내부 브랜치 리뷰**다.
- PR 전 Codex 브랜치 리뷰는 GitHub Actions가 아니라 `/implement-issue` 안에서 `/codex:review --base <base>`로 반복한다.
- PR 단계의 Claude/Codex 승인 체크는 **같은 head SHA**를 기준으로 독립 실행된다.
- 머지는 Claude 오케스트레이터가 직접 하지 않고, GitHub auto-merge가 수행한다.
- 릴리스는 merge/post-merge와 분리된 수동 운영 lane이며, `/release prepare`가 release PR을 만들고 `/release publish`가 merge된 main에서 배포를 담당한다.

## 4. 작업 실행 체계

에이전트의 구체적인 작업 절차는 `.agent/commands/`에 정의된 커맨드가 단일 출처(SSOT)다.

| 커맨드 | 역할 | 파일 |
|--------|------|------|
| `/plan-preflight` | GitHub 이슈 본문 구현계획 작성/정비 → Codex Plan Review → `plan-preflight:done` 확정 | `.agent/commands/plan-preflight.md` |
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → Plan Preflight 확인 → Codex Plan Review → 구현 → Codex 브랜치 리뷰 → PR 생성) | `.agent/commands/implement-issue.md` |
| `/autopilot` | 오픈 이슈 큐 순차 처리 (선별 → Plan Preflight → `/implement-issue` → merge/post-merge 모니터링, 기본 `limit=10`) | `.agent/commands/autopilot.md` |
| `/release` | prepare: release PR 생성 / publish: GitHub Release + PyPI + Docker image 배포 | `.agent/commands/release.md` |
| `/api-docs` | OpenAPI 스키마 조회 | `.agent/commands/api-docs.md` |

야간 배치나 backlog 정리에서는 `/autopilot`이 오픈 이슈 큐 snapshot을 잡고, 필요 시 Plan Preflight로 이슈 본문 구현계획을 확정한 뒤 `/implement-issue`에 개별 구현을 위임한다. 확정 계획의 tasks, verification, risk flags, stop conditions는 구현 체크리스트로 승격되며, `/autopilot`은 기본적으로 **한 번에 하나의 이슈만 implement → merge/post-merge까지 순차 모니터링**한다. 다만 현재 구현 lane이 코드 수정, 리뷰, CI, merge 대기 중일 때 다른 후보 이슈의 Plan Preflight는 병렬로 수행할 수 있다.
Plan Preflight의 SSOT는 `/plan-preflight`다. Plan Preflight가 완료되면 이슈 본문 구현계획을 최신화한 뒤 `plan-preflight:done` 라벨을 붙이고, 이후 `/implement-issue`는 이 라벨을 단서로 기존 구현계획을 재사용한다.

운영 중인 이슈의 현재 단계는 최신 `🤖 **Autopilot 사이클 상태**` 코멘트로 노출하며, 여기서 `review-state`, `implement-state`, `merge-monitor-state`를 각각 `pending | running | blocked | done`으로 추적한다.

### 4.1 Codex Plan Review

Codex Plan Review는 Claude 내부 사고 절차가 아니라, **Codex plugin의 `/codex:adversarial-review`로 수행하는 외부 read-only 리뷰 게이트**다.
Codex 브랜치 리뷰처럼 요청, 대기, 결과 수신, 수정 루프를 분리해 취급한다.
Plan Preflight가 이슈 본문에 구현계획을 작성하거나 정비한 뒤 Codex Plan Review를 요청하고,
Codex는 그 계획이 구현 가능한지, 더 안전하거나 단순한 대안이 있는지, 숨은 가정이 있는지 검토한다.

- 실행 명령은 `/codex:adversarial-review`다.
- 긴 리뷰는 `/codex:adversarial-review --background`로 시작하고 `/codex:status`, `/codex:result`로 결과를 회수한다.
- focus text에는 이슈 번호, 스펙 경로, 구현계획 요약, 중점 검토 위험을 포함한다.
- 이 단계는 코드를 수정하지 않고, 브랜치나 PR도 만들지 않는다.
- 결과는 이슈 코멘트에 `Codex Plan Review`로 남기고, 필요하면 이슈 본문 구현계획을 갱신한다.

Codex Plan Review의 출력은 다음 중 하나다.

- `approve-implement`
- `revise-plan`
- `narrow-scope`
- `split-issue`
- `invoke-human`

`approve-implement` 또는 `narrow-scope`가 아니면 구현을 시작하지 않는다.
`revise-plan`이면 Plan Preflight가 피드백을 반영해 이슈 본문 구현계획을 보강한 뒤 다시 Codex Plan Review를 요청한다.

### 4.2 브랜치 전략

브랜치 prefix, PR 전제 조건, 에픽 브랜치 정렬 규칙의 SSOT는 [03-git-workflow.md](03-git-workflow.md)다.
이 문서에서는 원칙만 둔다.

- 독립 이슈는 `{branch-prefix}/#{issue번호}-{짧은설명}` 브랜치에서 작업하고 `main`으로 PR을 낸다.
- 에픽은 통합용 `epic/*` 브랜치와 하위 이슈별 작업 브랜치를 분리한다.
- PR 생성 전 최신 HEAD는 내부 `/codex:review --base <base>` PASS 증적을 가져야 한다.
- stale base, duplicate commit, base regression이 보이면 PR 생성이나 리뷰 재시도보다 히스토리 정리를 먼저 한다.

### 4.3 Worktree 격리

모든 구현 작업은 **git worktree**로 격리하여 로컬 main을 보호한다. 생성·재사용·정리 절차의 SSOT는 `/implement-issue`와 [03-git-workflow.md](03-git-workflow.md)다.
공유 `.venv`를 쓰는 경우 로컬 검증이 현재 worktree의 `src/ante`를 import하는지 확인한다.

### 4.4 릴리스 운영

릴리스 정책은 [06-release.md](06-release.md), 실행 절차는 `/release`가 SSOT다.
`/release prepare`는 main 브랜치, 클린 워킹 트리, `origin/main` 동기화, open release PR 여부, 마지막 태그 이후 릴리스 대상 커밋을 확인한 뒤 `release/vX.Y.Z` PR을 만든다.
release PR은 릴리스 메타데이터와 Docker build 검증만 포함하며, merge 전에는 PyPI나 registry에 배포하지 않는다.
`/release publish`는 release PR이 최신 main HEAD로 merge된 뒤 `semantic-release.yml`을 수동 실행하고, GitHub Release가 생성되면 `publish.yml`을 모니터링해 PyPI와 Docker image 배포 결과까지 보고한다.

`/autopilot`, `/implement-issue`, GitHub auto-merge, post-merge automation은 릴리스를 자동으로 시작하지 않는다.
릴리스는 배포 가능한 main 누적 상태를 사람이 확인한 뒤 별도로 실행하는 운영 단계다.

## 5. 실패 복구 루프

구체적 실행 절차와 실패 임계값은 각 하위 프로세스가 SSOT다.
이 섹션은 실패가 어느 프로세스로 돌아가야 하는지와 공통 원칙만 정의한다.

| 실패 유형 | 원인 분류 | 복구 담당 | 복구 후 |
|-----------|----------|----------|--------|
| `/codex:review` FAIL | 코드/설계 문제 | Claude 개발 에이전트 | 같은 브랜치에서 수정 후 재검토 |
| CI 실패 — 코드 문제 | 테스트/lint/type 오류 | Claude 개발 에이전트 | 새 커밋 push 후 체크 재실행 |
| CI 실패 — 인프라 문제 | Docker/CI 설정/스크립트 | `@devops` | 수정 후 동일 PR에서 재실행 |
| `claude-pr-approve` FAIL — `content` | 스펙·계약·테스트 누락 | Claude 자동 재수정 워커 | 동일 PR 브랜치 수정 후 재검증 |
| `codex-pr-approve` FAIL — `content` | 버그/회귀/설계 위반 | Claude 자동 재수정 워커 | 동일 PR 브랜치 수정 후 재검증 |
| `claude-pr-approve` FAIL — `quota/script_error/auth_error/infra_error` | AI CLI/runner 문제 | `@devops` 또는 사람 개입 | 재수정 없이 워커 복구 후 재실행 |
| `codex-pr-approve` FAIL — `quota/script_error/auth_error/infra_error` | AI CLI/runner 문제 | `@devops` 또는 사람 개입 | 재수정 없이 워커 복구 후 재실행 |
| 수용 검증 FAIL | 기능 버그 | 오케스트레이터가 버그 이슈 등록 → Claude 개발 에이전트 | 재검증 속행 |

### 5.1 재시도와 중단 원칙

- 같은 head SHA에서 같은 실패를 반복 판정하지 않는다. 새 커밋이 만들어져야 새 시도로 본다.
- `/codex:review` 실패는 PR 생성 전에 같은 worktree에서 해소한다.
- PR 승인 루프는 `content` 실패만 자동 재수정 대상으로 삼고, `quota`, `script_error`, `auth_error`, `infra_error`는 워커/인프라 복구로 분리한다.
- 자동 수정 전에는 `.agent/skills/receive-review.md` 규칙으로 finding을 재서술하고 영향 범위를 다시 그린다.
- 같은 `risk class`가 반복되거나 구조 리스크가 넓어지면 얕은 자동 수정 대신 `@code-reviewer` 메타 리뷰 또는 사람 확인을 우선한다.
- 반복 리스크가 구현계획 자체의 문제라면 `/plan-preflight`로 돌아가 이슈 본문 구현계획을 다시 정비하고 Codex Plan Review를 재요청한다.
- `blocked:review-loop`, `blocked:pr-review-loop` 라벨은 자동 진행 중단 신호이며, 라벨 의미와 큐 제외 규칙은 [00-issue-management.md](00-issue-management.md)와 `/autopilot`을 따른다.

### 5.2 상세 절차의 SSOT

| 상황 | SSOT |
|------|------|
| Plan Preflight 재정비와 Codex Plan Review 재요청 | `.agent/commands/plan-preflight.md` |
| `/codex:review` 브랜치 리뷰 반복, 실패 횟수, PR 생성 전 PASS 조건 | `.agent/commands/implement-issue.md`, [03-git-workflow.md](03-git-workflow.md) |
| PR 승인 루프, 자동 재수정 예산, `NO_CHANGES`, post-merge 복구 | [04-ci-cd.md](04-ci-cd.md) |
| 리뷰 finding 수용, 영향 범위 재검토, 수정 전략 선택 | `.agent/skills/receive-review.md` |
| `gh run rerun`, PR `close → reopen`, 수동 복구 코멘트 | `.agent/skills/github-ops.md` |
| blocked 라벨 정의 | [00-issue-management.md](00-issue-management.md) |

## 6. 리뷰와 머지 게이트

> 상세 규칙: [04-ci-cd.md](04-ci-cd.md)

- **브랜치 리뷰 단계**: Codex만 수행한다. GitHub Actions가 아니라 `/codex:review --base <ref>` 내부 루프로 도는 PR 전 품질 게이트다.
- **PR 승인 단계**: Claude와 Codex가 각각 독립적으로 수행한다. 두 승인은 advisory check이며 머지 게이트 입력이 아니다.
- **메타 리뷰 단계**: `@code-reviewer`는 상시 게이트가 아니라, 고위험 변경과 반복 failure에서만 호출한다.
- **소스 오브 트루스**: 브랜치 리뷰는 이슈 코멘트의 최신 `/codex:review` PASS 기록을 PR 생성 조건으로 삼고, merge gate는 **`ci` status check + 충돌 없음 + 대화 해결**을 기준으로 삼는다. AI 승인 status check는 advisory 신호이며 머지 가능 여부 판정에 들어가지 않는다.
- **머지 담당**: GitHub auto-merge
- **이슈 close**: PR 본문의 `Closes #N`으로 GitHub 기본 auto-close를 우선 사용하고, `post-merge`가 체크박스/에픽 동기화와 수동 복구를 맡는다.
- **원격 브랜치 삭제**: GitHub의 "Automatically delete head branches" 기능 사용
- **로컬 worktree 정리**: Claude 측에서 후속 작업 시 `git worktree prune` 또는 명시적 remove

## 7. 생성 문서 동기화 규칙

생성 문서와 스크립트의 SSOT는 [docs/architecture/generated/](../architecture/generated/) 및 각 생성 스크립트다.
이 문서에서는 원칙만 둔다.

- CLI, DB DDL, 프로젝트 구조처럼 생성 산출물의 입력이 바뀌면 해당 생성 문서도 같은 작업에서 갱신한다.
- 스크립트로 생성되는 문서는 수동 편집하지 않는다.
- Plan Preflight와 리뷰 단계에서 generated artifact sync 위험을 발견하면 구현 체크리스트에 포함한다.

## 8. API 스키마 변경 규칙

API 스키마 계약의 상세 SSOT는 [docs/dashboard/architecture.md](../dashboard/architecture.md), `src/ante/web/schemas.py`, OpenAPI 생성물이다.
이 문서에서는 프로세스 원칙만 둔다.

- API 응답 스키마 변경은 백엔드와 프론트엔드 양쪽에 영향을 주는 계약 변경으로 본다.
- 구현 이슈 진행 중 스키마 변경이 드러나면 Plan Preflight에서 별도 이슈 분리 또는 `needs-spec-first` 전환을 판단한다.
- 새 엔드포인트와 응답 변경은 생성 타입 동기화까지 검증 계획에 포함한다.

## 9. AGENTS.md 경량화 원칙

AGENTS.md는 모든 세션에 주입되므로 핵심 규칙만 유지한다.

- 핵심 설계 원칙, 기술 스택, 디렉토리 구조만 유지
- 모듈별 세부 설계는 `docs/specs/`에 분리
- 상세 가이드는 `.agent/skills/`로 분리

## 관련 문서

| 문서 | 내용 |
|------|------|
| [00-issue-management.md](00-issue-management.md) | 이슈 등록, 분류, 추적 규칙 |
| [02-agent-structure.md](02-agent-structure.md) | Claude 역할과 Codex 외부 리뷰 워커 구조 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션, 브랜치/PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인, 리뷰/승인/merge gate 구성 |
| [05-testing.md](05-testing.md) | 테스트 전략, 커버리지 기준 |
| [06-release.md](06-release.md) | release PR, 버전 관리, PyPI/Docker 배포 |
