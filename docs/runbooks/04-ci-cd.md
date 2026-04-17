# 04. CI/CD 파이프라인

> GitHub Actions 기반 CI/CD 모델을 정의한다.

---

## 1. 파이프라인 개요

```
에이전트 코드 작성 (worktree 격리)
  │
  ▼
PR 생성 (feat/* → main, 또는 feat/* → epic/*)
  │
  ├──▶ [Gate 1] 정적 분석 + 린트 ────── 실패 → 에이전트가 수정
  │
  ├──▶ [Gate 2] 자동 테스트 실행 ────── 실패 → 에이전트가 수정
  │
  ├──▶ [Gate 3] 설계 적합성 검증 ────── 실패 → 에이전트가 수정 (미구현)
  │
  ├──▶ [Gate 4] @code-reviewer ────── REQUEST_CHANGES → 수정 루프 (최대 2회)
  │
  ▼
main 머지 (squash merge)
  │
  ▼ (/release 수동 실행 시)
semantic-release → 버전 범프 → GitHub Release
  │
  ▼ (자동 트리거)
publish.yml → 프론트엔드 빌드 → PyPI 배포
  │
  ▼
홈서버에서 ante update
```

## 2. Gate 상세

### Gate 1 — 정적 분석 + 린트

**트리거**: PR 생성/업데이트 시

```yaml
# .github/workflows/lint.yml
- ruff check src/ tests/        # 린트
- ruff format --check src/      # 포맷 검사
- mypy src/ante/                 # 타입 검사
```

### Gate 2 — 자동 테스트 실행

**트리거**: Gate 1 통과 후

```yaml
# .github/workflows/test.yml
- pytest tests/unit/ -v --cov=src/ante --cov-report=term-missing
- pytest tests/integration/ -v   # 통합 테스트 (있는 경우)
```

**기준**:
- 모든 테스트 통과
- 커버리지 기준: 신규 코드 80% 이상 (점진적으로 상향)

### Gate 3 — 설계 적합성 검증 (Phase 2 도입 예정)

모듈 간 import 방향과 순환 의존을 기계적으로 검사한다. `/review-pr`의 D2(사이드이펙트)가 수동으로 커버하고 있으나, 모듈 수가 늘어나면 자동 검사가 필요해진다.

**도입 시점**: 모듈 수 20개 이상 또는 순환 의존 사고 발생 시

```yaml
# .github/workflows/architecture.yml
- 모듈 간 import 규칙 검증 (순환 의존 감지)
- 금지된 직접 의존 검사
```

### Gate 4 — 체크리스트 기반 코드 리뷰

`@code-reviewer` 에이전트가 구조화된 체크리스트 기반 코드 리뷰를 수행한다. 리뷰어는 **판정만** 수행하고, 수정 루프는 오케스트레이터가 조율한다.

**실행 방식**: `/implement-issue` 10단계에서 `@code-reviewer`에 자동 위임, 또는 `/review-pr #{PR번호}`로 수동 실행

**검사 영역** (6개 카테고리, 15+ 항목):

| 영역 | 주요 검증 |
|------|----------|
| 이슈 정합성 | 유저스토리·수용 조건 충족, 범위 초과 변경 없음 |
| API 계약 | response_model 존재, 스키마 무단 변경 방지 |
| 설계 문서 | specs/ 일치, generated/ 갱신 여부 |
| 코드 품질 | 컨벤션 준수, 사이드이펙트, 에러 처리, OWASP 보안 |
| 테스트 | 테스트 존재, 엣지 케이스, 기존 테스트 무영향 |
| PR 형식 | Conventional Commits, PR 크기(≤300줄), base 브랜치 |

**판정**: APPROVE (FAIL 0개) 또는 REQUEST_CHANGES (FAIL 1개 이상)
**결과**: PR 코멘트로 항목별 PASS/FAIL/N/A 게시
**수정 루프**: REQUEST_CHANGES 시 최대 2회 수정 → 재리뷰. 초과 시 사용자 에스컬레이션.

> 체크리스트 상세: `.agent/skills/review-pr.md`
> 프로세스 상세: [01-development-process.md §8](01-development-process.md#8-코드-리뷰-프로세스)

## 3. GitHub Actions 워크플로우 구성

```
.github/
└── workflows/
    ├── ci.yml                # Gate 1+2: ruff + pytest (PR 시 실행)
    ├── architecture.yml      # Gate 3: 모듈 경계 검증 (미구현)
    ├── ai-review.yml         # Gate 4: @code-reviewer 에이전트 (에이전트 레벨에서 실행)
    ├── semantic-release.yml  # 수동 버전 관리: 커밋 분석 → 버전 범프 → GitHub Release 생성
    └── publish.yml           # PyPI 배포: GitHub Release 발행 시 자동 트리거
```

### semantic-release.yml → publish.yml 연계 흐름

릴리스는 **수동 dispatch**로만 실행된다. main에 머지되었다고 자동 릴리스되지 않는다.

```
사용자 또는 에이전트가 /release 실행
  │
  ▼
semantic-release.yml 수동 실행 (workflow_dispatch)
  ├── 커밋 메시지 분석 (feat → minor, fix/perf → patch)
  ├── pyproject.toml의 version 자동 범프
  ├── CHANGELOG.md 갱신
  ├── chore(release): v{version} 커밋 + 태그 push
  └── GitHub Release 생성 (generate_release_notes)
  │
  ▼
publish.yml 자동 트리거 (release: published 이벤트)
  ├── 프론트엔드 빌드 (npm ci && npm run build)
  ├── 빌드 산출물을 src/ante/web/static/ 에 복사
  ├── Python 패키지 빌드 (python -m build → .whl + .tar.gz)
  ├── wheel 검증 (pip install + import 확인)
  └── PyPI 업로드 (API 토큰 방식)
```

**버전 범프 규칙**: [03-git-workflow.md §2](03-git-workflow.md#2-커밋-컨벤션) 참조.

**주요 설정**:
- `pyproject.toml` `[tool.semantic_release]` — 버전 소스, 태그 포맷, 커밋 파서 옵션
- `pyproject.toml` `[project.scripts]` — `ante` CLI 엔트리포인트 등록
- `pyproject.toml` `[tool.hatch.build] artifacts` — `.gitignore` 대상인 `web/static/`을 패키지에 포함

## 4. 로컬 개발 시 사전 검증

CI 실패를 줄이기 위해 로컬에서도 동일한 검증을 수행:

```bash
# 린트 + 포맷
ruff check src/ tests/
ruff format src/ tests/

# 타입 검사
mypy src/ante/

# 테스트
pytest tests/unit/ -v
```

> 에이전트의 로컬 검증 절차: `/implement-issue`의 구현 단계(8단계) 참조.

## 5. CI 실패 시 복구

> 에이전트의 자동 복구 전략: [01-development-process.md §6](01-development-process.md#6-에이전트-실패-시-복구-루프) 참조.

## 6. Phase별 Gate 도입 로드맵

| Gate | Phase 1 (현재) | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| Gate 1 (린트) | ruff | + mypy | + security scan |
| Gate 2 (테스트) | pytest unit | + integration | + coverage gate |
| Gate 3 (설계) | — | import 검사 | + AST 검증 |
| Gate 4 (코드 리뷰) | `@code-reviewer` 체크리스트 (A~F) | + API 계약 자동 검증 | + 커스텀 룰 확장 |
