"""``ante report view`` DB 에러 → ``REPORT_ERROR`` envelope 회귀 (#1985).

이슈 #1985: ``report view`` 의 ``result = asyncio.run(_view())`` 가 try/except
로 감싸지지 않아, DB 연결/조회 실패 시 예외가 그대로 전파되어 Python
traceback 이 노출되던 결함을 닫는다.

형제 ``report list`` (report.py L255-260) 은 동일 read 경로를
``try: ... except Exception as e: fmt.error(str(e), code="REPORT_ERROR");
raise SystemExit(1) from e`` 로 처리하나 ``report view`` 만 누락되어 있었다.
본 모듈은 ``report list`` 와 동형으로 다음 invariant 를 lock 한다:

- R1: DB 연결/조회 예외 → ``REPORT_ERROR`` JSON envelope + exit 1, stdout/
  stderr 에 traceback 미노출 (핵심 repro).
- R2: 정상 DB + 미존재 report_id → ``REPORT_NOT_FOUND`` (DB 에러와 구분되는
  별도 envelope; ``REPORT_ERROR`` 가 아니다).
- R3: 존재하는 report → 정상 평면 detail dict 출력 (exit 0) 회귀 보존.

``report view`` 는 ``_view()`` 내부에서 ``ante.core.database.Database`` /
``ante.report.ReportStore`` 를 함수 로컬 import 로 resolve 하므로 각 원본
모듈 속성을 patch 하면 결정적으로 분기를 탄다 (output_drift 테스트와 동형).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.report.models import ReportStatus, StrategyReport

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


@pytest.fixture(autouse=True)
def bypass_auth():
    """master member 로 인증 우회 (report 도메인 테스트 동형 패턴)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str], *, catch_exceptions: bool = True):
    """``ante report ...`` 를 실행하고 결과를 반환한다.

    ``catch_exceptions=True`` 가 기본 — 결함 회귀(예외 전파 → traceback)를
    CliRunner 가 capture 해 ``result.exc_info`` 로 노출하므로, 수정 후에는
    예외가 ``SystemExit`` 로 정규화되어 ``exc_info`` 가 비어야 한다.
    """
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=catch_exceptions)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다."""
    text = output.lstrip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    start_brace = text.find("{")
    start_bracket = text.find("[")
    candidates = [s for s in (start_brace, start_bracket) if s >= 0]
    assert candidates, f"JSON 시작 토큰을 찾을 수 없다: {output!r}"
    start = min(candidates)
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return obj


def _make_report(
    *,
    report_id: str = "rpt-1",
    strategy_name: str = "my_strategy",
    status: ReportStatus = ReportStatus.SUBMITTED,
) -> StrategyReport:
    """테스트용 ``StrategyReport`` factory (output_drift 테스트와 동형)."""
    return StrategyReport(
        report_id=report_id,
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        strategy_path="strategies/my_strategy.py",
        status=status,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=15.3,
        total_trades=42,
        sharpe_ratio=1.2,
        max_drawdown_pct=-8.5,
        win_rate=58.0,
        summary="테스트 전략",
        rationale="모멘텀",
        risks="없음",
    )


# ── R1: DB 에러 → REPORT_ERROR envelope (핵심 repro) ───────────────────────


class TestReportViewDbErrorEnvelope:
    """``report view`` DB 연결/조회 실패 → ``REPORT_ERROR`` + exit 1, no traceback.

    ``report list`` (report.py L255-260) 와 동형. 결함 시점에는
    ``result = asyncio.run(_view())`` 가 try/except 밖이라 예외가 전파되어
    Python traceback 이 노출됐다.
    """

    def test_db_connect_error_surfaces_report_error_json(self, tmp_path) -> None:
        """``Database.connect`` 가 raise → ``REPORT_ERROR`` JSON + exit 1."""
        with patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(side_effect=RuntimeError("db connect boom")),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "view",
                    "rpt-x",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )

        assert result.exit_code == 1, result.output
        # 핵심 회귀: 예외가 ``SystemExit`` 로 정규화되어 전파 traceback 이
        # 없어야 한다 (CliRunner 는 미처리 예외를 ``exc_info`` 로 노출).
        if result.exc_info is not None:
            exc_type = result.exc_info[0]
            assert exc_type is SystemExit, (
                f"DB 에러가 SystemExit 으로 정규화되지 않고 {exc_type!r} 전파 "
                f"(traceback 노출 회귀 #1985): {result.output!r}"
            )
        assert "Traceback" not in result.output, (
            f"출력에 traceback 노출 (#1985): {result.output!r}"
        )
        payload = _load_json_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "REPORT_ERROR"

    def test_get_error_surfaces_report_error_json(self, tmp_path) -> None:
        """``ReportStore.get`` 가 raise (조회 실패) → ``REPORT_ERROR`` + exit 1.

        DB 연결은 성공하나 조회 단계에서 실패하는 경로. ``_view()`` 내부
        try/finally 가 ``db.close()`` 만 보장하고 예외는 전파하므로 호출
        경계에서 ``REPORT_ERROR`` 로 변환되어야 한다.
        """
        with (
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
            patch("ante.report.ReportStore.initialize", new=AsyncMock()),
            patch(
                "ante.report.ReportStore.get",
                new=AsyncMock(side_effect=RuntimeError("query boom")),
            ),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "view",
                    "rpt-x",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )

        assert result.exit_code == 1, result.output
        if result.exc_info is not None:
            assert result.exc_info[0] is SystemExit, (
                f"조회 에러가 SystemExit 으로 정규화되지 않음 (#1985): "
                f"{result.output!r}"
            )
        assert "Traceback" not in result.output, (
            f"출력에 traceback 노출 (#1985): {result.output!r}"
        )
        payload = _load_json_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "REPORT_ERROR"

    def test_db_error_text_mode_exit_nonzero(self, tmp_path) -> None:
        """text 모드에서도 DB 에러 → exit 1 + ``Error:`` (envelope code 없음).

        ``report list`` 와 동일하게 text 모드는 ``fmt.error`` 가 stderr/stdout
        에 ``Error:`` 메시지만 내고 exit 1 로 종료한다.
        """
        runner = CliRunner(mix_stderr=False)
        with patch(
            "ante.cli.main.authenticate_member",
            side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
        ):
            with patch(
                "ante.core.database.Database.connect",
                new=AsyncMock(side_effect=RuntimeError("db connect boom")),
            ):
                from ante.cli.main import cli

                result = runner.invoke(
                    cli,
                    [
                        "report",
                        "view",
                        "rpt-x",
                        "--db-path",
                        str(tmp_path / "ante.db"),
                    ],
                    env={"ANTE_MEMBER_TOKEN": ""},
                )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        if result.exc_info is not None:
            assert result.exc_info[0] is SystemExit
        assert "Traceback" not in result.stderr, result.stderr
        assert "Traceback" not in result.stdout, result.stdout
        assert "Error:" in result.stderr, result.stderr


# ── R2: 미존재 report_id → REPORT_NOT_FOUND (DB 에러와 구분) ────────────────


class TestReportViewNotFoundUnchanged:
    """정상 DB + 미존재 report → ``REPORT_NOT_FOUND`` (``REPORT_ERROR`` 아님).

    DB 에러만 ``REPORT_ERROR`` 로 정규화하고, 미발견은 별도 envelope 으로
    유지함을 lock 한다 (#1985 비목표: NOT_FOUND 경로 보존).
    """

    def test_missing_report_surfaces_not_found_not_error(self, tmp_path) -> None:
        with (
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
            patch("ante.report.ReportStore.initialize", new=AsyncMock()),
            patch(
                "ante.report.ReportStore.get",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "view",
                    "missing-id",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )

        assert result.exit_code == 1, result.output
        payload = _load_json_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "REPORT_NOT_FOUND", (
            f"미발견은 REPORT_NOT_FOUND 여야 한다 (REPORT_ERROR 아님): {payload!r}"
        )
        assert "missing-id" in payload["message"]


# ── R3: 정상 조회 회귀 보존 ────────────────────────────────────────────────


class TestReportViewFoundUnchanged:
    """존재하는 report → 정상 평면 detail dict 출력 (exit 0)."""

    def test_found_report_outputs_detail(self, tmp_path) -> None:
        report = _make_report(report_id="rpt-view-1", strategy_name="strat-V")
        with (
            patch("ante.core.database.Database.connect", new=AsyncMock()),
            patch("ante.core.database.Database.close", new=AsyncMock()),
            patch("ante.report.ReportStore.initialize", new=AsyncMock()),
            patch(
                "ante.report.ReportStore.get",
                new=AsyncMock(return_value=report),
            ),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "report",
                    "view",
                    "rpt-view-1",
                    "--db-path",
                    str(tmp_path / "ante.db"),
                ]
            )

        assert result.exit_code == 0, result.output
        payload = _load_json_payload(result.output)
        assert payload["report_id"] == "rpt-view-1"
        assert payload["status"] == "submitted"
        assert payload["total_trades"] == 42
        assert "strategy" in payload
