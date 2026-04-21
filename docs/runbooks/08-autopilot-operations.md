# 08. Autopilot 운영

> 야간/정기 배치에서 오픈 이슈를 순차 처리할 때의 큐 선별, `needs-triage`, 사전 리뷰 증적, `/implement-issue` 인계 규칙을 정의한다.

---

## 1. 목적

`/autopilot`의 목적은 GitHub에 쌓인 오픈 이슈를 밤 시간대에 **한 번에 하나씩 최대한 많이 전진시키는 것**이다.

- autopilot은 새 구현 파이프라인을 만들지 않는다.
- 실제 구현 절차 SSOT는 계속 `/implement-issue`다.
- autopilot은 이슈 선별, 보류 판단, 사전 리뷰 증적, 인계 순서를 책임진다.

기본 성공 기준:

- 이슈가 PR 생성까지 진행되었고
- 이후 CI + 승인 + auto-merge 파이프라인으로 인계되었음

실제 merge/post-merge까지 기다리는 동작은 예외 모드(`--strict-merge`)로만 사용한다.

## 2. 큐 모델

### 2.1 Snapshot 원칙

- 배치 시작 시점의 open issue 목록을 snapshot으로 고정한다.
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

### 2.3 정렬 규칙

1. `P0 - Critical`
2. `P1 - High`
3. `P2 - Medium`
4. `P3 - Low`

같은 우선순위 안에서는 오래 열린 이슈를 먼저 처리한다.

## 3. `needs-triage`

- `needs-triage`는 "이 이슈를 autopilot이 바로 집으면 안 된다"는 의미다.
- watcher나 QA 자동화가 만든 이슈, 중복/오탐 가능성이 있는 이슈, 스펙 준비 여부를 사람이 먼저 판단해야 하는 이슈에 붙인다.
- autopilot은 `needs-triage`가 남아 있는 이슈를 건너뛴다.
- 수동 `/implement-issue`도 `needs-triage`가 붙어 있으면 구현을 시작하지 않는다.
- 사람이 이슈를 검토한 뒤 실제 처리 가치와 범위를 확인하면 라벨을 제거한다.

## 4. 사전 리뷰 증적

autopilot은 필요 시 구현 전에 두 종류의 리뷰 증적을 남긴다.

### 4.1 `arch-review`

아래 신호가 있으면 먼저 검토한다.

- API / CLI / schema / field rename
- cache / invalidate / reconnect / mutable config
- 둘 이상의 모듈과 소비자 경로 동시 영향
- health / readiness / background task 변경
- 선행/후속 이슈 구조가 애매한 경우

### 4.2 `qa-review`

아래 신호가 있으면 먼저 검토한다.

- 수용 조건이 여러 개인데 기존 TC 매핑이 불명확
- 에러/경계값 검증이 핵심
- frontend/API 변경으로 contract와 TC 동기화가 중요
- 에픽 하위 이슈나 통합 시나리오가 필요한 경우

### 4.3 증적 위치

공식 증적은 GitHub 이슈 코멘트다.

- `🏗️ **아키텍트 리뷰**`
- `🧪 **QA 리뷰**`

최신 리뷰 verdict는 `ready | caution | blocked` 중 하나로 남긴다.

### 4.4 verdict 해석

- `ready`: 구현 진행 가능
- `caution`: 구현 진행 가능하지만 주의사항과 TC follow-up을 반드시 반영
- `blocked`: autopilot이 구현을 시작하지 않고 사람 판단이나 선행 작업을 기다림

## 5. `/implement-issue` 인계

- autopilot은 직접 코드를 구현하지 않는다.
- 사전 리뷰를 통과한 이슈만 `/implement-issue #{번호}`로 넘긴다.
- `/implement-issue`는 이슈 코멘트에 남아 있는 `arch-review` / `qa-review` 증적을 읽고:
  - 구현 착수 코멘트에 요약을 남기고
  - 개발 에이전트 프롬프트에도 같은 요약을 포함한다

이렇게 해야 사전 리뷰 증적과 실제 구현이 끊기지 않는다.

## 6. 결과 상태

각 이슈는 배치 안에서 아래 상태 중 하나로 정리한다.

- `handed-off`: PR 생성 후 기존 리뷰 게이트에 인계
- `deferred-triage`: `needs-triage`
- `deferred-dependency`: 선행 이슈 미완료
- `deferred-review`: `arch-review` 또는 `qa-review`가 `blocked`
- `retry-later-infra`: 인증/러너/네트워크/공통 환경 문제
- `skipped-in-progress`: 이미 open PR이 있거나 사람이 작업 중

## 7. 중단 규칙

- 공통 인프라 오류가 3회 연속 발생하면 현재 배치를 중단한다.
- 시간 예산이 소진되면 현재 이슈 정리 후 종료한다.
- `blocked:review-loop`, `blocked:pr-review-loop` 이슈는 강제로 다시 밀어붙이지 않는다.
- 같은 배치에서 같은 이슈를 반복 재집지 않는다.

## 8. 보고와 기록

공식 기록:

- 이슈 코멘트 (`arch-review`, `qa-review`, 구현 착수, PR 생성, 보류 사유)
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

### 이슈별 결과
| 이슈 | 제목 | 결과 | PR/비고 |
|------|------|------|---------|

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

1. autopilot은 큐 관리자다
2. 구현 절차는 `/implement-issue`가 SSOT다
3. `needs-triage`는 autopilot 안전핀이다
4. 사전 리뷰 증적은 GitHub 이슈 코멘트에 남기고 재사용한다
5. 기본 모드는 throughput 우선, merge 대기 모드는 예외적으로만 사용한다
