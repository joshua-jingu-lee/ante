# D-019: 리뷰 게이트 재설계 — Codex 플러그인 의존 제거 (2026-07-06)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)

**결정**: 개발 프로세스의 두 차단 게이트(구현 착수 전 Plan Review, PR 생성 전 브랜치 리뷰)에서 외부 Codex 플러그인(openai-codex) 의존을 제거하고, Claude Code 네이티브 수단으로 재배선한다.

**구성**:

- **Gate 0 (Plan Review)**: 구현 세션과 격리된 별도 컨텍스트의 계획 리뷰 서브에이전트 `@plan-reviewer`(신설, `.agent/agents/plan-reviewer.md`)가 수행한다. 명시적 반려 권한을 가지며, verdict 어휘(`approve-implement` / `narrow-scope` / `revise-plan` / `split-issue` / `invoke-human`)와 `plan-preflight:started/done` 라벨 상태 기계는 그대로 유지한다.
- **Gate A (브랜치 리뷰)**: Claude Code 네이티브 `/code-review`로 수행한다. PASS/FAIL 판정, 시도 횟수 누적, 반복 실패 시 `blocked:review-loop` 차단 계약은 그대로 유지한다.
- **@code-reviewer**: 메타 리뷰 전용(고위험 변경·반복 review failure 시 구조 분석)이라는 기존 정의를 유지한다. 일상 게이트로 승격하지 않는다.
- **이슈 검증 (@issue-reviewer 신설, `.agent/agents/issue-reviewer.md`)**: 외부에서 버그 리포트가 들어올 때(예: `source:ante-oracle` 자동 리포트, 외부 제보) 이슈의 진실성(주장하는 루트원인이 실제 코드와 일치하는가)과 재현 가능성을 구현 착수 전에 검토하는 read-only 서브에이전트. 상시 게이트가 아니며, 내부에서 기획한 이슈에는 적용하지 않는다. verdict는 `confirmed` / `not-reproduced` / `invalid` / `needs-info` 4종을 이슈 코멘트 증적(`이슈 검증` 헤더)으로 남기며, `invalid`·`not-reproduced` 판정 이슈는 자동 큐에서 제외한다. 라벨 등 큐 연동 세부는 런북 00 개정에서 확정한다.
- **고위험 변경·릴리스 직전 검증**: `/code-review`의 상위 effort(예: ultra)를 선택 경로로 열어둔다.
- **리뷰 증적**: 이슈 코멘트 헤더를 도구 중립 명칭(`Plan Review`, `브랜치 리뷰`)으로 바꾸고, 리뷰 수행 주체는 별도 필드(`reviewer:`)로 기록한다. 헤더 정의의 SSOT는 `.agent/skills/github-ops.md` 한 곳으로 두고, 커맨드·런북은 참조만 한다. 과거 이슈의 구 헤더(`Codex Plan Review` 등)는 읽기 호환으로 인정한다.
- **반복 실패 임계값**: 10회로 확정하고 SSOT는 `docs/runbooks/04-ci-cd.md`에 둔다. GitHub 라벨 설명에서는 도구명과 임계값 숫자를 제거한다(현재 라벨 설명은 5회, 런북·커맨드는 10회로 이미 불일치 — 숫자를 라벨에 두지 않는 근거).

**근거**:

- Codex 사용량 한도로 게이트가 장기 불능 상태였다(2026-06-20 #2404에서 blocked 확인, 리셋 예정 07-19). 그 사이 이슈 4건(#2404~#2407)이 사용자 승인 하에 @code-reviewer 대체 검토로 처리됐으나, 이 폴백 경로는 어떤 문서에도 정의되어 있지 않아 문서와 실운영이 갈라진 상태다. 단일 외부 벤더 CLI의 한도가 개발 처리량의 병목이 되는 구조 자체가 문제다.
- `/codex:adversarial-review`는 git 작업 상태 리뷰용 커맨드라, 코드가 없는 이슈 본문 계획 리뷰에 쓰는 것은 본래 용도 밖 사용이었다.
- verdict 어휘와 PASS/FAIL 증적 체계는 플러그인 출력이 아니라 프로젝트 오버레이다(플러그인 스키마의 verdict는 `approve`/`needs-attention` 2값뿐). 리뷰 주체를 바꿔도 어휘·라벨·증적 계약은 그대로 재사용할 수 있다.
- Claude Code 네이티브 `/code-review`가 effort 단계와 PR 코멘트 증적을 지원해 브랜치 리뷰 대체재로 충분하다.
- 타 모델 적대 리뷰의 독립성은 약해진다. 별도 컨텍스트 서브에이전트(계획)와 상위 effort 리뷰(고위험)로 부분 보전하고, 남는 차이는 외부 벤더 장애·한도로부터의 독립과 맞바꾼다.
- ante-oracle 런타임이 자동 리포트하는 이슈는 루트원인 추정이 부정확할 수 있어, 구현 전 진실성 검증이 실무 관행으로 이미 요구되어 왔다. @issue-reviewer는 이 관행의 명문화이며, 검증 없이 자동 큐에 들어간 오탐 이슈가 야간 무인 배치에서 잘못된 수정으로 이어지는 경로를 차단한다.

**영향**:

- 개정 대상: 런북 00·01·02·03·04·05, `.agent/commands/` 3종(autopilot, implement-issue, plan-preflight — release.md는 이미 도구 중립), `.agent/skills/` 3종(github-ops, review-pr, receive-review), `.agent/agents/` 2종(backend-dev, code-reviewer), `docs/runbooks/README.md` 인덱스, GitHub 라벨 설명 2건(`blocked:review-loop`, `blocked:pr-review-loop`). 이슈 본문 Implementation Plan 템플릿의 `Codex Plan Review` 섹션명은 plan-preflight.md 개정에 포함된다.
- 신설: `.agent/agents/plan-reviewer.md`, `.agent/agents/issue-reviewer.md`. 런북 02의 에이전트 구성과 런북 00의 이슈 수명주기에 두 에이전트를 반영한다(둘 다 개정 대상에 이미 포함).
- 보존 범위: 코드·테스트 주석의 Codex 리뷰 이력 인용, CHANGELOG, 과거 이슈/PR 증적은 회귀 근거로 보존한다. 제거 완료 기준은 "프로세스 문서·라벨·설정에서 Codex 참조 0건"이며, 이력 참조는 판정에서 제외한다.
- `/codex:status`·`/codex:result` 기반 비동기 회수 절차는 동기 서브에이전트 호출로 대체되어 삭제한다.
- 미참조 잔재(`scripts/ai_review.py`, `scripts/run_ai_review.sh`, `scripts/setup_actions_runners.sh`, `.github/review-output.schema.json`)는 이 결정과 함께 삭제 대상이 된다. 삭제 시 `docs/architecture/generated/project-structure.md` 재생성을 동반한다.
- 이행 순서: (1) 런북·커맨드·스킬 재작성 → (2) GitHub 라벨·코멘트 헤더 재정의 → (3) codex 플러그인 비활성화 및 `.claude/settings.local.json` 권한 정리 → (4) 개인 메모리의 폴백 선례 기록 폐기(런북 명문화 완료 후).
- D-007(외부 AI Agent 연동 방식)은 전략 Agent의 CLI 연동에 대한 결정으로, 본 결정과 무관하게 유지된다.
