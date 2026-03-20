"""E2E 테스트 시드 데이터 주입기.

DB 스키마 생성 → 시드 SQL 실행 → 샘플 Parquet 생성을 일괄 수행한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ante.core.database import Database

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent
SEED_SQL_PATH = SEED_DIR / "seed.sql"


async def _ensure_schemas(db: Database) -> None:
    """모든 모듈의 DB 스키마를 생성한다."""
    from ante.account.service import _CREATE_TABLE_SQL as ACCOUNT_SCHEMA
    from ante.approval.service import APPROVAL_SCHEMA
    from ante.audit.logger import AUDIT_SCHEMA
    from ante.bot.manager import BOT_SCHEMA
    from ante.bot.signal_key import SIGNAL_KEY_SCHEMA
    from ante.broker.order_registry import ORDER_REGISTRY_SCHEMA
    from ante.config.dynamic import DYNAMIC_CONFIG_SCHEMA
    from ante.eventbus.history import EVENT_LOG_SCHEMA
    from ante.member.service import MEMBER_SCHEMA
    from ante.report.store import REPORT_SCHEMA
    from ante.strategy.registry import STRATEGY_REGISTRY_SCHEMA
    from ante.trade.position import POSITION_SCHEMA
    from ante.trade.recorder import TRADE_SCHEMA
    from ante.treasury.treasury import TREASURY_SCHEMA
    from ante.web.session import SESSION_SCHEMA

    # system_state 테이블은 즉시 DROP하지 않고 레거시로 유지
    legacy_system_state_schema = """
    CREATE TABLE IF NOT EXISTS system_state (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS system_state_history (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        old_state  TEXT NOT NULL,
        new_state  TEXT NOT NULL,
        reason     TEXT DEFAULT '',
        changed_by TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    """

    schemas = [
        legacy_system_state_schema,
        ACCOUNT_SCHEMA,
        DYNAMIC_CONFIG_SCHEMA,
        MEMBER_SCHEMA,
        STRATEGY_REGISTRY_SCHEMA,
        BOT_SCHEMA,
        SIGNAL_KEY_SCHEMA,
        TREASURY_SCHEMA,
        TRADE_SCHEMA,
        POSITION_SCHEMA,
        ORDER_REGISTRY_SCHEMA,
        EVENT_LOG_SCHEMA,
        APPROVAL_SCHEMA,
        REPORT_SCHEMA,
        SESSION_SCHEMA,
        AUDIT_SCHEMA,
    ]

    for schema in schemas:
        await db.execute_script(schema)


async def inject_seed_data(db_path: str, data_dir: str | None = None) -> dict:
    """시드 데이터를 DB와 파일시스템에 주입한다.

    Args:
        db_path: SQLite DB 파일 경로.
        data_dir: OHLCV Parquet 저장 경로. None이면 Parquet 생성 생략.

    Returns:
        주입 결과 요약 딕셔너리.
    """
    from tests.fixtures.seed.generate_ohlcv import write_sample_parquet

    db = Database(db_path)
    await db.connect()

    try:
        # 1. 스키마 생성
        await _ensure_schemas(db)

        # 2. 시드 SQL 실행
        seed_sql = SEED_SQL_PATH.read_text(encoding="utf-8")
        await db.execute_script(seed_sql)
        logger.info("시드 데이터 주입 완료: %s", db_path)

        result: dict = {
            "db_path": db_path,
            "tables_seeded": [
                "strategies",
                "bots",
                "bot_budgets",
                "treasury_state",
                "accounts",
                "members",
            ],
        }

        # 3. 샘플 Parquet 생성
        if data_dir:
            parquet_path = write_sample_parquet(Path(data_dir))
            result["parquet_path"] = str(parquet_path)
            logger.info("샘플 OHLCV Parquet 생성: %s", parquet_path)

        return result
    finally:
        await db.close()
