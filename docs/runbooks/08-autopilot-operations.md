# 08. Autopilot 운영

> 야간/정기 배치에서 오픈 이슈를 순차 처리할 때의 큐 선별, `needs-triage`, 사전 리뷰 증적, `/implement-issue` 인계 규칙을 정의한다.

---

## 1. 목적

`/autopilot`의 목적은 GitHub에 쌓인 오픈 이슈를 밤 시간대에 **한 번에 하나씩 review → implement → merge-monitor 사이클까지 끝내는 것**이다.

- autopilot은 새 구현 파이프라인을 만들지 않는다.
- 실제 구현 절차 SSOT는 계속 `/implement-issue`다.
- autopilot은 이슈 선별, 보류 판단, 사전 리뷰 증적, 구현 위임, merge/post-merge 모니터링 순서를 책임진다.

기본 성공 기준:

- 사전 리뷰 결과가 구현 체크리스트로 정리되었고
- 이슈가 실제 수정/PR 생성까지 진행되었고
- 같은 이슈의 CI + 승인 + auto-merge + post-merge가 확인되었음

예외 모드(`--handoff-only`)일 때만 PR 생성 후 기존 게이트 인계에서 종료한다.

## 2. 큐 모델

### 2.1 Snapshot 원칙

- 배치 시작 시점의 open issue 목록을 snapshot으로 고정한다.
- snapshot 수집은 `needs-triage`와 기본 제외 라벨을 **server-side filter로 먼저 제외한 뒤**, pagination으로 전체 후보 집합을 끝까지 모으는 방식이어야 한다.
- "앞 100건만 가져온 뒤 로컬에서 제외 라벨을 거르는 방식"은 backlog가 커질 때 실제 처리 가능 이슈를 누락시킬 수 있으므로 사용하지 않는다.
- 배치 도중 새로 생긴 이슈나 follow-up 이슈는 다음 실행으로 넘긴다.
- 같은 배치에서 같은 이슈를 두 번 재선택하지 않는다.

### 2.2 포함/제외 규칙

포함:

- `feature`
- `bug`
- `refactor`
- `docs`
- `test`
- `chore`

제외:

- `needs-triage`
- `question`
- `blocked`
- `blocked:review-loop`
- `blocked:pr-review-loop`
- `epic`
- 이미 open PR이 연결된 이슈
- 선행 의존 이슈가 close되지 않은 이슈

라벨 기반 제외는 snapshot 수집 시점에 server-side로 먼저 적용하고, open PR 존재 여부나 선행 의존성처럼 추가 조회가 필요한 조건만 후행 검사로 남긴다.

### 2.3 정렬 규칙

1. `P0 - Critical`
2. `P1 - High`
3. `P2 - Medium`
4. `P3 - Low`

같은 우선순위 안에서는 오래 열린 이슈를 먼저 처리한다.

### 2.4 배치 한도

- 기본 처리 한도는 `10`개다.
- `--limit`이 생략되면 `10`으로 간주한다.
- `--limit`에 `10`보다 큰 값이 들어오면 `10`으로 고정하고, 리포트에 clamp 사실을 남긴다.
- 현재 활성 이슈가 merge/post-merge까지 정리되지 않으면 남은 한도와 무관하게 다음 이슈로 넘어가지 않는다.

## 3. `needs-triage`

- `needs-triage`는 "이 이슈를 autopilot이 바로 집으면 안 된다"는 의미다.
- watcher나 QA 자동화가 만든 이슈, 중복/오탐 가능성이 있는 이슈, 스펙 준비 여부를 사람이 먼저 판단해야 하는 이슈에 붙인다.
- autopilot은 `needs-triage`가 남아 있는 이슈를 건너뛴다.
- 이 건너뛰기는 후보를 다 가져온 뒤 후행 필터링하는 방식이 아니라, queue snapshot 수집 단계에서 `-label:needs-triage`를 먼저 적용해 보장한다.
- 수동 `/implement-issue`도 `needs-triage`가 붙어 있으면 구현을 시작하지 않는다.
- 사람이 이슈를 검토한 뒤 실제 처리 가치와 범위를 확인하면 라벨을 제거한다.

## 4. 사전 리뷰 증적

autopilot은 필요 시 구현 전에 아키텍처 리뷰 증적을 남긴다.

### 4.1 `arch-review`

아래 신호가 있으면 먼저 검토한다.

- API / CLI / schema / field rename
- cache / invalidate / reconnect / mutable config
- 둘 이상의 모듈과 소비자 경로 동시 영향
- health / readiness / background task 변경
- 선행/후속 이슈 구조가 애매한 경우

### 4.2 증적 위치

공식 증적은 GitHub 이슈 코멘트다.

- `🏗️ **아키텍트 리뷰**`

최신 verdict는 `ready | caution | blocked` 중 하나로 남긴다.

최신 리뷰에 verdict가 없거나, `blocked`/`caution` verdict 이후 이슈 본문·스펙·선행 조건이 바뀌었다면 `/arch-review`를 다시 실행해 refresh verdict를 남길 수 있어야 한다.

### 4.3 verdict 해석

- `ready`: 구현 진행 가능
- `caution`: 구현 진행 가능하지만 주의사항과 테스트 follow-up을 반드시 반영
- `blocked`: autopilot이 구현을 시작하지 않고 사람 판단이나 선행 작업을 기다림

`ready` / `caution`은 모두 구현 사이클로 이어져야 한다. `caution`은 종료 상태가 아니라, 착수 코멘트와 개발 프롬프트의 **필수 반영 체크리스트**로 승격한다.

## 5. 운영 사이클

### 5.1 의견 검토 사이클

- `arch-review` 최신 verdict를 재사용하거나 refresh한다.
- `ready` / `caution` verdict에서 나온 주의사항, 테스트 follow-up, 금지할 확장을 구현 체크리스트로 정리한다.
- `blocked`만 같은 배치의 보류 사유가 된다.

### 5.2 개별 이슈 실행 사이클

- autopilot은 직접 코드를 구현하지 않는다.
- 사전 리뷰를 통과한 이슈만 `/implement-issue #{번호}`로 넘긴다.
- `/implement-issue`는 이슈 코멘트에 남아 있는 `arch-review` 증적을 읽고:
  - 구현 착수 코멘트에 요약을 남기고
  - 개발 에이전트 프롬프트에도 같은 요약을 포함한다
  - `caution` 항목을 Done criteria로 승격한다
- verdict가 없거나 stale한 리뷰는 구현 게이트로 쓰지 않고, 해당 리뷰 타입의 refresh 리뷰를 먼저 남긴 뒤 최신 verdict를 사용한다.
- 구현 게이트는 최신 `arch-review` verdict를 평가한다. `blocked`면 구현을 시작하지 않는다.

이렇게 해야 사전 리뷰 증적과 실제 구현이 끊기지 않는다.

### 5.3 머지 모니터링 사이클

- PR이 생성되면 autopilot은 같은 이슈에 머물며 `ci`, `claude-pr-approve`, `codex-pr-approve`, `merge-gate`, auto-merge, `post-merge`를 순서대로 추적한다.
- 승인 워커의 `content` FAIL은 다음 이슈로 넘길 이유가 아니라, 현재 이슈의 수정 루프로 본다.
- 같은 head SHA에서 `quota`, `script_error`, `auth_error`, `infra_error`로 멈추면 `gh run rerun`을 우선하고, 복구되지 않으면 `retry-later-infra`로 종료한다.
- `--handoff-only`가 아니면 merge/post-merge 확인 전에는 다음 이슈를 시작하지 않는다.

### 5.4 사이클 상태판

autopilot은 활성 이슈마다 최신 `🤖 **Autopilot 사이클 상태**` 코멘트를 유지해 3개 사이클의 상태를 분리해서 노출한다.

- 코멘트 수정이 가능하면 같은 코멘트를 갱신한다.
- 수정이 어렵다면 같은 헤더의 새 코멘트를 남기고, **가장 최신 코멘트**를 공식 상태로 본다.
- 이 코멘트는 이슈 단위 운영 상태판이며, PR check run과 역할이 다르다.

필수 필드:

- `batch`
- `issue`
- `current-cycle`
- `review-state`
- `implement-state`
- `merge-monitor-state`
- `review-verdicts`
- `pr`
- `head`
- `result`
- `next`
- `updated_at`

권장 값 집합:

- `current-cycle`: `review | implement | merge-monitor | completed`
- 각 `*-state`: `pending | running | blocked | done`
- `result`: `in-progress | merged | handed-off | deferred-* | retry-later-infra | skipped-in-progress`

권장 예시:

```markdown
🤖 **Autopilot 사이클 상태**
- batch: 20260423-0130
- issue: #1234
- current-cycle: merge-monitor
- review-state: done
- implement-state: done
- merge-monitor-state: running
- review-verdicts: arch=caution
- pr: #1250
- head: a1b2c3d
- result: in-progress
- next: `codex-pr-approve` 완료 대기
- updated_at: 2026-04-23T02:10:00Z
```

전이 규칙:

- 의견 검토 시작 시 `review-state=running`
- 구현 위임 시 `review-state=done`, `implement-state=running`
- PR 생성 시 `implement-state=done`, `merge-monitor-state=running`
- 보류 시 해당 사이클을 `blocked`로 두고 `result`를 `deferred-*`로 기록
- merge/post-merge 확인 완료 시 `merge-monitor-state=done`, `current-cycle=completed`, `result=merged`

## 6. 결과 상태

각 이슈는 배치 안에서 아래 상태 중 하나로 정리한다.

- `merged`: PR merged + post-merge 확인 완료
- `handed-off`: `--handoff-only`에서만 사용
- `deferred-triage`: `needs-triage`
- `deferred-dependency`: 선행 이슈 미완료
- `deferred-review`: `arch-review`가 `blocked`
- `deferred-scope`: 리뷰 결과를 구현으로 이어가려면 남은 배치 예산을 초과
- `deferred-merge-monitoring`: PR은 생성됐지만 merge/post-merge 확인 전 시간 예산 또는 대기 임계값 소진
- `retry-later-infra`: 인증/러너/네트워크/공통 환경 문제
- `skipped-in-progress`: 이미 open PR이 있거나 사람이 작업 중

## 7. 중단 규칙

- 공통 인프라 오류가 3회 연속 발생하면 현재 배치를 중단한다.
- 시간 예산이 소진되면 현재 이슈 정리 후 종료한다.
- `blocked:review-loop`, `blocked:pr-review-loop` 이슈는 강제로 다시 밀어붙이지 않는다.
- 위 라벨은 각각 브랜치 리뷰 10회 소진, PR 승인 재수정 10회 소진의 안전장치로 해석하고 다음 이슈로 이동한다.
- 같은 배치에서 같은 이슈를 반복 재집지 않는다.

## 8. 보고와 기록

공식 기록:

- 이슈 코멘트 (`arch-review`, 구현 착수, PR 생성, 보류 사유, `🤖 **Autopilot 사이클 상태**`)
- PR 코멘트와 status check (`codex-branch-review`, `ci`, `claude-pr-approve`, `codex-pr-approve`)

필수 요약 기록:

- 배치 큐 snapshot이 1건 이상이면 `docs/temp/autopilot-report-*.md`

`docs/temp` 리포트는 이슈/PR 단위의 공식 증적을 대체하지는 않지만, 배치 전체 흐름과 회고를 남기는 **필수 운영 요약본**이다.

### 8.1 Autopilot 리포트 의무화

- 이번 배치의 autopilot 큐 snapshot이 1건 이상이면 실행 모드와 관계없이 리포트를 반드시 남긴다.
- `--dry-run`도 예외가 아니다. 실제 구현을 시작하지 않았더라도 큐 판단과 보류 사유를 남긴다.
- 큐 snapshot이 0건인 경우에만 리포트를 생략할 수 있다.

### 8.2 리포트 최소 구조

```markdown
## Autopilot 결과 보고

- 실행 시각:
- 종료 시각:
- 소요 시간:
- 실행 모드:
- 큐 snapshot 크기:
- 실제 처리 한도:

### 이슈별 결과
| 이슈 | 제목 | review | implement | merge-monitor | 결과 | PR/비고 |
|------|------|--------|-----------|---------------|------|---------|

### 보류/스킵 상세
- ...

### 후속 조치
- ...

### 프로세스 회고

#### 있었던 사건
- ...

#### 개선 포인트
- ...
```

### 8.3 회고에 남겨야 할 사건 예시

- 특정 runner가 비정상적으로 오래 대기하거나 실패를 반복함
- Claude/Codex 또는 다른 에이전트 판단이 충돌해 review loop가 길어짐
- merge conflict, stale base, duplicate commit 때문에 히스토리 정리가 필요했음
- 인증 실패, `gh` 권한 부족, workflow 수동 재실행 등 운영 마찰이 있었음
- `needs-triage`가 늦게 정리되어 배치 throughput이 떨어졌음
- 선행 이슈나 TC 부재 때문에 구현보다 보류 판단이 많았음

### 8.4 회고의 목적

- 단순 사건 나열이 아니라, 다음 배치에서 덜 흔들리기 위한 개선 포인트를 남긴다.
- 이슈 단위의 정답/오답보다, autopilot 큐 운영과 에이전트 협업 마찰을 줄이는 데 초점을 둔다.

GitHub 조회/코멘트/PR/재실행 절차는 `.agent/skills/github-ops.md`를 공통으로 따른다.

## 9. 운영 원칙

1. autopilot은 review → implement → merge-monitor 3사이클을 잇는 큐 관리자다
2. 구현 절차는 `/implement-issue`가 SSOT다
3. `needs-triage`는 autopilot 안전핀이다
4. 사전 리뷰 증적은 GitHub 이슈 코멘트에 남기고 재사용하되, `ready`/`caution`은 구현 체크리스트로 반드시 소비한다
5. 기본 모드는 merge-confirmation 우선, `--handoff-only`는 예외적인 throughput 모드다
