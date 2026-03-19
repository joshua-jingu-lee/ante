"""테스트 전용 시드 리셋 API.

ANTE_TEST_MODE=1 환경에서만 활성화된다.
E2E 테스트에서 시나리오별 시드 데이터를 주입하기 위해 사용한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from ante.web.schemas import SeedResetResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _find_scenarios_dir() -> Path:
    """시나리오 SQL 디렉토리를 탐색한다.

    pip install로 site-packages에 설치된 경우 __file__ 기준 경로가 맞지 않으므로,
    환경변수 -> CWD -> __file__ 순서로 탐색한다.
    """
    import os

    # 1. 환경변수로 명시적 지정
    env_dir = os.environ.get("ANTE_SCENARIOS_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p

    # 2. CWD 기준 (Docker 컨테이너에서 WORKDIR=/app)
    cwd_based = Path.cwd() / "tests" / "fixtures" / "seed" / "scenarios"
    if cwd_based.is_dir():
        return cwd_based

    # 3. __file__ 기준 (로컬 개발 시)
    file_based = (
        Path(__file__).resolve().parents[4]
        / "tests"
        / "fixtures"
        / "seed"
        / "scenarios"
    )
    if file_based.is_dir():
        return file_based

    return cwd_based  # fallback — 에러 메시지에서 경로 확인용


SCENARIOS_DIR = _find_scenarios_dir()
BASE_SQL = SCENARIOS_DIR / "_base.sql"


@router.post("/reset", response_model=SeedResetResponse)
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

    # 5. 메모리 기반 매니저 리로드
    await _reload_managers(request)

    logger.info("시드 리셋 완료: scenario=%s", scenario)
    return {"ok": True, "scenario": scenario}


async def _reload_managers(request: Request) -> None:
    """시딩 후 메모리 기반 매니저들을 DB에서 리로드한다."""
    # SystemState (인메모리 trading_state 동기화)
    system_state = getattr(request.app.state, "system_state", None)
    if system_state is not None and hasattr(system_state, "_load_from_db"):
        await system_state._load_from_db()  # noqa: SLF001

    # BotManager
    bot_manager = getattr(request.app.state, "bot_manager", None)
    if bot_manager is not None:
        await bot_manager.load_from_db()

    # Treasury (budget 리로드)
    treasury = getattr(request.app.state, "treasury", None)
    if treasury is not None and hasattr(treasury, "load_from_db"):
        await treasury.load_from_db()
