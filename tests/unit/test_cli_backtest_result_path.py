"""#1998/#2001: CLI ``_save_backtest_run`` 이 envelope result_path 를 이력에 기록한다.

#2001 으로 ``_save_backtest_run`` 시그니처가 ``BacktestResult`` 객체에서
``run_subprocess`` 가 반환하는 additive envelope dict 기반으로 바뀌었다. 본
테스트는 envelope dict 의 ``result_path`` / ``strategy_name`` /
``strategy_version`` / ``total_return_pct`` / ``total_trades`` 가
``backtest_runs`` 행으로 그대로 전파됨을 검증한다 (#1998 추적성 보존).
"""

from __future__ import annotations

import pytest

from ante.backtest.result import BacktestResult
from ante.backtest.run_store import BacktestRunStore
from ante.cli.commands.backtest import _save_backtest_run
from ante.core.database import Database


def _envelope(
    *,
    strategy_name: str = "momentum",
    strategy_version: str = "1.0.0",
    total_return: float = 10.0,
    result_path: str = "",
) -> dict:
    """run_subprocess 가 반환하는 envelope(to_dict superset + 런타임 3키)."""
    result = BacktestResult(
        strategy_name=strategy_name,
        strategy_version=strategy_version,
        start_date="2025-01-01",
        end_date="2025-12-31",
        initial_balance=10_000_000.0,
        final_balance=11_000_000.0,
        total_return=total_return,
    )
    result.result_path = result_path
    return {
        **result.to_dict(),
        "result_path": result.result_path,
        "strategy_name": result.strategy_name,
        "strategy_version": result.strategy_version,
    }


@pytest.mark.asyncio
async def test_save_backtest_run_records_result_path(tmp_path):
    """_save_backtest_run 이 envelope result_path 를 이력 result_path 로 저장."""
    db_path = str(tmp_path / "test.db")
    artifact_path = str(tmp_path / ".backtest" / "results" / "momentum_v1.0.0_abc.json")

    result_dict = _envelope(result_path=artifact_path)
    config = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
    metrics = {"sharpe_ratio": 1.1, "max_drawdown": -5.0, "win_rate": 0.6}

    run_id = await _save_backtest_run(db_path, result_dict, config, metrics)
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
    # envelope 스칼라 키가 그대로 전파된다.
    assert run.strategy_name == "momentum"
    assert run.strategy_version == "1.0.0"
    assert run.total_return_pct == 10.0


@pytest.mark.asyncio
async def test_save_backtest_run_empty_path_on_save_failure(tmp_path):
    """저장 실패 fallback(result_path="") 도 이력에 그대로 기록(무회귀)."""
    db_path = str(tmp_path / "test.db")

    # subprocess run() 저장 실패 시 envelope result_path 는 "" fallback.
    result_dict = _envelope(result_path="")
    assert result_dict["result_path"] == ""

    run_id = await _save_backtest_run(db_path, result_dict, {}, {})

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        run = await store.get(run_id)
    finally:
        await db.close()

    assert run is not None
    assert run.result_path == ""


@pytest.mark.asyncio
async def test_save_backtest_run_does_not_split_combined_strategy(tmp_path):
    """#2001: combined ``strategy`` 를 split 파싱하지 않고 개별 키를 직접 사용한다.

    version 문자열에 ``_v`` 가 포함된 경우 combined ``strategy``
    (``"{name}_v{version}"``) split 파싱은 잘못된 name/version 을 만든다.
    envelope 의 strategy_name/strategy_version 개별 키를 직접 써야 안전하다.
    """
    db_path = str(tmp_path / "test.db")

    # 일부러 strategy_name 에 ``_v`` 를 포함 → combined split 이면 깨진다.
    result_dict = _envelope(
        strategy_name="alpha_v2_breakout",
        strategy_version="1.0.0",
        result_path="",
    )
    # combined 표현은 "alpha_v2_breakout_v1.0.0" — split("_v") 면 잘못 분해된다.
    assert result_dict["strategy"] == "alpha_v2_breakout_v1.0.0"

    run_id = await _save_backtest_run(db_path, result_dict, {}, {})

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        run = await store.get(run_id)
    finally:
        await db.close()

    assert run is not None
    # 개별 키가 그대로 — split 파싱이면 name/version 이 깨진다.
    assert run.strategy_name == "alpha_v2_breakout"
    assert run.strategy_version == "1.0.0"
