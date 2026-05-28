"""ante strategy — 전략 관리 커맨드."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_invalid_account_id
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts import emit_cli_error
from ante.strategy.registry import StrategyStatus

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.strategy.registry import StrategyRegistry

# `StrategyStatus` enum이 단일 SSOT다. `ante.strategy.__init__`의 lazy
# ``__getattr__`` 정리로 본 import가 heavy 분석 의존성을 끌지 않는다.
# CLI dispatch path가 light한지는
# ``tests/unit/test_cli_dependency_isolation.py``가 fresh subprocess로 차단한다.


@click.group()
def strategy() -> None:
    """전략 관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


@asynccontextmanager
async def _create_registry(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[StrategyRegistry, Database]]:
    """CLI 에서 ``StrategyRegistry`` async context manager.

    ``open_cli_db`` 기반 lifecycle (factory composition, account.py 패턴
    1:1 미러). 호출 패턴:

        async with _create_registry(ctx=ctx) as (registry, db):
            ...

    fresh DB에서도 strategies 테이블이 존재하도록 helper 차원에서 보장한다.
    ``register/get_by_name/list_strategies`` 등 모든 caller 에 자동 적용되며,
    idempotent하므로 기존 명시 ``await registry.initialize()`` 호출은 회귀
    안전을 위해 보존한다 (read-only 명시 예외 대상이지만 본 helper 는
    안전성을 위해 호출을 그대로 보존한다).
    """
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


async def _find_bot_id_for_strategy(db, strategy_id: str) -> str | None:  # noqa: ANN001
    """전략에 연결된 첫 번째 봇 ID를 반환한다."""
    try:
        row = await db.fetch_one(
            "SELECT bot_id FROM bots WHERE strategy_id = ? AND status != 'deleted' "
            "ORDER BY bot_id LIMIT 1",
            (strategy_id,),
        )
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return None
        raise
    return row["bot_id"] if row else None


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
            # 기존 ad-hoc envelope (``submitted``/``stage``/``errors``) 은
            # 자동화 의존성 보호를 위해 유지하되, 안정 ``code`` 필드를
            # 추가해 표준 JSON 에러 envelope 의 분류 의미를 보존한다 (현존
            # ``meta_validation`` 분기와 동형).
            fmt.output(
                {
                    "submitted": False,
                    "stage": "validate",
                    "code": "STRATEGY_VALIDATION_ERROR",
                    "errors": validation.errors,
                }
            )
        else:
            # text-mode 도 STRATEGY_VALIDATION_ERROR 안정 코드를 명시
            # 부여한다 (JSON 분기의 ``code`` 필드와 동일 SSOT).
            # ``OutputFormatter.error`` 가 text 모드에서 code 를 stdout 에
            # 출력하지 않지만 (포맷 책임 분리), drift guard ``fmt.error``
            # callsite invariant 를 충족하기 위한 명시 부여.
            fmt.error(f"Validation failed: {path}", code="STRATEGY_VALIDATION_ERROR")
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
            # load 실패에도 안정 ``code`` 를 envelope 에 포함한다.
            fmt.output(
                {
                    "submitted": False,
                    "stage": "load",
                    "code": "STRATEGY_LOAD_ERROR",
                    "error": str(e),
                }
            )
        else:
            # helper 가 ``StrategyLoadError`` → ``STRATEGY_LOAD_ERROR`` 안정
            # 코드를 surface 한다 (JSON 분기의 ``code`` 필드와 동일 SSOT).
            # 도메인 문구 "Load test failed:" 는 ``fallback_message`` 로 보존.
            emit_cli_error(fmt, e, fallback_message=f"Load test failed: {e}")
        raise SystemExit(1)

    meta = strategy_cls.meta

    # meta shape 검증: StrategyMeta 인스턴스가 아니면 사용자 manifest 오류로
    # validation error 처리 (dict 등 invalid shape의 AttributeError 누출 차단).
    # registry.register(meta.name, meta.version, ...) 호출 전에 ingress에서
    # 차단해야 StrategyMeta가 아닌 객체가 attribute access 단계에서
    # AttributeError traceback으로 stderr에 새는 회귀를 막는다.
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
            fmt.error(
                f"Invalid meta shape: expected StrategyMeta, got {type(meta).__name__}",
                code="STRATEGY_VALIDATION_ERROR",
            )
        raise SystemExit(1)

    # 3. 전략 인스턴스에서 rationale/risks 추출
    rationale = ""
    risks: list[str] = []
    try:
        instance = strategy_cls(ctx=None)
        rationale = instance.get_rationale()
        risks = instance.get_risks()
    except Exception:
        pass  # 인스턴스 생성 실패 시 빈 값 사용

    # 4. Registry 등록
    async def _register() -> dict:
        # ``_create_registry`` async context manager lifecycle.
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
            # register 실패 (duplicate id 등) envelope 에 typed ``code`` 를
            # 포함한다. 예외 인스턴스가 class-level ``code`` 를 가지면 우선
            # 사용하고, 없으면 generic ``STRATEGY_ERROR`` fallback 으로
            # envelope 일관성을 유지한다.
            fmt.output(
                {
                    "submitted": False,
                    "stage": "register",
                    "code": getattr(e, "code", "STRATEGY_ERROR"),
                    "error": str(e),
                }
            )
        else:
            # helper 가 ``StrategyError`` MRO lookup 으로 subclass 별 typed
            # 코드 (예: ``IncompatibleExchangeError`` →
            # ``STRATEGY_INCOMPATIBLE_EXCHANGE``) 를 surface 한다. registry
            # miss + ``.code`` 미부여 시 ``EXECUTION_ERROR`` fallback (구
            # ``str(e)`` no-code 회귀 차단).
            emit_cli_error(fmt, e)
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

    # Preflight: invalid --status는 registry/DB 진입 전에 차단한다.
    # `StrategyStatus` enum이 SSOT이며 직접 비교한다. 이로써 일반적인 입력
    # 오타가 `StrategyStatus(status)` ValueError → Python traceback으로
    # 새지 않고 flat JSON error로 종료된다.
    valid_statuses = {s.value for s in StrategyStatus}
    if status is not None and status not in valid_statuses:
        fmt.error(
            f"잘못된 status 값: {status!r}. 허용값: {sorted(valid_statuses)}",
            code="STRATEGY_VALIDATION_ERROR",
        )
        raise SystemExit(1)

    async def _list() -> list[dict]:
        # ``_create_registry`` async context manager lifecycle.
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

    # account.py:683-687 패턴: click.ClickException은 그대로 전파해 click의
    # 표준 출력 경로를 보존하고, 나머지 일반 Exception은 STRATEGY_ERROR로
    # 분류해 구조화된 에러로 종료한다(traceback 노출 차단).
    #
    # 추가로 fresh DB에서 strategies 테이블 부재로 발생하는
    # `sqlite3.OperationalError: no such table: strategies` 는 빈 결과로
    # 정규화한다. `_create_registry()` 가 `await registry.initialize()` 를
    # 보장하므로 정상 경로에서는 발생하지 않지만, race/regress 시에도
    # 사용자에게 내부 schema 명을 노출하지 않도록 방어한다.
    try:
        rows = _run(_list())
    except click.ClickException:
        raise
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            rows = []
        else:
            fmt.error(str(e), code="STRATEGY_ERROR")
            raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code="STRATEGY_ERROR")
        raise SystemExit(1) from e

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

    async def _set_status() -> dict:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "strategy.set_status",
                {"strategy_id": strategy_id, "status": target_status.value},
                actor=actor,
            )

        # ``_create_registry`` async context manager lifecycle.
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
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e
    except ValueError as e:
        fmt.error(str(e), code="STRATEGY_INVALID_STATUS_TRANSITION")
        raise SystemExit(1) from e
    except Exception as e:
        # typed exception 의 class-level ``code`` 속성을 우선 surface 한다
        # (예: ``StrategyNotFoundError.code = "STRATEGY_NOT_FOUND"``).
        # 속성이 없는 일반 ``StrategyError`` 는 기존 ``STRATEGY_ERROR``
        # fallback 으로 유지된다 (회귀 없음).
        fmt.error(str(e), code=getattr(e, "code", "STRATEGY_ERROR"))
        raise SystemExit(1) from e

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

    async def _info() -> dict | None:
        # ``_create_registry`` async context manager lifecycle.
        async with _create_registry(ctx=ctx) as (registry, _):
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
                "author_name": record.author_name,
                "author_id": record.author_id,
                "filepath": record.filepath,
                "registered_at": record.registered_at.isoformat(),
                "validation_warnings": record.validation_warnings,
            }

            # 전략 파일에서 파라미터 정보 로드 시도
            params = _load_strategy_params(record.filepath)
            if params is not None:
                result["params"] = params["params"]
                result["param_schema"] = params["param_schema"]
                if params.get("rationale"):
                    result["rationale"] = params["rationale"]
                if params.get("risks"):
                    result["risks"] = params["risks"]

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

    # 호출 표면 try/except: fresh DB 또는 race 상황의
    # `sqlite3.OperationalError: no such table: strategies` 는 not-found 로
    # 정규화한다. 다른 OperationalError(예: malformed DB)는 STRATEGY_ERROR 로
    # 분류하여 내부 traceback 노출을 차단한다 (strategy_summary 동형 SSOT).
    try:
        result = _run(_info())
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            result = None
        else:
            fmt.error(str(e), code="STRATEGY_ERROR")
            raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code="STRATEGY_ERROR")
        raise SystemExit(1) from e

    if result is None:
        # `strategy_summary` / spec STRATEGY_NOT_FOUND SSOT 재사용.
        fmt.error(f"전략을 찾을 수 없습니다: {name}", code="STRATEGY_NOT_FOUND")
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
    """전략 기간별 성과 집계."""
    fmt = get_formatter(ctx)

    async def _summary() -> dict | None:
        # ``_create_registry`` async context manager lifecycle.
        from ante.trade.performance import PerformanceTracker

        async with _create_registry(ctx=ctx) as (registry, db):
            await registry.initialize()
            record = await registry.get(strategy_id)
            if record is None:
                return None

            tracker = PerformanceTracker(db)
            bot_id = await _find_bot_id_for_strategy(db, strategy_id)
            if period == "daily":
                daily_summaries = await tracker.get_daily_summary(bot_id=bot_id)
                items = [asdict(s) for s in daily_summaries]
            elif period == "weekly":
                weekly_summaries = await tracker.get_weekly_summary(bot_id=bot_id)
                items = [
                    {**asdict(s), "week_label": s.week_label} for s in weekly_summaries
                ]
            else:
                monthly_summaries = await tracker.get_monthly_summary(bot_id=bot_id)
                items = [asdict(s) for s in monthly_summaries]

            return {
                "strategy_id": strategy_id,
                "period": period,
                "bot_id": bot_id,
                "items": items,
            }

    try:
        result = _run(_summary())
    except Exception as e:
        fmt.error(str(e), code="STRATEGY_ERROR")
        raise SystemExit(1) from e

    if result is None:
        fmt.error(f"전략을 찾을 수 없습니다: {strategy_id}", code="STRATEGY_NOT_FOUND")
        raise SystemExit(1)

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
        fmt.error(
            "계좌 ID를 지정해야 합니다. --account-id <id> 옵션을 사용하세요.",
            code="STRATEGY_MISSING_REQUIRED_ACCOUNT",
        )
        raise SystemExit(1)

    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.strategy.performance"
    )

    async def _perf() -> dict | None:
        # ``open_cli_db`` 헬퍼 lifecycle (cleanup invariant — 예외/cancellation
        # 시에도 ``Database.close()`` 1회 보장).
        from ante.strategy.registry import StrategyRegistry
        from ante.trade.performance import PerformanceTracker

        async with open_cli_db(ctx) as db:
            registry = StrategyRegistry(db)
            # fresh DB에서도 strategies 테이블이 존재하도록 정규화한다
            # (`_create_registry` 경로와 동형 처리).
            await registry.initialize()
            records = await registry.get_by_name(name)
            if not records:
                return None

            # strategy 존재 확인 후, performance 계산 전에 account 존재를
            # 검증한다. AccountService.initialize()는 모든 non-deleted
            # account row를 materialize하며 credentials를 복호화하므로,
            # 조회 대상과 무관한 다른 계좌의 복호화 실패가 정상 사용을
            # 깨뜨릴 수 있다. 따라서 credentials 복호화 없이 이미 열린 db
            # 핸들로 lightweight 단건 존재 쿼리만 수행한다. 쿼리 의미는
            # AccountService.get(account_id 단건, status 필터 없음)과
            # 일치하며 미존재 시 동일한 AccountNotFoundError 메시지로
            # 분기한다. db.close()는 아래 finally가 단독 소유한다
            # (lifecycle 불변).
            #
            # ``accounts`` 테이블은 ``AccountService.initialize()`` 에서만
            # 생성된다. 이 경로는 raw ``Database`` 핸들만 쓰고
            # ``AccountService`` 를 초기화하지 않으므로, 부분 초기화/legacy
            # DB(예: ``ante init`` 직후)에서는 테이블 자체가 없어
            # ``sqlite3.OperationalError: no such table: accounts`` 가
            # 호출자까지 전파될 수 있다. 정의상 accounts 테이블 부재는
            # 해당 account 미존재와 동치이므로 동일한
            # AccountNotFoundError 로 정규화한다. 단, malformed db 같은
            # 다른 ``OperationalError`` 까지 삼키지 않도록 "no such table"
            # 메시지일 때로만 좁힌다.
            try:
                account_row = await db.fetch_one(
                    "SELECT 1 FROM accounts WHERE account_id = ?",
                    (account_id,),
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    raise AccountNotFoundError(
                        f"계좌 '{account_id}'를 찾을 수 없습니다."
                    ) from e
                raise
            if account_row is None:
                raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")

            tracker = PerformanceTracker(db)
            # 최신 버전의 strategy_id 기준으로 성과 계산
            record = records[0]
            metrics = await tracker.calculate(
                account_id=account_id, strategy_id=record.name
            )

            return {
                "strategy_name": record.name,
                "strategy_id": record.strategy_id,
                "metrics": asdict(metrics),
            }

    try:
        result = _run(_perf())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except sqlite3.OperationalError as e:
        # fresh DB / race 상황의 `no such table: strategies` 는 not-found 로
        # 정규화한다 (strategy_info 동형 패턴). 다른 OperationalError 는
        # STRATEGY_ERROR 로 분류한다.
        if "no such table" in str(e).lower():
            result = None
        else:
            fmt.error(str(e), code="STRATEGY_ERROR")
            raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code="STRATEGY_ERROR")
        raise SystemExit(1) from e

    if result is None:
        # strategy_summary / strategy_info STRATEGY_NOT_FOUND SSOT 재사용.
        fmt.error(f"전략을 찾을 수 없습니다: {name}", code="STRATEGY_NOT_FOUND")
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
