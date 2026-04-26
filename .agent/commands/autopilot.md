오픈 이슈 큐를 야간 배치로 순차 처리하며, 필요 시 사전 리뷰 증적을 남긴 뒤 `/implement-issue`에 위임한다.

## 인자

$ARGUMENTS — 옵션 (생략 가능)
- 없음: 기본 autopilot 큐 (`--limit 10`)
- `--limit {N}`: 이번 배치에서 처리할 최대 이슈 수 (기본 10, 최대 10)
- `--time-budget {예: 4h, 90m}`: 시간 예산이 소진되면 다음 이슈로 넘어가지 않고 종료
- `--label {라벨}`: 특정 라벨만 대상으로 제한
- `--handoff-only`: 예외적으로 PR 생성 후 기존 게이트 인계까지만 처리하고 merge/post-merge 확인은 생략
- `--strict-merge`: deprecated alias. 현재는 기본 동작과 동일하게 merge/post-merge까지 확인
- `--dry-run`: 큐 선별과 선행 리뷰 필요 여부만 계산하고 실제 구현은 시작하지 않음

## 목적

`/autopilot`은 직접 코드를 구현하는 명령이 아니다. 이 커맨드는 오픈 이슈 큐를 정리하고, 지금 자동으로 처리해도 되는 이슈만 골라 **한 번에 하나씩** `/implement-issue`에 넘기고, 각 이슈의 merge/post-merge까지 순차 모니터링하는 야간 배치 오케스트레이터다. 다만 현재 implementation lane이 코드 수정, 리뷰, CI, merge 대기 중일 때 다른 후보 이슈에 대해 Plan Preflight만 선행 수행할 수 있다.

GitHub 조회/코멘트/PR 관련 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

기본 성공 기준:

- 사전 리뷰 결과가 구현 체크리스트로 정리되었고
- 이슈가 `/implement-issue`를 통해 실제 수정과 PR 생성까지 진행되었고
- 같은 이슈의 CI + 승인 + auto-merge + post-merge가 확인되었음

`--handoff-only`일 때만 PR 생성 후 기존 리뷰 게이트 인계에서 종료한다.

## 운영 사이클

`/autopilot`은 아래 3개 사이클을 **같은 이슈에 대해 순차적으로** 끝낸 뒤에만 다음 이슈 구현으로 이동한다.

1. **의견 검토 사이클**
   - `arch-review`를 재사용 또는 refresh한다.
   - `ready` / `caution` verdict에서 나온 주의사항, 테스트 follow-up, 범위 경계는 구현 체크리스트로 승격한다.
2. **개별 이슈 실행 사이클**
   - `/implement-issue #{번호}`를 호출해 실제 수정, 검증, PR 생성까지 진행한다.
   - 사전 리뷰의 `caution`은 종료 사유가 아니라, 구현 프롬프트에 강제 반영할 항목이다.
3. **머지 모니터링 사이클**
   - CI, `claude-pr-approve`, `codex-pr-approve`, auto-merge, `post-merge`까지 같은 이슈를 계속 추적한다.
   - 승인 워커의 `content` FAIL은 현재 이슈의 수정 루프 일부로 간주하며, 다음 이슈로 넘어가지 않는다.

별도 선행 작업:

- implementation lane이 바쁠 때 다른 후보 이슈의 Plan Preflight를 수행할 수 있다.
- 이 선행 작업은 이슈 본문/코멘트의 실행계획 작성 또는 보강까지만 허용한다.
- Plan Review, 코드 수정, 브랜치 생성, PR 생성은 현재 implementation lane이 종료된 뒤 해당 이슈가 실제 처리 대상으로 선택될 때 수행한다.

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
- `review-verdicts`: `arch=ready/caution/blocked/n-a`
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
- review-verdicts: arch=caution
- pr: n-a
- head: a1b2c3d
- result: in-progress
- next: `/implement-issue #1234` 완료 후 PR 생성 대기
- updated_at: 2026-04-23T01:42:00Z
```

상태 전이 원칙:

- 의견 검토 시작: `review-state=running`, 나머지는 `pending`
- 사전 리뷰 통과 후 구현 위임: `review-state=done`, `implement-state=running`
- PR 생성 완료: `implement-state=done`, `merge-monitor-state=running`, `pr`/`head` 채움
- 리뷰/의존성/triage로 보류: 해당 사이클을 `blocked`로 두고 `result`를 `deferred-*`로 기록
- 머지 및 post-merge 확인 완료: `merge-monitor-state=done`, `current-cycle=completed`, `result=merged`
- `--handoff-only`: `merge-monitor-state=done`, `result=handed-off`

## 큐 선별 규칙

### 포함 대상

- 상태가 `open`
- 라벨이 `feature`, `bug`, `refactor`, `docs`, `test`, `chore` 중 하나
- 필요 시 `--label`로 좁힌 결과

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

## 정렬 규칙

1. 우선순위 `P0 → P1 → P2 → P3`
2. 같은 우선순위 안에서는 선행 의존성이 없는 이슈 우선
3. 같은 조건이면 오래 열린 이슈 우선

여러 이슈를 동시에 구현하지 않는다. 현재 활성 이슈가 merge/post-merge 완료 또는 명시적 보류 상태로 정리된 뒤에만 다음 이슈로 이동한다.

## 배치 한도

- 기본 처리 한도는 `10`개다.
- `--limit`이 생략되면 `10`으로 간주한다.
- `--limit`에 `10`보다 큰 값이 들어오면 `10`으로 고정하고, 그 사실을 리포트에 기록한다.
- 현재 활성 이슈가 merge/post-merge까지 정리되지 않으면, 남은 한도와 무관하게 다음 이슈로 넘어가지 않는다.

## 사전 리뷰 규칙

### Plan Preflight 병렬 lane

- 현재 활성 이슈가 구현, 브랜치 리뷰, CI, PR 승인, merge 대기 중이면 다른 후보 이슈의 Plan Preflight를 수행할 수 있다.
- Plan Preflight는 `superpowers:writing-plans` 원칙에 따라 이슈 본문을 실행 가능한 계획으로 보강한다.
- Plan Preflight의 `ready`는 Plan Review로 넘길 준비가 되었다는 뜻이며, 구현 승인으로 해석하지 않는다.
- `needs-rewrite`, `needs-spec-first`, `blocked`가 나오면 같은 배치에서 구현 대상으로 넘기지 않는다.
- 같은 이슈 또는 같은 open PR에 대해서는 implementation lane과 Plan Preflight lane을 병렬로 돌리지 않는다.

### `arch-review`를 먼저 거는 경우

- API / CLI / schema / field rename 가능성
- cache / invalidate / reconnect / mutable config / health-path 신호
- 둘 이상의 모듈과 소비자 경로가 함께 흔들릴 가능성
- 에픽 하위 이슈의 선행/후속 관계가 불명확

### 재사용 규칙

- 이슈에 최신 `🏗️ **아키텍트 리뷰**` 코멘트가 있으면 그대로 재사용한다.
- 이미 남아 있는 사전 리뷰 증적을 덮어쓰지 않는다. 새 정보가 없으면 중복 리뷰를 남기지 않는다.
- 다만 최신 리뷰에 `verdict:`가 없거나, 최신 verdict가 `blocked`/`caution`인데 이슈 본문·스펙·선행 조건이 이후 바뀌었다면 `/arch-review`를 다시 호출해 refresh verdict를 남긴다.

### 판정 해석

- `ready`: `/implement-issue` 인계 가능
- `caution`: `/implement-issue` 인계 가능하나 주의사항 또는 테스트 follow-up을 반드시 반영
- `blocked`: autopilot이 구현을 시작하지 않고 다음 이슈로 이동

`ready` / `caution`은 모두 다음 사이클(`/implement-issue`)로 이어져야 한다. `caution` 항목은 착수 코멘트와 구현 프롬프트의 **필수 반영 체크리스트**로 넘기고, `blocked`만 보류 사유가 된다.

`blocked`가 나오면 같은 배치에서 억지로 `/implement-issue`를 호출하지 않는다. 보류 사유를 이슈 코멘트로 남기고 사람 판단이나 후속 이슈를 기다린다.

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
- 위 전체 snapshot에 대해서만 open PR 존재, 선행 의존 이슈 close 여부, `--label` 좁히기처럼 server-side로 표현하기 어려운 후행 검사를 적용한다.
- snapshot 후 실제 처리 대상은 정렬 결과 상위 `min(limit, 10)`건으로 자른다.
- 이번 배치 큐가 1건 이상이면 실행 모드와 관계없이 `docs/temp/autopilot-report-<YYYYMMDD-HHMM>.md` 리포트를 반드시 생성한다.
- `--dry-run`이면 이 단계 결과를 리포트에 남기고 종료한다.

### 3단계: 의견 검토 사이클

각 이슈마다 다음을 순서대로 수행한다.

1. `needs-triage` 여부 재확인
2. 선행 의존 이슈 close 여부 확인
3. open PR 존재 여부 확인
4. `arch-review` 필요 여부 판단
5. 기존 리뷰 증적 재사용 또는 신규 리뷰 실행

최신 사전 리뷰에 `verdict:`가 없거나, 오래된 `blocked` verdict가 최신 이슈 상태를 반영하지 못하면 refresh 리뷰를 먼저 남긴 뒤 그 결과를 사용한다.

이 단계에 진입하면 이슈의 최신 `🤖 **Autopilot 사이클 상태**` 코멘트를 `current-cycle=review`, `review-state=running`으로 맞춘다.

`ready` 또는 `caution` verdict가 나오면, autopilot은 다음 정보를 **구현 필수 체크리스트**로 묶어 다음 단계에 넘긴다.

- 아키텍처 주의사항
- 테스트 follow-up
- 범위에 포함해야 할 스펙/문서/생성 산출물 동기화
- 이번 PR에서 하지 말아야 할 확장

사전 리뷰가 `caution`이라는 이유만으로 같은 배치에서 종료하지 않는다. 구현 착수 여부를 결정하는 기준은 `blocked` 여부와 남은 시간 예산이다.

`needs-triage`는 이미 2단계 server-side snapshot에서 제외되어 있어야 하며, 여기서는 stale snapshot이나 수동 개입 여부를 다시 확인하는 안전 검사를 수행한다.

사전 리뷰 결과가 `blocked`면 이슈 코멘트에 다음을 남기고 스킵한다.

```markdown
🤖 **Autopilot 보류**
- 이슈: #{번호}
- 사유: {needs-triage | 선행 이슈 미완료 | arch-review blocked}
- 다음 단계: {triage 제거 | 선행 이슈 완료 대기 | 스펙 정리 | 테스트 설계 보강}
```

### 4단계: 개별 이슈 실행 사이클

사전 리뷰를 통과한 이슈만 `/implement-issue #{번호}`로 넘긴다.

- `arch-review` 증적은 이슈 코멘트에 남아 있어야 한다.
- `/implement-issue`는 그 증적을 읽고 구현 착수 코멘트와 개발 에이전트 프롬프트에 요약을 포함한다.
- `caution` verdict의 주의사항과 테스트 follow-up은 **선택 메모가 아니라 Done criteria**다.
- 리뷰 의견을 반영한 실제 수정, 테스트, PR 생성이 확인될 때까지 같은 이슈를 유지한다.
- 이 단계에 진입하면 상태 코멘트를 `review-state=done`, `implement-state=running`, `current-cycle=implement`로 갱신한다.

사전 리뷰는 의견만 남기고 종료하는 단계가 아니다. autopilot은 리뷰 증적을 구현 단계로 연결하지 못한 이슈를 성공으로 취급하지 않는다.

### 5단계: 머지 모니터링 사이클

PR이 생성되면 autopilot은 같은 이슈에 머물며 아래를 순서대로 모니터링한다.

1. `ci`
2. `claude-pr-approve`
3. `codex-pr-approve`
4. `merge-gate`
5. auto-merge
6. `post-merge` 후처리

모니터링 규칙:

- `content` FAIL이 나오면 Claude 자동 재수정 루프가 새 커밋을 push할 때까지 기다리고, 새 head SHA 기준으로 같은 모니터링을 반복한다.
- 같은 head SHA에서 `quota`, `script_error`, `auth_error`, `infra_error`로 멈추면 `gh run rerun`을 우선하고, 복구되지 않으면 `retry-later-infra`로 종료한다.
- 상태 변화 없이 장시간 대기하거나 `--time-budget`이 소진되면 현재 이슈를 `deferred-merge-monitoring`으로 기록하고 배치를 종료한다.
- `--handoff-only`일 때만 PR 생성 직후 모니터링을 생략하고 `handed-off`로 기록한다.
- PR이 생성되는 즉시 상태 코멘트를 `implement-state=done`, `merge-monitor-state=running`, `current-cycle=merge-monitor`로 갱신하고 `pr`/`head`를 채운다.

### 6단계: 결과 분류

각 이슈는 아래 중 하나로 정리한다.

- `merged`: PR merged + post-merge 확인 완료
- `handed-off`: `--handoff-only`에서만 사용
- `deferred-triage`: `needs-triage`가 남아 있어 보류
- `deferred-dependency`: 선행 이슈 미완
- `deferred-review`: `arch-review`가 `blocked`
- `deferred-scope`: 리뷰 결과를 구현으로 이어가려면 남은 배치 예산을 초과
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
  - 예: 특정 runner 대기 지연, PR 승인 워커 충돌, stale base, merge conflict, review-loop 반복, 인증 실패, 수동 재실행 필요
- `### 개선 포인트`
  - 예: 라벨 규칙 보강, 선행 리뷰 강제, runner capacity 조정, 코멘트 템플릿 정리, 큐 정렬 규칙 수정

공식 증적은 GitHub 이슈/PR 코멘트와 status check이고, `docs/temp/autopilot-report-*.md`는 배치 전체를 한 번에 회고하는 운영 리포트다.

## 중단 규칙

- 공통 인프라 오류가 3회 연속 나오면 이번 배치를 중단한다.
- 시간 예산이 소진되면 현재 이슈 정리 후 종료한다.
- 같은 이슈를 같은 배치에서 반복 재집지 않는다.
- `blocked:review-loop` 또는 `blocked:pr-review-loop`가 붙은 이슈는 배치가 억지로 밀어붙이지 않는다.
- 위 라벨은 각각 브랜치 리뷰 10회 소진, PR 승인 재수정 10회 소진의 안전장치로 해석하며, autopilot은 해당 이슈를 보류하고 다음 이슈로 넘어간다.
- 현재 이슈가 merge/post-merge 확인 전 상태라면, 다음 이슈를 시작하지 않고 해당 이슈 상태를 먼저 확정한다.

## 원칙

1. autopilot은 큐 관리자이지만, review → implement → merge-monitor의 3사이클을 끝까지 잇는 오케스트레이터다
2. 공식 구현 절차는 `/implement-issue`가 계속 SSOT다
3. 사전 리뷰 증적은 이슈 코멘트에 남기고 재사용하되, `ready`/`caution`은 구현 체크리스트로 반드시 소비한다
4. `needs-triage`가 붙은 이슈는 사람이 분류하기 전까지 건드리지 않는다
5. 기본 모드는 merge-confirmation 우선이며, `--handoff-only`는 예외적인 throughput 모드다
