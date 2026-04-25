# GitHub 이슈 처리 프로세스 맵

> 임시 작업 문서. `docs/temp/`는 gitignore 대상이므로 커밋하지 않는다.
> 목적: 현재 런북 기준 GitHub 이슈 처리 흐름과, 새로 합의한 스펙 진입 경로를 번호로 고정해 이후 대화에서 같은 번호를 기준으로 소통한다.

## 번호 사용 규칙

- 큰 단계는 `1`, `2`, `3`처럼 부른다.
- 하위 선택지는 `1A`, `1B`처럼 부른다.
- 세부 규칙은 필요할 때 `1A-충돌`, `9-반복`, `15-회복`처럼 부른다.

## 1. 스펙 정합성 확인과 진입 경로 선택

모든 이슈는 구현 전에 스펙 정합성을 먼저 확인한다.

현재 합의한 진입 경로는 두 가지다.

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

충돌 시 규칙:

- 작업 중 스펙 충돌, SSOT 불명확, 영향 범위 확장이 발견되면 `1B`를 중단한다.
- 코드 patch를 계속하지 않고 `1A`로 전환한다.
- 이미 만든 구현 브랜치는 참고 자료로 보존하되, 스펙 정리 전 merge하지 않는다.
- 이슈 또는 PR 코멘트에 전환 사유와 필요한 스펙 결정 항목을 남긴다.

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

## 3. 처리 방식 선택

두 실행 방식이 있다.

1. 수동 `/implement-issue #{번호}`
2. `/autopilot` 큐 처리

`/autopilot`은 새 구현 절차가 아니라 큐 관리자다.
실제 구현 절차의 SSOT는 `/implement-issue`다.

## 4. Autopilot 큐 snapshot

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

## 5. 사전 리뷰 증적 확인

아래 신호가 있으면 `/arch-review` 또는 조건부 계획 리뷰를 먼저 확인한다.

- API, CLI, schema, field rename 가능성
- cache, invalidate, reconnect, mutable config, health-path 신호
- 둘 이상의 모듈과 소비자 경로 동시 영향
- 에픽 하위 이슈의 선행/후속 관계 불명확
- 같은 risk class failure가 과거 리뷰에서 2회 반복

판정:

- `ready`: 구현 진행 가능
- `caution`: 구현 진행 가능하나 주의사항을 Done criteria로 승격
- `blocked`: 구현 시작 금지

## 6. `/implement-issue` 분석

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

## 7. 경량 계획 작성

구현 전에 아래 다섯 가지를 짧게 정리한다.

1. 파일 맵
2. 작업 분해
3. risk flags
4. verification plan
5. stop conditions

조건부 계획 리뷰가 필요한 경우에는 구현 전에 `@code-reviewer`를 호출한다.
`approve-implement` 또는 `narrow-scope`가 아니면 구현하지 않는다.

## 8. 구현 착수 기록

이슈에 `🤖 구현 착수` 코멘트를 남긴다.

포함 항목:

- 담당 에이전트
- 변경 대상
- base 브랜치
- 계획 리뷰 결과
- risk flags
- 사전 리뷰 verdict와 핵심 주의사항

## 9. 작업 브랜치와 worktree 구현

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

## 10. 로컬 검증과 push

개발 에이전트는 변경 범위에 맞는 로컬 검증을 수행한다.

대표 검증:

- lint
- format
- unit test
- integration test
- 생성 산출물 갱신 여부 확인

검증 후 원격 브랜치에 push한다.

## 11. Codex 브랜치 리뷰

PR 생성 전 최신 브랜치 HEAD는 반드시 `codex-branch-review`를 통과해야 한다.

결과 처리:

- `success`: PR 생성 가능
- `failure`: 같은 브랜치에서 수정 후 재push

반복 규칙:

- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호로 본다.
- 같은 risk class가 2회 반복되면 `@code-reviewer` 메타 리뷰를 호출한다.
- 실패가 10회 누적되면 `blocked:review-loop` 라벨을 붙이고 자동 브랜치 리뷰를 중단한다.

## 12. PR 생성

조건:

- 최신 HEAD의 `codex-branch-review`가 `success`여야 한다.

PR 본문:

- `Closes #{이슈번호}`
- `Summary`
- `Test Plan`

PR 생성 후 이슈에 `🤖 PR 생성 완료` 코멘트를 남긴다.

## 13. PR 승인과 자동 재수정

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

## 14. Merge gate와 auto-merge

Merge gate는 새 리뷰어가 아니라 상태 집행자다.

입력:

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 충돌 여부
- 대화 해결 여부

모두 green이면 GitHub auto-merge가 머지한다.

## 15. Post-merge와 이슈 정리

머지 후 처리:

1. PR 본문의 `Closes #N`로 GitHub auto-close를 우선 사용한다.
2. `post-merge` automation이 이슈 체크박스와 에픽 상태를 동기화한다.
3. 누락 시 workflow 수동 실행으로 PR 번호 또는 이슈 번호 기준 복구한다.
4. 복구 시 자동 경로가 왜 실패했는지와 어떤 방식으로 복구했는지 코멘트로 남긴다.

`/autopilot`은 merge/post-merge 확인 전에는 다음 이슈로 넘어가지 않는다.

## 16. Review-loop 중단 지점

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
- GitHub Actions 반복 대기보다 로컬 재현과 스펙 정렬을 우선하는 기준

## 17. Review-loop recovery 초안 위치

앞으로 정식 런북으로 만들 후보:

- `docs/runbooks/09-review-loop-recovery.md`
- `docs/runbooks/01-development-process.md`의 실패 복구 루프
- `docs/runbooks/07-review-gate.md`의 반복 실패 규칙
- `.agent/skills/receive-review.md`
- `.agent/commands/implement-issue.md`
- `.agent/commands/autopilot.md`

## 18. 현재 합의된 핵심 변경점

기존에는 1단계를 "스펙 최신화 -> 이슈 발행 -> 코드 반영" 하나로만 표현했다.

새 합의:

- `1A`: 스펙 최신화 -> 이슈 발행 -> 코드 수정
- `1B`: 이슈 발행 -> 같은 작업에서 스펙 수정과 코드 수정
- `1B` 중 충돌이 발견되면 즉시 `1A`로 승격한다.

이 합의는 review-loop recovery 논의의 전제다.
