# 07. 리뷰 및 머지 게이트

> Claude 구현 + Codex 사전 리뷰 + Claude/Codex 이중 승인 + GitHub auto-merge 구조를 정의한다.

---

## 1. 목적

이 문서는 세 가지를 분리한다.

1. **Codex 브랜치 리뷰**: PR 전 사전 품질 게이트
2. **Claude/Codex PR 승인**: PR head SHA 기준 최종 승인
3. **Merge Gate**: 승인과 CI 결과를 종합해 실제 머지 가능 여부만 판단

## 2. Codex 브랜치 리뷰

### 2.1 트리거

- 브랜치 push
- 대상: `feat/*`, `fix/*`, `refactor/*`, `docs/*`, `epic/*`

### 2.2 결과

- 상태 체크: `codex-branch-review`
- 선택 출력:
  - 이슈 코멘트
  - 커밋/체크 요약

### 2.3 처리 규칙

- `success`:
  - Claude가 PR을 생성할 수 있다
- `failure`:
  - Claude가 같은 브랜치에서 수정 후 재push
- 같은 SHA에 `failure`가 남아 있는 상태에서 PR을 먼저 열지 않는다

### 2.4 역할

이 단계의 Codex는 **blocking finding 식별자**다.
아직 merge 후보를 승인하는 단계가 아니다.

## 3. PR 승인

### 3.1 트리거

- `pull_request`
- activity types:
  - `opened`
  - `synchronize`
  - `ready_for_review`
  - 필요 시 `reopened`

### 3.2 승인 워커

| 워커 | 상태 체크 | 역할 |
|------|-----------|------|
| Claude PR 승인 워커 | `claude-pr-approve` | 구현 의도와 스펙/테스트/계약의 최종 정합성 확인 |
| Codex PR 승인 워커 | `codex-pr-approve` | 독립적인 교차검증 |

### 3.3 독립성 원칙

- 두 워커는 **같은 PR head SHA**를 본다.
- 두 워커는 가능한 한 **서로의 verdict를 입력으로 삼지 않는다**.
- merge gate는 두 워커의 결과를 소비하지만, 한 워커가 다른 워커의 판정을 따라가선 안 된다.

### 3.4 판정 기준

- 공통 체크리스트 계약: `.agent/skills/review-pr.md`
- 구현 스펙 기준: `docs/specs/`
- 아키텍처 기준: `docs/architecture/`

## 4. Merge Gate

### 4.1 입력

- `ci`
- `claude-pr-approve`
- `codex-pr-approve`
- 충돌 여부
- 대화 해결 여부

### 4.2 출력

- 조건 충족 시 auto-merge 활성화 또는 유지
- 하나라도 실패면 merge 보류

### 4.3 원칙

- merge gate는 **세 번째 리뷰어가 아니다**
- 코드 품질을 새로 판단하지 않는다
- 정책과 상태만 집행한다

## 5. Post-merge 책임 분리

| 작업 | 담당 |
|------|------|
| PR 머지 | GitHub auto-merge |
| head branch 삭제 | GitHub repository setting |
| 이슈 체크박스 갱신 + close | `post-merge.yml` |
| 로컬 worktree 정리 | Claude 구현 머신 |

다른 컴퓨터의 Codex가 원격 브랜치를 머지해도, Claude가 만든 로컬 worktree는 Codex가 직접 지울 수 없다. 이 둘은 반드시 분리해서 취급한다.

## 6. 저장소 설정 권장값

- `Allow auto-merge`: 활성화
- `Automatically delete head branches`: 활성화
- AI 리뷰 runner label:
  - Claude: `claude-review`
  - Codex: `codex-review`
- 저장소 변수:
  - `AI_REVIEW_ENABLED=true`일 때만 AI 리뷰 gate를 실제로 활성화
- branch protection required status checks:
  - `ci`
  - `claude-pr-approve`
  - `codex-pr-approve`
- `Require conversation resolution before merging`: 활성화 권장

## 7. 이슈와의 연결

- PR 본문은 `Refs #이슈번호`만 사용한다
- 이슈 close는 post-merge automation이 수행한다
- PR 승인 실패로 다시 수정이 발생해도 같은 이슈/같은 PR을 계속 사용한다
