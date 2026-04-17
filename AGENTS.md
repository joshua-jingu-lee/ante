# Ante (AI-Native Trading Engine)

## 목적

Ante는 개인 홈서버 구동을 전제로 하는 자동 매매 시스템이다.
이 문서는 Ante 개발 및 유지보수를 위한 마스터 문서다.
에이전트는 이 문서 및 연결된 설계문서를 바탕으로 구현체가 설계 의도에서 벗어나지 않도록 관리한다.

## 정체성

Ante는 **개인의 홈서버 위에 존재하는 작은 투자 회사**다.

- **사용자**는 이 회사의 대표다. 전략 채택과 운용 여부를 최종 결정한다.
- **AI Agent**는 회사의 직원이다. 시장을 조사하고 투자 전략을 고안하여 시스템에 제출하고 결과를 모니터링 한다.
- **Ante 시스템**은 회사의 인프라다. 직원이 고안한 전략을 검증하고, 전략에 따라 실제 투자 업무를 수행하며, 업무 중 발생할 수 있는 사고에 대비한 안전장치를 제공하고, 수행 결과를 평가하여 더 나은 전략 개발을 위한 피드백을 돌려준다.

이 관점에서 Ante의 역할은 네 가지로 정리된다:

1. **전략 검증 지원**: Agent가 제출한 전략의 유효성을 정적 분석과 백테스트로 검증한다.
2. **투자 실행**: 채택된 전략에 따라 봇이 실제 매매를 수행한다.
3. **안전 관리**: 전역·전략별 거래 룰로 손실을 통제하고, 이상 상황 시 자동으로 개입한다.
4. **성과 피드백**: 거래 기록과 성과 지표를 축적하여 전략 개선의 근거를 제공한다.

## 설계 철학

- **Agent 잠재성 우선**: 시스템이 AI Agent의 자유로운 활동을 제약해서는 안 된다. Ante는 거래 실행과 안전 규칙만 담당하는 얇은 인프라에 머물고, 나머지 판단 영역은 Agent에게 열어둔다.
- **전략 전권 위임**: 전략의 설계와 수행은 AI Agent에게 최대한 일임한다. 전략은 정량적(가격, 지표) + 정성적(뉴스, 사건) 데이터를 자유롭게 활용할 수 있으며, 각 전략은 독립 모듈로 존재하여 시스템 코어와 완전히 분리된다.
- **인간-AI 공용 인터페이스**: Ante의 모든 인터페이스(웹 대시보드, REST API, CLI, MCP 등)는 사용자와 AI Agent가 함께 사용하는 것을 전제로 설계한다. 사람이 읽기 좋은 UI와 Agent가 다루기 좋은 구조화된 출력을 동시에 지원하며, 어느 한쪽을 위한 설계가 다른 쪽의 사용성을 희생시키지 않도록 한다.

## 기술 및 아키텍처

> 상세 설계: [docs/architecture/README.md](docs/architecture/README.md)
> 대시보드(프론트엔드): [docs/dashboard/architecture.md](docs/dashboard/architecture.md)
> 설계 결정 이력: [docs/decisions/README.md](docs/decisions/README.md)

## 개발 프로세스
> 이슈 관리: [docs/runbooks/00-issue-management.md](docs/runbooks/00-issue-management.md)
> 개발 프로세스: [docs/runbooks/01-development-process.md](docs/runbooks/01-development-process.md)
> 에이전트 구조: [docs/runbooks/02-agent-structure.md](docs/runbooks/02-agent-structure.md)
> Git 워크플로우: [docs/runbooks/03-git-workflow.md](docs/runbooks/03-git-workflow.md)
> CI/CD: [docs/runbooks/04-ci-cd.md](docs/runbooks/04-ci-cd.md)
> 테스트 전략: [docs/runbooks/05-testing.md](docs/runbooks/05-testing.md)

## 프로젝트 디렉토리 구조

> 파일 단위 상세 구조: [docs/architecture/generated/project-structure.md](docs/architecture/generated/project-structure.md)


## 향후 계획
- 개인 운용으로 충분히 검증 후 오픈소스 공개 고려

## 규칙
- 모든 대화는 **한국어**로 진행한다.
- (깃허브) 이슈 등록 전에는 반드시 스펙 선반영 여부를 확인하고, 스펙에 없으면 반영 여부를 묻는다.
- 메인 브랜치는 직접적인 허가가 없으면 절대 수정하지 않는다.
- 사용자의 질문에 임의로 대답하지 않는다. 항상 스펙문서를 확인 후 답변한다.
- .gitignore 에 등록된 파일은 커밋 여부를 묻지 않는다.
