GitHub 이슈 본문을 구현 가능한 실행계획으로 정비하고, Plan Review 피드백까지 반영해 Plan Preflight를 완료한다.

GitHub 조회/코멘트/이슈 본문 수정 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

## 인자

$ARGUMENTS — GitHub 이슈 번호와 옵션
- `#{번호}` 또는 `{번호}`: Plan Preflight 대상 이슈
- `--refresh`: 이미 `plan-preflight:done`인 이슈라도 이슈 본문/스펙/선행 조건 최신성을 다시 확인하고 필요 시 재작성
- `--dry-run`: 이슈 본문과 라벨을 수정하지 않고 필요한 변경 요약만 보고

## 목적

`/plan-preflight`는 구현 착수 전 이슈 본문을 canonical implementation plan으로 만드는 커맨드다.
계획 작성에는 `superpowers:writing-plans` 원칙을 적용한다. 대화 중 `superpower:write-plan`이라고 부르는 경우도 같은 계획 작성 원칙을 뜻한다.
이 커맨드는 코드 수정, 브랜치 생성, PR 생성을 하지 않는다.
이슈 범위가 너무 크거나 여러 invariant/consumer/계약을 한 번에 건드리면 이 커맨드는 구현계획을 확정하지 않고 `split-issue`로 보류한다. 이때 `/plan-preflight`는 하위 이슈를 직접 만들거나 `/autopilot` 실행을 유도하지 않고, 사람이 후속 이슈로 옮길 수 있는 구조화된 split plan만 남긴다.

완료 조건:

- 이슈 본문에 구현계획이 최신 상태로 정리되어 있음
- Plan Review verdict가 `approve-implement` 또는 `narrow-scope`
- Plan Review 피드백이 이슈 본문 구현계획에 반영되어 있음
- `plan-preflight:started` 라벨이 제거되고 `plan-preflight:done` 라벨이 붙어 있음

## 역할 분담

| 단계 | 담당 | 실행 주체 | GitHub 기록 |
|------|------|-----------|-------------|
| 이슈/스펙 분석 | 오케스트레이터 | Claude 메인 세션 | 시작/보류 이슈 코멘트 |
| 이슈 본문 구현계획 작성/정비 | 오케스트레이터 | Claude 메인 세션 | 이슈 본문 + 계획 정비 완료 이슈 코멘트 |
| 계획 검증 (Gate 0) | `@plan-reviewer` (verdict 반환, read-only) | 별도 컨텍스트 서브에이전트 | verdict → 오케스트레이터가 Plan Review 이슈 코멘트 기록 |
| 피드백 반영/라벨 확정 | 오케스트레이터 | Claude 메인 세션 | 이슈 본문 + 라벨 + 완료/보류 이슈 코멘트 |

## 실행 절차

### 1단계: 대상 이슈 확인

1. `gh issue view #{번호}`로 이슈 본문, 라벨, 코멘트, 연결 PR 여부를 확인한다.
2. `needs-triage`, `blocked`, `blocked:review-loop`, `blocked:pr-review-loop` 라벨이 있으면 Plan Preflight를 시작하지 않는다.
3. 선행 의존 이슈가 닫히지 않았으면 `blocked` 판정으로 중단한다.
4. 이미 open PR이 연결되어 있으면 이 커맨드로 본문 계획을 고치지 않고 `/implement-issue` 또는 PR 루프에서 처리한다.

### 2단계: 스펙 경로 판정

1. 관련 `docs/specs/`, `docs/architecture/`, `docs/decisions/` 문서를 읽는다.
2. 이슈가 스펙에 이미 정의된 구현이면 `1B Issue-First Bundled`로 진행한다.
3. 스펙 충돌, SSOT 불명확, 영향 범위 확장이 있으면 `needs-spec-first`로 판정하고 구현계획을 확정하지 않는다.
4. 이슈 본문에 스펙 경로와 기준 문서 링크를 명시한다.

### 3단계: Plan Preflight 시작 라벨

쓰기 모드에서는 Plan Preflight 시작 시 라벨을 정리한다.

```bash
gh issue edit #{번호} --remove-label "plan-preflight:done" || true
gh issue edit #{번호} --add-label "plan-preflight:started"
```

라벨을 정리한 직후 시작 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 시작**
- status: started
- mode: {default | refresh}
- spec-path: {1A Spec-First | 1B Issue-First Bundled | pending}
- next: 이슈 본문 Implementation Plan 작성/정비 후 Plan Review 요청"
```

`--dry-run`이면 라벨을 바꾸지 않고 필요한 라벨 변경만 보고한다.

### 4단계: 이슈 본문 구현계획 작성/정비

이슈 본문에 아래 섹션을 작성하거나 기존 내용을 최신화한다.

```markdown
## Implementation Plan

### Spec Path
- path: `1A Spec-First | 1B Issue-First Bundled`
- SSOT:
  - `docs/specs/...`

### File Map
- 수정 대상:
- 읽어야 할 호출자/소비자:
- 생성 산출물:

### Tasks
- [ ] ...

### Verification
- failing check:
- passing check:
- commands:

### Risk Flags
- `lifecycle | contract-drift | generated-artifact-sync | mutable-config | health-path | multi-consumer | none`

### Stop Conditions
- 스펙 충돌:
- 영향 범위 확장:
- failing check 불명확:

### Non-Goals
- ...

### Plan Review
- reviewer:
- verdict:
- feedback reflected:
- scope decision:
```

작성 원칙:

- `superpowers:writing-plans` 원칙을 Ante 이슈 본문에 맞게 적용한다.
- task는 개발 에이전트가 순서대로 실행할 수 있는 작은 체크박스 단위로 쓴다.
- 테스트 계획은 추상 문장이 아니라 실제 실행 명령 또는 확인 가능한 check로 쓴다.
- `narrow-scope` 가능성이 있으면 제외 범위와 후속 이슈 후보를 본문에 명시한다.
- 추론은 추론으로 표시하고, 스펙/코드에서 확인한 사실과 섞지 않는다.
- 다음 신호 중 하나가 있으면 계획 확정보다 `split-issue` 판정을 우선 검토한다.
  - 서로 다른 invariant가 한 PR 안에 섞인다.
  - API / CLI / schema / generated artifact / runtime lifecycle 중 둘 이상의 계약 축을 동시에 바꾼다.
  - producer와 consumer 경로를 모두 추적해야 하는데 한 계획 안에서 소비자 목록을 닫을 수 없다.
  - 예상 변경이 `40 files` 또는 `+1000 insertions`를 넘을 가능성이 높다.
  - Non-Goals로 둔 파일/경로를 건드리지 않으면 계획을 성립시킬 수 없다.
  - 선행/후속 관계가 있는 하위 작업을 한 이슈 안에서 동시에 구현해야 한다.

쓰기 모드에서는 이슈 본문 정비 직후 계획 정비 완료 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 계획 정비 완료**
- status: plan-ready-for-review
- spec-path: {1A Spec-First | 1B Issue-First Bundled}
- ssot: {docs/specs/...}
- risk flags: {none | lifecycle | contract-drift | generated-artifact-sync | mutable-config | health-path | multi-consumer}
- next: Plan Review 요청"
```

### 5단계: Plan Review 요청 (Gate 0)

정비된 구현계획을 별도 컨텍스트의 계획 리뷰 서브에이전트 `@plan-reviewer`로 넘긴다.
구현 세션과 격리된 read-only 리뷰이며, 이 단계는 코드 수정, 브랜치 생성, PR 생성을 하지 않는다.
`@plan-reviewer` 정의는 `.agent/agents/plan-reviewer.md`다.

```text
Agent(
  subagent_type="plan-reviewer",
  prompt="""
이슈 #{번호}의 본문 Implementation Plan을 검토하라.
가정, 범위 적합성, 누락된 소비자, 생성 산출물, 롤백/테스트 공백을 공격적으로 확인하라.

## 이슈 본문 Implementation Plan
{Spec Path / File Map / Tasks / Verification / Risk Flags / Stop Conditions / Non-Goals}

verdict(approve-implement | narrow-scope | revise-plan | split-issue | invoke-human)와 근거를 반환하라.
"""
)
```

`@plan-reviewer`는 동기 호출로 verdict와 근거를 반환한다(read-only, GitHub 쓰기 없음).
반환된 verdict를 오케스트레이터가 이슈 코멘트에 `Plan Review`로 남기고, `reviewer:` 필드에 리뷰 수행 주체를 기록한다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Review**
- verdict: {approve-implement | narrow-scope | revise-plan | split-issue | invoke-human}
- reviewer: @plan-reviewer
- reviewed-plan: 이슈 본문 Implementation Plan
- feedback summary: {요약}
- required changes: {없음 | 이슈 본문에 반영할 항목}
- next: {Plan Preflight 완료 | 이슈 본문 보강 후 재요청 | 분리/사람 판단 대기}"
```

Verdict:

- `approve-implement`: 계획대로 구현 가능
- `narrow-scope`: 축소 범위로 구현 가능
- `revise-plan`: 이슈 본문 보강 후 재검토 필요
- `split-issue`: 이슈 분리 필요
- `invoke-human`: 사람 판단 필요

### 6단계: 피드백 반영 루프

- `approve-implement`: 현재 구현계획을 확정한다.
- `narrow-scope`: 축소 범위, 제외 범위, 후속 이슈 후보를 이슈 본문에 반영한 뒤 확정한다.
- `revise-plan`: `plan-preflight:started` 상태를 유지하고 이슈 본문을 보강한 뒤 `Plan Review` 코멘트에 재요청 사유를 남기고 다시 요청한다.
- `split-issue`: 구현계획 확정을 중단하고 `Plan Preflight 보류` 코멘트에 아래 형식의 분리안을 남긴다. 하위 이슈 생성, 라벨 조작, 큐 편입, 부모 이슈 close 자동화는 하지 않는다.
- `invoke-human`: 구현계획 확정을 중단하고 `Plan Preflight 보류` 코멘트에 사람 판단이 필요한 질문을 남긴다.

`split-issue` 보류 코멘트에는 다음 구조를 사용한다.

```markdown
🤖 **Plan Preflight 보류**
- status: split-issue
- reason: {범위 과대 | 다중 invariant | 다중 consumer | 계약 축 혼재 | 선행/후속 관계 필요}
- autonomous action: none
- labels: plan-preflight:done 제거, plan-preflight:started 제거
- next: 사람 또는 별도 오케스트레이션이 아래 split plan을 기준으로 후속 이슈 등록

## Split Plan

### 후보 A
- 목표:
- 포함:
- 제외:
- 선행:
- 후속:
- 예상 수정 파일:
- 읽어야 할 소비자:
- 검증:
- risk class:
- stop conditions:

### 후보 B
- 목표:
- 포함:
- 제외:
- 선행:
- 후속:
- 예상 수정 파일:
- 읽어야 할 소비자:
- 검증:
- risk class:
- stop conditions:
```

split plan은 파일 묶음이 아니라 flow/invariant 기준으로 나눈다. 각 후보는 독립적으로 검증 가능해야 하며, 후속 이슈가 merge되기 전의 중간 상태가 안전한지 명시한다.

### 7단계: 완료 라벨

`approve-implement` 또는 `narrow-scope`가 반영된 경우에만 Plan Preflight를 완료한다.

```bash
gh issue edit #{번호} --remove-label "plan-preflight:started" || true
gh issue edit #{번호} --add-label "plan-preflight:done"
```

완료 직후 이슈 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 완료**
- status: done
- verdict: {approve-implement | narrow-scope}
- implementation plan: 이슈 본문 Implementation Plan 기준
- labels: plan-preflight:done
- next: `/implement-issue #{번호}` 실행 가능"
```

중단 시 라벨 처리:

- `needs-rewrite`, `needs-spec-first`, `blocked`, stale 계획: `plan-preflight:done` 제거
- `split-issue`, 사람 판단 또는 선행 이슈 대기: `plan-preflight:started` 제거 후 보류 사유 코멘트

중단 시에는 아래 코멘트를 남긴다.

```bash
gh issue comment #{번호} --body "🤖 **Plan Preflight 보류**
- status: {needs-rewrite | needs-spec-first | blocked | split-issue | invoke-human}
- reason: {스펙 충돌 | 선행 이슈 미완 | 범위 분리 필요 | 사람 판단 필요 | stale plan}
- labels: plan-preflight:done 제거, 필요 시 plan-preflight:started 제거
- next: {스펙 정리 | 선행 이슈 완료 대기 | 후속 이슈 분리 | 사람 답변 대기}"
```

`split-issue` 상태의 `next`는 자동 실행이 아니라 "후속 이슈 분리"다. 자동 하위 이슈 생성, 자동 실행 상태값, 부모 이슈 자동 close 같은 실행 계약은 이 커맨드 범위 밖이다.

## 결과 보고

사용자에게 아래를 요약한다.

```markdown
## Plan Preflight 완료

- issue: #123
- status: `done | needs-rewrite | needs-spec-first | blocked | split-issue | invoke-human`
- labels: `plan-preflight:started | plan-preflight:done | n-a`
- Plan Review: `approve-implement | narrow-scope | revise-plan | split-issue | invoke-human`
- 구현 인계 가능 여부:
- 주요 risk flags:
```
