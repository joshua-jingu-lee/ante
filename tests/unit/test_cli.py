"""CLI 모듈 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.formatter import OutputFormatter
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


@pytest.fixture
def runner():
    """인증된 상태의 CliRunner (모든 커맨드 테스트용)."""
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


@pytest.fixture
def unauthenticated_runner():
    """인증 안 된 상태의 CliRunner."""
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def strategy_file(tmp_path):
    """유효한 전략 파일 생성."""
    code = """
from ante.strategy.base import Strategy, StrategyMeta, Signal


class TestStrategy(Strategy):
    meta = StrategyMeta(
        name="test_cli",
        version="1.0",
        description="CLI test strategy",
    )

    async def on_step(self, context):
        return []
"""
    path = tmp_path / "test_strategy.py"
    path.write_text(code)
    return path


@pytest.fixture
def invalid_strategy_file(tmp_path):
    """유효하지 않은 전략 파일."""
    code = "import os\nprint('not a strategy')"
    path = tmp_path / "bad_strategy.py"
    path.write_text(code)
    return path


# ── OutputFormatter 테스트 ──────────────────────────


class TestOutputFormatter:
    def test_output_text(self, capsys):
        fmt = OutputFormatter("text")
        fmt.output({"name": "test"}, "Name: {name}")
        captured = capsys.readouterr()
        assert "Name: test" in captured.out

    def test_output_json(self, capsys):
        fmt = OutputFormatter("json")
        fmt.output({"name": "test"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["name"] == "test"

    def test_table_text(self, capsys):
        fmt = OutputFormatter("text")
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        fmt.table(rows, ["a", "b"])
        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "---" in captured.out

    def test_table_json(self, capsys):
        fmt = OutputFormatter("json")
        rows = [{"a": 1}]
        fmt.table(rows, ["a"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data[0]["a"] == 1

    def test_table_empty(self, capsys):
        fmt = OutputFormatter("text")
        fmt.table([], ["a"])
        captured = capsys.readouterr()
        assert "(no data)" in captured.out

    def test_error_text(self, capsys):
        fmt = OutputFormatter("text")
        fmt.error("something failed")
        captured = capsys.readouterr()
        assert "something failed" in captured.err

    def test_error_json(self, capsys):
        fmt = OutputFormatter("json")
        fmt.error("fail", code="ERR01")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"status": "error", "code": "ERR01", "message": "fail"}
        assert "error" not in data

    def test_success_text(self, capsys):
        fmt = OutputFormatter("text")
        fmt.success("done!")
        captured = capsys.readouterr()
        assert "done!" in captured.out

    def test_success_json(self, capsys):
        fmt = OutputFormatter("json")
        fmt.success("ok", {"count": 5})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert set(data) == {"status", "message", "data"}
        assert data["status"] == "ok"
        assert data["message"] == "ok"
        assert data["data"] == {"count": 5}
        assert "count" not in data

    def test_success_json_no_data(self, capsys):
        fmt = OutputFormatter("json")
        fmt.success("done!")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"status": "ok", "message": "done!", "data": {}}

    def test_success_json_preserves_payload_status(self, capsys):
        fmt = OutputFormatter("json")
        fmt.success("member revoked", {"status": "revoked"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "ok"
        assert data["data"]["status"] == "revoked"

    def test_is_json(self):
        assert OutputFormatter("json").is_json is True
        assert OutputFormatter("text").is_json is False


# ── CLI 기본 테스트 ──────────────────────────────────


class TestCLIBasic:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Ante" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "ante, version" in result.output

    def test_format_option(self, runner):
        result = runner.invoke(cli, ["--format", "json", "--help"])
        assert result.exit_code == 0

    def test_strategy_group(self, runner):
        result = runner.invoke(cli, ["strategy", "--help"])
        assert result.exit_code == 0
        assert "validate" in result.output

    def test_data_group(self, runner):
        result = runner.invoke(cli, ["data", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_backtest_group(self, runner):
        result = runner.invoke(cli, ["backtest", "--help"])
        assert result.exit_code == 0
        assert "run" in result.output

    def test_report_group(self, runner):
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0
        assert "schema" in result.output


# ── Strategy 커맨드 테스트 ──────────────────────────


class TestStrategyCommands:
    def test_validate_valid(self, runner, strategy_file):
        result = runner.invoke(cli, ["strategy", "validate", str(strategy_file)])
        assert result.exit_code == 0
        assert "passed" in result.output

    def test_validate_valid_json(self, runner, strategy_file):
        result = runner.invoke(
            cli, ["--format", "json", "strategy", "validate", str(strategy_file)]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"

    def test_validate_invalid(self, runner, invalid_strategy_file):
        # #1541: validation failure must exit 1 (single source of truth, not 0).
        result = runner.invoke(
            cli, ["strategy", "validate", str(invalid_strategy_file)]
        )
        assert result.exit_code == 1
        # text 모드에서는 stderr에 "Error: Validation failed: ..."가 들어간다.
        # CliRunner는 기본적으로 stderr를 stdout과 합치므로 result.output로 점검한다.
        combined = result.output
        assert "Validation failed" in combined

    def test_validate_invalid_json_single_envelope(self, runner, invalid_strategy_file):
        """#1541: JSON 모드 invalid 입력은 단일 envelope + exit 1로 종료한다."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "strategy",
                "validate",
                str(invalid_strategy_file),
            ],
        )
        assert result.exit_code == 1
        # 단일 JSON 문서로 파싱 가능해야 한다 (두 개의 문서 출력 금지).
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "STRATEGY_VALIDATION_FAILED"
        assert "Validation failed" in data["message"]
        assert data["data"]["valid"] is False
        assert isinstance(data["data"]["errors"], list)
        assert isinstance(data["data"]["warnings"], list)

    def test_validate_invalid_text_stderr(self, runner, invalid_strategy_file):
        """#1541: text 모드 invalid 입력은 stderr에 에러+상세 라인을 내보낸다."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "text",
                "strategy",
                "validate",
                str(invalid_strategy_file),
            ],
        )
        assert result.exit_code == 1
        assert "Error: Validation failed" in result.output

    def test_validate_nonexistent(self, runner):
        result = runner.invoke(cli, ["strategy", "validate", "/nonexistent.py"])
        assert result.exit_code != 0

    def test_list(self, runner):
        from unittest.mock import AsyncMock, MagicMock

        db = MagicMock()
        db.connect = AsyncMock()
        db.close = AsyncMock()
        registry = MagicMock()
        registry.list_strategies = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "list"])
            assert result.exit_code == 0


# ── Data 커맨드 테스트 ──────────────────────────────


class TestDataCommands:
    def test_list_empty(self, runner, data_dir):
        result = runner.invoke(cli, ["data", "list", "--data-path", str(data_dir)])
        assert result.exit_code == 0

    def test_list_json(self, runner, data_dir):
        result = runner.invoke(
            cli,
            ["--format", "json", "data", "list", "--data-path", str(data_dir)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 0

    def test_schema(self, runner, data_dir):
        result = runner.invoke(cli, ["data", "schema", "--data-path", str(data_dir)])
        assert result.exit_code == 0

    def test_schema_json(self, runner, data_dir):
        result = runner.invoke(
            cli,
            ["--format", "json", "data", "schema", "--data-path", str(data_dir)],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "timestamp" in data

    def test_storage(self, runner, data_dir):
        result = runner.invoke(cli, ["data", "storage", "--data-path", str(data_dir)])
        assert result.exit_code == 0


# ── Report 커맨드 테스트 ──────────────────────────


class TestReportCommands:
    def test_schema(self, runner):
        result = runner.invoke(cli, ["report", "schema"])
        assert result.exit_code == 0

    def test_schema_json(self, runner):
        result = runner.invoke(cli, ["--format", "json", "report", "schema"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "strategy_name" in data or isinstance(data, dict)
