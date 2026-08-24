# 01. AI 에이전트 기반 개발 프로세스

> 이 문서의 전체 절차는 maintainer/collaborator의 내부 lane이다. Claude Code는 선택적 내부 adapter이며, 구현 전 계획 리뷰(Gate 0)는 별도 컨텍스트 `@plan-reviewer`가, PR 전 브랜치 리뷰(Gate A)는 Claude Code 네이티브 `/code-review`가 담당한다. PR 단계의 자동 AI 승인 워커는 운영하지 않으며, 머지는 required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate` + 사람/오케스트레이터 판단으로 결정한다.

---

## 1. 개발 철학

외부 기여는 D-020에 따라 issue, Gate 0, Gate A 없이 fork PR → 공개 CI → maintainer 판단 경로를 따른다. 외부 공개 이슈는 받지 않는다.

- 주 개발은 Claude Code가 담당한다.
- 스펙 문서(`docs/specs/`)가 설계의 단일 출처(SSOT)다. 변경이 필요하면 **스펙 최신화 → 이슈 발행 → 코드 반영** 순서를 따른다.
- PR은 구현 완료 사실을 알리는 문서가 아니라, **이미 한 차례 사전 브랜치 리뷰(`/code-review`)를 통과한 변경**을 통합 후보로 올리는 단계다.
- 최종 머지 결정은 사람 감각이 아니라 **명시적인 게이트 상태**로 판단한다.
- `docs/specs/`와 `docs/architecture/`는 코드보다 앞선 계약이며, 리뷰와 승인 단계 모두 이 문서를 기준으로 판정한다.
- 구현 전 계획은 **Plan Preflight로 작성**하고, **Plan Review로 검증**한다.
- 리뷰는 수정된 파일 목록만으로 끝내지 않는다.
  - 캐시, 연결, 생성 산출물, 소비자 경로가 보이면 호출자와 후속 경로까지 넓혀 본다.

## 2. 역할 구성

> Claude 측 역할과 `.agent/` 구조 상세: [02-agent-structure.md](02-agent-structure.md)
> CI/CD와 리뷰/승인/머지 게이트 상세: [04-ci-cd.md](04-ci-cd.md)

- **Claude 오케스트레이터**: 이슈 분석, 스펙 확인, 구현 에이전트 위임, GitHub 기록 관리
- **Claude 개발 에이전트**: 구현, 로컬 검증, 브랜치 푸시, 리뷰 피드백 반영
- **계획 리뷰어 (`@plan-reviewer`)**: 별도 컨텍스트에서 구현 전 계획의 가정, 위험, 대안을 read-only로 검토 (Gate 0)
- **브랜치 리뷰 (`/code-review`)**: Claude Code 네이티브 리뷰로 PR 전 브랜치 단위 코드 품질 게이트 수행 (Gate A)
- **Claude 코드 리뷰어 (`@code-reviewer`)**: 구조 리스크 메타 리뷰, 반복 failure 원인 분석 (수동/오케스트레이터 호출)
- **이슈 검증 (`@issue-reviewer`)**: 협업자 또는 내부 자동화가 등록한 미검증 버그 후보에 한해 구현 착수 전 루트원인 진실성·재현 가능성을 read-only로 검증 (상시 게이트 아님)
- **GitHub merge gate**: required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) 통과와 충돌 없음·대화 해결·auto-merge 활성화 가능 상태를 기준으로 auto-merge 집행

## 3. 상호작용 흐름

각 단계의 실제 절차는 `.agent/commands/`가 SSOT다. 여기서는 이슈 하나가 거치는 단계와 소유 커맨드·게이트만 요약한다.

1. **분석** (오케스트레이터, `AGENTS.md` + `docs/specs/*` + `docs/architecture/*` 기준): 이슈 읽기 → 스펙 확인 → 스펙 경로(1A/1B) 판단. 증적은 `구현 분석 완료` 또는 보류 사유 이슈 코멘트.
2. **Plan Preflight + Plan Review (Gate 0)** — `/plan-preflight`: `plan-preflight:started` 부착 → 이슈 본문 Implementation Plan(파일 맵/작업 순서/risk flags/검증/stop conditions/비목표) 작성·정비 → 별도 컨텍스트 `@plan-reviewer`가 계획을 read-only로 검토해 verdict를 반환하고, 오케스트레이터가 이를 `Plan Review` 코멘트로 남김. `approve-implement`/`narrow-scope`면 `plan-preflight:started` 제거 후 `plan-preflight:done` 확정, `revise-plan`이면 보강 후 재요청, `split-issue`/`invoke-human`/`needs-spec-first`/`blocked`이면 구현 중단.
3. **구현 + 브랜치 리뷰 (Gate A)** — `/implement-issue`: `plan-preflight:done`과 최신 계획 확인 → 개발 에이전트(`@backend-dev`/`@devops`/`@strategy-dev`)가 worktree 격리 후 구현·로컬 lint/test·커밋 → 네이티브 `/code-review`로 PR 전 브랜치 리뷰(PASS까지 내부 반복, FAIL은 같은 worktree에서 수정, 반복 risk class는 `@code-reviewer` 메타 리뷰) → PASS 시 브랜치 push + PR 생성(`Closes #이슈`). 각 전환은 이슈 코멘트로 남긴다.
4. **PR 게이트** (GitHub Actions): required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate`가 충돌 없음·대화 해결·auto-merge 가능 상태에서 **`AUTOMERGE_TOKEN`(PAT)로 auto-merge를 활성화**한다(#2437, fail-closed). 머지가 발화한 `pull_request: closed` 이벤트로 `post-merge.yml`이 트리거된다(dispatch·폴링 없음). `/autopilot` 실행 중이면 사이클 상태 코멘트를 갱신한다.
5. **post-merge automation**: 이슈 체크박스 갱신 + close + `Post-merge 정리 완료` 코멘트, 원격 head branch 삭제(GitHub 설정).
6. **/autopilot side lane** (오케스트레이터): implementation lane이 바쁠 때 다른 후보 이슈의 `/plan-preflight`만 병렬 수행한다(코드 수정·브랜치·PR 생성 금지). Plan Preflight 코멘트 + Autopilot 사이클 상태 코멘트를 남긴다.
7. **/release** (수동 운영, 이슈 흐름 아님): prepare로 `release/vX.Y.Z` PR 생성 + Docker build 검증, publish로 release PR merge 후 GitHub Release + PyPI + Docker image 배포.

협업자 또는 내부 자동화가 등록한 미검증 버그 후보는 1 이전에 `이슈 검증`(`@issue-reviewer`, read-only)을 선행한다. 상시 게이트가 아니며, 세부 큐 연동은 [00-issue-management.md](00-issue-management.md)와 `.agent/commands/autopilot.md`를 따른다.

**핵심 차이**:
- 구현 전 Plan Preflight는 `/plan-preflight`가 담당하며, `superpowers:writing-plans` 원칙으로 이슈 본문에 구현계획을 작성하거나 정비하고 Plan Review를 별도 컨텍스트 게이트(`@plan-reviewer`)로 요청한 뒤 피드백을 반영해 확정한다.
- 이슈 기반 단계의 공식 증적은 이슈 본문, 라벨, 이슈 코멘트에 남긴다. 단계 전환이 코멘트 없이 로컬 메모로만 남으면 안 된다.
- Plan Preflight가 시작된 이슈는 `plan-preflight:started`, 구현계획이 확정된 이슈는 `plan-preflight:done` 라벨로 구분한다.
- `plan-preflight:done`은 최신 이슈 본문 구현계획과 Plan Review의 `approve-implement` 또는 `narrow-scope` verdict가 맞물려 구현 착수 가능한 상태라는 뜻이다.
- 착수 기록은 Plan Review 피드백이 반영된 구현계획이 이슈 본문에 남은 뒤, `/implement-issue` 과정에서 선택된 개발 에이전트가 첫 작업으로 작성한다.
- `/autopilot`은 구현 병렬화를 열지 않고, 구현 lane이 바쁠 때 다른 이슈의 Plan Preflight만 병렬 수행할 수 있다.
- 첫 계획 리뷰는 **구현 전 Plan Review(Gate 0)**이며, 첫 코드 리뷰는 **PR 전 브랜치 리뷰(Gate A)**다.
- PR 전 브랜치 리뷰는 GitHub Actions가 아니라 `/implement-issue` 안에서 네이티브 `/code-review`로 반복하며, 이 단계가 코드 품질 게이트다.
- PR 단계에서는 자동 AI 승인 워커가 동작하지 않는다. 머지 가능 여부는 required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate` + 사람/오케스트레이터 판단으로 결정한다. 추가 AI 감사가 필요하면 별도 수동 절차로 분리한다.
- 머지는 Claude 오케스트레이터가 직접 하지 않고, GitHub auto-merge가 수행한다.
- 릴리스는 merge/post-merge와 분리된 수동 운영 lane이며, `/release prepare`가 release PR을 만들고 `/release publish`가 merge된 main에서 배포를 담당한다.

## 4. 작업 실행 체계

에이전트의 구체적인 작업 절차는 `.agent/commands/`에 정의된 커맨드가 단일 출처(SSOT)다.

| 커맨드 | 역할 | 파일 |
|--------|------|------|
| `/plan-preflight` | GitHub 이슈 본문 구현계획 작성/정비 → Plan Review → `plan-preflight:done` 확정 | `.agent/commands/plan-preflight.md` |
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → Plan Preflight 확인 → Plan Review → 구현 → 브랜치 리뷰 → PR 생성) | `.agent/commands/implement-issue.md` |
| `/autopilot` | 오픈 이슈 큐 순차 처리 (선별 → Plan Preflight → `/implement-issue` → merge/post-merge 모니터링, 기본 `limit=10`, 최대 `limit=25`) | `.agent/commands/autopilot.md` |
| `/release` | prepare: release PR 생성 / publish: GitHub Release + PyPI + Docker image 배포 | `.agent/commands/release.md` |

야간 배치나 backlog 정리에서는 `/autopilot`이 오픈 이슈 큐 snapshot을 잡고, 필요 시 Plan Preflight로 이슈 본문 구현계획을 확정한 뒤 `/implement-issue`에 개별 구현을 위임한다. 확정 계획의 tasks, verification, risk flags, stop conditions는 구현 체크리스트로 승격되며, `/autopilot`은 기본적으로 **한 번에 하나의 이슈만 implement → merge/post-merge까지 순차 모니터링**한다. 다만 현재 구현 lane이 코드 수정, 리뷰, CI, merge 대기 중일 때 다른 후보 이슈의 Plan Preflight는 병렬로 수행할 수 있다.
Plan Preflight의 SSOT는 `/plan-preflight`다. Plan Preflight가 완료되면 이슈 본문 구현계획을 최신화한 뒤 `plan-preflight:done` 라벨을 붙이고, 이후 `/implement-issue`는 이 라벨을 단서로 기존 구현계획을 재사용한다.

운영 중인 이슈의 현재 단계는 최신 `🤖 **Autopilot 사이클 상태**` 코멘트로 노출하며, 여기서 `review-state`, `implement-state`, `merge-monitor-state`를 각각 `pending | running | blocked | done`으로 추적한다.

### 4.1 Plan Review (Gate 0)

Plan Review는 Claude 내부 사고 절차가 아니라, **구현 세션과 격리된 별도 컨텍스트의 계획 리뷰 서브에이전트 `@plan-reviewer`(`.agent/agents/plan-reviewer.md`)가 수행하는 read-only 리뷰 게이트**다.
브랜치 리뷰처럼 요청, 결과 수신, 수정 루프를 분리해 취급한다.
Plan Preflight가 이슈 본문에 구현계획을 작성하거나 정비한 뒤 Plan Review를 요청하고,
`@plan-reviewer`는 그 계획이 구현 가능한지, 더 안전하거나 단순한 대안이 있는지, 숨은 가정이 있는지 검토한다.

- 실행 주체는 `@plan-reviewer` 서브에이전트이며, 동기 호출로 verdict와 근거를 반환한다.
- 입력에는 이슈 번호, 스펙 경로, 이슈 본문 Implementation Plan, 중점 검토 위험을 포함한다.
- 이 단계는 코드를 수정하지 않고, 브랜치나 PR도 만들지 않는다.
- 반환된 verdict를 오케스트레이터가 이슈 코멘트에 `Plan Review`로 남기고 `reviewer:` 필드에 수행 주체를 기록하며, 필요하면 이슈 본문 구현계획을 갱신한다. `@plan-reviewer`는 GitHub에 쓰지 않는다.

Plan Review의 verdict는 다음 중 하나다.

- `approve-implement`
- `revise-plan`
- `narrow-scope`
- `split-issue`
- `invoke-human`

`approve-implement` 또는 `narrow-scope`가 아니면 구현을 시작하지 않는다.
`revise-plan`이면 Plan Preflight가 피드백을 반영해 이슈 본문 구현계획을 보강한 뒤 다시 Plan Review를 요청한다.
`split-issue`는 자동 실행 신호가 아니라 Plan Preflight 단계의 안전 판정이다. 이 경우 Plan Preflight는 `plan-preflight:done`을 붙이지 않고 보류 코멘트에 구조화된 split plan만 남긴다. 하위 이슈 생성, 라벨 조작, 큐 편입, 부모 이슈 자동 close 같은 실행 동작은 하지 않는다.

### 4.2 브랜치 전략

브랜치 prefix, PR 전제 조건, 에픽 브랜치 정렬 규칙의 SSOT는 [03-git-workflow.md](03-git-workflow.md)다.
이 문서에서는 원칙만 둔다.

- 독립 이슈는 `{branch-prefix}/{issue번호}-{짧은설명}` 브랜치에서 작업하고 `main`으로 PR을 낸다.
- 에픽은 통합용 `epic/*` 브랜치와 하위 이슈별 작업 브랜치를 분리한다.
- 장기 기능은 장기 브랜치 대신 keystone 방식을 우선한다 — 상세는 [03-git-workflow.md §1.5](03-git-workflow.md#15-장기-기능-개발-keystone-우선).
- PR 생성 전 최신 HEAD는 내부 `/code-review` PASS 증적을 가져야 한다.
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
| `/code-review` FAIL | 코드/설계 문제 | Claude 개발 에이전트 | 같은 브랜치에서 수정 후 재검토 |
| CI 실패 — 코드 문제 | 테스트/lint/type 오류 | Claude 개발 에이전트 | 새 커밋 push 후 체크 재실행 |
| CI 실패 — 인프라 문제 | Docker/CI 설정/스크립트 | `@devops` | 수정 후 동일 PR에서 재실행 |
| `merge-gate` 차단 | 충돌, 대화 미해결, auto-merge 비활성 상태 | Claude 오케스트레이터 또는 사람 | 충돌 해결/대화 마무리 후 PR 재동기화 |
| 수용 검증 FAIL | 기능 버그 | 오케스트레이터가 버그 이슈 등록 → Claude 개발 에이전트 | 재검증 속행 |

### 5.1 재시도와 중단 원칙

- 같은 head SHA에서 같은 실패를 반복 판정하지 않는다. 새 커밋이 만들어져야 새 시도로 본다.
- `/code-review` 실패는 PR 생성 전에 같은 worktree에서 해소한다.
- PR 후 추가 코드 변경이 있으면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다.
- 수정 전에는 `.agent/skills/receive-review.md` 규칙으로 finding을 재서술하고 영향 범위를 다시 그린다.
- 같은 `risk class`가 반복되거나 구조 리스크가 넓어지면 얕은 자동 수정 대신 `@code-reviewer` 메타 리뷰 또는 사람 확인을 우선한다.
- 반복 리스크가 구현계획 자체의 문제라면 `/plan-preflight`로 돌아가 이슈 본문 구현계획을 다시 정비하고 Plan Review를 재요청한다.
- `blocked:review-loop`, `blocked:pr-review-loop` 라벨은 자동 큐 제외 신호로 유지된다. 두 라벨이 붙은 이슈는 `/autopilot`이 자동으로 다루지 않으며 사람 개입을 기다린다. 라벨 의미와 큐 제외 규칙은 [00-issue-management.md](00-issue-management.md)와 `/autopilot`을 따른다.

### 5.2 상세 절차의 SSOT

| 상황 | SSOT |
|------|------|
| Plan Preflight 재정비와 Plan Review 재요청 | `.agent/commands/plan-preflight.md` |
| `/code-review` 브랜치 리뷰 반복, 실패 횟수, PR 생성 전 PASS 조건 | `.agent/commands/implement-issue.md`, [03-git-workflow.md](03-git-workflow.md) |
| `merge-gate`, post-merge 복구 | [04-ci-cd.md](04-ci-cd.md) |
| 리뷰 finding 수용, 영향 범위 재검토, 수정 전략 선택 | `.agent/skills/receive-review.md` |
| `gh run rerun`, PR `close → reopen`, 수동 복구 코멘트 | `.agent/skills/github-ops.md` |
| blocked 라벨 정의 | [00-issue-management.md](00-issue-management.md) |

## 6. 리뷰와 머지 게이트

> 상세 규칙: [04-ci-cd.md](04-ci-cd.md)

- **브랜치 리뷰 단계**: Claude Code 네이티브 `/code-review`가 수행한다. GitHub Actions가 아니라 `/code-review` 내부 루프로 도는 PR 전 코드 품질 게이트다.
- **PR 단계**: 자동 AI 승인 워커는 운영하지 않는다. PR 후 추가 변경이 있으면 새 head SHA에서 `/code-review`를 사람/오케스트레이터가 다시 호출해 검증한다.
- **메타 리뷰 단계**: `@code-reviewer`는 상시 게이트가 아니라, 고위험 변경과 반복 failure에서만 호출한다.
- **소스 오브 트루스**: 브랜치 리뷰는 이슈 코멘트의 최신 `/code-review` PASS 기록을 PR 생성 조건으로 삼고, merge gate는 **required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + 충돌 없음 + 대화 해결**을 기준으로 삼는다.
- **머지 담당**: GitHub auto-merge
- **이슈 close**: PR 본문의 `Closes #N`으로 GitHub 기본 auto-close를 우선 사용하고, `post-merge`가 체크박스/에픽 동기화와 수동 복구를 맡는다.
- **원격 브랜치 삭제**: GitHub의 "Automatically delete head branches" 기능 사용
- **로컬 worktree 정리**: Claude 측에서 후속 작업 시 `git worktree prune` 또는 명시적 remove

## 7. 생성 문서 동기화 규칙

생성 문서와 스크립트의 SSOT는 [docs/architecture/generated/](../architecture/generated/) 및 각 생성 스크립트다.
이 문서에서는 원칙만 둔다.

- CLI, DB DDL, 프로젝트 구조처럼 생성 산출물의 입력이 바뀌면 해당 생성 문서도 같은 작업에서 갱신한다.
- 스크립트로 생성되는 문서는 수동 편집하지 않는다.
- 구현 단계에서 생성 산출물 입력이 바뀌면 먼저 대응하는 regenerate 명령을 실행한다.
- 리뷰/CI 전에는 각 생성 산출물을 전용 check 명령으로 검증한다.
  - 프로젝트 구조: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py --check`
  - DB schema: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py --check`
  - CLI reference: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_cli_reference.py --check`
- 모든 생성 산출물은 전용 `--check`를 제공한다. 새 산출물을 추가하면 커밋된 날짜 스탬프를 동결하는 `--check`도 함께 만든다. 이 주장의 정의역은 `scripts/generate_*.py` 규약을 따르는 생성기이며, 다른 메커니즘으로 만들어지는 산출물을 도입하면 같은 규약으로 편입한다. 근거는 #2472다.
- 프로젝트 구조 regenerate 명령은 `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_project_structure.py`다.
- DB schema regenerate 명령은 `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_db_schema.py`다.
- CLI reference regenerate 명령은 `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_cli_reference.py`다.
- 로컬 검증 전에는 `PYTHONPATH=$PWD/src .venv/bin/python scripts/check_import_path.py`로 현재 worktree의 `src/ante/__init__.py`가 import되는지 확인한다.
- Plan Preflight와 리뷰 단계에서 generated artifact sync 위험을 발견하면 구현 체크리스트와 검증 체크리스트에 regenerate/check 흐름을 함께 포함한다.

## 8. CLI/IPC 계약 변경 규칙

CLI/IPC 계약의 상세 SSOT는 [docs/specs/cli/03-commands.md](../specs/cli/03-commands.md)와 [docs/specs/ipc/ipc.md](../specs/ipc/ipc.md)이다.
이 문서에서는 프로세스 원칙만 둔다.

- 명령 이름, 인자, scope, 응답 envelope, stable error code 변경은 사용자와 Agent 양쪽에 영향을 주는 계약 변경으로 본다.
- 구현 이슈 진행 중 계약 변경이 드러나면 Plan Preflight에서 별도 이슈 분리 또는 `needs-spec-first` 전환을 판단한다.
- 새 런타임 명령은 CLI 명령, IPC handler, scope guard, audit action, 테스트를 같은 검증 계획에 포함한다.
- 생성 산출물인 CLI reference와 프로젝트 구조 문서는 입력 변경 후 regenerate/check 흐름으로 검증한다.

### 8.1 default-deny 인증 게이트 — 새 명령 추가 시

> 정책 SSOT: [D-015 default-deny 인증 게이트](../decisions/D-015-default-deny-auth-gate.md)
> 공개 명령 SSOT: [docs/specs/cli/03-commands.md — 공개 명령 allowlist](../specs/cli/03-commands.md#공개-명령-allowlist--인증-면제)

CLI는 default-deny + allowlist (opt-out) 정책이다. 새 명령 추가 시 다음 단계를 거친다.

1. **공개 명령 allowlist 검토**: 신설 명령이 인증 없이 접근 가능해야 하는지 판단한다.
   - 인증 필요(기본값) → 별도 조치 없음. default-deny가 자동 적용된다. scope가 필요하면 `@require_scope`를 명시한다.
   - 공개 필요 → 위 SSOT 표(`03-commands.md`)에 행을 추가하고, 같은 PR에서 코드 allowlist(`_AUTH_EXEMPT_COMMAND_PATHS`)도 함께 갱신한다.
2. **검증 체크리스트**: PR 검증 단계에서 (1) 공개 명령 표와 코드 allowlist가 동기 상태인지, (2) 인증 필요 명령이 `AuthenticatedGroup` factory로 보호되는지, (3) scope가 필요하면 `@require_scope`가 부착되었는지를 확인한다.

## 9. AGENTS.md 경량화 원칙

AGENTS.md는 모든 세션에 주입되므로 핵심 규칙만 유지한다.

- 핵심 설계 원칙, 기술 스택, 디렉토리 구조만 유지
- 모듈별 세부 설계는 `docs/specs/`에 분리
- 상세 가이드는 `.agent/skills/`로 분리

## 10. 코드 주석 정합 원칙

코드 본문 주석은 과거 이슈 히스토리가 아니라 현재 invariant·계약·이유를 설명한다.

- **유지**: 현재 invariant, 호출 계약, 보안/cleanup/cancellation/idempotency/account boundary 이유
- **축약**: 이슈 번호와 리뷰 히스토리는 제거하고 현재 조건만 남김
- **이동**: 긴 배경 설명은 issue/PR/spec/runbook으로 옮기고 코드에는 링크/요약만
- 이슈 번호가 현재 추적에 반드시 필요한 경우(예: 진행 중 follow-up)에만 코드에 남기고 그 외에는 PR/issue 본문으로 옮긴다.
- **적용 시점**: 파일을 수정하는 PR에서 해당 파일의 주석을 함께 정리한다. 저장소 전체 일괄 삭제는 금지.
- **금지**: 주석 정리를 명분으로 로직/예외 타입/출력 문자열/테스트 기대값을 바꾸지 않는다. 실제 런타임 동작·public CLI/API/IPC contract·JSON envelope·로그 메시지·DB schema는 변경하지 않는다.

본 원칙의 SSOT는 본 절이며, 별도 가이드 문서는 만들지 않는다. 이슈 [#1924](https://github.com/joshua-jingu-lee/ante/issues/1924)에서 합의된 결정이다.

## 관련 문서

| 문서 | 내용 |
|------|------|
| [00-issue-management.md](00-issue-management.md) | 이슈 등록, 분류, 추적 규칙 |
| [02-agent-structure.md](02-agent-structure.md) | Claude 역할 구조, 계획/브랜치/이슈 리뷰 게이트, `.agent/`와 `.claude/` 레이어 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션, 브랜치/PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인, 리뷰/승인/merge gate 구성 |
| [05-testing.md](05-testing.md) | 테스트 전략, 커버리지 기준 |
| [06-release.md](06-release.md) | release PR, 버전 관리, PyPI/Docker 배포 |
