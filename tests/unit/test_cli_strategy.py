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


def _acm_factory(value):  # noqa: ANN001, ANN202
    """#1857: helper async context manager 전환에 맞춰 fake factory 를
    생성한다. 기존 ``new_callable=AsyncMock, return_value=(...)`` 패턴을
    ``new=_acm_factory((...))`` 로 대체해 ``async with helper(ctx) as
    (...):`` 호출이 yield 한 값을 그대로 받도록 한다.
    """
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def _fake_factory(*args, **kwargs):
        yield value

    return _fake_factory


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
                new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(cli, ["strategy", "info", "nonexistent"])
            assert result.exit_code == 1

    def test_info_not_found_json(self, runner):
        """JSON 모드 — 존재하지 않는 전략."""
        db = _mock_db()
        registry = _mock_registry([])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
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
                new=_acm_factory((registry, db)),
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
                new=_acm_factory((registry, db)),
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
                new=_acm_factory((registry, db)),
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
                new=_acm_factory((registry, db)),
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
            result = runner.invoke(
                cli,
                ["strategy", "performance", "momentum", "--account-id", "acc-test"],
            )
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
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
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
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["metrics"]["total_trades"] == 0

    def test_performance_account_required(self, runner):
        """--account-id 미지정 → STRATEGY_MISSING_REQUIRED_ACCOUNT 명시 실패 (#1218)."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "performance", "momentum"]
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data.get("code") == "STRATEGY_MISSING_REQUIRED_ACCOUNT"

    def test_performance_account_required_text(self, runner):
        """--account-id 미지정 + text 모드 — 명시 실패 (#1218)."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(cli, ["strategy", "performance", "momentum"])
            assert result.exit_code == 1
            assert "--account-id" in result.output

    def test_performance_with_account_id_passes_through(self, runner):
        """--account-id 명시 시 PerformanceTracker.calculate에 그대로 전달 (#1218)."""
        expected = {
            "strategy_name": "momentum",
            "strategy_id": "momentum_v1.0",
            "metrics": asdict(_SAMPLE_METRICS),
        }
        # 실제 _perf 코루틴 실행을 차단하기 위해 asyncio.run 결과만 mock한다.
        # 실패 분기(account-id 누락)는 별도 테스트가 책임지며, 본 테스트는
        # account-id 옵션이 있으면 SystemExit 없이 정상 흐름을 탄다는 것을 보장한다.
        with patch("ante.cli.commands.strategy.asyncio.run", return_value=expected):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["strategy_name"] == "momentum"

    @staticmethod
    def _patch_perf_internals(
        *,
        records,
        account_row,
        fetch_one_side_effect=None,
        metrics=None,
    ):
        """`_perf()` 내부 함수 지역 import 대상을 patch하는 컨텍스트 묶음.

        실제 ``_perf`` 코루틴을 실행해 account 존재 검증 분기를 직접 탄다.
        """
        db = MagicMock()
        db.connect = AsyncMock()
        db.close = AsyncMock()
        if fetch_one_side_effect is not None:
            db.fetch_one = AsyncMock(side_effect=fetch_one_side_effect)
        else:
            db.fetch_one = AsyncMock(return_value=account_row)

        registry = MagicMock()
        # #1753: `_perf()` 내부에서 `await registry.initialize()` 를 호출하므로
        # fresh DB 정합 회귀 후로는 AsyncMock 으로 await 가능하게 잠근다.
        registry.initialize = AsyncMock()
        registry.get_by_name = AsyncMock(return_value=records)

        tracker = MagicMock()
        tracker.calculate = AsyncMock(
            return_value=metrics if metrics is not None else _SAMPLE_METRICS
        )

        return (
            patch("ante.core.database.Database", return_value=db),
            patch("ante.cli.main.get_db_path", return_value=":memory:"),
            patch(
                "ante.strategy.registry.StrategyRegistry",
                return_value=registry,
            ),
            patch(
                "ante.trade.performance.PerformanceTracker",
                return_value=tracker,
            ),
            db,
            tracker,
        )

    def test_performance_missing_account_json(self, runner):
        """strategy 존재 + 미존재 account → exit 1 + ACCOUNT_NOT_FOUND (#1563)."""
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row=None,
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "oracle-missing-account",
                ],
            )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "ACCOUNT_NOT_FOUND"
        assert "oracle-missing-account" in data["message"]
        # account 미존재이므로 metric 계산까지 가지 않는다.
        tracker.calculate.assert_not_called()

    def test_performance_missing_account_text(self, runner):
        """미존재 account → text 모드 단건 에러 출력 + exit 1 (#1563)."""
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row=None,
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "oracle-missing-account",
                ],
            )
        assert result.exit_code == 1
        assert "계좌 'oracle-missing-account'를 찾을 수 없습니다." in result.output
        tracker.calculate.assert_not_called()

    def test_performance_real_account_regression(self, runner):
        """regression guard: 실재 account → exit 0 + metrics 유지 (#1563)."""
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row={"1": 1},
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["strategy_name"] == "momentum"
        assert data["metrics"]["total_trades"] == 10
        tracker.calculate.assert_awaited_once()

    def test_performance_filters_by_strategy_id_not_name(self, runner):
        """#2135: PerformanceTracker.calculate 에 record.strategy_id 로 필터.

        ``trades.strategy_id`` 는 ``{name}_v{version}`` (= record.strategy_id)
        형식으로 저장되므로, record.name(``momentum``)으로 필터하면 실거래가
        있어도 0건으로 집계된다. 따라서 calculate 는 record.strategy_id
        (``momentum_v1.0``)로 호출되어야 하며, 그 결과 metrics 가 0건이 아닌
        실제 집계로 반환된다. 픽스 전(record.name 전달)에는 kwargs 단언이
        ``momentum`` ≠ ``momentum_v1.0`` 으로 FAIL 한다.
        """
        # 실거래가 집계된 비-0 metrics. record.name 으로 필터하면 0건이 되는
        # 시나리오를 대표한다 (총 거래>0, 총 손익 반영).
        nonzero = PerformanceMetrics(
            total_trades=1,
            winning_trades=1,
            losing_trades=0,
            win_rate=1.0,
            total_pnl=10000.0,
            net_pnl=10000.0,
        )
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row={"1": 1},
            metrics=nonzero,
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        # 반환 dict shape 불변: name 과 strategy_id 둘 다 노출.
        assert data["strategy_name"] == _SAMPLE_RECORD.name  # "momentum"
        assert data["strategy_id"] == _SAMPLE_RECORD.strategy_id  # "momentum_v1.0"
        # 0건이 아니라 실제 집계가 반환된다.
        assert data["metrics"]["total_trades"] == 1
        assert data["metrics"]["total_pnl"] == 10000.0
        # 필터 인자는 record.name 이 아니라 record.strategy_id 여야 한다.
        tracker.calculate.assert_awaited_once_with(
            account_id="acc-test",
            strategy_id=_SAMPLE_RECORD.strategy_id,
        )
        # 회귀 방어: name 으로 호출되면 0건 집계로 회귀한다.
        _args, kwargs = tracker.calculate.await_args
        assert kwargs["strategy_id"] != _SAMPLE_RECORD.name

    def test_performance_strategy_not_found_regression(self, runner):
        """regression guard: strategy 미존재 → 기존 "전략을 찾을 수 없습니다" 유지.

        account 검증은 strategy records 확인 이후이므로, records가 없으면
        account 검증 분기에 도달하지 않고 기존 strategy-not-found 메시지를
        그대로 출력한다 (#1563 분기 순서 불변).
        """
        p_db, p_path, p_reg, p_track, db, _tracker = self._patch_perf_internals(
            records=[],
            account_row=None,
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "strategy",
                    "performance",
                    "nonexistent",
                    "--account-id",
                    "oracle-missing-account",
                ],
            )
        assert result.exit_code == 1
        assert "전략을 찾을 수 없습니다" in result.output
        # strategy 미존재이므로 account 존재 쿼리에 도달하지 않는다.
        db.fetch_one.assert_not_called()

    def test_performance_missing_account_no_accounts_table(self, runner):
        """accounts 테이블 부재 → missing-account로 정규화, OperationalError 비누설.

        부분 초기화/legacy DB에서 ``no such table: accounts``가 호출자까지
        전파되면 ACCOUNT_NOT_FOUND 계약을 우회한다. 동일 분기로 정규화 (#1563).
        """
        import sqlite3

        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row=None,
            fetch_one_side_effect=sqlite3.OperationalError("no such table: accounts"),
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "oracle-missing-account",
                ],
            )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["code"] == "ACCOUNT_NOT_FOUND"
        assert "no such table" not in result.output
        tracker.calculate.assert_not_called()

    def test_performance_other_operational_error_propagates(self, runner):
        """malformed db 등 다른 OperationalError는 삼키지 않고 비정상 종료 (#1563)."""
        import sqlite3

        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row=None,
            fetch_one_side_effect=sqlite3.OperationalError(
                "database disk image is malformed"
            ),
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
        # ACCOUNT_NOT_FOUND로 정규화되지 않고 예외가 전파된다.
        assert result.exit_code != 0
        assert "ACCOUNT_NOT_FOUND" not in result.output
        tracker.calculate.assert_not_called()

    # ── read-family follow-up: provided invalid account_id ingress 거부 ──
    # (#1657, oracle A7 cli_strategy_performance_invalid_account_id)
    #
    # docs/specs/account/14-account-id-contract.md L295: ``ante strategy
    # performance <name> --account-id <id>`` = read-family follow-up,
    # 목표 에러코드 = ``VALIDATION_ERROR``. provided invalid account_id
    # (``default``/``""``/패턴 위반)가 ``SELECT 1 FROM accounts`` 존재
    # 조회 이전 ingress에서 거부되지 않아 ``ACCOUNT_NOT_FOUND``로
    # 오분류되던 contract-drift를 ``reject_invalid_account_id`` 공유
    # 가드로 차단한다. 에러코드 SSOT는 #1633 선결정 재사용(신 코드 0).
    #
    # 3-way 분리 불변:
    #   invalid-format → VALIDATION_ERROR (본 픽스 목표)
    #   valid-format absent → ACCOUNT_NOT_FOUND (보존)
    #   omitted (--account-id 미지정) → STRATEGY_MISSING_REQUIRED_ACCOUNT (보존)
    # #1634/#1655 테스트 구조 미러.

    @pytest.mark.parametrize("invalid", ["default", "bad_id!", ""])
    def test_performance_invalid_account_id_rejected(self, runner, invalid):
        """(a) provided invalid account_id → VALIDATION_ERROR (ACCOUNT_NOT_FOUND 아님).

        #1657: invalid-format/예약어 account_id가 존재 SELECT 이전 ingress
        에서 거부되어 ``code=VALIDATION_ERROR``로 분류된다. 픽스 전 코드
        에서는 ``code=ACCOUNT_NOT_FOUND``로 오분류되어 본 단언이 FAIL한다.
        """
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    invalid,
                ],
            )
        assert result.exit_code != 0, result.output
        data = json.loads(result.output.strip())
        assert data["status"] == "error", data
        assert data["code"] == "VALIDATION_ERROR", data
        # not-found 오분류 차단 — invalid-format을 not-found로 분류 금지.
        assert data["code"] != "ACCOUNT_NOT_FOUND", data
        assert "찾을 수 없" not in result.output, result.output
        assert "Traceback" not in result.output, result.output

    def test_performance_valid_absent_account_keeps_not_found(self, runner):
        """(b) valid-format absent account_id → ACCOUNT_NOT_FOUND까지 실제 도달.

        #1657: helper가 형식 정상·미존재 account_id를 통과시켜 기존
        ``SELECT 1 FROM accounts`` → ``AccountNotFoundError`` →
        ``code=ACCOUNT_NOT_FOUND`` 경로가 보존된다. helper 삽입이
        non-None account_id 경로를 ``NameError`` 등으로 깨면 본 테스트가
        즉시 FAIL한다(NameError류 회귀 차단).
        """
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row=None,
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-9999",
                ],
            )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["status"] == "error", data
        assert data["code"] == "ACCOUNT_NOT_FOUND", data
        assert "acc-9999" in data["message"], data
        tracker.calculate.assert_not_called()

    def test_performance_omitted_account_keeps_missing_required(self, runner):
        """(c) --account-id 미지정 → STRATEGY_MISSING_REQUIRED_ACCOUNT 보존.

        #1657: omitted(account_id is None)는 helper 호출 이전
        ``if account_id is None:`` 가드가 선차단하므로
        ``STRATEGY_MISSING_REQUIRED_ACCOUNT`` 코드가 보존된다(helper는
        그 가드 이후 호출되어 None에 도달하지 않는다).
        """
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "strategy", "performance", "momentum"]
            )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["code"] == "STRATEGY_MISSING_REQUIRED_ACCOUNT", data

    def test_performance_valid_present_account_succeeds(self, runner):
        """(d) valid-format present account_id → 성공 경로 통과.

        #1657: helper가 형식 정상·존재 account_id를 통과시켜 정상 성과
        집계가 보존된다. helper 삽입이 non-None account_id 경로를
        ``NameError`` 등으로 깨면 본 테스트가 즉시 FAIL한다.
        """
        p_db, p_path, p_reg, p_track, _db, tracker = self._patch_perf_internals(
            records=[_SAMPLE_RECORD],
            account_row={"1": 1},
        )
        with p_db, p_path, p_reg, p_track:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "performance",
                    "momentum",
                    "--account-id",
                    "acc-test",
                ],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["strategy_name"] == "momentum", data
        assert data["metrics"]["total_trades"] == 10, data
        tracker.calculate.assert_awaited_once()


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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
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
            new=_acm_factory((registry, db)),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "strategy", "submit", strategy_file],
            )
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["submitted"] is False
            assert data["stage"] == "register"
