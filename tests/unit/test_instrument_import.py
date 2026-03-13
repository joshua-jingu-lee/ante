"""종목 데이터 import CLI 단위 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

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


class TestInstrumentImportCSV:
    def test_import_csv(self, runner, tmp_path):
        csv_file = tmp_path / "instruments.csv"
        csv_file.write_text(
            "symbol,exchange,name,instrument_type\n"
            "005930,KRX,삼성전자,stock\n"
            "000660,KRX,SK하이닉스,stock\n"
        )

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = 2
            result = runner.invoke(
                cli,
                ["instrument", "import", str(csv_file)],
            )
            assert result.exit_code == 0
            assert "2건" in result.output

    def test_import_csv_dry_run(self, runner, tmp_path):
        csv_file = tmp_path / "instruments.csv"
        csv_file.write_text("symbol,exchange,name\n005930,KRX,삼성전자\n")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(csv_file), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "미리보기" in result.output
        assert "005930" in result.output


class TestInstrumentImportJSON:
    def test_import_json(self, runner, tmp_path):
        json_file = tmp_path / "instruments.json"
        data = [
            {"symbol": "005930", "exchange": "KRX", "name": "삼성전자"},
            {"symbol": "000660", "exchange": "KRX", "name": "SK하이닉스"},
        ]
        json_file.write_text(json.dumps(data))

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = 2
            result = runner.invoke(
                cli,
                ["instrument", "import", str(json_file)],
            )
            assert result.exit_code == 0
            assert "2건" in result.output

    def test_import_json_dry_run_format(self, runner, tmp_path):
        json_file = tmp_path / "instruments.json"
        data = [{"symbol": "005930", "exchange": "KRX"}]
        json_file.write_text(json.dumps(data))

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "instrument",
                "import",
                str(json_file),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["dry_run"] is True
        assert output["total"] == 1


class TestInstrumentImportErrors:
    def test_unsupported_extension(self, runner, tmp_path):
        xml_file = tmp_path / "instruments.xml"
        xml_file.write_text("<data/>")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(xml_file)],
        )
        assert "지원하지 않는 파일 형식" in result.output

    def test_missing_required_columns(self, runner, tmp_path):
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("name,type\nSamsung,stock\n")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(csv_file)],
        )
        assert "필수 컬럼 누락" in result.output

    def test_empty_file(self, runner, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("symbol,exchange\n")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(csv_file)],
        )
        assert "데이터가 없습니다" in result.output

    def test_json_not_array(self, runner, tmp_path):
        json_file = tmp_path / "bad.json"
        json_file.write_text('{"symbol": "005930"}')

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file)],
        )
        assert "배열 형태" in result.output
