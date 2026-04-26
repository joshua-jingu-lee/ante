# 계획 리뷰 스킬

> Plan Preflight가 작성한 GitHub 이슈 실행계획을 구현 전에 검증하고 피드백을 주는 스킬이다.
> 이 스킬의 결과는 Plan Preflight가 이슈 본문 구현계획을 보강하거나 확정하는 입력으로 사용한다.
> 계획을 새로 작성하는 스킬이 아니라, 이미 작성된 계획이 구현 가능한지 확인하고 필요한 수정 방향을 제시한다.

## 언제 사용하나

- `/implement-issue`에서 구현 에이전트에게 위임하기 직전
- Plan Preflight가 `ready`라고 판단한 이슈
- Plan Preflight가 없지만 작은 이슈라서 이슈 본문 자체가 실행계획 역할을 하는 경우
- 캐시, 연결, 생성 산출물, API 계약, 설정 변경처럼 고위험 신호가 있는 경우
- "이 계획대로 바로 구현해도 되는가"가 불명확한 경우

## 입력

- GitHub 이슈 본문
- Plan Preflight 결과 또는 이슈 코멘트의 실행계획
- 관련 `docs/specs/` 링크와 SSOT 판단
- 필요한 경우 관련 코드/소비자 경로의 짧은 확인 결과

## 검토 항목

### 1. Scope Fit

- 이슈가 하나의 계약 또는 작은 구현 단위로 닫히는가
- 비목표가 충분히 명확한가
- 영향 범위가 새 모듈로 계속 확장될 가능성이 있는가

### 2. File Map

- 수정할 파일이 충분히 구체적인가
- 반드시 읽어야 할 호출자/소비자가 빠지지 않았는가
- generated artifact, 문서, OpenAPI, DB schema 갱신 대상이 빠지지 않았는가

### 3. Task Sequence

- 작업이 3~7개의 작은 단위로 나뉘었는가
- 각 작업이 짧은 검증으로 끝나는가
- 가능한 경우 `테스트 추가 -> 최소 구현 -> 소비자 반영 -> 생성물 동기화` 순서를 따른다

### 4. Risk Flags

아래에서 해당 항목을 표시한다.

- `lifecycle`
- `contract-drift`
- `generated-artifact-sync`
- `mutable-config`
- `health-path`
- `multi-consumer`

### 5. Verification And Stop Conditions

- 실행 가능한 검증 명령이 있는가
- 실행할 수 없는 검증은 `inferred`로 분리되어 있는가
- 중단 조건이 명확한가
  - 같은 `risk class` 반복
  - 영향 범위 확장
  - failing check 정의 불가
  - 스펙과 구현 요구 충돌
  - generated artifact/consumer 범위 불명확

## 출력 형식

```markdown
## Plan Review

- verdict: approve-implement | revise-plan | narrow-scope | split-issue | invoke-human
- reviewer: orchestrator | @code-reviewer

### Feedback
- ...

### Required Changes Before Implementation
- ...

### Implementation Checklist
- ...

### Verification Checklist
- ...

### Stop Conditions
- ...
```

## Verdict 의미

- `approve-implement`: 계획대로 구현 가능
- `revise-plan`: 구현 전 Plan Preflight 또는 이슈 본문을 보강해야 함
- `narrow-scope`: 범위를 줄인 계획으로 구현 가능
- `split-issue`: 하나의 PR로 다루면 안 되며 이슈 분리 필요
- `invoke-human`: 스펙/정책/운영 판단이 필요해 사람 확인 전 구현 금지

`approve-implement` 또는 `narrow-scope`가 아니면 구현 에이전트로 넘기지 않는다.
Plan Preflight의 `ready`는 Plan Review로 넘길 준비가 되었다는 뜻이며, 구현 승인으로 해석하지 않는다.

## @code-reviewer 호출 기준

아래 신호가 있으면 오케스트레이터 단독 검토로 끝내지 말고 `@code-reviewer`가 Plan Review를 수행한다.

- 캐시, 세션, 연결, long-lived adapter, mutable config 변경
- endpoint / schema / field / CLI rename
- OpenAPI, 생성 타입, 생성 문서 drift 가능성
- 둘 이상의 모듈과 소비자 경로 동시 영향
- 운영 health / readiness / background task 연결
- 같은 `risk class` failure가 과거 리뷰에서 2회 반복
