# GitHub 운용 스킬

> 이 저장소에서 에이전트가 GitHub CLI(`gh`)를 사용할 때, 인증·조회·코멘트·PR·워크플로우 재실행 절차를 일관되게 맞추기 위한 공통 스킬이다.

## 목적

- 여러 커맨드가 GitHub를 제각각 다루지 않도록 공통 규칙을 제공한다.
- 공식 기록 위치를 이슈/PR 코멘트와 status check로 통일한다.
- `gh` 쓰기 작업 전에 인증 확인 절차를 강제한다.

## 함께 쓰는 스킬

- 쓰기 작업 전에는 항상 `.agent/skills/github-auth.md`를 먼저 따른다.
- 이 스킬은 인증 이후의 GitHub 운용 규칙을 정의한다.

## 기본 원칙

1. **공식 기록은 GitHub에 남긴다**
   - 이슈 분석, Plan Preflight, 구현 착수, PR 생성, 보류 사유, 수동 복구 근거는 GitHub 이슈/PR 코멘트에 남긴다.
   - `docs/temp/` 리포트는 요약본일 뿐 공식 증적 저장소가 아니다.

2. **같은 의미의 코멘트를 중복으로 남기지 않는다**
   - 새 코멘트를 남기기 전에 기존 코멘트 헤더를 먼저 확인한다.
   - 헤더 정의의 SSOT는 아래 §4 "필수 이벤트별 코멘트" 표이며, 이 목록은 중복 탐지용 헤더 모음이다.
   - 예:
     - `🤖 **Plan Preflight 시작**`
     - `🤖 **Plan Preflight 계획 정비 완료**`
     - `🤖 **Plan Review**` (legacy 읽기 호환: `🤖 **Codex Plan Review**`)
     - `🤖 **Plan Preflight 완료**`
     - `🤖 **Plan Preflight 보류**`
     - `🤖 **구현 분석 완료**`
     - `🤖 **구현 착수**`
     - `🤖 **로컬 구현 완료**`
     - `🤖 **브랜치 리뷰**` (legacy 읽기 호환: `🤖 **Codex 브랜치 리뷰**`)
     - `🤖 **이슈 검증**`
     - `🤖 **PR 생성 완료**`
     - `🤖 **Autopilot 사이클 상태**`
     - `🤖 **Autopilot 보류**`
     - `🤖 **Post-merge 정리 완료**`

     위 두 legacy 항목은 과거 이슈 코멘트에 남은 구 헤더의 읽기 호환용이다. 신 헤더가 구 헤더의 substring이 아니라 선언만으로는 과거 증적 검색이 이어지지 않으므로, 구 헤더 문자열 자체를 이 목록에 유지한다. 새 코멘트는 신 헤더로만 남긴다.

3. **조회와 쓰기의 목적을 분리한다**
   - 조회: `gh issue list/view`, `gh pr list/view/diff`, `gh run list/view`
   - 쓰기: `gh issue comment/create`, `gh pr create/edit`, `gh run rerun`, `gh workflow run`

4. **사람 판단이 필요한 경우는 코멘트로 이유를 남기고 멈춘다**
   - `needs-triage`
   - 스펙 불일치
   - 선행 의존 미완료
   - 반복 review loop

## 표준 절차

### 1. 인증 확인

쓰기 작업 전:

```bash
source .github/local/github.env
gh auth status
```

상세 절차는 `.agent/skills/github-auth.md`를 따른다.

### 2. 이슈 조회

기본 조회:

```bash
gh issue view #{번호} --json number,title,body,labels,comments
```

큐 조회:

```bash
gh issue list --state open --limit 100 --json number,title,labels,body,createdAt
```

### 3. 기존 증적 확인

리뷰나 보류 코멘트를 쓰기 전에는 같은 헤더가 이미 있는지 먼저 확인한다.

예:

```bash
gh issue view #{번호} --json comments --jq '.comments[].body'
```

### 4. 이슈 코멘트 작성

코멘트는 아래 원칙을 따른다.

- 첫 줄에 의미가 분명한 헤더를 둔다.
- 다음 단계 또는 보류 사유를 함께 적는다.
- 자동화가 읽을 수 있도록 상태 단어를 고정한다.
- `docs/runbooks/01-development-process.md`의 상호작용 흐름에 있는 이슈 기반 단계는 로컬 메모만 남기지 않고 아래 표준 코멘트 중 하나로 상태를 남긴다.

예:

```markdown
🤖 **Autopilot 보류**
- 사유: needs-triage
- 다음 단계: triage 후 라벨 제거
```

필수 이벤트별 코멘트 — **이 표가 이슈/PR 코멘트 헤더 정의의 SSOT다.** 커맨드·런북은 헤더를 새로 정의하지 않고 이 표를 참조하며, 아래 헤더 문자열을 그대로 사용한다.

| 이벤트 | 헤더 | 소유 커맨드/자동화 |
|--------|------|--------------------|
| Plan Preflight 시작 | `🤖 **Plan Preflight 시작**` | `/plan-preflight` |
| 이슈 본문 구현계획 정비 완료 | `🤖 **Plan Preflight 계획 정비 완료**` | `/plan-preflight` |
| 구현계획 계획 리뷰 결과 (Gate 0) | `🤖 **Plan Review**` | `/plan-preflight`, `/implement-issue` |
| Plan Preflight 완료 | `🤖 **Plan Preflight 완료**` | `/plan-preflight` |
| Plan Preflight 보류/중단 | `🤖 **Plan Preflight 보류**` | `/plan-preflight`, `/autopilot` |
| 구현 전 분석 완료 | `🤖 **구현 분석 완료**` | `/implement-issue` |
| 개발 에이전트 착수 | `🤖 **구현 착수**` | `/implement-issue` |
| 로컬 구현/검증/커밋 완료 | `🤖 **로컬 구현 완료**` | `/implement-issue` |
| PR 전 내부 브랜치 리뷰 결과 (Gate A) | `🤖 **브랜치 리뷰**` | `/implement-issue` |
| 외부발 버그 리포트 검증 | `🤖 **이슈 검증**` | `@issue-reviewer`, `/autopilot` |
| PR 생성 후 게이트 인계 | `🤖 **PR 생성 완료**` | `/implement-issue` |
| Autopilot 사이클 상태 | `🤖 **Autopilot 사이클 상태**` | `/autopilot` |
| Autopilot 보류 | `🤖 **Autopilot 보류**` | `/autopilot` |
| merge 후 이슈 정리 완료 | `🤖 **Post-merge 정리 완료**` | `post-merge.yml` |

리뷰 증적 코멘트(`Plan Review`, `브랜치 리뷰`, `이슈 검증`)는 헤더 아래 `reviewer:` 필드에 리뷰 수행 주체를 함께 기록한다. 리뷰 주체는 도구 중립 헤더와 분리해 이 필드로만 남긴다 (D-019).

- `Plan Review`(Gate 0) → `reviewer: @plan-reviewer`
- `브랜치 리뷰`(Gate A) → `reviewer: /code-review`
- `이슈 검증` → `reviewer: @issue-reviewer`

### 5. PR 생성/조회

PR 생성 전 확인:

- 최신 내부 branch review (`/code-review`) PASS 여부
- open PR 중복 여부
- base 브랜치 적합성
- release PR은 예외적으로 이슈 코멘트 기반 branch review 대신 `/release prepare`의 릴리스 메타데이터 검증과 Docker build 검증을 확인한다.

기본 조회:

```bash
gh pr view #{번호} --json title,body,baseRefName,headRefName,labels,files
```

기본 생성:

```bash
gh pr create --base {base} --title "{title}" --body "{body}"
```

### 6. 워크플로우 재실행/수동 실행

- 같은 head SHA에서 러너/일시적 환경 문제면 `gh run rerun` 우선
- `pull_request` 이벤트가 꼭 필요할 때만 다른 수단 사용
- 수동 재실행 후에는 PR 또는 이슈 코멘트에 이유와 새 run 근거를 남긴다

## 커맨드별 기대 동작

- `/plan-preflight`
  - 시작 라벨 변경과 동시에 `Plan Preflight 시작` 코멘트를 남김
  - 이슈 본문 Implementation Plan 정비 후 `Plan Preflight 계획 정비 완료` 코멘트를 남김
  - Plan Review 결과를 `Plan Review` 코멘트로 남김
  - 완료 시 `Plan Preflight 완료`, 중단 시 `Plan Preflight 보류` 코멘트를 남김
- `/autopilot`
  - 큐 snapshot, open PR 여부 확인, 보류 코멘트, Plan Preflight 상태 확인
  - 외부발 버그 리포트는 큐 편입 전 `@issue-reviewer` 검증 결과(`이슈 검증` 코멘트)를 선행 확인
  - 활성 이슈의 최신 `Autopilot 사이클 상태` 코멘트를 유지하고 merge/post-merge 완료까지 갱신
- `/implement-issue`
  - 이슈 조회, 구현 분석 완료 코멘트, 구현 착수 코멘트, 로컬 구현 완료 코멘트, 리뷰 요청/결과 코멘트, PR 생성, PR 생성 완료 코멘트
- `/release`
  - release PR 중복 확인, `release/vX.Y.Z` 브랜치 PR 생성, workflow dispatch/모니터링
  - 릴리스는 일반 GitHub 이슈 처리 흐름이 아니므로 이슈 코멘트 대신 release PR 본문, PR 코멘트, GitHub Release, workflow run을 공식 증적으로 삼음

## 금지 사항

- 인증 상태를 확인하지 않은 채 `gh` 쓰기 작업을 시작하지 않는다.
- 같은 상황에 대해 헤더만 다른 중복 코멘트를 여러 개 남기지 않는다.
- 로컬 메모만 남기고 GitHub에 근거를 생략하지 않는다.
- `config/secrets.env`와 GitHub 토큰 관리 절차를 혼용하지 않는다.
