"""테스트 전용 시드 리셋 API.

ANTE_TEST_MODE=1 환경에서만 활성화된다.
E2E 테스트에서 시나리오별 시드 데이터를 주입하기 위해 사용한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter()

SCENARIOS_DIR = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "seed" / "scenarios"
)
BASE_SQL = SCENARIOS_DIR / "_base.sql"


@router.post("/reset")
async def reset_seed(
    request: Request,
    scenario: str = Query(..., description="시나리오 이름 (예: login-dashboard)"),
) -> dict:
    """DB를 초기화하고 시나리오별 시드 데이터를 주입한다.

    1. 모든 테이블 DROP
    2. 스키마 재생성
    3. _base.sql 실행
    4. {scenario}.sql 실행
    """
    scenario_sql = SCENARIOS_DIR / f"{scenario}.sql"
    if not scenario_sql.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"시나리오를 찾을 수 없습니다: {scenario}",
        )

    db = request.app.state.db

    # 1. 모든 테이블 DROP
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    for row in rows:
        await db.execute(f"DROP TABLE IF EXISTS [{row['name']}]")

    # 2. 스키마 재생성
    from tests.fixtures.seed.seeder import _ensure_schemas

    await _ensure_schemas(db)

    # 3. _base.sql 실행
    if BASE_SQL.is_file():
        base_content = BASE_SQL.read_text(encoding="utf-8")
        await db.execute_script(base_content)

    # 4. 시나리오 SQL 실행
    scenario_content = scenario_sql.read_text(encoding="utf-8")
    await db.execute_script(scenario_content)

    logger.info("시드 리셋 완료: scenario=%s", scenario)
    return {"ok": True, "scenario": scenario}
