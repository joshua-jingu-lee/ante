# Ante Runbooks

> 개발 프로세스 및 배포 가이드. 정책과 규칙을 정의한다.
> 에이전트의 구체적 작업 절차는 `.agent/commands/`가 단일 출처(SSOT).
>
> 마스터 문서: [AGENTS.md](../../AGENTS.md) | 아키텍처: [architecture.md](../architecture/README.md)

## 목차

| Runbook | 설명 |
|---------|------|
| [00-issue-management.md](00-issue-management.md) | GitHub Issues 등록, 분류, 추적 규칙 (이슈 템플릿, 라벨, 우선순위) |
| [01-development-process.md](01-development-process.md) | 개발 프로세스 정책 — Plan Preflight/Codex Plan Review, Claude 구현, Codex 사전 브랜치 리뷰, 메타 리뷰, PR 승인/자동 재수정/merge gate |
| [02-agent-structure.md](02-agent-structure.md) | Claude 역할 구조, Codex 외부 리뷰 워커, Claude 메타 리뷰어, `.agent/`와 `.claude/` 레이어 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션 (+ 버전 범프), `Closes #N` 기반 PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인, 리뷰/승인/머지 게이트, 저장소 설정 |
| [05-testing.md](05-testing.md) | 테스트 전략 (단위/통합 테스트, 커버리지, 배포 이미지 시뮬레이션 테스트 방향) |
| [06-release.md](06-release.md) | 릴리스 운영 (release PR, 버전 관리, PyPI/Docker 배포) |

## 에이전트 커맨드 (작업 절차 SSOT)

| 커맨드 | 설명 |
|--------|------|
| `/plan-preflight` | `superpowers:writing-plans` 원칙으로 이슈 본문 구현계획 작성/정비, Codex Plan Review, `plan-preflight:done` 라벨 확정 |
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → Plan Preflight 확인 → Codex Plan Review → 구현 → Codex 브랜치 리뷰 → PR 생성) |
| `/autopilot` | 오픈 이슈 큐 순차 처리 (필요 시 Plan Preflight 후 `/implement-issue`와 merge/post-merge까지 순차 모니터링, 기본 `limit=10`) |
| `/release` | prepare로 release PR 생성, publish로 GitHub Release/PyPI/Docker image 배포 |
| `/api-docs` | OpenAPI 스키마 조회 |
