"""CLI config 커맨드 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

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


class TestConfigGet:
    def test_get_specific_key_static(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = "INFO"
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "get", "system.log_level"])
            assert result.exit_code == 0
            assert "INFO" in result.output
            assert "static" in result.output

    def test_get_specific_key_dynamic(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=True)
            mock_dynamic.get = AsyncMock(return_value=42)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "get", "custom.key"])
            assert result.exit_code == 0
            assert "42" in result.output
            assert "dynamic" in result.output

    def test_get_not_found(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = None
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "get", "nonexistent.key"])
            assert result.exit_code == 0
            assert "찾을 수 없습니다" in result.output

    def test_get_all_json(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.side_effect = lambda k, d=None: d
            mock_dynamic = AsyncMock()
            mock_db = AsyncMock()
            mock_db.fetch_all = AsyncMock(return_value=[])
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["--format", "json", "config", "get"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "configs" in data
            assert len(data["configs"]) > 0

    def test_get_specific_key_json(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=True)
            mock_dynamic.get = AsyncMock(return_value="DEBUG")
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(
                cli, ["--format", "json", "config", "get", "system.log_level"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["key"] == "system.log_level"
            assert data["value"] == "DEBUG"
            assert data["source"] == "dynamic"


class TestConfigSet:
    def test_set_dynamic_key(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = None
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_dynamic.set = AsyncMock()
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "set", "custom.key", "hello"])
            assert result.exit_code == 0
            assert "변경 완료" in result.output

    def test_set_static_key_rejected(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = "INFO"
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "set", "system.log_level", "DEBUG"])
            assert result.exit_code == 0
            assert "정적 설정" in result.output

    def test_set_json_value(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = None
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_dynamic.set = AsyncMock()
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(cli, ["config", "set", "custom.count", "42"])
            assert result.exit_code == 0
            assert "변경 완료" in result.output

    def test_set_json_format(self, runner):
        with patch("ante.cli.commands.config._create_services") as mock_svc:
            mock_config = MagicMock()
            mock_config.get.return_value = None
            mock_dynamic = AsyncMock()
            mock_dynamic.exists = AsyncMock(return_value=False)
            mock_dynamic.set = AsyncMock()
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_config, mock_dynamic, mock_db)

            result = runner.invoke(
                cli,
                ["--format", "json", "config", "set", "custom.flag", "true"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True
            assert data["key"] == "custom.flag"
            assert data["value"] is True
