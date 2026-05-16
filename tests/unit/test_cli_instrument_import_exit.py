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

#1611 (split #1598 oracle A7 cli_instrument_import_invalid_krx_symbol):
exchange == KRX 행의 비6자리 symbol(예: ``ABCDEF``)을 dry-run/실 import
양쪽에서 ``INSTRUMENT_INVALID_SYMBOL`` 구조화 에러로 거부한다. 검증은
``core.market_data_vocab.is_krx_symbol`` SSOT(#1613) 위임이며 기존
exchange per-row 검증 루프(#1577)에 동형 확장한다. 비-KRX canonical
(NYSE/NASDAQ/AMEX/TEST)은 symbol-shape 미적용 (core.md 1.0 비목표).
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


# ── 7. exchange == KRX 행의 비6자리 symbol → exit 1 (#1611) ──


class TestKrxInvalidSymbolExit:
    """``exchange=KRX`` + 비6자리 ``symbol`` → exit 1 + 구조화 error code.

    #1598 oracle probe 재현: ``[{"symbol":"ABCDEF","exchange":"KRX"}]`` 가
    dry-run preview/실 import로 수락되던 ingress drift를 닫는다. dry-run·
    실 import 양쪽에서 instruments build/저장 이전에 거부된다.
    """

    def test_invalid_krx_symbol_dry_run_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """oracle probe 시그니처: ``--format json ... --dry-run``."""
        json_file = tmp_path / "inv_sym.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "symbol": "ABCDEF",
                        "exchange": "KRX",
                        "name": "Oracle Invalid Symbol",
                    }
                ]
            )
        )

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
        assert payload["code"] == "INSTRUMENT_INVALID_SYMBOL"
        assert "ABCDEF" in payload["message"]

    def test_invalid_krx_symbol_dry_run_text(self, runner: CliRunner, tmp_path) -> None:
        json_file = tmp_path / "inv_sym.json"
        json_file.write_text(
            json.dumps([{"symbol": "ABCDEF", "exchange": "KRX", "name": "x"}])
        )

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file), "--dry-run"],
        )

        assert result.exit_code == 1, result.stderr
        assert "유효하지 않은 종목 코드" in result.stderr

    def test_invalid_krx_symbol_real_import_not_reached(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """dry-run 없이도 import 미수행 + 동일 error contract.

        ``asyncio.run`` (``_import()`` 진입점)이 호출되지 않아야 한다 —
        검증이 InstrumentService/저장 이전에 차단함을 잠근다.
        """
        json_file = tmp_path / "inv_sym.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "symbol": "ABCDEF",
                        "exchange": "KRX",
                        "name": "Oracle Invalid Symbol",
                    }
                ]
            )
        )

        with patch("asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                ["--format", "json", "instrument", "import", str(json_file)],
            )

        assert result.exit_code == 1, result.stdout
        mock_run.assert_not_called()
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "INSTRUMENT_INVALID_SYMBOL"

    def test_non_string_krx_symbol_rejected_structured(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """KRX 행의 비문자열 symbol(JSON list/dict/number/None)도
        traceback이 아닌 구조화 ``INSTRUMENT_INVALID_SYMBOL`` exit 1.

        ``is_krx_symbol`` 의 ``isinstance(str)`` 가드가 ``re.fullmatch``
        의 ``TypeError`` 를 fail-closed False로 잠근다.
        """
        json_file = tmp_path / "nonstr_sym.json"
        json_file.write_text(
            json.dumps([{"symbol": 5930, "exchange": "KRX", "name": "x"}])
        )

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stdout
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            result.exception
        )
        payload = json.loads(result.stdout)
        assert payload["code"] == "INSTRUMENT_INVALID_SYMBOL"

    def test_invalid_krx_symbol_among_valid_rows_rejected(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """유효 KRX 행 뒤에 섞인 비6자리 KRX symbol 행도 식별·거부."""
        json_file = tmp_path / "mixed_sym.json"
        json_file.write_text(
            json.dumps(
                [
                    {"symbol": "005930", "exchange": "KRX"},
                    {"symbol": "12345", "exchange": "KRX"},
                ]
            )
        )

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
        assert payload["code"] == "INSTRUMENT_INVALID_SYMBOL"
        assert "12345" in payload["message"]


# ── 8. valid KRX symbol → 기존 preview/import 경로 회귀 보존 (#1611) ──


class TestValidKrxSymbolRegression:
    """``[{"symbol":"005930","exchange":"KRX",...}]`` 는 기존 동작 유지."""

    def test_valid_krx_symbol_dry_run_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "ok_krx.json"
        json_file.write_text(
            json.dumps(
                [
                    {
                        "symbol": "005930",
                        "exchange": "KRX",
                        "name": "Samsung Electronics",
                    }
                ]
            )
        )

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

    def test_valid_krx_symbol_real_import_reaches_service(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """유효 KRX symbol은 검증 통과 후 ``_import()`` (asyncio.run) 도달."""
        json_file = tmp_path / "ok_krx.json"
        json_file.write_text(
            json.dumps([{"symbol": "005930", "exchange": "KRX", "name": "삼성전자"}])
        )

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = 1
            result = runner.invoke(
                cli,
                ["instrument", "import", str(json_file)],
            )

        assert result.exit_code == 0, result.stderr
        mock_run.assert_called_once()

    def test_valid_krx_symbol_csv_dry_run_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """CSV 경로(symbol 항상 str)도 유효 6자리 → exit 0 회귀 보존."""
        csv_file = tmp_path / "ok_krx.csv"
        csv_file.write_text("symbol,exchange,name\n005930,KRX,삼성전자\n")

        result = runner.invoke(
            cli,
            ["instrument", "import", str(csv_file), "--dry-run"],
        )

        assert result.exit_code == 0, result.stderr
        assert "005930" in result.stdout


# ── 9. 비-KRX canonical은 KRX symbol-shape 미적용 (#1611) ──


class TestNonKrxSymbolShapeNotApplied:
    """비-KRX canonical(NYSE/NASDAQ/AMEX/TEST)은 symbol-shape 미적용.

    core.md ``### KRX symbol shape`` — exchange == KRX 한정. 비-KRX
    symbol format 정의는 1.0 비목표이므로 ``AAPL`` 같은 비6자리
    alphabetic symbol도 canonical exchange면 거부하지 않는다.
    """

    def test_non_krx_alpha_symbol_dry_run_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "nyse.json"
        json_file.write_text(
            json.dumps([{"symbol": "AAPL", "exchange": "NYSE", "name": "Apple Inc."}])
        )

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

    def test_non_krx_symbol_with_valid_krx_row_mixed_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """비-KRX 비6자리 + 유효 KRX 6자리 혼합 → 전부 통과 (exit 0)."""
        json_file = tmp_path / "mixed_ex.json"
        json_file.write_text(
            json.dumps(
                [
                    {"symbol": "005930", "exchange": "KRX"},
                    {"symbol": "AAPL", "exchange": "NASDAQ"},
                ]
            )
        )

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
        assert payload["total"] == 2


# ── 10. exchange invalid 검증 회귀 비파손 (#1577 보존, #1611) ──


class TestExchangeInvalidRegressionUnbroken:
    """KRX symbol 검증 추가 후에도 기존 exchange invalid 회귀 보존.

    exchange 검증이 KRX symbol 검증보다 먼저 차단하므로 invalid
    exchange row는 여전히 ``INSTRUMENT_INVALID_EXCHANGE`` 로 거부된다.
    """

    def test_invalid_exchange_still_invalid_exchange_code(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "inv_ex.json"
        json_file.write_text(
            json.dumps(
                [{"symbol": "ABCDEF", "exchange": "ORACLE_INVALID", "name": "x"}]
            )
        )

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
        # exchange 검증이 먼저 차단 — symbol 검증 코드가 아님.
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"
        assert payload["code"] != "INSTRUMENT_INVALID_SYMBOL"
