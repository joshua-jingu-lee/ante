"""#1998: CLI ``_save_backtest_run`` 이 result.result_path 를 이력에 기록한다."""

from __future__ import annotations

import pytest

from ante.backtest.result import BacktestResult
from ante.backtest.run_store import BacktestRunStore
from ante.cli.commands.backtest import _save_backtest_run
from ante.core.database import Database


@pytest.mark.asyncio
async def test_save_backtest_run_records_result_path(tmp_path):
    """_save_backtest_run 이 result.result_path 를 backtest_runs.result_path 로 저장."""
    db_path = str(tmp_path / "test.db")
    artifact_path = str(tmp_path / ".backtest" / "results" / "momentum_v1.0.0_abc.json")

    result = BacktestResult(
        strategy_name="momentum",
        strategy_version="1.0.0",
        start_date="2025-01-01",
        end_date="2025-12-31",
        initial_balance=10_000_000.0,
        final_balance=11_000_000.0,
        total_return=10.0,
    )
    result.result_path = artifact_path

    config = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
    metrics = {"sharpe_ratio": 1.1, "max_drawdown": -5.0, "win_rate": 0.6}

    run_id = await _save_backtest_run(db_path, result, config, metrics)
    assert run_id

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        run = await store.get(run_id)
    finally:
        await db.close()

    assert run is not None
    assert run.result_path == artifact_path


@pytest.mark.asyncio
async def test_save_backtest_run_empty_path_on_save_failure(tmp_path):
    """저장 실패 fallback(result_path="") 도 이력에 그대로 기록(무회귀)."""
    db_path = str(tmp_path / "test.db")

    result = BacktestResult(
        strategy_name="momentum",
        strategy_version="1.0.0",
        start_date="2025-01-01",
        end_date="2025-12-31",
        initial_balance=10_000_000.0,
        final_balance=11_000_000.0,
        total_return=10.0,
    )
    # service.run() 저장 실패 시 result_path 는 "" fallback 으로 남는다
    assert result.result_path == ""

    run_id = await _save_backtest_run(db_path, result, {}, {})

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        run = await store.get(run_id)
    finally:
        await db.close()

    assert run is not None
    assert run.result_path == ""
