# 04. CI/CD와 리뷰 게이트

> GitHub Actions 기반 CI/CD와 내부 브랜치 리뷰(`/code-review`), merge gate 정책을 정의한다.
> 에이전트의 실제 실행 절차는 `.agent/commands/`가 SSOT이며, 이 문서는 게이트와 상태 체크의 정책 기준만 둔다.

---

## 1. 파이프라인 개요

```
Claude 구현 준비
  │
  ├── Plan Preflight (이슈 계획 작성/보강)
  │
  ├──▶ [Gate 0] plan-review (@plan-reviewer) ── 실패 → Plan Preflight가 이슈 본문 재정비
  │
  ▼
Claude 구현 (worktree 격리)
  │
  ├── 로컬 lint / test
  │
  ├── 로컬 커밋
  │
  ├──▶ [Gate A] /code-review ───────────── 실패 → Claude가 수정 후 재검토
  │
  ├── 브랜치 push
  │
  ├── PR 생성
  │
  ├──▶ [Gate B] ci ─────────────────────── 실패 → Claude 또는 DevOps가 수정
  │
  ├──▶ [Meta] code-reviewer ───────────── 고위험 변경 / 반복 risk class 시 원인 분석 (수동/오케스트레이터 호출)
  │
  ├──▶ [Gate C] merge-gate ────────────── required status checks(§3.2) 통과 + 충돌 없음 + 대화 해결 시 AUTOMERGE_TOKEN(PAT)으로 auto-merge
  │
  ▼
post-merge automation (PR 머지가 발화한 pull_request:closed 이벤트로 트리거)
  ├── 이슈 체크박스 갱신 + close (+ 에픽 동기화·close)
  └── 원격 head branch 삭제 (GitHub 설정)
```

## 2. Gate 상세

### Gate 0 — Plan Review

**목적**: 구현 전 계획을 별도 컨텍스트의 계획 리뷰어가 공격적으로 검토하는 게이트

- **트리거**: Plan Preflight가 `plan-preflight:started` 상태에서 이슈 본문 구현계획 초안을 정리한 시점
- **실행**: 별도 컨텍스트 서브에이전트 `@plan-reviewer`(`.agent/agents/plan-reviewer.md`) 동기 호출
- **결과**: 오케스트레이터가 이슈 코멘트 `Plan Review`로 verdict 기록 (`reviewer:` 필드에 수행 주체; `@plan-reviewer`는 read-only, GitHub 쓰기 없음)
- **성공 시**: Plan Preflight가 이슈 본문 구현계획을 최신화하고 `plan-preflight:done` 라벨로 확정
- **실패 시**: Plan Preflight가 `plan-preflight:started` 상태를 유지한 채 이슈 본문 구현계획을 보강하고 재요청
- **해석 주의**: 이 단계는 구현 세션과 격리된 read-only 계획 리뷰다. 코드 수정, 브랜치 생성, PR 생성은 하지 않는다. verdict 어휘(`approve-implement`/`narrow-scope`/`revise-plan`/`split-issue`/`invoke-human`)와 라벨 상태 기계는 리뷰 주체와 무관하게 유지한다.

이 게이트는 보호 브랜치의 required status check가 아니라, **구현 착수 전 필수 이슈 증적**이다.

### Gate A — 브랜치 리뷰

**목적**: PR 전 코드 품질 게이트

- **트리거**: PR 생성 전 `/implement-issue` 내부 리뷰 루프
- **실행**: Claude Code 빌트인 `/code-review` 스킬 — 현재 브랜치 diff를 default 브랜치(main) 대비 리뷰한다. base 인자를 받지 않으며 effort(예: high) 지정 가능. PR을 요구하는 `code-review` 플러그인과 다르다.
- **결과**: 이슈 코멘트 `브랜치 리뷰` (`reviewer:` 필드에 `/code-review` 기록)
- **성공 시**: 브랜치 push 후 PR 생성
- **실패 시**: Claude가 같은 워크트리에서 수정 후 `/code-review` 재실행
- **반복 실패**: 같은 blocking finding 제목이 반복되면 escalation 신호로 보고, 같은 `risk class`가 2회 반복되면 Meta Review를 우선한다. **반복 실패 임계값은 10회이며, 이 임계값의 SSOT는 본 문서다.** 실패가 10회 누적되면 `blocked:review-loop` 라벨로 자동 브랜치 리뷰를 중단한다.
- **해석 주의**: 이 단계는 GitHub Actions workflow가 아니라 Claude 세션 안에서 돌아가는 read-only 리뷰다. 코드 수정은 Claude 개발 에이전트가 수행한다.

이 게이트는 보호 브랜치의 required status check가 아니며, **PR 생성 전 필수 이슈 증적**이다.
동일 HEAD SHA에서 `/code-review` FAIL이 남아 있으면 PR을 열지 않는다.

PR이 열린 뒤 추가 코드 변경이 발생하면 새 head SHA에서 `/code-review`를 다시 통과시킨 뒤 머지를 진행한다. PR 후 AI 감사 워크플로우는 운영하지 않으며, 추가 검증이 필요하면 사람/오케스트레이터가 수동으로 같은 브랜치 리뷰를 다시 호출한다.

### Gate B — CI

**목적**: 정적 분석 + 자동 테스트

- **트리거**: `pull_request`(사전 게이트) + `push: [main]`(머지 결과물 사후 검증)
- **결과**: status checks `ci`, `lint`, `test` (집계 진입점은 `ci`, defense-in-depth 근거는 [§3.2.1](#321-rationale--머지-안전망-defense-in-depth))
- **release PR 추가 검증**: head branch가 `release/*`이면 Docker image build를 함께 검증한다. 이 단계에서는 registry push를 하지 않는다.
- **main push CI(조합 회귀 사후 검증)**: 목적은 base가 뒤처진 PR들이 각자 green으로 순차 머지될 때 main에 들어온 조합 회귀를 main HEAD의 `lint`·`test` 재실행으로 사후 검출하는 것이다. 이미 머지된 결과물에 대한 run이라 머지를 차단하지 않으며(사전 게이트가 아님), required status checks 집합·의미론은 불변이다. **발화 조건**: 표준 머지 경로는 `pr-approvals.yml`이 **`AUTOMERGE_TOKEN`(PAT)**으로 enable한 auto-merge다(#2437). PAT 머지가 유발한 `push` 이벤트는 `GITHUB_TOKEN`과 달리 GitHub 재귀 방지 규칙에 걸리지 않아 워크플로우를 발화하므로, main push CI는 **전 머지 경로에서 활성화된다**(이전의 GITHUB_TOKEN auto-merge 시절 '미발화' 단서는 #2437 전환으로 해제됨). `push`(`refs/heads/main`)와 `pull_request`(`refs/pull/N/merge`)는 concurrency 그룹 키(`ci-${{ github.ref }}`)가 분리되어 서로 취소하지 않는다.

branch protection repository setting은 이 저장소 밖 운영 설정이므로 워크플로우가 직접 수정하지 않는다.

예시:

```yaml
- PYTHONPATH=$PWD/src .venv/bin/python scripts/check_import_path.py
- PYTHONPATH=$PWD/src .venv/bin/python -m ruff check src/ tests/
- PYTHONPATH=$PWD/src .venv/bin/python -m ruff format --check src/ tests/
- PYTHONPATH=$PWD/src .venv/bin/python -m mypy src/
- PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/unit/ -x -n auto --tb=short -q --cov=src/ante --cov-fail-under=80
- docker build -t ante:release-pr .  # release/* PR only
```

### Meta Review — Claude code-reviewer

**목적**: approve / fail 판정보다 앞서 반복 failure와 구조 리스크를 좁힌다.

- **트리거**:
  - 고위험 변경
  - 같은 `risk class` failure 2회 반복
- **실행 주체**: Claude 오케스트레이터 또는 수동 호출
- **기준**:
  - `.agent/agents/code-reviewer.md`
  - `.agent/skills/lifecycle-review.md`
  - `.agent/skills/contract-drift-review.md`
  - `.agent/skills/generated-artifact-sync.md`
- **원칙**:
  - status check를 하나 더 늘리는 단계가 아니다.
  - 다음 시도 전에 "무엇을 먼저 검증해야 하는가"를 정리하는 단계다.

### Gate C — Merge Gate

**목적**: 머지 가능성만 판단하는 정책 게이트

입력:
- required status checks 통과 — 권장 집합은 [§3.2 저장소 설정 권장값](#32-저장소-설정-권장값)이 SSOT다 (현재 권장: `ci`, `lint`, `test`)
- 충돌 없음
- 대화 해결 완료
- auto-merge 활성화 가능 상태

merge gate는 AI 승인 워커의 출력을 입력으로 삼지 않는다. PR 단계의 자동 AI 승인/감사 워커는 운영하지 않는다.

출력:
- auto-merge 활성화 또는 유지 — **`AUTOMERGE_TOKEN`(fine-grained PAT)으로 enable**한다(#2437; Actions·Dependabot 양쪽 시크릿 저장소에 등록 — §5.2). 머지 actor가 PAT 소유자가 되어 머지가 `pull_request: closed` 이벤트를 정상 발화하고, 그 이벤트가 `post-merge.yml`을 트리거한다.
- **fail-closed**: `AUTOMERGE_TOKEN`이 없으면 merge-gate가 명시 실패해 auto-merge를 걸지 않는다. `GITHUB_TOKEN` 폴백은 금지 — 그 머지는 closed 이벤트를 발화하지 않아 post-merge 정리가 조용히 소실된다(§5.2).
- merge-gate는 `post-merge.yml`을 dispatch하지 않는다(폴링·handoff 제거, #2437). 머지가 만든 closed 이벤트가 정상 트리거 경로이며, 누락 시 `workflow_dispatch(issue_numbers)`로 수동 복구한다(§5.2).
- 머지 불가 시 대기

**원칙**: merge gate는 코드 리뷰어가 아니라 **정책 집행자**다.
코드 품질을 새로 판단하지 않고, CI와 머지 가능성만 집행한다.

### Post-merge 책임 분리

| 작업 | 담당 |
|------|------|
| PR 머지 | GitHub auto-merge |
| head branch 삭제 | GitHub repository setting |
| 이슈 체크박스 갱신 + close | `post-merge.yml` |
| 로컬 worktree 정리 | Claude 구현 머신 |

이슈 close는 PR 본문의 `Closes #N`에 따른 GitHub 기본 auto-close를 우선 사용하고, `post-merge.yml`은 체크박스/에픽 상태 동기화와 누락 복구를 담당한다.

## 3. 워크플로우 구성

목표 워크플로우 구성은 다음과 같다.

```
.github/
└── workflows/
    ├── ci.yml                    # Gate B: lint + test
    ├── pr-approvals.yml          # Gate C: merge-gate (AUTOMERGE_TOKEN PAT로 auto-merge, fail-closed)
    ├── post-merge.yml            # 머지 후 이슈 정리 (pull_request:closed 이벤트 + workflow_dispatch(issue_numbers) 수동 복구)
    ├── semantic-release.yml      # 수동 릴리스
    └── publish.yml               # Release 기반 PyPI/Docker 배포
```

### 3.1 현재 저장소와 목표 상태

- **현재 존재**: `ci.yml`, `pr-approvals.yml`, `post-merge.yml`, `semantic-release.yml`, `publish.yml`
- `pr-approvals.yml`은 과거 PR 단계 자동 AI 승인 워커와 자동 재수정 워커를 포함했으나, 현재는 `merge-gate` 잡만 유지한다. 파일명 변경(`merge-gate.yml`)은 비목표.
- **운영 과제**:
  - 반복 `risk class` 에스컬레이션 자동화 고도화
  - 필요 시 architecture gate 도입

GitHub branch protection에서 required status checks를 사용할 경우, 각 job 이름은 서로 달라야 한다.

### 3.2 저장소 설정 권장값

- `Allow auto-merge`: 활성화
- `Automatically delete head branches`: 활성화
- branch protection required status checks:
  - `ci`
  - `lint`
  - `test`
- `main` 외에 `epic/**` 통합 브랜치도 같은 required status checks(`ci`, `lint`, `test`)를 적용해 base가 epic이어도 세 게이트가 모두 통과하지 않으면 머지되지 않도록 한다.
- `Require conversation resolution before merging`: 활성화 권장

> 권장값은 SSOT다. [03-git-workflow.md §5](03-git-workflow.md#5-보호-규칙-권장값)와 본 절은 같은 required status checks 집합을 가리킨다.

#### 3.2.1 Rationale — 머지 안전망 (defense-in-depth)

`ci`는 `lint`/`test`/`docker-build` 결과를 fail-fast로 집계하는 단일 진입점이다 (`.github/workflows/ci.yml`의 `ci` job, #1896에서 fail-fast 강화 완료). 그럼에도 `lint`, `test`를 required status checks에 함께 등록하는 이유는 다음과 같다.

- **`ci` 게이트 자체 회귀 방어**: `ci` job은 `lint`/`test`/`docker-build` 결과를 집계하는 aggregator이므로, `ci.yml` 로직 변경(예: 새 `needs` 추가 시 검사 누락, 집계 조건 오작성)으로 인해 `ci` job이 의도와 다르게 success 또는 skipped로 종료되는 회귀가 발생할 수 있다. `lint`/`test`를 직접 required로 등록해 두면 aggregator 결함과 무관하게 각 job 결과가 차단 게이트로 직접 노출되어, #1896 fail-fast 강화의 미래 회귀에 대한 안전망이 된다.
- **`needs` chain skip-as-success 회귀 방어**: GitHub Actions는 `needs` 의존성이 실패하면 dependent job을 자동으로 skip 처리하고, branch protection은 skipped required check를 success로 평가한다(#1896이 fix한 정확한 패턴). `ci` 단일 게이트만 required로 두면 이런 skip-as-success 우회가 다시 도입될 때 다시 차단력을 잃지만, `lint`/`test`를 직접 required로 등록하면 `lint`/`test` 결과 자체는 그대로 노출되어 aggregator 우회 경로로도 무결성이 유지된다.
- **`docker-build`는 required에 추가하지 않는다**: 비-release PR에서 `docker-build`는 안내 메시지만 출력하고 빠르게 success로 종료된다(`.github/workflows/ci.yml` 참고). 의미적 차단 게이트가 아니므로 required로 둘 경우 release/* 외 PR에서 불필요한 강제력만 추가된다.

#### 3.2.2 비채택 옵션 (ADR-style)

본 권장값을 확정하면서 다음 두 옵션은 의도적으로 채택하지 않았다.

- **옵션 A — `enforcement_level: everyone` (admin override 차단)**: branch protection enforcement를 `non_admins`에서 `everyone`으로 격상하면 admin도 fail 상태에서 머지할 수 없다. 그러나 Ante는 단독 admin 운영자(저장소 owner) 모델이므로, emergency hot-fix 시 우회 수단이 모두 사라진다. 운영 비용이 안전망 효과보다 크다고 판단해 비채택한다. 향후 운영자가 복수로 늘어나거나, off-hours hot-fix 사고가 누적되면 재검토한다.
- **옵션 C — `pr-approvals.yml` auto-merge 라벨 트리거**: PR open 시점의 무조건 auto-merge enable을 특정 라벨(`ready-to-merge` 등) 기반으로 게이트하는 안. #1896으로 `ci` fail-fast가 차단된 상태에서 추가 효과(marginal benefit)는 작고, `/autopilot` throughput 저하 비용이 크다. 비채택한다.

옵션 A/C가 필요해지는 시점(예: 운영자 증가, autopilot 사고 누적)이 오면 별도 이슈로 재개한다.

#### 3.2.3 실제 적용

본 절의 권장값을 운영 GitHub 저장소에 적용하려면 사용자가 GitHub UI(`Settings → Branches → Branch protection rules`)에서 `main`과 `epic/**`에 대해 required status checks 집합에 `ci`, `lint`, `test`를 등록해야 한다. 저장소 설정 변경은 본 런북의 비목표이며, 실제 적용 여부는 운영자가 결정한다.

### 3.3 검증 환경 체크리스트

- 목표 Python 버전이 저장소 기준과 일치해야 한다. Ante는 CPython 3.13 단일 런타임(`>=3.13,<3.14`)만 공식 지원하며, 검증 환경(러너/로컬)도 동일 버전으로 맞춘다.
- 로컬 개발 런타임도 3.13 단일이다. 저장소 루트 `.python-version`(`3.13`)이 도구 비종속 SSOT이며, `scripts/verify-install.py`가 진입 시 Python 3.13 가드로 drift를 차단한다.
- Python 3.13 free-threaded 빌드와 JIT는 공식 지원 범위 밖이다. 검증 환경에는 표준 CPython 3.13만 사용한다.
- `pytest`, `ruff`, 필요 테스트 의존성이 러너에 설치되어 있어야 한다.
- writable temp dir가 있어야 artifact/summary/result 파일을 안정적으로 생성할 수 있다.
- compose 또는 런타임 설정 검증이 필요한 저장소라면 `config/secrets.env` 같은 필수 입력 파일 가용성을 확인한다.
- 여러 worktree가 하나의 editable install을 공유한다면 `pip show ante`로 editable project location을 확인하고, 필요 시 `PYTHONPATH=$PWD/src` 또는 worktree 기준 재설치를 사용한다.

### 3.4 워크플로우 의존성 유지보수

- **서드파티 액션은 full-length commit SHA로 핀한다(필수)**: 배포·릴리스 권한을 가진 워크플로우(`publish.yml`, `semantic-release.yml`)가 참조하는 서드파티 액션(`pypa/*`, `softprops/*`, `docker/*`)은 이동 가능한 태그 대신 40자 commit SHA로 고정하고 곁 주석(`# vX.Y.Z`)에 릴리스 태그를 남긴다. 태그는 이동 가능해 액션 저장소 탈취 시 임의 코드 실행(supply chain) 위험이 있으므로 서드파티는 SHA 핀을 필수로 한다.
- **공식 `actions/*`는 메이저 태그를 유지한다**: GitHub 소유 액션(`actions/checkout`, `actions/setup-python`, `actions/github-script`)은 SHA 핀 대상이 아니며 메이저 태그로 보안 패치를 받는다. 메이저 업데이트 시 런타임 노드 버전·breaking change를 릴리스 노트로 확인한 뒤 적용한다.
- `.github/dependabot.yml`의 `github-actions` ecosystem(주간)이 SHA 핀·태그 갱신 PR을 자동 생성해 유지비를 낮춘다. 곁 주석 semver가 dependabot의 추적 기준이다.
- `actions/checkout`, `actions/upload-artifact`, `actions/download-artifact` 등 GitHub-hosted action의 런타임 deprecation 공지는 정기적으로 점검한다.
- Node 런타임 deprecation warning은 저장소 Python 코드 실패와 분리해서 추적한다.

### 3.5 Legacy 정리 후보

- 저장소 변수 `AI_REVIEW_ENABLED`는 더 이상 어떤 워크플로우에서도 참조하지 않는다. repo owner가 수동으로 삭제할 수 있으나, 본 SSOT는 변수 존재 여부에 의존하지 않는다.
- self-hosted runner label `claude-review`와 과거 외부 리뷰용 러너 라벨은 PR 단계 워크플로우에서 더 이상 필요하지 않다. 폐기 여부는 본 SSOT 범위 밖이다.

## 4. 로컬 개발 시 사전 검증

```bash
PYTHONPATH=$PWD/src .venv/bin/python scripts/check_import_path.py
PYTHONPATH=$PWD/src .venv/bin/python -m ruff check src/ tests/
PYTHONPATH=$PWD/src .venv/bin/python -m ruff format src/ tests/
PYTHONPATH=$PWD/src .venv/bin/python -m mypy src/ante/
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/unit/ -v
```

내부 브랜치 리뷰(`/code-review`) 전 이 검증을 통과시켜야 사전 리뷰 루프가 짧아진다.

## 5. CI/머지 게이트 실패 시 복구

이 섹션은 CI, 브랜치 리뷰, post-merge 복구 정책의 SSOT다.
실제 명령 실행과 GitHub 코멘트 절차는 `.agent/skills/github-ops.md`를 따르고,
구현 전 브랜치 리뷰 실행 루프는 `.agent/commands/implement-issue.md`와 [03-git-workflow.md](03-git-workflow.md)를 따른다.

| 실패 게이트 | 성격 | 머지 차단 여부 | 주 원인 | 복구 담당 |
|------------|-----|---------------|--------|----------|
| `/code-review` | PR 전 사전 게이트 | PR 생성 차단 (이슈 증적) | 설계/코드 품질 문제 | Claude 개발 에이전트 |
| `ci` / `lint` / `test` | required status checks (집합은 [§3.2](#32-저장소-설정-권장값) SSOT) | 차단 | lint/test/type/CI 설정 | Claude 개발 에이전트 또는 `@devops` |
| `merge-gate` | 정책 집행 | 차단 | 충돌, 대화 미해결, auto-merge 비활성화 상태 | Claude 오케스트레이터 또는 사람 |

내부 `/code-review` 브랜치 리뷰는 실패 이력을 이슈 코멘트에 누적하고, 같은 blocking finding 제목이 반복되면 escalation 신호를 남긴다. 실패가 10회(임계값 SSOT는 §2 Gate A) 누적되면 `blocked:review-loop` 라벨을 붙이고 더 이상의 자동 브랜치 리뷰를 중단한다.

`lifecycle`, `contract-drift`, `generated-artifact-sync` 같은 구조 리스크가 2회 반복되면 Meta Review를 먼저 수행한다.

### 5.1 머지 게이트 수동 복구 순서

1. required status check(`ci` / `lint` / `test` 등 [§3.2](#32-저장소-설정-권장값) 권장 집합) 중 하나가 일시적 환경 문제로 실패한 것으로 보이면 `gh run rerun`을 우선한다.
2. PR 코드 자체에 문제가 있으면 Claude 개발 에이전트가 같은 브랜치를 수정한 뒤 새 커밋을 push한다. push 전에는 `/code-review`를 새 head SHA에서 다시 통과시킨다.
3. `pull_request` 이벤트 누락으로 `merge-gate`가 다시 시작되지 않을 때만 PR `close → reopen`을 예외적으로 사용한다.
4. 수동 복구를 실행한 경우 PR 코멘트에 복구 이유, 사용한 방식, 새 run 링크를 남긴다.

### 5.2 Post-merge 실패 모드와 복구

`post-merge.yml`은 PR 머지가 만든 `pull_request: closed`(`merged == true`) 이벤트로 트리거된다(#2437 — 폴링·handoff 제거). 이 이벤트는 auto-merge를 **`AUTOMERGE_TOKEN`(PAT)**으로 enable했기에 발화한다(머지 actor = PAT 소유자).

같은 재귀 방지 규칙이 **릴리스 → publish 경로**에도 그대로 작용하며(`GITHUB_TOKEN`이 만든 GitHub Release가 `publish.yml`을 트리거하지 않음, #2449), 거기서도 `AUTOMERGE_TOKEN`이 같은 역할을 한다 — [§7.1](#71-릴리스--publish-트리거는-pat에-의존한다-2449). 아래 등록 규칙은 두 경로 공통이지만, **Dependabot 이중 등록 요구는 머지 경로에만 해당**한다(릴리스 경로 비대칭은 §7.1 참조).

**`AUTOMERGE_TOKEN`은 Actions·Dependabot 두 시크릿 저장소에 모두 등록한다.** GitHub는 `dependabot[bot]`이 트리거한 run의 `secrets` 컨텍스트를 **Dependabot secrets** 저장소로 해석한다(Actions secrets가 아님). Actions에만 등록하면 **dependabot PR**이, Dependabot에만 등록하면 **일반 PR**이 각각 빈 토큰으로 상시 fail-closed된다(아래 실패 모드 참조). `Settings → Secrets and variables → Actions`와 `→ Dependabot` 양쪽에 같은 PAT를 등록한다.

- 알려진 실패 모드:
  - **`AUTOMERGE_TOKEN` 미등록(Actions)**: 일반 PR의 merge-gate가 fail-closed로 명시 실패한다(가시적 미머지).
  - **`AUTOMERGE_TOKEN` 미등록(Dependabot)**: **dependabot PR에서만** merge-gate가 fail-closed된다 — 일반 PR은 정상인데 dependabot PR만 auto-merge가 안 걸리면 Dependabot 저장소 등록 누락이 원인이다.
  - 어느 경우든 `GITHUB_TOKEN`으로 우회 머지하지 않는다 — `GITHUB_TOKEN` 머지는 재귀 방지 규칙으로 `closed` 이벤트를 발화하지 않아, 폴링이 제거된 지금은 정리가 조용히 소실된다(이슈는 네이티브 auto-close로 닫혀 정상처럼 보이는 위장된 누락).
  - **closed 이벤트 정리 누락**: GitHub 기본 auto-close는 됐으나 체크박스/에픽 동기화가 누락된 경우(이벤트 유실 등). 아래 수동 복구를 쓴다.
- 복구 순서:
  1. **`AUTOMERGE_TOKEN` 미등록이면** PAT(Contents RW + Pull requests RW)를 Actions·Dependabot 양쪽 시크릿에 등록한 뒤 PR을 재트리거(close→reopen)해 정상 경로로 머지·정리한다. dependabot PR에서만 실패했다면 Dependabot 저장소 등록을 확인한다.
  2. **정리만 누락됐으면** `post-merge.yml`을 `workflow_dispatch`로 수동 실행하되 **`issue_numbers`에 대상 이슈 번호를 콤마로 넣는다**. 머지된 PR은 재오픈이 불가해 closed 이벤트를 재발화할 수 없으므로 이것이 유일한 재실행 경로다. `pr_number`/폴링 기반 dispatch는 #2437로 제거됐다.
  3. 이슈 또는 PR 코멘트에 복구 run 링크와 최종 상태를 남긴다.

**멱등성**: 이슈 상태·체크박스·에픽 동기화는 멱등이라 중복 실행이 안전하다(이미 `[x]`/closed면 무해 — 원본 보존 원칙). 단 수동 복구(`issue_numbers`) 경로는 `pr` 컨텍스트가 없어 post-merge 코멘트의 중복 판정 needle이 `- PR: n-a`인데 closed run이 남긴 코멘트는 `- PR: #N`이라 서로 매치되지 않는다 — 이미 closed run이 정리한 이슈에 수동 복구를 돌리면 `정리 완료` 코멘트가 **중복 게시**될 수 있다(무해). 중복을 피하려면 아직 정리되지 않은 이슈 번호만 지정한다.

## 6. 설계 적합성 검증 (선택 Gate)

모듈 간 import 방향과 순환 의존을 기계적으로 검사하는 Gate는 계속 도입 후보로 둔다.

예상 파일:

```yaml
# .github/workflows/architecture.yml
- 모듈 간 import 규칙 검증
- 금지된 직접 의존 검사
```

도입 시에는 `ci`에 병합하거나 별도 required status check로 분리한다.

## 7. 릴리스 연계

릴리스는 여전히 **수동 실행**만 허용한다.
실행 절차의 SSOT는 `.agent/commands/release.md`다.
`publish.yml`의 수동 `workflow_dispatch`는 build-only 검증이며, 실제 PyPI/Docker 배포는 GitHub Release `published` 이벤트에서만 수행한다.

```
PR auto-merge
  │
  ▼
main 누적
  │
  ▼
/release prepare
  │
  ▼
release PR
  │
  ▼
release PR merge
  │
  ▼
/release publish
  │
  ▼
semantic-release.yml
  │
  ▼
publish.yml
  ├── PyPI
  └── GHCR Docker image
```

main에 머지되었다고 자동 릴리스되지는 않는다.
release PR에서는 Docker build 검증만 수행하고, registry push는 GitHub Release가 published 된 뒤 `publish.yml`에서만 수행한다.

**릴리스 워크플로우 concurrency 비대칭(#2428)**: `semantic-release.yml`에는 정적 concurrency 그룹을 두어 이중 dispatch 시 동시 태그/버전 계산 경합을 막는다. 입력이 동일한 dispatch 간에는 취소돼도 다음 run이 같은 계산을 하므로 무해하다. 단 입력이 다른 dispatch(예: `semantic-release.yml`의 `declare_major` 선언 릴리스, #2417)가 pending 중 무음 취소되면 그 선언이 소실될 수 있으므로, `declare_major` dispatch는 다른 release run이 없는 상태에서만 실행한다. `publish.yml`에는 concurrency를 **두지 않는다** — concurrency 그룹은 pending run을 최대 1개만 유지하고 새 run이 큐잉되면 기존 pending run을 무음 취소하므로, run이 겹치면(실행 1 + pending 1 상태에서 세 번째 트리거) pending 중이던 릴리스의 run이 새 run으로 대체·무음 취소되어 해당 릴리스의 PyPI/GHCR 배포가 누락된다. 이는 막으려던 `:latest` push 경합(희귀)보다 나쁜 실패 모드다. 릴리스는 수동·순차라 겹침 자체가 실질적으로 없어 직렬화 이득도 없다.

### 7.1 릴리스 → publish 트리거는 PAT에 의존한다 (#2449)

위 흐름도의 `semantic-release.yml → publish.yml` 화살표는 **자동으로 이어지지 않는다.** `GITHUB_TOKEN`이 만든 이벤트가 다른 워크플로우를 트리거하지 않는 GitHub 기본 동작(무한 재귀 방지) 때문에, 기본 토큰으로 만든 GitHub Release는 `publish.yml`의 `on: release(published)`를 발화시키지 못한다. 그러면 `semantic-release.yml`은 `success`인데 PyPI·GHCR 배포만 통째로 빠진 **조용한 누락**이 된다(v0.11.0·v0.12.0 2회 연속 실측).

이는 [§5.2](#52-post-merge-실패-모드와-복구)가 이미 다루는 것과 **동일한 결함 클래스**다. `post-merge.yml`은 `GITHUB_TOKEN` 머지가 `pull_request: closed`를 발화시키지 않는 문제를 `AUTOMERGE_TOKEN`(PAT)으로 머지 actor를 실사용자로 바꿔 해소했고(#2437), 릴리스 경로도 같은 처방을 쓴다.

- **`AUTOMERGE_TOKEN`의 용도는 두 가지다**: (i) auto-merge enable(`pr-approvals.yml`, §5.2) — 머지가 `closed` 이벤트를 발화시키기 위해, (ii) **GitHub Release 생성(`semantic-release.yml`) — 릴리스가 `published` 이벤트를 발화시키기 위해**. 이름은 머지 유래지만 두 용도의 목적은 같다: **GitHub 이벤트를 실사용자 주체로 발화시켜 후속 워크플로우를 잇는 것**. 필요 권한은 §5.2의 발급 권장치(`Contents RW` + `Pull requests RW`)가 그대로 커버한다(릴리스 생성은 `Contents: Read and write`).
- **Dependabot 이중 등록은 릴리스 경로에 적용되지 않는다(비대칭)**: §5.2의 "Actions·Dependabot 양쪽 등록" 요구는 `dependabot[bot]`이 트리거한 run이 Dependabot secrets 저장소만 읽기 때문이다. `semantic-release.yml`은 **사람이 수동 `workflow_dispatch`로만 실행**하므로 `dependabot[bot]` 컨텍스트로 돌 일이 없고, **Actions 저장소 등록만으로 충분**하다. 양쪽 등록 요구는 여전히 머지 경로(§5.2) 때문에 유효하니 등록을 줄이지 않는다.
- **3중 방어**: 시크릿 부재 → `semantic-release.yml` 첫 스텝의 fail-closed 가드가 릴리스 생성 이전에 중단(액션의 `token` 입력은 빈 문자열을 "미설정"으로 보고 `GITHUB_TOKEN`에 조용히 폴백하므로 이 가드가 없으면 결함이 그대로 재현된다) / 권한 부족·만료 → 릴리스 생성 401·403(**고아 태그**) / 그 외 모든 원인 → 릴리스 직후 `Verify publish.yml was triggered` 자기검증 스텝이 `event=release` + 태그 커밋 `headSha` + baseline 초과 run id **3조건 AND**로 발화를 확인하고, 2분 폴링 후에도 없으면 run을 실패시킨다.
- 실패 시 복구(draft 토글)와 **`semantic-release.yml` rerun·재dispatch 금지 사유**는 [06-release.md §11](06-release.md#11-트러블슈팅)의 「`publish.yml` 미트리거」·「고아 태그」가 SSOT다. 그 금지는 `semantic-release.yml` 한정이며, `publish.yml` 실패에는 §5.1·`github-ops.md`의 rerun-우선 원칙이 그대로 적용된다.
