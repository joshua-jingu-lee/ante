"""v005: trades.timestamp 공백 구분 포맷 → UTC-aware isoformat 정규화."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """공백 구분 19자 UTC 행을 ``...T...+00:00`` isoformat 으로 변환한다.

    - **테이블 부재 가드**: fresh install(빈 DB)은 DDL 에 이미 trades 가 포함되며
      ``run_migrations`` 전체 실행 경로를 보존하기 위해 trades 부재 시 no-op.
    - **협소 변환**: ``datetime('now')`` 산출물(정확히 19자 ``YYYY-MM-DD
      HH:MM:SS``)만 변환한다. ``+09:00`` 변형, trailing/다중 공백, 임의 텍스트
      행은 GLOB/length 가드에서 미일치하여 불변(invalid timestamp 생성 차단).
    - **멱등**: 변환 후 19자 공백 패턴 행이 없어 재실행 no-op. isoformat 행
      (``T`` 구분)은 패턴 미일치로 불변.
    """
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
    )
    if row is None:
        return

    await db.execute(
        "UPDATE trades "
        "SET timestamp = replace(timestamp, ' ', 'T') || '+00:00' "
        "WHERE length(timestamp) = 19 "
        "AND timestamp GLOB "
        "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
        "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"
    )
