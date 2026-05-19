"""feed backfill_since 4-surface clean-reject 검증 (이슈 #1674).

검증 범위:
1. CLI `--since` malformed → `CLI_INVALID_DATE` (기존 `_validate_iso_date`
   선순위 유지).
2. CLI `--since` future → `INVALID_DATE_RANGE`, orchestrator 미호출.
3. config TOML `backfill_since` malformed/non-strict/future →
   수렴점에서 `CLI_INVALID_DATE`/`INVALID_DATE_RANGE` config_error,
   체크포인트·소스·lock 미진입.
4. CLI JSON 모드는 coded date config_error envelope만 출력 + exit 1.
5. resident `feed start` `_run_backfill_job`은 coded scope에서만
   완료 메시지 차단 + 명시 오류 echo/log.
6. 비날짜 config_errors(missing source / lock 경합) 회귀 — CLI/scheduler
   출력 및 exit 코드가 현행 유지.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.backfill_runner import (
    BACKFILL_DATE_ERROR_CODES,
    CONFIG_ERROR_CODE_INVALID_DATE,
    CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
    BackfillRunner,
    validate_backfill_since,
)
from ante.feed.pipeline.orchestrator import FeedOrchestrator
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


def _make_collection_result(
    config_errors: list[dict[str, Any]] | None = None,
) -> CollectionResult:
    return CollectionResult(
        mode="backfill",
        started_at="2026-05-20T00:00:00Z",
        finished_at="2026-05-20T00:00:01Z",
        duration_seconds=1.0,
        symbols_total=0,
        symbols_success=0,
        symbols_failed=0,
        rows_written=0,
        data_types=[],
        failures=[],
        warnings=[],
        config_errors=config_errors or [],
    )


@pytest.fixture
def runner() -> CliRunner:
    """인증된 상태의 CliRunner. stderr 분리 캡처."""
    r = CliRunner(mix_stderr=False)
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
def initialized_data_path(tmp_path: Path) -> str:
    """초기화된 데이터 디렉토리 경로 (config는 시나리오별로 덮어쓴다)."""
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()

    # 기본 config (정상 case): backfill_since=2024-01-01 (과거)
    (feed_dir / "config.toml").write_text(
        "[schedule]\n"
        'daily_at = "16:00"\n'
        'backfill_at = "01:00"\n'
        'backfill_since = "2024-01-01"\n'
        "\n"
        "[guard]\n"
        "blocked_days = []\n"
        'blocked_hours = ["09:00-15:30"]\n'
        "pause_during_trading = true\n"
    )

    return str(data_dir)


def _write_config(data_path: str, backfill_since: str | None) -> None:
    """config.toml의 backfill_since를 임의 값으로 덮어쓴다."""
    feed_dir = Path(data_path) / ".feed"
    if backfill_since is None:
        body = "[schedule]\n"
    else:
        body = f'[schedule]\nbackfill_since = "{backfill_since}"\n'
    body += "\n[guard]\nblocked_days = []\n"
    (feed_dir / "config.toml").write_text(body)


# ── (1) validate_backfill_since helper 단위 검증 ──────────────────────────


class TestValidateBackfillSinceHelper:
    """공유 strict parser/future-check helper 단위 검증."""

    def test_valid_past_date(self) -> None:
        parsed, error = validate_backfill_since("2024-01-01")
        assert parsed == date(2024, 1, 1)
        assert error is None

    def test_valid_today(self) -> None:
        # today 자체는 미래가 아니므로 정상.
        # KST 기준이지만 helper는 datetime을 고정하지 않으므로
        # 실제 today를 사용한다.
        from ante.feed.pipeline.backfill_runner import _today_kst

        today = _today_kst()
        parsed, error = validate_backfill_since(today.isoformat())
        assert parsed == today
        assert error is None

    @pytest.mark.parametrize(
        "bad_value",
        [
            "20260510",  # basic ISO (no separator)
            "2026-W19-1",  # ISO week date
            "2026-1-1",  # non-zero-padded
            "2026-13-01",  # invalid month
            "not-a-date",
            "",
            "2026/05/10",
            "2026-05-32",  # invalid day
        ],
    )
    def test_malformed_returns_invalid_date(self, bad_value: str) -> None:
        parsed, error = validate_backfill_since(bad_value)
        assert parsed is None
        assert error is not None
        assert error["code"] == CONFIG_ERROR_CODE_INVALID_DATE

    def test_future_returns_invalid_date_range(self) -> None:
        from ante.feed.pipeline.backfill_runner import _today_kst

        future = (_today_kst() + timedelta(days=365 * 30)).isoformat()
        parsed, error = validate_backfill_since(future)
        assert parsed is None
        assert error is not None
        assert error["code"] == CONFIG_ERROR_CODE_INVALID_DATE_RANGE
        assert future in error["error"]


# ── (2) CLI `--since` future early reject ─────────────────────────────────


class TestCliSinceFutureReject:
    """CLI `--since`가 future일 때 orchestrator 호출 전에 거부."""

    def test_future_since_json_envelope_only(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """`--since 2999-01-01 --format json` → exit 1, 단일 envelope,
        성공 result 미출력, orchestrator 미호출."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_make_collection_result())
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "2999-01-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            # stdout는 단일 envelope만; 성공 result(`mode`/`symbols_total`
            # 등)는 출력되어서는 안 된다.
            payload = json.loads(result.stdout)
            assert payload["status"] == "error"
            assert payload["code"] == CONFIG_ERROR_CODE_INVALID_DATE_RANGE
            assert "2999-01-01" in payload["message"]
            mock_orch.run_backfill.assert_not_awaited()

    def test_future_since_text_mode_writes_error(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_make_collection_result())
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "2999-01-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            assert "Error:" in (result.stderr or "")
            assert "2999-01-01" in (result.stderr or "")
            mock_orch.run_backfill.assert_not_awaited()

    def test_malformed_since_still_priority_invalid_date(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """malformed `--since`는 기존 CLI_INVALID_DATE 선순위 유지."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_make_collection_result())
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "2020-13-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            payload = json.loads(result.stdout)
            assert payload["code"] == CONFIG_ERROR_CODE_INVALID_DATE
            mock_orch.run_backfill.assert_not_awaited()


# ── (3) CLI config TOML backfill_since 검증 ───────────────────────────────


class TestCliConfigTomlBackfillSince:
    """config.toml backfill_since malformed/non-strict/future → 수렴점에서
    coded config_error, CLI 단일 envelope."""

    @pytest.mark.parametrize(
        ("bad_value", "expected_code"),
        [
            ("2020-13-01", CONFIG_ERROR_CODE_INVALID_DATE),
            ("20260510", CONFIG_ERROR_CODE_INVALID_DATE),
            ("2026-W19-1", CONFIG_ERROR_CODE_INVALID_DATE),
            ("2026-1-1", CONFIG_ERROR_CODE_INVALID_DATE),
            ("not-a-date", CONFIG_ERROR_CODE_INVALID_DATE),
            ("2999-01-01", CONFIG_ERROR_CODE_INVALID_DATE_RANGE),
        ],
    )
    def test_config_backfill_since_coded_error(
        self,
        runner: CliRunner,
        initialized_data_path: str,
        bad_value: str,
        expected_code: str,
    ) -> None:
        _write_config(initialized_data_path, bad_value)

        # _build_orchestrator는 실제 FeedOrchestrator를 만들도록 둔다.
        # (수렴점에서 검증되므로 외부 IO는 발생하지 않는다.)
        # 다만 BackfillRunner.run이 호출되지 않아야 함을 확인하기 위해
        # BackfillRunner.run을 spy로 감싼다.
        original_run = BackfillRunner.run
        run_calls: list[int] = []

        async def _spy_run(self, *args: Any, **kwargs: Any) -> CollectionResult:  # type: ignore[no-untyped-def]
            run_calls.append(1)
            return await original_run(self, *args, **kwargs)

        with patch.object(BackfillRunner, "run", _spy_run):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == expected_code
        # 수렴점(orchestrator.run_backfill)이 lock acquire 이전에
        # short-circuit하므로 BackfillRunner.run 자체가 호출되지 않는다.
        assert run_calls == []
        # lock 파일도 생성되지 않아야 한다 (lock acquire 이전 차단).
        lock_path = Path(initialized_data_path) / ".feed" / "lock"
        assert not lock_path.exists()

    def test_config_backfill_since_valid_past_passes(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """정상 과거 날짜는 기존 흐름 통과."""
        _write_config(initialized_data_path, "2024-01-01")
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_make_collection_result())
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            mock_orch.run_backfill.assert_awaited_once()


# ── (4) 비날짜 config_errors 회귀 (CLI) ───────────────────────────────────


class TestCliNonDateConfigErrorsRegression:
    """기존 비날짜 config_errors(소스 누락 / lock 경합) 정책 보존."""

    def test_non_date_config_error_does_not_map_to_clean_reject(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """소스 누락 같은 비날짜 config_errors는 envelope으로 잘못 매핑되어선
        안 되고, 현행 정상 출력 흐름을 유지한다."""
        legacy_errors = [
            {"error": "data.go.kr API 키 미설정", "source": "data_go_kr"},
            {"error": "DART API 키 미설정", "source": "dart"},
        ]
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(
                return_value=_make_collection_result(config_errors=legacy_errors)
            )
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            # 비날짜 config_errors는 현행과 동일하게 성공 result 출력 + exit 0.
            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            # 단일 error envelope이 아니라 성공 result dict.
            assert "status" not in payload or payload.get("status") != "error"
            assert payload.get("mode") == "backfill"
            assert payload.get("config_errors") == legacy_errors

    def test_lock_busy_error_does_not_map_to_clean_reject(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """lock 경합 config_error도 새 분기를 trigger하지 않는다."""
        legacy_errors = [{"error": "다른 수집 프로세스가 이미 실행 중"}]
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(
                return_value=_make_collection_result(config_errors=legacy_errors)
            )
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            payload = json.loads(result.stdout)
            assert payload.get("config_errors") == legacy_errors


# ── (5) BackfillRunner._validate_backfill_since 단위 ─────────────────────


class TestBackfillRunnerInternalValidation:
    """수렴점 helper가 올바른 coded shape를 반환하는지 확인."""

    def test_missing_backfill_since_returns_none(self) -> None:
        # config에 [schedule]만 있고 backfill_since 키가 없을 때는
        # DEFAULT(과거)가 적용되므로 검증을 건너뛴다.
        assert BackfillRunner._validate_backfill_since({"schedule": {}}) is None
        assert BackfillRunner._validate_backfill_since({}) is None

    @pytest.mark.parametrize(
        ("value", "expected_code"),
        [
            ("2020-13-01", CONFIG_ERROR_CODE_INVALID_DATE),
            ("20260510", CONFIG_ERROR_CODE_INVALID_DATE),
            ("2026-W19-1", CONFIG_ERROR_CODE_INVALID_DATE),
            ("2999-01-01", CONFIG_ERROR_CODE_INVALID_DATE_RANGE),
        ],
    )
    def test_invalid_backfill_since(self, value: str, expected_code: str) -> None:
        config: dict[str, Any] = {"schedule": {"backfill_since": value}}
        err = BackfillRunner._validate_backfill_since(config)
        assert err is not None
        assert err["code"] == expected_code

    def test_non_string_backfill_since_returns_invalid_date(self) -> None:
        # TOML 파서가 다른 타입을 넘기더라도 안전하게 차단.
        config: dict[str, Any] = {"schedule": {"backfill_since": 20260510}}
        err = BackfillRunner._validate_backfill_since(config)
        assert err is not None
        assert err["code"] == CONFIG_ERROR_CODE_INVALID_DATE


# ── (6) orchestrator.run_backfill 수렴점 가드 ────────────────────────────


class TestOrchestratorBackfillGate:
    """`run_backfill` 진입 시점에 future/malformed config가 lock acquire
    이전에 차단되어 체크포인트/소스/수집이 일절 호출되지 않는지 검증."""

    def test_future_config_short_circuits_before_lock(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        feed_dir = data_path / ".feed"
        feed_dir.mkdir(parents=True)

        orchestrator = FeedOrchestrator()

        async def _exercise() -> CollectionResult:
            return await orchestrator.run_backfill(
                data_path=data_path,
                config={"schedule": {"backfill_since": "2999-01-01"}},
            )

        result = asyncio.run(_exercise())

        assert any(
            isinstance(entry, dict)
            and entry.get("code") == CONFIG_ERROR_CODE_INVALID_DATE_RANGE
            for entry in result.config_errors
        )
        # lock 파일이 만들어지지 않았어야 한다.
        assert not (feed_dir / "lock").exists()

    def test_malformed_config_short_circuits_before_lock(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        feed_dir = data_path / ".feed"
        feed_dir.mkdir(parents=True)

        orchestrator = FeedOrchestrator()

        async def _exercise() -> CollectionResult:
            return await orchestrator.run_backfill(
                data_path=data_path,
                config={"schedule": {"backfill_since": "2026-W19-1"}},
            )

        result = asyncio.run(_exercise())
        assert any(
            isinstance(entry, dict)
            and entry.get("code") == CONFIG_ERROR_CODE_INVALID_DATE
            for entry in result.config_errors
        )
        assert not (feed_dir / "lock").exists()

    def test_valid_past_config_proceeds_into_runner(self, tmp_path: Path) -> None:
        data_path = tmp_path / "data"
        feed_dir = data_path / ".feed"
        feed_dir.mkdir(parents=True)

        orchestrator = FeedOrchestrator()  # 소스 없음 → ctx config_errors만

        async def _exercise() -> CollectionResult:
            return await orchestrator.run_backfill(
                data_path=data_path,
                config={"schedule": {"backfill_since": "2024-01-01"}},
            )

        result = asyncio.run(_exercise())
        # coded date error는 없어야 하고, 비날짜 source-missing 에러만 있어야 한다.
        codes = {
            entry.get("code")
            for entry in result.config_errors
            if isinstance(entry, dict)
        }
        assert not (codes & BACKFILL_DATE_ERROR_CODES)


# ── (7) cli_scheduler _run_backfill_job 차단 + 비날짜 회귀 ──────────────


class TestSchedulerBackfillJobCodedGate:
    """resident scheduler가 coded date scope에서만 완료 차단."""

    def test_coded_date_error_blocks_completion_message(self) -> None:
        from ante.feed import cli_scheduler

        mock_orch = MagicMock()
        mock_orch.run_backfill = AsyncMock(
            return_value=_make_collection_result(
                config_errors=[
                    {
                        "code": CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
                        "error": "backfill_since가 미래입니다",
                    }
                ]
            )
        )

        echoed: list[str] = []
        with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
            asyncio.run(
                cli_scheduler._run_backfill_job(mock_orch, "data/", {}, "2026-05-20")
            )

        # 완료 메시지 미출력
        assert not any("Backfill 완료" in line for line in echoed)
        # 명시 오류 라인 출력
        assert any(CONFIG_ERROR_CODE_INVALID_DATE_RANGE in line for line in echoed)

    def test_malformed_coded_error_blocks_completion_message(self) -> None:
        from ante.feed import cli_scheduler

        mock_orch = MagicMock()
        mock_orch.run_backfill = AsyncMock(
            return_value=_make_collection_result(
                config_errors=[
                    {
                        "code": CONFIG_ERROR_CODE_INVALID_DATE,
                        "error": "잘못된 형식",
                    }
                ]
            )
        )

        echoed: list[str] = []
        with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
            asyncio.run(
                cli_scheduler._run_backfill_job(mock_orch, "data/", {}, "2026-05-20")
            )

        assert not any("Backfill 완료" in line for line in echoed)
        assert any(CONFIG_ERROR_CODE_INVALID_DATE in line for line in echoed)

    def test_non_date_config_error_keeps_legacy_completion_message(
        self,
    ) -> None:
        """비날짜 config_errors만 있을 때는 현행 완료 메시지 그대로."""
        from ante.feed import cli_scheduler

        mock_orch = MagicMock()
        mock_orch.run_backfill = AsyncMock(
            return_value=_make_collection_result(
                config_errors=[
                    {"error": "data.go.kr API 키 미설정", "source": "data_go_kr"},
                    {"error": "다른 수집 프로세스가 이미 실행 중"},
                ]
            )
        )

        echoed: list[str] = []
        with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
            asyncio.run(
                cli_scheduler._run_backfill_job(mock_orch, "data/", {}, "2026-05-20")
            )

        # 현행 동작: "Backfill 완료" 메시지는 그대로 출력된다.
        assert any("Backfill 완료" in line for line in echoed)
        # 신설 차단 분기가 trigger되어선 안 된다.
        assert not any(
            CONFIG_ERROR_CODE_INVALID_DATE in line
            or CONFIG_ERROR_CODE_INVALID_DATE_RANGE in line
            for line in echoed
        )

    def test_no_config_errors_keeps_legacy_completion_message(self) -> None:
        from ante.feed import cli_scheduler

        mock_orch = MagicMock()
        mock_orch.run_backfill = AsyncMock(return_value=_make_collection_result())

        echoed: list[str] = []
        with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
            asyncio.run(
                cli_scheduler._run_backfill_job(mock_orch, "data/", {}, "2026-05-20")
            )

        assert any("Backfill 완료" in line for line in echoed)
