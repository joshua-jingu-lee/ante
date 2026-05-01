# 04. CI/CD와 리뷰 게이트

> GitHub Actions 기반 CI/CD와 내부 Codex 브랜치 리뷰, merge gate 정책을 정의한다.
> 에이전트의 실제 실행 절차는 `.agent/commands/`가 SSOT이며, 이 문서는 게이트와 상태 체크의 정책 기준만 둔다.

---

## 1. 파이프라인 개요

```
Claude 구현 준비
  │
  ├── Plan Preflight (이슈 계획 작성/보강)
  │
  ├──▶ [Gate 0] codex-plan-review ─────── 실패 → Plan Preflight가 이슈 본문 재정비
  │
  ▼
Claude 구현 (worktree 격리)
  │
  ├── 로컬 lint / test
  │
  ├── 로컬 커밋
  │
  ├──▶ [Gate A] /codex:review --base ───── 실패 → Claude가 수정 후 재검토
  │
  ├── 브랜치 push
  │
  ├── PR 생성
  │
  ├──▶ [Gate B] ci ─────────────────────── 실패 → Claude 또는 DevOps가 수정
  │
  ├──▶ [Meta] code-reviewer ───────────── 고위험 변경 / 반복 risk class 시 원인 분석 (수동/오케스트레이터 호출)
  │
  ├──▶ [Gate C] merge-gate ────────────── ci 통과 + 충돌 없음 + 대화 해결 시 auto-merge
  │
  ▼
post-merge automation
  ├── 이슈 체크박스 갱신 + close
  └── 원격 head branch 삭제 (GitHub 설정)
```

## 2. Gate 상세

### Gate 0 — Codex Plan Review

**목적**: 구현 전 계획을 외부 Codex가 공격적으로 검토하는 게이트

- **트리거**: Plan Preflight가 `plan-preflight:started` 상태에서 이슈 본문 구현계획 초안을 정리한 시점
- **실행**: `openai/codex-plugin-cc`의 `/codex:adversarial-review`
- **결과**: 이슈 코멘트 `codex-plan-review`
- **성공 시**: Plan Preflight가 이슈 본문 구현계획을 최신화하고 `plan-preflight:done` 라벨로 확정
- **실패 시**: Plan Preflight가 `plan-preflight:started` 상태를 유지한 채 이슈 본문 구현계획을 보강하고 재요청
- **해석 주의**: 이 단계는 Claude 내부 계획 검토가 아니라 외부 read-only Codex 리뷰다. 코드 수정, 브랜치 생성, PR 생성은 하지 않는다.

이 게이트는 보호 브랜치의 required status check가 아니라, **구현 착수 전 필수 이슈 증적**이다.

### Gate A — Codex 브랜치 리뷰

**목적**: PR 전 코드 품질 게이트

- **트리거**: PR 생성 전 `/implement-issue` 내부 리뷰 루프
- **실행**: `openai/codex-plugin-cc`의 `/codex:review --base <main 또는 epic/...>`
- **결과**: 이슈 코멘트 `Codex 브랜치 리뷰`
- **성공 시**: 브랜치 push 후 PR 생성
- **실패 시**: Claude가 같은 워크트리에서 수정 후 `/codex:review --base <base>` 재실행
- **반복 실패**: 같은 blocking finding 제목이 반복되면 escalation 신호로 보고, 같은 `risk class`가 2회 반복되면 Meta Review를 우선한다.
- **해석 주의**: 이 단계는 GitHub Actions workflow가 아니라 Claude 세션 안에서 돌아가는 read-only Codex 리뷰다. 코드 수정은 Claude 개발 에이전트가 수행한다.

이 게이트는 보호 브랜치의 required status check가 아니며, **PR 생성 전 필수 이슈 증적**이다.
동일 HEAD SHA에서 `/codex:review` FAIL이 남아 있으면 PR을 열지 않는다.

PR이 열린 뒤 추가 코드 변경이 발생하면 새 head SHA에서 `/codex:review --base <ref>`를 다시 통과시킨 뒤 머지를 진행한다. PR 후 AI 감사 워크플로우는 운영하지 않으며, 추가 검증이 필요하면 사람/오케스트레이터가 수동으로 같은 브랜치 리뷰를 다시 호출한다.

### Gate B — CI

**목적**: 정적 분석 + 자동 테스트

- **트리거**: `pull_request`
- **결과**: `ci`
- **release PR 추가 검증**: head branch가 `release/*`이면 Docker image build를 함께 검증한다. 이 단계에서는 registry push를 하지 않는다.

예시:

```yaml
- ruff check src/ tests/
- ruff format --check src/ tests/
- mypy src/
- pytest tests/unit/ -x -n auto --tb=short -q --cov=src/ante --cov-fail-under=80
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
- `ci` (required)
- 충돌 없음
- 대화 해결 완료
- auto-merge 활성화 가능 상태

merge gate는 AI 승인 워커의 출력을 입력으로 삼지 않는다. PR 단계의 자동 AI 승인/감사 워커는 운영하지 않는다.

출력:
- auto-merge 활성화 또는 유지
- auto-merge 활성화 전에 PR head ref 기준 `workflow_dispatch`로 `post-merge.yml` 호출
- `post-merge.yml`은 별도 workflow run 안에서 PR의 실제 merged 상태를 기다린 뒤 후처리를 수행하고, 장기 대기 시 handoff 직전에 PR 상태를 다시 확인한 뒤 자기 자신을 다시 dispatch해 대기를 넘겨받는다
- 장기 대기 handoff에는 고정 횟수 제한을 두지 않고 merged 상태까지 자동 경로를 유지한다
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
    ├── pr-approvals.yml          # Gate C: merge-gate (auto-merge + post-merge dispatch)
    ├── post-merge.yml            # 머지 후 이슈 정리, 후처리 (closed event + workflow_dispatch)
    ├── semantic-release.yml      # 수동 릴리스
    └── publish.yml               # Release 기반 PyPI/Docker 배포
```

### 3.1 현재 저장소와 목표 상태

- **현재 존재**: `ci.yml`, `pr-approvals.yml`, `post-merge.yml`, `semantic-release.yml`, `publish.yml`
- `pr-approvals.yml`은 과거 PR 단계 Claude/Codex 승인 워커와 자동 재수정 워커를 포함했으나, 현재는 `merge-gate` 잡만 유지한다. 파일명 변경(`merge-gate.yml`)은 비목표.
- **운영 과제**:
  - 반복 `risk class` 에스컬레이션 자동화 고도화
  - 필요 시 architecture gate 도입

GitHub branch protection에서 required status checks를 사용할 경우, 각 job 이름은 서로 달라야 한다.

### 3.2 저장소 설정 권장값

- `Allow auto-merge`: 활성화
- `Automatically delete head branches`: 활성화
- branch protection required status checks:
  - `ci`
- `main` 외에 `epic/**` 통합 브랜치도 같은 required status checks(`ci`)를 적용해 base가 epic이어도 ci 통과 없이는 머지되지 않도록 한다.
- `Require conversation resolution before merging`: 활성화 권장

### 3.3 검증 환경 체크리스트

- 목표 Python 버전이 저장소 기준과 일치해야 한다. Ante는 CPython 3.13 단일 런타임(`>=3.13,<3.14`)만 공식 지원하며, 검증 환경(러너/로컬)도 동일 버전으로 맞춘다.
- Python 3.13 free-threaded 빌드와 JIT는 공식 지원 범위 밖이다. 검증 환경에는 표준 CPython 3.13만 사용한다.
- `pytest`, `ruff`, 필요 테스트 의존성이 러너에 설치되어 있어야 한다.
- writable temp dir가 있어야 artifact/summary/result 파일을 안정적으로 생성할 수 있다.
- compose 또는 런타임 설정 검증이 필요한 저장소라면 `config/secrets.env` 같은 필수 입력 파일 가용성을 확인한다.
- 여러 worktree가 하나의 editable install을 공유한다면 `pip show ante`로 editable project location을 확인하고, 필요 시 `PYTHONPATH=$PWD/src` 또는 worktree 기준 재설치를 사용한다.

### 3.4 워크플로우 의존성 유지보수

- `actions/checkout`, `actions/upload-artifact`, `actions/download-artifact` 등 GitHub-hosted action의 런타임 deprecation 공지는 정기적으로 점검한다.
- Node 런타임 deprecation warning은 저장소 Python 코드 실패와 분리해서 추적한다.

### 3.5 Legacy 정리 후보

- 저장소 변수 `AI_REVIEW_ENABLED`는 더 이상 어떤 워크플로우에서도 참조하지 않는다. repo owner가 수동으로 삭제할 수 있으나, 본 SSOT는 변수 존재 여부에 의존하지 않는다.
- self-hosted runner label `claude-review`, `codex-review`는 PR 단계 워크플로우에서 더 이상 필요하지 않다. 폐기 여부는 본 SSOT 범위 밖이다.

## 4. 로컬 개발 시 사전 검증

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/ante/
pytest tests/unit/ -v
```

내부 Codex 브랜치 리뷰 전 이 검증을 통과시켜야 사전 리뷰 루프가 짧아진다.

## 5. CI/머지 게이트 실패 시 복구

이 섹션은 CI, 브랜치 리뷰, post-merge 복구 정책의 SSOT다.
실제 명령 실행과 GitHub 코멘트 절차는 `.agent/skills/github-ops.md`를 따르고,
구현 전 브랜치 리뷰 실행 루프는 `.agent/commands/implement-issue.md`와 [03-git-workflow.md](03-git-workflow.md)를 따른다.

| 실패 게이트 | 성격 | 머지 차단 여부 | 주 원인 | 복구 담당 |
|------------|-----|---------------|--------|----------|
| `/codex:review` | PR 전 사전 게이트 | PR 생성 차단 (이슈 증적) | 설계/코드 품질 문제 | Claude 개발 에이전트 |
| `ci` | required | 차단 | lint/test/type/CI 설정 | Claude 개발 에이전트 또는 `@devops` |
| `merge-gate` | 정책 집행 | 차단 | 충돌, 대화 미해결, auto-merge 비활성화 상태 | Claude 오케스트레이터 또는 사람 |

내부 `/codex:review` 브랜치 리뷰는 실패 이력을 이슈 코멘트에 누적하고, 같은 blocking finding 제목이 반복되면 escalation 신호를 남긴다. 실패가 10회 누적되면 `blocked:review-loop` 라벨을 붙이고 더 이상의 자동 브랜치 리뷰를 중단한다.

`lifecycle`, `contract-drift`, `generated-artifact-sync` 같은 구조 리스크가 2회 반복되면 Meta Review를 먼저 수행한다.

### 5.1 머지 게이트 수동 복구 순서

1. `ci`가 일시적 환경 문제로 실패한 것으로 보이면 `gh run rerun`을 우선한다.
2. PR 코드 자체에 문제가 있으면 Claude 개발 에이전트가 같은 브랜치를 수정한 뒤 새 커밋을 push한다. push 전에는 `/codex:review --base <ref>`를 새 head SHA에서 다시 통과시킨다.
3. `pull_request` 이벤트 누락으로 `merge-gate`가 다시 시작되지 않을 때만 PR `close → reopen`을 예외적으로 사용한다.
4. 수동 복구를 실행한 경우 PR 코멘트에 복구 이유, 사용한 방식, 새 run 링크를 남긴다.

### 5.2 Post-merge 실패 모드와 복구

- 알려진 실패 모드:
  - GitHub Actions의 `GITHUB_TOKEN`으로 수행한 auto-merge는 후속 workflow run을 자동으로 만들지 않아 `pull_request.closed` 후처리가 누락될 수 있음
  - `workflow_dispatch`를 default branch 기준으로 실행하면, 머지 전에는 최신 PR 브랜치의 `post-merge.yml` 변경이 반영되지 않음
  - `workflow_dispatch`를 auto-merge 뒤에 호출하면, head branch 자동 삭제와 경쟁해 PR head ref를 찾지 못할 수 있음
  - merge actor나 이벤트 경로 차이로 `pull_request.closed` 후처리가 기대대로 실행되지 않음
  - auto-merge 전에 별도 `post-merge` run을 시작해도, 실제 merged 상태가 늦게 반영될 수 있어 workflow 내부 대기와 handoff 재-dispatch가 필요함
  - `workflow_dispatch` 입력 파싱 실패
  - GitHub 기본 auto-close는 되었지만 체크박스/에픽 동기화가 누락됨
- 복구 순서:
  1. `post-merge`를 PR 번호 기준으로 수동 실행
  2. 필요 시 이슈 번호 기준 reconciliation/close 수행
  3. 이슈 또는 PR 코멘트에 복구 run 링크와 최종 상태를 남김

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
