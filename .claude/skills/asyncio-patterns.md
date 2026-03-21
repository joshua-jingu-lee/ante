# Ante asyncio 패턴 가이드

> 모든 async 코드는 이 패턴을 따른다. Python 3.11+ 기준.

## 1. EventBus — 타입 기반 직접 디스패치

> 상세 설계: docs/specs/eventbus.md 참조

```python
from inspect import isawaitable

class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[tuple[int, Callable]]] = {}

    def subscribe(
        self,
        event_type: type[Event],
        handler: Callable[[Event], Awaitable[None] | None],
        priority: int = 0,
    ) -> None:
        """이벤트 타입에 핸들러 등록. priority가 높을수록 먼저 실행."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)

    async def publish(self, event: Event) -> None:
        """이벤트를 모든 구독 핸들러에 순차 전달."""
        handlers = self._handlers.get(type(event), [])
        for priority, handler in handlers:
            try:
                result = handler(event)
                if isawaitable(result):
                    await result
            except Exception:
                logger.exception("핸들러 에러: %s", handler.__qualname__)
```

**핵심**:
- Queue 없이 직접 publish — 주문 흐름에서 순서 보장이 중요하므로 동기 순차 실행
- 우선순위 지원 (예: RuleEngine=100, Treasury=80, APIGateway=50)
- 핸들러별 에러 격리 — 한 핸들러 예외가 다른 핸들러를 막지 않음

## 2. Task 생명주기 관리

```python
class BotManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_bot(self, bot_id: str, bot: Bot) -> None:
        if bot_id in self._tasks:
            raise ValueError(f"봇 이미 실행 중: {bot_id}")
        task = asyncio.create_task(
            self._run_bot(bot_id, bot),
            name=f"bot-{bot_id}",  # 디버깅용 이름
        )
        self._tasks[bot_id] = task

    async def stop_bot(self, bot_id: str) -> None:
        task = self._tasks.pop(bot_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task  # CancelledError 대기
            except asyncio.CancelledError:
                pass

    async def stop_all(self) -> None:
        for bot_id in list(self._tasks):
            await self.stop_bot(bot_id)
```

**주의**:
- `create_task`에 항상 `name` 파라미터 사용 (디버깅 시 필수)
- `stop` 시 반드시 `await task`로 정리 완료 대기
- `task.done()` 체크 후 cancel (이미 완료된 Task cancel은 무해하지만 명시적이 좋음)

## 3. 봇 단위 예외 격리 (D-003)

```python
async def _run_bot(self, bot_id: str, bot: Bot) -> None:
    """각 봇은 독립 Task. 한 봇 오류가 다른 봇에 무영향."""
    try:
        await bot.run()
    except asyncio.CancelledError:
        logger.info("봇 정상 중지: %s", bot_id)
        raise  # CancelledError는 반드시 re-raise
    except Exception:
        logger.exception("봇 오류로 중지: %s", bot_id)
        await self._eventbus.publish(Event(
            event_type=EventType.BOT_ERROR,
            payload={"bot_id": bot_id},
        ))
    finally:
        self._tasks.pop(bot_id, None)
        await bot.cleanup()
```

**핵심 규칙**:
- `CancelledError`는 반드시 re-raise (삼키면 취소가 안 됨)
- `Exception`만 catch (BaseException 아님)
- `finally`에서 정리 작업 수행

## 4. Graceful Shutdown

```python
import signal

async def main() -> None:
    eventbus = EventBus()
    bot_manager = BotManager(eventbus)

    # 시그널 핸들러 등록
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(eventbus, bot_manager)))

    # 핵심 Task 시작
    eventbus_task = asyncio.create_task(eventbus.run(), name="eventbus")

    try:
        await asyncio.gather(eventbus_task)
    except asyncio.CancelledError:
        pass

async def shutdown(eventbus: EventBus, bot_manager: BotManager) -> None:
    """역순으로 정리: 봇 → 이벤트버스 → DB."""
    logger.info("시스템 종료 시작")
    await bot_manager.stop_all()   # 1. 봇 먼저 중지
    await eventbus.stop()          # 2. 이벤트버스 중지
    # 3. DB 연결 등 리소스 정리
    logger.info("시스템 종료 완료")
```

**종료 순서**: 봇(최상위) → 이벤트버스(중간) → DB/리소스(최하위). 역순으로 정리.

## 5. TaskGroup vs 수동 Task 관리

```python
# TaskGroup — 모든 Task가 함께 시작/종료될 때 사용
async def run_parallel_backtest(strategies: list[Strategy]) -> list[Result]:
    results = []
    async with asyncio.TaskGroup() as tg:
        for stg in strategies:
            tg.create_task(run_single_backtest(stg))
    return results

# 수동 관리 — 각 Task가 독립 생명주기를 가질 때 사용 (봇이 이 케이스)
# BotManager._tasks dict로 개별 관리
```

**선택 기준**:
| 상황 | 방식 |
|------|------|
| 봇 관리 (독립 생명주기, 개별 중지) | 수동 `create_task` |
| 병렬 백테스트 (모두 함께 완료) | `TaskGroup` |
| 이벤트 핸들러 병렬 실행 | `asyncio.gather` |

## 6. subprocess 실행 (백테스트)

```python
async def run_backtest(strategy_path: str, config: dict) -> BacktestResult:
    """백테스트를 subprocess로 격리 실행 (D-004)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "ante.backtest.runner",
        "--strategy", strategy_path,
        "--config", json.dumps(config),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await asyncio.communicate()

    if proc.returncode != 0:
        raise BacktestError(f"백테스트 실패: {stderr.decode()}")

    return BacktestResult.from_json(stdout.decode())
```

**주의**: `create_subprocess_exec`는 `create_subprocess_shell`보다 안전 (인젝션 방지)

## 7. Rate Limiting (Token Bucket)

```python
class RateLimiter:
    """토큰 버킷 기반 rate limiter."""

    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate        # 초당 토큰 충전량
        self._burst = burst      # 최대 토큰 수
        self._tokens = float(burst)
        self._last_refill = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1
```

## 8. 공통 주의사항

- **blocking I/O 금지**: `time.sleep()`, 동기 `requests`, 동기 파일 I/O 사용 금지. 반드시 async 버전 사용
- **CPU-bound 작업**: `loop.run_in_executor()` 또는 subprocess로 격리
- **asyncio.Lock**: 동시 접근 보호 필요 시 사용. 단, 단일 프로세스이므로 GIL과 혼동하지 않기
- **타임아웃**: 외부 API 호출에는 반드시 `asyncio.wait_for(coro, timeout=)` 사용
