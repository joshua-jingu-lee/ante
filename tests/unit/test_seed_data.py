"""시드 데이터 fixture 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from ante.core.database import Database
from tests.fixtures.seed.generate_ohlcv import (
    generate_sample_ohlcv,
    write_sample_parquet,
)
from tests.fixtures.seed.seeder import _ensure_schemas, inject_seed_data

# ── OHLCV 생성 테스트 ────────────────────────────────


def test_generate_sample_ohlcv_default() -> None:
    """기본 설정으로 5일치 OHLCV를 생성한다."""
    df = generate_sample_ohlcv()
    assert len(df) == 5
    assert set(df.columns) == {
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
    }
    assert df["symbol"][0] == "005930"
    assert df["source"][0] == "seed"


def test_generate_sample_ohlcv_custom() -> None:
    """커스텀 설정으로 OHLCV를 생성한다."""
    df = generate_sample_ohlcv(symbol="000660", days=3, base_price=100_000)
    assert len(df) == 3
    assert df["symbol"][0] == "000660"
    assert df["open"][0] == 100_000


def test_write_sample_parquet(tmp_path: Path) -> None:
    """Parquet 파일이 올바른 경로에 생성된다."""
    filepath = write_sample_parquet(tmp_path)
    assert filepath.exists()
    assert filepath.suffix == ".parquet"
    assert "ohlcv/1d/KRX/005930" in str(filepath)


# ── 시드 데이터 주입 테스트 ───────────────────────────


@pytest.mark.asyncio
async def test_ensure_schemas(tmp_path: Path) -> None:
    """모든 모듈 스키마가 정상 생성된다."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    await db.connect()
    try:
        await _ensure_schemas(db)

        tables = await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = {t["name"] for t in tables}

        expected = {
            "bots",
            "strategies",
            "bot_budgets",
            "treasury_state",
            "system_state",
            "members",
            "trades",
            "positions",
        }
        assert expected.issubset(table_names)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_inject_seed_data_db_only(tmp_path: Path) -> None:
    """DB에 시드 데이터가 주입된다."""
    db_path = str(tmp_path / "test.db")
    result = await inject_seed_data(db_path)

    assert result["db_path"] == db_path
    assert "parquet_path" not in result

    # 주입된 데이터 확인
    db = Database(db_path)
    await db.connect()
    try:
        strategies = await db.fetch_all("SELECT * FROM strategies")
        assert len(strategies) == 2

        bots = await db.fetch_all("SELECT * FROM bots")
        assert len(bots) == 2

        budgets = await db.fetch_all("SELECT * FROM bot_budgets")
        assert len(budgets) == 2

        state = await db.fetch_one(
            "SELECT value FROM system_state WHERE key='trading_state'"
        )
        assert state is not None
        assert state["value"] == "active"

        members = await db.fetch_all("SELECT * FROM members")
        assert len(members) == 1
        assert members[0]["member_id"] == "seed-admin"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_inject_seed_data_with_parquet(tmp_path: Path) -> None:
    """DB + Parquet 시드 데이터가 주입된다."""
    db_path = str(tmp_path / "test.db")
    data_dir = str(tmp_path / "data")

    result = await inject_seed_data(db_path, data_dir)

    assert "parquet_path" in result
    assert Path(result["parquet_path"]).exists()


@pytest.mark.asyncio
async def test_inject_seed_data_idempotent(tmp_path: Path) -> None:
    """시드 데이터 주입은 멱등성을 가진다 (INSERT OR IGNORE)."""
    db_path = str(tmp_path / "test.db")

    await inject_seed_data(db_path)
    await inject_seed_data(db_path)  # 두 번째 실행도 에러 없이 완료

    db = Database(db_path)
    await db.connect()
    try:
        strategies = await db.fetch_all("SELECT * FROM strategies")
        assert len(strategies) == 2  # 중복 없음
    finally:
        await db.close()


# ── 샘플 전략 테스트 ─────────────────────────────────


@pytest.mark.asyncio
async def test_sample_strategy_loads() -> None:
    """샘플 전략이 정상 로드되고 시그널을 생성한다."""
    from tests.fixtures.seed.daily_fixed_buy import DailyFixedBuy

    assert DailyFixedBuy.meta.name == "DailyFixedBuy"
    assert DailyFixedBuy.meta.symbols == ["005930"]

    strategy = DailyFixedBuy(ctx=None)
    signals = await strategy.on_step({})
    assert len(signals) == 1
    assert signals[0].symbol == "005930"
    assert signals[0].side == "buy"


# ── CLI --seed 옵션 테스트 ────────────────────────────


def test_init_seed_cli(tmp_path: Path) -> None:
    """ante init --seed가 시드 데이터를 주입한다."""
    from click.testing import CliRunner

    from ante.cli.commands.init import init
    from ante.cli.formatter import OutputFormatter

    runner = CliRunner()
    target = str(tmp_path / "ante-config")
    result = runner.invoke(
        init,
        ["--dir", target, "--seed"],
        obj={"format": "text", "formatter": OutputFormatter("text")},
        standalone_mode=False,
    )

    assert result.exit_code == 0
    assert (tmp_path / "ante-config" / "db" / "ante.db").exists()
    assert (tmp_path / "ante-config" / "system.toml").exists()
