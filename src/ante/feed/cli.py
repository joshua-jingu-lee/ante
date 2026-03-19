"""ante feed — DataFeed CLI 커맨드."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

if TYPE_CHECKING:
    from ante.feed.report.generator import ReportGenerator

logger = logging.getLogger(__name__)

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


# ── config 서브그룹 ──────────────────────────────────────────────────────────


@feed.group("config")
def feed_config() -> None:
    """DataFeed 설정 관리 (API 키 등)."""


@feed_config.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:write")
def config_set(ctx: click.Context, key: str, value: str, data_path: str) -> None:
    """API 키를 .feed/.env 파일에 저장한다."""
    from ante.feed.config import API_KEYS, FeedConfig

    fmt = get_formatter(ctx)

    if key not in API_KEYS:
        supported = ", ".join(API_KEYS)
        click.echo(f"지원하지 않는 키입니다: {key}\n지원 키: {supported}", err=True)
        raise SystemExit(1)

    cfg = FeedConfig(data_path)
    env_path = cfg.set_api_key(key, value)

    fmt.success(
        f"Saved {key} to {env_path}",
        {"key": key, "path": str(env_path)},
    )


@feed_config.command("list")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def config_list(ctx: click.Context, data_path: str) -> None:
    """등록된 API 키 목록을 마스킹하여 표시한다."""
    from ante.feed.config import FeedConfig

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
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def config_check(ctx: click.Context, data_path: str) -> None:
    """API 키 존재 여부를 확인한다."""
    from ante.feed.config import FeedConfig

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)
    statuses = cfg.check_api_keys()

    if fmt.is_json:
        fmt.output({"keys": statuses})
    else:
        click.echo()
        click.echo("API Key Status")
        click.echo("──────────────────────────────────────────────────")
        all_set = True
        for entry in statuses:
            if entry["set"]:
                source_info = f"(source: {entry['source']})"
                click.echo(f"  {entry['key']:<30} ✓ 설정됨 {source_info}")
            else:
                click.echo(f"  {entry['key']:<30} ✗ 미설정")
                all_set = False
        click.echo("──────────────────────────────────────────────────")
        if not all_set:
            click.echo("설정: ante feed config set <KEY> <VALUE>")
        click.echo()


# ── run 서브그룹 ──────────────────────────────────────────────────────────────


@feed.group("run")
def feed_run() -> None:
    """수집을 1회 실행한다 (backfill / daily)."""


def _build_orchestrator(  # noqa: ANN001, ANN201
    cfg,  # FeedConfig
):  # -> FeedOrchestrator
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


def _ensure_initialized(  # noqa: ANN001, ANN201
    cfg,  # FeedConfig
    fmt,  # OutputFormatter
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
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.option(
    "--since", default=None, help="수집 시작일 (YYYY-MM-DD, config 기본값 오버라이드)"
)
@click.option("--until", default=None, help="수집 종료일 (YYYY-MM-DD, 기본값: 오늘)")
@click.pass_context
@require_auth
@require_scope("data:write")
def run_backfill(
    ctx: click.Context,
    data_path: str,
    since: str | None,
    until: str | None,
) -> None:
    """과거 데이터를 1회 수집한다 (backfill)."""
    import asyncio
    from pathlib import Path

    from ante.feed.cli_output import format_backfill_result
    from ante.feed.config import FeedConfig

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    config = cfg.load_config()

    # CLI 옵션으로 schedule 오버라이드
    if since is not None:
        config.setdefault("schedule", {})["backfill_since"] = since  # type: ignore[union-attr]

    orchestrator = _build_orchestrator(cfg)

    result = asyncio.run(
        orchestrator.run_backfill(
            data_path=Path(data_path),
            config=config,
        )
    )

    format_backfill_result(result, fmt)


@feed_run.command("daily")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.option(
    "--date", "target_date", default=None, help="수집 대상일 (YYYY-MM-DD, 기본값: 어제)"
)
@click.pass_context
@require_auth
@require_scope("data:write")
def run_daily(
    ctx: click.Context,
    data_path: str,
    target_date: str | None,
) -> None:
    """어제(또는 지정일) 데이터를 1회 수집한다 (daily)."""
    import asyncio
    from pathlib import Path

    from ante.feed.cli_output import format_daily_result
    from ante.feed.config import FeedConfig

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    config = cfg.load_config()

    orchestrator = _build_orchestrator(cfg)

    # --date 옵션이 있으면 generate_daily_date를 패치
    if target_date is not None:
        import ante.feed.pipeline.scheduler as _sched

        _original_generate = _sched.generate_daily_date

        def _override(reference: object = None) -> str:
            return target_date  # type: ignore[return-value]

        _sched.generate_daily_date = _override  # type: ignore[assignment]
        try:
            result = asyncio.run(
                orchestrator.run_daily(
                    data_path=Path(data_path),
                    config=config,
                )
            )
        finally:
            _sched.generate_daily_date = _original_generate
    else:
        result = asyncio.run(
            orchestrator.run_daily(
                data_path=Path(data_path),
                config=config,
            )
        )

    format_daily_result(result, fmt)


# ── start (상주 스케줄러) ─────────────────────────────────────────────────────


@feed.command("start")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:write")
def feed_start(ctx: click.Context, data_path: str) -> None:
    """내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다."""
    import asyncio

    from ante.feed.cli_scheduler import run_scheduler_loop
    from ante.feed.config import FeedConfig

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not _ensure_initialized(cfg, fmt, data_path):
        raise SystemExit(1)

    config = cfg.load_config()
    schedule = config.get("schedule", {})
    daily_at = (
        schedule.get("daily_at", "16:00") if isinstance(schedule, dict) else "16:00"
    )
    backfill_at = (
        schedule.get("backfill_at", "01:00") if isinstance(schedule, dict) else "01:00"
    )

    orchestrator = _build_orchestrator(cfg)

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
    except KeyboardInterrupt:
        click.echo("\nDataFeed 스케줄러 종료")


# ── init ─────────────────────────────────────────────────────────────────────


@feed.command("init")
@click.argument("data_path", default="data/")
@click.pass_context
@require_auth
@require_scope("data:write")
def feed_init(ctx: click.Context, data_path: str) -> None:
    """DataFeed 운영 디렉토리를 초기화한다."""
    from ante.feed.config import FeedConfig

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


# ── status ────────────────────────────────────────────────────────────────────


@feed.command("status")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:read")
def feed_status(ctx: click.Context, data_path: str) -> None:
    """수집 상태를 조회한다."""

    from ante.feed.config import FeedConfig
    from ante.feed.report.generator import ReportGenerator

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not cfg.is_initialized():
        if fmt.is_json:
            fmt.output({"initialized": False, "message": "init 필요"})
        else:
            click.echo("DataFeed가 초기화되지 않았습니다.")
            click.echo(f"초기화: ante feed init {data_path}")
        return

    # 1. 체크포인트 로드
    checkpoints = _load_checkpoints(cfg.feed_dir)

    # 2. 최근 리포트 1건 로드
    report_gen = ReportGenerator(cfg.feed_dir)
    latest_report = _load_latest_report(report_gen)

    # 3. API 키 상태 확인
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
    cfg: object,  # FeedConfig
    checkpoints: list[dict[str, str]],
    latest_report: dict | None,
    api_keys: list[dict],
) -> None:
    """feed status의 텍스트 출력을 수행한다."""
    click.echo()
    click.echo(f"DataFeed Status ({cfg.feed_dir})")  # type: ignore[attr-defined]
    click.echo("══════════════════════════════════════════════════")

    _echo_checkpoints_section(checkpoints)
    _echo_report_section(latest_report)
    _echo_api_keys_section(api_keys)

    click.echo()


def _echo_checkpoints_section(checkpoints: list[dict[str, str]]) -> None:
    """체크포인트 섹션을 출력한다."""
    click.echo()
    click.echo("Checkpoints")
    click.echo("──────────────────────────────────────────────────")
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
    click.echo("──────────────────────────────────────────────────")
    if latest_report:
        summary = latest_report.get("summary", {})
        click.echo(f"  mode: {latest_report.get('mode', '?')}")
        click.echo(f"  date: {latest_report.get('target_date', '?')}")
        click.echo(
            f"  result: {summary.get('symbols_success', 0)} success"
            f" / {summary.get('symbols_failed', 0)} failed"
            f" / {len(latest_report.get('warnings', []))} warnings"
        )
        click.echo(f"  rows: {summary.get('rows_written', 0)}")
    else:
        click.echo("  (리포트 없음 — 아직 수집을 실행하지 않았습니다)")


def _echo_api_keys_section(api_keys: list[dict]) -> None:
    """API 키 섹션을 출력한다."""
    click.echo()
    click.echo("API Keys")
    click.echo("──────────────────────────────────────────────────")
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


# ── inject ───────────────────────────────────────────────────────────────────


@feed.command("inject")
@click.argument("path", type=click.Path(exists=True))
@click.option("--symbol", required=True, help="종목 코드 (6자리)")
@click.option("--timeframe", default="1d", help="타임프레임 (기본값: 1d)")
@click.option("--source", default="external", help="데이터 소스 식별자")
@click.option("--data-path", default="data/", help="데이터 저장소 경로")
@click.pass_context
@require_auth
@require_scope("data:write")
def feed_inject(
    ctx: click.Context,
    path: str,
    symbol: str,
    timeframe: str,
    source: str,
    data_path: str,
) -> None:
    """외부 CSV 파일에서 과거 데이터를 수동 주입한다."""
    import asyncio
    from pathlib import Path as _Path

    from ante.data.normalizer import DataNormalizer
    from ante.data.store import ParquetStore
    from ante.feed.injector import FeedInjector

    fmt = get_formatter(ctx)
    filepath = _Path(path)

    store = ParquetStore(base_path=_Path(data_path))
    normalizer = DataNormalizer()
    injector = FeedInjector(store=store, normalizer=normalizer)

    try:
        count = asyncio.run(
            injector.inject_csv(
                filepath,
                symbol=symbol,
                timeframe=timeframe,
                source=source,
            )
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
        click.echo()
        click.echo(f"Loaded {count} rows from {filepath.name}")
        click.echo(f"Normalized: source={source}, schema=OHLCV")
        click.echo(f"Validated: {count} rows passed")
        click.echo(f"Written to ohlcv/krx/{timeframe}/{symbol}/")
        click.echo()
        click.echo(f"Injected {count} rows for {symbol} ({timeframe})")
