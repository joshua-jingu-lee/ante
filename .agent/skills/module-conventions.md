# Ante 모듈 코딩 컨벤션

> 모든 모듈 구현 시 이 컨벤션을 따른다.

## 1. 디렉토리 구조

각 모듈은 `src/ante/{모듈}/` 하위에 다음 구조를 따른다:

```
src/ante/{모듈}/
├── __init__.py      # public API re-export
├── base.py          # ABC/Protocol 정의 (인터페이스)
├── models.py        # dataclass/NamedTuple (데이터 모델)
├── service.py       # 비즈니스 로직 구현체
├── errors.py        # 모듈 전용 예외 클래스 (필요 시)
└── {구현체}.py      # 외부 연동 구현체 (예: kis.py, telegram.py)
```

### __init__.py 패턴

```python
"""EventBus — 이벤트 발행/구독 관리."""

from ante.eventbus.base import EventBus
from ante.eventbus.models import Event, EventType

__all__ = ["EventBus", "Event", "EventType"]
```

- public API만 re-export
- 내부 구현 상세는 노출하지 않음

## 2. 인터페이스 정의 (base.py)

```python
"""Broker Adapter 인터페이스."""

from abc import ABC, abstractmethod
from ante.broker.models import Order, OrderResult


class BrokerAdapter(ABC):
    """증권사 API 추상화 인터페이스."""

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict:
        """잔고 조회."""
        ...
```

- `ABC` 사용 (Protocol은 duck typing 필요할 때만)
- 모든 I/O 메서드는 `async`
- 반환 타입 명시

## 3. 데이터 모델 (models.py)

```python
"""EventBus 데이터 모델."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """이벤트 타입."""
    ORDER_REQUEST = "order_request"
    ORDER_FILLED = "order_filled"
    BOT_STARTED = "bot_started"
    BOT_STOPPED = "bot_stopped"


@dataclass(frozen=True)
class Event:
    """이벤트 기본 구조."""
    event_type: EventType
    payload: dict
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = ""
```

- `dataclass(frozen=True)` 기본 사용 (불변 객체)
- 가변 필요 시 `frozen=False` 명시
- Enum은 `str, Enum` 상속 (직렬화 용이)
- 타임스탬프는 `datetime` (UTC 권장)

## 4. 에러 처리

### 모듈 전용 예외 (errors.py)

```python
"""Treasury 모듈 예외."""


class TreasuryError(Exception):
    """Treasury 기본 예외."""
    pass


class InsufficientFundsError(TreasuryError):
    """자금 부족."""
    pass


class AllocationExceededError(TreasuryError):
    """할당 한도 초과."""
    pass
```

- 모듈 기본 예외를 정의하고 구체적 예외가 상속
- 다른 모듈의 예외를 직접 raise하지 않음

### 예외 처리 패턴

```python
# 좋음: 구체적 예외를 잡고 변환
try:
    result = await self._broker.place_order(order)
except BrokerTimeoutError:
    raise OrderExecutionError(f"주문 타임아웃: {order.symbol}")

# 나쁨: 광범위한 예외 무시
try:
    result = await self._broker.place_order(order)
except Exception:
    pass
```

## 5. 의존성 주입

모듈 간 의존성은 생성자 주입:

```python
class BotManager:
    """봇 생명주기 관리."""

    def __init__(
        self,
        eventbus: EventBus,
        treasury: Treasury,
        rule_engine: RuleEngine,
    ) -> None:
        self._eventbus = eventbus
        self._treasury = treasury
        self._rule_engine = rule_engine
```

- 인터페이스(ABC)에 의존, 구현체에 의존하지 않음
- `main.py`에서 조립 (Composition Root)
- 모듈이 다른 모듈을 직접 import하여 생성하지 않음

## 6. import 규칙

```python
# 허용: 같은 모듈 내부
from ante.eventbus.models import Event

# 허용: 다른 모듈의 public API (__init__.py에서 export된 것)
from ante.eventbus import EventBus, Event

# 금지: 다른 모듈의 내부 구현
from ante.eventbus.service import _internal_method

# 금지: 순환 import
# ante.bot이 ante.strategy를 import하면서
# ante.strategy가 ante.bot을 import하는 것
```

## 7. 로깅

```python
import logging

logger = logging.getLogger(__name__)


class EventBus:
    async def publish(self, event: Event) -> None:
        logger.debug("이벤트 발행: %s", event.event_type)
        # ...
        logger.info("이벤트 처리 완료: %s (%d 핸들러)", event.event_type, count)
```

- `logging.getLogger(__name__)` 사용
- DEBUG: 상세 흐름 추적
- INFO: 주요 동작 (봇 시작/중지, 주문 체결 등)
- WARNING: 예상 가능한 문제 (재시도, 타임아웃)
- ERROR: 처리 실패 (봇 예외, API 오류)

## 8. 테스트 패턴

```python
"""tests/unit/test_eventbus.py"""

import pytest
from ante.eventbus import EventBus, Event, EventType


@pytest.fixture
def eventbus():
    """EventBus 인스턴스."""
    return EventBus()


@pytest.mark.asyncio
async def test_publish_subscribe(eventbus):
    """이벤트 발행 시 구독자가 수신한다."""
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    eventbus.subscribe(EventType.ORDER_REQUEST, handler)
    event = Event(event_type=EventType.ORDER_REQUEST, payload={"symbol": "005930"})
    await eventbus.publish(event)

    assert len(received) == 1
    assert received[0].payload["symbol"] == "005930"
```

- 테스트 함수명: `test_{동작}_{조건}` 또는 `test_{동작}`
- fixture로 모듈 인스턴스 생성
- 한 테스트에 한 가지만 검증
- mock은 외부 의존성(DB, API)에만 사용, 내부 로직은 실제 객체로 테스트

## 9. 타입 힌트

```python
# 모든 public 함수에 타입 힌트 필수
async def get_balance(self, bot_id: str) -> float:
    ...

# 컬렉션은 구체적 타입 사용
def get_handlers(self, event_type: EventType) -> list[EventHandler]:
    ...

# Optional은 명시적으로
def find_bot(self, bot_id: str) -> Bot | None:
    ...

# 콜백 타입
EventHandler = Callable[[Event], Awaitable[None]]
```

## 10. 금액 처리

```python
# float 사용 (스펙 문서 기준)
price = 50000.50
quantity = 10.0
total = price * quantity
```

- 금액, 수량, 비율은 `float` 사용 (스펙 문서와 일치)
- DB 저장 시 `REAL` 타입 사용
- 국내주식 외 다양한 상품 확장성을 위해 float 채택

## 11. DDL 컨벤션 (db-schema.md SSOT)

모든 모듈의 테이블 정의는 모듈 레벨 `_DDL` 문자열 상수로 관리한다. 이 상수가 `docs/architecture/generated/db-schema.md` 자동 생성의 원본(SSOT)이다.

### 규칙

- 새 테이블 추가 시 해당 모듈의 `store.py` 또는 `service.py`에 `_DDL` 상수 필수
- `_DDL`에 `CREATE TABLE IF NOT EXISTS`와 `CREATE INDEX IF NOT EXISTS`를 모두 포함
- 스키마 변경 시 `_DDL`을 먼저 수정 → `python scripts/generate_db_schema.py` 실행으로 문서 재생성
- `docs/architecture/generated/db-schema.md`를 직접 편집하지 않는다 (스크립트가 SSOT)

### 패턴

```python
# src/ante/{모듈}/store.py

_DDL = """
CREATE TABLE IF NOT EXISTS {테이블명} (
    id        TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    created   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_{테이블명}_name
    ON {테이블명}(name);
"""
```

### 보존 정책 (선택)

보존 정책이 있는 테이블은 DDL 앞에 주석으로 명시:

```sql
-- retention: 90d
CREATE TABLE IF NOT EXISTS trade_logs (
    ...
);
```

## 12. API 엔드포인트 응답 규칙

### response_model 필수

모든 새 API 엔드포인트는 반드시 `response_model`을 명시한다:

```python
# 좋음: response_model 명시
@router.get("/bots", response_model=BotListResponse)
async def list_bots() -> BotListResponse:
    ...

# 나쁨: dict 직접 반환
@router.get("/bots")
async def list_bots() -> dict:
    return {"bots": [...]}
```

**규칙**:
- 응답 모델은 `src/ante/web/schemas.py`에 Pydantic 모델로 정의한다
- `dict`를 직접 반환하는 것은 금지한다
- 기존 `response_model`(Pydantic 모델)을 변경하려면 별도 스키마 변경 이슈를 거친다 (참조: `docs/runbooks/01-development-process.md` §10)
- 예외: 204 응답(삭제)과 동적 스키마 엔드포인트는 `response_model` 면제
