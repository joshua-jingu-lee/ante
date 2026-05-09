"""v005: 기존 reports.win_rate legacy percent 값을 ratio로 정규화한다.

배경
----
``docs/specs/report-store/report-store.md`` SSOT는 ``win_rate`` 를 0~1 범위의
ratio 로 정의한다. #1353 이전에는 일부 record가 percent 단위(예: 62.2)로
저장되어 있었기 때문에, 신규 ratio 정의 하에서 frontend가 ``value * 100`` 으로
환산하면 6220% 와 같이 표시되는 회귀가 발생했다.

본 마이그레이션은 ``win_rate > 1.0`` 인 모든 legacy record를 ``win_rate / 100.0``
으로 갱신하여 ratio 표현으로 통일한다. 이미 ratio 인 값(0.0 ~ 1.0)과 NULL
값은 변경하지 않는다.

다운그레이드는 의도적으로 제공하지 않는다. ratio 가 spec SSOT 이므로 percent
로의 회귀는 신규 record와 다시 ambiguous 해지기 때문이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """``win_rate > 1.0`` 인 legacy record를 ratio로 변환한다."""
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
    )
    if row is None:
        # reports 테이블이 없으면 스킵 (신규 설치 시 ReportStore.initialize 생성).
        return

    await db.execute(
        "UPDATE reports SET win_rate = win_rate / 100.0 "
        "WHERE win_rate IS NOT NULL AND win_rate > 1.0"
    )
