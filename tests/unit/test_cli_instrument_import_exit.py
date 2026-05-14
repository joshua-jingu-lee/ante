"""``instrument import`` validation 경로의 nonzero exit code 보장 테스트 (#1516).

이슈 #1516 (oracle A7 cli_instrument_import_error_exit_zero):
``ante instrument import``의 5개 validation branch가 ``fmt.error(...)``로 error를
출력하면서도 ``return``만 수행해 exit code 0으로 종료되던 ingress drift를 닫는다.
#1515의 missing-resource 패턴(``ctx.exit(1)``)과 동일한 정책으로 통합한다.

분류 메모:
- ``instrument import``는 spec ``docs/specs/cli/03-commands.md``상 offline CLI —
  IPC route 없음 (handler 19개 외).
- ``Formatter.error()`` 자체는 미변경 — 출력은 호출자 책임, exit은 caller가
  ``ctx.exit(1)``로 강제.
- 검증된 사이트 5개:
    1. JSON shape (array 아님) — oracle probe 재현
    2. unsupported file extension (.txt 등)
    3. 파일 읽기 실패 (corrupt JSON)
    4. 빈 데이터 (`[]`)
    5. 필수 컬럼 누락 (symbol/exchange 부재)
- 회귀 보존: valid `--dry-run`은 exit 0 유지.
"""

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


@pytest.fixture()
def runner() -> CliRunner:
    """인증을 mock으로 우회한 CliRunner.

    stderr/stdout 분리(``mix_stderr=False``)로 text 모드 ``Error:`` 메시지가
    stderr로 가는지, JSON 모드 envelope이 stdout으로 가는지 분리 검증한다.
    """
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


# ── 1. JSON shape: array 아닌 object → exit 1 (oracle probe 재현) ──


class TestJsonNotArrayExit:
    """``instrument import <object.json>`` 은 exit 1 + ``배열 형태`` 메시지."""

    def test_json_object_exits_nonzero_text(self, runner: CliRunner, tmp_path) -> None:
        json_file = tmp_path / "object.json"
        json_file.write_text('{"symbol": "005930", "exchange": "KRX"}')

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file), "--dry-run"],
        )

        assert result.exit_code == 1, result.stderr
        assert "배열 형태" in result.stderr

    def test_json_object_exits_nonzero_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """oracle probe 시그니처와 정확히 동일한 경로: ``--format json`` 모드."""
        json_file = tmp_path / "object.json"
        json_file.write_text('{"symbol": "005930", "exchange": "KRX"}')

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

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "배열 형태" in payload["message"]


# ── 2. unsupported extension → exit 1 ──


class TestUnsupportedExtensionExit:
    def test_txt_exits_nonzero_text(self, runner: CliRunner, tmp_path) -> None:
        txt_file = tmp_path / "instruments.txt"
        txt_file.write_text("symbol,exchange\n005930,KRX\n")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(txt_file)],
        )

        assert result.exit_code == 1, result.stderr
        assert "지원하지 않는 파일 형식" in result.stderr

    def test_txt_exits_nonzero_json_envelope(self, runner: CliRunner, tmp_path) -> None:
        txt_file = tmp_path / "instruments.txt"
        txt_file.write_text("symbol,exchange\n005930,KRX\n")

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(txt_file)],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "지원하지 않는 파일 형식" in payload["message"]


# ── 3. 파일 읽기 실패 (corrupt JSON) → exit 1 ──


class TestFileReadFailureExit:
    """corrupt JSON: ``json.JSONDecodeError`` → ``except Exception`` → exit 1."""

    def test_corrupt_json_exits_nonzero_text(self, runner: CliRunner, tmp_path) -> None:
        json_file = tmp_path / "corrupt.json"
        json_file.write_text("{not valid json")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stderr
        assert "파일 읽기 실패" in result.stderr

    def test_corrupt_json_exits_nonzero_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "corrupt.json"
        json_file.write_text("{not valid json")

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "파일 읽기 실패" in payload["message"]


# ── 4. 빈 데이터 (`[]`) → exit 1 ──


class TestEmptyDataExit:
    def test_empty_json_array_exits_nonzero_text(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "empty.json"
        json_file.write_text("[]")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stderr
        assert "데이터가 없습니다" in result.stderr

    def test_empty_csv_exits_nonzero_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("symbol,exchange\n")

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(csv_file)],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "데이터가 없습니다" in payload["message"]


# ── 5. 필수 컬럼 누락 → exit 1 ──


class TestMissingRequiredColumnsExit:
    def test_missing_symbol_exchange_json_exits_nonzero_text(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "bad.json"
        json_file.write_text('[{"name": "x"}]')

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stderr
        assert "필수 컬럼 누락" in result.stderr

    def test_missing_symbol_exchange_csv_exits_nonzero_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("name,type\nSamsung,stock\n")

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(csv_file)],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "필수 컬럼 누락" in payload["message"]


# ── 6. valid dry-run 회귀 보존 → exit 0 ──


class TestValidDryRunRegression:
    """valid input의 ``--dry-run``은 exit 0으로 회귀 보존."""

    def test_valid_json_dry_run_exits_zero(self, runner: CliRunner, tmp_path) -> None:
        json_file = tmp_path / "ok.json"
        json_file.write_text(json.dumps([{"symbol": "005930", "exchange": "KRX"}]))

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file), "--dry-run"],
        )

        assert result.exit_code == 0, result.stderr
        assert "005930" in result.stdout

    def test_valid_json_dry_run_format_json_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "ok.json"
        json_file.write_text(json.dumps([{"symbol": "005930", "exchange": "KRX"}]))

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

        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["dry_run"] is True
        assert payload["total"] == 1
