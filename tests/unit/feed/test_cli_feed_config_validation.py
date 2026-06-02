"""feed 커맨드 공통 config helper 테스트 (#2037 guard 타입 검증 + #2038 log_level).

feed run backfill / feed run daily / feed start 진입에서 호출하는
``_validate_and_apply_feed_config`` 의 동작을 검증한다.

- #2038: ``[general].log_level`` 을 ``ante.feed`` 패키지 로거에 적용. 유효
  레벨명이 아니면 INFO fallback 없이 구조화 에러(``CONFIG_INVALID_LOG_LEVEL``)
  + exit 1 (text/JSON 모두).
- #2037: ``[guard]`` 타입 검증 — blocked_days(list[str]) / blocked_hours(list) /
  pause_during_trading(bool). 무효 타입은 ``CONFIG_INVALID_GUARD`` + exit 1.
  blocked_hours 의 window 형식(HH:MM-HH:MM)은 #2030 ``_validate_schedule_times``
  가 담당하므로 본 helper 는 list 여부만 본다(중복 검증 회피).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.feed.models.result import CollectionResult
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

_EMPTY_BACKFILL = CollectionResult(
    mode="backfill",
    started_at="2026-03-18T00:00:00Z",
    finished_at="2026-03-18T00:00:01Z",
    duration_seconds=1.0,
)

_EMPTY_DAILY = CollectionResult(
    mode="daily",
    started_at="2026-03-18T00:00:00Z",
    finished_at="2026-03-18T00:00:01Z",
    duration_seconds=1.0,
    target_date="2026-03-17",
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


def _init_with_config(tmp_path: Path, body: str) -> str:
    """주어진 config.toml 본문으로 초기화된 데이터 경로를 만든다."""
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "config.toml").write_text(body)
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()
    return str(data_dir)


_GENERAL = '[general]\nlog_level = "{log_level}"\n\n'
_SCHEDULE = (
    "[schedule]\n"
    'daily_at = "16:00"\n'
    'backfill_at = "01:00"\n'
    'backfill_since = "2024-01-01"\n\n'
)


def _config(
    *,
    log_level: str = "INFO",
    guard_body: str = (
        "[guard]\n"
        "blocked_days = []\n"
        'blocked_hours = ["09:00-15:30"]\n'
        "pause_during_trading = true\n"
    ),
) -> str:
    return _GENERAL.format(log_level=log_level) + _SCHEDULE + guard_body


def _run_backfill(runner: CliRunner, data_path: str, *, json_fmt: bool = False):  # type: ignore[no-untyped-def]
    """mock orchestrator 로 feed run backfill 실행."""
    args = ["feed", "run", "backfill", "--data-path", data_path]
    if json_fmt:
        args = ["--format", "json", *args]
    with patch("ante.feed.cli._build_orchestrator") as mock_build:
        mock_orch = AsyncMock()
        mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_BACKFILL)
        mock_build.return_value = mock_orch
        return runner.invoke(cli, args)


def _run_daily(runner: CliRunner, data_path: str, *, json_fmt: bool = False):  # type: ignore[no-untyped-def]
    """mock orchestrator 로 feed run daily 실행."""
    args = ["feed", "run", "daily", "--data-path", data_path]
    if json_fmt:
        args = ["--format", "json", *args]
    with patch("ante.feed.cli._build_orchestrator") as mock_build:
        mock_orch = AsyncMock()
        mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY)
        mock_build.return_value = mock_orch
        return runner.invoke(cli, args)


# ── #2038: log_level 적용 ───────────────────────────────────────────────────


class TestLogLevelApply:
    def test_debug_applied_to_feed_logger(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """log_level=DEBUG → ante.feed 로거 레벨이 DEBUG 로 설정된다."""
        feed_logger = logging.getLogger("ante.feed")
        original = feed_logger.level
        try:
            feed_logger.setLevel(logging.WARNING)
            data_path = _init_with_config(tmp_path, _config(log_level="DEBUG"))
            result = _run_backfill(runner, data_path)
            assert result.exit_code == 0
            assert feed_logger.level == logging.DEBUG
        finally:
            feed_logger.setLevel(original)

    def test_default_info_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        """기본 INFO 는 정상 통과(회귀)."""
        data_path = _init_with_config(tmp_path, _config(log_level="INFO"))
        result = _run_backfill(runner, data_path)
        assert result.exit_code == 0

    def test_root_logger_not_changed(self, runner: CliRunner, tmp_path: Path) -> None:
        """root 로거는 변경하지 않는다 (ante.feed 패키지 로거만)."""
        root_logger = logging.getLogger()
        original_root = root_logger.level
        feed_logger = logging.getLogger("ante.feed")
        original_feed = feed_logger.level
        try:
            data_path = _init_with_config(tmp_path, _config(log_level="ERROR"))
            result = _run_backfill(runner, data_path)
            assert result.exit_code == 0
            assert root_logger.level == original_root
            assert feed_logger.level == logging.ERROR
        finally:
            feed_logger.setLevel(original_feed)

    def test_invalid_log_level_rejected_text(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """무효 log_level(VERBOSE) → 거부 + exit 1 (INFO fallback 아님)."""
        data_path = _init_with_config(tmp_path, _config(log_level="VERBOSE"))
        result = _run_backfill(runner, data_path)
        assert result.exit_code != 0
        assert "log_level" in result.output

    def test_invalid_log_level_rejected_json(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """JSON 모드에서 구조화 에러 코드를 노출한다."""
        import json

        data_path = _init_with_config(tmp_path, _config(log_level="VERBOSE"))
        result = _run_backfill(runner, data_path, json_fmt=True)
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CONFIG_INVALID_LOG_LEVEL"

    def test_invalid_log_level_rejected_on_daily(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """daily 경로도 동일 helper 로 무효 log_level 을 거부한다."""
        data_path = _init_with_config(tmp_path, _config(log_level="VERBOSE"))
        result = _run_daily(runner, data_path)
        assert result.exit_code != 0
        assert "log_level" in result.output


# ── #2037: guard 타입 검증 ──────────────────────────────────────────────────


class TestGuardTypeValidation:
    def test_valid_guard_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        """정상 guard(blocked_days=[], blocked_hours=[...], pause=true) → 통과."""
        data_path = _init_with_config(tmp_path, _config())
        result = _run_backfill(runner, data_path)
        assert result.exit_code == 0

    def test_blocked_days_string_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """blocked_days='sat' (str, 비-list) → 거부."""
        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    "[guard]\n"
                    'blocked_days = "sat"\n'
                    'blocked_hours = ["09:00-15:30"]\n'
                    "pause_during_trading = true\n"
                )
            ),
        )
        result = _run_backfill(runner, data_path)
        assert result.exit_code != 0
        assert "blocked_days" in result.output

    def test_blocked_days_nonstring_element_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """blocked_days=[123] (비-str 원소) → 거부."""
        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    "[guard]\n"
                    "blocked_days = [123]\n"
                    'blocked_hours = ["09:00-15:30"]\n'
                    "pause_during_trading = true\n"
                )
            ),
        )
        result = _run_backfill(runner, data_path)
        assert result.exit_code != 0
        assert "blocked_days" in result.output

    def test_pause_during_trading_nonbool_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """pause_during_trading='yes' (비-bool) → 거부."""
        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    "[guard]\n"
                    "blocked_days = []\n"
                    'blocked_hours = ["09:00-15:30"]\n'
                    'pause_during_trading = "yes"\n'
                )
            ),
        )
        result = _run_backfill(runner, data_path)
        assert result.exit_code != 0
        assert "pause_during_trading" in result.output

    def test_blocked_hours_string_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """blocked_hours='09:00-15:30' (str, 비-list) → 거부."""
        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    "[guard]\n"
                    "blocked_days = []\n"
                    'blocked_hours = "09:00-15:30"\n'
                    "pause_during_trading = true\n"
                )
            ),
        )
        result = _run_backfill(runner, data_path)
        assert result.exit_code != 0
        assert "blocked_hours" in result.output

    def test_guard_error_json_code(self, runner: CliRunner, tmp_path: Path) -> None:
        """JSON 모드에서 CONFIG_INVALID_GUARD 코드를 노출한다."""
        import json

        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    '[guard]\nblocked_days = "sat"\npause_during_trading = true\n'
                )
            ),
        )
        result = _run_backfill(runner, data_path, json_fmt=True)
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CONFIG_INVALID_GUARD"

    def test_guard_validation_on_daily(self, runner: CliRunner, tmp_path: Path) -> None:
        """daily 경로도 동일 helper 로 guard 타입을 검증한다."""
        data_path = _init_with_config(
            tmp_path,
            _config(guard_body=('[guard]\npause_during_trading = "yes"\n')),
        )
        result = _run_daily(runner, data_path)
        assert result.exit_code != 0
        assert "pause_during_trading" in result.output


# ── feed start 경로도 helper 를 호출한다 ────────────────────────────────────


class TestFeedStartCallsHelper:
    def test_start_rejects_invalid_log_level(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """feed start 도 진입 시 무효 log_level 을 거부한다."""
        data_path = _init_with_config(tmp_path, _config(log_level="VERBOSE"))
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_build.return_value = AsyncMock()
            result = runner.invoke(
                cli,
                ["feed", "start", "--data-path", data_path],
            )
        assert result.exit_code != 0
        assert "log_level" in result.output

    def test_start_rejects_invalid_guard(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """feed start 도 진입 시 guard 타입을 검증한다."""
        data_path = _init_with_config(
            tmp_path,
            _config(
                guard_body=(
                    "[guard]\nblocked_days = [123]\npause_during_trading = true\n"
                )
            ),
        )
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_build.return_value = AsyncMock()
            result = runner.invoke(
                cli,
                ["feed", "start", "--data-path", data_path],
            )
        assert result.exit_code != 0
        assert "blocked_days" in result.output
