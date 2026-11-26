"""``feed`` 명령의 실패 경로와 실패가 아닌 종료 (#2738 ⑧-4).

``cli/commands/feed.py``의 출구마다 두 모드의 출력을 리터럴로 잠근다. JSON은
stdout 바이트 전체를, text는 stdout·stderr 전체를 비교한다. 실패가 아닌 종료
(스케줄러의 ``KeyboardInterrupt``, 미초기화 ``status``)와 날짜 코드가 아닌
``config_errors``가 성공 출력으로 이어지는 경로도 함께 잠근다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner, Result

from ante.cli.main import cli
from ante.feed.models.result import CollectionResult
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_DATA = "data"
_TODAY = date(2026, 1, 1)
_BASE_CONFIG = '[schedule]\nbackfill_since = "2024-01-01"\n'


def _set_master(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _MASTER


def _result(config_errors: list[dict[str, Any]]) -> CollectionResult:
    return CollectionResult(
        mode="backfill",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
        duration_seconds=1.0,
        symbols_total=0,
        symbols_success=0,
        symbols_failed=0,
        rows_written=0,
        data_types=[],
        failures=[],
        warnings=[],
        config_errors=config_errors,
    )


@pytest.fixture(autouse=True)
def _workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    yield


def _init(config: str = _BASE_CONFIG) -> None:
    feed_dir = Path(_DATA) / ".feed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "config.toml").write_text(config, encoding="utf-8")
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()


def _invoke(mode: str, args: list[str], *patches: Any) -> Result:
    runner = CliRunner(mix_stderr=False)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_master)
        )
        stack.enter_context(
            patch("ante.feed.pipeline.backfill_runner._today_kst", return_value=_TODAY)
        )
        for p in patches:
            stack.enter_context(p)
        return runner.invoke(cli, ["--format", mode, *args])


def _orchestrator(result: CollectionResult) -> Any:
    orch = AsyncMock()
    orch.run_backfill = AsyncMock(return_value=result)
    orch.run_daily = AsyncMock(return_value=result)
    return patch("ante.cli.commands.feed._build_orchestrator", return_value=orch)


def _no_nice() -> Any:
    return patch("ante.cli.commands.feed._apply_process_nice")


def _scheduler(exc: BaseException) -> Any:
    return patch(
        "ante.feed.cli_scheduler.run_scheduler_loop",
        AsyncMock(side_effect=exc),
    )


def _expected_text(code: str, message: str) -> str:
    return f"Error: {code}: {message}\n"


def _assert_json(result: Result, code: str, message: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    expected = json.dumps({"status": "error", "code": code, "message": message})
    assert result.stdout == expected + "\n"
    assert result.stderr == ""


def _assert_text(result: Result, code: str, message: str) -> None:
    assert result.exit_code == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert result.stderr == _expected_text(code, message)


def _check(mode: str, result: Result, code: str, message: str) -> None:
    if mode == "json":
        _assert_json(result, code, message)
    else:
        _assert_text(result, code, message)


_MODES = pytest.mark.parametrize("mode", ["json", "text"])

_NOT_INIT = "DataFeed가 초기화되지 않았습니다. 먼저 실행: ante feed init data"


@_MODES
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["feed", "run", "backfill"], id="backfill"),
        pytest.param(["feed", "run", "daily"], id="daily"),
        pytest.param(["feed", "start"], id="start"),
    ],
)
def test_not_initialized(mode: str, args: list[str]) -> None:
    result = _invoke(mode, [*args, "--data-path", _DATA], _no_nice())
    _check(mode, result, "NOT_INITIALIZED", _NOT_INIT)


@_MODES
@pytest.mark.parametrize(
    ("args", "message"),
    [
        pytest.param(
            ["feed", "run", "backfill", "--since", "2024-1-01"],
            "잘못된 --since 날짜 형식: '2024-1-01' (YYYY-MM-DD 형식 필요)",
            id="backfill-shape",
        ),
        pytest.param(
            ["feed", "run", "backfill", "--since", "2024-02-30"],
            "잘못된 --since 날짜 형식: '2024-02-30' (YYYY-MM-DD 형식 필요)",
            id="backfill-calendar",
        ),
        pytest.param(
            ["feed", "run", "daily", "--date", "20240101"],
            "잘못된 --date 날짜 형식: '20240101' (YYYY-MM-DD 형식 필요)",
            id="daily-shape",
        ),
        pytest.param(
            ["feed", "run", "daily", "--date", "2024-13-01"],
            "잘못된 --date 날짜 형식: '2024-13-01' (YYYY-MM-DD 형식 필요)",
            id="daily-calendar",
        ),
    ],
)
def test_invalid_date_option(mode: str, args: list[str], message: str) -> None:
    _init()
    result = _invoke(mode, [*args, "--data-path", _DATA])
    _check(mode, result, "CLI_INVALID_DATE", message)


@_MODES
def test_backfill_since_in_future(mode: str) -> None:
    _init()
    result = _invoke(
        mode, ["feed", "run", "backfill", "--since", "2026-01-02", "--data-path", _DATA]
    )
    _check(
        mode,
        result,
        "INVALID_DATE_RANGE",
        "잘못된 --since 날짜: backfill_since가 오늘(2026-01-01)보다 미래입니다: "
        "'2026-01-02'",
    )


_CONFIG_CELLS = [
    pytest.param(
        "general = 1\n",
        "CONFIG_INVALID_GENERAL",
        "[general] 섹션은 table 이어야 합니다 (현재: int)",
        id="general-not-table",
    ),
    pytest.param(
        '[general]\nlog_level = "LOUD"\n',
        "CONFIG_INVALID_LOG_LEVEL",
        "유효하지 않은 log_level: 'LOUD' (허용: CRITICAL, DEBUG, ERROR, INFO, WARNING)",
        id="log-level",
    ),
    pytest.param(
        "guard = 1\n",
        "CONFIG_INVALID_GUARD",
        "[guard] 섹션은 table 이어야 합니다 (현재: int)",
        id="guard-not-table",
    ),
    pytest.param(
        '[guard]\nblocked_days = "mon"\npause_during_trading = 1\n',
        "CONFIG_INVALID_GUARD",
        "잘못된 [guard] 설정: blocked_days 는 list 여야 합니다 (현재: str); "
        "pause_during_trading 는 bool 이어야 합니다 (현재: int)",
        id="guard-fields",
    ),
]


@_MODES
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["feed", "run", "backfill"], id="backfill"),
        pytest.param(["feed", "run", "daily"], id="daily"),
        pytest.param(["feed", "start"], id="start"),
    ],
)
@pytest.mark.parametrize(("config", "code", "message"), _CONFIG_CELLS)
def test_invalid_feed_config(
    mode: str, args: list[str], config: str, code: str, message: str
) -> None:
    _init(config)
    result = _invoke(mode, [*args, "--data-path", _DATA], _no_nice())
    _check(mode, result, code, message)


@_MODES
@pytest.mark.parametrize(
    ("config", "code", "message"),
    [
        pytest.param(
            "general = 1\n",
            "CONFIG_INVALID_GENERAL",
            "[general] 섹션은 table 이어야 합니다 (현재: int)",
            id="general-not-table",
        ),
        pytest.param(
            '[general]\nnice_value = "x"\n',
            "CONFIG_INVALID_NICE_VALUE",
            "nice_value 는 정수여야 합니다 (현재: 'x', type=str)",
            id="not-int",
        ),
        pytest.param(
            "[general]\nnice_value = true\n",
            "CONFIG_INVALID_NICE_VALUE",
            "nice_value 는 정수여야 합니다 (현재: True, type=bool)",
            id="bool",
        ),
        pytest.param(
            "[general]\nnice_value = 20\n",
            "CONFIG_INVALID_NICE_VALUE",
            "nice_value 는 0..19 범위여야 합니다 (현재: 20)",
            id="out-of-range",
        ),
    ],
)
def test_start_invalid_nice_value(
    mode: str, config: str, code: str, message: str
) -> None:
    _init(config)
    result = _invoke(
        mode,
        ["feed", "start", "--data-path", _DATA],
        _no_nice(),
        patch("ante.cli.commands.feed._apply_log_level"),
    )
    _check(mode, result, code, message)


@_MODES
def test_start_invalid_schedule_time(mode: str) -> None:
    _init('[schedule]\nbackfill_since = "2024-01-01"\ndaily_at = "25:00"\n')
    loop = AsyncMock()
    with (
        patch("ante.feed.cli_scheduler.run_scheduler_loop", loop),
        patch("ante.cli.commands.feed._build_orchestrator") as build,
    ):
        result = _invoke(mode, ["feed", "start", "--data-path", _DATA], _no_nice())
    _check(
        mode,
        result,
        "CLI_INVALID_SCHEDULE_TIME",
        "스케줄 시간 설정이 올바르지 않습니다: 잘못된 daily_at 형식: '25:00' "
        "(zero-padded HH:MM 필요, 예: 16:00)",
    )
    loop.assert_not_called()
    build.assert_not_called()


@_MODES
def test_start_cross_midnight_blocked_hours(mode: str) -> None:
    _init(_BASE_CONFIG + '[guard]\nblocked_hours = ["23:00-02:00"]\n')
    loop = AsyncMock()
    with (
        patch("ante.feed.cli_scheduler.run_scheduler_loop", loop),
        patch("ante.cli.commands.feed._build_orchestrator") as build,
    ):
        result = _invoke(mode, ["feed", "start", "--data-path", _DATA], _no_nice())
    _check(
        mode,
        result,
        "CLI_INVALID_SCHEDULE_TIME",
        "스케줄 시간 설정이 올바르지 않습니다: 잘못된 blocked_hours 항목: "
        "'23:00-02:00' (시작이 끝보다 늦은 구간은 받지 않습니다 — 자정을 넘으면 "
        "두 구간으로 나눠 적으세요, 예: 23:00-23:59, 00:00-02:00)",
    )
    loop.assert_not_called()
    build.assert_not_called()


@_MODES
def test_start_unrelated_value_error_is_not_schedule_error(mode: str) -> None:
    _init()
    result = _invoke(
        mode,
        ["feed", "start", "--data-path", _DATA],
        _no_nice(),
        _orchestrator(_result([])),
        _scheduler(ValueError("boom")),
    )
    _check(mode, result, "EXECUTION_ERROR", "boom")


@_MODES
def test_start_keyboard_interrupt_is_not_an_error(mode: str) -> None:
    _init()
    result = _invoke(
        mode,
        ["feed", "start", "--data-path", _DATA],
        _no_nice(),
        _orchestrator(_result([])),
        _scheduler(KeyboardInterrupt()),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert result.stdout == "\nDataFeed 스케줄러 종료\n"
    assert result.stderr == ""


@_MODES
def test_status_not_initialized_is_not_an_error(mode: str) -> None:
    result = _invoke(mode, ["feed", "status", "--data-path", _DATA])
    assert result.exit_code == 0, (result.stdout, result.stderr)
    if mode == "json":
        assert result.stdout == (
            json.dumps(
                {"initialized": False, "message": "init 필요"},
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        assert result.stdout == (
            "DataFeed가 초기화되지 않았습니다.\n초기화: ante feed init data\n"
        )
    assert result.stderr == ""


_BACKFILL_CODES = [
    pytest.param(
        "CLI_INVALID_DATE",
        "잘못된 backfill_since 날짜 형식: '2024-1-1' (YYYY-MM-DD 형식 필요)",
        id="invalid-date",
    ),
    pytest.param(
        "INVALID_DATE_RANGE",
        "backfill_since가 오늘(2026-01-01)보다 미래입니다: '2027-01-01'",
        id="invalid-date-range",
    ),
    pytest.param(
        "GUARD_PERMANENTLY_BLOCKED",
        "거래시간 가드(blocked_hours)가 대기 상한(93600s)을 초과해 "
        "해제되지 않았습니다. blocked_hours 설정을 확인하세요",
        id="guard-permanently-blocked",
    ),
    pytest.param(
        "BACKFILL_STOP_REQUESTED",
        "중단 요청으로 backfill 거래시간 대기를 종료했습니다",
        id="backfill-stop-requested",
    ),
]


@_MODES
@pytest.mark.parametrize(("code", "message"), _BACKFILL_CODES)
def test_backfill_date_config_error(mode: str, code: str, message: str) -> None:
    _init()
    errors: list[Any] = [
        "not-a-dict",
        {"code": "OTHER", "error": "무시된다"},
        {"code": code, "error": message, "source": "data_go_kr"},
        {"code": "CLI_INVALID_DATE", "error": "두 번째는 찍히지 않는다"},
    ]
    result = _invoke(
        mode,
        ["feed", "run", "backfill", "--data-path", _DATA],
        _orchestrator(_result(errors)),
    )
    _check(mode, result, code, message)


@_MODES
def test_backfill_date_config_error_without_message(mode: str) -> None:
    _init()
    result = _invoke(
        mode,
        ["feed", "run", "backfill", "--data-path", _DATA],
        _orchestrator(_result([{"code": "GUARD_PERMANENTLY_BLOCKED"}])),
    )
    _check(mode, result, "GUARD_PERMANENTLY_BLOCKED", "")


@_MODES
def test_backfill_non_date_config_error_reaches_summary(mode: str) -> None:
    _init()
    result = _invoke(
        mode,
        ["feed", "run", "backfill", "--data-path", _DATA],
        _orchestrator(_result([{"code": "OTHER", "error": "날짜 오류가 아니다"}])),
    )
    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    if mode == "json":
        assert json.loads(result.stdout)["config_errors"] == [
            {"code": "OTHER", "error": "날짜 오류가 아니다"}
        ]
    else:
        assert "날짜 오류가 아니다" in result.stdout


_SUPPORTED = "ANTE_DATAGOKR_API_KEY, ANTE_DART_API_KEY"


@_MODES
def test_config_set_unsupported_key(mode: str) -> None:
    result = _invoke(
        mode, ["feed", "config", "set", "FOO", "bar", "--data-path", _DATA]
    )
    _check(
        mode,
        result,
        "CONFIG_UNSUPPORTED_KEY",
        f"지원하지 않는 키입니다: FOO\n지원 키: {_SUPPORTED}",
    )
    assert not Path(_DATA).exists()


@_MODES
def test_config_set_invalid_value(mode: str) -> None:
    result = _invoke(
        mode,
        [
            "feed",
            "config",
            "set",
            "ANTE_DART_API_KEY",
            "a\nANTE_DATAGOKR_API_KEY=b",
            "--data-path",
            _DATA,
        ],
    )
    _check(
        mode,
        result,
        "CONFIG_INVALID_VALUE",
        "API 키 값에 개행 문자를 포함할 수 없습니다",
    )
    assert not (Path(_DATA) / ".feed" / ".env").exists()


@_MODES
def test_config_set_unencodable_value_preserves_env(mode: str) -> None:
    _init()
    env_path = Path(_DATA) / ".feed" / ".env"
    before = b"ANTE_DATAGOKR_API_KEY=aaa111\nANTE_DART_API_KEY=bbb222\n"
    env_path.write_bytes(before)
    env_path.chmod(0o600)
    result = _invoke(
        mode,
        [
            "feed",
            "config",
            "set",
            "ANTE_DART_API_KEY",
            "x\udcffy",
            "--data-path",
            _DATA,
        ],
    )
    _check(
        mode, result, "CONFIG_INVALID_VALUE", "API 키 값을 UTF-8로 인코딩할 수 없습니다"
    )
    assert env_path.read_bytes() == before
    assert sorted(p.name for p in env_path.parent.glob(".env*")) == [".env"]
    for trace in ("aaa111", "bbb222", "codec", "\\udcff", "\udcff", "position"):
        assert trace not in result.stdout + result.stderr


_NON_UTF8_ENV = b"ANTE_DART_API_KEY=fake-sec\xff\xfe-tail\n"


@_MODES
@pytest.mark.parametrize(
    "args",
    [
        pytest.param(["feed", "config", "set", "ANTE_DART_API_KEY", "v"], id="set"),
        pytest.param(["feed", "config", "list"], id="list"),
        pytest.param(["feed", "config", "check"], id="check"),
        pytest.param(["feed", "status"], id="status"),
        pytest.param(["feed", "run", "backfill"], id="backfill"),
        pytest.param(["feed", "run", "daily"], id="daily"),
        pytest.param(["feed", "start"], id="start"),
    ],
)
def test_non_utf8_env_is_execution_error(mode: str, args: list[str]) -> None:
    _init()
    env_path = Path(_DATA) / ".feed" / ".env"
    env_path.write_bytes(_NON_UTF8_ENV)
    result = _invoke(
        mode,
        [*args, "--data-path", _DATA],
        _no_nice(),
        _scheduler(AssertionError("스케줄 루프에 닿으면 안 된다")),
    )
    _check(
        mode, result, "EXECUTION_ERROR", "feed .env 파일을 UTF-8로 읽을 수 없습니다."
    )
    assert env_path.read_bytes() == _NON_UTF8_ENV
    for trace in ("0xff", "0xfe", "codec", "position", "fake-sec", _DATA + "/"):
        assert trace not in result.stdout + result.stderr


def _csv() -> str:
    path = Path("prices.csv")
    path.write_text("date,open,high,low,close,volume\n", encoding="utf-8")
    return str(path)


@_MODES
@pytest.mark.parametrize(
    ("options", "code", "message"),
    [
        pytest.param(
            ["--symbol", "005930", "--timeframe", "2d"],
            "FEED_INJECT_INVALID_TIMEFRAME",
            "유효하지 않은 타임프레임: '2d'. 허용 값: 1m, 5m, 15m, 1h, 1d",
            id="timeframe",
        ),
        pytest.param(
            ["--symbol", "ABC"],
            "FEED_INJECT_INVALID_SYMBOL",
            "유효하지 않은 종목 코드: 'ABC' (KRX 6자리 숫자)",
            id="symbol",
        ),
    ],
)
def test_inject_invalid_option(
    mode: str, options: list[str], code: str, message: str
) -> None:
    result = _invoke(mode, ["feed", "inject", _csv(), *options, "--data-path", _DATA])
    _check(mode, result, code, message)


@_MODES
@pytest.mark.parametrize(
    ("exc", "code", "message"),
    [
        pytest.param(
            FileNotFoundError("파일 없음: prices.csv"),
            "FILE_NOT_FOUND",
            "파일 없음: prices.csv",
            id="file-not-found",
        ),
        pytest.param(
            ValueError("필수 컬럼 누락: close"),
            "VALIDATION_ERROR",
            "필수 컬럼 누락: close",
            id="validation",
        ),
    ],
)
def test_inject_failure(mode: str, exc: Exception, code: str, message: str) -> None:
    result = _invoke(
        mode,
        ["feed", "inject", _csv(), "--symbol", "005930", "--data-path", _DATA],
        patch("ante.feed.injector.FeedInjector.inject_csv", side_effect=exc),
    )
    _check(mode, result, code, message)


def test_backfill_date_error_classes_cover_exactly_the_runner_codes() -> None:
    from ante.cli.commands import feed
    from ante.feed.pipeline.backfill_runner import BACKFILL_DATE_ERROR_CODES

    assert set(feed._BACKFILL_DATE_ERRORS) == set(BACKFILL_DATE_ERROR_CODES)
    assert all(
        getattr(cls, "code") == code for code, cls in feed._BACKFILL_DATE_ERRORS.items()
    )
