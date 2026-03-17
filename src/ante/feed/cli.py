"""ante feed — DataFeed CLI 커맨드."""

from __future__ import annotations

import logging

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

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

    fmt = get_formatter(ctx)
    cfg = FeedConfig(data_path)

    if not cfg.is_initialized():
        if fmt.is_json:
            fmt.output({"initialized": False, "message": "init 필요"})
        else:
            click.echo("DataFeed가 초기화되지 않았습니다.")
            click.echo(f"초기화: ante feed init {data_path}")
        return

    if fmt.is_json:
        fmt.output({"initialized": True, "feed_dir": str(cfg.feed_dir)})
    else:
        click.echo(f"DataFeed 초기화됨: {cfg.feed_dir}")
        click.echo("(상세 상태 조회는 Phase 2에서 구현 예정)")
