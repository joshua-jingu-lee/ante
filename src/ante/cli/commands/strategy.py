"""ante strategy — 전략 관리 커맨드."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_invalid_account_id
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts.cli_errors import (
    CliStrategyError,
    StrategyInvalidStatusTransitionError,
    StrategyMissingRequiredAccountError,
)
from ante.contracts.error_registry import EXECUTION_ERROR_SPEC
from ante.contracts.helpers import error_spec_for_exception
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.core.database import OperationalError
from ante.strategy.exceptions import (
    StrategyError,
    StrategyLoadError,
    StrategyNotFoundError,
    StrategyValidationError,
)
from ante.strategy.registry import StrategyStatus

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.strategy.registry import StrategyRegistry


@click.group()
def strategy() -> None:
    """전략 관리."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_registry(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[StrategyRegistry, Database]]:
    """CLI 에서 ``StrategyRegistry`` async context manager."""
    from ante.strategy.registry import StrategyRegistry

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_registry requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        registry = StrategyRegistry(db)
        await registry.initialize()
        yield registry, db


@strategy.command()
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
@require_auth
@require_scope("strategy:write")
def validate(ctx: click.Context, path: str) -> CommandResult:
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
        return CommandResult(data=data, message=f"Strategy validation passed: {path}")
    else:
        if fmt.is_json:
            import json as _json

            click.echo(
                _json.dumps(
                    {
                        "status": "error",
                        "code": "STRATEGY_VALIDATION_FAILED",
                        "message": f"Validation failed: {path}",
                        "data": data,
                    },
                    indent=2,
                    default=str,
                    ensure_ascii=False,
                )
            )
        else:
            fmt.error(
                f"Validation failed: {path}",
                code="STRATEGY_VALIDATION_FAILED",
            )
            for err in result.errors:
                click.echo(f"  - {err}", err=True)
            for warn in result.warnings:
                click.echo(f"  [warn] {warn}", err=True)
        raise SystemExit(1)


@strategy.command("submit")
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
@require_auth
@require_scope("strategy:write")
def submit(ctx: click.Context, path: str) -> None:
    """전략 제출 (검증 -> 로드 테스트 -> Registry 등록)."""
    from ante.strategy.base import StrategyMeta
    from ante.strategy.loader import StrategyLoader
    from ante.strategy.validator import StrategyValidator

    fmt = get_formatter(ctx)
    filepath = Path(path)

    validator = StrategyValidator()
    validation = validator.validate(filepath)

    if not validation.valid:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "validate",
                    "code": "STRATEGY_VALIDATION_ERROR",
                    "errors": validation.errors,
                }
            )
        else:
            fmt.error(f"Validation failed: {path}", code="STRATEGY_VALIDATION_ERROR")
            for err in validation.errors:
                click.echo(f"  - {err}", err=True)
        raise SystemExit(1)

    if validation.warnings and not fmt.is_json:
        for warn in validation.warnings:
            click.echo(f"  [warn] {warn}", err=True)

    try:
        strategy_cls = StrategyLoader.load(filepath)
    except StrategyLoadError as e:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "load",
                    "code": "STRATEGY_LOAD_ERROR",
                    "error": str(e),
                }
            )
        else:
            raise StrategyLoadError(f"Load test failed: {e}") from e
        raise SystemExit(1)

    meta = strategy_cls.meta

    if not isinstance(meta, StrategyMeta):
        error_message = (
            f"meta는 StrategyMeta 인스턴스여야 합니다 "
            f"(받은 타입: {type(meta).__name__})"
        )
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "meta_validation",
                    "code": "STRATEGY_VALIDATION_ERROR",
                    "error": error_message,
                }
            )
        else:
            raise StrategyValidationError(
                f"Invalid meta shape: expected StrategyMeta, got {type(meta).__name__}"
            )
        raise SystemExit(1)

    rationale = ""
    risks: list[str] = []
    try:
        instance = strategy_cls(ctx=None)
        rationale = instance.get_rationale()
        risks = instance.get_risks()
    except Exception:
        pass

    async def _register() -> dict[str, Any]:
        async with _create_registry(ctx=ctx) as (registry, _):
            await registry.initialize()
            record = await registry.register(
                filepath=filepath,
                meta=meta,
                warnings=validation.warnings,
                rationale=rationale,
                risks=risks,
            )
            return {
                "submitted": True,
                "strategy_id": record.strategy_id,
                "name": record.name,
                "version": record.version,
                "description": record.description,
                "author_name": record.author_name,
                "author_id": record.author_id,
                "filepath": str(record.filepath),
                "registered_at": record.registered_at.isoformat(),
                "validation_warnings": record.validation_warnings,
            }

    try:
        result = _run(_register())
    except StrategyError as e:
        if fmt.is_json:
            fmt.output(
                {
                    "submitted": False,
                    "stage": "register",
                    "code": getattr(e, "code", "STRATEGY_ERROR"),
                    "error": str(e),
                }
            )
        elif error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        else:
            raise CliStrategyError(str(e)) from e
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.success(
            f"전략 등록 완료: {result['strategy_id']}",
            result,
        )


@strategy.command("list")
@click.option("--status", default=None, help="상태 필터 (registered/adopted/archived)")
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_list(ctx: click.Context, status: str | None) -> None:
    """등록된 전략 목록 조회."""
    fmt = get_formatter(ctx)

    valid_statuses = {s.value for s in StrategyStatus}
    if status is not None and status not in valid_statuses:
        raise StrategyValidationError(
            f"잘못된 status 값: {status!r}. 허용값: {sorted(valid_statuses)}"
        )

    async def _list() -> list[dict[str, Any]]:
        async with _create_registry(ctx=ctx) as (registry, _):
            filter_status = StrategyStatus(status) if status else None
            records = await registry.list_strategies(status=filter_status)
            return [
                {
                    "strategy_id": r.strategy_id,
                    "name": r.name,
                    "version": r.version,
                    "status": r.status.value,
                    "description": r.description,
                    "author_name": r.author_name,
                    "author_id": r.author_id,
                    "registered_at": r.registered_at.isoformat(),
                }
                for r in records
            ]

    try:
        rows = _run(_list())
    except click.ClickException:
        raise
    except OperationalError as e:
        if "no such table" in str(e).lower():
            rows = []
        else:
            raise CliStrategyError(str(e)) from e
    except Exception as e:
        raise CliStrategyError(str(e)) from e

    if not rows:
        fmt.output({"message": "등록된 전략 없음", "strategies": []})
        return

    if fmt.is_json:
        fmt.output({"strategies": rows})
    else:
        fmt.table(
            rows,
            ["strategy_id", "name", "version", "status", "author_name", "author_id"],
        )


@strategy.command("set-status")
@click.argument("strategy_id")
@click.option(
    "--status",
    required=True,
    type=click.Choice(["adopted", "archived"]),
    help="변경할 전략 상태",
)
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:write")
def strategy_set_status(ctx: click.Context, strategy_id: str, status: str) -> None:
    """전략 상태 변경."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    target_status = StrategyStatus(status)

    async def _set_status() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "strategy.set_status",
                {"strategy_id": strategy_id, "status": target_status.value},
                actor=actor,
            )

        async with _create_registry(ctx=ctx) as (registry, _):
            await registry.initialize()
            await registry.update_status(strategy_id, target_status)
            record = await registry.get(strategy_id)
            return {
                "strategy_id": strategy_id,
                "status": target_status.value,
                "name": record.name if record else "",
                "version": record.version if record else "",
            }

    try:
        result = _run(_set_status())
    except (
        click.ClickException,
        IPCServerNotRunningError,
        IPCClientTimeoutError,
        IPCRemoteError,
    ):
        raise
    except ValueError as e:
        raise StrategyInvalidStatusTransitionError(str(e)) from e
    except Exception as e:
        if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        raise CliStrategyError(str(e)) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.success(f"전략 상태 변경 완료: {strategy_id} -> {status}", result)


@strategy.command("info")
@click.argument("name")
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_info(ctx: click.Context, name: str) -> None:
    """전략 상세 정보 조회 (메타데이터 + 파라미터)."""
    fmt = get_formatter(ctx)

    async def _info() -> dict[str, Any] | None:
        async with _create_registry(ctx=ctx) as (registry, _):
            records = await registry.get_by_name(name)
            if not records:
                return None

            record = records[0]

            result: dict[str, Any] = {
                "strategy_id": record.strategy_id,
                "name": record.name,
                "version": record.version,
                "status": record.status.value,
                "description": record.description,
                "author_name": record.author_name,
                "author_id": record.author_id,
                "filepath": record.filepath,
                "registered_at": record.registered_at.isoformat(),
                "validation_warnings": record.validation_warnings,
            }

            params = _load_strategy_params(record.filepath)
            if params is not None:
                result["params"] = params["params"]
                result["param_schema"] = params["param_schema"]
                if params.get("rationale"):
                    result["rationale"] = params["rationale"]
                if params.get("risks"):
                    result["risks"] = params["risks"]

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

    try:
        result = _run(_info())
    except OperationalError as e:
        if "no such table" in str(e).lower():
            result = None
        else:
            raise CliStrategyError(str(e)) from e
    except Exception as e:
        raise CliStrategyError(str(e)) from e

    if result is None:
        raise StrategyNotFoundError(f"전략을 찾을 수 없습니다: {name}")

    if fmt.is_json:
        fmt.output(result)
    else:
        _print_info_text(result)


def _print_info_text(result: dict[str, Any]) -> None:
    """전략 상세 정보 텍스트 출력."""
    click.echo(f"  {'이름':15s}: {result['name']}")
    click.echo(f"  {'버전':15s}: {result['version']}")
    click.echo(f"  {'상태':15s}: {result['status']}")
    click.echo(f"  {'설명':15s}: {result['description']}")
    click.echo(f"  {'작성자':15s}: {result['author_name']}")
    click.echo(f"  {'작성자 ID':15s}: {result['author_id']}")
    click.echo(f"  {'파일 경로':15s}: {result['filepath']}")
    click.echo(f"  {'등록일':15s}: {result['registered_at']}")
    _print_info_warnings(result.get("validation_warnings"))
    _print_info_rationale(result.get("rationale"))
    _print_info_risks(result.get("risks"))
    _print_info_params(result.get("params"), result.get("param_schema", {}))
    _print_info_versions(result.get("other_versions"))


def _print_info_warnings(warnings: list[str] | None) -> None:
    """검증 경고 섹션 출력."""
    if not warnings:
        return
    click.echo(f"  {'검증 경고':15s}:")
    for w in warnings:
        click.echo(f"    - {w}")


def _print_info_rationale(rationale: str | None) -> None:
    """투자 근거 섹션 출력."""
    if not rationale:
        return
    click.echo(f"  {'투자 근거':15s}: {rationale}")


def _print_info_risks(risks: list[str] | None) -> None:
    """리스크 섹션 출력."""
    if not risks:
        return
    click.echo(f"  {'리스크':15s}:")
    for r in risks:
        click.echo(f"    - {r}")


def _print_info_params(params: dict[str, Any] | None, schema: dict[str, Any]) -> None:
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


def _print_info_versions(versions: list[dict[str, Any]] | None) -> None:
    """다른 버전 목록 섹션 출력."""
    if not versions:
        return
    click.echo(f"  {'다른 버전':15s}:")
    for v in versions:
        click.echo(f"    - {v['strategy_id']} ({v['status']})")


def _load_strategy_params(filepath: str) -> dict[str, Any] | None:
    """전략 파일에서 파라미터 정보를 로드. 실패 시 None."""
    try:
        from ante.strategy.loader import StrategyLoader

        path = Path(filepath)
        if not path.exists():
            return None
        cls = StrategyLoader.load(path)
        instance = cls(ctx=None)
        return {
            "params": instance.get_params(),
            "param_schema": instance.get_param_schema(),
            "rationale": instance.get_rationale(),
            "risks": instance.get_risks(),
        }
    except Exception:
        return None


@strategy.command("summary")
@click.argument("strategy_id")
@click.option(
    "--period",
    required=True,
    type=click.Choice(["daily", "weekly", "monthly"]),
    help="집계 기간",
)
@format_option
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_summary(ctx: click.Context, strategy_id: str, period: str) -> None:
    """전략 기간별 성과 집계 (전략 전체 거래, absolute 지표).

    전략의 ``trades.strategy_id`` (거래 시점 전략 귀속 durable key)로
    해당 전략의 **모든 거래**를 집계한다. 같은 전략을 여러 봇/여러 계좌에서
    운용해도 전체가 합산되며, 삭제된 봇의 과거 거래도 포함되고 봇의 이후
    전략 변경으로 다른 전략에 귀속된 거래는 오염되지 않는다.

    지표는 ``realized_pnl``/``trade_count``/``win_rate`` 의 **기간별 절대
    집계**다. ``strategy performance`` (계좌별 portfolio-relative) 와 달리
    account-scoped 가 아니므로 여러 계좌·통화의 거래가 섞일 수 있다
    (다중 통화 운용 시 ``realized_pnl`` 은 통화가 혼합될 수 있다).
    """
    fmt = get_formatter(ctx)

    async def _summary() -> dict[str, Any] | None:
        from ante.trade.performance import PerformanceTracker

        async with _create_registry(ctx=ctx) as (registry, db):
            await registry.initialize()
            record = await registry.get(strategy_id)
            if record is None:
                return None

            tracker = PerformanceTracker(db)
            if period == "daily":
                daily_summaries = await tracker.get_daily_summary(
                    strategy_id=strategy_id
                )
                items = [asdict(s) for s in daily_summaries]
            elif period == "weekly":
                weekly_summaries = await tracker.get_weekly_summary(
                    strategy_id=strategy_id
                )
                items = [
                    {**asdict(s), "week_label": s.week_label} for s in weekly_summaries
                ]
            else:
                monthly_summaries = await tracker.get_monthly_summary(
                    strategy_id=strategy_id
                )
                items = [asdict(s) for s in monthly_summaries]

            return {
                "strategy_id": strategy_id,
                "period": period,
                "items": items,
            }

    try:
        result = _run(_summary())
    except Exception as e:
        raise CliStrategyError(str(e)) from e

    if result is None:
        raise StrategyNotFoundError(f"전략을 찾을 수 없습니다: {strategy_id}")

    if fmt.is_json:
        fmt.output(result)
    else:
        rows = result["items"]
        if not rows:
            fmt.output({"message": "성과 집계 없음", "items": []})
            return
        columns = {
            "daily": ["date", "realized_pnl", "trade_count", "win_rate"],
            "weekly": [
                "week_start",
                "week_end",
                "week_label",
                "realized_pnl",
                "trade_count",
                "win_rate",
            ],
            "monthly": ["year", "month", "realized_pnl", "trade_count", "win_rate"],
        }[period]
        fmt.table(rows, columns)


@strategy.command("performance")
@click.argument("name")
@click.option(
    "--account-id",
    default=None,
    help="계좌 ID (필수, 미지정 시 STRATEGY_MISSING_REQUIRED_ACCOUNT 에러)",
)
@click.pass_context
@require_auth
@require_scope("strategy:read")
def strategy_performance(ctx: click.Context, name: str, account_id: str | None) -> None:
    """전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용).

    --account-id 옵션은 필수다. 미지정 시 fallback 없이 명시적으로 실패한다
    (Edge resolver 정렬, query 정책 일관).
    """
    fmt = get_formatter(ctx)

    if account_id is None:
        raise StrategyMissingRequiredAccountError(
            "계좌 ID를 지정해야 합니다. --account-id <id> 옵션을 사용하세요."
        )

    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.strategy.performance"
    )

    async def _perf() -> dict[str, Any] | None:
        from ante.strategy.registry import StrategyRegistry
        from ante.trade.performance import PerformanceTracker

        async with open_cli_db(ctx) as db:
            registry = StrategyRegistry(db)
            await registry.initialize()
            records = await registry.get_by_name(name)
            if not records:
                return None

            try:
                account_row = await db.fetch_one(
                    "SELECT 1 FROM accounts WHERE account_id = ?",
                    (account_id,),
                )
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    raise AccountNotFoundError(
                        f"계좌 '{account_id}'를 찾을 수 없습니다."
                    ) from e
                raise
            if account_row is None:
                raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")

            tracker = PerformanceTracker(db)
            record = records[0]
            metrics = await tracker.calculate(
                account_id=account_id, strategy_id=record.strategy_id
            )

            return {
                "strategy_name": record.name,
                "strategy_id": record.strategy_id,
                "metrics": asdict(metrics),
            }

    try:
        result = _run(_perf())
    except AccountNotFoundError:
        raise
    except OperationalError as e:
        if "no such table" in str(e).lower():
            result = None
        else:
            raise CliStrategyError(str(e)) from e
    except Exception as e:
        raise CliStrategyError(str(e)) from e

    if result is None:
        raise StrategyNotFoundError(f"전략을 찾을 수 없습니다: {name}")

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
