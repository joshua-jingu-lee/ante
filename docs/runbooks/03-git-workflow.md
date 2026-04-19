# 03. Git 워크플로우

> 커밋 컨벤션, 브랜치 규칙, PR 생성/머지 규칙을 정의한다.

---

## 1. 브랜치 네이밍 규칙

```
feat/#42-symbol-validation
fix/#57-treasury-rounding
refactor/#63-broker-interface
docs/#70-api-reference
epic/#300-datafeed
```

### 1.1 이슈와 브랜치 대응 원칙

- 기본 원칙은 **한 이슈 = 한 작업 브랜치**다.
- 에픽은 통합용 `epic/*` 브랜치를 별도로 두고, 하위 이슈는 각자 작업 브랜치를 사용한다.
- 에픽과 하위 이슈를 하나의 공용 작업 브랜치에 순차 누적하지 않는다.

### 1.2 에픽 하위 브랜치 최신화

- 에픽 하위 이슈 브랜치는 PR 생성 전 최신 `origin/epic/*`를 기준으로 해야 한다.
- sibling PR이 `epic/*`에 머지되면 다음 확인을 수행한다.
  - `git fetch origin`
  - `git rebase origin/epic/#{에픽번호}-{짧은설명}` 또는 필요 시 새 브랜치 재생성
  - `git cherry -v origin/epic/#{에픽번호}-{짧은설명} HEAD`
  - 히스토리 정리 전후 검증이 필요하면 `git range-diff <정리 전 브랜치> <정리 후 브랜치>`
- stale base, duplicate commit, base regression이 보이면 PR 생성/수정보다 히스토리 정리를 먼저 한다.

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

PR을 열기 전, 최신 브랜치 HEAD는 반드시 Codex 사전 리뷰를 통과해야 한다.

### 3.1 브랜치 리뷰 트리거

- 대상 브랜치: `feat/*`, `fix/*`, `refactor/*`, `docs/*`, `epic/*`
- 트리거: 원격 브랜치 push
- 상태 체크: `codex-branch-review`

### 3.2 브랜치 리뷰 결과 처리

- `codex-branch-review = success`
  - PR 생성 가능
- `codex-branch-review = failure`
  - Claude가 같은 브랜치에서 수정 후 재push
- 동일 SHA에 실패한 상태에서 PR을 먼저 열지 않는다
- 실패 횟수는 이슈 코멘트로 누적 관리한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 대상으로 본다.
- 실패가 5회 누적되면 이슈에 `blocked:review-loop` 라벨을 붙이고 자동 브랜치 리뷰를 중단한다.

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
- **라벨**: `core`, `web`, `cli`, `docs`, `fix` 중 해당 항목
- **base 브랜치**: 에픽 하위 이슈는 에픽 브랜치, 그 외는 `main`
- **전제 조건**: 최신 branch HEAD의 `codex-branch-review`가 success

### 4.2 PR 머지 조건

1. `ci` 성공
2. `claude-pr-approve` 성공
3. `codex-pr-approve` 성공
4. 충돌 없음
5. 미해결 대화 없음
6. auto-merge 활성화 가능 상태

### 4.3 PR 승인 실패 처리

- `claude-pr-approve` 또는 `codex-pr-approve`가 `content` FAIL이면 Claude가 같은 PR 브랜치에서 자동 재수정을 시도한다.
- 자동 재수정은 최대 3회까지 허용한다.
- `quota`, `script_error`, `auth_error`, `infra_error`는 코드 내용 실패로 보지 않으며, 자동 재수정 횟수에 포함하지 않는다.
- 자동 재수정 결과가 `NO_CHANGES`이면, 이를 성공으로 취급하지 않고 메타 리뷰 또는 수동 수정 단계로 승격한다.
- 같은 head SHA에서 재실행만 필요할 때는 `gh run rerun`을 우선한다.
- `pull_request` 이벤트 자체를 다시 발생시켜야 할 때만 PR `close → reopen`을 예외적으로 허용하고, 재트리거 이유를 PR 코멘트에 남긴다.
- 3회 소진 시 `blocked:pr-review-loop` 라벨을 붙이고 PR을 사람 확인 대상으로 넘긴다.

### 4.4 머지 방식

- 기본 머지 방식은 **squash merge**
- merge 실행 주체는 GitHub auto-merge
- head branch 삭제는 GitHub의 **Automatically delete head branches** 설정 사용

### 4.5 PR 크기 가이드

- 모듈 1개 단위로 PR 생성
- 300줄 이하 권장
- 500줄 초과 시 분할 고려
- 테스트 코드는 줄 수 제한에서 제외

## 5. 보호 규칙 권장값

- required status checks:
  - `ci`
  - `claude-pr-approve`
  - `codex-pr-approve`
- require conversation resolution
- allow auto-merge
- automatically delete head branches

브랜치 보호 규칙의 source of truth는 사람 승인 수가 아니라 **status checks**다.
