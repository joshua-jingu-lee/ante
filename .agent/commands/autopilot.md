오픈 이슈 큐를 야간 배치로 순차 처리하며, 필요 시 사전 리뷰 증적을 남긴 뒤 `/implement-issue`에 위임한다.

## 인자

$ARGUMENTS — 옵션 (생략 가능)
- 없음: 기본 autopilot 큐 전체
- `--limit {N}`: 이번 배치에서 처리할 최대 이슈 수
- `--time-budget {예: 4h, 90m}`: 시간 예산이 소진되면 다음 이슈로 넘어가지 않고 종료
- `--label {라벨}`: 특정 라벨만 대상으로 제한
- `--strict-merge`: PR 생성 인계가 아니라 실제 merge/post-merge까지 확인
- `--dry-run`: 큐 선별과 선행 리뷰 필요 여부만 계산하고 실제 구현은 시작하지 않음

## 목적

`/autopilot`은 직접 코드를 구현하는 명령이 아니다. 이 커맨드는 오픈 이슈 큐를 정리하고, 지금 자동으로 처리해도 되는 이슈만 골라 **한 번에 하나씩** `/implement-issue`에 넘기는 야간 배치 오케스트레이터다.

GitHub 조회/코멘트/PR 관련 절차는 `.agent/skills/github-ops.md`를 따르고, 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따른다.

기본 성공 기준:

- 이슈가 `/implement-issue`를 통해 PR 생성까지 진행되고
- 이후 CI + 승인 + auto-merge 파이프라인으로 인계되었음

`--strict-merge`가 있을 때만 실제 merge/post-merge까지 기다린다.

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

여러 이슈를 동시에 구현하지 않는다. 현재 활성 이슈가 PR 생성 또는 명시적 보류 상태로 정리된 뒤에만 다음 이슈로 이동한다.

## 사전 리뷰 규칙

### `arch-review`를 먼저 거는 경우

- API / CLI / schema / field rename 가능성
- cache / invalidate / reconnect / mutable config / health-path 신호
- 둘 이상의 모듈과 소비자 경로가 함께 흔들릴 가능성
- 에픽 하위 이슈의 선행/후속 관계가 불명확

### `qa-review`를 먼저 거는 경우

- 수용 조건이 2개 이상인데 기존 TC 매핑이 불명확
- happy path 외 에러/경계값 검증이 핵심
- frontend / API 변경으로 수용 조건과 TC 동기화가 중요
- 에픽 하위 이슈 또는 통합 시나리오가 필요한 경우

### 재사용 규칙

- 이슈에 최신 `🏗️ **아키텍트 리뷰**` 코멘트가 있으면 그대로 재사용한다.
- 이슈에 최신 `🧪 **QA 리뷰**` 코멘트가 있으면 그대로 재사용한다.
- 이미 남아 있는 사전 리뷰 증적을 덮어쓰지 않는다. 새 정보가 없으면 중복 리뷰를 남기지 않는다.
- 다만 최신 리뷰에 `verdict:`가 없거나, 최신 verdict가 `blocked`/`caution`인데 이슈 본문·스펙·선행 조건이 이후 바뀌었다면 `/arch-review` 또는 `/qa-review`를 다시 호출해 refresh verdict를 남긴다.

### 판정 해석

- `ready`: 구현 진행 가능
- `caution`: 구현 진행 가능하나 주의사항 또는 TC follow-up을 반드시 반영
- `blocked`: autopilot이 구현을 시작하지 않고 다음 이슈로 이동

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
- 이번 배치 큐가 1건 이상이면 실행 모드와 관계없이 `docs/temp/autopilot-report-<YYYYMMDD-HHMM>.md` 리포트를 반드시 생성한다.
- `--dry-run`이면 이 단계 결과를 리포트에 남기고 종료한다.

### 3단계: 이슈별 사전 점검

각 이슈마다 다음을 순서대로 수행한다.

1. `needs-triage` 여부 재확인
2. 선행 의존 이슈 close 여부 확인
3. open PR 존재 여부 확인
4. `arch-review` 필요 여부 판단
5. `qa-review` 필요 여부 판단
6. 기존 리뷰 증적 재사용 또는 신규 리뷰 실행

최신 사전 리뷰에 `verdict:`가 없거나, 오래된 `blocked` verdict가 최신 이슈 상태를 반영하지 못하면 refresh 리뷰를 먼저 남긴 뒤 그 결과를 사용한다.

`needs-triage`는 이미 2단계 server-side snapshot에서 제외되어 있어야 하며, 여기서는 stale snapshot이나 수동 개입 여부를 다시 확인하는 안전 검사를 수행한다.

사전 리뷰 결과가 `blocked`면 이슈 코멘트에 다음을 남기고 스킵한다.

```markdown
🤖 **Autopilot 보류**
- 이슈: #{번호}
- 사유: {needs-triage | 선행 이슈 미완료 | arch-review blocked | qa-review blocked}
- 다음 단계: {triage 제거 | 선행 이슈 완료 대기 | 스펙 정리 | TC 설계 보강}
```

### 4단계: `/implement-issue`로 위임

사전 리뷰를 통과한 이슈만 `/implement-issue #{번호}`로 넘긴다.

- `arch-review` / `qa-review` 증적은 이슈 코멘트에 남아 있어야 한다.
- `/implement-issue`는 그 증적을 읽고 구현 착수 코멘트와 개발 에이전트 프롬프트에 요약을 포함한다.

### 5단계: 결과 분류

각 이슈는 아래 중 하나로 정리한다.

- `handed-off`: PR 생성 후 기존 게이트에 인계
- `deferred-triage`: `needs-triage`가 남아 있어 보류
- `deferred-dependency`: 선행 이슈 미완
- `deferred-review`: `arch-review` 또는 `qa-review`가 `blocked`
- `retry-later-infra`: 인증/러너/네트워크 등 공통 인프라 문제
- `skipped-in-progress`: 이미 open PR 또는 사람이 작업 중

### 6단계: 배치 종료

종료 시에는 사용자에게 다음을 요약한다.

- 실행 시각과 소요 시간
- 큐 snapshot 크기
- PR 인계 건수
- 보류 건수와 사유 분포
- 인프라 오류 여부

이번 배치 큐 snapshot이 1건 이상이었다면 `docs/temp/autopilot-report-<YYYYMMDD-HHMM>.md`를 반드시 남긴다.

리포트 최소 포함 항목:

- 실행 시각 / 종료 시각 / 소요 시간
- 실행 모드 (`default | strict-merge | dry-run`)
- 큐 snapshot 크기
- 이슈별 결과 표 (`handed-off | deferred-* | retry-later-infra | skipped-in-progress`)
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

## 원칙

1. autopilot은 큐 관리자이지 새 구현 파이프라인이 아니다
2. 공식 구현 절차는 `/implement-issue`가 계속 SSOT다
3. 사전 리뷰 증적은 이슈 코멘트에 남기고 재사용한다
4. `needs-triage`가 붙은 이슈는 사람이 분류하기 전까지 건드리지 않는다
5. 기본 모드는 throughput 우선, `--strict-merge`는 안정성 확인이 더 중요한 경우에만 사용한다
