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
| 생성 기준 | 최신 `origin/main` |
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

## 9. 트러블슈팅

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
