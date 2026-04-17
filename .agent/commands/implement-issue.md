GitHub 이슈의 유저스토리를 기반으로 구현하고 테스트까지 완료한다.

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

이 커맨드는 오케스트레이터로서 작업을 분석하고, 구현은 전문 에이전트에 위임한다.

| 단계 | 담당 | 에이전트 | GitHub 기록 |
|------|------|----------|-------------|
| 1~4 (분석) | 오케스트레이터 | 메인 세션 | 스킵 시 이슈 코멘트 |
| 5 (착수 기록) | 오케스트레이터 | 메인 세션 | 이슈 코멘트: 착수 알림 |
| 6~9 (구현 + PR) | 개발 에이전트 | `@backend-dev` / `@frontend-dev` / `@devops` / `@strategy-dev` | PR 생성 (Refs #이슈) |
| 10 (코드 리뷰) | 리뷰 에이전트 | `@code-reviewer` | PR review: 체크리스트 판정 |
| 11 (수정 루프) | 오케스트레이터 조율 | 개발 ↔ 리뷰 에이전트 반복 (최대 2회) | PR: 커밋 + 재리뷰 |
| 12 (머지) | 오케스트레이터 | 메인 세션 | 이슈: 체크박스 갱신 + close |
| 13~14 (정리) | 오케스트레이터 | 메인 세션 | — |

## 작업 흐름

### 분석 단계 (오케스트레이터)

1. **이슈 읽기**: `gh issue view #{번호}`로 이슈 본문을 읽고 유저스토리(US)와 수용 조건을 파악한다.
   - **에픽 이슈인 경우** (`epic` 라벨 또는 하위 작업 목록이 있는 경우): 아래 "에픽 이슈 처리 절차"를 따른다. 이후 단계(2~13)는 실행하지 않는다.
   - **에픽 소속 판별**: 이슈 본문에 에픽 이슈 번호 참조(예: "에픽: #300")가 있거나, `git branch -r --list 'origin/epic/*'`로 해당 이슈를 포함하는 에픽 브랜치가 존재하는지 확인한다. 에픽 소속이면 해당 에픽 번호를 기억한다.
   - **하위 이슈인 경우**: 선행 이슈(본문에 명시된 의존 이슈)가 모두 close 상태인지 `gh issue view #{선행이슈}`로 확인한다. 미완성이면 이 이슈를 스킵하고 사용자에게 보고한다.
2. **설계 문서 확인**: 이슈에 관련 설계 문서(`docs/specs/{모듈}/{모듈}.md`)가 있으면 읽고 인터페이스와 요구사항을 파악한다. 없으면 이슈 본문이 곧 스펙이다.
   - **스펙 ↔ 구현 정합성 검증**: 이슈가 요구하는 구현이 스펙 문서에 정의되지 않은 인터페이스·동작을 포함하는 경우, 구현을 진행하지 않는다. 이슈에 스킵 사유를 코멘트로 남기고 사용자에게 보고한다.
     ```bash
     gh issue comment #{이슈번호} --body "🤖 **스킵: 스펙 불일치**
     이슈가 요구하는 구현이 스펙에 정의되지 않은 범위를 포함합니다.

     **불일치 항목:**
     - {docs/specs/xxx/xxx.md §N}: {미정의 인터페이스/동작 설명}

     스펙 최신화 후 재시도가 필요합니다."
     ```
3. **대상 에이전트 결정**: 이슈의 변경 대상에 따라 위임할 에이전트를 결정한다.
   - `src/ante/` 변경 → `@backend-dev`
   - `frontend/` 변경 → `@frontend-dev`
   - Docker/CI/CD/scripts/ 변경 → `@devops`
   - `tests/` 변경만 → `@backend-dev` (테스트는 백엔드 에이전트가 담당)
   - `strategies/` 변경 → `@strategy-dev`
   - 양쪽 모두 변경 → 백엔드 먼저, 프론트엔드 후속 (API 계약 확정 후 UI)
4. **기존 코드 파악**: 이슈가 기존 모듈 수정을 포함하는 경우, 관련 소스를 먼저 읽고 영향 범위를 파악한다.
   - **API 스키마 변경 감지**: 구현 범위가 `src/ante/web/schemas.py`의 Pydantic 모델 추가·수정·삭제를 포함하는지 확인한다.
     - 스키마 변경이 필요하면 별도 이슈를 발행하고, 현재 이슈에 선행 의존으로 등록한다.
     - 참조: `docs/runbooks/01-development-process.md` §10 (API 스키마 변경 규칙)

### 구현 시작 기록 (오케스트레이터)

5. **이슈에 착수 코멘트**: 구현을 시작하기 전에 이슈에 코멘트를 남긴다.
    ```bash
    gh issue comment #{이슈번호} --body "🤖 **구현 착수**
    - 담당 에이전트: @{에이전트명}
    - 변경 대상: {src/ante/xxx, frontend/ 등}
    - base 브랜치: {main 또는 epic/#{에픽번호}-{설명}}"
    ```

### 구현 단계 (개발 에이전트)

6~9단계를 개발 에이전트에 위임한다. 개발 에이전트는 구현과 로컬 검증까지만 수행하고, 코드 품질 판정은 리뷰 에이전트에 맡긴다.

```
Agent(
  subagent_type="backend-dev",  # 또는 "frontend-dev", "devops"
  prompt="""
이슈 #{번호}를 구현하라.

## 이슈 내용
{이슈 본문 전체}

## 설계 문서
{관련 스펙 문서 내용 요약 또는 경로}

## Worktree
에픽 소속이면: base=epic/#{에픽번호}-{에픽설명}
독립 이슈이면: base=main

## 작업 범위
6. Worktree 생성
7. 유저스토리별 구현
8. 테스트 작성 + 로컬 검증 (ruff check, ruff format, pytest — 빌드가 깨지지 않는 수준만 확인)
9. 커밋 + 푸시 + PR 생성 (Conventional Commits, "Refs #{이슈번호}" 포함)

PR URL을 반환하라.
""",
  isolation="worktree"
)
```

### 코드 리뷰 단계 (리뷰 에이전트)

10. **코드 리뷰**: 개발 에이전트가 생성한 PR에 대해 `@code-reviewer`에 리뷰를 위임한다. 리뷰어는 `review-pr` 스킬의 체크리스트(A~F)를 적용하고, `gh pr review`로 판정을 PR에 게시한다.

```
Agent(
  subagent_type="code-reviewer",
  prompt="""
PR #{PR번호}를 리뷰하라.
review-pr 스킬의 전체 체크리스트(A~F)를 적용하고,
gh pr review로 APPROVE 또는 REQUEST_CHANGES를 게시하라.
판정 결과와 FAIL 항목 상세를 반환하라.
"""
)
```

리뷰 결과를 원본 이슈에도 기록한다:

```bash
# APPROVE인 경우
gh issue comment #{이슈번호} --body "🤖 **코드 리뷰: APPROVE**
- PR: #${PR번호}
- 체크리스트 A~F 전체 통과"

# REQUEST_CHANGES인 경우
gh issue comment #{이슈번호} --body "🤖 **코드 리뷰: REQUEST_CHANGES**
- PR: #${PR번호}
- FAIL 항목: {fail_items}
- 수정 루프 진입 (${수정_횟수}/${최대_수정}회)"
```

### 수정 루프 (오케스트레이터 조율)

11. **REQUEST_CHANGES 처리**: 리뷰 에이전트가 REQUEST_CHANGES를 반환한 경우, 오케스트레이터가 수정 루프를 조율한다.

```
수정_횟수 = 0
최대_수정 = 2

while 판정 == REQUEST_CHANGES and 수정_횟수 < 최대_수정:
  수정_횟수 += 1

  # 1. 개발 에이전트에 FAIL 항목 수정 위임
  Agent(
    subagent_type="backend-dev",
    prompt="""
    PR #{PR번호}에서 리뷰 지적 사항을 수정하라.

    ## FAIL 항목
    {리뷰어가 반환한 fail_items + details}

    ## 규칙
    - 새 커밋으로 추가 (amend 금지)
    - 수정 후 푸시
    """,
    isolation="worktree"  # 동일 worktree에서 계속
  )

  # 2. 리뷰 에이전트에 재리뷰 위임
  Agent(
    subagent_type="code-reviewer",
    prompt="PR #{PR번호}를 재리뷰하라. 이전 FAIL 항목: {fail_items}"
  )

수정_횟수 >= 최대_수정이면:
  - autopilot 모드: 스킵 처리, GitHub 이슈에 실패 사유 코멘트
  - 일반 모드: 사용자에게 에스컬레이션
```

### 머지 단계 (오케스트레이터)

12. **APPROVE 후 머지**: 리뷰 에이전트가 APPROVE를 반환하고 CI가 통과한 경우에만 머지를 진행한다.
    - **CI 실패 시**: CI 로그(`gh run view`)를 확인하여 원인을 분류하고, 해결 후 원래 머지 흐름을 속행한다.
      - **코드 문제** (테스트 실패, lint 오류 등): 개발 에이전트에 수정 위임 (수정 루프와 동일하게 처리)
      - **인프라 문제** (Docker 빌드 실패, 의존성 설치 오류, CI 설정 오류 등): `@devops`에 해결 위임
        ```
        Agent(
          subagent_type="devops",
          prompt="""
          PR #{PR번호}의 CI가 인프라 문제로 실패했다. 해결하라.

          ## CI 실패 로그
          {실패 로그 요약}

          ## 규칙
          - 새 커밋으로 수정 (amend 금지)
          - pyproject.toml dependencies 변경 시 사용자 확인 필요
          """,
          isolation="worktree"
        )
        ```
      - **속행 원칙**: `@devops`가 수정을 푸시하면 CI 재실행을 대기하고, 통과 시 머지 흐름을 이어간다. 코드 변경으로 인한 인프라 깨짐은 빈번하므로, 동일 유형 실패라도 수정 내용이 다르면 새로운 시도로 카운트한다. 동일 원인으로 2회 연속 실패 시에만 스킵 처리.
    - **autopilot 모드**: `gh pr merge --squash --delete-branch`로 자동 머지 후, 이슈 체크박스를 갱신하고 close한다.
    - **에픽 하위 이슈**: 에픽 브랜치로의 머지이므로, APPROVE + CI 통과 시 자동 머지한다.
    - **일반 모드 (독립 이슈)**: APPROVE 결과를 사용자에게 보고하고 머지 승인을 요청한다.

    **이슈 체크박스 갱신 절차** (머지 확인 후, close 전에 반드시 실행):

    a. 이슈 본문의 완료 조건 체크박스(`- [ ]`)를 모두 `- [x]`로 갱신한다:
    ```bash
    BODY=$(gh issue view #{이슈번호} --json body -q '.body')
    UPDATED=$(echo "$BODY" | sed 's/- \[ \]/- [x]/g')
    gh issue edit #{이슈번호} --body "$UPDATED"
    ```

    b. **에픽 소속 하위 이슈인 경우**, 에픽 이슈 본문에서 해당 하위 이슈 체크박스도 갱신한다:
    ```bash
    EPIC_BODY=$(gh issue view #{에픽번호} --json body -q '.body')
    UPDATED=$(echo "$EPIC_BODY" | sed 's/- \[ \] \(.*#'"${이슈번호}"'\)/- [x] \1/g')
    gh issue edit #{에픽번호} --body "$UPDATED"
    ```

    c. 갱신 완료 후 `gh issue close #{이슈번호}`로 close한다.

13. **Worktree 정리**: PR 머지 확인 후 worktree를 제거한다.
    ```bash
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    WORKTREE_ROOT="${ANTE_WORKTREE_ROOT:-$(cd "$REPO_ROOT/.." && pwd)/ante-worktrees}"
    cd "$REPO_ROOT"
    git worktree remove "$WORKTREE_ROOT/feat-{이슈번호}"
    ```
14. **결과 보고**: 구현한 내용을 US 단위로 요약한다.

---

## 에픽 이슈 처리 절차

에픽 이슈 번호가 인자로 들어온 경우 (하위 작업 목록이 있는 이슈), 직접 코드를 구현하지 않고 다음 절차를 수행한다.

### E1. 에픽 통합 브랜치 생성

```bash
git branch epic/#{에픽번호}-{짧은설명} main
git push -u origin epic/#{에픽번호}-{짧은설명}
```

### E2. 하위 이슈 파악 및 정렬

에픽 본문에서 하위 이슈 목록을 추출하고, 의존성 그래프를 파악한다.
- 각 하위 이슈의 본문에서 선행 의존 이슈를 확인한다.
- 의존성이 없는 이슈끼리는 병렬 실행 가능한 그룹으로 묶는다.

### E3. 하위 이슈 순차/병렬 실행

의존성 순서에 따라 `/implement-issue #{하위이슈번호}`를 실행한다.
에픽 통합 브랜치가 존재하므로 각 하위 이슈는 자동으로 에픽 브랜치를 base로 사용한다.

```
# 의존성 없는 이슈끼리 병렬 실행 가능
Agent(prompt="/implement-issue #328", isolation="worktree")
Agent(prompt="/implement-issue #329", isolation="worktree")

# 위 이슈에 의존하는 이슈는 완료 후 순차 실행
/implement-issue #330
```

### E4. 에픽 통합 브랜치 → main 머지

모든 하위 이슈가 에픽 브랜치에 머지되면, worktree를 만들어 검증한다.

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_ROOT="${ANTE_WORKTREE_ROOT:-$(cd "$REPO_ROOT/.." && pwd)/ante-worktrees}"
mkdir -p "$WORKTREE_ROOT"
git worktree add "$WORKTREE_ROOT/epic-{에픽번호}" epic/#{에픽번호}-{짧은설명}
cd "$WORKTREE_ROOT/epic-{에픽번호}"
git merge main
pytest tests/ -v
gh pr create --base main \
  --title "epic/#{에픽번호}: {에픽 설명}" \
  --body "Refs #{에픽번호}

하위 이슈: #{하위1}, #{하위2}, ..."
git push
```

### E5. 정리 및 보고

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE_ROOT="${ANTE_WORKTREE_ROOT:-$(cd "$REPO_ROOT/.." && pwd)/ante-worktrees}"
cd "$REPO_ROOT"
git worktree remove "$WORKTREE_ROOT/epic-{에픽번호}"
git branch -d epic/#{에픽번호}-{짧은설명}
git push origin --delete epic/#{에픽번호}-{짧은설명}
```

에픽 이슈 체크박스를 모두 `- [x]`로 갱신한 뒤 close한다.
하위 이슈별 완료/실패/스킵 상태를 요약 보고한다.
