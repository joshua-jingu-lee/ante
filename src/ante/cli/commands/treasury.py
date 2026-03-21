"""ante treasury — 자금 현황 조회/관리 커맨드."""

from __future__ import annotations

import asyncio

import click

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
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    if account_id:
        account = await account_service.get(account_id)
        t = Treasury(
            db,
            eventbus,
            account_id=account.account_id,
            currency=account.currency,
            buy_commission_rate=float(account.buy_commission_rate),
            sell_commission_rate=float(account.sell_commission_rate),
        )
    else:
        t = Treasury(db, eventbus)

    await t.initialize()
    return t, db


@treasury.command()
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def status(ctx: click.Context, account_id: str | None) -> None:
    """자금 현황 요약."""
    fmt = get_formatter(ctx)

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
@click.argument("amount", type=float)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def allocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇에 예산 할당."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    async def _run_allocate() -> dict:
        from ante.cli.commands._ipc import ipc_send

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
        return

    if result.get("success"):
        fmt.success(
            f"예산 할당 완료: {bot_id} <- {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(
            f"예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: {amount:,.0f}원)"
        )


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def deallocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇 예산 회수."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    async def _run_deallocate() -> dict:
        from ante.cli.commands._ipc import ipc_send

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
        return

    if result.get("success"):
        fmt.success(
            f"예산 회수 완료: {bot_id} -> {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(f"예산 회수 실패: 가용 예산 부족 (요청: {amount:,.0f}원)")


@treasury.command()
@click.option("--date", "date_str", default=None, help="특정 날짜 조회 (YYYY-MM-DD)")
@click.option("--from", "from_date", default=None, help="기간 조회 시작일 (YYYY-MM-DD)")
@click.option("--to", "to_date", default=None, help="기간 조회 종료일 (YYYY-MM-DD)")
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def snapshot(
    ctx: click.Context,
    date_str: str | None,
    from_date: str | None,
    to_date: str | None,
    account_id: str | None,
) -> None:
    """일별 자산 스냅샷 조회."""
    from datetime import UTC, datetime

    fmt = get_formatter(ctx)

    # 옵션 검증: --date 와 --from/--to 는 동시 사용 불가
    if date_str and (from_date or to_date):
        fmt.error("--date와 --from/--to 옵션은 동시에 사용할 수 없습니다.")
        return

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
        fmt.error(f"{target} 날짜의 스냅샷이 없습니다.")
        return

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
