# 05. 테스트 전략

> 테스트 프레임워크, 구조, 커버리지 기준을 정의한다.

---

## 1. 테스트 프레임워크

| 도구 | 용도 |
|------|------|
| `pytest` | 테스트 실행 |
| `pytest-asyncio` | async 테스트 지원 |
| `pytest-cov` | 커버리지 측정 |

## 2. 테스트 구조

```
tests/
├── conftest.py              # 공통 fixture
├── unit/                    # 단위 테스트 (pytest)
│   ├── test_eventbus.py
│   ├── test_config.py
│   ├── test_bot.py
│   ├── test_strategy.py
│   ├── test_rule.py
│   ├── test_treasury.py
│   ├── test_broker.py
│   ├── test_gateway.py
│   ├── test_data.py
│   ├── test_backtest.py
│   ├── test_trade.py
│   ├── test_report.py
│   ├── test_notification.py
│   └── test_cli.py
├── integration/             # 통합 테스트 (pytest)
│   ├── test_order_flow.py
│   ├── test_bot_lifecycle.py
│   └── test_backtest_e2e.py
```

## 3. 테스트 유형별 가이드

### 3.1 단위 테스트

- 모듈 하나의 로직을 격리하여 테스트
- 외부 의존성(DB, API, 파일)은 mock/fixture로 대체
- 각 모듈 구현 시 함께 작성

```python
# tests/unit/test_eventbus.py 예시
import pytest
from ante.eventbus import EventBus

@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe("OrderRequest", handler)
    await bus.publish("OrderRequest", {"symbol": "005930"})

    assert len(received) == 1
```

### 3.2 통합 테스트

- 복수 모듈이 EventBus를 통해 협력하는 흐름 검증
- 실제 SQLite(임시 DB) 사용, 외부 API는 mock

```python
# tests/integration/test_order_flow.py 예시
@pytest.mark.asyncio
async def test_order_request_to_fill():
    """주문 요청 → 룰 검증 → 자금 확인 → 체결까지의 전체 흐름"""
    # EventBus + RuleEngine + Treasury + BrokerAdapter(mock) 연동
    ...
```

### 3.3 백테스트 테스트

- subprocess 격리 실행 검증
- 작은 샘플 Parquet 데이터로 테스트

## 4. Fixture 전략

```python
# tests/conftest.py
import pytest
import tempfile

@pytest.fixture
def config(tmp_path):
    """임시 설정 파일 기반 Config 인스턴스"""
    ...

@pytest.fixture
def eventbus():
    """EventBus 인스턴스"""
    ...

@pytest.fixture
def db_path(tmp_path):
    """임시 SQLite DB 경로"""
    return tmp_path / "test.db"
```

## 5. 커버리지 기준

| 대상 | 기준 |
|------|------|
| 신규 코드 | 80% 이상 |
| 핵심 로직 (주문, 자금, 룰) | 90% 이상 |
| 전체 프로젝트 | 75% 이상 (점진 상향) |

- 단순 데이터 클래스, 설정 로딩 등은 커버리지에서 제외 가능

## 6. 테스트 실행 명령

```bash
# 단위 테스트만
pytest tests/unit/ -v

# 통합 테스트만
pytest tests/integration/ -v

# 전체 + 커버리지
pytest tests/ -v --cov=src/ante --cov-report=term-missing

# 특정 모듈만
pytest tests/unit/test_eventbus.py -v

# 특정 테스트만
pytest tests/unit/test_eventbus.py::test_publish_subscribe -v
```

## 7. 프론트엔드 API 타입 경계 검사

대시보드 API 계약은 OpenAPI generated type을 wire contract로 사용하고,
`frontend/src/api/*.ts` adapter가 UI/domain model로 변환한다.

```bash
# report-only 진단
cd frontend && npm run check-api-types

# blocking/CI 기준
cd frontend && npm run check-api-types:strict
```

- `check-api-types:strict`는 findings가 1건 이상이면 non-zero로 종료한다.
- GitHub Actions job 이름은 `frontend-api-types`이며 최종 `ci` aggregate job의 입력이다.
- 기준선은 findings 0이다. baseline/allowlist는 두지 않는다.
- generated type import는 `frontend/src/api/*.ts`와 `frontend/src/types/api.generated.ts`에만 허용한다.
- 수동 `Response`, `Request`, `Payload` 타입 선언은 `api.generated.ts` 밖에서 금지한다.
- `client.get/post/put/patch/delete` 호출은 adapter 안에서 generated response type parameter를 명시한다.
- `as unknown as`는 API adapter의 `toXxxView()` mapper 내부에서만 예외적으로 허용한다.

## 8. 배포 이미지 시뮬레이션 테스트

기존 repo-local QA 체계는 1.0 테스트 계약에서 제외한다.
저장소는 더 이상 QA 전용 Docker image, QA compose, TC 파일, QA seed script를
제공하지 않는다.

배포 이미지 기반 시뮬레이션 검증은 별도 테스트 전용 프로그램에서 정의한다.
그 프로그램은 외부에서 제공된 Ante Docker image를 입력으로 받아 public API,
CLI, process lifecycle, health endpoint를 검증해야 하며, repo 내부 DB 직접
시딩이나 QA 전용 entrypoint에 의존하지 않는다.

## 9. 에이전트의 테스트 작성 규칙

### 9.1 단위/통합 테스트 (`@backend-dev`, `@frontend-dev`)

- 모듈 구현 PR에 해당 모듈의 단위 테스트를 반드시 포함
- 테스트 없는 코드는 내부 `/codex:review` 브랜치 리뷰에서 blocking failure로 판정한다
- 테스트 실패 시 구현 코드를 수정하여 통과시킨 후 PR 업데이트
