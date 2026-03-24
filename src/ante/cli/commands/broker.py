"""ante broker — 증권사 계좌 조회 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def broker() -> None:
    """증권사 계좌 정보 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_account_service():  # noqa: ANN202
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    return account_service, db


async def _get_broker(account_id: str | None = None):  # noqa: ANN202
    """AccountService를 통해 브로커 어댑터를 획득한다.

    account_id가 None이면 기존 Config 기반 폴백을 사용한다.
    """
    if account_id:
        account_service, db = await _create_account_service()
        adapter = await account_service.get_broker(account_id)
        await adapter.connect()
        return adapter, db

    # 폴백: 기존 Config 기반 브로커 생성
    from ante.config.config import Config

    config = Config.load()
    broker_config = config.get("broker") or {}
    if not isinstance(broker_config, dict):
        broker_config = {}
    broker_type = broker_config.get("type", "kis")

    if broker_type == "kis":
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter(broker_config)
        await adapter.connect()
        return adapter, None
    elif broker_type == "mock":
        from ante.broker.mock import MockBrokerAdapter

        adapter = MockBrokerAdapter(broker_config)
        await adapter.connect()
        return adapter, None
    else:
        msg = f"지원하지 않는 브로커: {broker_type}"
        raise ValueError(msg)


async def _ipc_broker_command(command: str, account_id: str | None, actor: str) -> dict:
    """IPC를 통해 서버 브로커 인스턴스에 위임한다.

    ServerNotRunningError, IPCTimeoutError 시 예외를 전파하여 호출자가 폴백 처리한다.
    """
    from ante.cli.commands.ipc_helpers import ipc_send

    args: dict = {}
    if account_id:
        args["account_id"] = account_id
    return await ipc_send(command, args, actor=actor)


@broker.command()
@click.option("--account", "account_id", default=None, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def status(ctx: click.Context, account_id: str | None) -> None:
    """증권사 연결 상태 조회."""
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(_ipc_broker_command("broker.status", account_id, actor))
    except click.ClickException:
        # 서버 미실행 또는 타임아웃 — 기존 직접 연결 폴백
        async def _run_status() -> dict:
            try:
                adapter, db = await _get_broker(account_id)
                try:
                    healthy = await adapter.health_check()
                    return {
                        "connected": adapter.is_connected,
                        "healthy": healthy,
                        "exchange": adapter.exchange,
                    }
                finally:
                    if db:
                        await db.close()
            except Exception as e:
                return {
                    "connected": False,
                    "healthy": False,
                    "error": str(e),
                }

        result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(
            f"  연결 상태  : {'연결됨' if result.get('connected') else '미연결'}"
        )
        click.echo(f"  건강 상태  : {'정상' if result.get('healthy') else '이상'}")
        if result.get("exchange"):
            click.echo(f"  거래소     : {result['exchange']}")
        if result.get("error"):
            click.echo(f"  오류       : {result['error']}")


@broker.command()
@click.option("--account", "account_id", default=None, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def balance(ctx: click.Context, account_id: str | None) -> None:
    """증권사 계좌 잔고 조회."""
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(_ipc_broker_command("broker.balance", account_id, actor))
    except click.ClickException:
        # 서버 미실행 — 기존 직접 연결 폴백
        async def _run_balance() -> dict:
            adapter, db = await _get_broker(account_id)
            try:
                return await adapter.get_account_balance()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        try:
            result = _run(_run_balance())
        except Exception as e:
            fmt.error(str(e))
            return

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            if isinstance(value, float):
                click.echo(f"  {key:20s}: {value:>15,.0f}")
            else:
                click.echo(f"  {key:20s}: {value}")


@broker.command()
@click.option("--account", "account_id", default=None, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def positions(ctx: click.Context, account_id: str | None) -> None:
    """증권사 보유 종목 조회."""
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(_ipc_broker_command("broker.positions", account_id, actor))
    except click.ClickException:
        # 서버 미실행 — 기존 직접 연결 폴백
        async def _run_positions() -> list[dict]:
            adapter, db = await _get_broker(account_id)
            try:
                return await adapter.get_positions()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        try:
            pos_list = _run(_run_positions())
            result = {"positions": pos_list}
        except Exception as e:
            fmt.error(str(e))
            return

    pos_list = result.get("positions", [])

    if not pos_list:
        fmt.output({"message": "보유 종목 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": pos_list})
    else:
        columns = ["symbol", "quantity", "avg_price", "eval_amount"]
        fmt.table(pos_list, columns)


@broker.command()
@click.option("--account", "account_id", default=None, help="계좌 ID")
@click.option(
    "--fix", is_flag=True, default=False, help="불일치 발견 시 자동 보정 수행"
)
@click.pass_context
@require_auth
@require_scope("broker:read")
def reconcile(ctx: click.Context, account_id: str | None, fix: bool) -> None:
    """내부 데이터와 증권사 데이터 대사."""
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    # --fix 옵션이 있으면 IPC로 서버에 위임 (상태 변경)
    if fix:
        actor = get_member_id(ctx)

        async def _run_fix() -> dict:
            from ante.cli.commands.ipc_helpers import ipc_send

            args: dict = {"fix": True}
            if account_id:
                args["account_id"] = account_id
            return await ipc_send("broker.reconcile", args, actor=actor)

        try:
            result = _run(_run_fix())
        except click.ClickException:
            raise
        except Exception as e:
            fmt.error(str(e))
            return
    else:
        # 읽기 전용: IPC 우선, 폴백으로 오프라인 방식
        try:
            actor = get_member_id(ctx)

            async def _run_ipc_reconcile() -> dict:
                from ante.cli.commands.ipc_helpers import ipc_send

                args: dict = {"fix": False}
                if account_id:
                    args["account_id"] = account_id
                return await ipc_send("broker.reconcile", args, actor=actor)

            result = _run(_run_ipc_reconcile())
        except click.ClickException:
            # 서버 미실행 — 기존 오프라인 방식 폴백
            async def _run_reconcile() -> dict:
                from ante.core.database import Database
                from ante.trade.position import PositionHistory

                adapter, adapter_db = await _get_broker(account_id)
                db = adapter_db or Database("db/ante.db")
                if not adapter_db:
                    await db.connect()
                try:
                    position_history = PositionHistory(db)
                    await position_history.initialize()

                    broker_positions = await adapter.get_account_positions()
                    internal_positions = await position_history.get_all_positions()

                    broker_map = {p["symbol"]: p for p in broker_positions}
                    internal_map = {p.symbol: p for p in internal_positions}

                    all_symbols = set(broker_map.keys()) | set(internal_map.keys())
                    discrepancies = []
                    for symbol in sorted(all_symbols):
                        bp = broker_map.get(symbol)
                        ip = internal_map.get(symbol)
                        broker_qty = float(bp.get("quantity", 0)) if bp else 0.0
                        internal_qty = ip.quantity if ip else 0.0
                        if broker_qty != internal_qty:
                            discrepancies.append(
                                {
                                    "symbol": symbol,
                                    "broker_qty": broker_qty,
                                    "internal_qty": internal_qty,
                                    "diff": broker_qty - internal_qty,
                                }
                            )

                    return {
                        "total_symbols": len(all_symbols),
                        "discrepancies": discrepancies,
                        "match": len(discrepancies) == 0,
                        "fix_applied": False,
                        "corrections": 0,
                    }
                finally:
                    await adapter.disconnect()
                    await db.close()

            try:
                result = _run(_run_reconcile())
            except Exception as e:
                fmt.error(str(e))
                return

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  총 종목 수     : {result.get('total_symbols', 0)}")
        click.echo(f"  대사 결과      : {'일치' if result.get('match') else '불일치'}")
        if result.get("discrepancies"):
            click.echo("  불일치 종목:")
            fmt.table(
                result["discrepancies"],
                ["symbol", "broker_qty", "internal_qty", "diff"],
            )
        if result.get("fix_applied"):
            click.echo(f"  자동 보정      : {result.get('corrections', 0)}건 수행")
