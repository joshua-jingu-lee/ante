main 브랜치의 누적 변경을 수동 릴리스한다. 사전 점검 결과를 사용자에게 보고한 뒤, 승인된 경우에만 `semantic-release.yml`을 실행하고 `publish.yml`까지 모니터링한다.

릴리스 정책은 `docs/runbooks/06-release.md`를 따른다. GitHub CLI 쓰기 작업 전 인증은 `.agent/skills/github-auth.md`를 먼저 따르고, workflow 조회/재실행 같은 공통 GitHub 운용은 `.agent/skills/github-ops.md`를 따른다.

## 인자

$ARGUMENTS — 선택 인자

- 없음: 실제 릴리스 후보를 점검하고, 사용자 승인 후 릴리스 workflow를 실행한다.
- `--dry-run`: 실제 릴리스 없이 workflow dry run과 사전 점검만 수행한다.

## 원칙

- 릴리스는 항상 수동으로만 시작한다. `main` 머지, `/autopilot`, `/implement-issue`는 릴리스를 자동 시작하지 않는다.
- PyPI 업로드는 되돌릴 수 없으므로, 실제 릴리스 실행 전 사용자 확인을 받는다.
- 로컬에서 버전 파일, changelog, 태그를 직접 만들지 않는다. 버전 결정, 태그, GitHub Release 생성은 `semantic-release.yml`이 담당한다.
- `publish.yml`은 GitHub Release published 이벤트로 자동 실행되며, `/release`는 실행 결과를 모니터링하고 실패 원인을 보고한다.
- 실패 복구는 `docs/runbooks/06-release.md`의 트러블슈팅을 따른다. 이미 배포된 PyPI 버전은 재업로드하지 않는다.

## 절차

### 1. 사전 문서 확인

아래 문서를 먼저 읽고 현재 정책과 인증 절차를 확인한다.

- `docs/runbooks/06-release.md`
- `docs/runbooks/03-git-workflow.md`
- `docs/runbooks/04-ci-cd.md`
- `.agent/skills/github-auth.md`
- `.agent/skills/github-ops.md`

### 2. 사전 점검

아래 항목을 순서대로 확인한다. `error` 항목이 있으면 실제 릴리스는 시작하지 않는다.

```bash
git branch --show-current
git status --porcelain
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
gh run list -b main -L 1 --json status,conclusion,workflowName,databaseId,headSha,createdAt
git describe --tags --abbrev=0
git log {last-tag}..HEAD --oneline
```

확인 결과는 사용자에게 표로 보고한다.

| 항목 | 성공 기준 |
|------|----------|
| 브랜치 | 현재 브랜치가 `main` |
| 워킹 트리 | `git status --porcelain`이 비어 있음 |
| 리모트 동기화 | `HEAD == origin/main` |
| CI 상태 | 최신 main 커밋의 필수 CI가 성공 |
| 릴리스 대상 | 마지막 태그 이후 릴리스 대상 커밋 존재 |
| 버전 범프 | Conventional Commits 기준 `feat`, `fix`, `perf`, breaking change 여부 확인 |

### 3. 릴리스 대상 요약

마지막 태그 이후 커밋을 Conventional Commits 기준으로 분류하고 예상 범프를 보고한다.

- `feat` → minor
- `fix`, `perf` → patch
- `feat!`, `BREAKING CHANGE:` → major
- `docs`, `test`, `refactor`, `ci`, `chore`, `style`, `build` → 기본적으로 릴리스 없음

릴리스 대상 커밋이 없으면 workflow를 실행하지 않고 종료한다. 단, 사용자가 `--dry-run`을 지정한 경우에는 dry-run 실행 여부를 확인한 뒤 진행할 수 있다.

### 4. 사용자 확인

실제 릴리스라면 다음 정보를 보여주고 명시적 승인을 받는다.

- 마지막 태그
- 예상 새 버전 또는 예상 bump
- 릴리스 대상 커밋 수
- 최신 main CI 결과
- `semantic-release.yml` 실행 여부
- `publish.yml`이 PyPI 업로드까지 수행한다는 점

`--dry-run`이면 실제 GitHub Release와 PyPI 업로드가 없다는 점을 명시한다.

### 5. semantic-release 실행

승인 후 GitHub Actions workflow를 수동 실행한다.

```bash
gh workflow run semantic-release.yml -f dry_run={true|false}
```

실행 직후 최신 run을 조회하고, 완료될 때까지 모니터링한다.

```bash
gh run list -w semantic-release.yml -L 1 --json status,conclusion,databaseId,headSha,createdAt
gh run view {run-id} --json status,conclusion,url,jobs
```

semantic-release가 새 릴리스를 만들지 않았으면 그 이유를 보고하고 종료한다.

### 6. publish 모니터링

실제 릴리스에서 GitHub Release가 생성되면 `publish.yml` 실행을 확인한다.

```bash
gh run list -w publish.yml -L 1 --json status,conclusion,databaseId,headSha,createdAt
gh run view {run-id} --json status,conclusion,url,jobs
```

`publish.yml`이 실패하면 실패 job과 단계, 로그 확인 방법, 필요한 후속 조치를 보고한다. 토큰, PyPI 중복 버전, 빌드 산출물 문제는 `docs/runbooks/06-release.md`의 트러블슈팅을 따른다.

### 7. 결과 보고

완료 보고에는 다음을 포함한다.

- 릴리스 버전
- GitHub Release URL
- PyPI URL
- `semantic-release.yml` run URL과 결과
- `publish.yml` run URL과 결과
- 실행 중 발견한 경고 또는 후속 조치

## 중단 조건

- 현재 브랜치가 `main`이 아님
- 워킹 트리가 깨끗하지 않음
- 로컬 `HEAD`와 `origin/main`이 다름
- 최신 main 필수 CI가 실패했거나 확인 불가한데 사용자가 진행을 승인하지 않음
- 릴리스 대상 커밋이 없음
- PyPI에 같은 버전이 이미 존재함
- GitHub 인증 또는 workflow 권한이 없음
