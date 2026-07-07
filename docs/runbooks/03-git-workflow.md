# 03. Git 워크플로우

> 커밋 컨벤션, 브랜치 규칙, PR 생성/머지 규칙을 정의한다.

---

## 1. 브랜치 네이밍 규칙

```
feat/#42-symbol-validation
fix/#57-treasury-rounding
perf/#61-column-pruning
refactor/#63-broker-interface
docs/#70-api-reference
test/#81-regression-coverage
chore/#88-runner-cleanup
epic/#300-datafeed
release/v0.9.0
```

### 1.1 이슈와 브랜치 대응 원칙

- 기본 원칙은 **한 이슈 = 한 작업 브랜치**다.
- 에픽은 통합용 `epic/*` 브랜치를 별도로 두고, 하위 이슈는 각자 작업 브랜치를 사용한다.
- 에픽과 하위 이슈를 하나의 공용 작업 브랜치에 순차 누적하지 않는다.

### 1.2 이슈 타입과 브랜치 prefix 매핑

| 이슈 타입 | 대응 라벨 | 브랜치 prefix |
|-----------|-----------|---------------|
| `feat` | `feature` | `feat/` |
| `fix` | `bug` | `fix/` |
| `perf` | `feature` | `perf/` |
| `refactor` | `refactor` | `refactor/` |
| `docs` | `docs` | `docs/` |
| `test` | `test` | `test/` |
| `chore` | `chore` | `chore/` |
| `epic` | `epic` | `epic/` |
| `release` | 릴리스 PR | `release/` |

일반 구현 이슈는 `/implement-issue`, `/autopilot`, 내부 `/code-review` 브랜치 리뷰가 이 매핑을 기준으로 정렬한다.
`release/` 브랜치는 일반 구현 이슈가 아니라 `/release prepare`만 생성한다.

### 1.3 에픽 하위 브랜치 최신화

- 에픽 하위 이슈 브랜치는 PR 생성 전 최신 `origin/epic/*`를 기준으로 해야 한다.
- sibling PR이 `epic/*`에 머지되면 다음 확인을 수행한다.
  - `git fetch origin`
  - `git rebase origin/epic/#{에픽번호}-{짧은설명}` 또는 필요 시 새 브랜치 재생성
  - `git cherry -v origin/epic/#{에픽번호}-{짧은설명} HEAD`
  - 히스토리 정리 전후 검증이 필요하면 `git range-diff <정리 전 브랜치> <정리 후 브랜치>`
- stale base, duplicate commit, base regression이 보이면 PR 생성/수정보다 히스토리 정리를 먼저 한다.

### 1.4 Release 브랜치

- release 브랜치는 `/release prepare`만 생성한다.
- 브랜치 이름은 `release/vX.Y.Z`로 고정한다.
- release 브랜치는 항상 최신 `origin/main`에서 분기한다.
- open release PR은 한 번에 하나만 허용한다.
- release PR merge 후 publish 전에 main에 새 커밋이 추가되면 publish하지 않고 `/release prepare`를 다시 수행한다.
- release 브랜치에는 릴리스 메타데이터만 포함하고, 기능/버그/스펙 변경을 섞지 않는다.

## 2. 커밋 컨벤션

[Conventional Commits](https://www.conventionalcommits.org/) 기반:

```
<type>(<scope>): <subject>

<body>
<footer>
```

### Type과 버전 범프

| Type | 설명 | 버전 범프 |
|------|------|-----------|
| `feat` | 새 기능 추가 | minor |
| `fix` | 버그 수정 | patch |
| `perf` | 성능 개선 | patch |
| `refactor` | 리팩토링 | 없음 |
| `test` | 테스트 추가/수정 | 없음 |
| `docs` | 문서 변경 | 없음 |
| `style` | 포맷팅 | 없음 |
| `build` | 빌드/의존성 변경 | 없음 |
| `ci` | CI/CD 설정 변경 | 없음 |
| `chore` | 기타 잡무 | 없음 |

### Breaking Change

```
feat!: remove legacy broker adapter

BREAKING CHANGE: BrokerAdapter 인터페이스가 변경되었습니다.
```

### Scope 예시

`eventbus`, `config`, `bot`, `strategy`, `rule`, `treasury`, `broker`, `gateway`, `data`, `feed`, `backtest`, `report`, `notification`, `web`, `cli`

## 3. 브랜치 리뷰 규칙

PR을 열기 전, 최신 로컬 브랜치 HEAD는 반드시 사전 브랜치 리뷰(`/code-review`)를 통과해야 한다.

### 3.1 브랜치 리뷰 트리거

- 대상 브랜치: `feat/*`, `fix/*`, `perf/*`, `refactor/*`, `docs/*`, `test/*`, `chore/*`, `epic/*`
- 트리거: PR 생성 전 `/implement-issue` 내부 리뷰 루프
- 실행: Claude Code 네이티브 `/code-review` (base `<main 또는 epic/...>`)
- 증적: 이슈 코멘트 `브랜치 리뷰`

### 3.2 브랜치 리뷰 결과 처리

- `/code-review = PASS`
  - 브랜치 push 후 PR 생성 가능
- `/code-review = FAIL`
  - Claude가 같은 워크트리에서 수정 후 재검토
- 동일 SHA에 실패한 상태에서 PR을 먼저 열지 않는다.
- 실패 횟수는 이슈 코멘트로 누적 관리한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 대상으로 본다.
- 실패가 10회 누적되면 이슈에 `blocked:review-loop` 라벨을 붙이고 자동 브랜치 리뷰를 중단한다(반복 실패 임계값 SSOT: [04-ci-cd.md](04-ci-cd.md)).

### 3.3 Stale Base / Duplicate Commit / Merge Conflict 대응

- 증상:
  - sibling 이슈 커밋이 현재 브랜치에 섞여 들어옴
  - `epic/*` 기준으로 이미 해결된 변경이 다시 diff에 나타남
  - rebase 중 충돌이 발생하거나, 충돌 없이도 base regression이 의심됨
- 기본 절차:
  1. `git fetch origin`
  2. 현재 base가 `main`인지 `epic/*`인지 다시 확인
  3. `git rebase <최신 base>` 또는 필요 시 새 브랜치 재생성
  4. `git cherry -v <최신 base> HEAD`로 중복 커밋 여부 확인
  5. 히스토리 정리 전후 차이를 검증해야 하면 `git range-diff <정리 전 브랜치> <정리 후 브랜치>`
- 단순 충돌이면 issue 브랜치에서 rebase 후 force-push를 허용한다.
- 중복 커밋이나 잘못된 base 오염이 있으면 `git rebase --onto` 또는 브랜치 재생성으로 히스토리를 정리한 뒤 리뷰를 다시 받는다.
- 이미 열린 PR의 히스토리를 정리했다면, PR 코멘트에 rebase 목적과 새 HEAD SHA를 남긴다.

## 4. PR 규칙

### 4.1 PR 생성 시

- **제목**: 커밋 컨벤션과 동일한 형식 (70자 이내)
- **본문**: Summary + Test Plan + `Closes #{번호}`
- **release PR 예외**: release PR은 연결 이슈가 없어도 되며, 본문에 마지막 태그, 대상 버전, 포함 커밋, Docker build 검증, `/release publish` 후속 절차를 남긴다.
- **라벨**: `core`, `web`, `cli`, `docs`, `fix` 중 해당 항목
- **base 브랜치**: 에픽 하위 이슈는 에픽 브랜치, 그 외는 `main`
- **전제 조건**: 최신 branch HEAD의 `/code-review`가 PASS이고, 그 결과가 이슈 코멘트에 남아 있음
- **release PR 전제 조건**: release PR은 이슈 코멘트 기반 브랜치 리뷰 대신 `/release prepare`의 릴리스 메타데이터 검증과 Docker build 검증을 PR 본문에 남기고, 일반 PR 승인 게이트를 통과한다.

### 4.2 PR 머지 조건

1. required status checks(`ci`, `lint`, `test` — 집합은 [§5](#5-보호-규칙-권장값) 및 [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) 모두 성공
2. 충돌 없음
3. 미해결 대화 없음
4. auto-merge 활성화 가능 상태

머지 조건 판정은 `merge-gate` job이 집행한다. PR 단계의 자동 AI 승인 워커는 운영하지 않으며, 머지 가능 여부 판정에 AI status check가 끼어들지 않는다.

### 4.3 PR 후 추가 변경 처리

- PR 후 추가 코드 변경이 발생하면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다.
- `merge-gate` 이슈로 보이면 같은 head SHA 재실행이 필요할 때만 `gh run rerun`을 우선한다.
- `pull_request` 이벤트 자체를 다시 발생시켜야 할 때만 PR `close → reopen`을 예외적으로 허용하고, 재트리거 이유를 PR 코멘트에 남긴다.
- 추가 AI 감사가 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출하고, 그 결과를 PR 코멘트에 남긴다. 자동 PR 승인 워커는 더 이상 동작하지 않는다.

### 4.4 머지 방식

- 기본 머지 방식은 **squash merge**
- merge 실행 주체는 GitHub auto-merge
- head branch 삭제는 GitHub의 **Automatically delete head branches** 설정 사용
- head branch 자동 삭제가 필요하면 repository ruleset / branch protection이 모든 브랜치 삭제를 막지 않도록 확인한다
- `main` 보호는 `main` branch protection의 `allow_deletions=false`를 기준으로 두고, 전 브랜치 공통 ruleset에 `deletion`을 넣지 않는다

### 4.5 PR 크기 가이드

- 모듈 1개 단위로 PR 생성
- 300줄 이하 권장
- 500줄 초과 시 분할 고려
- 테스트 코드는 줄 수 제한에서 제외

## 5. 보호 규칙 권장값

- required status checks:
  - `ci`
  - `lint`
  - `test`
- require conversation resolution
- allow auto-merge
- automatically delete head branches

브랜치 보호 규칙의 source of truth는 사람 승인 수가 아니라 **status checks**다.

`lint`와 `test`를 `ci`와 함께 required에 등록하는 근거(defense-in-depth)와 비채택 옵션(enforcement_level everyone, auto-merge 라벨 트리거)에 대한 ADR-style Rationale은 [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값)가 SSOT다. 본 절은 cross-link이며, 권장값 집합이 변경되면 양쪽을 함께 갱신한다.
