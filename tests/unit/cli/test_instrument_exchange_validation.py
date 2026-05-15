"""``instrument`` CLI exchange 검증 회귀 테스트 (#1577).

이슈 #1577 (oracle A7 ``cli_instrument_invalid_exchange_accepted``):
``instrument list --exchange ORACLE_INVALID_EXCHANGE`` 및 invalid exchange
row를 포함한 ``instrument import --dry-run``이 exit 0으로 성공 처리되던
ingress drift를 닫는다. 3 ingress(list/sync/import)가 동일하게
``ante.core.exchange`` canonical SSOT를 경유한다.

4-axis 검증 (이슈 본문 Implementation Plan):
- Axis 1 — ``list``/``sync`` ``--exchange`` 비-canonical → exit 1 +
  ``INSTRUMENT_INVALID_EXCHANGE``.
- Axis 2 — ``import`` 행별 비-canonical exchange → ``import``/
  ``--dry-run`` 모두 exit 1 + ``INSTRUMENT_INVALID_EXCHANGE``.
- Axis 3 — ``sync`` canonical이나 KIS sync source(KRX) 미지원
  (``CANONICAL_EXCHANGES - {"KRX"}`` = NYSE/NASDAQ/AMEX/TEST) →
  exit 1 + ``INSTRUMENT_SYNC_SOURCE_UNSUPPORTED`` (invalid 아님 —
  축 A/B 불변식).
- 회귀 보존: ``sync --exchange KRX`` source 통과(KIS mock), 유효 입력
  ``import --dry-run`` exit 0.

기존 ``tests/unit/test_cli_instrument_import_exit.py`` 패턴
(``CliRunner(mix_stderr=False)``, text/JSON 양모드) 확장.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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
    """인증을 mock으로 우회한 CliRunner (stderr/stdout 분리)."""
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


# ── Axis 1: instrument list --exchange (비-canonical) → exit 1 ──


class TestListInvalidExchange:
    """``instrument list --exchange ORACLE_INVALID_EXCHANGE`` → exit 1."""

    def test_invalid_exchange_exits_nonzero_text(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "instrument",
                "list",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )

        assert result.exit_code == 1, result.stderr
        assert "유효하지 않은 거래소" in result.stderr

    def test_invalid_exchange_exits_nonzero_json_envelope(
        self, runner: CliRunner
    ) -> None:
        """oracle probe 시그니처와 정확히 동일한 경로: ``--format json``."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "instrument",
                "list",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"

    def test_wildcard_rejected_as_invalid(self, runner: CliRunner) -> None:
        """``*`` 는 StrategyMeta 전용 — instrument 표면에서 비-canonical."""
        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "list", "--exchange", "*"],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"


# ── Axis 1: instrument sync --exchange (비-canonical) → exit 1 ──


class TestSyncInvalidExchange:
    """``instrument sync --exchange ORACLE_INVALID_EXCHANGE`` → exit 1."""

    def test_invalid_exchange_exits_nonzero_text(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            [
                "instrument",
                "sync",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )

        assert result.exit_code == 1, result.stderr
        assert "유효하지 않은 거래소" in result.stderr

    def test_invalid_exchange_exits_nonzero_json_envelope(
        self, runner: CliRunner
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "instrument",
                "sync",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"


# ── Axis 3: instrument sync canonical-but-source-unsupported → exit 1 ──


class TestSyncSourceUnsupported:
    """canonical이나 KIS sync source(KRX) 미지원 → SOURCE_UNSUPPORTED.

    ``CANONICAL_EXCHANGES - {"KRX"}`` = NYSE/NASDAQ/AMEX/TEST. invalid가
    아니라 별도 코드로 거부 (축 A/B 불변식: canonical을 invalid로
    거부하지 않음).
    """

    @pytest.mark.parametrize("exchange", ["NYSE", "NASDAQ", "AMEX", "TEST"])
    def test_canonical_unsupported_exits_with_source_code(
        self, runner: CliRunner, exchange: str
    ) -> None:
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "instrument",
                "sync",
                "--exchange",
                exchange,
            ],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED"
        # 축 A/B 불변식: invalid가 아니라 source-unsupported로 분류.
        assert payload["code"] != "INSTRUMENT_INVALID_EXCHANGE"

    def test_nyse_text_mode_message(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["instrument", "sync", "--exchange", "NYSE"],
        )

        assert result.exit_code == 1, result.stderr
        assert "invalid exchange 아님" in result.stderr


# ── 회귀 보존: sync --exchange KRX → source 검증 통과 (KIS mock) ──


class TestSyncKrxSourcePasses:
    """``sync --exchange KRX``는 canonical+source 검증 통과 (기존 동작 보존).

    KIS 호출은 mock — exchange 검증이 KISAdapter 호출 전에 차단하지
    않음을 확인한다 (broker 설정 부재 시 기존 ``브로커 설정이 없습니다``
    경로로 진입).
    """

    def test_krx_passes_exchange_validation(self, runner: CliRunner, tmp_path) -> None:
        # broker 설정 부재 → 기존 "브로커 설정이 없습니다" 경로.
        # exchange 검증을 통과해야 이 경로에 도달한다 (검증이 먼저
        # 차단하면 INSTRUMENT_INVALID/SOURCE 에러가 났을 것).
        result = runner.invoke(
            cli,
            [
                "instrument",
                "sync",
                "--exchange",
                "KRX",
                "--db-path",
                str(tmp_path / "krx.db"),
            ],
        )

        assert result.exit_code == 1, result.stderr
        # exchange 검증이 아닌 broker 설정 부재로 실패해야 한다.
        assert "유효하지 않은 거래소" not in result.stderr
        assert "sync source" not in result.stderr
        assert "브로커 설정이 없습니다" in result.stderr

    def test_krx_reaches_adapter_when_broker_configured(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """broker 설정이 있으면 KRX는 검증 통과 후 KISAdapter 호출 도달."""
        fake_adapter = AsyncMock()
        fake_adapter.connect = AsyncMock()
        fake_adapter.disconnect = AsyncMock()
        fake_adapter.get_instruments = AsyncMock(
            return_value=[
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "name_en": "Samsung",
                    "instrument_type": "stock",
                    "listed": True,
                }
            ]
        )

        with (
            patch(
                "ante.broker.kis.KISAdapter",
                return_value=fake_adapter,
            ),
            patch(
                "ante.config.Config.load",
                return_value={"broker": {"app_key": "k", "app_secret": "s"}},
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "instrument",
                    "sync",
                    "--exchange",
                    "KRX",
                    "--db-path",
                    str(tmp_path / "krx2.db"),
                ],
            )

        assert result.exit_code == 0, result.stdout
        fake_adapter.get_instruments.assert_awaited_once()
        payload = json.loads(result.stdout)
        assert payload["sync_result"]["total"] == 1


# ── Axis 2: instrument import 행별 invalid exchange → exit 1 ──


class TestImportInvalidExchangeRow:
    """invalid exchange row를 포함한 ``import`` → exit 1 (dry-run 포함)."""

    def test_invalid_row_import_exits_nonzero_text(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "inv.json"
        json_file.write_text(
            json.dumps([{"symbol": "X", "exchange": "ORACLE_INVALID_EXCHANGE"}])
        )

        result = runner.invoke(
            cli,
            ["instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stderr
        assert "유효하지 않은 거래소" in result.stderr

    def test_invalid_row_import_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        json_file = tmp_path / "inv.json"
        json_file.write_text(
            json.dumps([{"symbol": "X", "exchange": "ORACLE_INVALID_EXCHANGE"}])
        )

        result = runner.invoke(
            cli,
            ["--format", "json", "instrument", "import", str(json_file)],
        )

        assert result.exit_code == 1, result.stdout
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"

    def test_invalid_row_dry_run_exits_nonzero_json_envelope(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """oracle probe 재현: ``import --dry-run``도 row 검증 후 거부."""
        json_file = tmp_path / "inv.json"
        json_file.write_text(
            json.dumps([{"symbol": "X", "exchange": "ORACLE_INVALID_EXCHANGE"}])
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
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"

    def test_invalid_row_among_valid_rows_rejected(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """유효 행 사이에 섞인 비-canonical 행도 식별·거부."""
        json_file = tmp_path / "mixed.json"
        json_file.write_text(
            json.dumps(
                [
                    {"symbol": "005930", "exchange": "KRX"},
                    {"symbol": "BAD", "exchange": "ORACLE_INVALID_EXCHANGE"},
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
        assert payload["code"] == "INSTRUMENT_INVALID_EXCHANGE"
        assert "BAD" in payload["message"]


# ── 회귀 보존: 유효 입력 import --dry-run → exit 0 ──


class TestValidImportDryRunRegression:
    """유효 canonical exchange 입력의 ``--dry-run``은 exit 0 회귀 보존."""

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

    def test_multi_canonical_exchanges_dry_run_exits_zero(
        self, runner: CliRunner, tmp_path
    ) -> None:
        """KRX 외 canonical(NYSE 등)도 import 행 검증은 통과 (저장 표면은
        sync source 제약과 무관 — import는 파일 데이터 적재)."""
        json_file = tmp_path / "multi.json"
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
