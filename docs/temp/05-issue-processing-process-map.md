# GitHub 이슈 처리 프로세스 맵

> 임시 작업 문서. `docs/temp/`는 평소 gitignore 대상이지만, 이 문서는 현재 런북 재정렬 맥락 공유를 위해 명시 허가에 따라 커밋한다.
> 목적: 현재 런북 기준 GitHub 이슈 처리 흐름과, 새로 합의한 스펙 진입 경로를 번호로 고정해 이후 대화에서 같은 번호를 기준으로 소통한다.

## 번호 사용 규칙

- 큰 단계는 `1`, `2`, `3`처럼 부른다.
- 하위 선택지는 `1A`, `1B`처럼 부른다.
- 세부 규칙은 필요할 때 `1A-충돌`, `12-반복`, `18-회복`처럼 부른다.

## 1. 스펙 정합성 확인과 진입 경로 선택

모든 이슈는 구현 전에 스펙 정합성을 먼저 확인한다. 이 단계의 목적은
"스펙을 먼저 고쳐야 하는가"와 "이슈 안에서 스펙과 코드를 함께 고쳐도 되는가"를
구분하는 것이다.

현재 합의한 진입 경로는 두 가지다.

공통 규칙:

- 별도 `spec-stabilization mode`는 두지 않는다.
- 별도 `spec-stabilization` 라벨도 만들지 않는다.
- 모든 작업은 일반 이슈 흐름 안에서 `1A` 또는 `1B` 중 하나로 분류한다.
- 이슈 등록 전 또는 구현 착수 전 관련 `docs/specs/` 문서를 확인한다.
- 이슈 본문에는 선택한 경로를 명시한다.
  - 예: `스펙 경로: 1A Spec-First`
  - 예: `스펙 경로: 1B Issue-First Bundled`
- 경로 판단이 애매하면 `1A`를 우선한다.

### 1A. Spec-First 경로

순서:

1. 스펙 최신화
2. 이슈 발행
3. 코드 수정

적합한 경우:

- API, CLI, IPC, DB schema, config path, account lifecycle처럼 핵심 계약을 바꾸는 경우
- 둘 이상의 모듈 또는 소비자 경로가 함께 영향받는 경우
- 기존 스펙끼리 충돌하거나 SSOT가 불명확한 경우
- 구현 전에 정책 결정이 필요한 경우
- review-loop recovery, stale TC, 반복 risk class처럼 구조 문제가 드러난 경우

이슈 등록 전 산출물:

- 수정된 스펙 문서 또는 스펙 정리 커밋
- 어떤 문서가 SSOT인지에 대한 명시
- stale 문서를 제거, 축소, 링크화할 계획
- 후속 구현 이슈가 참조할 기준 커밋 또는 문서 링크

이슈 본문 필수 항목:

- 관련 스펙 링크
- 변경된 계약 요약
- 비목표
- first failing check 또는 첫 검증 지점
- 영향 소비자: API, CLI, IPC, DB, generated artifact, 테스트 등
- 선행/후행 의존성

충돌 시 규칙:

- 구현을 시작하지 않는다.
- 먼저 SSOT 문서와 decision을 정리한다.
- stale 문서는 같은 spec 정리 작업에서 제거하거나 링크화한다.
- 그 후 새 이슈에는 관련 스펙 링크, 비목표, first failing check, 영향 소비자를 명시한다.

### 1B. Issue-First Bundled 경로

순서:

1. 이슈 발행
2. 같은 작업 또는 같은 PR에서 스펙 수정과 코드 수정을 함께 수행

적합한 경우:

- 스펙 누락이 작고 변경 의도가 명확한 경우
- 코드 변경과 spec delta를 한 PR에서 함께 검토하는 편이 자연스러운 경우
- 영향 범위가 단일 모듈 또는 좁은 소비자 경로로 제한되는 경우
- 구현 전 별도 정책 결정이 필요하지 않은 경우
- 이슈 본문에 "스펙+코드 동시 반영" 범위가 명시된 경우

이슈 등록 시 필수 항목:

- 스펙과 코드를 같은 작업에서 함께 바꾸는 이유
- 수정할 스펙 파일 목록
- 예상 spec delta
- 수정할 코드 영역
- 영향 소비자
- 이 경로가 `1A`가 아니라 `1B`인 이유
- `1B` 중단 조건

PR 필수 조건:

- `docs/specs/` 변경과 코드 변경이 같은 PR에 포함되어야 한다.
- PR Summary에 spec delta와 behavior delta를 분리해 적는다.
- Test Plan에는 스펙 변경을 검증하는 테스트 또는 리뷰 확인 항목을 포함한다.

충돌 시 규칙:

- 작업 중 스펙 충돌, SSOT 불명확, 영향 범위 확장이 발견되면 `1B`를 중단한다.
- 코드 patch를 계속하지 않고 `1A`로 전환한다.
- 이미 만든 구현 브랜치는 참고 자료로 보존하되, 스펙 정리 전 merge하지 않는다.
- 이슈 또는 PR 코멘트에 전환 사유와 필요한 스펙 결정 항목을 남긴다.

### 1C. 경로 전환 기록

`1B`에서 `1A`로 전환할 때는 이슈 또는 PR 코멘트에 다음을 남긴다.

- 전환 전 경로: `1B Issue-First Bundled`
- 전환 후 경로: `1A Spec-First`
- 전환 사유: 스펙 충돌, SSOT 불명확, 영향 범위 확장, failing check 불명확 등
- 보존할 브랜치 또는 HEAD
- 필요한 스펙 결정 목록
- 구현 재개 조건

## 2. 이슈 등록과 분류

순서:

1. GitHub Issue를 등록한다.
2. 제목은 `[{type}] {간결한 설명}` 형식을 따른다.
3. 라벨은 `feature`, `bug`, `refactor`, `docs`, `test`, `chore` 등을 붙인다.
4. 본문에는 배경, 완료 조건, 영향받는 계약, 위험 신호, 검증 시나리오를 적는다.
5. 에픽이면 하위 이슈와 실행 순서 의존성을 명시한다.

보류 라벨:

- `needs-triage`: 사람이 범위와 처리 가치, 스펙 준비 상태를 확인할 때까지 자동 처리 금지
- `blocked`: 선행 작업 대기
- `blocked:review-loop`: 브랜치 리뷰 반복 실패
- `blocked:pr-review-loop`: PR 승인 재수정 반복 실패

## 3. Plan Preflight

Plan Preflight는 구현 착수 전에 GitHub 이슈 본문을 실행 가능한 구현계획으로
보강하거나 전면 재작성하는 사전점검 단계다.
작성한 구현계획은 Codex Plan Review를 요청해 피드백을 받은 뒤 확정한다.
실행 절차의 SSOT는 `.agent/commands/plan-preflight.md`다.

사용 기준:

- `superpowers:writing-plans`의 원칙을 Ante 이슈 본문에 맞게 적용한다.
- 코드는 수정하지 않는다.
- 산출물의 canonical 위치는 GitHub 이슈 본문이다.
- 계획 단계 에이전트는 GitHub 이슈 등록과 본문 보강까지만 수행한다.

필수 적용 대상:

- `1B Issue-First Bundled` 이슈
- API, CLI, IPC, DB schema, config, lifecycle 변경
- 둘 이상의 모듈 또는 소비자 경로가 함께 영향받는 이슈
- generated artifact sync 위험이 있는 이슈
- review-loop, stale spec, stale TC, 같은 risk class 반복 이력이 있는 이슈

생략 가능 대상:

- 오타 수정
- 단일 문서의 단순 표현 수정
- 영향 소비자가 없는 작은 chore

Plan Preflight가 이슈 본문에 보강해야 할 항목:

- 스펙 경로: `1A` 또는 `1B`
- 기준 스펙과 SSOT 문서 링크
- 파일 맵: 수정 파일, 읽어야 할 호출자/소비자, 생성 산출물
- 실행 계획: 작은 체크박스 단위 task
- 테스트 계획: 각 task의 failing check, 통과 check, 실행 명령
- 문서/생성 산출물 동기화 계획
- 중단 조건: 스펙 충돌, 영향 범위 확장, failing check 불명확 등
- Codex Plan Review 피드백 반영 결과
- 커밋 단위 제안

Plan Preflight 상태/판정:

- `started`: 구현계획 작성, Codex Plan Review 요청, 리뷰 피드백 반영이 진행 중. 이슈에 `plan-preflight:started` 라벨 부착
- `done`: Codex Plan Review의 `approve-implement` 또는 `narrow-scope` 피드백까지 반영해 이슈 본문 구현계획 확정. `plan-preflight:started` 제거 후 `plan-preflight:done` 라벨 부착
- `needs-rewrite`: 이슈 본문을 전면 재작성한 뒤 다시 확인
- `needs-spec-first`: `1B`로 진행할 수 없고 `1A`로 전환 필요
- `blocked`: 선행 결정 또는 선행 이슈 없이는 계획 작성 불가

`needs-spec-first` 또는 `blocked`이면 구현으로 넘기지 않는다.
`needs-rewrite`, `needs-spec-first`, `blocked` 또는 stale 계획이면 `plan-preflight:done` 라벨을 제거한다.
보류나 사람 판단으로 Plan Preflight를 중단하면 `plan-preflight:started`도 제거하고, 중단 사유를 이슈 코멘트에 남긴다.

## 4. 처리 방식 선택

두 실행 방식이 있다.

1. 수동 `/plan-preflight #{번호}` 후 `/implement-issue #{번호}`
2. `/autopilot` 큐 처리

`/autopilot`은 새 구현 절차가 아니라 큐 관리자다.
실제 구현 절차의 SSOT는 `/implement-issue`다.

## 5. Autopilot 큐 snapshot

`/autopilot`은 배치 시작 시점의 open issue 목록을 snapshot으로 고정한다.

포함 대상:

- `feature`
- `bug`
- `refactor`
- `docs`
- `test`
- `chore`

제외 대상:

- `needs-triage`
- `question`
- `blocked`
- `blocked:review-loop`
- `blocked:pr-review-loop`
- `epic`
- 이미 open PR이 연결된 이슈
- 선행 의존 이슈가 close되지 않은 이슈

정렬:

1. `P0 - Critical`
2. `P1 - High`
3. `P2 - Medium`
4. `P3 - Low`
5. 같은 우선순위에서는 오래 열린 이슈 우선

## 6. Autopilot Lane 모델

`/autopilot`은 구현 병렬화를 열지 않는다. 대신 한 배치 안에서 lane을 둘로 나눈다.

### 6A. Implementation Lane

- 한 번에 하나의 이슈만 `/implement-issue`로 넘긴다.
- 이 lane은 코드 수정, 브랜치 push, PR 생성, merge/post-merge 모니터링까지 담당한다.
- 현재 implementation issue가 merge/post-merge 또는 명시적 보류 상태로 정리되기 전에는 다음 이슈를 구현하지 않는다.

### 6B. Plan-Preflight Lane

- implementation lane이 한 이슈의 코드를 수정하거나 리뷰/CI를 기다리는 동안, `/autopilot`은 다른 후보 이슈에 대해 Plan Preflight를 수행할 수 있다.
- 이 lane은 이슈 본문 보강, 실행계획 재작성, Codex Plan Review 요청/결과 반영, 사전 판단 코멘트 작성까지만 수행한다.
- 코드 수정, 브랜치 생성, PR 생성은 금지한다.
- 현재 implementation issue와 같은 이슈 또는 같은 open PR에 대해서는 병렬 Plan Preflight를 수행하지 않는다.
- 선행 의존성이 닫히지 않은 이슈, `needs-triage`, `blocked`, `blocked:review-loop`, `blocked:pr-review-loop` 이슈는 Plan Preflight도 하지 않는다.

Plan-Preflight Lane의 산출물:

- 이슈 본문 구현계획 업데이트
- 필요 시 `🧭 Plan Preflight` 코멘트로 변경 요약 기록
- verdict: `started`, `done`, `needs-rewrite`, `needs-spec-first`, `blocked`
- label: 진행 중일 때 `plan-preflight:started`, 확정 시 `plan-preflight:done`
- 다음 구현자가 따라야 할 task/checklist

Lane 전환 규칙:

- Plan Preflight가 `done`인 이슈도 현재 implementation lane이 끝나기 전에는 구현으로 넘기지 않는다.
- 현재 implementation lane이 종료되면, `plan-preflight:done` 라벨이 있는 이슈를 다음 구현 후보로 삼을 수 있다.
- Plan Preflight 중 스펙 충돌이 드러나면 해당 이슈는 `1A` 전환 대상으로 기록하고 구현 큐에 올리지 않는다.

## 7. Codex Plan Review

Codex Plan Review는 Plan Preflight가 작성한 계획을 구현 전에 외부 Codex에 검증받는 단계다.
`/codex:adversarial-review`로 실행하며, 계획을 새로 작성하지 않고 이미 작성된 계획이 현재 스펙/코드/소비자 경로 기준으로
구현 가능한지 확인한 뒤 피드백과 verdict를 Plan Preflight에 돌려준다.

검토 항목:

- scope fit: 이슈가 하나의 계약 또는 작은 구현 단위로 닫히는가
- file map: 수정 파일, 호출자/소비자, generated artifact가 빠지지 않았는가
- task sequence: 작업이 작은 검증 단위로 나뉘었는가
- risk flags: lifecycle, contract-drift, generated-artifact-sync, mutable-config, health-path, multi-consumer
- verification: 실행 가능한 검증 명령과 inferred check가 구분되어 있는가
- stop conditions: 스펙 충돌, 영향 범위 확장, failing check 불명확 등이 명시되어 있는가

Codex Plan Review를 수행해야 하는 조건:

- API, CLI, schema, field rename 가능성
- cache, invalidate, reconnect, mutable config, health-path 신호
- 둘 이상의 모듈과 소비자 경로 동시 영향
- 에픽 하위 이슈의 선행/후속 관계 불명확
- 같은 risk class failure가 과거 리뷰에서 2회 반복

판정:

- `approve-implement`: 계획대로 구현 가능
- `revise-plan`: 구현 전 Plan Preflight 또는 이슈 본문 보강 필요
- `narrow-scope`: 범위를 줄인 계획으로 구현 가능
- `split-issue`: 이슈 분리 필요
- `invoke-human`: 스펙/정책/운영 판단 필요

`approve-implement` 또는 `narrow-scope`가 아니면 구현으로 넘기지 않는다.
`revise-plan`이면 Plan Preflight가 피드백을 반영해 이슈 본문 구현계획을 정비한 뒤 다시 Codex Plan Review를 요청한다.
`approve-implement` 또는 `narrow-scope`이면 Plan Preflight가 이슈 본문 구현계획을 최신화하고 `plan-preflight:started`를 제거한 뒤 `plan-preflight:done` 라벨을 붙인다.

## 8. `/implement-issue` 분석

오케스트레이터가 수행한다.

순서:

1. 이슈 본문을 읽는다.
2. 에픽 또는 하위 이슈 여부를 확인한다.
3. 선행 이슈가 모두 close인지 확인한다.
4. `needs-triage` 라벨이 남아 있는지 확인한다.
5. 관련 `docs/specs/` 문서를 읽는다.
6. 스펙에 정의되지 않은 동작이면 구현하지 않고 보류 사유를 남긴다.
7. 담당 개발 에이전트를 결정한다.
8. 관련 코드와 소비자 경로를 읽는다.

## 9. 착수 기록

이슈 본문 구현계획 확정은 Plan Preflight의 책임이다.
착수 기록은 `plan-preflight:done` 라벨과 최신 이슈 본문 구현계획을 확인한 뒤 남긴다.
착수 기록은 `/implement-issue` 과정에서 선택된 개발 에이전트가 첫 작업으로 작성한다.
오케스트레이터는 이슈 본문 구현계획과 Codex Plan Review 결과를 개발 에이전트 프롬프트에 넘기되, 착수 기록을 대신 작성하지 않는다.
Plan Preflight의 tasks, verification, risk flags, stop conditions는 착수 코멘트와 개발 에이전트 프롬프트의 필수 반영 항목으로 넘긴다.

이슈에 `🤖 구현 착수` 코멘트를 남긴다.

포함 항목:

- 담당 에이전트
- 변경 대상
- base 브랜치
- Codex Plan Review verdict
- risk flags
- Codex Plan Review verdict와 Plan Preflight 핵심 체크리스트

## 10. 작업 브랜치와 worktree 구현

원칙:

- 한 이슈는 한 작업 브랜치를 사용한다.
- 모든 구현 작업은 git worktree로 격리한다.
- 에픽은 통합용 `epic/*` 브랜치를 두고 하위 이슈별 작업 브랜치를 분리한다.

브랜치 prefix:

- `feat/`
- `fix/`
- `perf/`
- `refactor/`
- `docs/`
- `test/`
- `chore/`
- `epic/`

개발 에이전트는 구현, 로컬 검증, push까지 수행한다.

## 11. 로컬 검증과 push

개발 에이전트는 변경 범위에 맞는 로컬 검증을 수행한다.

대표 검증:

- lint
- format
- unit test
- integration test
- 생성 산출물 갱신 여부 확인

검증 후 로컬 커밋을 만든다.

## 12. Codex 브랜치 리뷰

PR 생성 전 최신 로컬 브랜치 HEAD는 반드시 `/codex:review --base <main 또는 epic/...>`를 통과해야 한다.
이 단계는 GitHub Actions workflow가 아니라 Claude 세션 내부의 Codex plugin 명령으로 반복한다.

결과 처리:

- `PASS`: 브랜치 push 후 PR 생성 가능
- `FAIL`: 같은 워크트리에서 수정 후 `/codex:review --base <base>` 재실행

반복 규칙:

- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호로 본다.
- 같은 risk class가 2회 반복되면 `@code-reviewer` 메타 리뷰를 호출한다.
- 실패가 10회 누적되면 `blocked:review-loop` 라벨을 붙이고 자동 브랜치 리뷰를 중단한다.

## 13. PR 생성

조건:

- 최신 HEAD의 `/codex:review --base <base>`가 `PASS`여야 한다.
- PASS 결과가 이슈 코멘트에 남아 있어야 한다.

PR 본문:

- `Closes #{이슈번호}`
- `Summary`
- `Test Plan`

PR 생성 후 이슈에 `🤖 PR 생성 완료` 코멘트를 남긴다.

## 14. PR 승인과 자동 재수정

PR 생성 후 GitHub automation이 수행한다.

필수 체크:

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`

실패 처리:

- `content` FAIL이면 Claude 자동 재수정이 같은 PR 브랜치에서 최대 10회 동작한다.
- 자동 재수정 전 finding을 사실, 추론, 영향 범위로 다시 정리한다.
- `quota`, `script_error`, `auth_error`, `infra_error`는 자동 재수정 예산에 포함하지 않는다.
- 자동 재수정 결과가 `NO_CHANGES`면 성공으로 보지 않고 메타 리뷰 또는 수동 확인으로 올린다.
- content 재수정 10회 소진 시 `blocked:pr-review-loop` 라벨을 붙인다.

## 15. Merge gate와 auto-merge

Merge gate는 새 리뷰어가 아니라 상태 집행자다.

입력:

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 충돌 여부
- 대화 해결 여부

모두 green이면 GitHub auto-merge가 머지한다.

## 16. Post-merge와 이슈 정리

머지 후 처리:

1. PR 본문의 `Closes #N`로 GitHub auto-close를 우선 사용한다.
2. `post-merge` automation이 이슈 체크박스와 에픽 상태를 동기화한다.
3. 누락 시 workflow 수동 실행으로 PR 번호 또는 이슈 번호 기준 복구한다.
4. 복구 시 자동 경로가 왜 실패했는지와 어떤 방식으로 복구했는지 코멘트로 남긴다.

`/autopilot`은 merge/post-merge 확인 전에는 다음 이슈로 넘어가지 않는다.

## 17. Review-loop 중단 지점

현재 런북에 이미 존재하는 중단 지점:

- 브랜치 리뷰 실패 10회 누적: `blocked:review-loop`
- PR 승인 content 재수정 10회 누적: `blocked:pr-review-loop`
- 같은 blocking finding 제목 2회 반복: escalation 신호
- 같은 risk class 2회 반복: `@code-reviewer` 메타 리뷰
- 자동 재수정 `NO_CHANGES`: 메타 리뷰 또는 수동 확인

아직 보강해야 하는 지점:

- `blocked:review-loop` 이후 무엇을 산출해야 하는지
- 스펙 충돌 발견 시 patch loop를 언제 중단하는지
- Evidence matrix와 Contract matrix 템플릿
- stale follow-up 이슈를 닫고 새 dependency graph로 재등록하는 절차
- 내부 `/codex:review` 반복이 길어질 때 로컬 재현과 스펙 정렬을 우선하는 기준

## 18. Review-loop recovery 초안 위치

앞으로 정식 런북으로 만들 후보:

- `docs/runbooks/09-review-loop-recovery.md`
- `docs/runbooks/01-development-process.md`의 실패 복구 루프
- `docs/runbooks/04-ci-cd.md`의 반복 실패 규칙
- `.agent/skills/receive-review.md`
- `.agent/commands/implement-issue.md`
- `.agent/commands/autopilot.md`

## 19. 현재 합의된 핵심 변경점

기존에는 1단계를 "스펙 최신화 -> 이슈 발행 -> 코드 반영" 하나로만 표현했다.

새 합의:

- `1A`: 스펙 최신화 -> 이슈 발행 -> 코드 수정
- `1B`: 이슈 발행 -> 같은 작업에서 스펙 수정과 코드 수정
- `1B` 중 충돌이 발견되면 즉시 `1A`로 승격한다.
- `3`: Plan Preflight로 이슈 본문을 실행 가능한 계획으로 보강한다.
- `7`: Codex Plan Review로 계획을 검증하고 피드백/verdict를 남긴다.
- `6B`: Autopilot은 implementation lane이 바쁜 동안 다른 이슈의 Plan Preflight를 병렬로 수행할 수 있다.

이 합의는 review-loop recovery 논의의 전제다.
