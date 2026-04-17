GitHub 이슈의 유저스토리를 기반으로 구현하고, Codex 브랜치 리뷰를 통과한 뒤 PR을 생성한다.

## 인자

$ARGUMENTS — GitHub 이슈 번호 (예: 43, 39 등)

## 경로 규칙

아래 셸 예시는 저장소 루트와 worktree 루트를 동적으로 계산한다.

- `REPO_ROOT`: `git rev-parse --show-toplevel`
- `WORKTREE_ROOT`: `ANTE_WORKTREE_ROOT`가 설정되어 있으면 그 값을 사용하고, 없으면 저장소의 형제 디렉토리 `ante-worktrees/`를 사용한다.

공통 셸 변수:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_ROOT="${ANTE_WORKTREE_ROOT:-$(cd "$REPO_ROOT/.." && pwd)/ante-worktrees}"
mkdir -p "$WORKTREE_ROOT"
```

## 에이전트 역할 분담

이 커맨드는 Claude 오케스트레이터로서 작업을 분석하고, 구현은 Claude 개발 에이전트에 위임한다. PR 전 사전 리뷰는 Codex가 수행한다.

| 단계 | 담당 | 실행 주체 | GitHub 기록 |
|------|------|-----------|-------------|
| 1~4 (분석) | 오케스트레이터 | Claude 메인 세션 | 스킵 시 이슈 코멘트 |
| 5 (착수 기록) | 오케스트레이터 | Claude 메인 세션 | 이슈 코멘트 |
| 6~9 (구현 + push) | 개발 에이전트 | `@backend-dev` / `@frontend-dev` / `@devops` / `@strategy-dev` | 브랜치 push |
| 10~11 (사전 리뷰 루프) | Codex + Claude | GitHub workflow + Claude 개발 에이전트 | `codex-branch-review` + 이슈 코멘트 |
| 12 (PR 생성) | 오케스트레이터 | Claude 메인 세션 | PR 생성 (`Refs #이슈`) |
| 13 (최종 승인/머지) | GitHub automation | Claude/Codex PR 승인 워커 + auto-merge | PR checks |

## 작업 흐름

### 분석 단계 (오케스트레이터)

1. **이슈 읽기**: `gh issue view #{번호}`로 이슈 본문을 읽고 유저스토리와 수용 조건을 파악한다.
   - **에픽 이슈인 경우**: 아래 "에픽 이슈 처리 절차"를 따른다.
   - **하위 이슈인 경우**: 선행 이슈가 모두 close 상태인지 확인한다. 미완성이면 이 이슈를 스킵하고 사용자에게 보고한다.
2. **설계 문서 확인**: 관련 설계 문서(`docs/specs/{모듈}/{모듈}.md`)를 읽고 인터페이스와 요구사항을 파악한다.
   - 스펙에 정의되지 않은 인터페이스·동작을 요구하면 구현하지 않고 이슈에 스킵 사유를 남긴다.
3. **대상 에이전트 결정**:
   - `src/ante/` 변경 → `@backend-dev`
   - `frontend/` 변경 → `@frontend-dev`
   - Docker/CI/CD/scripts/ 변경 → `@devops`
   - `strategies/` 변경 → `@strategy-dev`
   - 양쪽 모두 변경 → 백엔드 먼저, 프론트엔드 후속
4. **기존 코드 파악**: 이슈가 기존 모듈 수정을 포함하면 관련 소스를 먼저 읽고 영향 범위를 파악한다.

### 구현 시작 기록 (오케스트레이터)

5. **이슈에 착수 코멘트**:

```bash
gh issue comment #{이슈번호} --body "🤖 **구현 착수**
- 담당 에이전트: @{에이전트명}
- 변경 대상: {src/ante/xxx, frontend/ 등}
- base 브랜치: {main 또는 epic/#{에픽번호}-{설명}}"
```

### 구현 단계 (개발 에이전트)

6~9단계를 Claude 개발 에이전트에 위임한다.

```
Agent(
  subagent_type="backend-dev",
  prompt="""
이슈 #{번호}를 구현하라.

## 이슈 내용
{이슈 본문 전체}

## 설계 문서
{관련 스펙 문서 경로와 요약}

## 작업 범위
6. Worktree 생성
7. 유저스토리별 구현
8. 로컬 검증 (ruff check, ruff format, pytest)
9. 브랜치 push

브랜치명과 push한 HEAD SHA를 반환하라.
""",
  isolation="worktree"
)
```

### Codex 브랜치 리뷰 루프

10. **Codex 사전 리뷰 요청 및 대기**: 브랜치 push 직후 Claude가 이슈에 리뷰 요청 코멘트를 남기고, 이후 `codex-branch-review` 상태를 확인한다.

```bash
gh issue comment #{이슈번호} --body "🤖 **Claude Code 리뷰 요청**
- 단계: Codex 브랜치 리뷰
- 브랜치: {브랜치명}
- HEAD: {SHA}
- 다음 단계: GitHub Actions가 리뷰를 시작하고, 시작/완료 결과를 이슈 코멘트로 남깁니다."
```

- `success`:
  - PR 생성 단계로 진행
- `failure`:
  - Codex가 남긴 blocking finding을 읽고 Claude 개발 에이전트에 수정 위임

11. **수정 루프**: `codex-branch-review`가 최신 HEAD SHA에서 `success`가 될 때까지 반복한다.

```text
while codex-branch-review != success:
  Claude 개발 에이전트가 같은 브랜치에서 수정
  새 커밋 push
  최신 HEAD SHA의 codex-branch-review 재확인
```

- 실패 횟수는 이슈 코멘트 기준으로 누적한다.
- 같은 blocking finding 제목이 2회 이상 연속 반복되면 escalation 신호로 보고 원인 파악을 우선한다.
- 반복 실패가 5회 이상이면 `blocked:review-loop` 라벨이 붙고 Codex 브랜치 리뷰를 더 이상 자동 실행하지 않는다.
- 이 상태에서는 사용자가 개입해 원인을 정리하거나 라벨을 해제하기 전까지 같은 이슈를 계속 밀어붙이지 않는다.

### PR 생성

12. **PR 생성**: 최신 HEAD SHA의 `codex-branch-review`가 성공한 뒤에만 PR을 만든다.

```bash
gh pr create \
  --base {main 또는 epic/...} \
  --title "{conventional commit 형식 제목}" \
  --body "Refs #{이슈번호}

## Summary
- {변경 요약}

## Test Plan
- {로컬 검증 명령}
"
```

PR 생성 후 이슈에 코멘트를 남긴다:

```bash
gh issue comment #{이슈번호} --body "🤖 **PR 생성 완료**
- PR: #{PR번호}
- branch-review: 통과
- 이후 단계: CI + claude-pr-approve + codex-pr-approve + auto-merge"
```

### PR 이후 단계

13. **최종 승인과 머지**: PR 생성 이후에는 GitHub automation이 다음을 수행한다.

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 모든 체크가 green이면 auto-merge
- 머지 후 post-merge automation이 이슈 체크박스를 갱신하고 close

이 커맨드는 **직접 머지하지 않는다**.

## 에픽 이슈 처리 절차

에픽 이슈 번호가 인자로 들어온 경우, 직접 코드를 구현하지 않고 다음 절차를 수행한다.

### E1. 에픽 통합 브랜치 생성

```bash
git branch epic/#{에픽번호}-{짧은설명} main
git push -u origin epic/#{에픽번호}-{짧은설명}
```

### E2. 하위 이슈 정렬

- 에픽 본문에서 하위 이슈 목록과 의존성을 파악한다.
- 의존성 없는 이슈끼리는 병렬 실행 가능 그룹으로 묶는다.

### E3. 하위 이슈 실행

각 하위 이슈에 대해 동일한 `/implement-issue #{하위이슈번호}` 흐름을 수행한다.

- 구현
- 브랜치 push
- Codex 브랜치 리뷰 통과
- PR 생성 (`base=epic/#{에픽번호}-{설명}`)

### E4. 에픽 PR 생성

모든 하위 이슈가 에픽 브랜치에 반영되면, 에픽 브랜치도 동일한 규칙을 따른다.

1. 에픽 브랜치 최신화 및 로컬 검증
2. `codex-branch-review` 통과
3. `epic/* -> main` PR 생성
4. `ci + claude-pr-approve + codex-pr-approve` 통과 후 auto-merge

### E5. 정리

- 원격 브랜치 삭제는 GitHub 설정에 맡긴다.
- 로컬 worktree는 Claude 구현 머신에서 후속 작업 시 prune/remove 한다.

## 종료 조건

이 커맨드의 성공 기준은 다음 중 하나다.

- PR이 성공적으로 생성되었고 자동 승인/머지 파이프라인이 인계됨
- 스펙 불일치 또는 반복 실패로 인해 이슈가 명시적으로 `blocked` 처리됨
