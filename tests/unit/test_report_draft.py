"""백테스트 리포트 초안 자동 생성 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.eventbus.events import BacktestCompleteEvent, NotificationEvent
from ante.member.models import Member, MemberRole, MemberType
from ante.report.draft import ReportDraftGenerator
from ante.report.models import ReportStatus

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_SAMPLE_RESULT = {
    "strategy": "momentum_v1.0.0",
    "period": "2025-01 ~ 2025-12",
    "initial_balance": 10_000_000,
    "final_balance": 11_500_000,
    "total_return_pct": 15.0,
    "total_trades": 42,
    "metrics": {
        "sharpe_ratio": 1.2,
        "max_drawdown": -8.5,
        "win_rate": 0.58,
        "profit_factor": 1.8,
    },
    "trades": [],
    "equity_curve": [],
}


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


class TestGenerateDraft:
    def test_generate_draft_basic(self):
        report = ReportDraftGenerator.generate_draft(_SAMPLE_RESULT)

        assert report.status == ReportStatus.DRAFT
        assert report.strategy_name == "momentum"
        assert report.strategy_version == "1.0.0"
        assert report.total_return_pct == 15.0
        assert report.total_trades == 42
        assert report.sharpe_ratio == 1.2
        assert report.max_drawdown_pct == -8.5
        assert report.win_rate == 0.58
        assert report.submitted_by == "system"
        assert "15.0%" in report.summary
        assert "42건" in report.summary

    def test_generate_draft_no_version(self):
        data = {**_SAMPLE_RESULT, "strategy": "simple_strategy"}
        report = ReportDraftGenerator.generate_draft(data)

        assert report.strategy_name == "simple_strategy"
        assert report.strategy_version == "0.0.0"

    def test_generate_draft_missing_metrics(self):
        data = {
            "strategy": "test_v1.0.0",
            "period": "2025-01 ~ 2025-06",
            "total_return_pct": 5.0,
            "total_trades": 10,
            "metrics": {},
        }
        report = ReportDraftGenerator.generate_draft(data)

        assert report.sharpe_ratio is None
        assert report.max_drawdown_pct is None
        assert report.win_rate is None

    def test_generate_draft_detail_json(self):
        report = ReportDraftGenerator.generate_draft(_SAMPLE_RESULT)
        detail = json.loads(report.detail_json)

        assert detail["total_return_pct"] == 15.0
        assert detail["metrics"]["sharpe_ratio"] == 1.2


class TestOnBacktestComplete:
    @pytest.mark.asyncio
    async def test_event_handler_creates_draft(self, tmp_path):
        result_file = tmp_path / "result.json"
        result_file.write_text(json.dumps(_SAMPLE_RESULT))

        mock_store = AsyncMock()
        mock_store.upsert_draft = AsyncMock(return_value="report-123")
        mock_eventbus = AsyncMock()
        mock_eventbus.subscribe = MagicMock()
        mock_eventbus.publish = AsyncMock()

        generator = ReportDraftGenerator(mock_store, mock_eventbus)

        event = BacktestCompleteEvent(
            backtest_id="bt-1",
            strategy_id="momentum_v1.0.0",
            status="completed",
            result_path=str(result_file),
        )

        await generator._on_backtest_complete(event)

        mock_store.upsert_draft.assert_called_once()
        submitted_report = mock_store.upsert_draft.call_args[0][0]
        assert submitted_report.status == ReportStatus.DRAFT
        assert submitted_report.total_return_pct == 15.0

        # NotificationEvent 발행 확인
        mock_eventbus.publish.assert_called_once()
        notification = mock_eventbus.publish.call_args[0][0]
        assert isinstance(notification, NotificationEvent)
        assert "초안 생성" in notification.title

    @pytest.mark.asyncio
    async def test_event_handler_skips_failed_backtest(self):
        mock_store = AsyncMock()
        mock_eventbus = AsyncMock()
        mock_eventbus.subscribe = MagicMock()

        generator = ReportDraftGenerator(mock_store, mock_eventbus)

        event = BacktestCompleteEvent(
            backtest_id="bt-2",
            strategy_id="test",
            status="failed",
            error_message="out of memory",
        )

        await generator._on_backtest_complete(event)

        mock_store.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_handler_handles_missing_result(self):
        mock_store = AsyncMock()
        mock_eventbus = AsyncMock()
        mock_eventbus.subscribe = MagicMock()

        generator = ReportDraftGenerator(mock_store, mock_eventbus)

        event = BacktestCompleteEvent(
            backtest_id="bt-3",
            strategy_id="test",
            status="completed",
            result_path="/nonexistent/path.json",
        )

        await generator._on_backtest_complete(event)

        mock_store.submit.assert_not_called()

    @pytest.mark.asyncio
    async def test_initialize_subscribes_to_event(self):
        mock_store = AsyncMock()
        mock_eventbus = MagicMock()
        mock_eventbus.subscribe = MagicMock()

        generator = ReportDraftGenerator(mock_store, mock_eventbus)
        generator.initialize()

        mock_eventbus.subscribe.assert_called_once()


class TestReportViewCLI:
    def test_view_existing_report(self, runner):
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = {
                "report_id": "rpt-1",
                "strategy": "momentum v1.0.0",
                "status": "draft",
                "submitted_at": "2026-03-13",
                "submitted_by": "system",
                "backtest_period": "2025-01 ~ 2025-12",
                "total_return_pct": 15.0,
                "total_trades": 42,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -8.5,
                "win_rate": 0.58,
                "summary": "백테스트 자동 생성 초안",
                "rationale": "",
                "risks": "",
                "recommendations": "",
            }
            result = runner.invoke(cli, ["report", "view", "rpt-1"])
            assert result.exit_code == 0
            assert "rpt-1" in result.output
            assert "draft" in result.output

    def test_view_not_found(self, runner):
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(cli, ["report", "view", "nonexistent"])
            assert result.exit_code == 0
            assert "찾을 수 없습니다" in result.output

    def test_view_json_format(self, runner):
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = {
                "report_id": "rpt-1",
                "strategy": "momentum v1.0.0",
                "status": "draft",
                "submitted_at": "2026-03-13",
                "submitted_by": "system",
                "backtest_period": "2025-01 ~ 2025-12",
                "total_return_pct": 15.0,
                "total_trades": 42,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": -8.5,
                "win_rate": 0.58,
                "summary": "초안",
                "rationale": "",
                "risks": "",
                "recommendations": "",
            }
            result = runner.invoke(cli, ["--format", "json", "report", "view", "rpt-1"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["report_id"] == "rpt-1"
            assert data["status"] == "draft"
