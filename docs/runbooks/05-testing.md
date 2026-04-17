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
└── tc/                      # QA TC (Gherkin .feature 파일)
    ├── README.md             # QA 환경 기본값, 전략 파일, 실행 가이드
    ├── scenario/             # 설치/초기화 시나리오
    ├── member/               # 인증/멤버 관리
    ├── account/              # 계좌 CRUD/라이프사이클
    ├── treasury/             # 자금 관리/할당
    ├── strategy/             # 전략 등록/조회
    ├── bot/                  # 봇 생성/라이프사이클
    ├── config/               # 동적 설정
    └── trade/                # 거래 조회
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

## 7. QA TC 테스트 (Gherkin)

### 7.1 개요

`tests/tc/` 하위의 `.feature` 파일은 Docker QA 환경에서 실행되는 수용 테스트다. pytest 단위/통합 테스트와는 별개의 레이어로, 실제 서버를 대상으로 API 호출과 CLI 실행을 검증한다.

### 7.2 실행 환경

- **Docker 컨테이너**: `docker-compose.qa.yml`로 QA 서버 기동
- **test 브로커**: GBM 시뮬레이션 기반 가상 시세 (credentials: `app_key=test`, `app_secret=test`)
- **QA Admin**: `member_id=qa-admin`, `password=qa-password`

### 7.3 담당 에이전트

- **TC 실행**: `@qa-engineer` 에이전트 (`/qa-test`, `/qa-sweep` 커맨드)
- **TC 작성**: `@qa-engineer` 에이전트
- **Step 해석 규칙**: `.agent/skills/qa-tester/` 스킬 참조

### 7.4 TC 실행 명령

```bash
# 단일 카테고리
/qa-test account

# 특정 파일
/qa-test bot/lifecycle

# 전수 검사
/qa-sweep

# 전수 검사 + FAIL 자동 수정
/qa-sweep --fix
```

### 7.5 데이터 초기화 전략

QA TC는 반복 실행을 전제로 한다. 이전 실행에서 생성된 데이터가 잔존하면 등록·상태 변경 시나리오가 실패하므로, 각 Feature는 **자체적으로 테스트 데이터를 정리**해야 한다.

#### 원칙

| 항목 | 규칙 |
|------|------|
| **책임 범위** | 각 Feature가 자신이 생성한 데이터를 정리한다 |
| **정리 시점** | Feature 시작 전(setup) — 이전 실행 잔존 데이터를 제거한다 |
| **정리 방식** | Background에서 삭제 API/CLI를 호출하되, 데이터가 없어도 실패하지 않도록 한다 (멱등성) |
| **bootstrap 데이터** | QA 환경이 제공하는 초기 데이터(`qa-admin` 등)는 정리 대상이 아니다 |

#### 패턴

```gherkin
Background:
  Given ante-qa 컨테이너가 실행 중이다
  And QA Admin 인증 토큰이 확보되어 있다
  # setup — 이전 실행 잔존 데이터 정리 (실패 무시)
  And DELETE /api/members/qa-test-agent-01 요청 (실패 무시)
  And DELETE /api/members/qa-test-human-01 요청 (실패 무시)
```

- `(실패 무시)` 접미사는 404 등 오류 응답을 무시하고 다음 Step으로 진행함을 의미한다.
- 정리 대상은 해당 Feature가 생성하는 리소스의 ID를 명시적으로 나열한다.

### 7.6 결과 판정

| 결과 | 조건 |
|------|------|
| **PASS** | 모든 Then/And 검증 통과 |
| **FAIL** | 기대값 ≠ 실제값 → 버그 이슈 자동 등록 |
| **ERROR** | 실행 자체 실패 (컨테이너 다운, 타임아웃) |
| **SKIP** | 선행 변수 미확보로 실행 불가 |

> QA 환경 상세: `tests/tc/README.md`

## 8. 에이전트의 테스트 작성 규칙

### 8.1 단위/통합 테스트 (`@backend-dev`, `@frontend-dev`)

- 모듈 구현 PR에 해당 모듈의 단위 테스트를 반드시 포함
- 테스트 없는 코드는 `codex-branch-review` 또는 PR 승인 게이트에서 blocking failure로 판정한다
- 테스트 실패 시 구현 코드를 수정하여 통과시킨 후 PR 업데이트

### 8.2 QA TC (`@qa-engineer`)

- 새 API 엔드포인트 추가 시 해당 모듈의 `.feature` 파일에 시나리오 추가 검토
- TC 파일은 `--fix` 모드에서도 수정하지 않음 (소스 코드만 수정)
- Feature 내 Scenario는 순서 의존적 — 변수를 공유하므로 순서를 지켜야 함
