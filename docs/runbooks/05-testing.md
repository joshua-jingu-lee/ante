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

### 3.4 CLI dependency-isolation smoke test

- `tests/unit/test_cli_dependency_isolation.py`는 `ante.cli.commands.*` import 시
  `pandas`, `pandas_ta`, `numba`, `numpy`, `polars`, `sklearn`, `talib` 같은
  분석/수치 heavy 의존성이 eager-load되지 않는지 검증한다.
- 같은 pytest 프로세스에서 `sys.modules` 캐시 영향을 받지 않도록 **fresh
  interpreter subprocess**를 띄워 격리된 환경에서 import한다.
- 회귀 차단 시나리오:
  - CLI dispatch 경로(예: `ante.cli.commands.strategy`)에 `import pandas`를
    추가하면 smoke test가 실패한다.
  - `ante.strategy.__init__` 같은 transitive import 체인에 heavy 모듈이
    top-level로 들어와도 실패한다.
- 새 CLI 명령 모듈을 추가했다면 `CLI_COMMAND_MODULES` 튜플에 모듈명을 추가한다.
- 헬퍼 `_run_isolated_import`는 메타-테스트
  `test_isolation_helper_detects_planted_heavy_import`로 자체 회귀를 검증한다.

### 3.5 Test isolation invariants

- 같은 pytest 프로세스 안에서 `del sys.modules[...]`를 **호출하지 않는다**.
  module re-import는 closure-bound reference (예: Click callback의
  `__globals__`)와 `sys.modules` 사이 inconsistency를 만들어, 같은 worker의
  다른 test가 `patch("ante.cli.commands.member._create_service", ...)` 등
  module-level attribute를 mock할 때 wrong module instance를 target하게
  된다. 그러면 real factory가 실행되어 결정적 fail로 이어진다 (#1909).
- import side-effect 자체를 검증해야 한다면 별도 Python subprocess
  (`subprocess.run([sys.executable, "-c", ...], env={..., "PYTHONPATH": ...})`)
  에서 실행한다. 본 패턴 예시는 §3.4의
  `tests/unit/test_cli_dependency_isolation.py`와 `#1909` fix 후의
  `tests/unit/contracts/test_cli_registry_shell.py::
  test_cli_registry_import_does_not_load_cli_main`를 참고한다.
- module-level monkey-patch (autouse fixture 외)는 금지. 필요 시 pytest
  fixture로 감싸 시점·범위를 명시한다.
- `mock.patch(...).start()` 호출은 반드시 동일 scope의 `stop()` 또는
  `addCleanup` / `with` context로 동반한다. `tests/conftest.py`의
  `mock.patch.stopall()` autouse cleanup은 안전망일 뿐 idiomatic 패턴이
  아니다 — start/stop은 test 본문에서 짝을 맞춰 작성한다.

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
# 현재 worktree import sanity check
PYTHONPATH=$PWD/src .venv/bin/python scripts/check_import_path.py

# 단위 테스트만
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/unit/ -v

# 통합 테스트만
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/integration/ -v

# 전체 + 커버리지
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/ -v --cov=src/ante --cov-report=term-missing

# 특정 모듈만
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/unit/test_eventbus.py -v

# 특정 테스트만
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/unit/test_eventbus.py::test_publish_subscribe -v
```

## 7. 배포 이미지 시뮬레이션 테스트

기존 repo-local QA 체계는 1.0 테스트 계약에서 제외한다.
저장소는 더 이상 QA 전용 Docker image, QA compose, TC 파일, QA seed script를
제공하지 않는다.

배포 이미지 기반 시뮬레이션 검증은 별도 테스트 전용 프로그램에서 정의한다.
그 프로그램은 외부에서 제공된 Ante Docker image를 입력으로 받아 public API,
CLI, process lifecycle, health endpoint를 검증해야 하며, repo 내부 DB 직접
시딩이나 QA 전용 entrypoint에 의존하지 않는다.

## 8. 에이전트의 테스트 작성 규칙

### 8.1 단위/통합 테스트 (`@backend-dev`)

- 모듈 구현 PR에 해당 모듈의 단위 테스트를 반드시 포함
- 테스트 없는 코드는 내부 `/codex:review` 브랜치 리뷰에서 blocking failure로 판정한다
- 테스트 실패 시 구현 코드를 수정하여 통과시킨 후 PR 업데이트
