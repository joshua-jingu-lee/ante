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
   - 예:
     - `🤖 **구현 착수**`
     - `🤖 **PR 생성 완료**`
     - `🤖 **Autopilot 보류**`

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

예:

```markdown
🤖 **Autopilot 보류**
- 사유: needs-triage
- 다음 단계: triage 후 라벨 제거
```

### 5. PR 생성/조회

PR 생성 전 확인:

- 최신 내부 branch review (`/codex:review --base <ref>`) PASS 여부
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

- `/autopilot`
  - 큐 snapshot, open PR 여부 확인, 보류 코멘트, Plan Preflight 상태 확인
- `/implement-issue`
  - 이슈 조회, 구현 착수 코멘트, 리뷰 요청 코멘트, PR 생성, PR 생성 완료 코멘트
- `/release`
  - release PR 중복 확인, `release/vX.Y.Z` 브랜치 PR 생성, workflow dispatch/모니터링

## 금지 사항

- 인증 상태를 확인하지 않은 채 `gh` 쓰기 작업을 시작하지 않는다.
- 같은 상황에 대해 헤더만 다른 중복 코멘트를 여러 개 남기지 않는다.
- 로컬 메모만 남기고 GitHub에 근거를 생략하지 않는다.
- `config/secrets.env`와 GitHub 토큰 관리 절차를 혼용하지 않는다.
