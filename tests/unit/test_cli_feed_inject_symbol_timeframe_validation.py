"""CLI feed inject --symbol/--timeframe 저장 전 검증 테스트 (#1606).

CLI 경계 단일 검증 (#1603 backtest run / #1605 data validate 블록 1:1
동형 미러):
- invalid timeframe → exit 1 + `FEED_INJECT_INVALID_TIMEFRAME`.
- invalid KRX symbol(비-6자리) → exit 1 + `FEED_INJECT_INVALID_SYMBOL`.
- 유효 `--symbol 005930 --timeframe 1d` → 기존 inject 동작 유지.
- invalid 입력 → ParquetStore/FeedInjector/inject_csv 미도달 **그리고**
  tmp data-path 내 parquet 파일/디렉터리 미생성 (#1592 oracle 증상:
  invalid 입력이 비표준 dataset 생성, 둘 다 확인).
- JSON/text 양 포맷 error code/메시지 회귀.
- `@require_auth`/`@require_scope("data:write")` 데코레이터 정상 동작.

검증 precedence: ① timeframe → ② KRX symbol shape
(이슈 #1606 Implementation Plan 고정 — #1603/#1605 동형).

`feed inject`는 --exchange 옵션 없는 KRX-domain이므로 symbol은
is_krx_symbol을 직접 적용한다 (core.md `### KRX symbol shape` 정합,
비-KRX 경로 부재). `--symbol`은 required이므로 None 케이스가 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
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

# 최소 OHLCV CSV — click.Path(exists=True) 충족용. 검증은 이 파일을
# 읽기 전에 일어나므로 내용 자체는 invalid 케이스에서 사용되지 않는다.
_CSV_CONTENT = "timestamp,open,high,low,close,volume\n2026-01-02,100,110,90,105,1000\n"


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


def _write_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "ohlcv.csv"
    csv.write_text(_CSV_CONTENT, encoding="utf-8")
    return csv


def _inject_args(csv: Path, data_path: Path, *extra: str) -> list[str]:
    return [
        "feed",
        "inject",
        str(csv),
        "--data-path",
        str(data_path),
        *extra,
    ]


def _assert_no_parquet_artifact(data_path: Path) -> None:
    """tmp data-path 내 parquet 파일/디렉터리가 생성되지 않았는지 확인.

    Codex 권고: store/injector mock 미도달(미도달 assert)뿐 아니라
    실제 data-path 산출물 부재도 함께 검증한다.
    """
    if not data_path.exists():
        return
    leaked = sorted(
        str(p) for p in data_path.rglob("*") if p.suffix == ".parquet" or p.is_dir()
    )
    assert leaked == [], f"invalid 입력인데 parquet 산출물 생성됨: {leaked}"


class TestFeedInjectTimeframeValidation:
    """feed inject --timeframe canonical 검증 (CLI 경계 단일 지점)."""

    def test_invalid_timeframe_text_mode_exit1_message_only(self, tmp_path):
        """비-canonical timeframe: text 모드 exit 1 + 메시지만(code 미출력)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            _inject_args(
                csv,
                data_path,
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
        assert "FEED_INJECT_INVALID_TIMEFRAME" not in result.output
        _assert_no_parquet_artifact(data_path)

    def test_invalid_timeframe_json_mode_exit1_with_code(self, tmp_path):
        """비-canonical timeframe: --format json exit 1 + 구조화 payload."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_inject_args(
                    csv,
                    data_path,
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
        assert payload["code"] == "FEED_INJECT_INVALID_TIMEFRAME"
        _assert_no_parquet_artifact(data_path)

    def test_invalid_timeframe_does_not_reach_store_or_injector(self, tmp_path):
        """invalid timeframe → ParquetStore/FeedInjector 미도달 + parquet 미생성."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with (
            patch("ante.data.store.ParquetStore") as mock_store,
            patch("ante.feed.injector.FeedInjector") as mock_injector,
        ):
            result = runner.invoke(
                cli,
                _inject_args(
                    csv,
                    data_path,
                    "--symbol",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            )

        assert result.exit_code == 1
        mock_store.assert_not_called()
        mock_injector.assert_not_called()
        _assert_no_parquet_artifact(data_path)

    def test_valid_canonical_timeframe_not_rejected(self, tmp_path):
        """canonical timeframe(1d)은 invalid-timeframe 거부 아님 (정상 경로)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with patch("ante.feed.injector.FeedInjector") as mock_injector:
            mock_injector.return_value.inject_csv.return_value = 1
            result = runner.invoke(
                cli,
                _inject_args(csv, data_path, "--symbol", "005930", "--timeframe", "1d"),
            )

        assert result.exit_code == 0
        mock_injector.return_value.inject_csv.assert_called_once()
        assert "유효하지 않은 타임프레임" not in result.output


class TestFeedInjectSymbolValidation:
    """feed inject --symbol KRX shape 검증."""

    def test_krx_non_six_digit_symbol_text_mode_exit1(self, tmp_path):
        """비-6자리 symbol: text 모드 exit 1 + 메시지만(code 미출력)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            _inject_args(csv, data_path, "--symbol", "ABCDEF", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output
        assert "ABCDEF" in result.output
        assert "FEED_INJECT_INVALID_SYMBOL" not in result.output
        _assert_no_parquet_artifact(data_path)

    def test_krx_non_six_digit_symbol_json_mode_with_code(self, tmp_path):
        """비-6자리 symbol: JSON exit 1 + 구조화 code."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_inject_args(
                    csv, data_path, "--symbol", "ABCDEF", "--timeframe", "1d"
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "FEED_INJECT_INVALID_SYMBOL"
        _assert_no_parquet_artifact(data_path)

    def test_invalid_symbol_does_not_reach_store_or_injector(self, tmp_path):
        """invalid symbol → ParquetStore/FeedInjector 미도달 + parquet 미생성."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with (
            patch("ante.data.store.ParquetStore") as mock_store,
            patch("ante.feed.injector.FeedInjector") as mock_injector,
        ):
            result = runner.invoke(
                cli,
                _inject_args(csv, data_path, "--symbol", "ABCDEF", "--timeframe", "1d"),
            )

        assert result.exit_code == 1
        mock_store.assert_not_called()
        mock_injector.assert_not_called()
        _assert_no_parquet_artifact(data_path)

    def test_valid_krx_symbol_not_rejected(self, tmp_path):
        """유효한 KRX 6자리 symbol(005930): 거부 아님 (정상 진행)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with patch("ante.feed.injector.FeedInjector") as mock_injector:
            mock_injector.return_value.inject_csv.return_value = 1
            result = runner.invoke(
                cli,
                _inject_args(csv, data_path, "--symbol", "005930", "--timeframe", "1d"),
            )

        assert result.exit_code == 0
        mock_injector.return_value.inject_csv.assert_called_once()
        assert "유효하지 않은 종목 코드" not in result.output


class TestFeedInjectValidationPrecedence:
    """검증 precedence: ① timeframe → ② KRX symbol shape (#1603/#1605 동형)."""

    def test_timeframe_checked_before_symbol(self, tmp_path):
        """timeframe·symbol 동시 invalid → timeframe error 우선 (① 먼저)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_inject_args(
                    csv,
                    data_path,
                    "--symbol",
                    "ABCDEF",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["code"] == "FEED_INJECT_INVALID_TIMEFRAME"
        _assert_no_parquet_artifact(data_path)


class TestFeedInjectWrittenPath:
    """#2050: text 출력 'Written to' 경로가 실제 ParquetStore 레이아웃과 정합.

    하드코딩 `ohlcv/krx/{tf}/{symbol}/`가 아니라
    `store.resolve_path(symbol, tf, exchange="KRX")`(= `ohlcv/{tf}/KRX/{symbol}/`)
    를 출력한다(drift 방지).
    """

    def test_written_path_matches_store_resolve_path(self, tmp_path):
        """text 모드 'Written to' 경로 == store.resolve_path base 상대경로."""
        from ante.data.store import ParquetStore

        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with patch("ante.feed.injector.FeedInjector") as mock_injector:
            mock_injector.return_value.inject_csv.return_value = 3
            result = runner.invoke(
                cli,
                _inject_args(csv, data_path, "--symbol", "005930", "--timeframe", "1d"),
            )

        assert result.exit_code == 0, result.output
        expected = ParquetStore(base_path=data_path).resolve_path(
            "005930", "1d", exchange="KRX"
        )
        expected_rel = expected.relative_to(data_path)
        assert f"Written to {expected_rel}/" in result.output
        # 실제 레이아웃 정합: ohlcv/{tf}/{exchange}/{symbol}/
        assert "Written to ohlcv/1d/KRX/005930/" in result.output
        # 기존 하드코딩 잘못된 경로(ohlcv/krx/{tf}/{symbol}/)는 더 이상 출력 안 됨.
        assert "ohlcv/krx/1d/005930/" not in result.output

    def test_written_path_not_emitted_in_json_mode(self, tmp_path):
        """JSON 모드는 'Written to' 텍스트 라인을 출력하지 않는다(회귀 락)."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        with patch("ante.feed.injector.FeedInjector") as mock_injector:
            mock_injector.return_value.inject_csv.return_value = 3
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    *_inject_args(
                        csv, data_path, "--symbol", "005930", "--timeframe", "1d"
                    ),
                ],
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["rows"] == 3
        assert "Written to" not in result.stdout


class TestFeedInjectAuthDecorators:
    """@require_auth / @require_scope("data:write") 데코레이터 정상 동작."""

    def test_auth_mock_allows_validation_path(self, tmp_path):
        """auth mock 주입 시 require_auth/require_scope 통과 → 검증 로직 도달."""
        runner = _make_runner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        # 인증이 통과해야만 ingress 검증(invalid timeframe)까지 도달한다.
        result = runner.invoke(
            cli,
            _inject_args(
                csv,
                data_path,
                "--symbol",
                "005930",
                "--timeframe",
                "oracle-invalid-timeframe",
            ),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 타임프레임" in result.output

    def test_unauthenticated_does_not_reach_validation(self, tmp_path):
        """auth mock 미주입 시 require_auth 차단 → exit 비정상, 검증 미도달."""
        # 일반 CliRunner (auth mock 없음) — authenticate_member 미패치.
        runner = CliRunner()
        csv = _write_csv(tmp_path)
        data_path = tmp_path / "data"

        result = runner.invoke(
            cli,
            _inject_args(
                csv,
                data_path,
                "--symbol",
                "005930",
                "--timeframe",
                "oracle-invalid-timeframe",
            ),
        )
        # 인증 실패로 비정상 종료하며 ingress 검증 메시지에 도달하지 않는다.
        assert result.exit_code != 0
        assert "유효하지 않은 타임프레임" not in result.output
