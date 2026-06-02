"""feed start 프로세스 우선순위(nice_value) 적용 테스트 (#2029).

스펙(docs/specs/data-feed/08-resource-protection.md)의 "시작 시 프로세스
우선순위를 낮춘다" 계약을 ``feed start`` 가 상주 루프 진입 전에 적용한다.

- 유효 nice_value(기본 10) → os.setpriority(PRIO_PROCESS, 0, nice_value) 호출.
- 범위 밖(25, -1)/비-int → 구조화 config error(CONFIG_INVALID_NICE_VALUE) + exit 1.
- 적용 실패(OSError/PermissionError) → warning + run_scheduler_loop 계속 진입.
- 비-POSIX(AttributeError) → graceful(루프 계속 진입).
- feed run 일회성에는 nice 를 적용하지 않는다(스펙 한정, 비목표 회귀).
"""

from __future__ import annotations

import os
from pathlib import Path
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


def _init_with_config(tmp_path: Path, *, nice_value: str | None = "10") -> str:
    """주어진 nice_value 로 초기화된 데이터 경로를 만든다.

    ``nice_value=None`` 이면 [general] 에 nice_value 키를 생략한다(기본값 경로).
    """
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)

    general = '[general]\nlog_level = "INFO"\n'
    if nice_value is not None:
        general += f"nice_value = {nice_value}\n"
    body = (
        general + "\n[schedule]\n"
        'daily_at = "16:00"\n'
        'backfill_at = "01:00"\n'
        'backfill_since = "2024-01-01"\n\n'
        "[guard]\n"
        "blocked_days = []\n"
        'blocked_hours = ["09:00-15:30"]\n'
        "pause_during_trading = true\n"
    )
    (feed_dir / "config.toml").write_text(body)
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()
    return str(data_dir)


def _invoke_start(runner: CliRunner, data_path: str, *, json_fmt: bool = False):  # type: ignore[no-untyped-def]
    """mock orchestrator + mock run_scheduler_loop 로 feed start 실행."""
    args = ["feed", "start", "--data-path", data_path]
    if json_fmt:
        args = ["--format", "json", *args]
    with (
        patch("ante.feed.cli._build_orchestrator") as mock_build,
        patch(
            "ante.feed.cli_scheduler.run_scheduler_loop", new_callable=AsyncMock
        ) as mock_loop,
    ):
        mock_build.return_value = AsyncMock()
        # 상주 루프는 즉시 반환(awaitable)하도록 AsyncMock — 진입 여부만 본다.
        mock_loop.return_value = None
        result = runner.invoke(cli, args)
    return result, mock_loop


# ── (a) 유효 nice_value → setpriority 호출 ──────────────────────────────────


class TestValidNiceApplied:
    def test_default_ten_calls_setpriority(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """nice_value=10 → os.setpriority(PRIO_PROCESS, 0, 10) 호출 후 루프 진입."""
        data_path = _init_with_config(tmp_path, nice_value="10")
        with patch("os.setpriority") as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code == 0, result.output
        mock_sp.assert_called_once_with(os.PRIO_PROCESS, 0, 10)
        mock_loop.assert_called_once()

    def test_missing_nice_value_uses_default_ten(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """nice_value 미지정 → 기본값 10 으로 setpriority 호출."""
        data_path = _init_with_config(tmp_path, nice_value=None)
        with patch("os.setpriority") as mock_sp:
            result, _ = _invoke_start(runner, data_path)
        assert result.exit_code == 0, result.output
        mock_sp.assert_called_once_with(os.PRIO_PROCESS, 0, 10)

    def test_boundary_zero_and_nineteen(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """경계값 0, 19 는 허용되어 setpriority 로 전달된다."""
        for value in ("0", "19"):
            data_path = _init_with_config(tmp_path / value, nice_value=value)
            with patch("os.setpriority") as mock_sp:
                result, _ = _invoke_start(runner, data_path)
            assert result.exit_code == 0, result.output
            mock_sp.assert_called_once_with(os.PRIO_PROCESS, 0, int(value))


# ── (b) 범위 밖/비-int → config error ──────────────────────────────────────


class TestInvalidNiceRejected:
    @pytest.mark.parametrize("value", ["25", "20", "-1", "100"])
    def test_out_of_range_rejected(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        """0..19 범위 밖 → CONFIG_INVALID_NICE_VALUE + exit 1, setpriority 미호출."""
        data_path = _init_with_config(tmp_path / value.lstrip("-"), nice_value=value)
        with patch("os.setpriority") as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code != 0
        assert "nice_value" in result.output
        mock_sp.assert_not_called()
        mock_loop.assert_not_called()

    def test_out_of_range_json_code(self, runner: CliRunner, tmp_path: Path) -> None:
        """JSON 모드에서 CONFIG_INVALID_NICE_VALUE 코드를 노출한다."""
        import json

        data_path = _init_with_config(tmp_path, nice_value="25")
        result, _ = _invoke_start(runner, data_path, json_fmt=True)
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CONFIG_INVALID_NICE_VALUE"

    def test_non_int_string_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        """nice_value='high' (str) → 거부."""
        data_path = _init_with_config(tmp_path, nice_value='"high"')
        with patch("os.setpriority") as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code != 0
        assert "nice_value" in result.output
        mock_sp.assert_not_called()
        mock_loop.assert_not_called()

    def test_float_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        """nice_value=10.5 (float) → 거부."""
        data_path = _init_with_config(tmp_path, nice_value="10.5")
        with patch("os.setpriority") as mock_sp:
            result, _ = _invoke_start(runner, data_path)
        assert result.exit_code != 0
        assert "nice_value" in result.output
        mock_sp.assert_not_called()

    def test_bool_rejected(self, runner: CliRunner, tmp_path: Path) -> None:
        """nice_value=true (bool) → 거부 (int subclass 이지만 무의미)."""
        data_path = _init_with_config(tmp_path, nice_value="true")
        with patch("os.setpriority") as mock_sp:
            result, _ = _invoke_start(runner, data_path)
        assert result.exit_code != 0
        assert "nice_value" in result.output
        mock_sp.assert_not_called()


# ── (c)(d) 적용 실패 best-effort → warning + 루프 계속 진입 ─────────────────


class TestApplyBestEffort:
    def test_oserror_warns_and_continues(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """setpriority 가 OSError → warning 후 run_scheduler_loop 진입(실패 안 함)."""
        data_path = _init_with_config(tmp_path, nice_value="10")
        with patch("os.setpriority", side_effect=OSError("nope")) as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code == 0, result.output
        mock_sp.assert_called_once()
        mock_loop.assert_called_once()

    def test_permission_error_warns_and_continues(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """setpriority 가 PermissionError → graceful, 루프 진입."""
        data_path = _init_with_config(tmp_path, nice_value="10")
        with patch("os.setpriority", side_effect=PermissionError("denied")) as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code == 0, result.output
        mock_sp.assert_called_once()
        mock_loop.assert_called_once()

    def test_non_posix_attribute_error_graceful(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """비-POSIX(os.setpriority 부재, AttributeError) → graceful, 루프 진입."""
        data_path = _init_with_config(tmp_path, nice_value="10")
        with patch(
            "os.setpriority", side_effect=AttributeError("no setpriority")
        ) as mock_sp:
            result, mock_loop = _invoke_start(runner, data_path)
        assert result.exit_code == 0, result.output
        mock_sp.assert_called_once()
        mock_loop.assert_called_once()


# ── 비목표 회귀: feed run 에는 nice 미적용 ──────────────────────────────────


class TestFeedRunNoNice:
    def test_feed_run_backfill_does_not_apply_nice(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """feed run backfill 은 nice 를 적용하지 않는다(스펙: feed start 한정)."""
        from ante.feed.models.result import CollectionResult

        data_path = _init_with_config(tmp_path, nice_value="10")
        with (
            patch("ante.feed.cli._build_orchestrator") as mock_build,
            patch("os.setpriority") as mock_sp,
        ):
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(
                return_value=CollectionResult(
                    mode="backfill",
                    started_at="2026-03-18T00:00:00Z",
                    finished_at="2026-03-18T00:00:01Z",
                    duration_seconds=1.0,
                )
            )
            mock_build.return_value = mock_orch
            result = runner.invoke(
                cli, ["feed", "run", "backfill", "--data-path", data_path]
            )
        assert result.exit_code == 0, result.output
        mock_sp.assert_not_called()
