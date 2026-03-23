"""ante strategy — 전략 관리 커맨드."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def strategy() -> None:
    """전략 관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_registry():  # noqa: ANN202
    from ante.core.database import Database
    from ante.strategy.registry import StrategyRegistry

    db = Database("db/ante.db")
    await db.connect()
    registry = StrategyRegistry(db)
    return registry, db


@strategy.command()
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
@require_auth
@require_scope("strategy:write")
def validate(ctx: click.Context, path: str) -> None:
    """전략 파일 정적 검증 (AST 기반)."""
    from ante.strategy.validator import StrategyValidator

    fmt = get_formatter(ctx)
    validator = StrategyValidator()
    result = validator.validate(Path(path))

    data = {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }

    if result.valid:
        fmt.success(f"Strategy validation passed: {path}", data)
    else:
        fmt.error(f"Validation failed: {path}")
        if not fmt.is_json:
            for err in result.errors:
                click.echo(f"  - {err}", err=True)
            for warn in result.warnings:
                click.echo(f"  [warn] {warn}", err=True)
        else:
            fmt.output(data)


@strategy.command("submit")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
@require_auth
@require_scope("strategy:write")
def submit(ctx: click.Context, path: str) -> None:
    """전략 제출 (검증 -> 로드 테스트 -> Registry 등록)."""
    from ante.strategy.exceptions import StrategyError, StrategyLoadError
    from ante.strategy.loader import StrategyLoader
    from ante.strategy.validator import StrategyValidator

    fmt = get_formatter(ctx)
    filepath = Path(path)

    # 1. 정적 검증
    validator = StrategyValidator()
    validation = validator.validate(filepath)

    if not validation.valid:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "validate",
                    "errors": validation.errors,
                }
            )
        else:
            fmt.error(f"Validation failed: {path}")
            for err in validation.errors:
                click.echo(f"  - {err}", err=True)
        raise SystemExit(1)

    if validation.warnings and not fmt.is_json:
        for warn in validation.warnings:
            click.echo(f"  [warn] {warn}", err=True)

    # 2. 로드 테스트 — Strategy 클래스 import + meta 추출
    try:
        strategy_cls = StrategyLoader.load(filepath)
    except StrategyLoadError as e:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "load",
                    "error": str(e),
                }
            )
        else:
            fmt.error(f"Load test failed: {e}")
        raise SystemExit(1)

    meta = strategy_cls.meta

    # 3. Registry 등록
    async def _register() -> dict:
        registry, db = await _create_registry()
        try:
            await registry.initialize()
            record = await registry.register(
                filepath=filepath,
                meta=meta,
                warnings=validation.warnings,
            )
            return {
                "submitted": True,
                "strategy_id": record.strategy_id,
                "name": record.name,
                "version": record.version,
                "description": record.description,
                "author": record.author,
                "filepath": str(record.filepath),
                "registered_at": record.registered_at.isoformat(),
                "validation_warnings": record.validation_warnings,
            }
        finally:
            await db.close()

    try:
        result = _run(_register())
    except StrategyError as e:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "register",
                    "error": str(e),
                }
            )
        else:
            fmt.error(str(e))
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.success(
            f"전략 등록 완료: {result['strategy_id']}",
            result,
        )


@strategy.command("list")
@click.option(
    "--status", default=None, help="상태 필터 (registered/active/inactive/archived)"
)
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_list(ctx: click.Context, status: str | None) -> None:
    """등록된 전략 목록 조회."""
    fmt = get_formatter(ctx)

    async def _list() -> list[dict]:
        from ante.strategy.registry import StrategyStatus

        registry, db = await _create_registry()
        try:
            filter_status = StrategyStatus(status) if status else None
            records = await registry.list_strategies(status=filter_status)
            return [
                {
                    "strategy_id": r.strategy_id,
                    "name": r.name,
                    "version": r.version,
                    "status": r.status.value,
                    "description": r.description,
                    "author": r.author,
                    "registered_at": r.registered_at.isoformat(),
                }
                for r in records
            ]
        finally:
            await db.close()

    rows = _run(_list())

    if not rows:
        fmt.output({"message": "등록된 전략 없음", "strategies": []})
        return

    if fmt.is_json:
        fmt.output({"strategies": rows})
    else:
        fmt.table(
            rows,
            ["strategy_id", "name", "version", "status", "author"],
        )


@strategy.command("info")
@click.argument("name")
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_info(ctx: click.Context, name: str) -> None:
    """전략 상세 정보 조회 (메타데이터 + 파라미터)."""
    fmt = get_formatter(ctx)

    async def _info() -> dict | None:
        registry, db = await _create_registry()
        try:
            records = await registry.get_by_name(name)
            if not records:
                return None

            # 최신 버전 사용
            record = records[0]

            result: dict = {
                "strategy_id": record.strategy_id,
                "name": record.name,
                "version": record.version,
                "status": record.status.value,
                "description": record.description,
                "author": record.author,
                "filepath": record.filepath,
                "registered_at": record.registered_at.isoformat(),
                "validation_warnings": record.validation_warnings,
            }

            # 전략 파일에서 파라미터 정보 로드 시도
            params = _load_strategy_params(record.filepath)
            if params is not None:
                result["params"] = params["params"]
                result["param_schema"] = params["param_schema"]

            # 동일 이름의 다른 버전 목록
            if len(records) > 1:
                result["other_versions"] = [
                    {
                        "version": r.version,
                        "strategy_id": r.strategy_id,
                        "status": r.status.value,
                    }
                    for r in records[1:]
                ]

            return result
        finally:
            await db.close()

    result = _run(_info())

    if result is None:
        fmt.error(f"전략을 찾을 수 없습니다: {name}")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        _print_info_text(result)


def _print_info_text(result: dict) -> None:
    """전략 상세 정보 텍스트 출력."""
    click.echo(f"  {'이름':15s}: {result['name']}")
    click.echo(f"  {'버전':15s}: {result['version']}")
    click.echo(f"  {'상태':15s}: {result['status']}")
    click.echo(f"  {'설명':15s}: {result['description']}")
    click.echo(f"  {'작성자':15s}: {result['author']}")
    click.echo(f"  {'파일 경로':15s}: {result['filepath']}")
    click.echo(f"  {'등록일':15s}: {result['registered_at']}")
    _print_info_warnings(result.get("validation_warnings"))
    _print_info_params(result.get("params"), result.get("param_schema", {}))
    _print_info_versions(result.get("other_versions"))


def _print_info_warnings(warnings: list[str] | None) -> None:
    """검증 경고 섹션 출력."""
    if not warnings:
        return
    click.echo(f"  {'검증 경고':15s}:")
    for w in warnings:
        click.echo(f"    - {w}")


def _print_info_params(params: dict | None, schema: dict) -> None:
    """파라미터 섹션 출력."""
    if not params:
        return
    click.echo(f"  {'파라미터':15s}:")
    for key, value in params.items():
        desc = schema.get(key, "")
        line = f"    {key} = {value}"
        if desc:
            line += f"  ({desc})"
        click.echo(line)


def _print_info_versions(versions: list[dict] | None) -> None:
    """다른 버전 목록 섹션 출력."""
    if not versions:
        return
    click.echo(f"  {'다른 버전':15s}:")
    for v in versions:
        click.echo(f"    - {v['strategy_id']} ({v['status']})")


def _load_strategy_params(filepath: str) -> dict | None:
    """전략 파일에서 파라미터 정보를 로드. 실패 시 None."""
    try:
        from ante.strategy.loader import StrategyLoader

        path = Path(filepath)
        if not path.exists():
            return None
        cls = StrategyLoader.load(path)
        # 더미 컨텍스트로 인스턴스 생성하여 파라미터 조회
        instance = cls(ctx=None)
        return {
            "params": instance.get_params(),
            "param_schema": instance.get_param_schema(),
        }
    except Exception:
        return None


@strategy.command("performance")
@click.argument("name")
@click.option("--account-id", default=None, help="계좌 ID (미지정 시 'default')")
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_performance(ctx: click.Context, name: str, account_id: str | None) -> None:
    """전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용)."""
    fmt = get_formatter(ctx)

    async def _perf() -> dict | None:
        from ante.core.database import Database
        from ante.strategy.registry import StrategyRegistry
        from ante.trade.performance import PerformanceTracker

        db = Database("db/ante.db")
        await db.connect()
        try:
            registry = StrategyRegistry(db)
            records = await registry.get_by_name(name)
            if not records:
                return None

            tracker = PerformanceTracker(db)
            # 최신 버전의 strategy_id 기준으로 성과 계산
            record = records[0]
            resolved = account_id or "default"
            metrics = await tracker.calculate(
                account_id=resolved, strategy_id=record.name
            )

            return {
                "strategy_name": record.name,
                "strategy_id": record.strategy_id,
                "metrics": asdict(metrics),
            }
        finally:
            await db.close()

    result = _run(_perf())

    if result is None:
        fmt.error(f"전략을 찾을 수 없습니다: {name}")
        raise SystemExit(1)

    metrics = result["metrics"]

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"전략 성과: {result['strategy_name']} ({result['strategy_id']})")
        click.echo(f"  {'총 거래':15s}: {metrics['total_trades']}")
        click.echo(f"  {'승률':15s}: {metrics['win_rate']:.1%}")
        click.echo(f"  {'승리':15s}: {metrics['winning_trades']}")
        click.echo(f"  {'패배':15s}: {metrics['losing_trades']}")
        click.echo(f"  {'총 손익':15s}: {metrics['total_pnl']:,.0f}")
        click.echo(f"  {'순 손익':15s}: {metrics['net_pnl']:,.0f}")
        click.echo(f"  {'총 수수료':15s}: {metrics['total_commission']:,.0f}")
        click.echo(f"  {'평균 수익':15s}: {metrics['avg_profit']:,.0f}")
        click.echo(f"  {'평균 손실':15s}: {metrics['avg_loss']:,.0f}")
        click.echo(f"  {'수익 팩터':15s}: {metrics['profit_factor']:.2f}")
        click.echo(f"  {'MDD':15s}: {metrics['max_drawdown']:.1%}")
        click.echo(f"  {'MDD 금액':15s}: {metrics['max_drawdown_amount']:,.0f}")
        sharpe = metrics["sharpe_ratio"]
        click.echo(
            f"  {'샤프 비율':15s}: {sharpe:.2f}"
            if sharpe is not None
            else f"  {'샤프 비율':15s}: N/A (거래 30건 미만)"
        )
        click.echo(f"  {'활성 일수':15s}: {metrics['active_days']}")
        if metrics.get("first_trade_at"):
            click.echo(f"  {'첫 거래':15s}: {metrics['first_trade_at']}")
        if metrics.get("last_trade_at"):
            click.echo(f"  {'마지막 거래':15s}: {metrics['last_trade_at']}")
