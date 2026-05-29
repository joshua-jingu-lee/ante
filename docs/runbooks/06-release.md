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
  ├── release/vX.Y.Z 브랜치 생성 (origin/main 기준)
  │
  ├── 릴리스 메타데이터 갱신
  │     ├── pyproject.toml version
  │     └── CHANGELOG.md
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
이 경우 `origin/main`으로 rebase하고 버전/CHANGELOG를 다시 계산하거나, 기존 release PR을 닫고 새 release PR을 만든다.

## 4. 충돌 방지 규칙

- open release PR이 있으면 새 release PR을 만들지 않는다.
- 같은 `release/vX.Y.Z` 원격 브랜치가 있으면 덮어쓰지 않는다.
- release PR merge 후 publish 전에 main에 새 커밋이 추가되면 publish하지 않는다.
- publish 대상 버전의 git tag, PyPI version, GHCR image tag가 이미 있으면 중단한다.
- release PR은 auto-merge 대상이 될 수 있지만, publish는 별도 수동 실행이다.
- `/autopilot`과 `/implement-issue`는 release 브랜치나 release PR을 생성하지 않는다.

## 5. 버전 범프 규칙

| 커밋 타입 | 범프 | 예시 |
|-----------|------|------|
| `feat` | minor | 0.7.0 → 0.8.0 |
| `fix`, `perf` | patch | 0.7.0 → 0.7.1 |
| `feat!`, `BREAKING CHANGE:` | major | 0.7.0 → 1.0.0 |
| `refactor`, `test`, `docs`, `ci`, `chore` | 없음 | — |

> 상세: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션)

## 6. Docker image 정책

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

## 7. PyPI 배포 인증

| 단계 | 인증 방식 | 비고 |
|------|-----------|------|
| 현재 (private repo) | API 토큰 (`PYPI_API_TOKEN` secret) | GitHub environment: `pypi` |
| 공개 후 | Trusted Publisher (OIDC) | pending publisher 등록 완료 |

전환 시: `publish.yml`에서 `password:` 라인 제거 → OIDC 자동 적용.

## 8. 트러블슈팅

### semantic-release가 "No release will be made"

- 마지막 태그 이후 `feat`/`fix`/`perf` 커밋이 없으면 발생한다.
- release PR이 stale이면 main 최신 커밋 기준으로 `/release prepare`를 다시 수행한다.

### release PR이 stale

- release PR 생성 후 main에 다른 PR이 merge된 상태다.
- `origin/main`으로 rebase한 뒤 버전/CHANGELOG를 다시 계산한다.
- 예상 버전이 달라지면 기존 release PR을 닫고 새 `release/vX.Y.Z` PR을 만든다.

### publish.yml 실패

- PyPI 토큰 만료 시 GitHub Secrets에서 `PYPI_API_TOKEN`을 갱신한다.
- Docker login 실패 시 `GITHUB_TOKEN`의 `packages: write` 권한과 repository package 설정을 확인한다.
- Docker build 실패 시 release PR의 Docker build 검증과 실제 publish 환경 차이를 비교한다.

### 이미 릴리스된 버전

- PyPI에 이미 올라간 버전은 재업로드할 수 없다.
- 이미 존재하는 git tag나 Docker image tag는 덮어쓰지 않는다.
- 잘못 생성된 GitHub Release/tag 정리는 사람 확인 후 수동으로만 수행한다.
