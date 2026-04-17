# 02. 에이전트 구조 및 .agent/ 디렉토리

> 에이전트 역할 정의와 `.agent/` 디렉토리 구성을 정의한다.
> 에이전트 정의 파일(`.agent/agents/*.md`)이 각 에이전트의 SSOT이다. `.claude/`는 설정 및 호환 레이어다.

---

## 1. 에이전트 역할 구성

에이전트 정의 파일은 `.agent/agents/` 디렉토리에 있다. 각 에이전트는 역할, 사용 도구, 참조 스킬이 YAML frontmatter로 정의되어 있다.

### 1.1 오케스트레이터 (Orchestrator)

**담당**: 사용자(개발자)가 직접 대화하는 메인 에이전트

**판단 기준** (우선순위 순):
1. **GitHub 이슈**: 유저스토리, 수용 조건, 의존성, 기술 노트 — 작업의 범위와 목표
2. **docs/specs/**: 설계 인터페이스, 동작 정의 — 구현의 정합성 검증 (SSOT)
3. **AGENTS.md**: 프로젝트 정체성, 설계 철학 — 방향성 판단

**역할**:
- 위 세 소스를 기반으로 작업을 분석하고 분해
- 적절한 서브에이전트에게 작업 위임
- 개발 ↔ 리뷰 수정 루프 조율
- 리뷰 통과 후 머지 결정
- 판단이 필요한 시점에 사용자에게 에스컬레이션

**실행 환경**: Claude Code 메인 세션

**소스코드 수정 원칙**: 오케스트레이터는 `.gitignore`에 등록되지 않은 소스코드(`src/`, `tests/` 등)를 직접 수정하지 않는다. GitHub 이슈를 발행하고 서브에이전트가 구현한다.

예외:
- `.gitignore` 대상 파일 (예: `docs/` 내 문서)
- 사용자가 명시적으로 직접 수정을 지시한 경우

### 1.2 백엔드 개발자 (`@backend-dev`)

**담당**: Python 백엔드 모듈 구현

- docs/specs/ 설계 문서를 따라 구현, 테스트 작성, 로컬 검증, PR 생성까지 수행
- 저사양 환경(N100)에서의 리소스 효율을 항상 고려
- 코드 품질 판정은 하지 않음 — `@code-reviewer`에 맡긴다

**스킬**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
**실행 환경**: worktree 격리

### 1.3 프론트엔드 개발자 (`@frontend-dev`)

**담당**: 대시보드(React) 구현

- `docs/dashboard/architecture.md`의 화면 구성을 **픽셀 단위로** 충실히 구현
- 디자인 토큰(`index.css` `@theme`) 기반 스타일링, Tailwind 기본 색상 사용 금지
- API 연동 시 타입 안전성 확보 — 백엔드에 없는 API를 임의로 만들지 않는다

**스킬**: `frontend-conventions`
**실행 환경**: worktree 격리

### 1.4 코드 리뷰어 (`@code-reviewer`)

**담당**: PR의 코드 품질과 설계 준수 여부를 체크리스트 기반으로 **판정만** 수행

- 체크리스트(A~F): 이슈 정합성, API 계약, 설계 문서 정합성, 코드 품질, 테스트, PR 형식
- `gh pr review`로 APPROVE 또는 REQUEST_CHANGES를 PR에 게시
- 수정과 머지는 리뷰어의 역할이 아님

**스킬**: `review-pr`, `module-conventions`
**실행 환경**: 읽기 전용 도구 + Bash (gh 명령용)

### 1.5 QA 엔지니어 (`@qa-engineer`)

**담당**: Gherkin TC 실행, Docker QA 환경 테스트, 버그 리포트

- `tests/tc/` 하위 .feature 파일을 실행하고 PASS/FAIL/ERROR/SKIP을 판정
- FAIL 시 재현 명령을 포함한 상세 리포트 반환

**스킬**: `qa-tester`
**실행 환경**: 일반 (worktree 격리 불필요)

### 1.6 DevOps 엔지니어 (`@devops`)

**담당**: Docker, CI/CD, 배포 스크립트, QA 환경 관리

- Dockerfile, docker-compose, GitHub Actions, scripts/ 관리
- pyproject.toml 변경 시 사용자 확인 필수

**실행 환경**: worktree 격리

### 1.7 전략 개발자 (`@strategy-dev`)

**담당**: 매매 전략 개발 — 데이터 탐색, 전략 작성, 정적 검증, 백테스트, 리포트 제출

- 전략 파일은 `strategies/` 디렉토리에 작성
- 봇 생성, 자금 할당, 실전 운용은 사용자 영역

**실행 환경**: 일반

## 2. `.agent/` 및 `.claude/` 디렉토리 구조

### 2.1 전체 구조

```
.agent/
├── agents/                # 역할별 에이전트 정의 (정식 위치)
│   ├── backend-dev.md         # @backend-dev
│   ├── frontend-dev.md        # @frontend-dev
│   ├── code-reviewer.md       # @code-reviewer
│   ├── qa-engineer.md         # @qa-engineer
│   ├── devops.md              # @devops
│   └── strategy-dev.md        # @strategy-dev
├── commands/              # 커스텀 슬래시 명령어 (작업 절차 SSOT)
│   ├── implement-issue.md     # /implement-issue
│   ├── autopilot.md           # /autopilot
│   ├── qa-test.md             # /qa-test
│   ├── qa-sweep.md            # /qa-sweep
│   └── api-docs.md            # /api-docs
└── skills/                # 도메인 지식 스킬 (에이전트가 참조)
    ├── module-conventions.md      # 백엔드 모듈 컨벤션
    ├── asyncio-patterns.md        # asyncio 패턴 가이드
    ├── sqlite-patterns.md         # SQLite 사용 패턴
    ├── frontend-conventions.md    # 프론트엔드 컨벤션
    ├── review-pr.md               # PR 리뷰 체크리스트 (A~F)
    └── qa-tester/                 # QA TC 실행 가이드
        ├── SKILL.md                   # Step 해석 규칙
        ├── gherkin-guide.md           # Gherkin → curl/docker 변환
        └── report-format.md           # 리포트 포맷

.claude/
├── settings.json              # 에이전트 권한 설정
├── settings.local.json        # 로컬 환경 오버라이드
├── settings.local.example.json # 로컬 설정 예시
├── hooks/                     # Claude hooks
├── agents -> ../.agent/agents
├── commands -> ../.agent/commands
└── skills -> ../.agent/skills
```

### 2.2 에이전트 정의 (agents/)

각 에이전트 파일은 YAML frontmatter에 `name`, `model`, `tools`, `skills`, `isolation` 등을 선언한다. 오케스트레이터가 `Agent(subagent_type="backend-dev")`처럼 호출하면 해당 정의가 자동 적용된다.

### 2.3 커스텀 명령어 (commands/)

반복적인 개발 작업을 슬래시 명령으로 정의하여 에이전트가 일관되게 실행:

- `/implement-issue #{번호}` — 이슈 기반 구현 전체 흐름 (구현 → 리뷰 → 머지)
- `/autopilot` — 완전 자동 모드 (구현 → QA → 수정 루프, 무확인)
- `/qa-test {카테고리}` — 지정 TC 실행 (`@qa-engineer` 위임)
- `/qa-sweep` — 전체 TC 전수 검사
- `/api-docs` — OpenAPI 스키마 조회

### 2.4 도메인 스킬 (skills/)

에이전트가 참고할 코딩 컨벤션과 도메인 지식. 에이전트 정의의 `skills:` 필드로 자동 연결된다:

- **백엔드**: `module-conventions`, `asyncio-patterns`, `sqlite-patterns`
- **프론트엔드**: `frontend-conventions`
- **코드 리뷰**: `review-pr` (체크리스트 A~F), `module-conventions`
- **QA**: `qa-tester/` (Gherkin Step 해석, 리포트 포맷)

### 2.5 권한 및 Hooks (settings.json)

- **permissions**: 에이전트가 실행할 수 있는 도구와 명령을 제한
- **hooks**: 파일 수정 시 자동 포맷팅(`auto-format.sh`), 보호 파일 검사(`protect-files.sh`)
