"""CLI `backtest run --format json` 회귀 — stdout이 단일 JSON document인지 검증 (#1752).

버그:
- 기존에는 결과 페이로드(`fmt.output(result_dict)`)와 metric 테이블(`fmt.table(...)`)이
  JSON 모드에서도 모두 출력되어 stdout에 두 개의 독립된 JSON document가 붙었다.
- `json.loads`/`jq` 같은 single-document parser가 `Extra data` 오류로 실패했다.

회귀 검증 축:
- R1: `--format json` 호출 → stdout이 `json.loads`로 한 번에 파싱된다.
- R2: 파싱된 payload에 `metrics` 필드가 보존된다 (정보 손실 없음).
- R3: text 모드는 기존대로 metric 테이블을 출력한다 (회귀 보존).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import polars as pl
from click.testing import CliRunner

from ante.backtest.result import BacktestResult
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


def _make_runner() -> CliRunner:
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _make_result_envelope() -> dict:
    """run_subprocess 가 반환하는 envelope(to_dict superset + 런타임 3키).

    `if metrics and not fmt.is_json:` 분기를 타려면 metrics가 truthy해야 한다.
    """
    result = BacktestResult(
        strategy_name="momentum",
        strategy_version="1.0.0",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_balance=10_000_000.0,
        final_balance=11_000_000.0,
        total_return=10.0,
        trades=[],
        equity_curve=[],
        metrics={
            "total_return": 10.0,
            "sharpe_ratio": 1.5,
            "max_drawdown": -3.2,
            "win_rate": 0.6,
            "total_trades": 5,
        },
    )
    return {
        **result.to_dict(),
        "result_path": result.result_path,
        "strategy_name": result.strategy_name,
        "strategy_version": result.strategy_version,
    }


class _SpyService:
    """BacktestService를 흉내내고 envelope dict 를 돌려주는 subprocess spy (#2001)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def run_subprocess(self, config: dict) -> dict:  # noqa: ARG002
        return _make_result_envelope()


def _invoke_run(runner: CliRunner, tmp_path, *extra_args: str):
    """`backtest run`을 호출하되 BacktestService/_save_backtest_run을 stub."""
    strategy = tmp_path / "test_strategy.py"
    strategy.write_text("# dummy")

    with (
        patch("ante.backtest.service.BacktestService", _SpyService),
        patch(
            "ante.cli.commands.backtest._save_backtest_run",
            new=_fake_save_backtest_run,
        ),
    ):
        return runner.invoke(
            cli,
            [
                *extra_args,
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
            ],
        )


async def _fake_save_backtest_run(
    db_path: str,  # noqa: ARG001
    result_dict: dict,  # noqa: ARG001
    config: dict,  # noqa: ARG001
    metrics: dict,  # noqa: ARG001
) -> str:
    """DB 접근 없이 결정적 run_id를 반환."""
    return "run-test-1752"


class TestBacktestRunJsonSingleDocument:
    """`backtest run --format json` stdout이 단일 JSON document인지 (R1, R2)."""

    def test_json_mode_stdout_is_single_parseable_document(self, tmp_path):
        """R1: stdout 전체를 `json.loads`로 한 번에 파싱할 수 있어야 한다.

        분기 추가 전에는 metric 테이블이 두 번째 JSON document(배열)로 추가 출력되어
        `json.JSONDecodeError: Extra data`가 발생했다.
        """
        runner = _make_runner()
        result = _invoke_run(runner, tmp_path, "--format", "json")

        assert result.exit_code == 0, result.output
        # 한 번의 json.loads로 stdout 전체가 파싱되어야 한다.
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)

    def test_json_mode_payload_preserves_metrics(self, tmp_path):
        """R2: JSON payload의 `metrics`가 보존되어 정보 손실이 없다.

        `if metrics and not fmt.is_json:` 분기는 표면 출력을 잘라낼 뿐,
        result_dict["metrics"]는 그대로 노출되어야 한다.
        """
        runner = _make_runner()
        result = _invoke_run(runner, tmp_path, "--format", "json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "metrics" in payload
        # 핵심 지표가 그대로 보존되는지 확인.
        assert payload["metrics"]["sharpe_ratio"] == 1.5
        assert payload["metrics"]["win_rate"] == 0.6
        assert payload["metrics"]["max_drawdown"] == -3.2
        # 결과 페이로드 본문도 함께 보존되는지 확인.
        assert payload["run_id"] == "run-test-1752"
        assert payload["strategy"] == "momentum_v1.0.0"


class TestBacktestRunTextModeMetricTableRegression:
    """R3: text 모드는 기존대로 metric 테이블을 출력해 회귀가 없어야 한다."""

    def test_text_mode_still_renders_metric_table(self, tmp_path):
        """text 모드: `_format_metrics` 라벨(`Sharpe Ratio` 등)이 stdout에 나타난다."""
        runner = _make_runner()
        # --format 미지정 = text 모드 (default).
        result = _invoke_run(runner, tmp_path)

        assert result.exit_code == 0, result.output
        # _format_metrics가 만드는 한국어/영문 라벨 중 대표 토큰이 보여야 한다.
        # (테이블 헤더 "지표 | 값" + 라벨 행 둘 다 검증한다.)
        assert "지표" in result.output
        assert "값" in result.output
        assert "Sharpe Ratio" in result.output
        # 결과 페이로드 텍스트 템플릿도 같이 출력된다 (기존 회귀 보존).
        assert "Run ID: run-test-1752" in result.output


# ── #1995: 명시 종목 전체 무데이터 → BACKTEST_DATA_NOT_FOUND ───────────

# 데이터 없음(빈 store) 케이스를 실제 BacktestService/ParquetStore end-to-end로
# 재현한다. 명시 종목 전체가 row_count=0이면 backtest_runs 이력을 저장하지 않고
# exit 1 + BACKTEST_DATA_NOT_FOUND 로 실패해야 한다(fake success 차단).

_EMPTY_STRATEGY_SRC = '''\
"""테스트용 무동작 전략 (데이터 없음 케이스 재현)."""

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class EmptyStrategy(Strategy):
    """아무 시그널도 내지 않는 전략."""

    meta = StrategyMeta(
        name="empty",
        version="1.0",
        description="Does nothing",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []
'''


def _make_ohlcv_df(symbol: str, n: int = 10, base_price: float = 50000.0):
    """테스트용 OHLCV DataFrame (test_backtest.py 헬퍼 미러)."""
    start = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(days=n - 1),
        interval="1d",
        eager=True,
        time_zone="UTC",
    )
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [base_price + i * 100 for i in range(n)],
            "high": [base_price + i * 100 + 50 for i in range(n)],
            "low": [base_price + i * 100 - 50 for i in range(n)],
            "close": [base_price + i * 100 + 25 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )


def _write_strategy(tmp_path) -> str:
    """EmptyStrategy 전략 파일을 작성하고 경로를 반환."""
    strategy = tmp_path / "empty_strategy.py"
    strategy.write_text(_EMPTY_STRATEGY_SRC)
    return str(strategy)


def _count_runs(db_path: str, strategy_name: str = "empty") -> int:
    """backtest_runs 테이블에 저장된 해당 전략 run 개수를 센다.

    테이블이 아직 없을 수 있으므로 initialize() 후 조회한다(초기화는 멱등).
    """
    from ante.backtest.run_store import BacktestRunStore
    from ante.core.database import Database

    async def _query() -> int:
        db = Database(db_path)
        await db.connect()
        try:
            store = BacktestRunStore(db)
            await store.initialize()
            runs = await store.list_by_strategy(strategy_name)
            return len(runs)
        finally:
            await db.close()

    return asyncio.run(_query())


def _invoke_real_run(runner: CliRunner, tmp_path, *extra_args: str):
    """실제 BacktestService/ParquetStore/DB로 `backtest run`을 호출."""
    strategy_path = _write_strategy(tmp_path)
    data_path = tmp_path / "data"
    data_path.mkdir(exist_ok=True)
    db_path = tmp_path / "ante.db"

    return (
        runner.invoke(
            cli,
            [
                *extra_args,
                "backtest",
                "run",
                strategy_path,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
                "--data-path",
                str(data_path),
                "--db-path",
                str(db_path),
            ],
        ),
        str(db_path),
        data_path,
    )


class TestBacktestRunDataNotFound:
    """#1995: 명시 종목 전체가 무데이터(row_count=0)면 실패하고 이력을 남기지 않는다."""

    def test_all_explicit_symbols_no_data_fails_without_history(self, tmp_path):
        """(a) 재현: 빈 store + `--symbols 999999` → exit 1 + 이력 미저장.

        분기 추가 전에는 exit 0 성공 + backtest_runs 이력이 저장되는 fake
        success였다. 가드는 _save_backtest_run 이전에서 차단해야 한다.
        """
        runner = _make_runner()
        strategy_path = _write_strategy(tmp_path)
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        db_path = tmp_path / "ante.db"

        # store는 비어 있다(write 안 함) → 999999 row_count=0.
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                strategy_path,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
                "--symbols",
                "999999",
                "--data-path",
                str(data_path),
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_DATA_NOT_FOUND"
        # backtest_runs 이력이 남지 않아야 한다 (fake success 방지).
        assert _count_runs(str(db_path)) == 0

    def test_explicit_symbol_with_data_succeeds_and_saves_history(self, tmp_path):
        """(b) 회귀: 데이터 있는 종목 정상 run → exit 0 + run_id 저장."""
        runner = _make_runner()
        strategy_path = _write_strategy(tmp_path)
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        db_path = tmp_path / "ante.db"

        # ParquetStore에 005930 OHLCV를 적재해 row_count>0 을 만든다.
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=data_path)
        store.write("005930", "1d", _make_ohlcv_df("005930"))

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                strategy_path,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
                "--symbols",
                "005930",
                "--data-path",
                str(data_path),
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload.get("run_id")
        # 이력이 정확히 1건 저장된다.
        assert _count_runs(str(db_path)) == 1

    def test_no_symbols_run_skips_guard(self, tmp_path):
        """(c) 회귀: `--symbols` 생략(no-symbols) → 가드 미적용(기존 동작 보존).

        explicit_symbols 가 falsy([])이므로 데이터가 없어도 실패하지 않고
        기존 no-symbols 백테스트 경로(성공)를 그대로 탄다.
        """
        runner = _make_runner()
        result, db_path, _data_path = _invoke_real_run(
            runner, tmp_path, "--format", "json"
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload.get("run_id")
        # no-symbols 정상 run 은 기존대로 이력을 남긴다.
        assert _count_runs(str(db_path)) == 1

    def test_partial_missing_symbol_still_succeeds(self, tmp_path):
        """(d) 비목표 lock: 데이터 있는 종목 + 999999(무데이터) → 현행 성공.

        부분 누락은 #1995 비목표다. all(row_count==0) 이 False 이므로 가드를
        건너뛰고 기존 성공 동작을 유지해야 한다(회귀 방지).
        """
        runner = _make_runner()
        strategy_path = _write_strategy(tmp_path)
        data_path = tmp_path / "data"
        data_path.mkdir(exist_ok=True)
        db_path = tmp_path / "ante.db"

        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=data_path)
        store.write("005930", "1d", _make_ohlcv_df("005930"))

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                strategy_path,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
                "--symbols",
                "005930,999999",
                "--data-path",
                str(data_path),
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload.get("run_id")
        assert _count_runs(str(db_path)) == 1
