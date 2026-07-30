"""ante broker — 증권사 계좌 조회 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.contracts import emit_cli_error


@click.group()
def broker() -> None:
    """증권사 계좌 정보 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_account_service():  # noqa: ANN202
    # broker live-state 경로 (adapter.connect 동반) 는 별도 epic scope.
    # live broker state 와 ``Database`` lifecycle 이 같은 try/except 로 엮여
    # 있어 단순 ``open_cli_db`` wrap 으로 동치 변환이 불가능하다 — 별도 spec
    # 정렬 PR (부모 epic #1818 follow-up) 에서 다룬다.
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


async def _get_broker(account_id: str | None = None):  # noqa: ANN202
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

    # 폴백: 기존 Config 기반 브로커 생성
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
    """IPC를 통해 서버 브로커 인스턴스에 위임한다.

    ``account_id``는 호출자(``--account`` required CLI 옵션 + helper 통과)
    에서 이미 검증된 값이어야 한다. fallback 금지 정책에 따라 빈 dict 를
    IPC 로 보내지 않는다.

    ServerNotRunningError, IPCTimeoutError 시 예외를 전파하여 호출자가 폴백 처리한다.

    Refs #2412: ``extra`` 는 command 고유 인자(예 ``order-history`` 의
    ``from_date``/``to_date``)를 payload 에 합치기 위한 **순수 additive**
    확장이다. ``None``(또는 빈 dict)이면 payload 는 종전과 **바이트 동일**한
    ``{"account_id": ...}`` 이며, 기존 호출자 3곳(``status`` / ``balance`` /
    ``positions``)의 동작은 불변이다. ``reconcile`` 은 본 helper 를 경유하지
    않고 ``ipc_send`` 를 직접 호출하므로(payload ``{"fix", "account_id"}``)
    본 확장의 영향 범위 밖이다 — 통일은 별건 스코프다.
    """
    from ante.cli.commands.ipc_helpers import ipc_send

    args: dict = {"account_id": account_id}
    if extra:
        args.update(extra)
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

    # CLI ingress에서 invalid account_id를 IPC/_get_broker 이전에 명시 거부
    # (fallback 금지, helper 재사용).
    # ``InvalidAccountIdError``는 non-Click ``AccountError``라 기존
    # ``except click.ClickException`` fallback이 잡지 못해 traceback이 났다.
    # helper가 ``InvalidAccountIdError``→``fmt.error(code=VALIDATION_ERROR)``+
    # ``SystemExit(1)``로 변환하고 검증된 account_id를 반환한다.
    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.status"
    )

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(_ipc_broker_command("broker.status", validated_account_id, actor))
    except click.ClickException:
        # 서버 미실행 또는 타임아웃 — 기존 직접 연결 폴백
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
                    # sibling(balance/positions/reconcile)과 대칭으로 connect 성공
                    # 이후 adapter session 을 정리한다 (#2373). disconnect 가 raise
                    # 해도 db.close() 가 실행되도록 내부 try/finally 로 중첩 —
                    # aiosqlite 스레드 누수(hang) 방지를 disconnect 예외보다 우선
                    # 보장한다.
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

        try:
            result = _run(_run_status())
        except AccountNotFoundError as e:
            fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
            raise SystemExit(1) from e

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

    # CLI ingress에서 invalid account_id를 IPC/_get_broker 이전에 명시 거부
    # (fallback 금지, helper 재사용).
    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.balance"
    )

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(
            _ipc_broker_command("broker.balance", validated_account_id, actor)
        )
    except click.ClickException:
        # 서버 미실행 — 기존 직접 연결 폴백
        async def _run_balance() -> dict:
            adapter, db = await _get_broker(validated_account_id)
            try:
                return await adapter.get_account_balance()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        try:
            result = _run(_run_balance())
        except AccountNotFoundError as e:
            fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
            raise SystemExit(1) from e
        except Exception as e:
            # emit_cli_error 로 CLI/IPC 동일 public code surface 정렬.
            # broker typed exception (APIError / AuthenticationError /
            # OrderNotFoundError / RateLimitError / CircuitOpenError) 은
            # registry MRO lookup 으로 ``BROKER_*`` 안정 코드를 surface 하며,
            # 미분류 fault 는 ``EXECUTION_ERROR`` fallback.
            emit_cli_error(fmt, e)

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

    # CLI ingress에서 invalid account_id를 IPC/_get_broker 이전에 명시 거부
    # (fallback 금지, helper 재사용).
    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.positions"
    )

    # IPC 우선 시도
    try:
        actor = get_member_id(ctx)
        result = _run(
            _ipc_broker_command("broker.positions", validated_account_id, actor)
        )
    except click.ClickException:
        # 서버 미실행 — 기존 직접 연결 폴백
        async def _run_positions() -> list[dict]:
            adapter, db = await _get_broker(validated_account_id)
            try:
                return await adapter.get_positions()
            finally:
                await adapter.disconnect()
                if db:
                    await db.close()

        try:
            pos_list = _run(_run_positions())
            result = {"positions": pos_list}
        except AccountNotFoundError as e:
            fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
            raise SystemExit(1) from e
        except Exception as e:
            # emit_cli_error 로 broker typed exception 안정 코드 surface
            # (positions 표면 동일 정책).
            emit_cli_error(fmt, e)

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

    # CLI ingress에서 invalid account_id를 IPC/_get_broker 이전에 명시 거부
    # (fallback 금지, helper 재사용 — 형제 4종 동형).
    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.order-history"
    )

    # inverted date range(시작일 > 종료일) 거부: IPC/_get_broker 이전에
    # 차단한다 (#1597 date-range read family 동형, INVALID_DATE_RANGE +
    # exit 1). 이 helper 없이 추가하면 ``--from > --to`` 가 exit 0 빈 결과로
    # 돌아가 오라클 #1597 이 닫은 drift class 가 재개방된다.
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

    # IPC 우선 시도. 폴백 트리거는 ``IPC_SERVER_NOT_RUNNING`` **단독** 이다
    # (``bot signal-key`` 패턴, bot.py:641-650). 형제 balance/positions 의
    # 통짜 ``except click.ClickException`` 은 서버 error envelope 까지 삼켜
    # credentials/rate limit/circuit breaker 를 우회하므로 따르지 않는다
    # (docs/specs/ipc/ipc.md 경고). IPC_TIMEOUT·server-error 는 폴백 없이
    # 원본 code/message 로 surface 한다.
    try:
        actor = get_member_id(ctx)
        result = _run(
            _ipc_broker_command(
                "broker.order_history", validated_account_id, actor, extra=extra
            )
        )
    except click.ClickException as e:
        if getattr(e, "ipc_error_code", "") != "IPC_SERVER_NOT_RUNNING":
            code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
            message = getattr(e, "ipc_error_message", None) or e.message
            # text 모드는 ``bot signal-key`` 형제와 동일한 ``{code}: {message}``
            # prefix UX 를 유지하되, ``code=`` 인자를 함께 넘겨 error taxonomy
            # drift(Family A: code 누락) allowlist 부채를 새로 만들지 않는다.
            fmt.error(message if fmt.is_json else f"{code}: {message}", code=code)
            raise SystemExit(1) from e

        # 서버 미실행 — 직접 연결 폴백. 이 경로는 IPC 핸들러를 거치지 않으므로
        # **여기서도** ISO→YYYYMMDD 변환을 반드시 수행해야 한다. ISO 가 그대로
        # 어댑터로 새면 3개월 경계 판정(문자열 사전순 비교)이 항상 before 로
        # 오선택되고 malformed 날짜가 KIS 로 전송된다 — 예외도 경고도 없다.
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

        try:
            result = {"orders": _run(_run_order_history())}
        except AccountNotFoundError as exc:
            fmt.error(str(exc), code="ACCOUNT_NOT_FOUND")
            raise SystemExit(1) from exc
        except Exception as exc:
            # emit_cli_error 로 broker typed exception 안정 코드 surface
            # (형제 표면 동일 정책). ``InvalidIsoDateError`` 는 class-level
            # ``code="VALIDATION_ERROR"`` 로 접힌다.
            emit_cli_error(fmt, exc)

    orders = result.get("orders", [])

    if fmt.is_json:
        # IPC envelope passthrough — ``fmt.success`` 재래핑 금지(형제 shape
        # 불일치 방지). 빈 결과도 ``{"orders": []}`` 로 통일하며 positions 의
        # ``message`` 키 혼합(broker.py 의 empty 분기)은 따르지 않는다.
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

    # CLI ingress에서 invalid account_id를 IPC/_get_broker 이전에 명시 거부
    # (fallback 금지, helper 재사용).
    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.broker.reconcile"
    )

    # --fix 옵션이 있으면 IPC로 서버에 위임 (상태 변경)
    if fix:
        actor = get_member_id(ctx)

        async def _run_fix() -> dict:
            from ante.cli.commands.ipc_helpers import ipc_send

            args: dict = {"fix": True, "account_id": validated_account_id}
            return await ipc_send("broker.reconcile", args, actor=actor)

        try:
            result = _run(_run_fix())
        except click.ClickException:
            raise
        except Exception as e:
            # emit_cli_error 로 broker typed exception 안정 코드 surface
            # (reconcile --fix mutating path).
            emit_cli_error(fmt, e)
    else:
        # 읽기 전용: IPC 우선, 폴백으로 오프라인 방식
        try:
            actor = get_member_id(ctx)

            async def _run_ipc_reconcile() -> dict:
                from ante.cli.commands.ipc_helpers import ipc_send

                args: dict = {"fix": False, "account_id": validated_account_id}
                return await ipc_send("broker.reconcile", args, actor=actor)

            result = _run(_run_ipc_reconcile())
        except click.ClickException:
            # 서버 미실행 — 기존 오프라인 방식 폴백.
            # broker live-state (adapter + DB) 경로는 별도 spec 정렬 PR
            # (#1818 follow-up) 에서 ``open_cli_db`` 와 adapter lifecycle 의
            # 동치 변환 contract 를 정합한다.
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
                    # 단일 계좌 reconcile은 해당 계좌 포지션끼리만 비교한다.
                    # account_id 필터를 빼면 다른 계좌의 positions 가 false
                    # discrepancy 로 잡힌다.
                    internal_positions = await position_history.get_all_positions(
                        account_id=validated_account_id
                    )

                    # #2120: 같은 심볼을 보유한 다중봇 internal 을 **심볼별로
                    # 합산**한다. ``{p.symbol: p}`` dict 컴프리헨션은 동일 심볼을
                    # 덮어써 한 봇 수량만 비교 대상이 되어 다중봇 계좌를 false
                    # discrepancy 로 오판했다(per-bot 오판). detect-only 경로이므로
                    # 계좌 총합 broker vs 전 봇 합산 internal 을 비교한다.
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

            try:
                result = _run(_run_reconcile())
            except AccountNotFoundError as e:
                fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
                raise SystemExit(1) from e
            except Exception as e:
                # emit_cli_error 로 broker typed exception (APIError 등)
                # 안정 코드 surface. helper 의 registry MRO lookup +
                # EXECUTION_ERROR fallback 으로 일관 정렬한다.
                emit_cli_error(fmt, e)

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
