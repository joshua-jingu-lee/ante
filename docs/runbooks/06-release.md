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
        ├── PyPI package (+ password-less 업로드 성공 여부 확인 — §8)
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
| PR 게이트 | 일반 PR과 동일: required status checks([04-ci-cd.md §3.2](04-ci-cd.md#32-저장소-설정-권장값) SSOT) + `merge-gate` (`AUTOMERGE_TOKEN` PAT로 auto-merge 활성화; 머지 후 `pull_request:closed` 이벤트로 post-merge 정리 — #2437) |
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

리포는 PUBLIC이며, PyPI 업로드는 **Trusted Publishing(OIDC)**을 기본 경로로 쓴다(#2436). `publish.yml`의 pypa/gh-action-pypi-publish 스텝은 `password:` 입력 없이 `id-token: write` + `environment: pypi`만으로 OIDC 인증을 자동 진입한다(핀된 pypa 액션 README: "authentication to PyPI **without a manually configured API token or username/password**", "`id-token: write` permission and **without** an explicit username or password").

> **이 문서는 액션 버전 숫자를 적지 않는다.** 핀된 pypa 액션의 버전·SHA SSOT는 [`publish.yml`](../../.github/workflows/publish.yml)의 `Publish to PyPI` 스텝(`uses:` 줄의 커밋 SHA와 그 트레일링 `# vX.Y.Z` 주석)뿐이다. `.github/dependabot.yml`이 github-actions를 weekly로 범프해 이 값은 계속 움직이므로(런북에 박아 둔 버전 라벨이 실제로 두 번 낡았다 — #2450), 위 인용은 특정 버전이 아니라 **그때그때 핀된 README**에 귀속한다.

| 인증 방식 | 상태 | 비고 |
|-----------|------|------|
| Trusted Publishing (OIDC) | 기본 (현행 — 실증 완료) | `id-token: write` + `environment: pypi`, `password:` 없음. 실증 근거는 아래 「실증 기록」 |
| API 토큰 (`PYPI_API_TOKEN` secret) | 폴백 (**장애 대응** — 시크릿 보존, 워크플로우 경로 전용) | 검증된 기본 경로가 막혔을 때의 장애 대응 수단이며 상시 전환 후보가 아니다. 구조적 OIDC 포기 시 **다음 릴리스부터** 토큰 경로 복귀(현 릴리스 소급 불가). 시크릿은 write-only라 수동 twine의 자격증명 출처는 아님 — rerun 창 경과 시 수동 구조는 새 토큰 발급으로([§11 OIDC 인증 실패](#oidc-인증-실패-pypi-업로드-403인증-오류)) |

**사용자 사전조건 (소유자만 확인 가능한 외부 상태)**: ante는 이미 여러 버전이 게시된 기존 PyPI 프로젝트다. **pending publisher는 미존재 프로젝트 예약용이라 기존 프로젝트를 커버하지 못한다** — "pending publisher 등록 완료"를 OIDC 동작 증거로 삼지 않는다. 소유자가 프로젝트 설정 `https://pypi.org/manage/project/ante/settings/publishing/`에서 이 리포·워크플로우(`publish.yml`)·environment(`pypi`)를 가리키는 **trusted publisher를 직접 등록**해야 한다(pypa README: "your project's publisher must already be configured on PyPI"). 이 등록은 **v0.12.0 업로드 성공으로 활성 상태가 확인됐다**(아래 「실증 기록」).

등록 **내용**도 웹 UI 없이 읽을 수 있다. PyPI provenance 엔드포인트는 **인증 없이** 해당 업로드를 승인한 publisher의 `repository`·`workflow`·`environment`를 그대로 반환하므로, curl 한 번이면 된다(경로의 버전·휠 파일명을 가장 최근 게시 버전으로 바꿔 조회한다):

```bash
curl -s -H "Accept: application/vnd.pypi.integrity.v1+json" \
  https://pypi.org/integrity/ante/0.12.0/ante-0.12.0-py3-none-any.whl/provenance \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['attestation_bundles'][0]['publisher'])"
# {'environment': 'pypi', 'kind': 'GitHub', 'repository': 'joshua-jingu-lee/ante', 'workflow': 'publish.yml'}
```

여기서 `environment`는 업로드 측 토큰 claim이 아니라 **PyPI 등록 레코드의 값**이다 — warehouse는 attestation의 publisher identity를 등록 레코드(`GitHubPublisher`)에서 만들고, 그 레코드의 `environment` 컬럼을 그대로 싣는다(환경 제약이 있는 레코드를 우선 매칭하고, 없을 때만 무제약 레코드로 폴백한다 — 무제약 레코드가 매칭됐다면 이 필드는 값이 없다(null/누락)). 따라서 위 출력은 등록이 environment `pypi`로 **제약돼 있음**을 확인해 준다. 확인된 이 등록이 매칭에서 벗어나는 변경은 두 갈래이고, **위험한 쪽은 조용한 쪽이다.** 워크플로우 파일명(`publish.yml`) 변경과 리포 이동·개명은 후보 조회 자체를 비운다 — warehouse는 리포 소유자(이름·소유자 ID)·리포명·워크플로우 파일명으로 등록 레코드를 질의하므로, 이 중 하나만 바뀌어도 후보가 **0건**이 되어 폴백할 레코드조차 없고 **토큰 교환 단계에서 `invalid-publisher`로 거부된다**(dist 업로드 이전 — [§11](#11-트러블슈팅)). 반면 **environment 이름만 바꾸면 거부되지 않을 수 있다**: unique 키에 `environment`가 포함되어 같은 리포·워크플로우에 제약 레코드와 무제약 레코드가 **공존할 수 있고**(위 출력은 제약 레코드가 우선 매칭된 결과라 이 공존을 배제하지 못한다), 무제약 등록이 함께 있으면 제약 매칭 실패 후 그 레코드로 폴백해 **업로드는 그대로 성공하면서 environment 제약만 조용히 사라진다.** 무제약 등록이 없으면 위와 같이 거부된다. 즉 이 절이 경고하는 실제 리스크는 시끄러운 실패가 아니라 **무성 보안 강도 저하**이며, 사후 탐지는 같은 provenance 조회로 한다 — 그 업로드의 `environment`가 `null`(누락)로 나오면 무제약 레코드가 쓰인 것이다. 확인은 **재등록이 필요해지는 변경이 생길 때** 한다.

남는 한계는 하나다: **provenance는 업로드 시점의 스냅샷이라 현재 등록 상태를 증명하지 않는다.** 등록은 소유자가 언제든 철회·변경할 수 있는 가변 상태라, 한 번 확인됐다고 진단 순위에서 내리지 않는다(§11 1순위 유지).

**여전히 검증 불가인 전제**: 폴백용 `PYPI_API_TOKEN` 시크릿의 실재·유효성은 `gh secret list`가 403이라 확인할 수 없다. 폴백 경로(§11)를 실제로 쓰기 전에 소유자 확인이 필요하다.

**실증 기록**: password-less OIDC 업로드는 **v0.12.0(2026-07-28)에서 실증됐다.** `publish.yml` run [30398415975](https://github.com/joshua-jingu-lee/ante/actions/runs/30398415975)의 `Publish to PyPI` 스텝이 `password:` 입력 없이 성공해 PyPI에 `ante 0.12.0`이 게시됐고, digital attestations 생성도 성공했다(attestation은 Trusted Publishing 업로드에만 허용되므로 OIDC 경로였음의 증거다). 새 venv에서 `pip install ante==0.12.0` → `import ante` / `ante --version`으로 사후 확인까지 마쳤다. 즉 OIDC는 **검증된 기본 경로**이며, 토큰 폴백은 그 경로의 장애 대응 수단이다 — 미검증 리스크를 이유로 폴백으로 전환할 근거는 없다.

**사전 검증의 한계 (현행 구성 한정)**: 이 실증이 실 릴리스에서만 가능했던 것은 **현행 `publish.yml` 구성의 성질**이다. PyPI 업로드·GHCR login·GHCR push 세 지점이 모두 `github.event_name == 'release'`에 걸려 있어 `workflow_dispatch`는 OIDC 경로를 아예 실행하지 않는다(build-only). 정확히는 **스텝 게이트 2개**(`Publish to PyPI`·`Log in to GHCR`의 `if:`)와 **입력 게이트 1개**(`Build and publish Docker image`의 `push:` — 이 스텝 자체는 dispatch에서도 실행되어 push 없이 빌드만 한다)이며, "dispatch는 OIDC를 밟지 않는다"는 결론은 `Publish to PyPI` 스텝 게이트 하나로 성립한다. OIDC를 밟으려면 실제 `release` 이벤트가 필요하고, 그 이벤트는 동시에 **실 PyPI 업로드와 실 GHCR push를 낸다** — 검증용 임시 릴리스는 파괴적이다. 이는 "OIDC는 원리적으로 사전 검증이 불가하다"는 뜻이 **아니다**: 핀된 pypa 액션은 `repository-url: https://test.pypi.org/legacy/`로 TestPyPI 대상 업로드를 정식 지원하며, 현행 구성이 그 경로를 쓰지 않을 뿐이다. 한편 OIDC publish가 실패해도 인증은 dist 업로드 이전 단계라 버전을 소모하지 않는다(§11).

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
  - **(ii) 즉시 릴리스가 필요한 경우**: `semantic-release.yml`에는 forced-minor 전파 입력이 없다(현재 `declare_major`만 §6 경로로 전파된다). 따라서 자동 해소 경로가 아직 없으며, §6 declare-major와 동일 패턴으로 **prepare 계약(`release.md`의 forced-minor 인자)과 CI(`semantic-release.yml` 전파 입력)를 함께** 확장하는 이슈를 등록해 반영한 뒤 진행한다 — CI만 확장하면 prepare의 버전 산정·전역 태그 가드에서 다시 막힌다.

#### `:latest` 취급 (조건부)

`publish.yml`은 릴리스 태그가 **전역 최고 semver일 때만** GHCR `:latest`를 push한다([publish.yml](../../.github/workflows/publish.yml)의 `:latest` semver 가드, #2430). 따라서 GHCR `:latest`는 과거 라인 핫픽스에서도 자동으로 역행하지 않는다. 두 경우로 나뉜다.

- **핫픽스 태그가 최고 semver인 경우(일반적 — 예: 1.1 미릴리스 상태에서 1.0.4가 곧 최고 태그)**: `:latest`가 핫픽스 버전으로 전진하는 것이 정상이다. 아무 재지정도 하지 않는다(7단계 `--latest=false`도 붙이지 않는다).
- **핫픽스 태그보다 높은 릴리스가 이미 있는 경우(과거 라인 핫픽스 — 예: main이 이미 1.1.x로 릴리스됨)**: (i) **GHCR `:latest`는 `publish.yml`의 semver 가드(#2430)가 자동으로 역행을 막는다** — 릴리스 태그가 전역 최고가 아니면 `:latest`를 아예 push하지 않으므로 정상적으로는 수동 재지정이 필요 없다. 가드가 어떤 이유로 동작하지 않아 역행이 실제로 발생했을 때만 폴백으로 GHCR `:latest`를 최신 정규 버전으로 수동 재지정한다(§11). (ii) **GitHub Release 'Latest' 마커는 가드 범위 밖(Docker `:latest`와 별개)이므로** 7단계 `gh release create`에 `--latest=false`를 지정해 마커 역행을 수동으로 막는다.

semver 최고 태그만 `:latest`로 push하는 CI 가드는 `publish.yml`에 구현돼 있다(#2430 — checkout 후 `git fetch --tags --force origin`으로 전역 태그를 확보하고, 릴리스 태그가 전역 최고 semver와 문자열 등가일 때만 조건부 태그 목록에 `:latest`를 포함). 버전별 태그(`:v1.0.4`)는 §7대로 절대 덮어쓰지 않으며, 부동 태그인 `:latest`만 가드·재지정 대상이다.

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

### publish.yml 미트리거 (릴리스는 생겼는데 배포가 없음)

**증상**: `semantic-release.yml`이 `success`로 끝나고 GitHub Release도 dist 자산·노트까지 정상 생성됐는데, `publish.yml`이 **아예 실행되지 않아** PyPI 업로드와 GHCR push가 통째로 누락된다. 겉보기에는 릴리스가 성공한 것처럼 보이는 **조용한 누락**이 이 실패 모드의 본질이다(v0.11.0·v0.12.0 2회 연속 실측 — #2449).

**판정**: **최신 run(`-L 1`)을 보면 안 된다.** 직전 릴리스의 성공 run이나 build-only `workflow_dispatch` run이 잡혀 거짓 성공으로 읽힌다(v0.12.0에서 실제로 오판). `event=release` **와** 이번 릴리스 태그 커밋 `headSha`를 함께 대조한다.

```bash
git fetch --tags --force origin
TAG_SHA=$(git rev-parse "vX.Y.Z^{commit}")
gh run list -w publish.yml -L 20 --json databaseId,event,headSha,status,conclusion,url \
  | jq --arg sha "$TAG_SHA" '[.[] | select(.event == "release" and .headSha == $sha)]'
```

빈 배열이면 미트리거다. `semantic-release.yml`의 `Verify publish.yml was triggered` 스텝(#2449)이 릴리스 직후 같은 판정을 최대 105초(15초 간격, 조회 8회) 폴링하므로, 정상 경로에서는 사람이 이 조회를 하기 전에 **워크플로우 run이 red로 먼저 알려준다**.

**원인**: `GITHUB_TOKEN`이 만든 이벤트는 다른 워크플로우를 트리거하지 않는 GitHub 기본 동작(무한 재귀 방지)이다 — [04-ci-cd.md §5.2](04-ci-cd.md#52-post-merge-실패-모드와-복구)의 머지 경로와 동일한 결함 클래스. `semantic-release.yml`은 `AUTOMERGE_TOKEN`(PAT)으로 릴리스를 만들어 이를 피한다([04-ci-cd.md §7](04-ci-cd.md#7-릴리스-연계)). 따라서 실무 원인 1순위는 **`AUTOMERGE_TOKEN`의 만료·권한 부족(`Contents: Read and write` 필요)**이다. 시크릿이 아예 없으면 워크플로우 앞단의 fail-closed 가드가 태그 생성 이전에 막는다(아래 「고아 태그」).

**재실행 금지 (중요)**: **`semantic-release.yml`의 rerun과 재dispatch를 모두 하지 않는다.** 둘 다 HEAD가 이미 태그된 상태라 `semantic-release version`이 "No release will be made"를 반환하고, `released=false`가 되어 Build·Create GitHub Release·자기검증 스텝이 **전부 skip된 채 run이 초록으로 끝난다** — 시끄러운 실패가 다시 조용해지는 경로다. 이 금지는 `semantic-release.yml` 한정이며, 아래 「OIDC 인증 실패」가 권장하는 **`publish.yml`의 `gh run rerun`(표준 복구)과는 대상 워크플로우가 다르다.** `.agent/skills/github-ops.md`의 rerun-우선 규범도 `publish.yml`처럼 이벤트가 보존된 run에 적용된다.

**복구 — draft 토글 단일 경로**: 실사용자 PAT 주체로 `published` 이벤트를 재발생시킨다.

```bash
source .github/local/github.env
gh release edit vX.Y.Z --draft
gh release edit vX.Y.Z --draft=false --latest
```

비파괴다 — dist 자산·릴리스 노트·annotated 태그가 모두 보존된다(v0.12.0 실측, 토글 직후 1초 내 `publish.yml` 발화). **릴리스를 삭제·재생성하지 않는다**(dist 자산이 유실되는 파괴 경로 — 「이미 릴리스된 버전」). 핫픽스 등으로 이 태그가 전역 최고 semver가 아니면 `--latest` 대신 `--latest=false`를 쓴다([§10 7단계](#10-핫픽스-릴리스)).

복구 후에는 위 판정 명령으로 `event=release` run이 실제로 생겼는지 다시 확인하고, `/release publish` 4단계 모니터링을 이어간다.

### 고아 태그 (태그는 있는데 릴리스가 없음)

**증상**: `semantic-release.yml`이 `Create GitHub Release` 스텝에서 401/403으로 실패했다. PSR은 이미 `vX.Y.Z` 태그를 push한 뒤라 **태그는 원격에 있는데 GitHub Release가 없는** 부분 완료 상태가 된다. 릴리스가 없으니 `publish.yml`도 당연히 트리거되지 않는다.

**원인**: `AUTOMERGE_TOKEN`의 권한 부족(`Contents: Read and write` 미보유) 또는 만료. 시크릿 자체가 없는 경우는 fail-closed 가드가 태그 생성 이전에 막으므로 이 상태가 되지 않는다.

**복구**: 태그는 불변이므로 지우지 않는다. §10 핫픽스의 **수동 릴리스 경로를 그대로 재사용**해 릴리스만 사후 생성한다. 실사용자 주체의 `gh release create`라 `publish.yml`은 정상 트리거된다.

```bash
source .github/local/github.env
git fetch --tags --force origin
git switch --detach vX.Y.Z
pip install build && python -m build      # 실패한 run의 dist는 남아 있지 않으므로 재빌드
gh release create vX.Y.Z --generate-notes dist/*
```

`--latest` 취급은 [§10 7단계](#10-핫픽스-릴리스)와 동일하다(전역 최고 semver가 아니면 `--latest=false`). 근본 원인인 PAT 권한은 다음 릴리스 전에 반드시 정정한다 — 정정하지 않으면 매 릴리스가 이 상태로 떨어진다.

### publish.yml 실패

- Docker login 실패 시 `GITHUB_TOKEN`의 `packages: write` 권한과 repository package 설정을 확인한다.
- Docker build 실패 시 release PR의 Docker build 검증과 실제 publish 환경 차이를 비교한다.
- PyPI 인증 실패는 아래 「OIDC 인증 실패」를 따른다(현행은 OIDC 기본, 토큰은 폴백 — §8).
- 폴백용 `PYPI_API_TOKEN` 시크릿은 만료 시 GitHub Secrets에서 갱신한다 — 토큰 폴백 경로(§8·아래)를 살려두려면 유효성을 유지해야 한다.

### OIDC 인증 실패 (PyPI 업로드 403/인증 오류)

password-less OIDC 전환(#2436) 후 PyPI 업로드가 실패하면 아래 순서로 진단·복구한다.

**진단**

- **1순위 — trusted publisher 등록 확인**: ante는 기존 PyPI 프로젝트라 **pending publisher가 아니라** 프로젝트 설정에 등록된 trusted publisher가 필요하다. `https://pypi.org/manage/project/ante/settings/publishing/`에서 이 리포·`publish.yml`·environment `pypi`를 가리키는 publisher가 활성인지 확인한다. 미등록/불일치면 업로드가 **403**(`invalid-publisher`/`trusted publisher` 계열 메시지)으로 거부된다 — 전환 직후 가장 흔한 원인이다.
- **후순위 — environment/permissions**: `id-token: write`(`publish.yml`)·`environment: pypi`는 정적 전제로 이미 정상 확인됐다. publisher 등록이 맞는데도 실패하면 이 둘과 environment 보호 규칙(승인 대기 등)을 점검한다.

**1차(표준) 복구 — 비파괴 rerun**

OIDC 인증은 dist 업로드 **이전** 단계라 실패해도 PyPI에 어떤 버전도 올라가지 않는다(버전 미소모 → 「이미 릴리스된 버전」 충돌 없음). 유력 원인인 trusted publisher 미등록/불일치는 **PyPI 프로젝트 설정에서만 정정하면 워크플로우·릴리스·태그를 전혀 건드릴 필요가 없다**.

1. 위 진단대로 PyPI 프로젝트 설정에서 trusted publisher 등록을 정정한다.
2. 실패한 run을 `gh run rerun --failed <run-id>`로 재실행한다(초기 실행 후 **~30일 이내**). **같은 `release: published` 이벤트·같은 태그 SHA로 다시 돌아** OIDC가 성공하며, 릴리스·dist 자산·노트가 모두 보존된다(비파괴).

> `workflow_dispatch` 재실행은 Publish to PyPI 스텝의 `if: github.event_name == 'release'` 게이트로 업로드하지 못하므로(dispatch는 build-only), 현 릴리스 재실행의 표준 경로는 위 `gh run rerun`이다(창 경과 시 아래 최후 수단). **릴리스를 삭제·재생성하지 않는다** — semantic-release가 첨부한 dist 자산이 유실되는 파괴 경로다.

**rerun 창(~30일) 경과 시 최후 수단 — 수동 twine 업로드**

GitHub run 재실행은 초기 실행 후 ~30일 제한이라 창이 지나면 rerun이 불가하다. 이때는 릴리스에 첨부된 dist 자산(semantic-release가 업로드)을 받아, 구조 시점에 새로 발급한 PyPI API 토큰으로 직접 업로드한다(아래 — 보존된 시크릿은 읽기 불가라 출처가 될 수 없음).

```bash
gh release download vX.Y.Z -D dist-rescue/
TWINE_USERNAME=__token__ TWINE_PASSWORD="<PyPI API 토큰>" twine upload dist-rescue/*
```

토큰은 **구조 시점에 PyPI 계정에서 새로 발급**한다(pypi.org/manage/account/token/) — GitHub Actions 시크릿은 write-only라 로컬로 읽어올 수 없으므로 "보존된 시크릿"이 자격증명 출처가 될 수 없다(시크릿 보존은 워크플로우 토큰 경로 복귀용 — 아래). 발급한 토큰으로 시크릿도 함께 갱신해 두면 좋다.

PyPI 산출물만 복구된다. GHCR 이미지는 태그 커밋 체크아웃에서 `docker build`·push로 별도 수동 복구한다 — **버전 태그(vX.Y.Z·X.Y.Z)만 push**하고, `:latest`는 이 태그가 전역 최고 semver일 때만 push한다(§10 :latest 가드 규칙의 수동 적용 — 수동 경로는 publish.yml 가드를 우회하므로 직접 판정). §7 태그 정책(같은 버전 태그 덮어쓰기 금지) 준수.

**토큰 폴백(워크플로우 config)은 현 릴리스에 소급되지 않는다 (구조적 한계)**

`release` 이벤트는 **태그 커밋 시점의 `publish.yml`**을 실행한다. 따라서 main에 `password:`를 복원해도 이미 만들어진 태그의 재실행에는 반영되지 않고(같은 OIDC 경로로 재실패), 태그를 새 커밋으로 다시 만드는 것은 「이미 릴리스된 버전」의 태그 불변 규칙 위반이다. 즉 **`publish.yml`에 password를 복원하는 워크플로우 경로로는 현 릴리스를 구제할 수 없다** — 현 릴리스는 위 rerun(표준) 또는 수동 twine(창 경과 시)으로 처리한다. 워크플로우 토큰 경로는 OIDC를 구조적 이유로 포기하고 **다음 릴리스부터** 되돌아갈 때만 유효하다: `publish.yml` pypa 스텝에 `with:`/`password: ${{ secrets.PYPI_API_TOKEN }}`을 복원한다(시크릿은 삭제하지 않아 보존됨 — §8 폴백, 만료 시 갱신은 「publish.yml 실패」 참조).

### 이미 릴리스된 버전

- PyPI에 이미 올라간 버전은 재업로드할 수 없다.
- 이미 존재하는 git tag나 Docker image tag는 덮어쓰지 않는다.
- 잘못 생성된 GitHub Release/tag 정리는 사람 확인 후 수동으로만 수행한다.

### 운영 버전에 긴급 수정이 필요한데 main이 릴리스 불가

- main이 릴리스 가능한 상태면 일반 패치 릴리스(`fix:` → `/release prepare`/`publish`)로 처리한다 — [§10 핫픽스 릴리스 · 기본 경로](#10-핫픽스-릴리스).
- 1.1 개발 커밋 등이 쌓여 main을 지금 릴리스할 수 없으면 라인 브랜치(lazy-branch) 예외 경로를 쓴다 — [§10 · 예외 경로](#10-핫픽스-릴리스). 핫픽스 태그보다 높은 릴리스가 이미 있는 과거 라인 핫픽스에서만 `:latest` 역행이 문제되는데, GHCR `:latest`는 `publish.yml` semver 가드(#2430)가 자동으로 막으므로 별도 조치가 필요 없고([§10 · `:latest` 취급](#10-핫픽스-릴리스)), GitHub Release 'Latest' 마커만 7단계 `--latest=false`로 수동 관리한다.

### 핫픽스 후 GHCR `:latest`가 과거 버전을 가리킴

- **GHCR `:latest` 역행은 `publish.yml`의 semver 가드(#2430)가 자동으로 막는다** — 릴리스 태그가 전역 최고 semver가 아니면 `:latest`를 push하지 않으므로, 정상적으로는 이 증상이 GHCR에서 발생하지 않는다. 핫픽스 태그가 최고 semver면 `:latest` 전진이 정상이다.
- 가드가 어떤 이유로 동작하지 않아 역행이 실제로 발생한 경우의 사후 복구: (i) GitHub Latest 마커 복원(가드 범위 밖 — Docker `:latest`와 별개) — 최신 정규 릴리스 태그를 대상으로 `gh release edit vX.Y.Z --latest`(이미 생성된 릴리스라 `--latest=false`는 쓸 수 없다), (ii) 폴백으로 GHCR `:latest`를 최신 정규 버전으로 수동 재지정.
- 사전 예방: GHCR `:latest`는 위 자동 가드가 처리하고, GitHub Release 'Latest' 마커는 [§10 7단계](#10-핫픽스-릴리스)의 `--latest=false`(태그 생성 시점)로 관리한다.
