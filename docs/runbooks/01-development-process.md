# 01. AI 에이전트 기반 개발 프로세스

> Claude Code가 구현을 담당하고, Codex가 사전 브랜치 리뷰를 담당하며, PR 단계에서는 두 모델이 독립적으로 승인하는 개발 체계를 정의한다.

---

## 1. 개발 철학

- 주 개발은 Claude Code가 담당한다.
- 스펙 문서(`docs/specs/`)가 설계의 단일 출처(SSOT)다. 변경이 필요하면 **스펙 최신화 → 이슈 발행 → 코드 반영** 순서를 따른다.
- PR은 구현 완료 사실을 알리는 문서가 아니라, **이미 한 차례 Codex 사전 리뷰를 통과한 변경**을 통합 후보로 올리는 단계다.
- 최종 머지 결정은 사람 감각이 아니라 **명시적인 게이트 상태**로 판단한다.
- `docs/specs/`와 `docs/architecture/`는 코드보다 앞선 계약이며, 리뷰와 승인 단계 모두 이 문서를 기준으로 판정한다.

## 2. 역할 구성

> Claude 측 역할과 `.agent/` 구조 상세: [02-agent-structure.md](02-agent-structure.md)
> 리뷰/승인/머지 게이트 상세: [07-review-gate.md](07-review-gate.md)

- **Claude 오케스트레이터**: 이슈 분석, 스펙 확인, 구현 에이전트 위임, GitHub 기록 관리
- **Claude 개발 에이전트**: 구현, 로컬 검증, 브랜치 푸시, Codex 피드백 반영
- **Codex 브랜치 리뷰어**: PR 전 브랜치 단위 사전 리뷰, blocking issue 식별
- **Claude PR 승인 워커**: PR head SHA 기준 최종 승인 체크
- **Codex PR 승인 워커**: PR head SHA 기준 최종 승인 체크
- **GitHub merge gate**: 두 모델 승인과 CI 성공 여부를 기준으로 auto-merge 실행

## 3. 상호작용 흐름

```
사용자 (요구사항/이슈)
  │
  ▼
Claude 오케스트레이터
  │  ◄──── AGENTS.md + docs/specs/* + docs/architecture/*
  │
  ├── 분석: 이슈 읽기 → 스펙 확인 → 구현 에이전트 결정
  │
  ├── 착수 기록: 이슈 코멘트
  │
  ├──▶ Claude 개발 에이전트 (worktree 격리)
  │         │
  │         ├── 구현 + 로컬 lint/test
  │         ├── 브랜치 push
  │         ▼
  │    Codex 브랜치 리뷰 (`codex-branch-review`)
  │         │
  │         ├── FAIL → Claude가 같은 브랜치에서 수정 후 재push
  │         └── PASS → PR 생성
  │
  ├── PR 생성 후
  │    ├── CI
  │    ├── Claude PR 승인 (`claude-pr-approve`)
  │    └── Codex PR 승인 (`codex-pr-approve`)
  │
  ├── 모든 게이트 green → GitHub auto-merge
  │
  ├── post-merge automation → 이슈 체크박스 갱신 + close
  │
  ▼
결과 보고
```

**핵심 차이**:
- Codex의 첫 리뷰는 **PR 전 브랜치 리뷰**다.
- PR 단계의 Claude/Codex 승인 체크는 **같은 head SHA**를 기준으로 독립 실행된다.
- 머지는 Claude 오케스트레이터가 직접 하지 않고, GitHub auto-merge가 수행한다.

## 4. 작업 실행 체계

에이전트의 구체적인 작업 절차는 `.agent/commands/`에 정의된 커맨드가 단일 출처(SSOT)다.

| 커맨드 | 역할 | 파일 |
|--------|------|------|
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → 구현 → Codex 브랜치 리뷰 → PR 생성) | `.agent/commands/implement-issue.md` |
| `/qa-test` | 지정 TC 실행 (`@qa-engineer` 위임) | `.agent/commands/qa-test.md` |
| `/qa-sweep` | 전체 TC 순차 실행 (전수 검사) | `.agent/commands/qa-sweep.md` |
| `/api-docs` | OpenAPI 스키마 조회 | `.agent/commands/api-docs.md` |

`/autopilot`은 레거시 커맨드이며, 이 운영 모델이 정착되면 제거한다.

### 4.1 브랜치 전략

> Git 컨벤션 상세: [03-git-workflow.md](03-git-workflow.md)

**독립 이슈**:

```
main
  └─ {type}/#{issue번호}-{짧은설명}
       ├─ 구현 + push
       ├─ codex-branch-review PASS
       └─ PR → main → auto-merge
```

**에픽 이슈**:

```
main
  └─ epic/#{에픽번호}-{짧은설명}
       ├─ feat/#{하위1} → Codex 브랜치 리뷰 → PR → epic/*
       ├─ feat/#{하위2} → Codex 브랜치 리뷰 → PR → epic/*
       └─ feat/#{하위3} → Codex 브랜치 리뷰 → PR → epic/*
     epic 브랜치 자체도 최종 PR 전에 Codex 브랜치 리뷰를 거친다.
```

### 4.2 Worktree 격리

모든 구현 작업은 **git worktree**로 격리하여 로컬 main을 보호한다.

| 상황 | Worktree 사용 |
|------|:------------:|
| 독립 모듈 병렬 구현 | O |
| 에픽 하위 이슈 병렬 구현 | O |
| 의존성 있는 순차 구현 | O |
| PR 승인 실패 후 재수정 | O (같은 이슈 브랜치 재사용) |

## 5. 실패 복구 루프

구체적 절차는 `/implement-issue`, 리뷰 게이트 상세는 [07-review-gate.md](07-review-gate.md)가 SSOT이며, 이 섹션은 정책만 정의한다.

| 실패 유형 | 원인 분류 | 복구 담당 | 복구 후 |
|-----------|----------|----------|--------|
| `codex-branch-review` FAIL | 코드/설계 문제 | Claude 개발 에이전트 | 같은 브랜치에서 수정 후 재push |
| CI 실패 — 코드 문제 | 테스트/lint/type 오류 | Claude 개발 에이전트 | 새 커밋 push 후 체크 재실행 |
| CI 실패 — 인프라 문제 | Docker/CI 설정/스크립트 | `@devops` | 수정 후 동일 PR에서 재실행 |
| `claude-pr-approve` FAIL | 스펙·계약·테스트 누락 | Claude 개발 에이전트 | 동일 PR 브랜치 수정 후 재검증 |
| `codex-pr-approve` FAIL | 버그/회귀/설계 위반 | Claude 개발 에이전트 | 동일 PR 브랜치 수정 후 재검증 |
| QA FAIL | 기능 버그 | 오케스트레이터가 버그 이슈 등록 → Claude 개발 에이전트 | 재검증 속행 |

### 5.1 재시도 규칙

- 동일 head SHA에 대해 같은 실패를 반복 판정하지 않는다. 새 커밋이 push되어야 새 시도로 본다.
- 이슈 코멘트에 Codex 브랜치 리뷰 실패 횟수를 누적한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호로 본다.
- 동일 유형의 blocking failure가 5회 누적되면 `blocked:review-loop` 라벨을 붙이고 자동 브랜치 리뷰를 중단한다.
- Codex 브랜치 리뷰에서 잡힌 이슈는 PR 생성 전에 해소해야 한다.

## 6. 리뷰와 머지 게이트

> 상세 규칙: [07-review-gate.md](07-review-gate.md)

- **브랜치 리뷰 단계**: Codex만 수행한다. PR 전 품질 게이트다.
- **PR 승인 단계**: Claude와 Codex가 각각 독립적으로 수행한다.
- **소스 오브 트루스**: GitHub PR review 코멘트보다 **status check 결과**를 merge gate의 기준으로 삼는다.
- **머지 담당**: GitHub auto-merge
- **원격 브랜치 삭제**: GitHub의 "Automatically delete head branches" 기능 사용
- **로컬 worktree 정리**: Claude 측에서 후속 작업 시 `git worktree prune` 또는 명시적 remove

## 7. 생성 문서 동기화 규칙

`docs/architecture/generated/` 하위 문서는 소스 코드에서 추출한 정보를 정리한 것이다. 해당 소스가 변경되면 반드시 생성 문서도 함께 갱신한다.

| 생성 문서 | 갱신 트리거 | 대상 소스 | 갱신 방법 |
|-----------|-----------|----------|----------|
| `guide/cli.md` | 명령어 추가/삭제, 인자·옵션·scope 변경 | `src/ante/cli/commands/` | `python scripts/generate_cli_reference.py` |
| `docs/architecture/generated/db-schema.md` | CREATE TABLE / CREATE INDEX 변경, 테이블 추가/삭제 | `src/ante/**/` 내 `_DDL` 상수 | `python scripts/generate_db_schema.py` |
| `docs/architecture/generated/project-structure.md` | 디렉토리·모듈 추가/삭제/이동 | 프로젝트 디렉토리 트리 | 수동 편집 |

### 7.1 자동 생성 스크립트

| 문서 | 스크립트 | 비고 |
|------|---------|------|
| `guide/cli.md` | `python scripts/generate_cli_reference.py` | 스크립트가 SSOT이며 수동 편집 금지 |
| `docs/architecture/generated/db-schema.md` | `python scripts/generate_db_schema.py` | 스크립트가 SSOT이며 수동 편집 금지 |
| `docs/architecture/generated/project-structure.md` | 미구현 | 디렉토리 구조 변경 시 수동 편집 |

### 7.2 갱신 규칙

- **CLI 변경 시**: `guide/cli.md`를 재생성한다.
- **DDL 변경 시**: `db-schema.md`를 재생성한다.
- **디렉토리 구조 변경 시**: `project-structure.md`를 갱신한다.
- **API 엔드포인트**: Swagger UI(`/docs`)에 자동 반영되므로 별도 문서 갱신은 불필요하다.

## 8. API 스키마 변경 규칙

API 응답 스키마(`src/ante/web/schemas.py`의 Pydantic 모델)는 백엔드와 프론트엔드 양쪽에 영향을 미치는 계약(contract)이다. 스키마 변경은 별도 이슈로 분리하여 양쪽 영향을 통제한다.

### 8.1 스키마 변경 = 별도 이슈

- `src/ante/web/schemas.py`의 Pydantic 모델 추가·수정·삭제는 **구현 이슈와 분리하여 별도 이슈로 등록**한다.
- 구현 이슈 진행 중 스키마 변경이 필요하다고 판단되면, 해당 이슈 안에서 직접 변경하지 않고 새 이슈를 발행한다.
- 스키마 변경 이슈와 구현 이슈 사이에 의존성을 명시한다.

### 8.2 오케스트레이터 검증

- 오케스트레이터는 구현 요청에 API 스키마 변경이 포함되어 있는지 감지한다.
- 스키마 변경이 감지되면, 스키마 변경을 별도 이슈로 분리하도록 안내한다.
- API 스키마 변경 이슈는 오케스트레이터가 **백엔드·프론트엔드 양쪽 영향**을 확인한 뒤 진행한다.

### 8.3 백엔드 규칙

- 모든 새 엔드포인트는 반드시 `response_model`을 명시한다.
- `dict`를 직접 반환하는 것은 금지한다.
- 기존 `response_model` 변경은 별도 스키마 변경 이슈를 거친다.

### 8.4 프론트엔드 규칙

- API 응답 타입은 `openapi-typescript`로 자동 생성된 `api.generated.ts`에서만 import한다.
- 수동으로 API 응답 인터페이스를 정의하지 않는다.
- 스키마 변경 이슈가 머지되면 `npm run generate-types`로 타입을 재생성한다.
- 백엔드에 존재하지 않는 API를 프론트엔드에서 임의로 만들지 않는다.

## 9. AGENTS.md 경량화 원칙

AGENTS.md는 모든 세션에 주입되므로 핵심 규칙만 유지한다.

- 핵심 설계 원칙, 기술 스택, 디렉토리 구조만 유지
- 모듈별 세부 설계는 `docs/specs/`에 분리
- 상세 가이드는 `.agent/skills/`로 분리

## 관련 문서

| 문서 | 내용 |
|------|------|
| [00-issue-management.md](00-issue-management.md) | 이슈 등록, 분류, 추적 규칙 |
| [02-agent-structure.md](02-agent-structure.md) | Claude 역할과 Codex 외부 리뷰 워커 구조 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션, 브랜치/PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인과 status check 구성 |
| [05-testing.md](05-testing.md) | 테스트 전략, 커버리지 기준 |
| [07-review-gate.md](07-review-gate.md) | 브랜치 리뷰, PR 승인, merge gate 상세 |
