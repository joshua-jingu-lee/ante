"""CLI data validate --symbol/--timeframe ingress 검증 테스트 (#1605).

CLI 경계 단일 검증 (#1603 backtest run 블록 1:1 동형 미러):
- invalid timeframe → exit 1 + `DATA_VALIDATE_INVALID_TIMEFRAME`.
- invalid KRX symbol(비-6자리) → exit 1 + `DATA_VALIDATE_INVALID_SYMBOL`.
- `--symbol` 미지정(symbol is None) → 기존 전체 validate 동작 유지
  (거부 안 함, ParquetStore.list_symbols 경유 정상 진행 경로).
- 유효 `--symbol 005930 --timeframe 1d` → 기존 동작 유지.
- invalid 입력 → ParquetStore/list_symbols/validate 미도달
  (`if not symbols:` exit-0 fake-success #1591 oracle 증상 미도달).
- JSON/text 양 포맷 error code/메시지 회귀.
- `@require_auth`/`@require_scope("data:read")` 데코레이터 정상 동작.

검증 precedence: ① timeframe → ② KRX symbol shape
(이슈 #1605 Implementation Plan 고정 — #1603 동형).

`data validate`는 --exchange 옵션 없는 KRX-domain local store 대상이므로
symbol은 is_krx_symbol을 직접 적용한다 (core.md `### KRX symbol shape`
정합, 비-KRX 경로 부재).
"""

from __future__ import annotations

import json
from unittest.mock import patch

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


def _make_runner():
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


def _validate_args(*extra):
    return ["data", "validate", *extra]


class TestDataValidateTimeframeValidation:
    """data validate --timeframe canonical 검증 (CLI 경계 단일 지점)."""

    def test_invalid_timeframe_text_mode_exit1_message_only(self):
        """비-canonical timeframe: text 모드 exit 1 + 메시지만(code 미출력)."""
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _validate_args(
                "--symbol",
                "005930",
                "--timeframe",
                "oracle-invalid-timeframe",
            ),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 타임프레임" in result.output
        assert "oracle-invalid-timeframe" in result.output
        # text 모드: OutputFormatter.error는 code를 출력하지 않는다.
        assert "DATA_VALIDATE_INVALID_TIMEFRAME" not in result.output

    def test_invalid_timeframe_json_mode_exit1_with_code(self):
        """비-canonical timeframe: --format json exit 1 + 구조화 payload."""
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_validate_args(
                    "--symbol",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "DATA_VALIDATE_INVALID_TIMEFRAME"

    def test_invalid_timeframe_does_not_reach_parquet_store(self):
        """invalid timeframe → ParquetStore 미도달 (fake-success exit-0 미도달)."""
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                _validate_args(
                    "--symbol",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            )

        assert result.exit_code == 1
        mock_store.assert_not_called()

    def test_valid_canonical_timeframe_not_rejected(self):
        """canonical timeframe(1d)은 invalid-timeframe 거부 아님."""
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.list_symbols.return_value = []
            result = runner.invoke(
                cli,
                _validate_args("--symbol", "005930", "--timeframe", "1d"),
            )

        mock_store.assert_called_once()
        assert "유효하지 않은 타임프레임" not in result.output


class TestDataValidateSymbolValidation:
    """data validate --symbol KRX shape 검증."""

    def test_krx_non_six_digit_symbol_text_mode_exit1(self):
        """비-6자리 symbol: text 모드 exit 1 + 메시지만(code 미출력)."""
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _validate_args("--symbol", "ABCDEF", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output
        assert "ABCDEF" in result.output
        assert "DATA_VALIDATE_INVALID_SYMBOL" not in result.output

    def test_krx_non_six_digit_symbol_json_mode_with_code(self):
        """비-6자리 symbol: JSON exit 1 + 구조화 code."""
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_validate_args("--symbol", "ABCDEF", "--timeframe", "1d"),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "DATA_VALIDATE_INVALID_SYMBOL"

    def test_invalid_symbol_does_not_reach_parquet_store(self):
        """invalid symbol → ParquetStore 미도달 (fake-success exit-0 미도달)."""
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                _validate_args("--symbol", "ABCDEF", "--timeframe", "1d"),
            )

        assert result.exit_code == 1
        mock_store.assert_not_called()

    def test_valid_krx_symbol_not_rejected(self):
        """유효한 KRX 6자리 symbol(005930): 거부 아님 (정상 진행)."""
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.list_symbols.return_value = []
            result = runner.invoke(
                cli,
                _validate_args("--symbol", "005930", "--timeframe", "1d"),
            )

        mock_store.assert_called_once()
        assert "유효하지 않은 종목 코드" not in result.output


class TestDataValidateOmittedSymbolScope:
    """omitted --symbol 경계 — 기존 전체 validate 동작 보존."""

    def test_omitted_symbol_passes_validate_all(self):
        """--symbol 미지정(None): 기존 전체 validate 동작 유지 (거부 안 함).

        symbol is None → KRX shape 검증 미진입, store.list_symbols(timeframe)
        경유 전체 validate 정상 진행 경로.
        """
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            instance = mock_store.return_value
            instance.list_symbols.return_value = []
            result = runner.invoke(
                cli,
                _validate_args("--timeframe", "1d"),
            )

        mock_store.assert_called_once()
        instance.list_symbols.assert_called_once_with("1d")
        assert "유효하지 않은 종목 코드" not in result.output
        assert "유효하지 않은 타임프레임" not in result.output

    def test_omitted_symbol_invalid_timeframe_still_rejected(self):
        """--symbol 미지정이라도 invalid timeframe(①)은 거부 (symbol 무관 경계)."""
        runner = _make_runner()

        with patch("ante.data.store.ParquetStore") as mock_store:
            result = runner.invoke(
                cli,
                _validate_args("--timeframe", "oracle-invalid-timeframe"),
            )

        assert result.exit_code == 1
        assert "유효하지 않은 타임프레임" in result.output
        mock_store.assert_not_called()


class TestDataValidateValidationPrecedence:
    """검증 precedence: ① timeframe → ② KRX symbol shape (#1603 동형)."""

    def test_timeframe_checked_before_symbol(self):
        """timeframe·symbol 동시 invalid → timeframe error 우선 (① 먼저)."""
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_validate_args(
                    "--symbol",
                    "ABCDEF",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["code"] == "DATA_VALIDATE_INVALID_TIMEFRAME"


class TestDataValidateAuthDecorators:
    """@require_auth / @require_scope("data:read") 데코레이터 정상 동작."""

    def test_auth_mock_allows_validation_path(self):
        """auth mock 주입 시 require_auth/require_scope 통과 → 검증 로직 도달."""
        runner = _make_runner()

        # 인증이 통과해야만 ingress 검증(invalid timeframe)까지 도달한다.
        result = runner.invoke(
            cli,
            _validate_args("--timeframe", "oracle-invalid-timeframe"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 타임프레임" in result.output

    def test_unauthenticated_does_not_reach_validation(self):
        """auth mock 미주입 시 require_auth 차단 → exit 비정상, 검증 미도달."""
        # 일반 CliRunner (auth mock 없음) — authenticate_member 미패치.
        runner = CliRunner()
        result = runner.invoke(
            cli,
            _validate_args("--timeframe", "oracle-invalid-timeframe"),
        )
        # 인증 실패로 비정상 종료하며 ingress 검증 메시지에 도달하지 않는다.
        assert result.exit_code != 0
        assert "유효하지 않은 타임프레임" not in result.output
