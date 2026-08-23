# D-020: 도구 중립 기여 및 공개 거버넌스 계약 (2026-08-22)

> Ante 설계 결정 기록.
> 인덱스: [README.md](README.md)
> 상태: **Draft — 사용자 승인 전**
> 수용 시 관계: D-019의 Claude Code 수행 주체 고정 부분을 부분 대체한다.

**결정**: Ante의 공식 개발·기여 완료 조건은 특정 AI 모델, CLI, 플러그인, 슬래시 명령 또는 로컬 세션이 아니라 공개 저장소에 버전 관리되는 스펙·기여 규칙, GitHub Issue/PR, 재현 가능한 검증 명령, CI 결과와 maintainer 판단으로 정의한다. 기여 인터페이스와 자동화 수준은 달라질 수 있으나, 저장소 전체의 수용 기준은 실행 주체나 개발용 AI provider에 따라 달라지지 않으며 특정 AI provider의 사용을 요구하지 않는다. Claude Code 등 provider별 자동화는 그 기준을 편리하게 수행하는 선택 어댑터로 둔다. 이 결정에서 provider는 개발용 AI 모델·Agent 도구 공급자를 뜻하며, GitHub는 Ante가 선택한 공개 forge로서 추상화 대상에 포함하지 않는다.

**구성**:

- **공개 기여 범위**:
  - Ante는 외부의 이슈와 PR을 받고 공개된 기준으로 검토하는 오픈소스 프로젝트로 운영한다.
  - 유지관리 지원은 단독 maintainer의 가용 범위 안에서 best-effort로 제공하며, 응답이나 병합을 보장하지 않는다.
  - 현재 거버넌스는 공개적으로 문서화된 owner-led 방식으로 둔다. Maintainer는 범위, 설계, 병합, 릴리스와 보안 대응의 최종 책임을 지고, 주요 정책 변경은 스펙·ADR·Issue/PR에 근거와 함께 남긴다.
  - 기여는 사람인지 AI인지 또는 어떤 제품을 사용했는지가 아니라 스펙 적합성, 검증 결과, 위험과 유지보수성으로 평가한다. 제출자는 AI 생성 여부와 무관하게 변경의 정확성, 라이선스 적합성, 보안을 동일하게 책임진다.
  - 외부 이슈와 PR은 한국어 또는 영어로 제출할 수 있다. 상세 설계문서의 기준 언어는 한국어를 유지할 수 있으나, `README.md`, `CONTRIBUTING.md`와 Issue/PR 진입점은 최소한 영어 요약을 함께 제공한다. 번역이 충돌하면 canonical 한국어 문서를 우선한다.
- **공통 SSOT 경계**:
  - 현재 제품 계약은 `docs/specs/`, 결정 이유와 대체 이력은 `docs/decisions/`, 사용자 운용법은 `guide/`를 정본으로 둔다.
  - 공개 기여 절차와 합격 조건의 정본은 `CONTRIBUTING.md`로 둔다. `SECURITY.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`는 각각 보안 신고, 행동 규범, 권한·의사결정만 소유한다. `AGENTS.md`는 Agent 탐색·실행 지침의 진입점이고 GitHub 이슈·PR 템플릿은 입력 수집 표면이다. 두 표면 모두 해당 관심사의 정본을 참조하며 합격 조건을 복제하거나 재정의하지 않는다. 충돌 시 해당 관심사를 소유한 canonical 문서가 우선한다.
  - 기여자가 재현해야 하는 CI check는 저장소가 소유하고 문서화한 로컬 실행 명령을 사용한다. 권한·플랫폼 의존 검사는 별도로 표시할 수 있으며, 특정 provider 명령의 성공 여부를 공용 합격 조건으로 사용하지 않는다.
  - Git에 기록한 정책은 원하는 상태(desired state), GitHub 보호 규칙·보안 기능·runner·secret metadata 등은 실제 운영 상태(runtime state)로 구분한다. 저장소에는 secret의 이름·필요 권한·회전·복구 계약만 기록하고 값은 기록하거나 조회하지 않는다. API가 노출하는 상태는 읽기 전용으로 대조하고, 관측할 수 없는 속성은 비파괴 기능 점검이나 maintainer 확인으로 검증한다.
  - 생성 문서는 코드·스키마·생성기에서 파생된 산출물로 표시한다. 생성 결과 자체를 SSOT로 선언하지 않으며, 재생성 또는 `--check`로 드리프트를 검증한다.
- **사람·Agent 공통 불변조건**:
  - 수용된 구현 작업은 canonical 스펙과 승인된 이슈 범위를 먼저 확인한다.
  - 기본 브랜치에 직접 push하지 않고 작업 브랜치와 PR을 사용한다. 내부 자동화는 추가 격리가 필요할 때 worktree를 사용할 수 있다.
  - 변경에 필요한 테스트·정적 검사·생성물 검사를 공개된 명령으로 실행한다.
  - 동작 변경 PR에는 연결 이슈, 변경 범위, 검증 결과, 스펙 영향과 잔여 위험을 남긴다. 비동작 사소한 변경과 release PR의 예외는 `CONTRIBUTING.md`와 release 정책에 명시한다.
  - 필수 CI, 충돌 없음, 대화 해결과 maintainer의 merge-ready 판단을 만족해야 병합할 수 있다.
  - 위 조건을 만족하는 주체를 특정 모델이나 provider를 사용하지 않았다는 이유로 배제하지 않는다.
- **provider 어댑터 경계**:
  - `.agent/`, `.claude/`와 provider별 설정은 역할 프롬프트, 슬래시 명령, 모델·effort 선택, 자동화 편의를 담을 수 있다.
  - 필수 결론, 검증 명령과 결과, 잔여 위험이 Git 추적 문서 또는 공개 Issue/PR/check/review에 기록될 때 프로젝트 증거로 인정한다. 원시 프롬프트, 비공개 세션과 내부 추론 전문은 공개 증거로 요구하지 않는다. Provider 어댑터가 만든 결과도 동일한 공개 형태로 남길 수 있어야 한다.
  - provider 어댑터는 공개 기여 전체의 유효성·merge 기준을 추가하거나 재정의할 수 없다. 본 결정이 허용한 trusted lane 내부에는 사전 자동화 게이트를 둘 수 있지만, provider-neutral 수동 경로를 함께 제공하고 그 실패를 외부 기여의 유효성 판단에 적용하지 않는다. 어댑터 문서는 canonical 문서를 링크하고 공통 계약을 복제하지 않는다.
  - 도구 중립성은 모든 provider의 기능 동등성이나 자동화를 보장한다는 뜻이 아니다. 특정 provider 없이 수행 가능한 수동 reference path가 있으면 공통 계약을 충족한다.
  - 현행 `.agent/`와 `.claude/` 경로는 이 결정만으로 일괄 이동하지 않는다. 공통 정책을 공개 문서와 검증 명령으로 옮긴 뒤, 실제 소비자에 맞춰 provider 전용 내용을 점진적으로 정리한다.
  - 반복되고 안정된 공통 의미와 실제 유지비 절감이 확인되기 전에는 범용 Agent orchestration 또는 plugin framework를 만들지 않는다. 도입이 필요해지면 별도 ADR로 결정한다.
- **이슈 수명주기**:
  - 외부 버그 신고와 변경 제안은 스펙 반영 전에도 미분류 접수 상태로 받을 수 있다. 접수는 구현 승인과 동일하지 않다.
  - maintainer는 재현 가능성, 중복, 지원 범위와 스펙 영향을 확인해 추가정보 필요, 중복, 거절 또는 수용 상태로 분류한다. 분류 결과는 maintainer가 공개 이슈 코멘트에 기록하고, machine-readable 라벨 매핑은 이슈 관리 런북에서 정의한다.
  - 스펙에 없는 동작을 구현하기로 수용한 경우에는 스펙 또는 ADR을 먼저 반영한 뒤 구현 가능한 이슈로 전환한다.
  - 신고자에게 코드 영향 경계, 회귀 테스트 위치, 내부 계약 소비자처럼 구현자에게 속하는 분석을 필수로 요구하지 않는다. 이 정보는 maintainer나 구현 Agent가 triage·계획 단계에서 보강한다.
  - Agent가 발견한 후보는 중복 제거와 maintainer가 기록한 수용 상태 없이 자동 구현 큐로 승격하지 않는다. `@issue-reviewer`의 `confirmed` verdict나 오케스트레이터 판단만으로 수용 상태를 대체하지 않는다.
- **PR 신뢰 경계**:
  - same-repository PR과 fork PR은 권한·자동화가 다른 운영 레인으로 구분하되, 저장소 위치만으로 코드를 신뢰하지 않는다. Maintainer가 검토·승인하지 않은 코드, metadata와 산출물은 untrusted로 취급한다.
  - provider별 검증은 무인 자동 병합의 추가 안전 조건으로 사용할 수 있다. 기여자에게 해당 provider 사용을 요구하거나 수동 maintainer 병합의 유일한 승인 근거가 될 수 없으며, provider 장애 시 사용할 공개된 수동 fallback을 제공해야 한다.
  - fork PR은 repository·maintainer secret을 주입하지 않고 `contents: read` 최소 권한의 단기 `GITHUB_TOKEN`만 사용하는 GitHub-hosted CI에서 검증한 뒤 maintainer가 직접 triage·검토한다.
  - 외부 PR 코드는 기본적으로 repository-controlled self-hosted runner나 홈서버에서 실행하지 않는다. Disposable runner, 네트워크·자격증명 격리와 실행 후 폐기를 별도 보안 결정으로 승인한 경우에만 예외로 둔다.
  - 권한 있는 workflow는 maintainer가 승인한 정확한 commit SHA만 대상으로 한다. `pull_request_target`, `workflow_run` 또는 동등한 권한 이벤트에서 신뢰하지 않은 코드를 checkout·실행하거나, untrusted artifact·cache를 검증 없이 소비하거나, PR 제목·브랜치명 같은 untrusted metadata를 shell에 직접 보간하지 않는다.
  - write token, repository/environment secret 또는 배포 자격증명을 사용하는 workflow는 검토 대상 코드를 실행하지 않고 fork-triggered 실행 경로에 연결하지 않는다. 외부 PR은 공개 기준을 통과한 뒤 maintainer가 일반 GitHub 병합 경로로 병합한다.
- **리뷰와 승인**:
  - D-019의 `Plan Review`, `브랜치 리뷰`, `reviewer:` 증적과 verdict 어휘는 내부 자동화 계약으로 재사용할 수 있다.
  - Claude Code `/code-review` PASS나 특정 `model:` 값은 저장소 전체의 PR 생성·병합 필수조건으로 사용하지 않는다.
  - 단독 maintainer 단계에서는 비저자 인간 승인이나 CODEOWNERS 승인을 필수화하지 않는다. 재현 가능한 CI와 공개된 maintainer 판단을 기본 게이트로 둔다.
  - 필수 check 통과는 병합의 필요조건이지 병합 권리가 아니다. Maintainer는 범위, 스펙, 보안과 유지보수성을 근거로 변경 요청이나 병합 거절을 결정할 수 있다.
  - 실제 공동 maintainer가 합류하면 organization 이전, CODEOWNERS, 비저자 승인, release·복구 권한 분리를 별도 결정으로 검토한다.
- **오픈소스 보안 기준선**:
  - [OSPS Baseline v2026.02.19](https://baseline.openssf.org/versions/2026-02-19.html)의 적용 가능한 Level 1 통제를 평가 기준으로 고정한다. 통제별 적용 여부, 증거와 미충족 gap을 maintainer 보안 점검표에 기록하고, 적용 통제가 모두 충족되기 전에는 Level 1 준수를 선언하지 않는다. 새 Baseline 버전 채택은 별도 검토한다.
  - 거래·계좌 자격증명을 다루는 위험을 근거로 `SECURITY.md`, 비공개 취약점 신고 경로와 공개 저장소 코드에서 홈서버·배포 자격증명을 격리하는 것을 필수 desired state로 둔다.
  - 공개 수용 검사는 실제 거래 계정, 운영 secret, 개인 금융 데이터, 홈서버 접근 또는 비공개 dataset을 요구하지 않는다. 자격증명 의존 검증은 maintainer 전용 후속 검사로 분리하며 공개 필수 check로 삼지 않는다. Issue·PR·로그에는 실제 자격증명과 개인 거래 데이터를 제출하지 않는다.
- **결정 이력**:
  - 수용된 ADR의 과거 결정과 당시 근거를 현재 정책처럼 다시 쓰지 않는다.
  - 정책을 바꿀 때는 새 ADR이 대체 범위를 명시하고, 구 ADR은 상태 링크와 함께 역사 기록으로 보존한다.

**근거**:

- Ante 런타임과 전략 인터페이스는 특정 LLM SDK를 요구하지 않으며, 인간과 Agent가 공유하는 CLI/IPC·구조화 출력 원칙도 이미 모델 중립적이다. 제품 코어를 다시 설계하기보다 개발·기여 운영 경계를 맞추는 편이 변경 범위와 위험이 작다.
- D-019는 외부 Codex 사용량 한도가 필수 리뷰 게이트를 장기간 막은 경험을 근거로 단일 provider 장애가 개발 처리량의 병목이 되는 문제를 정확히 진단했다. 그러나 해결책으로 Claude Code 네이티브 게이트를 공통 필수 경로에 고정해 같은 종류의 결합이 다른 provider로 이동했고, 타 모델 적대 리뷰의 독립성이 약해졌음을 스스로 기록했다.
- 결정 당시 PAT 기반 merge automation은 `.github/workflows/pr-approvals.yml` 조건상 same-repository PR만 처리하는 권한 있는 내부 자동화 레인이다. 저장소 위치만으로 코드 신뢰가 보장되지는 않지만, 공개 fork PR은 read-only CI 이후 write 권한이 있는 동일 경로로 자동 인계되지 않으므로 별도의 공개 triage·review 경로를 명문화해야 한다.
- 외부 신고자는 저장소 내부 라벨 권한, Claude 명령, Agent 역할 또는 구현계획 형식을 알 필요가 없다. 신고 접수와 구현 승인·계획을 분리해야 외부 접근성을 낮추지 않으면서 Ante의 스펙 우선 원칙을 유지할 수 있다.
- 모델별 runner와 GitHub 보호·보안 설정은 Git 트리에서 참조가 사라져도 원격에 남을 수 있다. 공개 저장소의 정책 SSOT만 정의해서는 실제 운영 상태의 드리프트를 발견할 수 없으므로 원하는 상태와 원격 점검을 함께 관리해야 한다.
- 저장소에는 이미 Issue/PR/CI라는 도구 중립 공통분모가 있다. 별도의 범용 다중 모델 프레임워크나 새 증적 프로토콜을 만드는 것보다 기존 공개 객체와 검증 명령을 정본으로 삼는 것이 YAGNI에 부합한다.

**검토한 대안**:

- **현행 Claude 전용 완료 경로 유지**: 현재 처리량에는 유리하지만 provider 장애·요금·기능 변경이 다시 필수 게이트를 멈출 수 있고 외부 기여자가 같은 절차를 재현할 수 없어 채택하지 않는다.
- **모든 provider를 감싸는 자체 orchestration framework 구축**: 반복되고 안정된 공통 의미나 실제 유지비 절감이 검증되지 않았고 새로운 코어와 호환성 유지비가 생기므로 채택하지 않는다.
- **내부 AI 계획·리뷰 게이트 전면 제거**: 단독 maintainer의 self-review와 자동화 안전장치로 가치가 있으므로 제거하지 않는다. 다만 trusted lane의 provider 어댑터로 범위를 제한한다.
- **지금 CODEOWNERS와 비저자 승인 1개 강제**: 현재 단독 maintainer가 자신의 PR을 승인할 수 없어 개발이 정지하므로 보류한다. 공동 maintainer가 실제 합류할 때 재검토한다.
- **모든 문서와 대화를 즉시 영어로 전환**: 기존 한국어 스펙의 대규모 번역·동기화 비용이 크므로 채택하지 않는다. 외부 진입점과 제출 언어만 먼저 개방한다.

**비목표**:

- `src/ante` 런타임 아키텍처, 전략 API, CLI/IPC 계약 변경
- 마이크로서비스 전환 또는 프로젝트 디렉토리 전면 재배치
- `.agent/`·`.claude/`의 즉시 삭제나 모든 provider 참조 제거
- 모든 과거 이슈·PR·CHANGELOG의 provider 이름 제거
- GitHub organization, TSC, merge queue, CLA, CODEOWNERS 강제 승인 도입
- 범용 LLM plugin API 또는 provider별 빈 디렉토리 선생성
- 공개 기여의 자동 병합 또는 응답·병합 SLA 보장

**영향**:

- **D-019 관계**: 본 결정이 수용되면 D-019에서 Claude Code 안의 `@plan-reviewer`와 `/code-review`를 모든 구현·PR의 공통 필수 경로로 보는 부분을 부분 대체한다. D-019의 단일 provider 병목 진단, 증적 어휘, verdict·라벨 상태 기계, 외부발 이슈 검증과 내부 trusted lane 리뷰 루프는 보존한다. 다만 `.agent/skills/github-ops.md`를 공통 증적 계약의 SSOT로 둔 부분과 `confirmed`만으로 자동 큐 진입이 가능하다는 해석은 대체한다. 공개 합격·증적 의미는 `CONTRIBUTING.md`, 내부 상태 매핑은 canonical maintainer 런북으로 이동하고 provider 어댑터는 이를 참조한다. D-019의 당시 Codex 제거 완료 판정은 역사적 전환 결과로 보존하며, D-020 이후에는 공통 계약에 특정 provider 명령이 필수가 아닌지를 기준으로 삼는다. D-019에는 부분 대체 상태 링크를 추가하고 역사 기록으로 유지한다.
- **관련 결정**: D-010의 Agent 친화적 설계 원칙을 개발·기여 Agent까지 확장한다. D-007의 전략 Agent CLI 연동과 D-018의 CLI/IPC 중심 런타임 결정은 변경하지 않는다.
- **공개 정책 개정 대상**: `AGENTS.md`, `docs/decisions/README.md`, `docs/runbooks/README.md`, `00-issue-management.md`, `01-development-process.md`, `02-agent-structure.md`, `03-git-workflow.md`, `04-ci-cd.md`, `05-testing.md`에서 주체와 합격 조건을 도구 중립 용어로 재정의한다. 세부 실행 명령을 모든 문서에 복제하지 않고 공개 기여 계약과 검증 진입점을 참조하게 한다. 결정 인덱스의 "과거 결정을 직접 수정" 규칙은 대체 ADR과 상태 링크로 이력을 보존하는 규칙으로 바꾼다.
- **공개 진입점 신설 대상**: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, PR 템플릿과 Issue Form chooser 설정을 추가한다. 공개 버그 신고 필드와 maintainer 구현계획 필드를 분리한다.
- **provider 어댑터 영향**: `/plan-preflight`, `/implement-issue`, `/autopilot`, `/code-review`는 trusted lane의 선택 자동화로 유지할 수 있다. 각 문서는 어떤 공개 상태와 검증 결과를 생성하는지 설명하고, 자신만이 유일한 수행 수단이라고 선언하지 않는다.
- **자동화 영향**: 기여자가 재현해야 하는 CI check에 대응하는 도구 중립 로컬 검증 진입점을 추가한다. Same-repository와 fork의 자동화 차이, 승인된 SHA와 write credential 경계를 명시하고, fork PR에는 최소 권한 CI와 사람 인계 경로를 제공한다.
- **운영 설정 영향**: 공개 PR 실행 경계, self-hosted runner 인벤토리, branch protection, Actions 권한, vulnerability reporting·scanning의 원하는 상태와 확인 방법을 maintainer 문서에 기록한다. 현재 원격 값을 ADR에 고정하지 않고 별도 운영 점검으로 관리한다.
- **운영 비용과 호환성**: 공개 계약과 provider 어댑터의 매핑을 함께 유지하고 외부 이슈·PR을 사람이 triage하는 비용이 새로 생긴다. 과거 `Claude`·`Codex` 이름이 포함된 Issue/PR 증적과 결정 기록은 읽기 호환으로 보존하며, 중립화를 이유로 이력을 일괄 변경하지 않는다.
- **이행 순서**: (1) 공개 기여·보안·거버넌스 계약 추가 → (2) `AGENTS.md`와 런북의 공통 불변조건 중립화 → (3) 검증 진입점과 fork PR 인계 경로 검증 → (4) 원격 runner·보안·보호 설정 감사 및 정리 → (5) 비Claude 주체의 clean-clone E2E 기여 시험 → (6) 실제 사용 증거가 생긴 범위에서만 provider 디렉토리와 문서 구조를 점진 정리한다.
- **이행 완료 검증**:
  - Claude 전용 명령 없이 사람 또는 다른 Agent가 clean clone에서 스펙 확인, 브랜치 작업과 로컬 검증까지 완료할 수 있다. Fork workflow의 정적 신뢰 경계를 먼저 감사하고, 첫 실제 외부 fork PR에서 제출·CI·maintainer 인계 경로를 동적으로 확인한다.
  - 공개 `CONTRIBUTING.md`와 PR 합격 조건에 특정 모델·provider 필수 명령이 없다.
  - 외부 버그 신고는 스펙·테스트 위치·코드 영향 경계를 미리 알지 못해도 접수되고, 구현 승인 전에 maintainer triage를 거친다.
  - 외부 PR 코드는 별도 보안 결정으로 승인된 격리형 예외가 아니면 repository-controlled self-hosted runner나 홈서버에서 실행되지 않고 배포 secret에 접근하지 않는다.
  - 읽기 전용 API가 노출하는 범위에서 원하는 GitHub 운영 설정과 실제 원격 상태의 차이를 식별할 수 있고, 비관측 항목의 별도 검증 절차가 문서화되어 있다.
  - 비공개 AI 세션의 정보 없이 공개 Issue/PR/check/review만으로 merge 조건을 판정할 수 있다.
  - 기존 Claude 자동화는 공통 계약을 참조하는 선택 어댑터로 계속 동작한다.
