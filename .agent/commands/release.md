릴리스를 두 단계로 운영한다. `/release prepare`는 릴리스 메타데이터와 Docker 빌드 검증을 담은 PR을 만들고, `/release publish`는 그 PR이 main에 머지된 뒤 GitHub Release, PyPI, Docker image 배포를 수행한다.

릴리스 정책은 `docs/runbooks/06-release.md`를 따른다. GitHub CLI 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따르고, workflow 조회/재실행 같은 공통 GitHub 운용은 `.agent/skills/github-ops.md`를 따른다.

## 인자

$ARGUMENTS — 릴리스 모드와 선택 인자

- `prepare`: 릴리스 PR을 만든다.
- `prepare --dry-run`: 스탬핑·브랜치 생성·커밋 없이 예상 버전 계산만 수행한다(`semantic-release version --print`). Docker build 검증은 포함하지 않는다 — build 검증은 실 prepare 4단계(또는 `publish.yml` 수동 dispatch)에서 수행된다.
- `publish`: merge된 최신 release PR 기준으로 실제 배포 workflow를 실행한다.
- `publish vX.Y.Z`: 특정 버전이 main 최신 release PR과 일치하는지 확인하고 배포한다.
- `publish --dry-run`: 커밋·태그·push 없이 예상 버전 계산만 수행한다. Python build도 스킵되므로 build 검증은 `publish.yml` 수동 dispatch 경로에서 별도로 수행한다.
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

아래 선행조건은 모두 스탬핑(3단계) 이전에 통과해야 한다.

- open release PR이 있으면 새 PR을 만들지 않는다.
- `release/vX.Y.Z` 원격 브랜치가 이미 있으면 덮어쓰지 않는다.
- 로컬 `release/vX.Y.Z` 브랜치가 이미 있으면 중단한다.
- 로컬 워킹 트리가 깨끗하지 않으면 중단한다.
- 로컬 `main`과 `origin/main`이 다르면 `git pull --ff-only` 또는 push/pull 필요 상태를 보고하고 중단한다.

```bash
if git show-ref --verify --quiet refs/heads/release/vX.Y.Z; then
  echo "로컬 release/vX.Y.Z 브랜치가 이미 존재한다 — 이전 prepare 잔재 확인(회수 또는 git branch -D) 후 재시도" >&2
  exit 1
fi
```

브랜치가 없는 정상 경로에서는 `exit 0`으로 통과한다.

### 3. 릴리스 메타데이터 스탬핑과 release 브랜치 생성

`prepare --dry-run`은 스탬핑하지 않고 예상 버전만 계산한다. 2단계까지 통과한 최신 `main`에서 실행한다.

```bash
semantic-release version --print       # 예상 버전 (예: 0.12.0)
semantic-release version --print-tag   # 예상 태그 (예: v0.12.0)
```

`--print`/`--print-tag`는 파일 기록·브랜치 생성·커밋이 없어 부작용이 없다. 따라서 정리 규칙이 원천 불필요하며, dry-run은 이후 4·5단계를 수행하지 않는다.

실제 prepare에서는 최신 `main`에서 스탬핑한 직후 곧바로 release 브랜치로 옮긴다. PSR 기본 release group은 `main`/`master`만 매칭하므로 `release/*` 브랜치에서 스탬핑하면 no-op이 된다(스탬핑이 일어나지 않는다). 스탬핑 직후 커밋 없이 `git switch -c`로 브랜치를 만들면 워킹 트리 변경이 새 브랜치로 따라온다(start-point `origin/main`이 현재 HEAD와 동일).

```bash
git switch main
git pull --ff-only origin main
semantic-release version --no-commit --no-tag --no-push --no-vcs-release
git switch -c release/vX.Y.Z origin/main
```

`--no-commit --no-tag --no-push`로 파일 변경(`pyproject.toml`/`CHANGELOG.md`)은 워킹 트리에 남고 — PSR이 스테이징까지 수행 — 커밋·태그·push는 발생하지 않는다. `--no-vcs-release`는 GitHub Release 생성을 끈다. 예상 변경은 `pyproject.toml` version과 `CHANGELOG.md`뿐이며, 둘 다 tracked이므로 아래 정리 규칙으로 완전히 되돌릴 수 있다(별도 untracked 산출물 없음).

스탬핑과 `git switch -c`는 한 명령 간격이다. 이 사이 크래시로 `main`이 더러워지면 다음 prepare의 2단계 clean-tree 가드가 검출해 중단한다. 수동 복구는 아래와 같다. PSR이 스테이징까지 하므로 `--staged --worktree`가 모두 필요하다(worktree-only `git restore`는 인덱스의 스탬핑 값으로 되돌려 무음 no-op이 된다).

```bash
git restore --staged --worktree --source=HEAD pyproject.toml CHANGELOG.md
```

### 4. 버전 확인과 검증

release 브랜치에서 스탬핑된 버전이 예상 `vX.Y.Z`와 일치하는지 확인하고 검증을 수행한다. 검증 결과는 release PR에 포함한다.

```bash
grep '^version = ' pyproject.toml         # 예상 vX.Y.Z와 일치 확인
ruff check src/ tests/
ruff format --check src/ tests/
pytest tests/unit/ -x -n auto --tb=short -q
docker build -t ante:release-vX.Y.Z .
```

CI에서도 `release/*` PR이면 Docker build 검증을 수행한다. 이 단계에서는 registry push를 하지 않는다.

스탬핑(3단계)부터 커밋(5단계) 직전까지 워킹 트리가 더러운 것은 의도된 상태다. release 브랜치 생성(3단계 `git switch -c`) **이후**의 중도 종료(버전 불일치·검증 실패·사용자 거부)는 아래 하나로 정리한다. 더러운 워킹 트리는 release 브랜치에 있으므로 `main`으로 강제 전환하며 브랜치를 지우면 원상 복구된다. (스탬핑~`git switch -c` 사이 구간의 복구는 3단계에 규정된 `git restore --staged --worktree --source=HEAD pyproject.toml CHANGELOG.md`가 담당한다 — 이 구간은 release 브랜치가 아직 없어 `git branch -D`가 실패한다.)

```bash
git switch -f main && git branch -D release/vX.Y.Z
```

### 5. release commit과 PR

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

- 현재 브랜치가 `main`이 아니거나, release prepare 중 `release/vX.Y.Z`가 아님 — 4단계 이후 구간에만 적용한다. 3단계까지의 prepare는 의도적으로 `main`에서 진행한다.
- 워킹 트리가 깨끗하지 않음 — prepare 시작 시점(2단계)과 publish 경로에만 적용한다. prepare 3단계 스탬핑부터 5단계 커밋 직전까지 워킹 트리가 더러운 것은 의도된 상태이며 중단 사유가 아니다.
- 로컬 `HEAD`와 `origin/main`이 다름 — prepare 시작 시점(2단계)과 publish 경로에만 적용한다. 5단계 릴리스 커밋 이후 release 브랜치 HEAD 전진은 의도된 상태다.
- open release PR이 이미 있음
- publish 대상 release PR이 최신 main HEAD가 아님
- 최신 main 필수 CI가 실패했거나 확인 불가한데 사용자가 진행을 승인하지 않음
- 릴리스 대상 커밋이 없음
- PyPI에 같은 버전이 이미 존재함
- GHCR에 같은 Docker image tag가 이미 존재함
- GitHub 인증 또는 workflow 권한이 없음
