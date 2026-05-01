릴리스를 두 단계로 운영한다. `/release prepare`는 릴리스 메타데이터와 Docker 빌드 검증을 담은 PR을 만들고, `/release publish`는 그 PR이 main에 머지된 뒤 GitHub Release, PyPI, Docker image 배포를 수행한다.

릴리스 정책은 `docs/runbooks/06-release.md`를 따른다. GitHub CLI 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따르고, workflow 조회/재실행 같은 공통 GitHub 운용은 `.agent/skills/github-ops.md`를 따른다.

## 인자

$ARGUMENTS — 릴리스 모드와 선택 인자

- `prepare`: 릴리스 PR을 만든다.
- `prepare --dry-run`: PR 생성 없이 사전 점검, 예상 버전, Docker build 가능성만 확인한다.
- `publish`: merge된 최신 release PR 기준으로 실제 배포 workflow를 실행한다.
- `publish vX.Y.Z`: 특정 버전이 main 최신 release PR과 일치하는지 확인하고 배포한다.
- `publish --dry-run`: 실제 GitHub Release, PyPI, Docker push 없이 build-only 검증을 실행한다.
- 인자가 없으면 `prepare` 기준으로 사전 점검을 수행하되, 실제 push/PR 생성 전 사용자 확인을 받는다.

## 원칙

- 릴리스는 항상 수동으로만 시작한다. `main` 머지, `/autopilot`, `/implement-issue`는 릴리스를 자동 시작하지 않는다.
- release PR은 `release/vX.Y.Z` 브랜치에서 `main`으로만 연다.
- release 브랜치는 항상 최신 `origin/main`에서 만들고, stale한 로컬 `main`이나 작업 브랜치에서 분기하지 않는다.
- 동시에 열린 release PR은 하나만 허용한다. 이미 열린 release PR이 있으면 새 브랜치를 만들지 않고 기존 PR을 보고한다.
- release PR에는 버전, changelog, 릴리스 노트 같은 릴리스 메타데이터만 포함한다. 기능 수정, 버그 수정, 스펙 변경은 별도 이슈/PR로 분리한다.
- release PR에서는 Docker image를 push하지 않는다. `docker build` 검증만 수행한다.
- 실제 PyPI 업로드와 Docker image push는 release PR이 머지된 main에서 `/release publish`가 실행한 GitHub Release `published` 이벤트 이후에만 수행한다.
- main에 직접 release commit을 push하지 않는다. 릴리스 커밋은 release PR로만 main에 들어간다.
- publish 전에 release PR merge commit 이후 main에 새 커밋이 추가되었으면 중단하고 `/release prepare`를 다시 수행한다.
- 이미 배포된 PyPI 버전이나 Docker tag는 재사용하지 않는다.

## 공통 사전 확인

아래 문서를 먼저 읽고 현재 정책과 인증 절차를 확인한다.

- `docs/runbooks/06-release.md`
- `docs/runbooks/03-git-workflow.md`
- `docs/runbooks/04-ci-cd.md`
- `.agent/skills/github-auth.md`
- `.agent/skills/github-ops.md`

쓰기 작업 전 인증:

```bash
source .github/local/github.env
gh auth status
```

공통 상태 확인:

```bash
git branch --show-current
git status --porcelain
git fetch origin main --tags
git rev-parse HEAD
git rev-parse origin/main
gh pr list --state open --base main --json number,title,headRefName,baseRefName,url
gh run list -b main -L 1 --json status,conclusion,workflowName,databaseId,headSha,createdAt
```

## `/release prepare`

### 1. 릴리스 후보 확인

마지막 태그 이후 커밋을 Conventional Commits 기준으로 분류하고 예상 bump를 계산한다.

```bash
git describe --tags --abbrev=0
git log {last-tag}..origin/main --oneline
```

- `feat` → minor
- `fix`, `perf` → patch
- `feat!`, `BREAKING CHANGE:` → major
- `docs`, `test`, `refactor`, `ci`, `chore`, `style`, `build` → 기본적으로 릴리스 없음

릴리스 대상 커밋이 없으면 release PR을 만들지 않는다.

### 2. 충돌 방지 확인

- open release PR이 있으면 새 PR을 만들지 않는다.
- `release/vX.Y.Z` 원격 브랜치가 이미 있으면 덮어쓰지 않는다.
- 로컬 워킹 트리가 깨끗하지 않으면 중단한다.
- 로컬 `main`과 `origin/main`이 다르면 `git pull --ff-only` 또는 push/pull 필요 상태를 보고하고 중단한다.

### 3. release 브랜치 생성

```bash
git switch main
git pull --ff-only origin main
git switch -c release/vX.Y.Z origin/main
```

브랜치가 이미 존재하는 경우에는 무조건 재사용하지 말고, 해당 브랜치가 같은 release PR의 최신 작업인지 확인한다.

### 4. 릴리스 메타데이터 생성

semantic-release는 로컬 release 브랜치에서만 실행하고, tag나 main push는 만들지 않는다.

```bash
semantic-release version --no-vcs-release
```

예상 변경:

- `pyproject.toml` version
- `CHANGELOG.md`
- 필요 시 릴리스 노트 초안

생성된 버전이 `vX.Y.Z`와 다르면 중단하고 브랜치를 정리한다.

### 5. 검증

release PR에는 최소 검증 결과를 포함한다.

```bash
ruff check src/ tests/
ruff format --check src/ tests/
pytest tests/unit/ -x -n auto --tb=short -q
docker build -t ante:release-vX.Y.Z .
```

CI에서도 `release/*` PR이면 Docker build 검증을 수행한다. 이 단계에서는 registry push를 하지 않는다.

### 6. release commit과 PR

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): vX.Y.Z"
git push -u origin release/vX.Y.Z
gh pr create --base main --head release/vX.Y.Z --title "chore(release): vX.Y.Z" --body "{release-pr-body}"
```

PR 본문에는 다음을 포함한다.

- 마지막 태그
- 예상 버전
- 포함 커밋 요약
- 릴리스 메타데이터 변경 파일
- Docker build 검증 결과
- publish는 merge 후 `/release publish`에서만 수행한다는 문구

release PR도 일반 PR과 동일하게 `ci`와 `merge-gate`를 통과해야 한다. PR 단계의 자동 AI 승인 워커는 운영하지 않으며, 추가 검증이 필요하면 사람/오케스트레이터가 같은 브랜치 리뷰를 수동으로 호출한다.

## `/release publish`

### 1. main 확정 상태 확인

```bash
git switch main
git fetch origin main --tags
git pull --ff-only origin main
git status --porcelain
gh pr list --state open --base main --json number,title,headRefName,url
gh pr list --state merged --base main --limit 20 --json number,title,headRefName,mergedAt,mergeCommit,url
```

publish 조건:

- open release PR이 없음
- `headRefName`이 `release/*`인 최신 merged release PR의 merge commit이 현재 `origin/main` HEAD임
- `pyproject.toml` version이 publish 대상 버전과 일치함
- `vX.Y.Z` git tag가 아직 없음
- GHCR `vX.Y.Z` image tag와 PyPI `X.Y.Z` 버전이 아직 배포되지 않았음

release PR merge 이후 main에 다른 커밋이 추가되었으면 publish하지 않는다. 새 커밋을 포함한 release PR을 다시 준비한다.

### 2. 사용자 확인

실제 릴리스라면 다음 정보를 보여주고 명시적 승인을 받는다.

- release PR 번호와 merge commit
- publish 버전
- GitHub Release 생성 여부
- PyPI 업로드 여부
- Docker image push 대상
  - `ghcr.io/{owner}/{repo}:vX.Y.Z`
  - `ghcr.io/{owner}/{repo}:X.Y.Z`
  - `ghcr.io/{owner}/{repo}:latest`

### 3. semantic-release 실행

```bash
gh workflow run semantic-release.yml -f dry_run={true|false}
```

실행 직후 최신 run을 조회하고, 완료될 때까지 모니터링한다.

```bash
gh run list -w semantic-release.yml -L 1 --json status,conclusion,databaseId,headSha,createdAt
gh run view {run-id} --json status,conclusion,url,jobs
```

semantic-release가 새 GitHub Release를 만들지 않았으면 그 이유를 보고하고 종료한다.

### 4. PyPI와 Docker publish 모니터링

GitHub Release가 생성되면 `publish.yml` 실행을 확인한다.

```bash
gh run list -w publish.yml -L 1 --json status,conclusion,databaseId,headSha,createdAt
gh run view {run-id} --json status,conclusion,url,jobs
```

`publish.yml`은 GitHub Release `published` 이벤트에서만 Python package를 PyPI에 올리고 Docker image를 GHCR에 push한다.
수동 `workflow_dispatch`는 build-only 검증으로만 사용한다.
실패하면 실패 job과 단계, 로그 확인 방법, 필요한 후속 조치를 보고한다.

`--dry-run`이면 GitHub Release가 생성되지 않으므로 필요 시 `publish.yml`을 수동 dispatch해 build-only 검증만 수행한다.

```bash
gh workflow run publish.yml
```

### 5. 결과 보고

완료 보고에는 다음을 포함한다.

- 릴리스 버전
- release PR URL
- GitHub Release URL
- PyPI URL
- GHCR image URL과 tags
- `semantic-release.yml` run URL과 결과
- `publish.yml` run URL과 결과
- 실행 중 발견한 경고 또는 후속 조치

## 중단 조건

- 현재 브랜치가 `main`이 아니거나, release prepare 중 `release/vX.Y.Z`가 아님
- 워킹 트리가 깨끗하지 않음
- 로컬 `HEAD`와 `origin/main`이 다름
- open release PR이 이미 있음
- publish 대상 release PR이 최신 main HEAD가 아님
- 최신 main 필수 CI가 실패했거나 확인 불가한데 사용자가 진행을 승인하지 않음
- 릴리스 대상 커밋이 없음
- PyPI에 같은 버전이 이미 존재함
- GHCR에 같은 Docker image tag가 이미 존재함
- GitHub 인증 또는 workflow 권한이 없음
