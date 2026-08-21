"""ante feed status CLI 커맨드 테스트."""

from __future__ import annotations

import json
from pathlib import Path
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
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx: object) -> None:
                import click

                ctx = click.get_current_context()
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def data_path(tmp_path: Path) -> str:
    """임시 데이터 디렉토리 경로 (문자열)."""
    return str(tmp_path / "data")


def _init_feed(data_path: str) -> None:
    """피드 디렉토리를 초기화한다."""
    from ante.feed.config import FeedConfig

    cfg = FeedConfig(data_path)
    cfg.init()


def _invoke_status(runner: CliRunner, data_path: str, fmt: str = "text") -> object:
    """feed status 커맨드를 실행한다."""
    args = ["feed", "status", "--data-path", data_path]
    if fmt == "json":
        args = ["--format", "json"] + args
    return runner.invoke(cli, args, catch_exceptions=False)


class TestFeedStatusNotInitialized:
    """초기화되지 않은 상태에서의 feed status."""

    def test_shows_not_initialized(self, runner: CliRunner, data_path: str) -> None:
        result = _invoke_status(runner, data_path)
        assert "초기화되지 않았습니다" in result.output

    def test_shows_init_command(self, runner: CliRunner, data_path: str) -> None:
        result = _invoke_status(runner, data_path)
        assert "ante feed init" in result.output

    def test_json_not_initialized(self, runner: CliRunner, data_path: str) -> None:
        result = _invoke_status(runner, data_path, fmt="json")
        data = json.loads(result.output)
        assert data["initialized"] is False


class TestFeedStatusInitialized:
    """초기화된 상태에서의 feed status (체크포인트/리포트 없음)."""

    def test_shows_empty_checkpoints(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path)
        assert "체크포인트 없음" in result.output

    def test_shows_empty_reports(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path)
        assert "리포트 없음" in result.output

    def test_shows_api_keys_section(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path)
        assert "API Keys" in result.output
        assert "ANTE_DATAGOKR_API_KEY" in result.output
        assert "ANTE_DART_API_KEY" in result.output

    def test_shows_unset_api_keys(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path)
        assert "미설정" in result.output

    def test_exit_code_zero(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path)
        assert result.exit_code == 0


class TestFeedStatusWithCheckpoints:
    """체크포인트가 있는 상태에서의 feed status."""

    def test_shows_checkpoint_info(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        _create_checkpoint(data_path, "data_go_kr", "ohlcv", "2026-03-15")
        result = _invoke_status(runner, data_path)
        assert "data_go_kr" in result.output
        assert "ohlcv" in result.output
        assert "2026-03-15" in result.output

    def test_shows_multiple_checkpoints(
        self, runner: CliRunner, data_path: str
    ) -> None:
        _init_feed(data_path)
        _create_checkpoint(data_path, "data_go_kr", "ohlcv", "2026-03-15")
        _create_checkpoint(data_path, "dart", "fundamental", "2026-03-10")
        result = _invoke_status(runner, data_path)
        assert "data_go_kr" in result.output
        assert "dart" in result.output

    def test_json_contains_checkpoints(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        _create_checkpoint(data_path, "data_go_kr", "ohlcv", "2026-03-15")
        result = _invoke_status(runner, data_path, fmt="json")
        data = json.loads(result.output)
        assert data["initialized"] is True
        assert len(data["checkpoints"]) == 1
        assert data["checkpoints"][0]["source"] == "data_go_kr"
        assert data["checkpoints"][0]["last_date"] == "2026-03-15"


class TestFeedStatusWithReport:
    """리포트가 있는 상태에서의 feed status."""

    def test_shows_report_summary(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        _create_report(data_path, mode="daily", target_date="2026-03-16")
        result = _invoke_status(runner, data_path)
        assert "daily" in result.output
        assert "2026-03-16" in result.output
        assert "success" in result.output

    def test_shows_report_failure_count(
        self, runner: CliRunner, data_path: str
    ) -> None:
        _init_feed(data_path)
        _create_report(
            data_path, mode="daily", target_date="2026-03-16", failed=2, warnings=3
        )
        result = _invoke_status(runner, data_path)
        assert "2 failed" in result.output
        assert "3 warnings" in result.output

    def test_json_contains_report(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        _create_report(data_path, mode="daily", target_date="2026-03-16")
        result = _invoke_status(runner, data_path, fmt="json")
        data = json.loads(result.output)
        assert data["latest_report"] is not None
        assert data["latest_report"]["mode"] == "daily"
        assert data["latest_report"]["summary"]["symbols_success"] == 2485

    def test_shows_total_failures_with_non_symbol_failure(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """날짜/소스 단위 실패가 텍스트의 total failures로 표면화된다(#2117).

        symbols_failed=0이어도 failures_total>0이면 '0 failed'와 별개로
        'N total failures'가 표시되어 성공처럼 보이는 것을 막는다.
        """
        _init_feed(data_path)
        _create_report(
            data_path,
            mode="daily",
            target_date="2026-03-16",
            success=10,
            failed=0,
            extra_failures=[
                {"date": "2026-03-16", "source": "data_go_kr", "reason": "HTTP 500"},
                {"source": "dart", "reason": "연결 실패"},
            ],
        )
        result = _invoke_status(runner, data_path)

        assert "0 failed" in result.output
        assert "2 total failures" in result.output

    def test_total_failures_falls_back_to_failures_len(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """구버전 리포트(summary.failures_total 없음)는 failures 길이로 폴백한다."""
        _init_feed(data_path)
        _create_report(
            data_path,
            mode="daily",
            target_date="2026-03-16",
            success=10,
            failed=0,
            extra_failures=[
                {"date": "2026-03-16", "source": "data_go_kr", "reason": "HTTP 500"},
            ],
            include_failures_total=False,
        )
        result = _invoke_status(runner, data_path)

        assert "1 total failures" in result.output

    def test_warnings_count_uses_total_not_sample_length(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """절단 리포트에서도 총 경고 건수를 보고한다(#2414).

        warnings 배열은 type 버킷별로 유계 절단되므로 len()으로 세면
        99,691건이 "3"으로 조용히 축소 보고된다.
        """
        _init_feed(data_path)
        _create_report(
            data_path,
            mode="backfill",
            target_date="2026-03-16",
            warnings=3,
            warnings_total=99691,
        )
        result = _invoke_status(runner, data_path)

        assert "99691 warnings" in result.output
        assert "3 warnings" not in result.output

    def test_warnings_count_falls_back_to_warnings_len(
        self, runner: CliRunner, data_path: str
    ) -> None:
        """구버전 리포트(summary.warnings_total 없음)는 warnings 길이로 폴백한다."""
        _init_feed(data_path)
        _create_report(
            data_path,
            mode="daily",
            target_date="2026-03-16",
            warnings=3,
            include_warnings_total=False,
        )
        result = _invoke_status(runner, data_path)

        assert "3 warnings" in result.output


class TestFeedStatusApiKeys:
    """API 키 상태 표시."""

    def test_shows_set_api_key(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        from ante.feed.config import FeedConfig

        cfg = FeedConfig(data_path)
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "test_key_value_123")
        result = _invoke_status(runner, data_path)
        assert "설정됨" in result.output

    def test_json_api_keys(self, runner: CliRunner, data_path: str) -> None:
        _init_feed(data_path)
        result = _invoke_status(runner, data_path, fmt="json")
        data = json.loads(result.output)
        assert len(data["api_keys"]) == 2
        for key_info in data["api_keys"]:
            assert "key" in key_info
            assert "set" in key_info


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


def _create_checkpoint(
    data_path: str, source: str, data_type: str, last_date: str
) -> None:
    """테스트용 체크포인트 파일을 생성한다."""
    cp_dir = Path(data_path) / ".feed" / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_file = cp_dir / f"{source}_{data_type}.json"
    cp_file.write_text(
        json.dumps(
            {
                "source": source,
                "data_type": data_type,
                "last_date": last_date,
                "updated_at": "2026-03-17T01:23:45Z",
            }
        ),
        encoding="utf-8",
    )


def _create_report(
    data_path: str,
    *,
    mode: str = "daily",
    target_date: str = "2026-03-16",
    success: int = 2485,
    failed: int = 0,
    warnings: int = 0,
    extra_failures: list[dict] | None = None,
    include_failures_total: bool = True,
    include_warnings_total: bool = True,
    warnings_total: int | None = None,
) -> None:
    """테스트용 리포트 파일을 생성한다.

    Args:
        extra_failures: 종목에 귀속되지 않는 날짜/소스 단위 실패(#2117 검증용).
        include_failures_total: summary에 failures_total을 넣을지(구버전 폴백 검증용).
        include_warnings_total: summary에 warnings_total을 넣을지(구버전 폴백 검증용).
        warnings_total: summary.warnings_total 값. None이면 warnings 배열 길이.
            배열보다 큰 값을 주면 절단 리포트(#2414)를 모사한다.
    """
    reports_dir = Path(data_path) / ".feed" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = [
        {"symbol": f"00{i:04d}", "reason": "test"} for i in range(failed)
    ]
    failures.extend(extra_failures or [])
    summary: dict = {
        "symbols_total": success + failed,
        "symbols_success": success,
        "symbols_failed": failed,
        "rows_written": success,
        "data_types": ["ohlcv", "fundamental"],
    }
    if include_failures_total:
        summary["failures_total"] = len(failures)
    if include_warnings_total:
        summary["warnings_total"] = (
            warnings if warnings_total is None else warnings_total
        )
    report = {
        "mode": mode,
        "started_at": f"{target_date}T16:00:12Z",
        "finished_at": f"{target_date}T16:05:34Z",
        "duration_seconds": 322,
        "target_date": target_date,
        "summary": summary,
        "failures": failures,
        "warnings": [
            {"symbol": f"00{i:04d}", "message": "test warning"} for i in range(warnings)
        ],
        "config_errors": [],
    }
    filename = f"{target_date}-{mode}.json"
    (reports_dir / filename).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
