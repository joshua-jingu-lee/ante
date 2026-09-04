# 03. Git 워크플로우

> 커밋 컨벤션, 브랜치 규칙, PR 생성/머지 규칙을 정의한다.

> 이 문서의 브랜치 네이밍, 이슈 대응, `/code-review`, `Closes`, auto-merge 규칙은 **maintainer/collaborator 내부 lane**에만 적용한다. 외부 기여의 SSOT는 [CONTRIBUTING.md](../../CONTRIBUTING.md)다.

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

표준 표기는 이슈 번호에 `#`를 붙이지 않는 `type/이슈번호-슬러그`다(예: `feat/42-symbol-validation`). 위 예시의 `#` 포함 표기도 통용되나 신규 브랜치는 `#` 없이 만든다.

### 1.1 이슈와 브랜치 대응 원칙

- 기본 원칙은 **한 이슈 = 한 작업 브랜치**다.
- 에픽은 통합용 `epic/*` 브랜치를 별도로 두고, 하위 이슈는 각자 작업 브랜치를 사용한다.
- 에픽과 하위 이슈를 하나의 공용 작업 브랜치에 순차 누적하지 않는다.

### 1.2 이슈 타입과 브랜치 prefix 매핑

| 이슈 타입 | 대응 라벨 | 브랜치 prefix |
|-----------|-----------|---------------|
| `feat` | `enhancement` | `feat/` |
| `fix` | `bug` | `fix/` |
| `perf` | `enhancement` | `perf/` |
| `refactor` | `refactor` | `refactor/` |
| `docs` | `docs` | `docs/` |
| `test` | `test` | `test/` |
| `chore` | `chore` | `chore/` |
| `epic` | `epic` | `epic/` |
| `release` | 릴리스 PR | `release/` |

> 이 표의 `대응 라벨` 열에서 `feat`·`fix`·`refactor`·`perf`·`docs`·`test`·`chore` 행은 [00-issue-management.md](00-issue-management.md) §2의 사본이다. 이 7종 라벨을 바꿀 때는 §2를 먼저 고친다.

일반 구현 이슈는 `/implement-issue`, `/autopilot`, 내부 `/code-review` 브랜치 리뷰가 이 매핑을 기준으로 정렬한다.
`release/` 브랜치는 일반 구현 이슈가 아니라 `/release prepare`만 생성한다. 단, 핫픽스 라인 브랜치 `release/X.Y`(패치 자리 없음, 예: `release/1.0`)는 예외로 운영 태그에서 수동 절단하며 `/release prepare`를 거치지 않는다([06-release.md §10 핫픽스 릴리스](06-release.md#10-핫픽스-릴리스)).

#### 타입 라벨이 없는 이슈의 prefix 결정

위 표 `대응 라벨` 열의 `feat`~`chore` 7행에 나오는 라벨 6종(`enhancement`·`bug`·`refactor`·`docs`·`test`·`chore`)을 **하나도 갖지 않은 이슈**가 이 절의 정의역이다. 이 6종은 [.agent/commands/autopilot.md](../../.agent/commands/autopilot.md) 「큐 선별 규칙」 → 「포함 대상」이 열거하는 라벨 집합과 같은 집합이다. 표의 에픽 행과 릴리스 행은 타입 라벨 축이 아니므로 정의역 산정에서 제외한다. area 라벨만 붙은 채 큐에 편입된 이슈가 이 정의역의 대표 사례다.

판정 전에 세 가지를 먼저 처리한다.

- **`epic` 라벨이 붙었거나 [00-issue-management.md §3.4 에픽 이슈](00-issue-management.md#34-에픽-이슈)로 등록된 이슈는 이 절의 정의역이 아니다.** 라벨 축과 제목 축을 함께 본다 — 라벨이 아직 붙지 않았거나 떨어졌더라도 §3.4의 에픽 이슈로 등록된 것이면 여기서 걸러낸다. 그 이슈의 브랜치는 표의 에픽 행이 정본이고, 에픽 통합 브랜치와 하위 이슈 브랜치의 관계는 §1.1이 따로 정한다. 아래 갈래로 흘려보내지 않는다.
- **릴리스는 이슈 축이 아니다.** §1.4가 정하는 릴리스 브랜치는 이슈에서 파생되지 않고 `/release prepare`(핫픽스 라인은 운영 태그에서 수동 절단)가 만들므로, 이 절은 그 prefix를 산출하지 않는다.
- **`feature`(legacy) 라벨이 붙은 이슈는 [00-issue-management.md](00-issue-management.md) §4 `feature` 행의 승계 규칙(→ `enhancement`)을 먼저 적용한다.** 승계하면 타입 라벨을 가진 이슈가 되어 이 절의 정의역 밖으로 나가고, 위 표의 `enhancement` 행이 그대로 적용된다.

그 뒤 이슈 제목으로 판정한다.

1. 제목이 [00-issue-management.md](00-issue-management.md) §2의 `[{type}]` 규약을 따르고 그 `{type}`이 `feat`·`fix`·`refactor`·`perf`·`docs`·`test`·`chore` 7종 중 하나이면, 위 표에서 그 타입 행의 prefix를 쓴다.
2. **그 외 전부**는 `chore/`를 쓴다. 표에 없는 미지 토큰, 제목이 `[{type}]` 규약을 따르지 않는 경우를 모두 포함한다.

커밋 `<type>`은 이렇게 결정된 prefix와 같은 토큰을 쓴다(예: prefix가 `docs/`면 커밋은 `docs(...)`, 갈래 2로 결정됐으면 `chore(...)`). 갈래 1의 7종과 갈래 2의 `chore`는 모두 §2 커밋 타입 표에 실재하므로 별도 매핑이 필요 없다.

두 갈래가 산출하는 prefix는 갈래 1의 7종과 `chore/`뿐이며 전부 §3.1 브랜치 리뷰 트리거 대상 글롭(`docs/*`·`chore/*` 등) 안에 떨어진다. 따라서 이 규칙으로 만든 브랜치는 Gate A가 정상 트리거되고, 라벨이 비어 있다는 이유로 사전 리뷰가 건너뛰어지지 않는다.

**유계 한계 — 라벨만으로는 `feat/`와 `perf/`가 갈리지 않는다.** 위 표 `대응 라벨` 열에서 `enhancement`는 `feat` 행과 `perf` 행 두 곳에 걸려 있다. 그래서 `enhancement` 라벨 하나만으로는 prefix가 `feat/`인지 `perf/`인지 결정되지 않는다. 다만 이 절은 타입 라벨이 **없는** 이슈만 다루므로 그 모호성은 이 절의 정의역 밖이고, 실무에서는 제목의 `[{type}]` 토큰이 그 구분을 담당한다 — 폼 템플릿이 제목을 프리필하므로 폼 경로로 등록된 이슈는 두 타입이 제목에서 갈린다. 라벨만으로의 판정은 유계 한계로 남긴다.

### 1.3 에픽 하위 브랜치 최신화

- 에픽 하위 이슈 브랜치는 PR 생성 전 최신 `origin/epic/*`를 기준으로 해야 한다.
- sibling PR이 `epic/*`에 머지되면 다음 확인을 수행한다.
  - `git fetch origin`
  - `git rebase origin/epic/{에픽번호}-{짧은설명}` 또는 필요 시 새 브랜치 재생성
  - `git cherry -v origin/epic/{에픽번호}-{짧은설명} HEAD`
  - 히스토리 정리 전후 검증이 필요하면 `git range-diff <정리 전 브랜치> <정리 후 브랜치>`
- stale base, duplicate commit, base regression이 보이면 PR 생성/수정보다 히스토리 정리를 먼저 한다.

### 1.4 Release 브랜치

- release 브랜치는 `/release prepare`만 생성한다. **예외**: 핫픽스 라인 브랜치는 `/release prepare` 경로 밖에서 수동 생성한다([06-release.md §10 핫픽스 릴리스](06-release.md#10-핫픽스-릴리스)).
- 브랜치 이름은 `release/vX.Y.Z`로 고정한다. **예외**: 핫픽스 라인 브랜치는 패치 자리가 없는 `release/X.Y`(예: `release/1.0`)를 쓴다 — `release/vX.Y.Z` 정규 브랜치와 이름이 겹치지 않으므로 prepare 가드와 충돌하지 않는다.
- release 브랜치는 항상 최신 `origin/main`에서 분기한다. **예외**: 핫픽스 라인 브랜치는 main이 릴리스 불가 상태일 때 운영 태그(`vX.Y.Z`)에서 절단한다. 수정 자체는 upstream-first로 main에 먼저 머지하고, 라인 브랜치는 빌드 소스로만 쓴다.
- open release PR은 한 번에 하나만 허용한다.
- release PR merge 후 publish 전에 main에 새 커밋이 추가되면 publish하지 않고 `/release prepare`를 다시 수행한다.
- release 브랜치에는 릴리스 메타데이터만 포함하고, 기능/버그/스펙 변경을 섞지 않는다(핫픽스 라인 브랜치 `release/X.Y`는 예외 — cherry-pick된 수정 커밋을 포함한다, [06-release.md §10](06-release.md#10-핫픽스-릴리스)).
- 핫픽스 라인 브랜치는 main으로 release PR을 열지 않는다. 수정은 upstream-first로 main에 이미 들어가 있고, `release/X.Y`는 태그·빌드 소스일 뿐이다(→ `release/*` CI glob과 release PR 규칙 오작동 차단). 상세는 [06-release.md §10](06-release.md#10-핫픽스-릴리스).

### 1.5 장기 기능 개발 (keystone 우선)

수 주에 걸치는 장기 기능(예: 1.1 미국장 지원)은 장기 유지 브랜치 대신 **keystone 인터페이스** 방식(Martin Fowler)을 우선한다. 장기 브랜치는 main과의 격차가 벌어질수록 리베이스 비용과 base regression 위험이 커지므로, 기본은 trunk-based를 유지한 채 다음 규칙으로 병합한다.

- **하위 모듈을 작은 PR로 계속 병합한다.** 기능을 구성하는 하위 모듈(예: 브로커 어댑터·거래 캘린더·통화 처리)을 이슈 단위 작은 PR로 main에 지속 병합한다. 각 PR은 테스트를 포함하되 **기본 비활성** 상태로 들어가 운영 동작을 바꾸지 않는다.
- **진입점 배선은 마지막 PR에서만 한다.** 하위 모듈을 실제로 이어 붙여 기능을 켜는 keystone(진입점 배선)은 모든 하위 모듈이 병합·검증된 뒤 마지막 PR로 추가한다.
- **게이트는 부팅 시 설정 게이트 수준만 허용한다.** 미완성 기능을 숨기는 게이트는 부팅 시점에 읽는 설정 게이트까지만 둔다. 요청마다 분기하는 런타임 플래그 서비스는 도입하지 않는다(YAGNI — 관측·정리 비용이 이득을 넘어선다).
- **게이트는 제거 기한을 이슈로 등록한다.** 설정 게이트를 도입하면, 해당 기능이 릴리스된 뒤 게이트를 제거하는 후속 이슈를 함께 등록해 임시 게이트가 영구 잔존하지 않게 한다.
- **epic/\* 대비 keystone을 우선한다.** 통합용 `epic/*` 장기 브랜치(§1.1·§1.3)는 현재 휴면 상태이며, 브랜치 리뷰 스코프 한계가 있다(참고: [#2418](https://github.com/joshua-jingu-lee/ante/issues/2418)). 장기 기능은 keystone을 기본으로 하고, `epic/*`는 keystone으로 나누기 어려운 통합이 실제로 필요할 때만 예외적으로 쓴다.

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

## 3. 브랜치 리뷰 규칙 (내부 lane)

PR을 열기 전, 최신 로컬 브랜치 HEAD는 반드시 사전 브랜치 리뷰(`/code-review`)를 통과해야 한다.

Gate A 호출 규범(effort 하한·리뷰 범위·clean worktree·모드 플래그)의 정본은 `.agent/commands/implement-issue.md` §브랜치 리뷰 루프다.

### 3.1 브랜치 리뷰 트리거

- 대상 브랜치: `feat/*`, `fix/*`, `perf/*`, `refactor/*`, `docs/*`, `test/*`, `chore/*`, `epic/*`
- 트리거: PR 생성 전 `/implement-issue` 내부 리뷰 루프
- 실행: Claude Code 빌트인 `/code-review` 스킬. 스킬이 노출하는 인자 문법 관측은 `.agent/commands/implement-issue.md` §브랜치 리뷰 루프 10번에 있다. 같은 이름의 마켓플레이스 플러그인 커맨드와 혼동하지 않는다 — 그 플러그인은 커맨드 설명이 PR 리뷰를 전제하고 허용 도구에 `gh pr` 계열이 열거돼 있으며, Gate A는 PR이 아직 없는 시점의 리뷰다.
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

### 4.1 공통

- **본문**: 목적, 범위, 검증, 스펙 영향을 명시한다.
- 공개 required checks를 통과하고, 충돌과 미해결 대화를 해결한다. 최종 머지 여부는 maintainer가 판단한다.

### 4.2 maintainer/collaborator 내부 lane

- **제목**: 커밋 컨벤션과 동일한 형식 (70자 이내)
- **본문**: Summary + Test Plan + `Closes #{번호}`
- 기존 이슈 하나에 내부 작업 브랜치 하나를 대응한다.
- **release PR 예외**: release PR은 연결 이슈가 없어도 되며, 본문에 마지막 태그, 대상 버전, 포함 커밋, Docker build 검증, `/release publish` 후속 절차를 남긴다.
- **라벨**: `core`, `web`, `cli`, `docs`, `fix` 중 해당 항목
- **base 브랜치**: 에픽 하위 이슈는 에픽 브랜치, 그 외는 `main`
- **전제 조건**: 최신 branch HEAD의 `/code-review`가 PASS이고, 그 결과가 이슈 코멘트에 남아 있음
- **release PR 전제 조건**: release PR은 이슈 코멘트 기반 브랜치 리뷰 대신 `/release prepare`의 릴리스 메타데이터 검증과 Docker build 검증을 PR 본문에 남기고, 일반 PR 승인 게이트를 통과한다.
- same-repo PR은 `merge-gate`가 공개 required checks, 충돌, 대화 해결을 확인한 뒤 `AUTOMERGE_TOKEN`으로 auto-merge를 활성화한다.

### 4.3 외부 fork lane

- 선행 이슈, `Closes`, 내부 브랜치 네이밍, AI 증적은 필요 없다.
- 공개 CI 통과 후 maintainer가 일반 GitHub 경로로 **수동 squash merge**한다. fork PR에는 auto-merge를 사용하지 않는다.

### 4.4 내부 PR 후 추가 변경 처리

- PR 후 추가 코드 변경이 발생하면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다. 호출은 `.agent/commands/implement-issue.md` §브랜치 리뷰 루프의 정본 형태를 따른다.
- `merge-gate` 이슈로 보이면 같은 head SHA 재실행이 필요할 때만 `gh run rerun`을 우선한다.
- `pull_request` 이벤트 자체를 다시 발생시켜야 할 때만 PR `close → reopen`을 예외적으로 허용하고, 재트리거 이유를 PR 코멘트에 남긴다.
- 추가 AI 감사가 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 다시 호출하고, 그 결과를 PR 코멘트에 남긴다. 자동 PR 승인 워커는 더 이상 동작하지 않는다.

### 4.5 내부 머지 방식

- 기본 머지 방식은 **squash merge**
- merge 실행 주체는 GitHub auto-merge이며, `merge-gate`가 **`AUTOMERGE_TOKEN`(fine-grained PAT)**으로 enable한다(#2437). 머지 actor는 GitHub 봇이 아니라 PAT 소유자이므로, 머지가 `pull_request: closed` 이벤트를 정상 발화해 `post-merge.yml` 정리가 동작한다(`GITHUB_TOKEN` enable은 재귀 방지로 이 이벤트를 만들지 못해 폴백 금지 — [04-ci-cd.md §5.2](04-ci-cd.md#52-post-merge-실패-모드와-복구))
- head branch 삭제는 GitHub의 **Automatically delete head branches** 설정 사용
- head branch 자동 삭제가 필요하면 repository ruleset / branch protection이 모든 브랜치 삭제를 막지 않도록 확인한다
- `main` 보호는 `main` branch protection의 `allow_deletions=false`를 기준으로 두고, 전 브랜치 공통 ruleset에 `deletion`을 넣지 않는다

### 4.6 PR 크기 가이드

- 모듈 1개 단위로 PR 생성
- 300줄 이하 권장
- 500줄 초과 시 분할 고려
- 테스트 코드는 줄 수 제한에서 제외

## 5. 보호 규칙 권장값

required status checks와 대화 해결은 내부 same-repo PR 및 외부 fork PR 두 경로에 공통으로 적용한다. auto-merge와 head branch 자동 삭제는 maintainer/collaborator 내부 same-repo 운영에만 적용한다.

- 두 PR 경로 공통:
  - required status checks: [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값)의 운영 기준을 따른다.
  - require conversation resolution
- 내부 same-repo 운영 전용:
  - allow auto-merge
  - automatically delete head branches

브랜치 보호 규칙의 source of truth는 사람 승인 수가 아니라 **status checks**다.

required status check의 집합과 집계 안전 근거는 [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값)가 SSOT다. 본 절은 두 lane의 적용 경계만 정의한다.
