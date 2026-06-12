"""v005: trades.timestamp 공백 구분 포맷 → UTC-aware isoformat 정규화 (#2371).

과거 ``save_adjustment`` 가 SQLite ``datetime('now')`` 로 저장한 보정 행의
``timestamp`` 는 공백 구분 포맷(``YYYY-MM-DD HH:MM:SS``, UTC, 19자)이다. 나머지
쓰기 경로(save_trade/_save_trade)는 UTC-aware isoformat(``...T...+00:00``)을
저장하므로 포맷이 혼재했고, TEXT lexical 비교에서 공백(``0x20``) < ``'T'``
(``0x54``) 이라 ``trade list --from`` 당일 경계에서 보정 행이 누락됐다.

본 마이그레이션은 기존 공백 19자 행만 isoformat UTC 로 협소 변환해 단일 포맷
invariant(``docs/specs/trade/03-05-sqlite-schema.md``)를 충족시킨다.
"""

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
      UTC 가정은 이 협소 가드 위에서만 성립한다.
    - **멱등**: 변환 후 19자 공백 패턴 행이 없어 재실행 no-op. isoformat 행
      (``T`` 구분)은 패턴 미일치로 불변.
    """
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
    )
    if row is None:
        return  # trades 테이블이 없으면 스킵 (신규 설치 시 DDL에 이미 포함)

    await db.execute(
        "UPDATE trades "
        "SET timestamp = replace(timestamp, ' ', 'T') || '+00:00' "
        "WHERE length(timestamp) = 19 "
        "AND timestamp GLOB "
        "'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] "
        "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"
    )
