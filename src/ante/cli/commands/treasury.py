"""ante treasury — 자금 현황 조회/관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli._validators import (
    reject_invalid_account_id,
    reject_inverted_date_range,
    validate_iso_date,
    validate_positive_finite_amount,
)
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id as _get_member_id
from ante.cli.middleware import require_auth, require_scope


@click.group()
def treasury() -> None:
    """자금 현황 조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_treasury(account_id: str | None = None):  # noqa: ANN202
    from ante.account.scoping import require_account_id
    from ante.account.service import AccountService
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    validated_account_id = require_account_id(account_id, context="cli.treasury")

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    account = await account_service.get(validated_account_id)
    t = Treasury(
        db,
        eventbus,
        account_id=account.account_id,
        currency=account.currency,
        buy_commission_rate=float(account.buy_commission_rate),
        sell_commission_rate=float(account.sell_commission_rate),
    )
    await t.initialize()
    return t, db


@treasury.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def status(ctx: click.Context, account_id: str) -> None:
    """자금 현황 요약."""
    fmt = get_formatter(ctx)

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). `_create_treasury`는 이미
    # `require_account_id`를 `db.connect()` 이전에 호출하지만(leak-free), CLI
    # 콜백이 non-Click `InvalidAccountIdError`를 명시적으로 catch하지 않아
    # traceback으로 새던 contract-drift를 본 ingress 거부가 닫는다. 에러코드는
    # #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    async def _run_status() -> dict:
        t, db = await _create_treasury(account_id)
        try:
            return t.get_summary()
        finally:
            await db.close()

    result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  계좌 잔고      : {result['account_balance']:>15,.0f}")
        click.echo(f"  매수 가능      : {result['purchasable_amount']:>15,.0f}")
        click.echo(f"  총 평가액      : {result['total_evaluation']:>15,.0f}")
        click.echo(f"  총 손익        : {result['total_profit_loss']:>15,.0f}")
        click.echo(f"  총 할당        : {result['total_allocated']:>15,.0f}")
        click.echo(f"  총 예약        : {result['total_reserved']:>15,.0f}")
        click.echo(f"  미할당         : {result['unallocated']:>15,.0f}")
        click.echo(f"  봇 수          : {result['bot_count']:>15d}")


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def allocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇에 예산 할당."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    # #1656 E bucket defense-in-depth: invalid account_id(`default`/패턴
    # 위반/`""`)를 `ipc_send`(→`_handle_treasury_allocate`) 이전에 거부한다.
    # IPC handler가 1차 보증(handler-first require_account_id)하지만, CLI
    # ingress 거부는 clean early exit(traceback 부재) + #1634/#1635 동형
    # 방어선이다. `--account` required arg라 전 입력을 검증한다. 에러코드는
    # #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.allocate"
    )

    async def _run_allocate() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.allocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    try:
        result = _run(_run_allocate())
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        ctx.exit(1)

    if result.get("success"):
        fmt.success(
            f"예산 할당 완료: {bot_id} <- {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(
            f"예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: {amount:,.0f}원)"
        )
        ctx.exit(1)


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def deallocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇 예산 회수."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    # #1656 E bucket defense-in-depth: `allocate`와 동형 — invalid account_id를
    # `ipc_send`(→`_handle_treasury_deallocate`) 이전에 거부한다(required arg
    # 전검증, clean early exit). 에러코드는 #1633 SSOT `VALIDATION_ERROR`.
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.deallocate"
    )

    async def _run_deallocate() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.deallocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    try:
        result = _run(_run_deallocate())
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        ctx.exit(1)

    if result.get("success"):
        fmt.success(
            f"예산 회수 완료: {bot_id} -> {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(f"예산 회수 실패: 가용 예산 부족 (요청: {amount:,.0f}원)")
        ctx.exit(1)


@treasury.command()
@click.option(
    "--date",
    "date_str",
    default=None,
    callback=validate_iso_date,
    help="특정 날짜 조회 (YYYY-MM-DD)",
)
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=validate_iso_date,
    help="기간 조회 시작일 (YYYY-MM-DD)",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=validate_iso_date,
    help="기간 조회 종료일 (YYYY-MM-DD)",
)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def snapshot(
    ctx: click.Context,
    date_str: str | None,
    from_date: str | None,
    to_date: str | None,
    account_id: str,
) -> None:
    """일별 자산 스냅샷 조회."""
    from datetime import UTC, datetime

    fmt = get_formatter(ctx)

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). `status`와 동일 `_create_treasury`
    # construction-lifecycle 경계를 공유하므로 동형으로 ingress에서 차단한다.
    # 에러코드는 #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    # 옵션 검증: --date 와 --from/--to 는 동시 사용 불가
    if date_str and (from_date or to_date):
        fmt.error(
            "--date와 --from/--to 옵션은 동시에 사용할 수 없습니다.",
            code="CLI_OPTION_CONFLICT",
        )
        raise SystemExit(1)

    # inverted date range(시작일 > 종료일) 거부: CLI_OPTION_CONFLICT 검증
    # 직후, _run_snapshot/서비스 호출 이전에 차단한다 (backtest.py:72-77
    # 동형, INVALID_DATE_RANGE + exit 1).
    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_snapshot() -> dict | list[dict] | None:
        t, db = await _create_treasury(account_id)
        try:
            if date_str:
                return await t.get_daily_snapshot(date_str)
            if from_date or to_date:
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                start = from_date or "2000-01-01"
                end = to_date or today
                return await t.get_snapshots(start, end)
            # 기본: 오늘 스냅샷
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            return await t.get_daily_snapshot(today)
        finally:
            await db.close()

    result = _run(_run_snapshot())

    if result is None:
        target = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
        fmt.error(f"{target} 날짜의 스냅샷이 없습니다.", code="snapshot_not_found")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
        return

    # text 모드 출력
    if isinstance(result, list):
        _print_snapshot_list(result)
    else:
        _print_snapshot(result)


def _print_snapshot(s: dict) -> None:
    """단일 스냅샷을 텍스트로 출력."""
    daily_pnl = s.get("daily_pnl", 0.0)
    daily_return = s.get("daily_return", 0.0)
    sign = "+" if daily_pnl >= 0 else ""

    click.echo(f"일별 자산 스냅샷 ({s['snapshot_date']})")
    click.echo(f"  총 자산:      {s['total_asset']:>15,.0f}원")
    purchase = s["ante_purchase_amount"]
    click.echo(
        f"  Ante 관리:    {s['ante_eval_amount']:>15,.0f}원 (매입: {purchase:,.0f}원)"
    )
    click.echo(f"  미할당:       {s['unallocated']:>15,.0f}원")
    click.echo(
        f"  당일 손익:    {sign}{daily_pnl:>14,.0f}원 ({sign}{daily_return:.2f}%)"
    )
    click.echo(f"  미실현 손익:  {s.get('unrealized_pnl', 0.0):>+15,.0f}원")
    click.echo(f"  보유 종목:    {s.get('bot_count', 0)}개 봇")


def _print_snapshot_list(snapshots: list[dict]) -> None:
    """스냅샷 목록을 테이블로 출력."""
    if not snapshots:
        click.echo("(스냅샷 없음)")
        return

    first = snapshots[0]["snapshot_date"]
    last = snapshots[-1]["snapshot_date"]
    click.echo(f"일별 자산 스냅샷 ({first} ~ {last})")
    header = f"  {'날짜':>12} {'총 자산':>15} {'당일 손익':>15} {'수익률':>10}"
    click.echo(header)
    click.echo("  " + "-" * 56)
    for s in snapshots:
        pnl = s.get("daily_pnl", 0.0)
        ret = s.get("daily_return", 0.0)
        sign = "+" if pnl >= 0 else ""
        click.echo(
            f"  {s['snapshot_date']:>12}"
            f" {s['total_asset']:>15,.0f}"
            f" {sign}{pnl:>14,.0f}"
            f" {sign}{ret:>9.2f}%"
        )
