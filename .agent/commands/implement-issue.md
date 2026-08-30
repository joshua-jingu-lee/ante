GitHub 이슈의 유저스토리를 기반으로 구현하고, 내부 브랜치 리뷰(`/code-review`)를 통과한 뒤 PR을 생성한다.

GitHub 조회/코멘트/PR 관련 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

## 인자

$ARGUMENTS — GitHub 이슈 번호 (예: 43, 39 등)

## 경로 규칙

아래 셸 예시는 저장소 루트와 worktree 루트를 동적으로 계산한다.

- `REPO_ROOT`: `git rev-parse --show-toplevel`
- `WORKTREE_ROOT`: `ANTE_WORKTREE_ROOT`가 설정되어 있으면 그 값을 사용하고, 없으면 저장소의 형제 디렉토리 `ante-worktrees/`를 사용한다.

공통 셸 변수:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_ROOT="${ANTE_WORKTREE_ROOT:-$(cd "$REPO_ROOT/.." && pwd)/ante-worktrees}"
mkdir -p "$WORKTREE_ROOT"
```

## 에이전트 역할 분담

이 커맨드는 Claude 오케스트레이터로서 작업을 분석하고, 구현은 Claude 개발 에이전트에 위임한다. 구현 전 Plan Review(Gate 0)는 별도 컨텍스트 서브에이전트 `@plan-reviewer`가, PR 전 브랜치 리뷰(Gate A)는 Claude Code 네이티브 `/code-review`가 수행한다. Plan Review는 구현 세션과 격리된 read-only 계획 리뷰다. PR 전 브랜치 리뷰는 GitHub Actions가 아니라 같은 Claude 세션에서 `/code-review`를 실행해 내부 반복한다.

구조 리스크가 높거나 반복 failure가 나오면 Claude `@code-reviewer`가 메타 리뷰를 수행한다.

| 단계 | 담당 | 실행 주체 | GitHub 기록 |
|------|------|-----------|-------------|
| 1~4 (분석) | 오케스트레이터 | Claude 메인 세션 | 구현 분석 완료 또는 스킵 이슈 코멘트 |
| 4a (Plan Preflight 구현계획 작성/정비) | 오케스트레이터 | Claude 메인 세션 | 이슈 본문 |
| 4b (Plan Review 요청/대기, Gate 0) | `@plan-reviewer` (verdict 반환, read-only) | 별도 컨텍스트 서브에이전트 | verdict → 오케스트레이터가 Plan Review 이슈 코멘트 기록 |
| 5 (착수 기록) | 개발 에이전트 | `@backend-dev` / `@devops` / `@strategy-dev` | 이슈 코멘트 |
| 6~9 (구현 + 로컬 검증) | 개발 에이전트 | `@backend-dev` / `@devops` / `@strategy-dev` | 로컬 커밋 + 로컬 구현 완료 이슈 코멘트 |
| 10~11 (브랜치 리뷰 루프, Gate A) | `/code-review` + Claude 개발 에이전트 | 네이티브 리뷰 + Claude 개발 에이전트 | 이슈 코멘트 |
| 11a (메타 리뷰) | Claude | `@code-reviewer` | 필요 시 이슈/PR 코멘트 |
| 12 (PR 생성) | 오케스트레이터 | Claude 메인 세션 | PR 생성 (`Closes #이슈`) |
| 13 (최종 머지) | GitHub automation + `/autopilot` | `merge-gate` + auto-merge | PR checks + 이슈 상태/post-merge 코멘트 |

## 작업 흐름

### 분석 단계 (오케스트레이터)

1. **이슈 읽기**: `gh issue view #{번호}`로 이슈 본문을 읽고 유저스토리와 수용 조건을 파악한다.
   - **에픽 이슈인 경우**: 아래 "에픽 이슈 처리 절차"를 따른다.
   - **하위 이슈인 경우**: 선행 이슈가 모두 close 상태인지 확인한다. 미완성이면 이 이슈를 스킵하고 사용자에게 보고한다.
   - **`needs-triage` 라벨이 붙어 있으면**: 구현을 시작하지 않고 이슈에 보류 사유를 남긴다.
2. **설계 문서 확인**: 관련 설계 문서(`docs/specs/{모듈}/{모듈}.md`)를 읽고 인터페이스와 요구사항을 파악한다.
   - 스펙에 정의되지 않은 인터페이스·동작을 요구하면 구현하지 않고 이슈에 스킵 사유를 남긴다.
3. **대상 에이전트 결정**:
   - `src/ante/` 변경 → `@backend-dev`
   - Docker/CI/CD/scripts/ 변경 → `@devops`
   - `strategies/` 변경 → `@strategy-dev`
   - 여러 영역 변경 → 모듈 의존성 순서대로 진행
4. **기존 코드 파악**: 이슈가 기존 모듈 수정을 포함하면 관련 소스를 먼저 읽고 영향 범위를 파악한다.

4a. **Plan Preflight 구현계획 작성/정비**: 구현 전에 이슈 본문에 실행 가능한 구현계획이 있는지 확인하고, 없거나 부족하거나 stale하면 `/plan-preflight #{번호}`를 먼저 실행한다.

- Plan Preflight 절차와 `plan-preflight:started`/`plan-preflight:done` 라벨·verdict 수명주기의 SSOT는 `.agent/commands/plan-preflight.md`다. 이 커맨드는 그 수명주기를 재정의하지 않고 따른다.
- 코드 수정, 브랜치 생성, PR 생성은 Plan Preflight 단계에서 하지 않는다.
- 이슈에 `plan-preflight:done` 라벨이 있으면 기존 구현계획을 우선 재사용하되, 이슈 본문/스펙/선행 조건 변경으로 stale하지 않은지 확인한다.
- Plan Preflight 결과가 `needs-rewrite`, `needs-spec-first`, `blocked`이면 구현을 시작하지 않는다.
- `plan-preflight:done`은 구현계획까지 확정됐다는 뜻이며, 이슈 본문이 canonical plan이다.
- 작은 이슈라도 `plan-preflight:done` 라벨과 최신 이슈 본문 구현계획이 있어야 구현을 시작한다.

4b. **Plan Review 요청/대기 (Gate 0)**: Plan Preflight가 정비한 구현계획을 별도 컨텍스트의 계획 리뷰 서브에이전트 `@plan-reviewer`로 넘긴다.

- 실행 주체는 `@plan-reviewer`(`.agent/agents/plan-reviewer.md`)이며, 동기 호출로 verdict와 근거를 반환한다.
- 입력에는 이슈 번호, 스펙 경로, 이슈 본문 Implementation Plan, 중점 검토 위험을 포함한다.
- 이 단계는 코드 수정, 브랜치 생성, PR 생성을 하지 않는다.
- 반환된 verdict를 오케스트레이터가 이슈 코멘트에 `Plan Review`로 남기고 `reviewer:` 필드에 수행 주체를 기록한다. `@plan-reviewer`는 GitHub에 쓰지 않는다.

예시:

```text
Agent(
  subagent_type="plan-reviewer",
  prompt="이슈 #{번호} 본문 Implementation Plan 검토: 가정, 범위 적합성, 누락된 소비자, 생성 산출물, 롤백/테스트 공백을 확인하고 verdict를 반환하라."
)
```

Plan Review verdict가 `approve-implement` 또는 `narrow-scope`가 아니면 6단계 구현으로 넘어가지 않는다. `revise-plan`이면 `plan-preflight:started` 상태를 유지하고, Plan Preflight가 피드백을 반영해 이슈 본문 구현계획을 보강한 뒤 다시 Plan Review를 요청한다.

4c. **구현 분석 완료 코멘트**: 구현에 넘길 수 있는 상태가 확인되면 오케스트레이터가 이슈에 분석 완료 코멘트를 남긴다. 이 코멘트는 개발 에이전트의 착수 기록을 대체하지 않고, 어떤 계획과 기준으로 구현을 위임하는지 고정한다.

```bash
gh issue comment #{이슈번호} --body "🤖 **구현 분석 완료**
- status: ready-to-implement
- spec-path: {1A Spec-First | 1B Issue-First Bundled}
- plan-preflight: done
- Plan Review: {approve-implement | narrow-scope}
- target agent: @{에이전트명}
- base branch: {main 또는 epic/{에픽번호}-{설명}}
- next: 개발 에이전트가 구현 착수 코멘트를 남기고 worktree 격리 후 작업"
```

### 구현 시작 기록 (개발 에이전트)

5. **이슈에 착수 코멘트**:

착수 코멘트는 `/implement-issue` 과정에서 선택된 개발 에이전트가 첫 작업으로 남긴다.
오케스트레이터는 이슈 본문 구현계획과 Plan Review 결과를 개발 에이전트 프롬프트에 넘기되, 착수 기록을 대신 작성하지 않는다.
착수 코멘트는 `plan-preflight:done` 라벨이 있고, 이슈 본문 구현계획이 최신 Plan Review verdict를 반영한 뒤에만 남긴다.

```bash
gh issue comment #{이슈번호} --body "🤖 **구현 착수**
- 담당 에이전트: @{에이전트명}
- 변경 대상: {src/ante/xxx, docs/xxx, scripts/xxx 등}
- base 브랜치: {main 또는 epic/{에픽번호}-{설명}}
- Plan Review: {approve-implement | narrow-scope}
- risk flags: {없음 또는 쉼표 구분 목록}
- 구현계획: 이슈 본문 Implementation Plan 기준"
```

### 구현 단계 (개발 에이전트)

6~9단계를 Claude 개발 에이전트에 위임한다.

```
Agent(
  subagent_type="backend-dev",
  prompt="""
이슈 #{번호}를 구현하라.

## 이슈 내용
{이슈 본문 전체}

## 설계 문서
{관련 스펙 문서 경로와 요약}

## 작업 범위
6. Worktree 생성
7. 유저스토리별 구현
8. 로컬 검증 (ruff check, ruff format, pytest)
9. 로컬 커밋

## Plan Preflight
{이슈 본문 또는 이슈 코멘트의 실행계획 요약}

## Plan Review
{verdict, feedback, implementation checklist, verification checklist, stop conditions}

## 구현 필수 체크리스트
{이슈 본문 Implementation Plan의 tasks, verification, risk flags, stop conditions}

브랜치명과 로컬 HEAD SHA를 반환하라.
완료 후 이슈에 `로컬 구현 완료` 코멘트를 남겨라.
""",
  isolation="worktree"
)
```

개발 에이전트가 로컬 검증과 커밋을 마치면 이슈 코멘트를 남긴다.

```bash
gh issue comment #{이슈번호} --body "🤖 **로컬 구현 완료**
- 담당 에이전트: @{에이전트명}
- branch: {작업 브랜치}
- head: {SHA7}
- checks: {ruff check | ruff format | pytest | 기타 명령과 결과}
- implementation plan: 이슈 본문 체크리스트 기준
- next: 브랜치 리뷰 요청"
```

### 브랜치 리뷰 루프 (Gate A)

10. **브랜치 리뷰 요청 및 대기**: PR 생성 전 최신 로컬 브랜치 HEAD를 Claude Code 빌트인 `/code-review` 스킬로 검토한다. 같은 이름의 마켓플레이스 플러그인 커맨드와 혼동하지 않는다 — 그 플러그인은 커맨드 설명이 PR 리뷰를 전제하고 허용 도구에 `gh pr` 계열이 열거돼 있다. Gate A는 PR이 아직 없는 시점의 로컬 브랜치 리뷰이므로 빌트인 스킬로 실행한다.

**스킬이 노출하는 인자 문법 (CLI 버전 종속 관측)**

- 인자 힌트 리터럴: `[low|medium|high|xhigh|max] [--fix] [--comment] [<pr#>|<branch>|<path>]` — 첫 자리에는 레벨 토큰이 `|`로 이어져 열거되고, 조건부로 `ultra`가 그 열거에 더해진다. `<level>` 같은 자리표시 토큰은 이 리터럴에 없다.
- 첫 자리 레벨 토큰으로 effort 레벨을 지정할 수 있다. 레벨을 생략한 호출에 대해 스킬 설명은 직전에 입력한 레벨을 재사용한다고 서술한다.
- 모드 플래그는 인자 힌트에 `--fix`·`--comment` 두 가지가 열거돼 있고, 파서는 여기에 `--post`·`--no-post`를 더한 네 가지를 받는다. 각 플래그가 무엇을 하는지는 이 문서가 서술하지 않는다.
- 인자 힌트의 마지막 자리 `[<pr#>|<branch>|<path>]`는 파서에서 `target` 한 필드로 들어간다. 비교 기준(base)을 별도 인자나 플래그로 지정하는 문법은 인자 힌트에도 파서가 받는 플래그 목록에도 없다. 그 자리를 비운 호출의 기본 비교 범위는 이 문서가 서술하지 않는다.
- 이 블록의 열거와 리터럴, 그 의미는 모두 CLI 버전에 종속된 관측이라 저장소에 회귀 lock을 걸지 않는다. 인자 문법이나 그 의미가 필요해지면 그 시점 스킬 설명을 직접 확인한다.

모드 플래그는 이 게이트에서 쓰지 않는다. 근거: (a) Gate A는 read-only 리뷰다 (b) 작업 브랜치 수정은 개발 서브에이전트 위임으로 한정된다 (c) PR 생성 전이라 코멘트 대상이 없다([#2469](https://github.com/joshua-jingu-lee/ante/issues/2469)).

**정본 호출 형태**

```text
/code-review {effort} {base}...{head}
```

- effort는 `high`·`xhigh`·`max` 중 하나로 명시한다.
- base는 `git merge-base origin/main {head}`로 잡되, epic/* 하위 이슈는 epic 브랜치와의 merge-base로 잡는다(base 산출 전 `origin/main` 갱신 전제).
- `{base}...{head}` range를 항상 명시한다. range는 스킬 인자의 `target` 자리에 들어가는 문자열이며 스코프 고정은 도구가 보장하는 계약이 아니라 호출 관례다. range가 존중되면 리뷰 스코프는 그 범위로 고정되고, 존중되지 않는 경우의 스코프는 미상이며 이 규범에는 그것을 탐지하는 수단이 없다(known-limitation). clean worktree 전제는 미커밋 변경 혼입만 닫는다. 리뷰 출력이 range 밖 파일의 finding을 반환하는 관측이 나오면 그 시점에 후속 이슈로 등록한다.
- 호출 직전 `git status --porcelain` 출력이 비어 있음을 확인한다.
- 재호출은 직전 호출과 같은 레벨 이상으로 한다.

- 결과는 이슈 코멘트에 `브랜치 리뷰`로 남긴다.
- `PASS`:
  - 브랜치를 push하고 PR 생성 단계로 진행
- `FAIL`:
  - 리뷰가 남긴 blocking finding을 `.agent/skills/receive-review.md` 규칙으로 정리한 뒤 Claude 개발 에이전트에 수정 위임

```bash
gh issue comment #{이슈번호} --body "🤖 **브랜치 리뷰**
- verdict: {PASS | FAIL}
- reviewer: /code-review
- effort: {high|xhigh|max}
- scope: {base}...{head}
- worktree: clean
- head: {SHA7}
- attempt: {N}
- blocking findings: {없음 | finding 요약}
- next: {브랜치 push 후 PR 생성 | 같은 worktree에서 수정 후 재검토}"
```

리뷰 스코프는 위 증적의 `scope:` 필드에 `{base}...{head}`로 기록한다([#2469](https://github.com/joshua-jingu-lee/ante/issues/2469)).

11. **수정 루프**: `/code-review`가 최신 HEAD SHA에서 `PASS`가 될 때까지 내부 반복한다.

```text
while /code-review verdict != PASS:
  Claude 개발 에이전트가 같은 브랜치에서 수정
  새 로컬 커밋 생성
  /code-review 재실행
```

- 실패 횟수는 이슈 코멘트 기준으로 누적한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호로 보고 원인 파악을 우선한다.
- 자동 수정 전에 finding을 곧바로 patch로 번역하지 말고 `.agent/skills/receive-review.md` 규칙으로 사실/추론/영향 범위를 먼저 다시 정리한다.
- 같은 `risk class`가 2회 반복되면 `@code-reviewer`를 호출해 구조 리스크와 계획 편차를 먼저 정리한다.
- 반복 실패가 임계값(10회, SSOT: [04-ci-cd.md](../../docs/runbooks/04-ci-cd.md)) 이상이면 `blocked:review-loop` 라벨이 붙고 브랜치 리뷰를 더 이상 자동 실행하지 않는다.
- 이 상태에서는 사용자가 개입해 원인을 정리하거나 라벨을 해제하기 전까지 같은 이슈를 계속 밀어붙이지 않는다.

11a. **메타 리뷰 호출 조건**: 아래에 해당하면 PR을 만들기 전에 Claude `@code-reviewer`를 다시 호출한다.

- 캐시, 세션, 연결, long-lived adapter, mutable config 변경
- endpoint / schema / generated artifact drift 가능성
- 같은 `risk class` failure 2회 반복
- "무슨 파일을 고쳐야 하는가"보다 "원래 계획에서 왜 어긋났는가"가 더 중요해진 경우

### PR 생성

12. **PR 생성**: 최신 HEAD SHA의 `/code-review`가 PASS한 뒤에만 브랜치를 push하고 PR을 만든다.

```bash
gh pr create \
  --base {main 또는 epic/...} \
  --title "{conventional commit 형식 제목}" \
  --body "Closes #{이슈번호}

## Summary
- {변경 요약}

## Test Plan
- {로컬 검증 명령}
"
```

PR 생성 후 이슈에 코멘트를 남긴다:

```bash
gh issue comment #{이슈번호} --body "🤖 **PR 생성 완료**
- PR: #{PR번호}
- branch-review: `/code-review` PASS
- 이후 단계: ci required + merge-gate + auto-merge"
```

### PR 이후 단계

13. **최종 머지**: PR 생성 이후에는 GitHub automation이 다음을 수행한다.

- `ci` 통과는 머지 차단 게이트다. (required status check)
- PR 단계의 자동 AI 승인 워커는 운영하지 않는다. 머지 가능 여부 판정에 AI status check가 끼어들지 않는다.
- PR 후 추가 코드 변경이 발생하면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다. 추가 검증이 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출하고 결과를 PR 코멘트에 남긴다. 호출은 §브랜치 리뷰 루프의 정본 형태를 따른다.
- 구조 리스크가 반복되면 `@code-reviewer` 메타 리뷰 우선.
- `ci` 통과 + 충돌 없음 + 대화 해결 완료 + auto-merge 활성화 가능 상태이면 `merge-gate`가 GitHub auto-merge를 활성화하고 squash merge가 수행된다.
- `merge-gate`는 `AUTOMERGE_TOKEN`(fine-grained PAT)으로 auto-merge를 활성화한다(#2437, fail-closed — 시크릿 부재 시 명시 실패). 머지가 발화한 `pull_request:closed` 이벤트로 `post-merge.yml`이 트리거된다(dispatch·폴링 없음).
- 머지 후 post-merge automation이 이슈 체크박스를 갱신하고 close.
- `/autopilot` 실행 중이면 최신 `🤖 **Autopilot 사이클 상태**` 이슈 코멘트를 `current-cycle=merge-monitor`에서 `completed`까지 갱신한다.
- `post-merge.yml`은 연결 이슈에 `🤖 **Post-merge 정리 완료**` 코멘트를 남긴다.

이 커맨드는 **직접 머지하지 않는다**.

## 에픽 이슈 처리 절차

에픽 이슈 번호가 인자로 들어온 경우, 직접 코드를 구현하지 않고 다음 절차를 수행한다.

### E1. 에픽 통합 브랜치 생성

```bash
git branch epic/{에픽번호}-{짧은설명} main
git push -u origin epic/{에픽번호}-{짧은설명}
```

### E2. 하위 이슈 정렬

- 에픽 본문에서 하위 이슈 목록과 의존성을 파악한다.
- 의존성 없는 이슈끼리는 병렬 실행 가능 그룹으로 묶는다.

### E3. 하위 이슈 실행

각 하위 이슈에 대해 동일한 `/implement-issue #{하위이슈번호}` 흐름을 수행한다.

- 구현
- 로컬 커밋
- `/code-review` 통과
- 브랜치 push
- PR 생성 (`base=epic/{에픽번호}-{설명}`)

epic 하위 이슈 브랜치는 `epic/*`에서 분기하고, 분기 시점의 `epic/*`에는 먼저 머지된 형제 하위 이슈 변경이 이미 들어 있다. `/code-review`가 노출하는 인자 문법 관측은 §브랜치 리뷰 루프 10번에 있고, 이 게이트의 호출도 그 절의 정본 형태를 따른다. **비교 범위가 형제 하위 이슈 변경까지 포함하면**, 형제 하위 이슈와 이 하위 이슈가 **같은 파일**을 수정한 경우 형제 라인에서 비롯한 잘못된 FAIL이나 실제 버그 누락 위험이 있다. 두 갈래의 분리는 §브랜치 리뷰 루프가 정한 epic base 분기(epic 브랜치와의 merge-base)가 제공한다. 현재 epic 워크플로는 휴면 상태이며, 재개 시 이 스코핑을 재설계한다 — 그 시점의 스킬 설명을 다시 확인해 정한다. 재설계 대상은 스코핑 전반이며, base 산출은 §브랜치 리뷰 루프가 소유한다. 이 관측은 CLI 버전에 종속되므로 저장소에 회귀 lock을 걸지 않는다. 그때까지 리뷰어는 `git diff <epic-base>...HEAD`로 이 하위 이슈 자체 델타를 확인하고, 그 델타 밖의 코드에서 비롯한 finding은 이 하위 이슈의 blocking으로 보지 않는다.

### E4. 에픽 PR 생성

모든 하위 이슈가 에픽 브랜치에 반영되면, 에픽 브랜치도 동일한 규칙을 따른다.

1. 에픽 브랜치 최신화 및 로컬 검증
2. `/code-review` 통과 (에픽 브랜치가 `main`으로 머지되는 단계다)
3. `epic/* -> main` PR 생성
4. `ci` 통과 후 `merge-gate`가 auto-merge 활성화

### E5. 정리

- 원격 브랜치 삭제는 GitHub 설정에 맡긴다.
- 로컬 worktree는 Claude 구현 머신에서 후속 작업 시 prune/remove 한다.

## 종료 조건

이 커맨드의 성공 기준은 다음 중 하나다.

- PR이 성공적으로 생성되었고 머지 자동화(`ci` + `merge-gate` + auto-merge)가 인계됨
- 스펙 불일치 또는 반복 실패로 인해 이슈가 명시적으로 `blocked` 처리됨
