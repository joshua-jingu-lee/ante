# 06. 릴리스 프로세스

> PyPI 배포까지의 릴리스 절차를 정의한다.

---

## 1. 릴리스 정책

- **수동 실행만 허용**: main에 머지되었다고 자동 릴리스되지 않는다.
- **실행 방법**: `/release` 스킬 또는 GitHub Actions에서 semantic-release.yml 수동 dispatch.
- **버전 규칙**: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션) Conventional Commits 기반 자동 범프.

## 2. 릴리스 흐름

```
/release 실행
  │
  ├── [사전 점검] 체크리스트 검증
  │     ├── main 브랜치인지 확인
  │     ├── 워킹 트리 클린 여부
  │     ├── 로컬/리모트 동기화 여부
  │     ├── CI 상태 확인 (최근 main 커밋)
  │     └── 릴리스할 커밋 존재 여부 (마지막 태그 이후)
  │
  ├── [1단계] semantic-release.yml 실행
  │     ├── 커밋 메시지 분석 → 버전 결정
  │     ├── pyproject.toml version 범프
  │     ├── CHANGELOG.md 갱신
  │     ├── chore(release): v{version} 커밋 + 태그 push
  │     └── GitHub Release 생성 (generate_release_notes)
  │
  ├── [2단계] publish.yml 자동 트리거
  │     ├── 프론트엔드 빌드 (npm ci && npm run build)
  │     ├── 빌드 산출물 → src/ante/web/static/ 복사
  │     ├── Python 패키지 빌드 (python -m build)
  │     ├── wheel 검증 (pip install + import 확인)
  │     └── PyPI 업로드 (API 토큰)
  │
  └── [완료] 결과 확인
        ├── GitHub Release 페이지 확인
        ├── PyPI 패키지 페이지 확인
        └── pip install ante=={version} 검증
```

## 3. 사전 점검 체크리스트

| # | 항목 | 검증 방법 | 실패 시 |
|---|------|-----------|---------|
| 1 | main 브랜치 | `git branch --show-current` | 에러 — main에서만 릴리스 가능 |
| 2 | 클린 워킹 트리 | `git status --porcelain` | 에러 — 커밋되지 않은 변경 있음 |
| 3 | 리모트 동기화 | `git fetch && git diff HEAD origin/main` | 에러 — push/pull 필요 |
| 4 | CI 통과 | `gh run list -b main -L 1 --json conclusion` | 경고 — CI 실패 시 확인 필요 |
| 5 | 릴리스할 커밋 | `git log $(git describe --tags --abbrev=0)..HEAD --oneline` | 경고 — 새 커밋 없으면 릴리스 불필요 |
| 6 | 릴리스할 타입 | feat/fix/perf 커밋 존재 여부 | 경고 — 버전 범프 대상 없음 |

## 4. 버전 범프 규칙

| 커밋 타입 | 범프 | 예시 |
|-----------|------|------|
| `feat` | minor | 0.7.0 → 0.8.0 |
| `fix`, `perf` | patch | 0.7.0 → 0.7.1 |
| `feat!`, `BREAKING CHANGE:` | major | 0.7.0 → 1.0.0 |
| `refactor`, `test`, `docs`, `ci`, `chore` | 없음 | — |

> 상세: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션)

## 5. PyPI 배포 인증

| 단계 | 인증 방식 | 비고 |
|------|-----------|------|
| 현재 (private repo) | API 토큰 (`PYPI_TOKEN` secret) | GitHub environment: `pypi` |
| 공개 후 | Trusted Publisher (OIDC) | pending publisher 등록 완료 |

전환 시: `publish.yml`에서 `password:` 라인 제거 → OIDC 자동 적용.

## 6. 트러블슈팅

### semantic-release가 "No release will be made"

- 마지막 태그 이후 `feat`/`fix`/`perf` 커밋이 없으면 발생.
- `refactor`, `test`, `docs` 등은 버전 범프 대상이 아님.

### publish.yml 실패

- `src/ante/web/static/` 디렉토리가 없으면 프론트엔드 빌드 복사 실패 → `mkdir -p` 로 해결 (현재 적용됨).
- PyPI 토큰 만료 시 → GitHub Secrets에서 `PYPI_TOKEN` 갱신.

### 이미 릴리스된 버전

- `semantic-release version`이 이미 존재하는 태그를 생성하면 실패.
- `git tag -d vX.Y.Z && git push --delete origin vX.Y.Z` 로 태그 제거 후 재시도 (주의: PyPI에 이미 올라간 버전은 재업로드 불가).
