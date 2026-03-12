# Ante — 세션 핸드오프

> 이 문서는 다음 에이전트 세션에서 `/next` 명령으로 읽힌다.
> 세션 종료 시 업데이트할 것.

## 프로젝트 요약

**Ante** (AI-Native Trading Engine, 엔티)는 개인 홈서버(Intel N100)에서 구동하는 AI 에이전트 기반 자동 주식 매매 시스템이다. AI Agent가 전략을 개발·검증하고, 시스템이 그 전략을 운용하는 거래 인프라를 제공한다.

- 아키텍처: 이벤트 드리븐 모듈러 모놀리스 (단일 asyncio 프로세스)
- 설계 방식: master-plan-first — 모든 설계를 문서로 확정한 후 구현
- 문서 언어: 한국어 (기술 용어는 영어)

## 구현 진행 상황

### Phase 1 — 코어 인프라 ✅ 완료

| 모듈 | PR | 상태 | 테스트 |
|------|----|------|--------|
| Config (1-2) | #3→develop, #4→main | ✅ 완료 | 17개 |
| EventBus (1-3) | #5→develop, #6→main | ✅ 완료 | 14개 |
| main.py 통합 (1-4) | #5에 포함 | ✅ 완료 | 2개 |
| DynamicConfig | #3에 포함 | ✅ 완료 | 10개 |
| SystemState | #3에 포함 | ✅ 완료 | 7개 |
| Database (core) | #3에 포함 | ✅ 완료 | 5개 |
| EventHistoryStore | #5에 포함 | ✅ 완료 | 4개 |

### Phase 2 — 전략 + 봇 코어 ✅ 완료

| 모듈 | PR | 상태 | 테스트 |
|------|----|------|--------|
| Strategy (2-1) | #7→develop, #8→main | ✅ 완료 | 36개 |
| Rule Engine (2-2) | #9→develop, #10→main | ✅ 완료 | 34개 |
| Treasury (2-3) | #11→develop, #12→main | ✅ 완료 | 24개 |
| Bot (2-4) | #13→develop, #14→main | ✅ 완료 | 22개 |

### Phase 3 — 거래 실행 경로 ✅ 완료

| 순서 | 모듈 | PR | 상태 | 테스트 |
|------|------|----|------|--------|
| 3-1/3-2 | Broker Adapter + KIS | #15→develop, #16→main | ✅ 완료 | 32개 |
| 3-3 | API Gateway | #17→develop, #18→main | ✅ 완료 | 28개 |
| 3-4 | Trade | #19→develop, #20→main | ✅ 완료 | 37개 |

### Phase 4 — 데이터 + 백테스트 (부분 완료)

| 순서 | 모듈 | PR | 상태 | 비고 |
|------|------|----|------|------|
| 4-1 | Data Pipeline | — | ⏭️ 스킵 | polars 미설치, pyproject.toml 수정 불가 |
| 4-2 | Backtest Engine | — | ⏭️ 스킵 | Data Pipeline 의존 |
| 4-3 | Report Store | #21→develop, #22→main | ✅ 완료 | 16개 테스트 |

### Phase 5 — 외부 인터페이스 (부분 완료)

| 순서 | 모듈 | PR | 상태 | 비고 |
|------|------|----|------|------|
| 5-1 | CLI | — | ⏭️ 스킵 | click 미설치, pyproject.toml 수정 불가 |
| 5-2 | Web API | — | ⏭️ 스킵 | fastapi 미설치, pyproject.toml 수정 불가 |
| 5-3 | Notification | #23→develop, #24→main | ✅ 완료 | 14개 테스트 |
| 5-4 | Frontend | — | ⏳ 대기 | React 별도 구현 |

**총 테스트: 302개 (전체 통과)**

## 아키텍처 설계 (완료)

- [x] 모든 주요 설계 결정 완료 → [decisions.md](decisions.md)
- [x] 시스템 아키텍처 문서 → [architecture.md](architecture.md)
- [x] 14개 모듈 세부 설계 문서 (docs/specs/) — 전체 확정
- [x] 크로스 스펙 리뷰 완료 (6 CRITICAL + 15 WARNING 해결)
- [x] 6개 시나리오 기반 설계 검증 완료

## 중요 결정 사항

- **킬 스위치**: 시스템 코어(인메모리 + SQLite), 3채널 제어 (웹/CLI/텔레그램)
- **금액 타입**: `float` + DB `REAL` (다양한 상품 확장성 우선)
- **포지션 단일 소유**: Trade 모듈. Treasury는 현금/예산만, 리스크는 Rule Engine
- **주문 취소/정정**: 룰 검증 생략, APIGateway 직접 처리 (리스크 감소 행위)
- **order_id 추적**: 내부 = OrderRequestEvent.event_id, 증권사 = broker_order_id
- **aiohttp 미포함**: pyproject.toml dependencies 변경 금지. KISAdapter는 connect() 시 conditional import

## 다음 단계

### 의존성 설치 후 구현 가능한 모듈 (pyproject.toml에 의존성 추가 필요)

1. **Data Pipeline (4-1)**: `polars` 추가 후 구현 → specs/data-pipeline.md
2. **Backtest Engine (4-2)**: Data Pipeline 완료 후 구현 → specs/backtest.md
3. **CLI (5-1)**: `click` 추가 후 구현 → specs/cli.md
4. **Web API (5-2)**: `fastapi`, `uvicorn` 추가 후 구현 → specs/web-api.md
5. **Frontend (5-4)**: React 별도 프로젝트

### 권장 작업 순서

```
1. pyproject.toml에 polars, click, fastapi, uvicorn 의존성 추가
2. Data Pipeline → Backtest Engine (Phase 4 완료)
3. CLI → Web API (Phase 5 완료)
4. E2E 통합 테스트 (Phase 6)
```

## 미해결 사항
- DataProviderFactory / PortfolioViewFactory / OrderViewFactory 인터페이스 — Phase 4에서 구체화
- StopOrderManager 개입 위치 — 추후 결정
- PaperExecutor 상세 설계 — 가상 체결 시뮬레이션
- 봇 자동 재시작 정책

## 최종 업데이트
- 2026-03-13 (세션 9 — Report Store + Notification 구현 완료, 302개 테스트 통과)
- 스킵 모듈: Data Pipeline(polars), Backtest(의존성), CLI(click), Web API(fastapi)
