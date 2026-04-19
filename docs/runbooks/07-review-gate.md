# 07. 리뷰 및 머지 게이트

> Claude 구현 + 조건부 계획 리뷰 + Codex 사전 리뷰 + Claude/Codex 이중 승인 + GitHub auto-merge 구조를 정의한다.

---

## 1. 목적

이 문서는 네 가지를 분리한다.

1. **조건부 계획 리뷰**: 구현 시작 전 고위험 이슈의 계획 적합성 확인
2. **Codex 브랜치 리뷰**: PR 전 사전 품질 게이트
3. **Claude/Codex PR 승인**: PR head SHA 기준 최종 승인
4. **Merge Gate**: 승인과 CI 결과를 종합해 실제 머지 가능 여부만 판단

## 2. 조건부 계획 리뷰

### 2.1 성격

- GitHub status check가 아니다.
- 구현 전에만 거는 사전 게이트다.
- `implement-issue` 오케스트레이터가 경량 계획을 만든 뒤 필요할 때만 `@code-reviewer`를 호출한다.

### 2.2 트리거

아래 조건이 하나라도 맞으면 계획 리뷰를 강제한다.

- 캐시, 세션, 연결, long-lived adapter, mutable config 변경
- endpoint / schema / field / CLI rename
- OpenAPI, 생성 타입, 생성 문서, schema drift 가능성
- 둘 이상의 모듈과 소비자 경로 동시 영향
- 운영 health / readiness / background task와 연결된 동작 변경
- 같은 `risk class` failure가 과거 리뷰에서 2회 반복

### 2.3 결과

`@code-reviewer`는 아래 중 하나를 반환한다.

- `approve-implement`
- `narrow-scope`
- `split-issue`
- `invoke-human`

`approve-implement` 또는 `narrow-scope`가 아니면 구현을 시작하지 않는다.

### 2.4 책임

이 단계의 `@code-reviewer`는 approve / fail 상태 체크를 남기지 않는다.
대신 구현을 지금 시작해도 되는지, 범위를 줄여야 하는지, 아예 이슈를 나눠야 하는지를 판단한다.

## 3. Codex 브랜치 리뷰

### 3.1 트리거

- 브랜치 push
- 대상: `feat/*`, `fix/*`, `refactor/*`, `docs/*`, `epic/*`

### 3.2 결과

- 상태 체크: `codex-branch-review`
- 이슈 코멘트:
  - Claude Code 리뷰 요청
  - Codex 브랜치 리뷰 시작 (workflow 자동)
  - Codex 브랜치 리뷰 완료 + blocking finding / follow-up
- 커밋/체크 요약

### 3.3 처리 규칙

- `success`:
  - Claude가 PR을 생성할 수 있다
- `failure`:
  - Claude가 같은 브랜치에서 수정 후 재push
- 같은 SHA에 `failure`가 남아 있는 상태에서 PR을 먼저 열지 않는다
- 실패 횟수는 이슈 코멘트 기준으로 누적한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호를 이슈 코멘트에 남긴다.
- 같은 `risk class`가 2회 반복되면 Claude 오케스트레이터가 `@code-reviewer` 메타 리뷰를 호출한다.
- 실패가 5회 누적되면 `blocked:review-loop` 라벨을 붙이고 추가 Codex 브랜치 리뷰를 중단한다.
- sibling PR 머지 후 stale base나 duplicate commit이 의심되면, 브랜치 리뷰 재시도 전에 최신 base로 rebase하고 히스토리를 정리한다.

### 3.4 역할

이 단계의 Codex는 **blocking finding 식별자**다.
아직 merge 후보를 승인하는 단계가 아니다.

## 4. PR 승인

### 4.1 트리거

- `pull_request`
- activity types:
  - `opened`
  - `synchronize`
  - `ready_for_review`
  - 필요 시 `reopened`

### 4.2 승인 워커

| 워커 | 상태 체크 | 역할 |
|------|-----------|------|
| Claude PR 승인 워커 | `claude-pr-approve` | 구현 의도와 스펙/테스트/계약의 최종 정합성 확인 |
| Codex PR 승인 워커 | `codex-pr-approve` | 독립적인 교차검증 |

### 4.3 독립성 원칙

- 두 워커는 **같은 PR head SHA**를 본다.
- 두 워커는 가능한 한 **서로의 verdict를 입력으로 삼지 않는다**.
- merge gate는 두 워커의 결과를 소비하지만, 한 워커가 다른 워커의 판정을 따라가선 안 된다.

### 4.4 판정 기준

- 공통 체크리스트 계약: `.agent/skills/review-pr.md`
- 구현 스펙 기준: `docs/specs/`
- 아키텍처 기준: `docs/architecture/`
- 조건부 플레이북:
  - `.agent/skills/lifecycle-review.md`
  - `.agent/skills/contract-drift-review.md`
  - `.agent/skills/generated-artifact-sync.md`

### 4.5 리뷰 확장 규칙

아래 신호가 있으면 승인 워커는 diff만 읽고 끝내지 않는다.

- 캐시, 세션, 연결, long-lived adapter, mutable config 변경
- endpoint / schema / field / CLI rename
- generated type / generated doc 동기화 가능성
- 운영 health / readiness / background task와 연결된 동작 변경
- 같은 `risk class` failure 반복

이 경우 생성자, 팩토리, 캐시 저장소, 소비자, 생성 산출물까지 읽는다.

### 4.6 승인 실패 후 Claude 재수정 루프

- `claude-pr-approve` 또는 `codex-pr-approve`가 **content FAIL**을 반환하면, GitHub automation이 같은 PR 브랜치에서 Claude 재수정을 시도한다.
- 자동 재수정 전 Claude는 `.agent/skills/receive-review.md` 규칙으로 finding을 사실/추론/영향 범위로 다시 정리한다.
- 자동 재수정은 최대 **3회**까지 시도한다.
- 각 시도는 **새 커밋을 push한 경우에만** 다음 승인 사이클로 이어진다.
- 재수정 결과는 PR 코멘트에 남기고, 새 커밋이 push되면 `pull_request synchronize`로 승인 워크플로우를 다시 시작한다.
- 자동 재수정 결과가 `NO_CHANGES`면, 승인 루프를 성공으로 보지 않고 메타 리뷰 또는 수동 수정 단계로 승격한다.
- 3회 소진 후에도 승인 실패가 반복되면 `blocked:pr-review-loop` 라벨을 붙이고 자동 재수정을 중단한다.
- 같은 head SHA에서 재실행만 필요할 때는 `gh run rerun`을 우선하고, `pull_request` 이벤트가 필요할 때만 PR `close → reopen`을 예외적으로 사용한다.

### 4.7 실패 분류

PR 승인 워커 실패는 아래처럼 분리해서 처리한다.

| 분류 | 의미 | Claude 자동 재수정 |
|------|------|-------------------|
| `content` | 실제 blocking finding | 실행 |
| `quota` | AI 사용량/요금제 제한 | 실행 안 함 |
| `script_error` | 리뷰 스크립트 또는 CLI 호출 오류 | 실행 안 함 |
| `auth_error` | AI CLI 인증 만료/누락 | 실행 안 함 |
| `infra_error` | 기타 runner/환경 실패 | 실행 안 함 |

- `quota`, `script_error`, `auth_error`, `infra_error`는 **재수정 예산 3회에 포함하지 않는다**.
- 이 경우 PR 코멘트에 중단 사유를 남기고, 워커 복구 또는 수동 재실행을 기다린다.
- `content` FAIL이라도 같은 `risk class`가 2회 반복되면, 다음 자동 재수정 전에 `@code-reviewer` 메타 리뷰를 우선한다.
- review 결과가 생성되었고 마지막 verdict step만 실패했다면, 이를 워커 장애보다 **실제 content finding**으로 우선 해석한다.

## 5. Merge Gate

### 5.1 입력

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 충돌 여부
- 대화 해결 여부

### 5.2 출력

- 조건 충족 시 auto-merge 활성화 또는 유지
- 하나라도 실패면 merge 보류

### 5.3 원칙

- merge gate는 **세 번째 리뷰어가 아니다**
- 코드 품질을 새로 판단하지 않는다
- 정책과 상태만 집행한다

## 6. Post-merge 책임 분리

| 작업 | 담당 |
|------|------|
| PR 머지 | GitHub auto-merge |
| head branch 삭제 | GitHub repository setting |
| 이슈 체크박스 갱신 + close | `post-merge.yml` |
| 로컬 worktree 정리 | Claude 구현 머신 |

다른 컴퓨터의 Codex가 원격 브랜치를 머지해도, Claude가 만든 로컬 worktree는 Codex가 직접 지울 수 없다. 이 둘은 반드시 분리해서 취급한다.

### 6.1 Post-merge 수동 복구

- `post-merge`가 자동으로 실행되지 않거나, 실행되었어도 체크박스/에픽 동기화가 누락될 수 있다.
- 복구 순서:
  1. PR 번호 기준 `workflow_dispatch`
  2. 필요 시 이슈 번호 기준 reconciliation / close
  3. 복구 run 링크와 최종 상태를 PR 또는 이슈 코멘트에 기록
- merge actor가 GitHub App인 경우에도 후처리 누락 가능성을 점검한다.

## 7. 저장소 설정 권장값

- `Allow auto-merge`: 활성화
- `Automatically delete head branches`: 활성화
- AI 리뷰 runner label:
  - Claude: `claude-review`
  - Codex: `codex-review`
- 저장소 변수:
  - `AI_REVIEW_ENABLED=true`일 때만 AI 리뷰 gate를 실제로 활성화
- branch protection required status checks:
  - `ci`
  - `claude-pr-approve`
  - `codex-pr-approve`
- `Require conversation resolution before merging`: 활성화 권장

## 8. 이슈와의 연결

- PR 본문은 기본적으로 `Closes #이슈번호`를 사용한다
- 이슈 close는 GitHub 기본 auto-close를 우선 사용하고, `post-merge`는 체크박스 / 에픽 상태 동기화와 수동 복구 경로를 담당한다
- PR 승인 실패로 다시 수정이 발생해도 같은 이슈/같은 PR을 계속 사용한다
- PR 승인 실패가 `content`인 경우에만 Claude 자동 재수정이 같은 PR 브랜치에서 최대 3회 동작한다
- 승인 워커는 verdict만 남기지 않고 아래 정보를 함께 남긴다.
  - `blocking findings`
  - `follow-ups`
  - `executed checks`
  - `inferred checks`
  - `risk flags`
- `post-merge`가 누락되면 `workflow_dispatch`로 PR 번호 또는 이슈 번호를 넣어 수동 복구할 수 있다
- 수동 복구는 “조용히” 끝내지 않고, 왜 자동 경로가 실패했는지와 어떤 경로로 복구했는지를 코멘트로 남긴다
