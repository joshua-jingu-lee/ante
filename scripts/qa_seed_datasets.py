"""QA 데이터셋 시딩 스크립트.

서버 기동 후 DB에 직접 삽입하여 테스트에 필요한 기본 데이터셋을 생성한다.
API로 생성하기 어려운 거래 내역, 일별 성과 등을 포함한다.

시드 항목:
- 봇 2개 (qa-test-bot-01, qa-test-bot-02)
- 거래 내역 12건
- 포지션 이력
- 일별 Treasury 스냅샷 14일분

멱등성: 이미 데이터가 존재하면 INSERT OR IGNORE로 건너뛴다.

Usage::

    python scripts/qa_seed_datasets.py [--db-path db/ante.db]
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timedelta
from uuid import UUID, uuid5

logger = logging.getLogger(__name__)

# QA 시드 데이터 전용 UUID 네임스페이스 (결정적 생성으로 멱등성 보장)
_QA_NS = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _qa_trade_id(name: str) -> str:
    """결정적 UUID5를 문자열로 반환한다."""
    return str(uuid5(_QA_NS, name))


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
ACCOUNT_ID = "test"
STRATEGY_IDS = ["qa_sample_v0.1.0", "qa_buy_signal_v0.1.0"]
BOT_CONFIGS = [
    {
        "bot_id": "qa-test-bot-01",
        "name": "QA Bot 01",
        "strategy_id": STRATEGY_IDS[0],
        "account_id": ACCOUNT_ID,
        "config_json": '{"symbols":["005930"],"timeframe":"1d"}',
        "status": "created",
    },
    {
        "bot_id": "qa-test-bot-02",
        "name": "QA Bot 02",
        "strategy_id": STRATEGY_IDS[1],
        "account_id": ACCOUNT_ID,
        "config_json": '{"symbols":["005930"],"timeframe":"1d"}',
        "status": "created",
    },
]

# 기준 시각: 오늘 기준 14일 전부터
_BASE_DATE = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
_START_DATE = _BASE_DATE - timedelta(days=14)


def _trade_timestamp(day_offset: int, hour: int = 10, minute: int = 0) -> str:
    """_START_DATE 기준 day_offset일 후의 타임스탬프 문자열."""
    dt = _START_DATE + timedelta(days=day_offset, hours=hour - 9, minutes=minute)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# 거래 내역 12건: 봇 2개에 걸쳐 매수/매도 혼합
TRADES = [
    # bot-01: 삼성전자 매수 5건, 매도 2건
    (
        _qa_trade_id("qa-trade-001"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "buy",
        10,
        71000,
        "filled",
        "market",
        "QA 시드 매수 1",
        35.5,
        _trade_timestamp(0, 9, 30),
    ),
    (
        _qa_trade_id("qa-trade-002"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "buy",
        5,
        70500,
        "filled",
        "market",
        "QA 시드 매수 2",
        17.6,
        _trade_timestamp(1, 10, 0),
    ),
    (
        _qa_trade_id("qa-trade-003"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "sell",
        8,
        72000,
        "filled",
        "market",
        "QA 시드 매도 1",
        28.8,
        _trade_timestamp(3, 14, 0),
    ),
    (
        _qa_trade_id("qa-trade-004"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "buy",
        3,
        71500,
        "filled",
        "limit",
        "QA 시드 매수 3",
        10.7,
        _trade_timestamp(5, 11, 30),
    ),
    (
        _qa_trade_id("qa-trade-005"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "sell",
        5,
        73000,
        "filled",
        "market",
        "QA 시드 매도 2",
        18.3,
        _trade_timestamp(7, 13, 0),
    ),
    (
        _qa_trade_id("qa-trade-006"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "buy",
        7,
        72500,
        "filled",
        "market",
        "QA 시드 매수 4",
        25.4,
        _trade_timestamp(9, 10, 30),
    ),
    (
        _qa_trade_id("qa-trade-007"),
        "qa-test-bot-01",
        STRATEGY_IDS[0],
        "005930",
        "buy",
        2,
        72000,
        "filled",
        "limit",
        "QA 시드 매수 5",
        7.2,
        _trade_timestamp(11, 9, 30),
    ),
    # bot-02: SK하이닉스 매수 3건, 매도 2건
    (
        _qa_trade_id("qa-trade-008"),
        "qa-test-bot-02",
        STRATEGY_IDS[1],
        "000660",
        "buy",
        20,
        185000,
        "filled",
        "market",
        "QA 시드 매수 1",
        185.0,
        _trade_timestamp(0, 10, 0),
    ),
    (
        _qa_trade_id("qa-trade-009"),
        "qa-test-bot-02",
        STRATEGY_IDS[1],
        "000660",
        "sell",
        10,
        190000,
        "filled",
        "market",
        "QA 시드 매도 1",
        95.0,
        _trade_timestamp(2, 14, 30),
    ),
    (
        _qa_trade_id("qa-trade-010"),
        "qa-test-bot-02",
        STRATEGY_IDS[1],
        "000660",
        "buy",
        5,
        187000,
        "filled",
        "limit",
        "QA 시드 매수 2",
        46.8,
        _trade_timestamp(4, 11, 0),
    ),
    (
        _qa_trade_id("qa-trade-011"),
        "qa-test-bot-02",
        STRATEGY_IDS[1],
        "000660",
        "sell",
        8,
        192000,
        "filled",
        "market",
        "QA 시드 매도 2",
        76.8,
        _trade_timestamp(8, 13, 30),
    ),
    (
        _qa_trade_id("qa-trade-012"),
        "qa-test-bot-02",
        STRATEGY_IDS[1],
        "000660",
        "buy",
        3,
        188000,
        "filled",
        "market",
        "QA 시드 매수 3",
        28.2,
        _trade_timestamp(10, 10, 0),
    ),
]

# 포지션 이력 (거래에 대응하는 포지션 변동)
POSITION_HISTORY = [
    # bot-01 005930
    ("qa-test-bot-01", "005930", "open", 10, 71000, 0.0, _trade_timestamp(0, 9, 30)),
    ("qa-test-bot-01", "005930", "add", 5, 70500, 0.0, _trade_timestamp(1, 10, 0)),
    (
        "qa-test-bot-01",
        "005930",
        "reduce",
        8,
        72000,
        10333.0,
        _trade_timestamp(3, 14, 0),
    ),
    ("qa-test-bot-01", "005930", "add", 3, 71500, 0.0, _trade_timestamp(5, 11, 30)),
    (
        "qa-test-bot-01",
        "005930",
        "reduce",
        5,
        73000,
        8500.0,
        _trade_timestamp(7, 13, 0),
    ),
    ("qa-test-bot-01", "005930", "add", 7, 72500, 0.0, _trade_timestamp(9, 10, 30)),
    ("qa-test-bot-01", "005930", "add", 2, 72000, 0.0, _trade_timestamp(11, 9, 30)),
    # bot-02 000660
    ("qa-test-bot-02", "000660", "open", 20, 185000, 0.0, _trade_timestamp(0, 10, 0)),
    (
        "qa-test-bot-02",
        "000660",
        "reduce",
        10,
        190000,
        50000.0,
        _trade_timestamp(2, 14, 30),
    ),
    ("qa-test-bot-02", "000660", "add", 5, 187000, 0.0, _trade_timestamp(4, 11, 0)),
    (
        "qa-test-bot-02",
        "000660",
        "reduce",
        8,
        192000,
        44000.0,
        _trade_timestamp(8, 13, 30),
    ),
    ("qa-test-bot-02", "000660", "add", 3, 188000, 0.0, _trade_timestamp(10, 10, 0)),
]

# 봇 예산 (bot_budgets)
BOT_BUDGETS = [
    ("qa-test-bot-01", ACCOUNT_ID, 1000000, 800000, 0, 200000, 50000),
    ("qa-test-bot-02", ACCOUNT_ID, 5000000, 3500000, 0, 1500000, 200000),
]


def _daily_snapshots() -> list[tuple]:
    """14일분 일별 Treasury 스냅샷을 생성한다."""
    snapshots = []
    base_asset = 10000000.0
    for i in range(14):
        d = _START_DATE + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        # 약간의 일별 변동 시뮬레이션
        pnl = (-1) ** i * (5000 + i * 1200)
        daily_return = pnl / base_asset * 100
        total_asset = base_asset + pnl * (i + 1) / 14
        snapshots.append(
            (
                ACCOUNT_ID,
                date_str,
                round(total_asset, 2),  # total_asset
                round(total_asset * 0.6, 2),  # ante_eval_amount
                round(total_asset * 0.55, 2),  # ante_purchase_amount
                round(total_asset * 0.4, 2),  # unallocated
                round(total_asset * 0.35, 2),  # account_balance
                round(total_asset * 0.6, 2),  # total_allocated
                2,  # bot_count
                round(pnl, 2),  # daily_pnl
                round(daily_return, 4),  # daily_return
                0.0,  # net_trade_amount
                round(pnl * 0.3, 2),  # unrealized_pnl
            )
        )
        base_asset = total_asset
    return snapshots


def seed(db_path: str) -> None:
    """DB에 QA 데이터셋을 시딩한다."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. 봇 시드
        bot_inserted = 0
        for bot in BOT_CONFIGS:
            cursor.execute(
                "INSERT OR IGNORE INTO bots "
                "(bot_id, name, strategy_id, account_id, config_json, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    bot["bot_id"],
                    bot["name"],
                    bot["strategy_id"],
                    bot["account_id"],
                    bot["config_json"],
                    bot["status"],
                ),
            )
            bot_inserted += cursor.rowcount
        logger.info("봇 시드: %d건 삽입 (총 %d건 정의)", bot_inserted, len(BOT_CONFIGS))

        # 2. 봇 예산 시드
        budget_inserted = 0
        for b in BOT_BUDGETS:
            cursor.execute(
                "INSERT OR IGNORE INTO bot_budgets "
                "(bot_id, account_id, allocated, available, reserved, spent, returned) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                b,
            )
            budget_inserted += cursor.rowcount
        logger.info("봇 예산 시드: %d건 삽입", budget_inserted)

        # 3. 거래 내역 시드
        trade_inserted = 0
        for t in TRADES:
            cursor.execute(
                "INSERT OR IGNORE INTO trades "
                "(trade_id, bot_id, strategy_id, symbol, side, quantity, price, "
                "status, order_type, reason, commission, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                t,
            )
            trade_inserted += cursor.rowcount
        logger.info(
            "거래 내역 시드: %d건 삽입 (총 %d건 정의)", trade_inserted, len(TRADES)
        )

        # 4. 포지션 이력 시드
        ph_inserted = 0
        for ph in POSITION_HISTORY:
            # 중복 방지: bot_id + symbol + timestamp 조합 체크
            cursor.execute(
                "SELECT 1 FROM position_history "
                "WHERE bot_id=? AND symbol=? AND timestamp=?",
                (ph[0], ph[1], ph[6]),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO position_history "
                    "(bot_id, symbol, action, quantity, price, pnl, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ph,
                )
                ph_inserted += 1
        logger.info("포지션 이력 시드: %d건 삽입", ph_inserted)

        # 5. 일별 Treasury 스냅샷 시드
        snapshots = _daily_snapshots()
        snap_inserted = 0
        for s in snapshots:
            cursor.execute(
                "INSERT OR IGNORE INTO treasury_daily_snapshots "
                "(account_id, snapshot_date, total_asset, ante_eval_amount, "
                "ante_purchase_amount, unallocated, account_balance, "
                "total_allocated, bot_count, daily_pnl, daily_return, "
                "net_trade_amount, unrealized_pnl) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                s,
            )
            snap_inserted += cursor.rowcount
        logger.info(
            "일별 스냅샷 시드: %d건 삽입 (총 %d일분)", snap_inserted, len(snapshots)
        )

        conn.commit()
        logger.info("QA 데이터셋 시딩 완료")

    except Exception:
        conn.rollback()
        logger.exception("QA 데이터셋 시딩 실패")
        raise
    finally:
        conn.close()


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="QA 데이터셋 시딩")
    parser.add_argument(
        "--db-path",
        type=str,
        default="db/ante.db",
        help="SQLite DB 경로 (기본: db/ante.db)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[qa-seed-datasets] %(message)s",
    )

    seed(args.db_path)


if __name__ == "__main__":
    main()
