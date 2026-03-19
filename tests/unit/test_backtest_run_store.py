"""backtest_runs 저장/조회 단위 테스트."""

from __future__ import annotations

import json

import pytest

from ante.backtest.run_store import BacktestRunStore


@pytest.fixture
async def run_store(tmp_path):
    """테스트용 BacktestRunStore."""
    from ante.core.database import Database

    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    await db.connect()

    store = BacktestRunStore(db)
    await store.initialize()
    yield store

    await db.close()


class TestBacktestRunStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self, run_store):
        run_id = await run_store.save(
            strategy_name="momentum",
            strategy_version="1.0.0",
            params={"start_date": "2025-01-01", "end_date": "2025-12-31"},
            total_return_pct=15.0,
            sharpe_ratio=1.2,
            max_drawdown_pct=-8.5,
            total_trades=42,
            win_rate=0.58,
            result_path="/results/bt-1.json",
        )

        assert run_id  # UUID string

        run = await run_store.get(run_id)
        assert run is not None
        assert run.strategy_name == "momentum"
        assert run.strategy_version == "1.0.0"
        assert run.total_return_pct == 15.0
        assert run.sharpe_ratio == 1.2
        assert run.max_drawdown_pct == -8.5
        assert run.total_trades == 42
        assert run.win_rate == 0.58
        assert run.result_path == "/results/bt-1.json"

        params = json.loads(run.params_json)
        assert params["start_date"] == "2025-01-01"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, run_store):
        result = await run_store.get("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_strategy(self, run_store):
        for i in range(3):
            await run_store.save(
                strategy_name="momentum",
                strategy_version="1.0.0",
                total_return_pct=float(i * 5),
                total_trades=i * 10,
            )

        await run_store.save(
            strategy_name="other_strategy",
            strategy_version="1.0.0",
            total_return_pct=20.0,
        )

        runs = await run_store.list_by_strategy("momentum")
        assert len(runs) == 3
        assert all(r.strategy_name == "momentum" for r in runs)
        # 최신순 정렬 확인
        assert runs[0].total_return_pct == 10.0  # 마지막에 저장된 것

    @pytest.mark.asyncio
    async def test_list_by_strategy_with_limit(self, run_store):
        for i in range(5):
            await run_store.save(
                strategy_name="test_stg",
                strategy_version="1.0.0",
                total_return_pct=float(i),
            )

        runs = await run_store.list_by_strategy("test_stg", limit=2)
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_list_by_strategy_empty(self, run_store):
        runs = await run_store.list_by_strategy("nonexistent")
        assert runs == []

    @pytest.mark.asyncio
    async def test_save_minimal(self, run_store):
        """필수 필드만으로 저장."""
        run_id = await run_store.save(
            strategy_name="minimal",
            strategy_version="0.1.0",
        )
        run = await run_store.get(run_id)
        assert run is not None
        assert run.strategy_name == "minimal"
        assert run.total_return_pct is None
        assert run.sharpe_ratio is None
        assert run.total_trades is None

    @pytest.mark.asyncio
    async def test_to_dict(self, run_store):
        run_id = await run_store.save(
            strategy_name="test",
            strategy_version="1.0.0",
            total_return_pct=10.0,
        )
        run = await run_store.get(run_id)
        d = run.to_dict()
        assert d["run_id"] == run_id
        assert d["strategy_name"] == "test"
        assert d["total_return_pct"] == 10.0
