# 00. 이슈 관리

> GitHub Issues를 활용한 작업 등록, 분류, 추적 규칙을 정의한다.

---

## 1. 이슈 등록 기준

모든 코드 변경은 **GitHub Issue 등록 → 브랜치 → PR** 흐름을 따른다.

- 기능 추가
- 버그 수정
- 성능 개선
- 리팩터링 (영향 범위 큼)

**예외** (이슈 없이 직접 커밋 가능):
- 오타 수정, 포매팅 변경, 주석 추가 등 코드 동작에 영향 없는 사소한 변경
- 이 경우에도 Conventional Commits 형식은 준수 (예: `chore: fix typo in config`)

## 2. 이슈 제목 컨벤션

```
[{type}] {간결한 설명}
```

### Type

| Type | 설명 | 대응 라벨 |
|------|------|-----------|
| `feat` | 새 기능 추가 | `enhancement` |
| `fix` | 버그 수정 | `bug` |
| `refactor` | 리팩토링 | `refactor` |
| `perf` | 성능 개선 | `enhancement` |
| `docs` | 문서 작성/수정 | `docs` |
| `test` | 테스트 추가/수정 | `test` |
| `chore` | 빌드, CI, 인프라 등 | `chore` |

브랜치 prefix 매핑과 PR 규칙은 [03-git-workflow.md](03-git-workflow.md)가 SSOT다.
이 문서는 이슈 제목 타입과 라벨만 정의한다.

### 예시

```
[feat] 전략 백테스트 결과 비교 리포트
[fix] Treasury 잔고 계산 시 소수점 반올림 오류
[refactor] Broker 어댑터 인터페이스 통일
[perf] Parquet 읽기 시 컬럼 프루닝 적용
[docs] API 엔드포인트 레퍼런스 문서 작성
[chore] GitHub Actions 캐시 키 정책 정리
```

## 3. 이슈 본문 구조

### 3.1 기능 요청 (feat)

```markdown
## 배경
왜 이 기능이 필요한지, 어떤 문제를 해결하는지.

## 유저스토리
- [ ] {actor}는 {action}을 할 수 있다. 그래서 {benefit}.
- [ ] ...

## 비목표
이번 이슈에서 다루지 않을 것.

## 영향 받는 계약
API / CLI / DB schema / generated type / runtime config 중 해당 항목.

## 위험 신호
- [ ] cache / invalidate
- [ ] reconnect / reinitialize
- [ ] mutable config
- [ ] generated artifact sync
- [ ] background task / health path

## 검증 시나리오
- 시나리오 1:
- 시나리오 2:

## 기술 노트 (선택)
구현 시 참고할 제약 조건, 관련 모듈, 설계 문서 링크 등.

## 완료 조건
- [ ] 기능 구현
- [ ] 단위 테스트 통과
- [ ] 관련 문서 갱신 (해당 시)
```

### 3.2 버그 리포트 (fix)

```markdown
## 현상
무엇이 잘못되었는지 (에러 메시지, 스크린샷 등).

## 재현 절차
1. ...
2. ...
3. ...

## 기대 동작
정상적으로 어떻게 동작해야 하는지.

## 첫 failing check
처음 실패를 확인한 로그, 체크, 테스트 또는 workflow.

## 회귀를 막을 테스트 위치
추가하거나 보강해야 할 테스트 파일/카테고리.

## 영향 범위 경계
예: `web만`, `web + QA consumer`, `account + gateway + broker`

## 원인 분석 (선택)
추정 원인, 관련 코드 위치.

## 완료 조건
- [ ] 버그 수정
- [ ] 재현 시나리오 기반 테스트 추가
```

### 3.3 리팩터링 / 성능 개선

```markdown
## 배경
현재 코드의 문제점과 개선 동기.

## 보존해야 할 동작 invariant
리팩터링 후에도 절대 바뀌면 안 되는 동작.

## 변경 범위
영향받는 모듈, 파일 목록.

## 영향 소비자
이 변경을 읽거나 호출하는 소비자, 생성 산출물, 운영 경로.

## 금지할 확장
이번 이슈에서 같이 하지 않을 구조 변경.

## 접근 방법
어떻게 개선할 것인지 (구체적 전략).

## 완료 조건
- [ ] 리팩터링 완료
- [ ] 기존 테스트 전체 통과
- [ ] 성능 개선 시: 개선 수치 측정
```

### 3.4 에픽 이슈

규모가 큰 작업은 에픽 이슈로 등록하고, 하위 작업을 별도 이슈로 분할한다. 하위 이슈 간 **실행 순서 의존성**을 명시하여 Claude 오케스트레이터와 브랜치/PR 자동화가 올바른 순서로 처리할 수 있도록 한다.

```markdown
## 배경
에픽의 전체 목표와 배경.

## 하위 작업
- [ ] #{번호} 하위 작업 A
- [ ] #{번호} 하위 작업 B (선행: #A번호)
- [ ] #{번호} 하위 작업 C (선행: #A번호, #B번호)

## 의존성 그래프
A → B → C (순차)
A → D     (A 완료 후 B, D 병렬 가능)

## 완료 조건
모든 하위 작업 완료 시 close.
```

**하위 이슈 본문에도 의존성을 명시**한다:

```markdown
## 기술 노트
- 선행: #A번호 (이 이슈가 close되어야 착수 가능)
```

오케스트레이터는 하위 이슈의 선행 의존이 모두 close 상태인지 확인한 후에만 구현을 시작한다. 선행 미완 시 해당 이슈를 스킵하고 다음 이슈로 진행한다.

## 4. 라벨

| 라벨 | 용도 | 색상 권장 |
|------|------|-----------|
| `enhancement` | 새 기능·성능 개선 (§2의 `feat`·`perf`) | 하늘색 |
| `feature` | (legacy) 2026-06-13부터 신규 이슈에 쓰지 않는다. 그 이전에는 `enhancement`와 수개월간 혼용됐다. | 녹색 |
| `bug` | 버그 수정 | 빨간색 |
| `refactor` | 리팩터링 | 파란색 |
| `docs` | 문서 | 보라색 |
| `test` | 테스트 | 노란색 |
| `chore` | 빌드/CI/인프라 | 회색 |
| `question` | 논의/질문 | 주황색 |
| `epic` | 에픽 (하위 이슈 묶음) | 검정색 |
| `blocked` | 다른 작업에 의존하여 대기 | 빨간색 |
| `needs-triage` | 자동 처리 전 사람 분류 필요 | 회색 |
| `plan-preflight:started` | Plan Preflight 진행 중, 구현계획 작성/리뷰 피드백 반영 중 | 파란색 |
| `plan-preflight:done` | Plan Preflight 완료, 이슈 본문 구현계획 확정 | 파란색 |
| `blocked:review-loop` | 브랜치 리뷰 반복 실패로 자동 진행 중단 | 진한 빨간색 |
| `blocked:pr-review-loop` | (legacy) 자동 큐 제외 신호. autopilot/구현 큐가 다루지 않는 사람 개입 대기 상태로만 사용한다. 자동 PR 재수정 루프 의미는 더 이상 없다. | 진한 빨간색 |
| `good first issue` | 에이전트가 자율 처리 가능 | 연두색 |

### 4.1 `needs-triage` 라벨

- `needs-triage`는 "이 이슈를 autopilot이나 `/implement-issue`가 바로 집으면 안 된다"는 뜻이다.
- watcher, QA, 리뷰 후속 자동화처럼 에이전트가 새 이슈를 만들었지만 중복/우선순위/스펙 준비 상태를 아직 사람이 확인하지 않았을 때 사용한다.
- 이 라벨이 붙은 이슈는 autopilot 큐에서 제외한다.
- 수동 `/implement-issue`도 `needs-triage`가 남아 있으면 구현을 시작하지 않는다.
- 외부발 버그 리포트(예: `source:ante-oracle` 자동 리포트, 외부 제보)가 `이슈 검증`(`@issue-reviewer`, read-only)에서 `confirmed`가 아닌 verdict(`not-reproduced` / `invalid` / `needs-info`)를 받으면, 호출자(오케스트레이터)가 이 라벨을 부착해 자동 큐에서 제외한다. `@issue-reviewer`는 verdict만 반환하고 라벨·코멘트는 호출자가 쓴다. 신규 라벨을 만들지 않고 기존 `needs-triage`를 재사용하며, 자동 close는 하지 않고 사람 판단을 기다린다.
- 사용자 또는 오케스트레이터가 이슈를 확인한 뒤, 실제로 처리할 가치와 범위가 맞는다고 판단하면 라벨을 제거한다.

### 4.2 `plan-preflight:*` 라벨

- `plan-preflight:started`는 Plan Preflight가 시작되어 이슈 본문 구현계획 작성, Plan Review 요청, 리뷰 피드백 반영 중이라는 뜻이다.
- `plan-preflight:done`은 Plan Preflight가 끝났고, Plan Review의 `approve-implement` 또는 `narrow-scope` verdict가 반영되어 이슈 본문 구현계획이 최신 상태로 확정됐다는 뜻이다.
- Plan Preflight를 시작할 때는 `plan-preflight:started`를 붙이고 `plan-preflight:done`은 제거한다.
- 구현계획을 확정할 때는 이슈 본문을 최신 계획으로 갱신한 뒤 `plan-preflight:started`를 제거하고 `plan-preflight:done`을 붙인다.
- Plan Preflight 실행 절차의 SSOT는 `/plan-preflight`다.
- `/autopilot`과 `/implement-issue`는 `plan-preflight:done`이 있으면 기존 구현계획을 우선 재사용하되, 이슈 본문/스펙/선행 조건이 이후 바뀌었는지 확인한다.
- Plan Preflight 결과가 `needs-rewrite`, `needs-spec-first`, `blocked`이거나 구현계획이 stale하면 `plan-preflight:done`을 제거한다.
- 보류나 사람 판단으로 Plan Preflight를 중단하면 `plan-preflight:started`도 제거하고, 중단 사유를 이슈 코멘트에 남긴다.

## 5. 우선순위

GitHub 기본 라벨 또는 프로젝트 보드로 관리:

| 우선순위 | 기준 |
|---------|------|
| `P0 - Critical` | 시스템 장애, 자금 관련 버그 — 즉시 처리 |
| `P1 - High` | 핵심 기능 결함, 차단 이슈 — 당일 처리 |
| `P2 - Medium` | 일반 기능/개선 — 스프린트 내 처리 |
| `P3 - Low` | 편의 기능, 기술 부채 — 여유 시 처리 |

### 5.1 Autopilot과 우선순위

Autopilot 큐 선별, snapshot, 정렬, Plan Preflight lane, merge/post-merge 모니터링은
[.agent/commands/autopilot.md](../../.agent/commands/autopilot.md)가 SSOT다.
이 문서에서는 이슈에 우선순위와 보류 라벨을 정확히 붙이는 것까지만 다룬다.

## 6. 이슈 생명주기

이슈 관리 관점의 상태는 다음과 같이 본다.

| 상태 | 의미 | 다음 처리 |
|------|------|-----------|
| Open | 등록됨 | 분류, 스펙 경로 확인, Plan Preflight |
| Preflight started | `plan-preflight:started` 라벨 존재 | 구현계획 작성 또는 Plan Review 피드백 반영 중 |
| Preflight done | `plan-preflight:done` 라벨 존재 | 확정된 이슈 본문 구현계획을 기준으로 구현 착수 가능 |
| Needs triage | `needs-triage` 라벨 존재 | 사람/오케스트레이터가 범위와 처리 가치를 확인한 뒤 라벨 제거 |
| Blocked | `blocked` 또는 review-loop 라벨 존재 | 선행 조건, 스펙 결정, review-loop recovery가 끝날 때까지 구현 제외 |
| Closed | PR auto-close 또는 수동 close | 필요 시 post-merge reconciliation 확인 |

**외부발 버그 리포트 검증 단계**: 외부에서 들어온 버그 리포트(예: `source:ante-oracle` 자동 리포트, 외부 제보)는 Open 이후 자동 큐 편입 전에 `이슈 검증`(`@issue-reviewer`, read-only)을 거친다. 이 게이트는 주장한 루트원인이 실제 코드와 일치하는지와 재현 가능성을 확인해 `confirmed` / `not-reproduced` / `invalid` / `needs-info` 4종 verdict를 반환하며, 호출자(오케스트레이터)가 이를 `🤖 **이슈 검증**` 코멘트로 남긴다. `@issue-reviewer` 자신은 GitHub에 쓰지 않는다. verdict가 `confirmed`가 아니면 호출자가 `needs-triage`를 붙여 사람 분류를 기다리게 하고, 이슈를 자동 close하지 않는다. 내부에서 기획한 이슈에는 이 단계를 적용하지 않는다. 큐 연동 절차의 SSOT는 [.agent/commands/autopilot.md](../../.agent/commands/autopilot.md)다.

구현 실행 흐름은 [01-development-process.md](01-development-process.md),
브랜치/PR 규칙은 [03-git-workflow.md](03-git-workflow.md),
리뷰/머지 게이트는 [04-ci-cd.md](04-ci-cd.md),
autopilot 배치 상태는 [.agent/commands/autopilot.md](../../.agent/commands/autopilot.md)를 따른다.

### 이슈 close 규칙

- **PR 본문에는 `Closes #N`를 기본으로 사용한다.** `Fixes #N`, `Resolves #N`도 허용하지만, runbook과 예시는 `Closes #N`으로 통일한다.
- 이슈 close는 GitHub 기본 auto-close를 우선 사용하고, `post-merge` automation은 체크박스와 에픽 상태를 동기화한다.
- 에픽 이슈는 모든 하위 이슈가 close된 후에 close한다.
- `post-merge`가 누락되면 `post-merge.yml`을 `workflow_dispatch`로 수동 실행하되 `issue_numbers`에 이슈 번호를 넣어 복구한다(머지된 PR은 재오픈 불가라 이것이 유일 재실행 경로 — `pr_number`/폴링 dispatch는 #2437로 제거, [04-ci-cd.md §5.2](04-ci-cd.md#52-post-merge-실패-모드와-복구)).

## 7. 에이전트의 이슈 등록

에이전트(외부 검증, 리뷰 게이트 후속 수정 등)가 작업 중 새로운 이슈를 발견하면 직접 등록할 수 있다:

- 이 문서의 제목/본문 템플릿을 사용한다.
- 스펙 준비 상태나 중복 여부가 불명확하면 `needs-triage`를 함께 붙인다.
- review-loop recovery 중에는 단발 follow-up을 즉시 양산하지 않고 [01-development-process.md §5](01-development-process.md#5-실패-복구-루프)와 [04-ci-cd.md §5](04-ci-cd.md#5-ci승인-실패-시-복구)의 복구 원칙에 따라 원인 정리, 메타 리뷰, 사람 판단을 우선한다.
- watcher, 외부 검증, 리뷰 후속 자동화가 만든 이슈도 분류 전이면 `needs-triage`로 시작한다.

## 8. 이슈와 버전 관리의 연결

커밋 메시지와 PR 본문에는 관련 이슈 번호를 포함한다.
상세 커밋 컨벤션은 [03-git-workflow.md](03-git-workflow.md),
릴리스/버전 관리는 [06-release.md](06-release.md)와 `/release`가 SSOT다.
