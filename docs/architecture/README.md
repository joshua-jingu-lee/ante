# Ante 시스템 아키텍처

> 이 문서는 Ante 아키텍처 문서의 인덱스다.
> 정체성과 설계 철학은 [AGENTS.md](../../AGENTS.md), 설계 결정 이력은 [decisions/README.md](../decisions/README.md), 모듈별 세부 설계는 [specs/](../specs/)를 참조한다.
>
> 생성 문서:
> [CLI Reference](../../guide/cli.md) · [DB Schema](generated/db-schema.md) · [프로젝트 구조](generated/project-structure.md)

## 기술 스택

| 영역 | 선택 | 결정 |
|------|------|------|
| 언어 | Python | D-001 |
| 아키텍처 패턴 | 이벤트 드리븐 모듈러 모놀리스 — 단일 asyncio 프로세스 | D-002 |
| 시세 데이터 저장 | Parquet | D-006 |
| 운영 데이터 저장 | SQLite WAL 모드 | D-006 |
| 웹 백엔드 | FastAPI | D-008 |
| 웹 프론트엔드 | React + TradingView Lightweight Charts | D-008 |
| AI Agent 연동 | CLI 인터페이스 (+ 향후 MCP 고려) | D-007 |

**운영 환경**: 인텔 N100 기반 홈서버 (4코어, TDP 6W), VM 위에서 구동. 저전력·경량 환경이므로 백테스트는 벡터화 연산(numpy/polars) 기반으로 CPU 병목에 대응한다. 서버에는 Python 런타임만 필요하며, React 빌드는 개발 머신 또는 CI에서 수행 후 정적 파일로 배포한다.

**저장 용량 제약**: VM 할당 가능 용량 약 60GB. 초기 운영 시 10~15GB 수준으로 충분하며, 데이터 보존 정책 및 외부 이관 경로 설계 필요.

## 아키텍처 개요

**패턴**: 이벤트 드리븐 모듈러 모놀리스 (Event-Driven Modular Monolith)

- 단일 asyncio 프로세스 위에서 모든 핵심 컴포넌트가 동작
- 핵심 흐름(주문, 시스템 이벤트, 알림)은 EventBus를 통해 통신
- 데이터 조회, 자금 확인 등 요청-응답 성격의 호출은 직접 호출
- 백테스트 엔진만 별도 subprocess로 격리 실행
- 각 봇은 독립 asyncio.Task로 운영되며, 봇 단위 예외 격리 적용

## 문서 구성

| 문서 | 내용 |
|---|---|
| [system-diagram.md](system-diagram.md) | 시스템 구성도, 데이터 계층 구조, 통신 방식, 주문 처리 흐름 |
| [module-map.md](module-map.md) | 모듈 책임, 확장성 고려, 배포 산출물 |
| [generated/db-schema.md](generated/db-schema.md) | SQLite 스키마 전체 목록 |
| [generated/project-structure.md](generated/project-structure.md) | 프로젝트 디렉토리 구조 |

## 읽기 순서

1. 이 문서에서 기술 스택과 전반적 패턴을 확인한다.
2. [system-diagram.md](system-diagram.md)에서 런타임 구조와 데이터/이벤트 흐름을 본다.
3. [module-map.md](module-map.md)에서 각 모듈의 책임과 경계를 확인한다.
4. 필요 시 `docs/specs/<module>/` 아래 세부 스펙으로 내려간다.
