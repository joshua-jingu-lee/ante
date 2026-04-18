# 04. CI/CD 파이프라인

> GitHub Actions 기반 CI/CD와 리뷰 게이트 모델을 정의한다.

---

## 1. 파이프라인 개요

```
Claude 구현 (worktree 격리)
  │
  ├── 로컬 lint / test
  │
  ├── 브랜치 push
  │
  ├──▶ [Gate A] codex-branch-review ────── 실패 → Claude가 수정 후 재push
  │
  ├── PR 생성
  │
  ├──▶ [Gate B] ci ─────────────────────── 실패 → Claude 또는 DevOps가 수정
  │
  ├──▶ [Gate C] claude-pr-approve ─────── content 실패 → Claude 자동 재수정
  │
  ├──▶ [Gate D] codex-pr-approve ──────── content 실패 → Claude 자동 재수정
  │
  ├──▶ [Loop] Claude PR repair ────────── 최대 3회, quota/script/auth/infra는 제외
  │
  ├──▶ [Gate E] merge-gate ────────────── 모든 게이트 성공 시 auto-merge
  │
  ▼
post-merge automation
  ├── 이슈 체크박스 갱신 + close
  └── 원격 head branch 삭제 (GitHub 설정)
```

## 2. Gate 상세

### Gate A — Codex 브랜치 리뷰

**목적**: PR 전 브랜치 품질 게이트

- **트리거**: feature/fix/refactor/docs/epic 브랜치 push
- **결과**: `codex-branch-review`
- **실패 시**: Claude가 같은 브랜치에서 수정 후 재push

이 게이트는 보호 브랜치의 required status check는 아니지만, **PR 생성 전 필수 조건**이다.

### Gate B — CI

**목적**: 정적 분석 + 자동 테스트

- **트리거**: `pull_request`
- **결과**: `ci`

예시:

```yaml
- ruff check src/ tests/
- ruff format --check src/ tests/
- mypy src/
- pytest tests/unit/ -x -n auto --tb=short -q --cov=src/ante --cov-fail-under=80
```

### Gate C — Claude PR 승인

**목적**: PR head SHA 기준 계약/스펙/테스트 최종 확인

- **트리거**: `pull_request` opened / synchronize / ready_for_review
- **결과**: `claude-pr-approve`
- **기준**: `.agent/skills/review-pr.md`
- **후속 처리**:
  - `content` FAIL → Claude 자동 재수정 루프
  - `quota/script_error/auth_error/infra_error` → 재수정 없이 PR 코멘트로 중단 사유 기록

### Gate D — Codex PR 승인

**목적**: PR head SHA 기준 독립 교차검증

- **트리거**: `pull_request` opened / synchronize / ready_for_review
- **결과**: `codex-pr-approve`
- **기준**: `.agent/skills/review-pr.md`
- **후속 처리**:
  - `content` FAIL → Claude 자동 재수정 루프
  - `quota/script_error/auth_error/infra_error` → 재수정 없이 PR 코멘트로 중단 사유 기록

### Claude PR 재수정 루프

**목적**: PR 승인에서 발견된 실제 blocking finding을 같은 PR 브랜치에서 빠르게 해소

- **트리거**: `claude-pr-approve` 또는 `codex-pr-approve`의 `content` FAIL
- **실행 주체**: Claude self-hosted runner
- **예산**: 최대 3회
- **비포함 실패**: `quota`, `script_error`, `auth_error`, `infra_error`
- **결과**:
  - 새 커밋 push → `pull_request synchronize`로 Gate B/C/D 재실행
  - 3회 초과 → `blocked:pr-review-loop`

### Gate E — Merge Gate

**목적**: 머지 가능성만 판단하는 정책 게이트

입력:
- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 충돌 여부
- 대화 해결 여부

출력:
- auto-merge 활성화 또는 유지
- 머지 불가 시 대기

**원칙**: merge gate는 세 번째 코드 리뷰어가 아니라 **정책 집행자**다.

## 3. 워크플로우 구성

목표 워크플로우 구성은 다음과 같다.

```
.github/
└── workflows/
    ├── ci.yml                    # Gate B: lint + test
    ├── codex-branch-review.yml   # Gate A: PR 전 Codex 브랜치 리뷰
    ├── pr-approvals.yml          # Gate C/D: Claude + Codex PR 승인
    ├── post-merge.yml            # 머지 후 이슈 정리, 후처리
    ├── semantic-release.yml      # 수동 릴리스
    └── publish.yml               # Release 기반 배포
```

### 3.1 현재 저장소와 목표 상태

- **현재 존재**: `ci.yml`, `semantic-release.yml`, `publish.yml`
- **추가 필요**: `codex-branch-review.yml`, `pr-approvals.yml`, `post-merge.yml`

GitHub branch protection에서 required status checks를 사용할 경우, 각 job 이름은 서로 달라야 한다.

### 3.2 AI 리뷰 러너 전제

- `codex-branch-review`, `codex-pr-approve`는 self-hosted runner label `codex-review`를 전제로 한다.
- `claude-pr-approve`는 self-hosted runner label `claude-review`를 전제로 한다.
- 저장소 변수 `AI_REVIEW_ENABLED=true`일 때만 AI 리뷰 workflow를 활성화한다.
- runner가 준비되기 전에는 `AI_REVIEW_ENABLED`를 비워 두거나 `false`로 유지한다.

## 4. 로컬 개발 시 사전 검증

```bash
ruff check src/ tests/
ruff format src/ tests/
mypy src/ante/
pytest tests/unit/ -v
```

브랜치 push 전 이 검증을 통과시켜야 Codex 사전 리뷰 루프가 짧아진다.

## 5. CI 실패 시 복구

> 상세 복구 정책: [01-development-process.md §5](01-development-process.md#5-실패-복구-루프)

| 실패 게이트 | 주 원인 | 복구 담당 |
|------------|--------|----------|
| `codex-branch-review` | 설계/코드 품질 문제 | Claude 개발 에이전트 |
| `ci` | lint/test/type/CI 설정 | Claude 개발 에이전트 또는 `@devops` |
| `claude-pr-approve` | 스펙/계약/테스트 누락 | Claude 자동 재수정 워커 또는 `@devops` |
| `codex-pr-approve` | 버그/회귀/설계 위반 | Claude 자동 재수정 워커 또는 `@devops` |

`codex-branch-review`는 실패 이력을 이슈 코멘트에 누적하고, 같은 blocking finding 제목이 반복되면 escalation 신호를 남긴다. 실패가 5회 누적되면 `blocked:review-loop` 라벨을 붙이고 더 이상의 자동 브랜치 리뷰를 중단한다.
`claude-pr-approve` / `codex-pr-approve`는 `content` FAIL일 때만 Claude 자동 재수정을 최대 3회 시도한다. `quota`, `script_error`, `auth_error`, `infra_error`는 자동 재수정을 건너뛰고 PR 코멘트에 원인을 남긴다.

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

릴리스는 여전히 **수동 dispatch**만 허용한다.

```
PR auto-merge
  │
  ▼
main 누적
  │
  ▼
/release 또는 workflow_dispatch
  │
  ▼
semantic-release.yml
  │
  ▼
publish.yml
```

main에 머지되었다고 자동 릴리스되지는 않는다.
