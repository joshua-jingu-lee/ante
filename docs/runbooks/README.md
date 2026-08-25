# Ante Runbooks

> 내부 maintainer·collaborator용 개발 프로세스 및 배포 런북. 정책과 규칙을 정의한다. 외부 기여자는 [CONTRIBUTING.md](../../CONTRIBUTING.md)를 따른다.
> 에이전트의 구체적 작업 절차는 `.agent/commands/`가 단일 출처(SSOT).
>
> 마스터 문서: [AGENTS.md](../../AGENTS.md) | 아키텍처: [architecture.md](../architecture/README.md)

## 목차

| Runbook | 설명 |
|---------|------|
| [00-issue-management.md](00-issue-management.md) | GitHub Issues 등록, 분류, 추적 규칙 (이슈 템플릿, 라벨, 우선순위) |
| [01-development-process.md](01-development-process.md) | 개발 프로세스 정책 — Plan Preflight/Plan Review(Gate 0), 선택 AI adapter 구현, 사전 브랜치 리뷰(Gate A `/code-review`), 메타 리뷰, merge gate |
| [02-agent-structure.md](02-agent-structure.md) | 선택 AI adapter 역할 구조, 계획/브랜치/이슈 리뷰 게이트, 메타 리뷰어, `.agent/`와 adapter 레이어 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션 (+ 버전 범프), `Closes #N` 기반 PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인, 리뷰/승인/머지 게이트, 저장소 설정 |
| [05-testing.md](05-testing.md) | 테스트 전략 (단위/통합 테스트, 커버리지, 배포 이미지 시뮬레이션 테스트 방향) |
| [06-release.md](06-release.md) | 릴리스 운영 (release PR, 버전 관리, PyPI/Docker 배포) |

## 보관 문서 (archive/)

일회성 데이터 정리 등 개발 프로세스·배포 정책에 해당하지 않는 문서는 `archive/`에 보관한다.
이 디렉토리 목적(개발 프로세스·배포 정책)에 맞지 않는 문서는 앞으로 루트에 넘버링하지 않는다.

| 보관 문서 | 설명 |
|---------|------|
| [archive/07-member-invalid-role-cleanup.md](archive/07-member-invalid-role-cleanup.md) | `MemberRole` enum 외 role 을 가진 legacy member row 의 식별 → 검토 → revoke 운영 절차 (#1417/#1465/#1466/#1468) |
| [archive/08-legacy-invalid-approval-cleanup.md](archive/08-legacy-invalid-approval-cleanup.md) | `ApprovalType` enum 외 `type` 을 가진 legacy approval row 의 식별 → 검토 → administrative cancel 운영 절차 (#1418/#1469/#1470/#1472) |

## 에이전트 커맨드 (작업 절차 SSOT)

| 커맨드 | 설명 |
|--------|------|
| `/plan-preflight` | `superpowers:writing-plans` 원칙으로 이슈 본문 구현계획 작성/정비, Plan Review, `plan-preflight:done` 라벨 확정 |
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → Plan Preflight 확인 → Plan Review → 구현 → 브랜치 리뷰 → PR 생성) |
| `/autopilot` | 오픈 이슈 큐 순차 처리 (필요 시 Plan Preflight 후 `/implement-issue`와 merge/post-merge까지 순차 모니터링, 기본 `limit=10`, 최대 `limit=25`) |
| `/release` | prepare로 release PR 생성, publish로 GitHub Release/PyPI/Docker image 배포 |
