오픈 이슈 큐를 야간 배치로 순차 처리하며, 필요 시 Plan Preflight로 구현계획을 확정한 뒤 `/implement-issue`에 위임한다.

이 파일이 `/autopilot` 실행 절차의 SSOT다. 런북은 정책과 링크만 제공하고, 큐 선별·상태 코멘트·리포트·merge/post-merge 모니터링의 실제 순서는 이 커맨드를 따른다.

## 인자

$ARGUMENTS — 옵션 (생략 가능)
- 없음: 기본 autopilot 큐 (`--limit 10`)
- `--limit {N}`: 이번 배치에서 처리할 최대 이슈 수 (기본 10, 최대 25)
- `--time-budget {예: 4h, 90m}`: 시간 예산이 소진되면 다음 이슈로 넘어가지 않고 종료
- `--label {라벨}`: 특정 라벨만 대상으로 제한
- `--handoff-only`: 예외적으로 PR 생성 후 기존 게이트 인계까지만 처리하고 merge/post-merge 확인은 생략
- `--strict-merge`: deprecated alias. 현재는 기본 동작과 동일하게 merge/post-merge까지 확인
- `--dry-run`: 2단계 snapshot 수집·정렬·한도 컷까지만 계산하고 실제 구현은 시작하지 않음

## 목적

`/autopilot`은 직접 코드를 구현하는 명령이 아니다. 이 커맨드는 오픈 이슈 큐를 정리하고, 지금 자동으로 처리해도 되는 이슈만 골라 **한 번에 하나씩** `/implement-issue`에 넘기고, 각 이슈의 merge/post-merge까지 순차 모니터링하는 야간 배치 오케스트레이터다. 다만 현재 implementation lane이 코드 수정, 리뷰, CI, merge 대기 중일 때 다른 후보 이슈에 대해 Plan Preflight만 선행 수행할 수 있다.

GitHub 조회/코멘트/PR 관련 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

기본 성공 기준:

- Plan Preflight 결과가 이슈 본문 구현계획으로 확정되었고
- 이슈가 `/implement-issue`를 통해 실제 수정과 PR 생성까지 진행되었고
- 같은 이슈의 `ci` 통과 + auto-merge + post-merge가 확인되었음

`--handoff-only`일 때만 PR 생성 후 머지 모니터링을 생략하고 종료한다.

## 운영 사이클

`/autopilot`은 아래 3개 사이클을 **같은 이슈에 대해 순차적으로** 끝낸 뒤에만 다음 이슈 구현으로 이동한다.

1. **Plan Preflight 사이클**
   - `plan-preflight:done` 라벨과 이슈 본문 구현계획 최신성을 확인한다.
   - 필요하면 `/plan-preflight #{번호}`로 구현계획과 Plan Review 피드백을 확정한다.
2. **개별 이슈 실행 사이클**
   - `/implement-issue #{번호}`를 호출해 실제 수정, 검증, PR 생성까지 진행한다.
   - Plan Preflight의 tasks, verification, risk flags, stop conditions는 구현 프롬프트에 강제 반영할 항목이다.
3. **머지 모니터링 사이클**
   - 머지 조건은 `ci` + `merge-gate` + auto-merge + `post-merge`다.
   - PR 단계의 자동 AI 승인 워커는 운영하지 않으므로 monitoring에 포함하지 않는다. 추가 검증이 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출한 결과를 PR 코멘트로 확인한다.

별도 선행 작업:

- implementation lane이 바쁠 때 다른 후보 이슈의 Plan Preflight를 수행할 수 있다.
- 이 선행 작업은 `/plan-preflight #{번호}`로 수행하며, 이슈 본문 구현계획 작성/보강, Plan Review 요청/결과 반영, `plan-preflight:*` 라벨 관리까지만 허용한다.
- Plan Preflight를 시작하면 `plan-preflight:started`를 붙이고, 구현계획이 확정되면 이슈 본문을 최신화한 뒤 `plan-preflight:done`으로 교체한다.
- `/plan-preflight`가 남기는 시작/계획 정비/리뷰/완료 코멘트는 Autopilot 상태 코멘트와 별개로 유지한다.
- 코드 수정, 브랜치 생성, PR 생성은 현재 implementation lane이 종료된 뒤 해당 이슈가 실제 처리 대상으로 선택될 때 수행한다.

## 상태 코멘트 계약

`/autopilot`은 활성 이슈마다 최신 `🤖 **Autopilot 사이클 상태**` 코멘트를 유지해 3개 사이클의 현재 상태를 한눈에 보이게 한다.

- 가능하면 같은 코멘트를 갱신한다.
- 코멘트 수정이 어렵다면 같은 헤더의 새 코멘트를 남기되, **가장 최신 코멘트**를 공식 상태로 본다.
- 이 코멘트는 이슈 단위의 운영 상태판이며, PR status check를 대체하지 않는다.

필수 필드:

- `batch`: `YYYYMMDD-HHMM`
- `issue`: `#번호`
- `current-cycle`: `review | implement | merge-monitor | completed`
- `review-state`: `pending | running | blocked | done`
- `implement-state`: `pending | running | blocked | done`
- `merge-monitor-state`: `pending | running | blocked | done`
- `preflight`: `pending | started | done | stale | blocked | n-a`
- `plan-review`: `approve-implement | narrow-scope | revise-plan | split-issue | invoke-human | n-a`
- `pr`: `#번호 | n-a`
- `head`: `{SHA7} | n-a`
- `result`: `in-progress | merged | handed-off | deferred-* | retry-later-infra | skipped-in-progress`
- `next`: 다음 자동 동작 또는 대기 사유
- `updated_at`: UTC timestamp

권장 템플릿:

```markdown
🤖 **Autopilot 사이클 상태**
- batch: 20260423-0130
- issue: #1234
- current-cycle: implement
- review-state: done
- implement-state: running
- merge-monitor-state: pending
- preflight: done
- plan-review: approve-implement
- pr: n-a
- head: a1b2c3d
- result: in-progress
- next: `/implement-issue #1234` 완료 후 PR 생성 대기
- updated_at: 2026-04-23T01:42:00Z
```

상태 전이 원칙:

- Plan Preflight 사이클 시작: `review-state=running`, 나머지는 `pending`
- Plan Preflight 시작: `preflight=started`, `plan-preflight:started` 라벨 부착, `plan-preflight:done` 라벨 제거
- Plan Preflight 완료: 이슈 본문 구현계획 최신화 후 `preflight=done`, `plan-preflight:started` 제거, `plan-preflight:done` 라벨 부착
- Plan Preflight stale/blocked: `preflight=stale` 또는 `blocked`, `plan-preflight:done` 라벨 제거
- Plan Preflight 완료 후 구현 위임: `review-state=done`, `implement-state=running`
- PR 생성 완료: `implement-state=done`, `merge-monitor-state=running`, `pr`/`head` 채움
- Plan Preflight/의존성/triage로 보류: 해당 사이클을 `blocked`로 두고 `result`를 `deferred-*`로 기록
- 머지 및 post-merge 확인 완료: `merge-monitor-state=done`, `current-cycle=completed`, `result=merged`
- `--handoff-only`: `merge-monitor-state=done`, `result=handed-off`

## 큐 선별 규칙

### 포함 대상

- 상태가 `open`
- 라벨이 `enhancement`, `bug`, `refactor`, `docs`, `test`, `chore` 중 하나
- 필요 시 `--label`로 좁힌 결과

> `feature`는 legacy 라벨이다. 신규 이슈에는 쓰지 않는다. 큐 선별 라벨 집합과 GitHub 기본 `enhancement`가 갈라져 이슈 판정이 실행마다 달라진 것이 재정 사유이며, 근거와 반대 방향 근거는 #2458에 있다. 이슈 type과 라벨의 매핑은 [00-issue-management.md](../../docs/runbooks/00-issue-management.md) §2를 따른다.

위 라벨이 하나도 붙지 않은 이슈의 편입 판정과 legacy `feature` 승계는 아래 `타입 라벨이 없는 이슈` 절을 따른다.

### 기본 제외 대상

- `needs-triage`
- `question`
- `blocked`
- `blocked:review-loop`
- `blocked:pr-review-loop`
- `epic`
- 이미 open PR이 연결된 이슈
- 선행 의존 이슈가 아직 close되지 않은 이슈

새 이슈는 배치 시작 시점에 snapshot으로 고정한다. 배치 도중 새로 등록된 이슈나 follow-up 이슈는 다음 실행으로 넘긴다.

### 타입 라벨이 없는 이슈

이 절이 라벨 판정의 정본이며, 실제 배치 집행 스텝은 아래 `실행 절차` → `3단계: Plan Preflight 사이클`의 per-issue 루프의 `feature 승계`·`타입·area 라벨 판정` 항목이다.

- `feature` 라벨이 붙은 이슈에는(다른 라벨과의 병기 포함, reopen 여부 판별 불요) **이 절의 편입/미편입 판정 전에** [00-issue-management.md](../../docs/runbooks/00-issue-management.md) §4 `feature` 행의 승계 규칙을 먼저 적용한다. 이 불릿은 타입 라벨을 이미 가진 이슈에도 적용하고, 이슈 제외가 아니라 라벨 정정이므로 루프에 진입한 이슈에는 open PR 유무와 무관하게 적용하며, 승계 후에는 타입 라벨 보유로 정상 편입된다. 2단계 후행 검사에서 제외된 이슈는 루프에 진입하지 않으므로 승계는 그 이슈가 다시 큐 후보가 되는 시점에 적용된다. 승계 규칙 자체의 정본은 §4 `feature` 행이고, 이 불릿은 autopilot 실행 경로에서의 적용 지점이다.
- 타입 라벨이 없어도 area 라벨(`core`·`cli`·`api`·`e2e`·`dashboard`) 중 하나가 있으면 큐에 정상 편입한다.
- 타입 라벨과 area 라벨이 모두 없으면 큐에 편입하지 않는다.
- 미편입 이슈에는 아래 `3단계: Plan Preflight 사이클`의 `🤖 **Autopilot 보류**` 코멘트를 사유 `타입 라벨 부재`로 남기고 `needs-triage`를 부착한다. 결과 분류는 기존 `deferred-triage`를 재사용한다.
- 라벨 판정이 아래 `내부 생성 미검증 버그 후보 검증 선행`의 `이슈 검증` 게이트보다 먼저다. 큐 후보가 아닌 이슈에는 `@issue-reviewer`를 호출하지 않으며, 사람이 라벨을 정리해 재평가될 때 `이슈 검증`이 선행한다.
- `needs-triage` 부착 후에는 자동 경로는 2단계 snapshot의 server-side 필터가, 수동 `/implement-issue`는 자체 거부 규칙이 걸러내 양쪽에서 보이지 않는다. 사람이 라벨을 정리할 때까지의 절충으로 수용한다.
- 불변식: 탈락분은 snapshot에서 관측 가능해야 한다. 이 불변식을 지키는 집행 형태는 #2460이 소유한다.

### 내부 생성 미검증 버그 후보 검증 선행

협업자 또는 내부 자동화가 등록한 미검증 버그 후보(예: `source:ante-oracle` 라벨이 붙은 자동 리포트)는 루트원인 추정이 부정확할 수 있어, 위 `타입 라벨이 없는 이슈` 판정을 통과한 뒤 구현 큐 편입 전에 `이슈 검증`을 선행한다. 상시 게이트가 아니며, 내부에서 기획한 이슈에는 적용하지 않는다. 실제 배치 실행 스텝은 아래 `실행 절차` → `3단계: Plan Preflight 사이클`의 per-issue 루프의 `내부 생성 미검증 버그 후보 검증` 항목이다. 이 절은 그 스텝의 정책 요약이다.

- 이슈에 `이슈 검증` 코멘트의 `confirmed` 증적이 이미 있으면 그대로 큐에 편입한다.
- `confirmed` 증적이 없으면 `@issue-reviewer`(`.agent/agents/issue-reviewer.md`)를 **read-only로 호출해 verdict를 반환받는다.** `@issue-reviewer`는 GitHub에 코멘트·라벨을 쓰지 않는다. 코멘트·라벨 쓰기는 오케스트레이터가 verdict를 받아 수행한다(검증과 쓰기 주체 분리 — 서브에이전트 gh 쓰기 실패로 인한 fail-open 방지).
- 반환된 verdict를 오케스트레이터가 이슈에 `🤖 **이슈 검증**` 증적 코멘트(`reviewer: @issue-reviewer`)로 남긴다.
- verdict가 `confirmed`가 아니면(`not-reproduced` / `invalid` / `needs-info`) 오케스트레이터가 이어서 `needs-triage` 라벨을 부착한다. 이 이슈는 위 `기본 제외 대상`의 `needs-triage` 규칙에 따라 자동으로 큐에서 빠지며, 사람 판단을 기다린다. 자동 close는 하지 않는다.
- verdict가 `confirmed`면 `needs-triage` 없이 큐에 편입한다.

## 정렬 규칙

1. 우선순위 `P0 → P1 → P2 → P3`
2. 우선순위 라벨이 2개 이상 중복 부착된 이슈에는 그중 가장 높은 우선순위를 적용한다.
3. 우선순위 라벨이 없는 이슈는 `P3` 뒤, 즉 큐의 맨 끝 구간에 둔다. 우선순위 라벨이 없다는 이유로 큐에서 제외하지 않으며, 아래 4·5번은 그 구간 안에서도 그대로 적용한다.
4. 같은 우선순위 안에서는 선행 의존성이 없는 이슈 우선
5. 같은 조건이면 오래 열린 이슈 우선

여러 이슈를 동시에 구현하지 않는다. 현재 활성 이슈가 merge/post-merge 완료 또는 명시적 보류 상태로 정리된 뒤에만 다음 이슈로 이동한다.

## 배치 한도

- 기본 처리 한도는 `10`개다.
- `--limit`이 생략되면 `10`으로 간주한다.
- `--limit`에 `25`보다 큰 값이 들어오면 `25`로 고정하고, 그 사실을 리포트에 기록한다.
- 현재 활성 이슈가 merge/post-merge까지 정리되지 않으면, 남은 한도와 무관하게 다음 이슈로 넘어가지 않는다.

## Plan Preflight 규칙

### Plan Preflight 병렬 lane

- 현재 활성 이슈가 구현, 브랜치 리뷰, CI, merge-gate 또는 merge 대기 중이면 다른 후보 이슈의 Plan Preflight를 수행할 수 있다.
- Plan Preflight 절차와 `plan-preflight:started`/`plan-preflight:done` 라벨·verdict 수명주기의 SSOT는 `.agent/commands/plan-preflight.md`다. autopilot은 직접 다른 절차를 만들지 않고 `/plan-preflight #{번호}`를 호출하며 그 수명주기를 따른다.
- 완료된 `plan-preflight:done` 계획은 다음 `/autopilot` 또는 `/implement-issue`가 확정 계획으로 재사용한다. 이미 `plan-preflight:done`이고 이슈 본문/스펙/선행 조건이 stale하지 않으면 Plan Preflight를 반복하지 않는다.
- `needs-rewrite`, `needs-spec-first`, `blocked`가 나오면 같은 배치에서 구현 대상으로 넘기지 않는다.
- 같은 이슈 또는 같은 open PR에 대해서는 implementation lane과 Plan Preflight lane을 병렬로 돌리지 않는다.

### 구현 전 점검 기준

- Plan Preflight가 사전점검의 SSOT다.
- API / CLI / schema / field rename, cache / reconnect / mutable config, multi-consumer 영향, health path 변경, 에픽 의존성 불명확성은 Plan Preflight의 `Risk Flags`와 `Stop Conditions`에 반영한다.
- `approve-implement` 또는 `narrow-scope`가 이슈 본문에 반영되어 `plan-preflight:done`이 붙은 이슈만 `/implement-issue`로 넘긴다.
- `revise-plan`, `split-issue`, `invoke-human`, `needs-spec-first`, `blocked`는 같은 배치의 구현 대상으로 넘기지 않는다.

## 실행 절차

### 1단계: 단일 실행 보장

- 같은 시간대에 다른 autopilot 배치가 이미 진행 중이면 새 배치를 시작하지 않는다.
- 중복 실행이 감지되면 이번 배치는 종료하고 사용자에게 보고한다.

### 2단계: 큐 snapshot 수집

```bash
REPO="$(gh repo view --json nameWithOwner --jq '.nameWithOwner')"
QUERY="repo:${REPO} is:issue is:open sort:created-asc \
  -label:needs-triage \
  -label:question \
  -label:blocked \
  -label:blocked:review-loop \
  -label:blocked:pr-review-loop \
  -label:epic"

page=1
while :; do
  batch="$(gh api search/issues -f q="$QUERY" -f per_page=100 -f page="$page" --jq '.items')"
  [[ "$batch" == "[]" ]] && break
  printf '%s\n' "$batch"
  page=$((page + 1))
done
```

- 큐 snapshot은 "앞 100건만 가져온 뒤 로컬에서 후행 필터링"하지 않는다.
- `needs-triage`와 기본 제외 라벨은 **수집 단계에서 server-side search filter로 먼저 제외**한다.
- snapshot은 100건 단일 조회가 아니라 **pagination으로 끝까지 수집한 전체 open issue 후보 집합**으로 고정한다.
- 위 전체 snapshot에 대해서만 open PR 존재, 선행 의존 이슈 close 여부, `--label` 좁히기처럼 server-side로 표현하기 어려운 후행 검사를 적용한다. 이 후행 검사가 해당 제외의 소유 단계이며, 3단계 per-issue 루프의 open PR·선행 의존 항목은 배치 도중의 상태 변화를 잡는 stale snapshot 재확인이다.
- 타입·area 라벨 판정(위 `타입 라벨이 없는 이슈`)은 server-side 필터가 아니라 3단계 per-issue 루프의 `타입·area 라벨 판정` 항목에서 집행한다. 판정 대상 이슈는 2단계 snapshot에 그대로 남는다.
- snapshot 후 실제 처리 대상은 정렬 결과 상위 `min(limit, 25)`건으로 자른다.
- 큐 snapshot이 1건 이상이면 `default`·`handoff-only`·`dry-run` 공통으로 첫 리포트를 쓰기 전에 `mkdir -p docs/temp`를 실행한다. `docs/temp/`는 gitignore 대상이므로 clean clone/worktree에 없을 수 있다.
- 이번 배치 큐가 1건 이상이면 실행 모드와 관계없이 `docs/temp/autopilot-report-<YYYYMMDD-HHMM>.md` 리포트를 반드시 생성한다.
- `--dry-run`이면 이 단계 결과를 리포트에 남기고 종료한다. feature 승계·타입·area 라벨 판정·`이슈 검증`은 3단계 집행이므로 `--dry-run` 결과에는 반영되지 않는다(한계 — 예상 판정 포함은 #2491이 소유한다).

### 3단계: Plan Preflight 사이클

각 이슈마다 다음을 순서대로 수행한다.

1. **`needs-triage` 여부 재확인 (2단계 server-side 필터의 재확인)**: 배치 도중 부착되지 않았는지 재확인한다. 부착되어 있으면 이 이슈를 이번 배치에서 제외하고(6단계 `deferred-triage`) 다음 이슈로 넘어간다.
2. **feature 승계**: `큐 선별 규칙` → `타입 라벨이 없는 이슈` 절 첫 불릿의 승계 규칙을 적용한다. 적용 조건과 범위는 그 불릿이 정본이다.
3. **open PR 존재 확인 (2단계 후행 검사의 재확인)**: 이슈에 open PR이 이미 연결되어 있으면 `needs-triage`를 부착하지 않고 보류 코멘트도 남기지 않으며, 6단계 `skipped-in-progress`로 분류하고 다음 이슈로 넘어간다.
4. **타입·area 라벨 판정**: `큐 선별 규칙` → `타입 라벨이 없는 이슈` 절의 편입/미편입 판정을 적용한다. 미편입이면 그 절이 정한 보류 코멘트(사유 `타입 라벨 부재`)와 `needs-triage`를 남기고 이 이슈를 **이번 배치에서 제외(다음 순번으로)**. 편입이면 정상 진행한다.
5. **내부 생성 미검증 버그 후보 검증 (조건부, `이슈 검증` 게이트)**: 이슈가 협업자 또는 내부 자동화가 등록한 미검증 후보(`source:ante-oracle` 라벨 등)이고 `confirmed` `이슈 검증` 증적이 없으면(= 최신 `이슈 검증` verdict가 `confirmed`가 아니면; non-confirmed 코멘트만 있는 재큐 상태도 포함) `@issue-reviewer`(`.agent/agents/issue-reviewer.md`)를 **read-only로 호출해 verdict를 반환받는다.** 오케스트레이터가 반환된 verdict를 `🤖 **이슈 검증**` 코멘트(`reviewer: @issue-reviewer`)로 남긴다. verdict가 `confirmed`가 아니면(`not-reproduced`/`invalid`/`needs-info`) 오케스트레이터가 `needs-triage`를 부착하고 이 이슈를 **이번 배치에서 제외(다음 순번으로)**. `confirmed`면 코멘트만 남기고 정상 진행한다. 내부 기획 이슈에는 적용하지 않으며, `@issue-reviewer`는 GitHub에 쓰지 않는다(검증·쓰기 주체 분리 — fail-open 방지).
6. 선행 의존 이슈 close 여부 확인 (2단계 후행 검사의 재확인)
7. `plan-preflight:started`/`plan-preflight:done` 라벨과 이슈 본문 구현계획 최신성 확인
8. 필요 시 `/plan-preflight #{번호}` 실행

`plan-preflight:done` 라벨이 없거나 stale이면 `/plan-preflight #{번호}`를 먼저 수행하고, 이슈 본문 구현계획이 확정되어 `plan-preflight:done`이 된 뒤에만 `/implement-issue`로 넘긴다.

이 단계에 진입하면 이슈의 최신 `🤖 **Autopilot 사이클 상태**` 코멘트를 `current-cycle=review`, `review-state=running`으로 맞춘다.

Plan Preflight가 완료되면, autopilot은 이슈 본문 구현계획의 다음 정보를 **구현 필수 체크리스트**로 묶어 다음 단계에 넘긴다.

- tasks
- verification
- risk flags
- stop conditions
- 이번 PR에서 하지 말아야 할 확장

이 단계에서 이슈를 이번 배치에서 제외할 때는 아래 코멘트를 남긴다. 예외 둘: open PR이 이미 있는 이슈는 6단계 `skipped-in-progress`로 분류하며 PR 자체가 증적이라 별도 보류 코멘트를 남기지 않고, `이슈 검증` verdict가 confirmed가 아닌 이슈는 `이슈 검증` 증적 코멘트와 `needs-triage` 부착이 증적이라 중복 코멘트를 남기지 않는다.

```markdown
🤖 **Autopilot 보류**
- 이슈: #{번호}
- 사유: {needs-triage | 타입 라벨 부재 | 선행 이슈 미완료 | plan-preflight blocked | plan-preflight needs-rewrite | revise-plan | needs-spec-first | split-issue | invoke-human}
- 다음 단계: {triage 제거 | 타입/area 라벨 부착 후 needs-triage 제거 | 선행 이슈 완료 대기 | 스펙 정리 | 계획 재작성 | 테스트 설계 보강 | 후속 이슈 분리 | 사람 답변 대기}
```

두 enum은 각각 독립 목록이며 위치가 서로 대응하지 않는다 — 사유와 다음 단계는 상황에 맞게 각각 고른다.

### 4단계: 개별 이슈 실행 사이클

`plan-preflight:done` 라벨과 최신 이슈 본문 구현계획이 있는 이슈만 `/implement-issue #{번호}`로 넘긴다.

- `/implement-issue`는 이슈 본문 Implementation Plan과 Plan Review 결과를 읽고 구현 착수 코멘트와 개발 에이전트 프롬프트에 포함한다.
- Plan Preflight의 tasks, verification, risk flags, stop conditions는 **선택 메모가 아니라 Done criteria**다.
- 확정 계획을 반영한 실제 수정, 테스트, PR 생성이 확인될 때까지 같은 이슈를 유지한다.
- 이 단계에 진입하면 상태 코멘트를 `review-state=done`, `implement-state=running`, `current-cycle=implement`로 갱신한다.

Plan Preflight는 의견만 남기고 종료하는 단계가 아니다. autopilot은 확정된 구현계획을 구현 단계로 연결하지 못한 이슈를 성공으로 취급하지 않는다.

### 5단계: 머지 모니터링 사이클

PR이 생성되면 autopilot은 같은 이슈에 머물며 아래를 순서대로 모니터링한다.

1. `ci` (required, 머지 차단 게이트)
2. `merge-gate`
3. auto-merge
4. `post-merge` 후처리

모니터링 규칙:

- 같은 head SHA에서 `ci`/`merge-gate`가 인프라 이슈로 멈추면 `gh run rerun`을 우선하고, 복구되지 않으면 `retry-later-infra`로 종료한다.
- PR 후 추가 코드 변경이 필요해 보이면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 `ci` 결과를 다시 확인한다.
- 상태 변화 없이 장시간 대기하거나 `--time-budget`이 소진되면 현재 이슈를 `deferred-merge-monitoring`으로 기록하고 배치를 종료한다.
- `--handoff-only`일 때만 PR 생성 직후 모니터링을 생략하고 `handed-off`로 기록한다.
- PR이 생성되는 즉시 상태 코멘트를 `implement-state=done`, `merge-monitor-state=running`, `current-cycle=merge-monitor`로 갱신하고 `pr`/`head`를 채운다.
- `post-merge.yml`이 연결 이슈에 `🤖 **Post-merge 정리 완료**` 코멘트를 남겼는지 확인한다. 예전 run처럼 코멘트가 없고 이슈 close/체크박스 갱신만 확인되면 Autopilot 상태 코멘트를 `result=merged`로 갱신하면서 누락 사실을 기록한다.

### 6단계: 결과 분류

각 이슈는 아래 중 하나로 정리한다.

- `merged`: PR merged + post-merge 확인 완료
- `handed-off`: `--handoff-only`에서만 사용
- `deferred-triage`: `needs-triage`가 남아 있어 보류
- `deferred-dependency`: 선행 이슈 미완
- `deferred-preflight`: Plan Preflight가 구현 불가 상태로 끝남
- `deferred-scope`: 확정 계획을 구현으로 이어가려면 남은 배치 예산을 초과
- `deferred-merge-monitoring`: PR은 생성됐지만 merge/post-merge 확인 전 시간 예산 또는 대기 임계값 소진
- `retry-later-infra`: 인증/러너/네트워크 등 공통 인프라 문제
- `skipped-in-progress`: 이미 open PR 또는 사람이 작업 중

### 7단계: 배치 종료

종료 시에는 사용자에게 다음을 요약한다.

- 실행 시각과 소요 시간
- 큐 snapshot 크기
- 실제 처리 한도 (`limit`, clamp 여부)
- merge 완료 건수
- 보류 건수와 사유 분포
- 인프라 오류 여부

이번 배치 큐 snapshot이 1건 이상이었다면 `docs/temp/autopilot-report-<YYYYMMDD-HHMM>.md`를 반드시 남긴다.

리포트 최소 포함 항목:

- 실행 시각 / 종료 시각 / 소요 시간
- 실행 모드 (`default | handoff-only | dry-run`)
- 큐 snapshot 크기
- 실제 처리 한도 (`limit`, clamp 여부)
- 이슈별 사이클 상태 표 (`review-state | implement-state | merge-monitor-state`)
- 이슈별 결과 표 (`merged | handed-off | deferred-* | retry-later-infra | skipped-in-progress`)
- 스킵/보류 상세
- 남은 작업 또는 후속 조치

리포트 말미에는 **프로세스 회고**를 반드시 포함한다.

- `### 있었던 사건`
  - 예: 특정 runner 대기 지연, stale base, merge conflict, review-loop 반복, 인증 실패, 수동 재실행 필요
- `### 개선 포인트`
  - 예: 라벨 규칙 보강, Plan Preflight 조건 조정, runner capacity 조정, 코멘트 템플릿 정리, 큐 정렬 규칙 수정

공식 증적은 GitHub 이슈/PR 코멘트와 PR status check다. PR 전 브랜치 리뷰는 status check가 아니라 이슈 코멘트의 `/code-review` PASS/FAIL 기록으로 확인한다. `docs/temp/autopilot-report-*.md`는 배치 전체를 한 번에 회고하는 운영 리포트다.

## 중단 규칙

- 공통 인프라 오류가 3회 연속 나오면 이번 배치를 중단한다.
- 시간 예산이 소진되면 현재 이슈 정리 후 종료한다.
- 같은 이슈를 같은 배치에서 반복 재집지 않는다.
- `blocked:review-loop` 또는 `blocked:pr-review-loop`가 붙은 이슈는 배치가 억지로 밀어붙이지 않는다.
- `blocked:review-loop`는 브랜치 리뷰 10회 소진의 안전장치로 해석한다. `blocked:pr-review-loop`는 자동 PR 재수정 루프가 더 이상 운영되지 않는 환경에서도 큐 제외 / 사람 개입 대기 신호로 유지하며, autopilot은 해당 이슈를 보류하고 다음 이슈로 넘어간다.
- 현재 이슈가 merge/post-merge 확인 전 상태라면, 다음 이슈를 시작하지 않고 해당 이슈 상태를 먼저 확정한다.

## 원칙

1. autopilot은 큐 관리자이지만, review → implement → merge-monitor의 3사이클을 끝까지 잇는 오케스트레이터다
2. 공식 구현 절차는 `/implement-issue`가 계속 SSOT다
3. Plan Preflight 결과는 이슈 본문 구현계획과 라벨로 확정하고, 구현 단계에서 반드시 소비한다
4. `needs-triage`가 붙은 이슈는 사람이 분류하기 전까지 건드리지 않는다
5. 기본 모드는 merge-confirmation 우선이며, `--handoff-only`는 예외적인 throughput 모드다
