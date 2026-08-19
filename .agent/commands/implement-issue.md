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

10. **브랜치 리뷰 요청 및 대기**: PR 생성 전 최신 로컬 브랜치 HEAD를 Claude Code 빌트인 `/code-review` 스킬로 검토한다. 아래 두 블록을 순서대로 읽는다 — 앞 블록은 이 저장소가 정하는 게이트 규범이고, 뒤 블록은 스킬이 노출하는 인자 문법 관측이다.

**Gate A 호출 규범 (이 저장소가 정한다)**

- **effort 레벨 토큰을 반드시 붙이고, Gate A 최소 레벨은 `high` 이상이다.** 스킬 설명은 레벨을 생략하면 직전에 입력한 레벨을 다시 쓴다고 적는다 — 생략하면 게이트 강도가 호출자의 입력 이력에 좌우된다. 하한을 정해 두지 않으면 더 낮은 레벨을 골라도 규범을 만족해 같은 모양의 PASS 증적이 남으므로, 게이트 강도가 호출자 상태에 좌우되는 실패 모드가 출처만 바뀐 채 남는다. `high`보다 높은 레벨(`xhigh`·`max`)은 변경 규모와 리스크를 보고 오케스트레이터가 올릴 수 있고, 같은 이슈의 재호출은 첫 호출과 같은 레벨을 다시 붙인다. `ultra`는 인자 힌트 열거에 조건부로 더해지지만 파서가 레벨로 해석하기 전에 분기하는 별개 실행 모드이므로 Gate A 레벨 집합에서 제외한다.
- **범위를 좁히는 위치 인자(`<pr#>`·`<path>`)는 넘기지 않는다.** Gate A는 브랜치 변경 전체를 판정하는 게이트이므로, 일부만 리뷰한 결과로 PASS 증적을 남기면 게이트가 무력해진다. 이 금지는 그 자리에 `<pr#>`·`<path>`를 넣지 말라는 뜻이지, 아래 range나 effort 레벨 토큰까지 생략하라는 뜻이 아니다.
- **`[<pr#>|<branch>|<path>]` 자리에는 `{base}...{head}` 커밋 범위를 항상 명시해 넘긴다.** range를 넘기면 리뷰 스코프가 호출 위치·대상 브랜치의 체크아웃 상태·push 여부와 무관하게 결정적으로 고정된다. 그 자리를 비우면 기본 비교 범위가 호출 상황에 따라 달라져(특히 PR 이후 push된 브랜치) 사실상 빈 diff를 리뷰한 PASS가 남을 수 있다. `{base}`는 작업 브랜치가 분기한 통합 지점(표준 흐름에서는 `main`)의 커밋, `{head}`는 리뷰 대상 브랜치 최신 로컬 커밋이며 둘 다 SHA로 넘긴다 — 표준 흐름의 6~9번은 `isolation="worktree"`로 위임되어 작업 브랜치가 격리 worktree에만 있고 오케스트레이터의 작업 디렉터리는 `main`이므로, SHA로 대상 커밋을 특정하지 않으면 깨끗한 `main`을 리뷰한 PASS 증적이 남는다.
- **작업 트리를 clean하게 둔 상태로 호출한다.** range를 넘긴 호출에서도 호출 시점 체크아웃에 남아 있는 미커밋 변경이 리뷰 스코프에 함께 들어오는 것이 실행으로 관측됐다 — 리뷰 대상이 아닌 변경이 남아 있으면 판정과 증적이 그만큼 오염된다.
- **모드 플래그는 넘기지 않는다** — 인자 힌트에 열거된 `--fix`·`--comment`와 파서가 받는 `--post`·`--no-post` 중 어느 것도 붙이지 않는다.
- 모드 플래그 금지 근거는 이 게이트의 성질이다. Gate A는 read-only 리뷰 게이트이고([04-ci-cd.md](../../docs/runbooks/04-ci-cd.md) §2 Gate A) PR 생성(12번) 이전 단계다. 작업 브랜치 수정은 `CLAUDE.md`의 「직접 코드 구현과 작업 브랜치 수정은 `/implement-issue` 흐름 안에서만 개발 서브에이전트(`@backend-dev`, `@devops`, `@strategy-dev`)에게 위임한다」 규칙을 따르고, 외부에 남기는 기록은 아래 증적 규칙과 12번 이후 PR 절차만을 경로로 삼는다.
- 따라서 Gate A가 허용하는 호출 형태는 `/code-review {effort 레벨} {base}...{head}` 하나다. 호출 위치나 체크아웃 상태로 형태가 갈라지지 않으므로 개발 에이전트가 자기 worktree에서 호출하든 오케스트레이터가 다른 작업 디렉터리에서 호출하든 같은 문장을 쓴다. 인자 힌트에 새 인자나 플래그가 늘어나도 이 형태를 벗어나므로 Gate A 자동 루프에서 쓰지 않는다.
- 같은 이름의 마켓플레이스 플러그인 커맨드와 혼동하지 않는다. 그 플러그인은 커맨드 설명이 PR 리뷰를 전제하고 허용 도구에 `gh pr` 계열이 열거돼 있다 — Gate A는 PR이 아직 없는 시점의 로컬 브랜치 리뷰이므로 빌트인 스킬로 실행한다.

**스킬이 노출하는 인자 문법 (CLI 버전 종속 관측 — 규범을 넓히지 않는다)**

- 인자 힌트 리터럴: `[low|medium|high|xhigh|max] [--fix] [--comment] [<pr#>|<branch>|<path>]` — 첫 자리에는 레벨 토큰이 `|`로 이어져 열거되고, 조건부로 `ultra`가 그 열거에 더해진다. `<level>` 같은 자리표시 토큰은 이 리터럴에 없다.
- 위 레벨 토큰은 `/code-review` 호출에 쓰는 값이며, 서브에이전트에 지시하는 effort 어휘와는 별개 축이다.
- 모드 플래그는 인자 힌트에 `--fix`·`--comment` 두 가지가 열거돼 있고, 파서는 여기에 `--post`·`--no-post`를 더한 네 가지를 받는다. 각 플래그가 무엇을 하는지는 이 문서가 서술하지 않는다.
- 인자 힌트의 마지막 자리 `[<pr#>|<branch>|<path>]`는 파서에서 `target` 한 필드로 들어간다. 비교 기준(base)을 별도 인자나 플래그로 지정하는 문법은 인자 힌트에도 파서가 받는 플래그 목록에도 없다. 실행으로 관측된 사실은 두 가지다 — `{base}...{head}` 범위를 그 자리에 넘긴 호출은 그 범위의 커밋을 리뷰 대상으로 보고했고, 같은 호출이 호출 시점 체크아웃의 미커밋 변경도 함께 리뷰했다. 그 자리를 비운 호출의 기본 비교 범위는 관측된 바 없고 이 문서가 서술하지 않는다.
- 이 블록의 열거와 리터럴, 그 의미는 모두 CLI 버전에 종속된 관측이라 저장소에 회귀 lock을 걸지 않는다. 인자 문법이나 그 의미가 필요해지면 그 시점 스킬 설명을 직접 확인하고, 위 규범과 어긋나면 이 문서를 먼저 갱신한다.

```text
/code-review {effort 레벨} {base}...{head}
```

- 결과는 이슈 코멘트에 `브랜치 리뷰`로 남긴다.
- `PASS`:
  - 브랜치를 push하고 PR 생성 단계로 진행
- `FAIL`:
  - 리뷰가 남긴 blocking finding을 `.agent/skills/receive-review.md` 규칙으로 정리한 뒤 Claude 개발 에이전트에 수정 위임

```bash
gh issue comment #{이슈번호} --body "🤖 **브랜치 리뷰**
- verdict: {PASS | FAIL}
- reviewer: /code-review
- effort: {호출에 붙인 effort 레벨 토큰}
- review-scope: {호출에 넘긴 범위 — 예: 6273c581...1ac0ec1b}
- head: {SHA7}
- attempt: {N}
- blocking findings: {없음 | finding 요약}
- next: {브랜치 push 후 PR 생성 | 같은 worktree에서 수정 후 재검토}"
```

11. **수정 루프**: `/code-review`가 최신 HEAD SHA에서 `PASS`가 될 때까지 내부 반복한다.

```text
while /code-review {effort 레벨} {base}...{head} verdict != PASS:
  Claude 개발 에이전트가 같은 브랜치에서 수정
  새 로컬 커밋 생성
  /code-review {10번과 같은 effort 레벨} {base}...{새 head} 재실행
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
- PR 후 추가 코드 변경이 발생하면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다. 추가 검증이 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출하고(호출에는 effort 레벨 토큰을 붙인다) 결과를 PR 코멘트에 남긴다.
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

epic 하위 이슈 브랜치는 `epic/*`에서 분기하고, 분기 시점의 `epic/*`에는 먼저 머지된 형제 하위 이슈 변경이 이미 들어 있다. 분기 사실만으로 형제 변경이 리뷰 diff에 섞이는 것은 아니다 — 리뷰 기준이 형제 머지 이후의 `epic/*` 통합 지점이면 섞이지 않는다. Gate A 호출 형태가 `{base}...{head}` range이므로 그 기준을 넘기는 문법은 이미 있다 — `{base}`에 형제 머지 이후의 `epic/*` 통합 지점을 넣으면 리뷰 스코프가 그 지점 이후로 고정된다(§브랜치 리뷰 루프 10번). 남은 문제는 해결 불가한 도구 제약이 아니라, 하위 이슈마다 그 통합 지점을 무엇으로 잡을지 정하는 epic 절차가 아직 없다는 점이다. 리뷰 기준이 그 통합 지점보다 앞선 커밋이면 이미 epic에 머지된 형제 하위 이슈 변경이 브랜치 diff에 섞여 들어온다. 형제 하위 이슈와 이 하위 이슈가 **같은 파일**을 수정한 경우 두 갈래가 Gate A 리뷰 스코프에서 완벽히 분리되지 않아, 형제 라인에서 비롯한 잘못된 FAIL이나 실제 버그 누락 위험이 남는다. 현재 epic 워크플로는 휴면 상태이므로([03-git-workflow.md](../../docs/runbooks/03-git-workflow.md) §1.5, [#2418](https://github.com/joshua-jingu-lee/ante/issues/2418)) 이 한계를 지금 닫지 않는다. epic 워크플로를 재개할 때 그 시점 스킬 설명에서 인자 문법과 그 의미를 다시 확인하고 이 스코핑을 재설계한다. 그 재설계가 끝나기 전까지는 리뷰어가 `git diff <epic-base>...HEAD`로 이 하위 이슈 자체 델타를 확인해 판정 근거로 삼고, 형제 코드에서 비롯한 finding은 제외한다.

### E4. 에픽 PR 생성

모든 하위 이슈가 에픽 브랜치에 반영되면, 에픽 브랜치도 동일한 규칙을 따른다.

1. 에픽 브랜치 최신화 및 로컬 검증
2. `/code-review` 통과 (§브랜치 리뷰 루프 10번의 Gate A 호출 규범을 그대로 적용 — `{base}...{head}` range를 명시하고, 범위를 좁히는 `<pr#>`·`<path>`와 모드 플래그는 붙이지 않는다)
3. `epic/* -> main` PR 생성
4. `ci` 통과 후 `merge-gate`가 auto-merge 활성화

### E5. 정리

- 원격 브랜치 삭제는 GitHub 설정에 맡긴다.
- 로컬 worktree는 Claude 구현 머신에서 후속 작업 시 prune/remove 한다.

## 종료 조건

이 커맨드의 성공 기준은 다음 중 하나다.

- PR이 성공적으로 생성되었고 머지 자동화(`ci` + `merge-gate` + auto-merge)가 인계됨
- 스펙 불일치 또는 반복 실패로 인해 이슈가 명시적으로 `blocked` 처리됨
