# 릴리스 스킬

> main 브랜치의 변경사항을 PyPI에 배포한다. 사전 체크리스트를 검증하고, semantic-release → publish.yml 파이프라인을 실행한다.

## 트리거

- `/release` — 사용자가 수동 실행

## 인자

$ARGUMENTS — 없음 (옵션: `--dry-run` 시 실제 릴리스 없이 검증만 수행)

## 실행 절차

### 1단계: 사전 점검

아래 항목을 **순서대로** 검증한다. 에러 항목이 있으면 즉시 중단하고 사용자에게 보고한다.

```bash
# 1. main 브랜치 확인
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then echo "ERROR: main 브랜치에서만 릴리스 가능 (현재: $BRANCH)"; fi

# 2. 클린 워킹 트리
if [ -n "$(git status --porcelain)" ]; then echo "ERROR: 커밋되지 않은 변경이 있습니다"; fi

# 3. 리모트 동기화
git fetch origin main
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then echo "ERROR: 로컬과 리모트가 다릅니다. git pull 또는 git push 필요"; fi

# 4. CI 상태 확인
gh run list -b main -L 1 --json conclusion -q '.[0].conclusion'

# 5. 릴리스할 커밋 확인
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -n "$LAST_TAG" ]; then
  git log ${LAST_TAG}..HEAD --oneline
else
  echo "태그 없음 — 첫 릴리스"
fi
```

검증 결과를 사용자에게 표로 보고한다:

```
## 릴리스 사전 점검

| # | 항목 | 결과 |
|---|------|------|
| 1 | main 브랜치 | ✅ |
| 2 | 클린 워킹 트리 | ✅ |
| 3 | 리모트 동기화 | ✅ |
| 4 | CI 상태 | ✅ success |
| 5 | 릴리스할 커밋 | ✅ N개 (feat: X, fix: Y) |
```

### 2단계: 릴리스 대상 확인

마지막 태그 이후 커밋을 요약하고, 예상 버전 범프를 사용자에게 안내한다.

```
### 릴리스 대상 커밋

- feat(cli): add ante update command
- fix(config): handle missing secrets.env
- ...

**예상 범프**: 0.7.0 → 0.8.0 (minor — feat 커밋 존재)
```

사용자 확인을 요청한다: "릴리스를 진행할까요?"

### 3단계: semantic-release 실행

사용자가 승인하면 GitHub Actions에서 semantic-release를 실행한다.

```bash
# dry-run이면 여기서 종료
gh workflow run semantic-release.yml -f dry_run=$DRY_RUN
```

실행 후 워크플로우 완료를 모니터링한다:

```bash
# 최근 실행 확인
gh run list -w semantic-release.yml -L 1 --json status,conclusion,databaseId
```

### 4단계: publish.yml 모니터링

semantic-release가 GitHub Release를 생성하면 publish.yml이 자동 트리거된다.

```bash
# publish 워크플로우 확인
gh run list -w publish.yml -L 1 --json status,conclusion,databaseId
```

### 5단계: 결과 보고

```
## 릴리스 완료

| 항목 | 값 |
|------|-----|
| 버전 | v0.8.0 |
| GitHub Release | https://github.com/joshua-jingu-lee/ante/releases/tag/v0.8.0 |
| PyPI | https://pypi.org/project/ante/0.8.0/ |
| semantic-release | ✅ success |
| publish | ✅ success |
```

## 주의사항

- **main 브랜치에서만 실행** — 다른 브랜치에서는 릴리스 금지.
- **수동 실행만** — main 머지 시 자동 릴리스되지 않음.
- **PyPI 업로드는 되돌릴 수 없음** — 같은 버전을 다시 올릴 수 없으므로 신중하게 진행.
- CI 실패 상태에서 릴리스 시 사용자에게 경고 후 확인을 받는다.

## 참조

- 릴리스 프로세스 상세: [docs/runbooks/06-release.md](../../docs/runbooks/06-release.md)
- CI/CD 파이프라인: [docs/runbooks/04-ci-cd.md](../../docs/runbooks/04-ci-cd.md)
- 커밋 컨벤션: [docs/runbooks/03-git-workflow.md](../../docs/runbooks/03-git-workflow.md)
