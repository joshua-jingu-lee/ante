# Ante Runbooks

> 개발 프로세스 및 배포 가이드. 정책과 규칙을 정의한다.
> 에이전트의 구체적 작업 절차는 `.agent/commands/`가 단일 출처(SSOT).
>
> 마스터 문서: [AGENTS.md](../../AGENTS.md) | 아키텍처: [architecture.md](../architecture/README.md)

## 목차

| Runbook | 설명 |
|---------|------|
| [00-issue-management.md](00-issue-management.md) | GitHub Issues 등록, 분류, 추적 규칙 (이슈 템플릿, 라벨, 우선순위) |
| [01-development-process.md](01-development-process.md) | 개발 프로세스 정책 — 조건부 계획 리뷰, Claude 구현, Codex 사전 브랜치 리뷰, 메타 리뷰, PR 승인/자동 재수정/merge gate |
| [02-agent-structure.md](02-agent-structure.md) | Claude 역할 구조, 조건부 계획 리뷰어 `@code-reviewer`, Codex 외부 리뷰 워커, `.agent/`와 `.claude/` 레이어 |
| [03-git-workflow.md](03-git-workflow.md) | 커밋 컨벤션 (+ 버전 범프), `Closes #N` 기반 PR 규칙 |
| [04-ci-cd.md](04-ci-cd.md) | CI/CD 파이프라인 (Codex 브랜치 리뷰, 이중 승인, auto-merge) |
| [05-testing.md](05-testing.md) | 테스트 전략 (단위/통합/QA TC 테스트, 커버리지) |
| [07-review-gate.md](07-review-gate.md) | 조건부 계획 리뷰, 리뷰 단계와 merge gate의 책임 분리, 확장 리뷰 규칙, status check 기준 |

## 에이전트 커맨드 (작업 절차 SSOT)

| 커맨드 | 설명 |
|--------|------|
| `/implement-issue` | 이슈 구현 전체 흐름 (분석 → 경량 계획 → 조건부 계획 리뷰(필요 시) → 구현 → Codex 브랜치 리뷰 → PR 생성) |
| `/qa-test` | 지정 TC 실행 (`@qa-engineer` 위임) |
| `/qa-sweep` | 전체 TC 순차 실행 (전수 검사) |
| `/api-docs` | OpenAPI 스키마 조회 |
| `/arch-review` | 구현 전 아키텍처/의존성/계약 관점 사전 검토 |
| `/qa-review` | 구현 전 TC 커버리지/시나리오 관점 사전 검토 |
