"""ante broker — 증권사 계좌 조회 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.contracts.ipc_client_errors import IPCServerNotRunningError


@click.group()
def broker() -> None:
    """증권사 계좌 정보 조회."""


def _run(coro):
    return asyncio.run(coro)


async def _create_account_service():
    from ante.account.service import AccountService
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    return account_service, db


async def _get_broker(account_id: str | None = None):
    """AccountService를 통해 브로커 어댑터를 획득한다.

    account_id가 None이면 기존 Config 기반 폴백을 사용한다.

    ``account_id`` 분기에서 ``account_service.get_broker`` 또는
    ``adapter.connect`` 가 raise 하면, 호출자에 ``db`` 핸들이 전달되지 않으므로
    여기서 ``db.close()`` 를 보장해야 한다. close 를 누락하면 aiosqlite
    백그라운드 스레드가 살아 있어 ``asyncio.run`` 종료 후에도 프로세스가
    수 초간 hang 한다. lifecycle 보장 — 정상 경로의 close 는 호출자
    (``_run_balance`` 등) 가 계속 책임진다.
    """
    if account_id:
        account_service, db = await _create_account_service()
        try:
            adapter = await account_service.get_broker(account_id)
            await adapter.connect()
        except Exception:
            await db.close()
            raise
        return adapter, db

    from ante.cli.main import get_config_dir
    from ante.config.config import Config

    config = Config.load(config_dir=get_config_dir())
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


async def _ipc_broker_command(
    command: str,
    account_id: str,
    actor: str,
    extra: dict | None = None,
) -> dict:
    """IPC를 통해 서버 브로커 인스턴스에 위임한다."""
    from ante.cli.commands.ipc_helpers import ipc_send

    args: dict = {**(extra or {}), "account_id": account_id}
    return await ipc_send(command, args, actor=actor)


@broker.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def status(ctx: click.Context, account_id: str) -> None:
    """증권사 연결 상태 조회."""
    from ante.cli._validators import reject_invalid_account_id
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.status"
    )

    try:
        actor = get_member_id(ctx)
        result = _run(_ipc_broker_command("broker.status", validated_account_id, actor))
    except IPCServerNotRunningError:

        async def _run_status() -> dict:
            try:
                adapter, db = await _get_broker(validated_account_id)
                try:
                    healthy = await adapter.health_check()
                    return {
                        "connected": adapter.is_connected,
                        "healthy": healthy,
                        "exchange": adapter.exchange,
                    }
                finally:
                    try:
                        await adapter.disconnect()
                    finally:
                        if db:
                            await db.close()
            except AccountNotFoundError:
                raise
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
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def balance(ctx: click.Context, account_id: str) -> None:
    """증권사 계좌 잔고 조회."""
    from ante.cli._validators import reject_invalid_account_id
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.balance"
    )

    try:
        actor = get_member_id(ctx)
        result = _run(
            _ipc_broker_command("broker.balance", validated_account_id, actor)
        )
    except IPCServerNotRunningError:

        async def _run_balance() -> dict:
            adapter, db = await _get_broker(validated_account_id)
            try:
                return await adapter.get_account_balance()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        result = _run(_run_balance())

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            if isinstance(value, float):
                click.echo(f"  {key:20s}: {value:>15,.0f}")
            else:
                click.echo(f"  {key:20s}: {value}")


@broker.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("broker:read")
def positions(ctx: click.Context, account_id: str) -> None:
    """증권사 보유 종목 조회."""
    from ante.cli._validators import reject_invalid_account_id
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.positions"
    )

    try:
        actor = get_member_id(ctx)
        result = _run(
            _ipc_broker_command("broker.positions", validated_account_id, actor)
        )
    except IPCServerNotRunningError:

        async def _run_positions() -> list[dict]:
            adapter, db = await _get_broker(validated_account_id)
            try:
                return await adapter.get_positions()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        result = {"positions": _run(_run_positions())}

    pos_list = result.get("positions", [])

    if not pos_list:
        fmt.output({"message": "보유 종목 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": pos_list})
    else:
        columns = ["symbol", "quantity", "avg_price", "eval_amount"]
        fmt.table(pos_list, columns)


@broker.command("order-history")
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=validate_iso_date,
    help="조회 시작일 (YYYY-MM-DD, 미지정 시 어댑터 기본 최근 7일)",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=validate_iso_date,
    help="조회 종료일 (YYYY-MM-DD, 미지정 시 어댑터 기본 오늘)",
)
@click.pass_context
@require_auth
@require_scope("broker:read")
def order_history(
    ctx: click.Context,
    account_id: str,
    from_date: str | None,
    to_date: str | None,
) -> None:
    """증권사 주문/체결 이력 조회 (read-only).

    출력은 BrokerAdapter 가 정규화한 8키다: ``order_id`` / ``symbol`` /
    ``side`` / ``quantity`` / ``filled_quantity`` / ``price`` / ``status`` /
    ``timestamp``. KIS 원시 필드(``rvse_cncl_dvsn_nm``, ``ord_tmd`` 등)는
    어댑터 내부 fold 단계에서 이미 버려져 이 표면에 존재하지 않는다.

    알려진 한계 — 어댑터 계약 범위라 본 명령이 해소하지 않고 노출만 한다:

    - 취소된 주문도 ``status=pending`` 으로 보인다 (상태가 체결수량 기준 2값).

    - 정정/취소 구분과 원주문 번호가 소실되어 정정 행을 구별할 수 없다.

    - 주문 시각이 소실된다 (``timestamp`` 는 영업일 단위).

    - ``price`` 는 체결단가와 주문단가를 한 칸에 혼합한다 (구분 표시 없음).

    - ``timestamp`` 어휘가 어댑터마다 다르다 (KIS ``YYYYMMDD``, 그 외 ISO).

    - ``broker_type`` 이 ``test`` 인 계좌는 ``--from``/``--to`` 를 무시한다.

    - KIS 3개월 경계를 가로지르는 구간은 결과가 불완전할 수 있다.
    """
    from ante.cli._validators import reject_invalid_account_id
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.order-history"
    )

    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="조회 시작일",
        to_label="조회 종료일",
    )

    extra: dict = {}
    if from_date is not None:
        extra["from_date"] = from_date
    if to_date is not None:
        extra["to_date"] = to_date

    actor = get_member_id(ctx)

    try:
        result = _run(
            _ipc_broker_command(
                "broker.order_history", validated_account_id, actor, extra=extra
            )
        )
    except click.ClickException as e:
        if getattr(e, "ipc_error_code", "") != "IPC_SERVER_NOT_RUNNING":
            code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
            message = getattr(e, "ipc_error_message", None) or e.message
            fmt.error(message if fmt.is_json else f"{code}: {message}", code=code)
            raise SystemExit(1) from e

        async def _run_order_history() -> list[dict]:
            from ante.core.time import iso_to_kis_date

            adapter, db = await _get_broker(validated_account_id)
            try:
                return await adapter.get_order_history(
                    iso_to_kis_date(from_date),
                    iso_to_kis_date(to_date),
                )
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        result = {"orders": _run(_run_order_history())}

    orders = result.get("orders", [])

    if fmt.is_json:
        fmt.output(result)
        return

    if not orders:
        click.echo("  주문/체결 이력 없음")
        return

    click.echo(
        "  ※ status 는 체결수량 기준 2값(filled/pending)이라 "
        "취소 주문도 pending 으로 보입니다. price 는 체결가/주문가 혼합, "
        "timestamp 는 영업일(일자)까지입니다."
    )
    fmt.table(
        orders,
        [
            "order_id",
            "symbol",
            "side",
            "quantity",
            "filled_quantity",
            "price",
            "status",
            "timestamp",
        ],
    )


@broker.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.option(
    "--fix", is_flag=True, default=False, help="불일치 발견 시 자동 보정 수행"
)
@click.pass_context
@require_auth
@require_scope("broker:read")
def reconcile(ctx: click.Context, account_id: str, fix: bool) -> None:
    """내부 데이터와 증권사 데이터 대사."""
    from ante.cli._validators import reject_invalid_account_id
    from ante.cli.middleware import get_member_id

    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.reconcile"
    )

    if fix:
        actor = get_member_id(ctx)

        async def _run_fix() -> dict:
            from ante.cli.commands.ipc_helpers import ipc_send

            args: dict = {"fix": True, "account_id": validated_account_id}
            return await ipc_send("broker.reconcile", args, actor=actor)

        result = _run(_run_fix())
    else:
        try:
            actor = get_member_id(ctx)

            async def _run_ipc_reconcile() -> dict:
                from ante.cli.commands.ipc_helpers import ipc_send

                args: dict = {"fix": False, "account_id": validated_account_id}
                return await ipc_send("broker.reconcile", args, actor=actor)

            result = _run(_run_ipc_reconcile())
        except IPCServerNotRunningError:

            async def _run_reconcile() -> dict:
                from ante.cli.main import get_db_path
                from ante.core.database import Database
                from ante.trade.position import PositionHistory

                adapter, adapter_db = await _get_broker(validated_account_id)
                db = adapter_db or Database(get_db_path())
                if not adapter_db:
                    await db.connect()
                try:
                    position_history = PositionHistory(db)
                    await position_history.initialize()

                    broker_positions = await adapter.get_account_positions()
                    internal_positions = await position_history.get_all_positions(
                        account_id=validated_account_id
                    )

                    broker_totals: dict[str, float] = {}
                    for bp in broker_positions:
                        b_qty = float(bp.get("quantity", 0) or 0)
                        if b_qty != 0:
                            sym = bp["symbol"]
                            broker_totals[sym] = broker_totals.get(sym, 0.0) + b_qty
                    internal_totals: dict[str, float] = {}
                    for ip in internal_positions:
                        internal_totals[ip.symbol] = (
                            internal_totals.get(ip.symbol, 0.0) + ip.quantity
                        )

                    all_symbols = set(broker_totals.keys()) | set(
                        internal_totals.keys()
                    )
                    discrepancies = []
                    for symbol in sorted(all_symbols):
                        broker_qty = broker_totals.get(symbol, 0.0)
                        internal_qty = internal_totals.get(symbol, 0.0)
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

            result = _run(_run_reconcile())

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
