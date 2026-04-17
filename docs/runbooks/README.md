# Ante Runbooks

> 개발 프로세스 및 배포 가이드. 정책과 규칙을 정의한다.
> 에이전트의 구체적 작업 절차는 `.agent/commands/`가 단일 출처(SSOT).
>
> 마스터 문서: [AGENTS.md](../../AGENTS.md) | 아키텍처: [architecture.md](../architecture/README.md)

## 목차

| Runbook | 설명 |
|---------|------|
| [00-issue-management.md](00-issue-management.md) | GitHub Issues 등록, 분류, 추적 규칙 (이슈 템플릿, 라벨, 우선순위) |
| [01-development-process.md](01-development-process.md) | 개발 프로세스 정책 — 상호작용 흐름, 브랜치 전략, 복구 루프, autopilot, 코드 리뷰 |
| [02-agent-structure.md](02-agent-structure.md) | 에이전트 역할(7종), `.agent/` 구조와 `.claude/` 호환 레이어 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션 (+ 버전 범프), PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인 (Gate 모델, semantic-release, 릴리스 빌드) |
| [05-testing.md](05-testing.md) | 테스트 전략 (단위/통합/QA TC 테스트, 커버리지) |

## 에이전트 커맨드 (작업 절차 SSOT)

| 커맨드 | 설명 |
|--------|------|
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → 구현 → 리뷰 → 머지) |
| `/autopilot` | 완전 자동 모드 (구현 → QA → 수정 루프, 무확인) |
| `/qa-test` | 지정 TC 실행 (`@qa-engineer` 위임) |
| `/qa-sweep` | 전체 TC 순차 실행 (전수 검사) |
| `/api-docs` | OpenAPI 스키마 조회 |
