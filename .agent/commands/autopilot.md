> deprecated: 현재 기본 운영 모델은 `Claude 구현 → Codex 브랜치 리뷰 → PR → Claude/Codex 이중 승인 → auto-merge`다.
> 이 커맨드는 삭제 예정인 레거시 문서다.

오픈 이슈 구현 → QA 검증 → 버그 수정을 이슈가 없어질 때까지 자율 반복하는 완전 자동 모드.

## 인자

$ARGUMENTS — 옵션 (생략 가능)
- 없음: 전체 오픈 이슈 대상
- `--label {라벨}`: 특정 라벨의 이슈만 대상

## 에이전트 역할 분담

| 단계 | 담당 | 에이전트 |
|------|------|----------|
| 루프 제어/이슈 선택 | 오케스트레이터 | 메인 세션 |
| 구현 | 개발 에이전트 | `/implement-issue` → `@backend-dev` / `@frontend-dev` / `@devops` |
| 코드 리뷰 | 리뷰 에이전트 | `/implement-issue` → `@code-reviewer` |
| QA 검증 | QA 에이전트 | `/qa-sweep` → `@qa-engineer` |
| 머지/정리 | 오케스트레이터 | 메인 세션 |

## 자율 운전 규칙

1. **무확인 원칙**: 모든 단계를 사용자 확인 없이 자동으로 수행한다. PR 머지, 이슈 close, 버그 이슈 등록 모두 자동.
2. **3회 스킵**: 동일 이슈에서 3회 이상 실패(구현 실패, 리뷰 거부, CI 실패 등) 시 해당 이슈를 스킵 처리하고 GitHub 이슈에 실패 사유를 코멘트로 남긴다.
3. **변경 금지 영역**: AGENTS.md, docs/specs/, pyproject.toml의 dependencies 섹션은 수정하지 않는다. specs는 SSOT이므로 스펙 불일치 시 구현하지 않고 스킵 처리한다.
4. **gitignore 보호**: .gitignore에 포함된 파일은 `git add -f`로 강제 커밋하지 않는다.
5. **Worktree 격리**: 모든 구현은 독립된 worktree에서 수행한다.

## 메인 루프

```
SKIP_LIST = []       # 스킵된 이슈 (사유 포함)
DONE_LIST = []       # 완료된 이슈
ROUND = 0

loop:
  ROUND += 1

  ┌─────────────────────────────────────────┐
  │ Phase 1: 구현                            │
  │                                         │
  │ 1. 오픈 이슈 조회                         │
  │    gh issue list --state open            │
  │    --label feature,bug,epic              │
  │                                         │
  │ 2. 이슈 정렬 (우선순위)                    │
  │    a. epic → 에픽 통합 절차               │
  │    b. bug → 버그 우선 수정                │
  │    c. feature → 낮은 번호 순              │
  │    d. 선행 의존 미완 이슈 제외              │
  │    e. SKIP_LIST 이슈 제외                 │
  │                                         │
  │ 3. 각 이슈에 대해:                        │
  │    /implement-issue #{번호}               │
  │    → 구현 + 리뷰 + 자동 머지 + close      │
  │    → 실패 시 재시도 (최대 3회, 초과 시 SKIP)│
  │    → DONE_LIST 또는 SKIP_LIST에 추가      │
  │                                         │
  │ 4. 더 이상 구현할 이슈가 없으면 Phase 2로   │
  └─────────────────────────────────────────┘
                    ↓
  ┌─────────────────────────────────────────┐
  │ Phase 2: QA 검증                         │
  │                                         │
  │ 1. /qa-sweep --fix 실행                  │
  │    → @qa-engineer가 전체 TC 실행          │
  │    → FAIL 발견 시 자동으로 버그 이슈 등록   │
  │                                         │
  │ 2. 새로 등록된 버그 이슈가 있으면           │
  │    → loop 처음으로 (Phase 1 재진입)        │
  │                                         │
  │ 3. 새 버그 이슈가 없으면 (전체 PASS 또는    │
  │    남은 FAIL이 모두 SKIP_LIST) → 종료      │
  └─────────────────────────────────────────┘
                    ↓
  ┌─────────────────────────────────────────┐
  │ Phase 3: 정리 및 보고                     │
  │                                         │
  │ 1. Worktree 정리                         │
  │    git worktree prune                   │
  │                                         │
  │ 2. 최종 리포트 출력                       │
  └─────────────────────────────────────────┘
```

## Phase 1 상세: 구현

각 이슈에 대해 `/implement-issue #{번호}`를 실행한다.

**autopilot 모드에서의 implement-issue 동작 차이:**
- 머지: APPROVE + CI 통과 시 무조건 자동 머지 (`gh pr merge --squash --delete-branch`)
- 스펙 불일치: 스킵 처리 (일반 모드에서는 사용자에게 보고)
- 리뷰 거부: 자동 수정 후 재시도 (최대 2회, 초과 시 스킵)

```
/implement-issue 호출 시 prompt에 다음을 포함:

## 모드
autopilot — 모든 단계를 사용자 확인 없이 자동 수행.
APPROVE + CI 통과 시 자동 머지. 스펙 불일치 시 스킵 처리.
```

**병렬 실행**: 의존성이 없는 이슈들은 동시 실행 가능:

```
Agent(prompt="/implement-issue #328 (autopilot)", isolation="worktree")
Agent(prompt="/implement-issue #329 (autopilot)", isolation="worktree")
```

## Phase 2 상세: QA 검증

`/qa-sweep --fix`를 실행한다. 내부 동작:

1. `@qa-engineer`가 카테고리별 TC 실행
2. FAIL 발견 시 자동으로 버그 이슈 등록 (`gh issue create --label bug`)
3. 등록된 버그 이슈를 즉시 `/implement-issue`로 수정 시도
4. 수정 후 해당 TC만 재검증
5. 재검증 PASS → 이슈 close
6. 재검증 FAIL → 재시도 횟수 확인 → 3회 초과 시 SKIP_LIST에 추가

**루프 탈출 조건:**
- 새로 등록된 버그 이슈가 0건 → 종료
- 새 버그 이슈가 모두 SKIP_LIST에 해당 → 종료
- 최대 루프 횟수 초과 (ROUND > 5) → 강제 종료

## 에픽 이슈 처리

에픽 이슈를 발견하면 `/implement-issue #{에픽번호}`를 실행한다.
에픽 통합 브랜치 생성, 하위 이슈 실행, main 머지까지 `/implement-issue`의 "에픽 이슈 처리 절차"(E1~E5)를 따른다.

에픽 내 하위 이슈도 autopilot 규칙(무확인, 3회 스킵)을 동일하게 적용한다.

## 최종 리포트

리포트는 `docs/temp/`에 파일로 저장한다.

```bash
mkdir -p docs/temp
# 파일명: autopilot-report-YYYYMMDD-HHMM.md
Write("docs/temp/autopilot-report-{날짜시간}.md", "{리포트 내용}")
```

리포트 포맷:

```markdown
## Autopilot 결과 보고

- 실행 시각: {시작} ~ {종료}
- 루프 횟수: {ROUND}회

### 구현 이슈
| 이슈 | 제목 | 결과 | PR |
|------|------|------|-----|
| #601 | 계좌 CRUD API | 완료 | #610 |
| #602 | 봇 라이프사이클 | 완료 | #611 |
| #604 | 리스크 엔진 | 스킵 (스펙 불일치) | — |
| #605 | 알림 서비스 | 스킵 (3회 CI 실패) | #612 |

### QA 검증
| 라운드 | TC 수 | PASS | FAIL | 자동 수정 | 미해결 |
|--------|-------|------|------|----------|--------|
| 1      | 50    | 45   | 5    | 3        | 2      |
| 2      | 50    | 48   | 2    | 1        | 1      |
| 3      | 50    | 49   | 1    | 0        | 1      |

### 미해결 이슈
- #703 QA: treasury/allocation — 음수 할당 허용 (3회 수정 실패)
- #604 스펙 불일치: 리스크 엔진 — risk.md §3 인터페이스 미정의
```
