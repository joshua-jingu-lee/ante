"""CLI strategy list/info/performance/submit 커맨드 단위 테스트."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.registry import StrategyRecord, StrategyStatus
from ante.trade.models import PerformanceMetrics

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)

_SAMPLE_RECORD = StrategyRecord(
    strategy_id="momentum_v1.0",
    name="momentum",
    version="1.0",
    filepath="/strategies/momentum.py",
    status=StrategyStatus.ADOPTED,
    registered_at=_NOW,
    description="모멘텀 전략",
    author_name="agent",
    author_id="agent",
    validation_warnings=[],
)

_SAMPLE_RECORD_V2 = StrategyRecord(
    strategy_id="momentum_v2.0",
    name="momentum",
    version="2.0",
    filepath="/strategies/momentum_v2.py",
    status=StrategyStatus.REGISTERED,
    registered_at=_NOW,
    description="모멘텀 전략 v2",
    author_name="agent",
    author_id="agent",
    validation_warnings=["warning1"],
)

_SAMPLE_METRICS = PerformanceMetrics(
    total_trades=10,
    winning_trades=7,
    losing_trades=3,
    win_rate=0.7,
    total_pnl=500000.0,
    total_commission=5000.0,
    net_pnl=495000.0,
    avg_profit=100000.0,
    avg_loss=50000.0,
    profit_factor=4.67,
    max_drawdown=0.05,
    max_drawdown_amount=25000.0,
    sharpe_ratio=1.5,
    first_trade_at=_NOW,
    last_trade_at=_NOW,
    active_days=5,
)


@pytest.fixture
def runner():
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


def _mock_db():
    """Mock Database with connect/close."""
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


def _mock_registry(strategies=None):
    """Mock StrategyRegistry."""
    registry = MagicMock()
    registry.list_strategies = AsyncMock(return_value=strategies or [])
    registry.get_by_name = AsyncMock(return_value=strategies or [])
    return registry


class TestStrategyList:
    def test_list_empty(self, runner):
        """전략이 없으면 빈 목록 출력."""
        db = _mock_db()
        registry = _mock_registry([])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
        ):
            result = runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0
            assert "등록된 전략 없음" in result.output

    def test_list_empty_json(self, runner):
        """JSON 모드 — 빈 목록."""
        db = _mock_db()
        registry = _mock_registry([])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "strategy", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["strategies"] == []

    def test_list_with_strategies(self, runner):
        """전략이 있으면 테이블 출력."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0
            assert "momentum" in result.output

    def test_list_json(self, runner):
        """JSON 모드 — 전략 목록."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "strategy", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data["strategies"]) == 1
            assert data["strategies"][0]["name"] == "momentum"
            assert data["strategies"][0]["strategy_id"] == "momentum_v1.0"

    def test_list_with_status_filter(self, runner):
        """--status 필터 적용."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "list", "--status", "adopted"])
            assert result.exit_code == 0
            registry.list_strategies.assert_called_once_with(
                status=StrategyStatus.ADOPTED,
            )


class TestStrategyInfo:
    def test_info_not_found(self, runner):
        """존재하지 않는 전략."""
        db = _mock_db()
        registry = _mock_registry([])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "info", "nonexistent"])
            assert result.exit_code == 1

    def test_info_not_found_json(self, runner):
        """JSON 모드 — 존재하지 않는 전략."""
        db = _mock_db()
        registry = _mock_registry([])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "info", "nonexistent"]
            )
            assert result.exit_code == 1

    def test_info_found(self, runner):
        """전략 상세 정보 출력."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value={
                    "params": {"period": 20},
                    "param_schema": {"period": "이동평균 기간"},
                    "rationale": "모멘텀 기반 추세 추종",
                    "risks": ["급반전 시 손실 확대"],
                },
            ),
        ):
            result = runner.invoke(cli, ["strategy", "info", "momentum"])
            assert result.exit_code == 0
            assert "momentum" in result.output
            assert "1.0" in result.output

    def test_info_json(self, runner):
        """JSON 모드 — 전략 상세."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value={
                    "params": {"period": 20},
                    "param_schema": {"period": "이동평균 기간"},
                    "rationale": "모멘텀 기반 추세 추종",
                    "risks": ["급반전 시 손실 확대"],
                },
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "info", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "momentum"
            assert data["params"] == {"period": 20}
            assert data["param_schema"] == {"period": "이동평균 기간"}
            assert data["rationale"] == "모멘텀 기반 추세 추종"
            assert data["risks"] == ["급반전 시 손실 확대"]

    def test_info_multiple_versions(self, runner):
        """동일 이름의 여러 버전이 있을 때 최신 버전 + 다른 버전 목록."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD_V2, _SAMPLE_RECORD])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "info", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["version"] == "2.0"
            assert len(data["other_versions"]) == 1
            assert data["other_versions"][0]["version"] == "1.0"

    def test_info_params_load_failure(self, runner):
        """전략 파일 로드 실패 시 params 필드 없음."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "info", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "params" not in data


class TestStrategyPerformance:
    def test_perf_not_found(self, runner):
        """존재하지 않는 전략."""
        with (
            patch("ante.cli.commands.strategy.asyncio.run") as mock_run,
        ):
            mock_run.return_value = None
            result = runner.invoke(cli, ["strategy", "performance", "nonexistent"])
            assert result.exit_code == 1

    def test_perf_found(self, runner):
        """전략 성과 출력 (text 모드)."""
        expected = {
            "strategy_name": "momentum",
            "strategy_id": "momentum_v1.0",
            "metrics": asdict(_SAMPLE_METRICS),
        }

        with patch("ante.cli.commands.strategy.asyncio.run", return_value=expected):
            result = runner.invoke(cli, ["strategy", "performance", "momentum"])
            assert result.exit_code == 0
            assert "momentum" in result.output
            assert "70.0%" in result.output

    def test_perf_json(self, runner):
        """JSON 모드 — 전략 성과."""
        expected = {
            "strategy_name": "momentum",
            "strategy_id": "momentum_v1.0",
            "metrics": asdict(_SAMPLE_METRICS),
        }

        with patch("ante.cli.commands.strategy.asyncio.run", return_value=expected):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "performance", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["strategy_name"] == "momentum"
            assert data["metrics"]["total_trades"] == 10
            assert data["metrics"]["win_rate"] == 0.7

    def test_perf_empty_metrics(self, runner):
        """거래 없는 전략 성과."""
        empty = PerformanceMetrics()
        expected = {
            "strategy_name": "momentum",
            "strategy_id": "momentum_v1.0",
            "metrics": asdict(empty),
        }

        with patch("ante.cli.commands.strategy.asyncio.run", return_value=expected):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "performance", "momentum"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["metrics"]["total_trades"] == 0


class TestStrategySubmit:
    """ante strategy submit 커맨드 테스트."""

    @pytest.fixture
    def strategy_file(self, tmp_path):
        """유효한 전략 파일 생성."""
        import textwrap

        code = textwrap.dedent("""\
            from ante.strategy.base import Strategy, StrategyMeta, Signal

            class MyStrategy(Strategy):
                meta = StrategyMeta(
                    name="test_strat",
                    version="1.0.0",
                    description="Test strategy",
                    author="agent",
                )

                async def on_step(self, context):
                    return []
        """)
        fp = tmp_path / "test_strat.py"
        fp.write_text(code)
        return str(fp)

    @pytest.fixture
    def invalid_strategy_file(self, tmp_path):
        """검증 실패하는 전략 파일 (Strategy 클래스 없음)."""
        fp = tmp_path / "bad_strat.py"
        fp.write_text("x = 1\n")
        return str(fp)

    def test_submit_success(self, runner, strategy_file):
        """검증 -> 로드 -> 등록 전체 성공 플로우."""

        mock_record = StrategyRecord(
            strategy_id="test_strat_v1.0.0",
            name="test_strat",
            version="1.0.0",
            filepath=strategy_file,
            status=StrategyStatus.REGISTERED,
            registered_at=_NOW,
            description="Test strategy",
            author_name="agent",
            author_id="agent",
            validation_warnings=[],
        )

        db = _mock_db()
        registry = MagicMock()
        registry.initialize = AsyncMock()
        registry.register = AsyncMock(return_value=mock_record)

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "submit", strategy_file])
            assert result.exit_code == 0
            assert "test_strat_v1.0.0" in result.output

    def test_submit_success_json(self, runner, strategy_file):
        """JSON 모드 성공 출력."""
        mock_record = StrategyRecord(
            strategy_id="test_strat_v1.0.0",
            name="test_strat",
            version="1.0.0",
            filepath=strategy_file,
            status=StrategyStatus.REGISTERED,
            registered_at=_NOW,
            description="Test strategy",
            author_name="agent",
            author_id="agent",
            validation_warnings=[],
        )

        db = _mock_db()
        registry = MagicMock()
        registry.initialize = AsyncMock()
        registry.register = AsyncMock(return_value=mock_record)

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "submit", strategy_file]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["submitted"] is True
            assert data["strategy_id"] == "test_strat_v1.0.0"
            assert data["name"] == "test_strat"
            assert data["version"] == "1.0.0"

    def test_submit_validation_failure(self, runner, invalid_strategy_file):
        """정적 검증 실패 시 exit 1."""
        result = runner.invoke(cli, ["strategy", "submit", invalid_strategy_file])
        assert result.exit_code == 1

    def test_submit_validation_failure_json(self, runner, invalid_strategy_file):
        """JSON 모드 — 검증 실패."""
        result = runner.invoke(
            cli,
            ["--format", "json", "strategy", "submit", invalid_strategy_file],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["submitted"] is False
        assert data["stage"] == "validate"
        assert len(data["errors"]) > 0

    def test_submit_load_failure(self, runner, tmp_path):
        """로드 테스트 실패 (올바른 AST이지만 import 불가)."""
        import textwrap

        # 검증은 통과하지만 로드 시 실패하는 전략 파일
        code = textwrap.dedent("""\
            from ante.strategy.base import Strategy, StrategyMeta, Signal

            class BrokenStrategy(Strategy):
                meta = StrategyMeta(
                    name="broken",
                    version="1.0.0",
                    description="Broken",
                )

                async def on_step(self, context):
                    return []

                def __init_subclass__(cls, **kwargs):
                    raise RuntimeError("intentional break")
        """)
        fp = tmp_path / "broken.py"
        fp.write_text(code)

        # 검증은 통과하도록 mock, 로드만 실패
        from ante.strategy.exceptions import StrategyLoadError

        with patch(
            "ante.strategy.loader.StrategyLoader.load",
            side_effect=StrategyLoadError("Cannot load"),
        ):
            result = runner.invoke(cli, ["strategy", "submit", str(fp)])
            assert result.exit_code == 1

    def test_submit_duplicate(self, runner, strategy_file):
        """중복 등록 시 에러."""
        from ante.strategy.exceptions import StrategyError

        db = _mock_db()
        registry = MagicMock()
        registry.initialize = AsyncMock()
        registry.register = AsyncMock(
            side_effect=StrategyError("Strategy already registered: test_strat_v1.0.0")
        )

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "submit", strategy_file])
            assert result.exit_code == 1
            assert "already registered" in result.output

    def test_submit_duplicate_json(self, runner, strategy_file):
        """JSON 모드 — 중복 등록 에러."""
        from ante.strategy.exceptions import StrategyError

        db = _mock_db()
        registry = MagicMock()
        registry.initialize = AsyncMock()
        registry.register = AsyncMock(
            side_effect=StrategyError("Strategy already registered: test_strat_v1.0.0")
        )

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "strategy", "submit", strategy_file],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["submitted"] is False
            assert data["stage"] == "register"
