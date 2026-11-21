"""ante feed — DataFeed CLI 커맨드."""

from __future__ import annotations

import logging
import pathlib
import re
from typing import TYPE_CHECKING

import click

from ante.cli._data_path import resolve_data_path
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

if TYPE_CHECKING:
    from ante.feed.report.generator import ReportGenerator

logger = logging.getLogger("ante.feed.cli")

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _validate_iso_date(value: str, option: str, fmt: object) -> None:
    """``value``가 엄격한 ``YYYY-MM-DD``인지 검증한다."""
    from datetime import date

    if _ISO_DATE_RE.fullmatch(value) is None:
        fmt.error(  # type: ignore[attr-defined]
            f"잘못된 {option} 날짜 형식: '{value}' (YYYY-MM-DD 형식 필요)",
            code="CLI_INVALID_DATE",
        )
        raise SystemExit(1)

    try:
        date.fromisoformat(value)
    except ValueError:
        fmt.error(  # type: ignore[attr-defined]
            f"잘못된 {option} 날짜 형식: '{value}' (YYYY-MM-DD 형식 필요)",
            code="CLI_INVALID_DATE",
        )
        raise SystemExit(1)


_DATA_PATH_HELP = "데이터 저장소 경로 (미지정 시 config_dir 기반)"
_SCOPE_DATA_WRITE = "data:write"
_SCOPE_DATA_READ = "data:read"
_SEPARATOR = "──────────────────────────────────────────────────"

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_FEED_LOGGER_NAME = "ante.feed"


def _apply_log_level(config: dict[str, object], fmt: object) -> None:
    """``[general].log_level`` 을 ``ante.feed`` 패키지 로거에 적용한다."""
    general = config.get("general", {})
    if not isinstance(general, dict):
        fmt.error(  # type: ignore[attr-defined]
            f"[general] 섹션은 table 이어야 합니다 (현재: {type(general).__name__})",
            code="CONFIG_INVALID_GENERAL",
        )
        raise SystemExit(1)

    level_name = general.get("log_level", "INFO")
    if not isinstance(level_name, str) or level_name.upper() not in _VALID_LOG_LEVELS:
        allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
        fmt.error(  # type: ignore[attr-defined]
            f"유효하지 않은 log_level: {level_name!r} (허용: {allowed})",
            code="CONFIG_INVALID_LOG_LEVEL",
        )
        raise SystemExit(1)

    logging.getLogger(_FEED_LOGGER_NAME).setLevel(getattr(logging, level_name.upper()))


def _validate_guard_config(config: dict[str, object], fmt: object) -> None:
    """``[guard]`` 섹션의 타입/형식을 진입 시 1회 fail-fast 검증한다."""
    guard = config.get("guard", {})
    if not isinstance(guard, dict):
        fmt.error(  # type: ignore[attr-defined]
            f"[guard] 섹션은 table 이어야 합니다 (현재: {type(guard).__name__})",
            code="CONFIG_INVALID_GUARD",
        )
        raise SystemExit(1)

    errors: list[str] = []

    if "blocked_days" in guard:
        blocked_days = guard["blocked_days"]
        if not isinstance(blocked_days, list):
            errors.append(
                f"blocked_days 는 list 여야 합니다 "
                f"(현재: {type(blocked_days).__name__})"
            )
        else:
            non_str = [d for d in blocked_days if not isinstance(d, str)]
            if non_str:
                errors.append(
                    f"blocked_days 의 모든 원소는 요일 문자열이어야 합니다 "
                    f"(비-문자열 원소: {non_str!r})"
                )

    if "blocked_hours" in guard and not isinstance(guard["blocked_hours"], list):
        errors.append(
            f"blocked_hours 는 list 여야 합니다 "
            f"(현재: {type(guard['blocked_hours']).__name__})"
        )

    if "pause_during_trading" in guard and not isinstance(
        guard["pause_during_trading"], bool
    ):
        errors.append(
            f"pause_during_trading 는 bool 이어야 합니다 "
            f"(현재: {type(guard['pause_during_trading']).__name__})"
        )

    if errors:
        fmt.error(  # type: ignore[attr-defined]
            "잘못된 [guard] 설정: " + "; ".join(errors),
            code="CONFIG_INVALID_GUARD",
        )
        raise SystemExit(1)


def _validate_and_apply_feed_config(config: dict[str, object], fmt: object) -> None:
    """feed 커맨드 공통 진입 검증/적용."""
    _apply_log_level(config, fmt)
    _validate_guard_config(config, fmt)


_NICE_VALUE_MIN = 0
_NICE_VALUE_MAX = 19
_NICE_VALUE_DEFAULT = 10


def _validate_nice_value(config: dict[str, object], fmt: object) -> int:
    """``[general].nice_value`` 를 읽어 타입/범위를 검증하고 반환한다."""
    general = config.get("general", {})
    if not isinstance(general, dict):
        fmt.error(  # type: ignore[attr-defined]
            f"[general] 섹션은 table 이어야 합니다 (현재: {type(general).__name__})",
            code="CONFIG_INVALID_GENERAL",
        )
        raise SystemExit(1)

    nice_value = general.get("nice_value", _NICE_VALUE_DEFAULT)
    if isinstance(nice_value, bool) or not isinstance(nice_value, int):
        fmt.error(  # type: ignore[attr-defined]
            f"nice_value 는 정수여야 합니다 "
            f"(현재: {nice_value!r}, type={type(nice_value).__name__})",
            code="CONFIG_INVALID_NICE_VALUE",
        )
        raise SystemExit(1)

    if not (_NICE_VALUE_MIN <= nice_value <= _NICE_VALUE_MAX):
        fmt.error(  # type: ignore[attr-defined]
            f"nice_value 는 {_NICE_VALUE_MIN}..{_NICE_VALUE_MAX} 범위여야 합니다 "
            f"(현재: {nice_value})",
            code="CONFIG_INVALID_NICE_VALUE",
        )
        raise SystemExit(1)

    return nice_value


def _apply_process_nice(nice_value: int) -> None:
    """현재 프로세스의 nice 값을 ``nice_value`` 절대값으로 설정한다."""
    import os

    try:
        os.setpriority(os.PRIO_PROCESS, 0, nice_value)  # type: ignore[attr-defined]
    except (PermissionError, OSError, AttributeError, ValueError) as exc:
        logger.warning(
            "프로세스 우선순위(nice=%d) 적용 실패 — 수집은 계속합니다: %s",
            nice_value,
            exc,
        )
        return

    logger.info("프로세스 우선순위 적용: nice=%d", nice_value)


_API_KEY_GUIDE = """\
──────────────────────────────────────────────────
API 키 설정이 필요합니다.

DataFeed은 공공 데이터 API를 통해 시세·재무 데이터를 수집합니다.
각 API를 사용하려면 해당 서비스에서 발급받은 인증키를 등록해야 합니다.

  ANTE_DATAGOKR_API_KEY  data.go.kr 공공데이터포털 서비스키
                          발급: https://www.data.go.kr → 마이페이지 → 인증키 발급

  ANTE_DART_API_KEY      금융감독원 DART OpenAPI 인증키
                          발급: https://opendart.fss.or.kr → 인증키 신청

설정:
  ante feed config set ANTE_DATAGOKR_API_KEY your_key_here
  ante feed config set ANTE_DART_API_KEY your_key_here

확인:
  ante feed config check

Docker 환경에서는 환경변수(-e)로도 전달 가능합니다.
──────────────────────────────────────────────────"""


@click.group()
def feed() -> None:
    """DataFeed — 시세·재무 데이터 수집 파이프라인."""


@feed.group("config")
def feed_config() -> None:
    """DataFeed 설정 관리 (API 키 등)."""


@feed_config.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def config_set(ctx: click.Context, key: str, value: str, data_path: str | None) -> None:
    """API 키를 .feed/.env 파일에 저장한다."""
    from ante.feed.config import API_KEYS, FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)

    if key not in API_KEYS:
        supported = ", ".join(API_KEYS)
        fmt.error(
            f"지원하지 않는 키입니다: {key}\n지원 키: {supported}",
            code="CONFIG_UNSUPPORTED_KEY",
        )
        raise SystemExit(1)

    cfg = FeedConfig(data_path)
    try:
        env_path = cfg.set_api_key(key, value)
    except ValueError as e:
        fmt.error(str(e), code="CONFIG_INVALID_VALUE")
        raise SystemExit(1) from e

    fmt.success(
        f"Saved {key} to {env_path}",
        {"key": key, "path": str(env_path)},
    )


@feed_config.command("list")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_READ)
def config_list(ctx: click.Context, data_path: str | None) -> None:
    """등록된 API 키 목록을 마스킹하여 표시한다."""
    from ante.feed.config import FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)
    keys = cfg.list_api_keys()

    if fmt.is_json:
        fmt.output({"keys": keys})
    else:
        click.echo()
        for entry in keys:
            source_info = f"  (source: {entry['source']})" if entry["source"] else ""
            click.echo(f"  {entry['key']:<30} {entry['value']}{source_info}")
        click.echo()


@feed_config.command("check")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_READ)
def config_check(ctx: click.Context, data_path: str | None) -> None:
    """API 키 존재 여부와 유효성을 확인한다.

    설정된 키는 해당 API에 경량 요청을 보내 3-state로 검증한다:
    ✓ 유효 / ✗ 인증 실패 / ? 검증 불가(네트워크). offline/타임아웃은
    검증 불가(unknown)로 graceful 처리한다.
    """
    import asyncio

    from ante.feed.config import FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)
    statuses = asyncio.run(cfg.check_api_keys_with_validation())

    if fmt.is_json:
        fmt.output({"keys": statuses})
    else:
        click.echo()
        click.echo("API Key Status")
        click.echo(_SEPARATOR)
        all_set = True
        for entry in statuses:
            if entry["set"]:
                source_info = f"(source: {entry['source']})"
                valid = entry["valid"]
                if valid is True:
                    verdict = "✓ 유효"
                elif valid is False:
                    verdict = "✗ 인증 실패"
                else:
                    verdict = "? 검증 불가 (네트워크)"
                click.echo(f"  {entry['key']:<30} ✓ 설정됨 {source_info}  {verdict}")
            else:
                click.echo(f"  {entry['key']:<30} ✗ 미설정")
                all_set = False
        click.echo(_SEPARATOR)
        if not all_set:
            click.echo("설정: ante feed config set <KEY> <VALUE>")
        click.echo()


@feed.group("run")
def feed_run() -> None:
    """수집을 1회 실행한다 (backfill / daily)."""


def _build_orchestrator(
    cfg,
):
    """FeedConfig의 API 키를 기반으로 FeedOrchestrator를 조립한다."""
    from ante.feed.pipeline.orchestrator import FeedOrchestrator
    from ante.feed.sources.dart import DARTSource
    from ante.feed.sources.data_go_kr import DataGoKrSource

    api_keys = cfg.load_api_keys()

    data_go_kr_source = None
    dart_source = None

    datagokr_key = api_keys.get("ANTE_DATAGOKR_API_KEY")
    if datagokr_key:
        data_go_kr_source = DataGoKrSource(api_key=datagokr_key)

    dart_key = api_keys.get("ANTE_DART_API_KEY")
    if dart_key:
        dart_source = DARTSource(api_key=dart_key)

    return FeedOrchestrator(
        data_go_kr_source=data_go_kr_source,
        dart_source=dart_source,
    )


def _ensure_initialized(
    cfg,
    fmt,
    data_path: str,
) -> bool:
    """초기화 상태를 확인하고 미초기화 시 에러를 출력한다."""
    if not cfg.is_initialized():
        fmt.error(
            f"DataFeed가 초기화되지 않았습니다. 먼저 실행: ante feed init {data_path}",
            "NOT_INITIALIZED",
        )
        return False
    return True


@feed_run.command("backfill")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.option(
    "--since", default=None, help="수집 시작일 (YYYY-MM-DD, config 기본값 오버라이드)"
)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def run_backfill(
    ctx: click.Context,
    data_path: str | None,
    since: str | None,
) -> None:
    """과거 데이터를 1회 수집한다 (backfill)."""
    import asyncio
    from pathlib import Path

    from ante.feed.cli_output import format_backfill_result
    from ante.feed.config import FeedConfig
    from ante.feed.pipeline.backfill_runner import (
        BACKFILL_DATE_ERROR_CODES,
        CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
        validate_backfill_since,
    )

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    if since is not None:
        _validate_iso_date(since, "--since", fmt)

    if since is not None:
        _parsed, since_err = validate_backfill_since(since)
        if since_err is not None and since_err.get("code") == (
            CONFIG_ERROR_CODE_INVALID_DATE_RANGE
        ):
            fmt.error(
                f"잘못된 --since 날짜: {since_err['error']}",
                code=CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
            )
            raise SystemExit(1)

    config = cfg.load_config()
    _validate_and_apply_feed_config(config, fmt)

    if since is not None:
        schedule = config.setdefault("schedule", {})
        if isinstance(schedule, dict):
            schedule["backfill_since"] = since

    orchestrator = _build_orchestrator(cfg)

    result = asyncio.run(
        orchestrator.run_backfill(
            data_path=Path(data_path),
            config=config,
        )
    )

    for entry in result.config_errors:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        if code in BACKFILL_DATE_ERROR_CODES:
            fmt.error(str(entry.get("error", "")), code=str(code))
            raise SystemExit(1)

    format_backfill_result(result, fmt)


@feed_run.command("daily")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.option(
    "--date", "target_date", default=None, help="수집 대상일 (YYYY-MM-DD, 기본값: 어제)"
)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def run_daily(
    ctx: click.Context,
    data_path: str | None,
    target_date: str | None,
) -> None:
    """어제(또는 지정일) 데이터를 1회 수집한다 (daily)."""
    import asyncio
    from pathlib import Path

    from ante.feed.cli_output import format_daily_result
    from ante.feed.config import FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    if target_date is not None:
        _validate_iso_date(target_date, "--date", fmt)

    config = cfg.load_config()
    _validate_and_apply_feed_config(config, fmt)

    orchestrator = _build_orchestrator(cfg)

    result = asyncio.run(
        orchestrator.run_daily(
            data_path=Path(data_path),
            config=config,
            target_date=target_date,
        )
    )

    format_daily_result(result, fmt)


@feed.command("start")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def feed_start(ctx: click.Context, data_path: str | None) -> None:
    """내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다."""
    import asyncio

    from ante.feed.cli_scheduler import run_scheduler_loop
    from ante.feed.config import FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    config = cfg.load_config()
    _validate_and_apply_feed_config(config, fmt)
    nice_value = _validate_nice_value(config, fmt)
    schedule = config.get("schedule", {})
    daily_at = (
        schedule.get("daily_at", "16:00") if isinstance(schedule, dict) else "16:00"
    )
    backfill_at = (
        schedule.get("backfill_at", "01:00") if isinstance(schedule, dict) else "01:00"
    )

    orchestrator = _build_orchestrator(cfg)

    _apply_process_nice(nice_value)

    try:
        asyncio.run(
            run_scheduler_loop(
                orchestrator=orchestrator,
                data_path=data_path,
                config=config,
                daily_at=daily_at,
                backfill_at=backfill_at,
            )
        )
    except ValueError as exc:
        fmt.error(  # type: ignore[attr-defined]
            f"스케줄 시간 설정이 올바르지 않습니다: {exc}",
            code="CLI_INVALID_SCHEDULE_TIME",
        )
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        click.echo("\nDataFeed 스케줄러 종료")


@feed.command("init")
@click.argument("data_path", required=False, default=None)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def feed_init(ctx: click.Context, data_path: str | None) -> None:
    """DataFeed 운영 디렉토리를 초기화한다."""
    from ante.feed.config import FeedConfig

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)
    created = cfg.init()

    if fmt.is_json:
        fmt.output({"created": created, "data_path": data_path})
    else:
        click.echo()
        for path in created:
            click.echo(f"Created {path}")
        click.echo()
        click.echo(_API_KEY_GUIDE)


@feed.command("status")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_READ)
def feed_status(ctx: click.Context, data_path: str | None) -> None:
    """수집 상태를 조회한다."""

    from ante.feed.config import FeedConfig
    from ante.feed.report.generator import ReportGenerator

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not cfg.is_initialized():
        if fmt.is_json:
            fmt.output({"initialized": False, "message": "init 필요"})
        else:
            click.echo("DataFeed가 초기화되지 않았습니다.")
            click.echo(f"초기화: ante feed init {data_path}")
        return

    checkpoints = _load_checkpoints(cfg.feed_dir)

    report_gen = ReportGenerator(cfg.feed_dir)
    latest_report = _load_latest_report(report_gen)

    api_keys = cfg.check_api_keys()

    if fmt.is_json:
        fmt.output(
            {
                "initialized": True,
                "feed_dir": str(cfg.feed_dir),
                "checkpoints": checkpoints,
                "latest_report": latest_report,
                "api_keys": api_keys,
            }
        )
    else:
        _echo_status_text(cfg, checkpoints, latest_report, api_keys)


def _echo_status_text(
    cfg: object,
    checkpoints: list[dict[str, str]],
    latest_report: dict | None,
    api_keys: list[dict],
) -> None:
    """feed status의 텍스트 출력을 수행한다."""
    click.echo()
    click.echo(f"DataFeed Status ({cfg.feed_dir})")  # type: ignore[attr-defined]
    click.echo("═" * 50)

    _echo_checkpoints_section(checkpoints)
    _echo_report_section(latest_report)
    _echo_api_keys_section(api_keys)

    click.echo()


def _echo_checkpoints_section(checkpoints: list[dict[str, str]]) -> None:
    """체크포인트 섹션을 출력한다."""
    click.echo()
    click.echo("Checkpoints")
    click.echo(_SEPARATOR)
    if checkpoints:
        for cp in checkpoints:
            click.echo(
                f"  {cp['source']}/{cp['data_type']:<16}"
                f" last_date: {cp['last_date']}"
                f"  (updated: {cp['updated_at']})"
            )
    else:
        click.echo("  (체크포인트 없음 — 아직 수집을 실행하지 않았습니다)")


def _echo_report_section(latest_report: dict | None) -> None:
    """최근 리포트 섹션을 출력한다."""
    click.echo()
    click.echo("Latest Report")
    click.echo(_SEPARATOR)
    if latest_report:
        summary = latest_report.get("summary", {})
        failures_total = summary.get(
            "failures_total", len(latest_report.get("failures", []))
        )
        warnings_total = summary.get(
            "warnings_total", len(latest_report.get("warnings", []))
        )
        click.echo(f"  mode: {latest_report.get('mode', '?')}")
        click.echo(f"  date: {latest_report.get('target_date', '?')}")
        click.echo(
            f"  result: {summary.get('symbols_success', 0)} success"
            f" / {summary.get('symbols_failed', 0)} failed"
            f" / {failures_total} total failures"
            f" / {warnings_total} warnings"
        )
        click.echo(f"  rows: {summary.get('rows_written', 0)}")
    else:
        click.echo("  (리포트 없음 — 아직 수집을 실행하지 않았습니다)")


def _echo_api_keys_section(api_keys: list[dict]) -> None:
    """API 키 섹션을 출력한다."""
    click.echo()
    click.echo("API Keys")
    click.echo(_SEPARATOR)
    for entry in api_keys:
        if entry["set"]:
            source_info = f"(source: {entry['source']})"
            click.echo(f"  {entry['key']:<30} ✓ 설정됨 {source_info}")
        else:
            click.echo(f"  {entry['key']:<30} ✗ 미설정")


def _load_checkpoints(feed_dir: pathlib.Path) -> list[dict[str, str]]:
    """체크포인트 디렉토리에서 모든 체크포인트를 로드한다."""
    import json

    from ante.feed.pipeline.checkpoint import CHECKPOINT_DIR

    checkpoint_dir = feed_dir / CHECKPOINT_DIR
    if not checkpoint_dir.exists():
        return []

    results: list[dict[str, str]] = []
    for cp_file in sorted(checkpoint_dir.glob("*.json")):
        try:
            data: dict[str, str] = json.loads(cp_file.read_text(encoding="utf-8"))
            results.append(
                {
                    "source": data.get("source", "?"),
                    "data_type": data.get("data_type", "?"),
                    "last_date": data.get("last_date", "?"),
                    "updated_at": data.get("updated_at", "?"),
                }
            )
        except (json.JSONDecodeError, OSError):
            logger.warning("체크포인트 파일 읽기 실패: %s", cp_file)
    return results


def _load_latest_report(
    report_gen: ReportGenerator,
) -> dict | None:
    """최근 리포트 1건을 로드한다."""
    import json

    reports = report_gen.list_reports(limit=1)
    if not reports:
        return None

    try:
        return json.loads(reports[0].read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        logger.warning("리포트 파일 읽기 실패: %s", reports[0])
        return None


@feed.command("inject")
@click.argument("path", type=click.Path(exists=True))
@click.option("--symbol", required=True, help="종목 코드 (6자리)")
@click.option("--timeframe", default="1d", help="타임프레임 (기본값: 1d)")
@click.option("--source", default="external", help="데이터 소스 식별자")
@click.option("--data-path", default=None, help=_DATA_PATH_HELP)
@click.pass_context
@require_auth
@require_scope(_SCOPE_DATA_WRITE)
def feed_inject(
    ctx: click.Context,
    path: str,
    symbol: str,
    timeframe: str,
    source: str,
    data_path: str | None,
) -> None:
    """외부 CSV 파일에서 과거 데이터를 수동 주입한다."""
    from pathlib import Path as _Path

    from ante.core.market_data_vocab import (
        CANONICAL_TIMEFRAMES,
        is_krx_symbol,
        is_valid_timeframe,
    )
    from ante.data.normalizer import DataNormalizer
    from ante.data.store import ParquetStore
    from ante.feed.injector import FeedInjector

    data_path = resolve_data_path(ctx, data_path)
    fmt = get_formatter(ctx)
    filepath = _Path(path)

    if not is_valid_timeframe(timeframe):
        fmt.error(
            f"유효하지 않은 타임프레임: {timeframe!r}. "
            f"허용 값: {', '.join(CANONICAL_TIMEFRAMES)}",
            code="FEED_INJECT_INVALID_TIMEFRAME",
        )
        raise SystemExit(1)

    if not is_krx_symbol(symbol):
        fmt.error(
            f"유효하지 않은 종목 코드: {symbol!r} (KRX 6자리 숫자)",
            code="FEED_INJECT_INVALID_SYMBOL",
        )
        raise SystemExit(1)

    store = ParquetStore(base_path=_Path(data_path))
    normalizer = DataNormalizer()
    injector = FeedInjector(store=store, normalizer=normalizer)

    try:
        count = injector.inject_csv(
            filepath,
            symbol=symbol,
            timeframe=timeframe,
            source=source,
        )
    except FileNotFoundError as e:
        fmt.error(str(e), "FILE_NOT_FOUND")
        raise SystemExit(1)
    except ValueError as e:
        fmt.error(str(e), "VALIDATION_ERROR")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(
            {
                "rows": count,
                "symbol": symbol,
                "timeframe": timeframe,
                "source": source,
                "path": str(filepath),
            }
        )
    else:
        written = store.resolve_path(symbol, timeframe, exchange="KRX")
        try:
            written_display = written.relative_to(_Path(data_path))
        except ValueError:
            written_display = written
        click.echo()
        click.echo(f"Loaded {count} rows from {filepath.name}")
        click.echo(f"Normalized: source={source}, schema=OHLCV")
        click.echo(f"Validated: {count} rows passed")
        click.echo(f"Written to {written_display}/")
        click.echo()
        click.echo(f"Injected {count} rows for {symbol} ({timeframe})")
