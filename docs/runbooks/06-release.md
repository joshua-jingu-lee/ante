# 06. 릴리스 프로세스

> PyPI와 Docker image 배포까지의 릴리스 정책을 정의한다.
> 실행 절차의 SSOT는 `.agent/commands/release.md`다.

---

## 1. 릴리스 정책

- **수동 실행만 허용**: main에 머지되었다고 자동 릴리스되지 않는다.
- **2단계 운영**:
  - `/release prepare`: release PR 생성
  - `/release publish`: release PR merge 후 실제 배포
- **직접 main push 금지**: 릴리스 커밋은 `release/vX.Y.Z` 브랜치의 PR로만 main에 들어간다.
- **동시 release PR 금지**: open release PR은 한 번에 하나만 허용한다.
- **배포 산출물**: GitHub Release, PyPI package, GHCR Docker image.
- **버전 규칙**: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션) Conventional Commits 기반 자동 범프.

## 2. 릴리스 흐름

```
/release prepare
  │
  ├── [사전 점검]
  │     ├── main 브랜치 / clean tree / origin/main 동기화 확인
  │     ├── open release PR 없음 확인
  │     ├── 마지막 태그 이후 릴리스 대상 커밋 확인
  │     └── 예상 버전 산정
  │
  ├── 릴리스 메타데이터 스탬핑 (main, PSR 기본 release group)
  │     ├── pyproject.toml version
  │     └── CHANGELOG.md
  │
  ├── release/vX.Y.Z 브랜치 생성 (origin/main 기준, 스탬핑 변경 이관)
  │
  ├── release PR 검증
  │     ├── lint/test
  │     ├── Docker build 검증
  │     └── PR 게이트 통과
  │
  └── release PR merge
        │
        ▼
/release publish
  │
  ├── main 최신 HEAD가 release PR merge commit인지 확인
  ├── semantic-release.yml 수동 실행
  │     └── GitHub Release 생성 (dist 파일 첨부)
  │
  ├── publish.yml 자동 트리거
  │     ├── Python package build + PyPI 업로드
  │     └── Docker image build + GHCR push
  │
  └── 결과 보고
        ├── GitHub Release
        ├── PyPI package
        └── GHCR image tags
```

## 3. release PR 규칙

| 항목 | 규칙 |
|------|------|
| 브랜치 | `release/vX.Y.Z` |
| base | `main` |
| 생성 기준 | 최신 `origin/main` (핫픽스 라인 브랜치는 예외 — 운영 태그에서 절단, [§10](#10-핫픽스-릴리스)) |
| 커밋 | `chore(release): vX.Y.Z` |
| 허용 변경 | `pyproject.toml`, `CHANGELOG.md`, 릴리스 노트 등 릴리스 메타데이터 |
| 금지 변경 | 기능 수정, 버그 수정, 스펙 변경, unrelated workflow 변경 |
| PR 게이트 | 일반 PR과 동일: required status checks(`ci`, `lint`, `test` — 집합은 [04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate` (auto-merge 활성화 + post-merge dispatch) |
| Docker | PR에서는 build 검증만 수행하고 push 금지 |

release PR이 열려 있는 동안 main에 새 커밋이 들어오면 release PR은 stale로 본다.
이 경우 rebase로 되살리지 않는다. release PR을 닫고 release 브랜치를 정리한 뒤(로컬 `git switch -f main && git branch -D release/vX.Y.Z`, 원격 `git push origin --delete release/vX.Y.Z`) `/release prepare`를 처음부터 재실행해 최신 `origin/main` 기준으로 다시 스탬핑한다. 로컬 정리는 release.md 4단계 통일 정리 규칙과 동일하다 — prepare 종료 시 release 브랜치에 체크아웃돼 있어 `git switch -f main`으로 먼저 벗어나야 `git branch -D`가 실패하지 않는다. `release/*` 브랜치에서는 `semantic-release` 재계산이 동작하지 않는다(PSR 기본 release group이 `main`/`master` 한정이라 무음 no-op).

## 4. 충돌 방지 규칙

- open release PR이 있으면 새 release PR을 만들지 않는다.
- 같은 `release/vX.Y.Z` 원격 브랜치가 있으면 덮어쓰지 않는다.
- release PR merge 후 publish 전에 main에 새 커밋이 추가되면 publish하지 않는다.
- publish 대상 버전의 git tag, PyPI version, GHCR image tag가 이미 있으면 중단한다.
- release PR은 auto-merge 대상이 될 수 있지만, publish는 별도 수동 실행이다.
- `/autopilot`과 `/implement-issue`는 release 브랜치나 release PR을 생성하지 않는다.

## 5. 버전 범프 규칙

범프는 현재 버전 구간에 따라 달라진다. `pyproject.toml`의 `major_on_zero = false` 때문에 0.x 구간에서는 `feat!`/`BREAKING CHANGE:`도 minor로만 범프된다 — 즉 1.0.0은 자동으로 산출되지 않는다. 1.0.0 선언은 §6 「메이저 선언 릴리스」의 명시적 절차로만 수행한다.

| 커밋 타입 | 0.x 구간 범프 | ≥1.0.0 구간 범프 | 예시 |
|-----------|--------------|-----------------|------|
| `feat` | minor | minor | 0.7.0 → 0.8.0 |
| `fix`, `perf` | patch | patch | 0.7.0 → 0.7.1 |
| `feat!`, `BREAKING CHANGE:` | minor (`major_on_zero = false`) | major | 0.x: 0.7.0 → 0.8.0 / ≥1.0.0: 1.2.0 → 2.0.0 |
| `refactor`, `test`, `docs`, `ci`, `chore` | 없음 | 없음 | — |

> 상세: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션)

## 6. 메이저 선언 릴리스

1.0.0 같은 메이저 선언은 커밋 이력 기반 자동 계산이 아니라 **대표의 명시적 결정**이다. `major_on_zero = false`라 0.x에서 `feat!`/`BREAKING CHANGE:`가 쌓여도 자동으로 1.0.0이 나오지 않으므로, 메이저 선언은 아래 강제 범프 경로로만 수행한다.

### 강제 범프 경로

`semantic-release version`의 `--major` 플래그로 다음 메이저를 강제한다. forced-level 플래그는 `major_on_zero`/`allow_zero_version` 설정을 우회하므로 0.x에서도 1.0.0을 산출한다.

- **채택 근거**: `--major`는 일회성 CLI 플래그라 `pyproject.toml` 설정을 변이시키지 않는다. 따라서 1.0.0 선언 이후의 마이너/패치는 별도 조치 없이 §5 자동 계산 경로로 자연 복귀한다(설정 변이 없음).
- **대안 기각**: (b) `major_on_zero`를 `true`로 플립하면 `feat!` 커밋 하나로 1.0.0이 우발적으로 자동 산출될 위험이 있다. (c) prepare 단계 수동 버전 기입은 재현성이 부족하다.

실행은 `/release prepare --declare-major`로 하며, `.agent/commands/release.md`의 prepare 라이프사이클을 그대로 재사용하되 3단계 스탬핑 명령에만 `--major`를 추가한다(`semantic-release version --major --no-commit --no-tag --no-push --no-vcs-release`, dry-run은 `semantic-release version --major --print`). 선행조건 확인·즉시 switch·단일 정리 규칙은 일반 prepare와 동일하다.

publish도 강제 범프를 전파해야 한다. `semantic-release.yml`은 태그 이력 기준으로 버전을 재계산하므로, 메이저 선언 릴리스는 `gh workflow run semantic-release.yml -f declare_major=true`로 dispatch한다(전달하지 않으면 선언된 `X.0.0` 대신 자동 계산값이 태그·배포된다). 기본값 `declare_major=false`에서는 기존 자동 계산 경로가 그대로 동작한다.

### 선언 체크리스트

1.0.0 선언 시점에 아래 대면 문서를 함께 갱신한다. 각 항목은 **선언 시점의 별도 작업**이며, 본 절차는 갱신 대상을 명문화하는 데까지다(내용 수정은 이 런북 범위 밖).

- [ ] `README.md`의 베타 배지(`status-beta-yellow`)를 안정 릴리스 상태로 갱신
- [ ] `guide/getting-started.md`의 베타 단계 WARNING 갱신 또는 제거
- [ ] `llms.txt`의 현재 범위 서술 갱신
- [ ] 공개 API 표면 선언 문서(semver 보장 범위)의 존재 확인 — 없으면 선언 전 별도 이슈로 작성(본 이슈 스코프 밖)

### 1.0.0 이후 흐름

`--major`는 설정을 바꾸지 않으므로 1.0.0 이후 `feat`→minor(1.1.0), `fix`/`perf`→patch(1.0.1)는 §5 자동 계산으로 복귀한다. 1.0.0 이상 구간에서는 `major_on_zero`와 무관하게 `feat!`/`BREAKING CHANGE:`가 자동으로 major(2.0.0)를 범프한다.

## 7. Docker image 정책

릴리스 Docker image는 GHCR에 배포한다.

| 태그 | 의미 |
|------|------|
| `ghcr.io/{owner}/{repo}:vX.Y.Z` | GitHub Release tag와 동일 |
| `ghcr.io/{owner}/{repo}:X.Y.Z` | semver 버전 |
| `ghcr.io/{owner}/{repo}:latest` | 최신 안정 릴리스 |

- release PR에서는 `docker build` 검증만 한다.
- GitHub Release가 published 된 뒤 `publish.yml`에서 build/push를 수행한다.
- `publish.yml`의 수동 `workflow_dispatch`는 build-only 검증이며, registry push를 하지 않는다.
- 같은 버전 tag를 덮어쓰지 않는다.
- Docker image build 실패는 PyPI 성공 여부와 별개로 릴리스 실패로 기록한다.

## 8. PyPI 배포 인증

| 단계 | 인증 방식 | 비고 |
|------|-----------|------|
| 현재 (private repo) | API 토큰 (`PYPI_API_TOKEN` secret) | GitHub environment: `pypi` |
| 공개 후 | Trusted Publisher (OIDC) | pending publisher 등록 완료 |

전환 시: `publish.yml`에서 `password:` 라인 제거 → OIDC 자동 적용.

## 9. 운영 배포 결합 규약

핫픽스 경로(§10)가 성립하려면 **"운영 중 버전 = git tag `vX.Y.Z`"** 등식이 항상 유지되어야 한다. 지금 운영에 올라간 버전이 태그로 특정되어야, 그 태그에서 라인 브랜치를 절단해 핫픽스할 수 있기 때문이다.

- 운영 배포는 **GHCR 고정 태그 이미지**(`ghcr.io/{owner}/{repo}:vX.Y.Z`) 또는 **PyPI 휠**(`ante==X.Y.Z`)로만 한다. 둘 다 릴리스 태그에 1:1로 대응한다.
- `docker-compose.yml`의 `build: .`는 **개발용 로컬 빌드**다. 운영에서 로컬 소스를 빌드해 올리면 "운영 버전 = 태그" 등식이 깨지므로 운영에 쓰지 않는다.
- `:latest`는 부동 태그라 운영 고정 참조로 쓰지 않는다(§7·§10의 `:latest` 주의 참조).

> compose를 GHCR 이미지 소비로 실제 전환하는 것(운영용 override 파일 등)은 별도 이슈 후보다. 본 절은 결합 규약만 성문화한다.

## 10. 핫픽스 릴리스

운영 중인 버전에 긴급 수정이 필요할 때의 경로다. **기본은 main 패치 릴리스**이고, main이 릴리스 불가 상태일 때만 **예외로 라인 브랜치(lazy-branch)** 경로를 쓴다.

### 기본 경로 — main 패치 릴리스

main이 릴리스 가능한 상태(운영 태그 이후 쌓인 커밋을 모두 릴리스해도 무방)면 핫픽스도 일반 릴리스와 같다.

1. 수정을 일반 이슈/PR로 main에 머지한다(`fix:` 커밋).
2. `/release prepare` → `/release publish`로 §5 규칙대로 커밋 구성에 따라 산출된 버전(`fix`만이면 patch, `feat`가 섞였으면 minor)으로 정규 릴리스한다.

별도 절차 없이 §1~§4를 그대로 따른다.

### 예외 경로 — 라인 브랜치(lazy-branch)

1.1 개발 커밋이 main에 쌓여 main을 지금 릴리스할 수 없는데 운영 중인 1.0.x에 버그가 났다면, 운영 태그에서 라인 브랜치를 사후 절단한다. `hotfix` 상시 브랜치를 미리 두지 않고 **필요할 때만 만들어(lazy) 쓰고 지운다**. 표준 패턴(trunkbaseddevelopment.com의 branch-for-release + GitLab upstream-first)을 따른다.

절차(예: 운영 `v1.0.3`에 핫픽스 → `v1.0.4`):

1. **upstream-first — 수정을 main에 먼저 머지한다.** 일반 이슈/PR로 수정을 main에 반영한다(`fix:`). 수정은 항상 main → 라인 방향으로만 흐른다(역방향 금지).
2. **운영 태그에서 라인 브랜치를 수동 절단한다.** `git switch -c release/1.0 v1.0.3` — 이 브랜치는 `/release prepare`가 만들지 않는다(핫픽스 한정 예외, [03-git-workflow.md §1.4](03-git-workflow.md#14-release-브랜치)). 이름은 패치 자리가 없는 `release/X.Y`라 정규 `release/vX.Y.Z` 및 prepare 가드와 겹치지 않는다.
3. **수정 커밋을 cherry-pick한다.** `git cherry-pick <main의 수정 커밋>`.
4. **`pyproject.toml`을 수동 범프한다.** 핫픽스는 semantic-release를 우회하므로(`gh release create` 직접 호출) 버전 스탬핑이 자동으로 일어나지 않는다. `pyproject.toml`의 `version`을 `1.0.4`로 직접 올려 커밋한다.
5. **기능 검증 (태그 생성 전 필수).** `release/X.Y`는 어떤 CI도 타지 않는다(`ci.yml`은 `main`/`epic`을 base로 하는 PR만 검증하며, 라인 브랜치는 PR을 열지 않는다). 따라서 라인 브랜치를 체크아웃한 상태에서 prepare 4단계와 동일한 검증 세트를 로컬로 돌린다:
   ```bash
   ruff check src/ tests/
   ruff format --check src/ tests/
   pytest tests/unit/ -x -n auto --tb=short -q
   docker build -t ante:hotfix-v1.0.4 .
   ```
   하나라도 실패하면 태그를 만들지 않고 정리 규칙(9단계)으로 중단한다.
6. **자가검증 (태그 생성 직전).** 핫픽스는 `/release publish`의 가드레일이 돌지 않으므로(gh release create 직접 호출) 그 수동 등가물을 직접 확인한다:
   - (i) `grep '^version = ' pyproject.toml` 값이 대상 버전(`1.0.4`)과 일치
   - (ii) `v1.0.4` git tag·PyPI `1.0.4`·GHCR `:v1.0.4` image가 아직 배포되지 않음
7. **annotated 태그 + GitHub Release 생성.** `git tag -a v1.0.4 -m "..."`(lightweight 아님)로 만든 뒤 push하고 `gh release create v1.0.4 --generate-notes`로 릴리스를 만든다. 핫픽스 태그가 최고 semver가 아니면(더 높은 릴리스가 이미 존재하면) `--latest=false`를 함께 지정한다(아래 `:latest` 취급 참조).
   - CHANGELOG.md는 **수동 갱신하지 않는다.** GitHub Release 노트(`--generate-notes`)로 갈음한다. 수정 커밋은 upstream-first로 이미 main에 있으므로, 다음 정규 릴리스의 semantic-release CHANGELOG 재생성에 자연 포함된다.
8. **publish.yml이 태그 ref를 빌드한다.** `gh release create`의 `release: published` 이벤트가 `publish.yml`을 트리거하고, 그 워크플로우가 릴리스 태그(`v1.0.4`) 커밋을 체크아웃해 PyPI·GHCR로 배포한다 — 정규 파이프라인을 그대로 재사용한다.
9. **종료 후 라인 브랜치를 삭제한다(태그는 보존).** 배포가 끝나면 정리 규칙과 동일하게 `git switch -f main && git branch -D release/1.0`으로 지운다(원격에 push했다면 `git push origin --delete release/1.0`). 라인 브랜치를 체크아웃한 상태에서 `git switch -f main` 없이 `git branch -D`하면 실패한다. 다시 필요하면 태그에서 lazy하게 다시 만든다. `v1.0.4` 태그와 릴리스는 남긴다.

#### 핫픽스 태그와 정규 릴리스 버전 불변식

예외 경로 진입 조건은 "main이 지금 릴리스 불가"다. 핫픽스 태그 `vX.Y.(Z+1)`은 main에서 비도달(unreachable)이므로, 다음 정규 릴리스가 이 버전을 재산정하면 태그 충돌로 publish가 막힌다. main에 쌓인 커밋 종류에 따라 두 경우로 나뉜다.

- **(a) main에 minor 이상 범프를 유발할 커밋(`feat`)이 있는 경우(일반적)**: 다음 정규 릴리스의 산정 버전은 `vX.(Y+1).0` 이상이라 핫픽스 태그와 충돌하지 않는다.
- **(b) main에 minor 이상 유발 커밋이 없는 경우(범프 미유발 커밋만, 또는 `fix`/`perf` 등 patch 유발 커밋만 쌓인 경우 포함)**: upstream-first로 넣은 `fix:` 커밋과 합쳐져 다음 정규 산정 버전이 핫픽스 태그(`vX.Y.(Z+1)`)와 **충돌할 수 있다**. 이는 규정을 정확히 따른 결과이며 사용 오류가 아니다. (a)/(b)는 "minor 이상 유발 커밋 유무"로 갈리는 상호 배타·전수 구분이다.
- **(c) 해소 절차**: 충돌은 다음 정규 `/release prepare` 2단계의 전역 태그 검사(`git tag -l 'vX.Y.Z'`)에서 감지된다(`git describe`는 도달 가능 태그만 보므로 여기서만 잡힌다). 감지되면 prepare를 중단하고 대표에게 보고한다. 해소 경로는 두 가지다.
  - **(i) 자연 해소(권장)**: main에 minor 이상 유발 커밋(`feat`)이 곧 머지될 예정이면 그것을 기다려 정규 minor 릴리스(`vX.(Y+1).0`)로 충돌을 벗어난다.
  - **(ii) 즉시 릴리스가 필요한 경우**: `semantic-release.yml`에는 forced-minor 전파 입력이 없다(현재 `declare_major`만 §6 경로로 전파된다). 따라서 자동 해소 경로가 아직 없으며, §6 declare-major와 동일 패턴의 forced-minor 입력 추가를 별도 이슈로 등록해 CI를 확장한 뒤 진행한다.

#### `:latest` 취급 (조건부)

`publish.yml`은 모든 release에 무조건 `:latest`를 push한다([publish.yml](../../.github/workflows/publish.yml)). 하지만 재지정이 필요한 경우는 **핫픽스 태그보다 높은 릴리스가 이미 존재할 때뿐이다**.

- **핫픽스 태그가 최고 semver인 경우(일반적 — 예: 1.1 미릴리스 상태에서 1.0.4가 곧 최고 태그)**: `:latest`가 핫픽스 버전으로 전진하는 것이 정상이다. 아무 재지정도 하지 않는다(7단계 `--latest=false`도 붙이지 않는다).
- **핫픽스 태그보다 높은 릴리스가 이미 있는 경우(과거 라인 핫픽스 — 예: main이 이미 1.1.x로 릴리스됨)**: `:latest`가 핫픽스 버전으로 **역행**한다. 이를 막으려면 (i) 7단계 `gh release create`에 `--latest=false`를 지정해 GitHub Latest 마커 역행을 막고, (ii) GHCR `:latest`를 최신 정규 버전으로 **수동 재지정**한다.

semver 최고 태그만 `:latest`로 push하는 CI 가드는 별도 이슈로 분리 예정이다(publish.yml checkout이 depth=1·tags 미fetch라 fetch-depth 변경+실증이 필요해 격리 리뷰가 마땅하다). 버전별 태그(`:v1.0.4`)는 §7대로 절대 덮어쓰지 않으며, 부동 태그인 `:latest`만 재지정 대상이다.

#### release PR을 열지 않는다

라인 브랜치는 main으로 **release PR을 열지 않는다**. 수정은 이미 upstream-first로 main에 있고, `release/X.Y`는 태그·빌드 소스일 뿐이다. release PR을 열면 `release/*` CI glob([04-ci-cd.md §Gate B](04-ci-cd.md#gate-b--ci))과 release PR 규칙(§3)이 오작동한다.

#### prepare 라이프사이클과의 관계

핫픽스의 `release/X.Y`는 [§2 릴리스 흐름](#2-릴리스-흐름)·`.agent/commands/release.md`의 prepare 경로 **밖**이다. main 전용 스탬핑, 2단계의 로컬 `release/vX.Y.Z` 가드, 단일 정리 규칙은 모두 정규 prepare 전용이며 핫픽스에는 적용되지 않는다. 이름을 `release/X.Y`(패치 자리 없음)로 구분해 prepare 가드와의 충돌을 원천 회피한다.

#### 상시 maintenance 브랜치를 두지 않는 이유

라인 브랜치는 필요할 때만 만들고 지운다(lazy). 상시 `hotfix`/`maintenance` 브랜치는 YAGNI로 두지 않는다. 재도입 트리거만 남긴다: **1.1 개발이 수개월 지속되며 main이 릴리스 불가 상태로 자주 머무는 것이 실측되면** 해당 minor에 한해 상시 라인 브랜치 도입을 재검토한다.

## 11. 트러블슈팅

### semantic-release가 "No release will be made"

- 마지막 태그 이후 `feat`/`fix`/`perf` 커밋이 없으면 발생한다.
- release PR이 stale이면 main 최신 커밋 기준으로 `/release prepare`를 다시 수행한다.

### release PR이 stale

- release PR 생성 후 main에 다른 PR이 merge된 상태다.
- rebase로 되살리지 않는다. release PR을 닫고 release 브랜치를 정리한다: 로컬 `git switch -f main && git branch -D release/vX.Y.Z`, 원격 `git push origin --delete release/vX.Y.Z`. (로컬 정리는 release.md 4단계 규칙과 동일 — release 브랜치 체크아웃 상태에서 `git switch -f main` 없이 `git branch -D`하면 실패한다.)
- `/release prepare`를 처음부터 재실행해 최신 main 기준으로 다시 스탬핑한다. `release/*` 브랜치에서는 `semantic-release` 재계산이 동작하지 않는다(PSR release group이 `main`/`master` 한정).

### publish.yml 실패

- PyPI 토큰 만료 시 GitHub Secrets에서 `PYPI_API_TOKEN`을 갱신한다.
- Docker login 실패 시 `GITHUB_TOKEN`의 `packages: write` 권한과 repository package 설정을 확인한다.
- Docker build 실패 시 release PR의 Docker build 검증과 실제 publish 환경 차이를 비교한다.

### 이미 릴리스된 버전

- PyPI에 이미 올라간 버전은 재업로드할 수 없다.
- 이미 존재하는 git tag나 Docker image tag는 덮어쓰지 않는다.
- 잘못 생성된 GitHub Release/tag 정리는 사람 확인 후 수동으로만 수행한다.

### 운영 버전에 긴급 수정이 필요한데 main이 릴리스 불가

- main이 릴리스 가능한 상태면 일반 패치 릴리스(`fix:` → `/release prepare`/`publish`)로 처리한다 — [§10 핫픽스 릴리스 · 기본 경로](#10-핫픽스-릴리스).
- 1.1 개발 커밋 등이 쌓여 main을 지금 릴리스할 수 없으면 라인 브랜치(lazy-branch) 예외 경로를 쓴다 — [§10 · 예외 경로](#10-핫픽스-릴리스). 핫픽스 태그보다 높은 릴리스가 이미 있는 과거 라인 핫픽스에서만 `:latest` 역행이 발생하니, 그 경우에 한해 `--latest=false`와 GHCR `:latest` 수동 재지정을 잊지 않는다.

### 핫픽스 후 GHCR `:latest`가 과거 버전을 가리킴

- `:latest` 역행은 **핫픽스 태그보다 높은 릴리스가 이미 존재할 때만** 발생한다(과거 라인 핫픽스). 핫픽스 태그가 최고 semver면 `:latest` 전진이 정상이므로 아무 조치도 하지 않는다.
- 이미 역행이 발생한 사후 복구: (i) GitHub Latest 마커 복원 — 최신 정규 릴리스 태그를 대상으로 `gh release edit vX.Y.Z --latest`(이미 생성된 릴리스라 `--latest=false`는 쓸 수 없다), (ii) GHCR `:latest`를 최신 정규 버전으로 수동 재지정.
- 사전 예방(태그 생성 시점)은 [§10 7단계](#10-핫픽스-릴리스)의 `--latest=false`를 참조.
