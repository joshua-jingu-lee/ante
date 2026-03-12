"""Ante - AI-Native Trading Engine entrypoint."""

import asyncio
import logging
import signal
from pathlib import Path

from ante.config import Config, DynamicConfigService, SystemState
from ante.core import Database
from ante.eventbus import EventBus, EventHistoryStore

logger = logging.getLogger(__name__)


async def main() -> None:
    """Main asyncio entrypoint.

    시스템 초기화 순서 (architecture.md 참조):
    1. Config.load() + validate()
    2. Database 초기화
    3. EventBus 초기화
    4. SystemState 초기화
    5. DynamicConfigService 초기화
    6~13. (Phase 2+ 에서 추가)
    """
    # 1. Config
    config = Config.load(config_dir=Path("config"))
    config.validate()

    # 로깅 설정
    log_level = config.get("system.log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Ante 시작")

    # 2. Database
    db_path = config.get("db.path", "db/ante.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    await db.connect()
    logger.info("Database 연결 완료: %s", db_path)

    # 3. EventBus
    history_size = config.get("eventbus.history_size", 1000)
    eventbus = EventBus(history_size=history_size)

    # EventHistoryStore — 모든 이벤트를 SQLite에 영속화
    event_history = EventHistoryStore(db=db)
    await event_history.initialize()
    eventbus.use(event_history.record)
    logger.info("EventBus 초기화 완료 (history_size=%d)", history_size)

    # 4. SystemState (킬 스위치)
    system_state = SystemState(db=db, eventbus=eventbus)
    await system_state.initialize()
    logger.info("SystemState 초기화 완료: %s", system_state.trading_state)

    # 5. DynamicConfigService
    dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
    await dynamic_config.initialize()
    logger.info("DynamicConfigService 초기화 완료")

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("종료 시그널 수신")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Ante 준비 완료 — 종료 시그널 대기 중")
    await shutdown_event.wait()

    # 종료 정리 (역순)
    logger.info("Ante 종료 시작")
    await db.close()
    logger.info("Ante 종료 완료")


if __name__ == "__main__":
    asyncio.run(main())
