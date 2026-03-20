"""ante account -- 계좌 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.service import AccountService
    from ante.core.database import Database

logger = logging.getLogger(__name__)


@click.group()
def account() -> None:
    """계좌 생성·조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_account_service() -> tuple[AccountService, Database]:
    """CLI에서 AccountService를 생성하는 헬퍼."""
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    return account_service, db


def mask_value(key: str, value: str) -> str:
    """인증 정보 값을 마스킹한다.

    6자 이하: '****'
    초과: 앞 4자 + '****' + 뒤 2자
    """
    if len(value) <= 6:
        return "****"
    return value[:4] + "****" + value[-2:]


def _get_selectable_broker_types() -> list[str]:
    """BROKER_REGISTRY에 등록된 broker_type만 반환 (kis-overseas 제외)."""
    from ante.broker.registry import BROKER_REGISTRY

    return list(BROKER_REGISTRY.keys())


# ── create ──────────────────────────────────────


@account.command("create")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_create(ctx: click.Context) -> None:
    """대화형 계좌 생성."""
    fmt = get_formatter(ctx)

    from ante.account.models import Account, TradingMode
    from ante.account.presets import BROKER_PRESETS

    # 1) 브로커 선택 (BROKER_REGISTRY에 등록된 것만)
    selectable = _get_selectable_broker_types()
    click.echo("\n브로커를 선택하세요:")
    for i, bt in enumerate(selectable, 1):
        preset = BROKER_PRESETS[bt]
        click.echo(f"  {i}) {bt} ({preset.default_name})")

    choice = click.prompt("선택", type=click.IntRange(1, len(selectable)), default=1)
    broker_type = selectable[choice - 1]
    preset = BROKER_PRESETS[broker_type]

    # 2) 계좌 ID, 이름
    account_id = click.prompt("계좌 ID", default=preset.default_account_id)
    name = click.prompt("이름", default=preset.default_name)

    # 3) 거래 모드
    click.echo("거래 모드를 선택하세요:")
    click.echo("  1) virtual (가상거래)")
    click.echo("  2) live (실제거래)")
    mode_choice = click.prompt("선택", type=click.IntRange(1, 2), default=1)
    trading_mode = TradingMode.VIRTUAL if mode_choice == 1 else TradingMode.LIVE

    # 4) 인증 정보
    credentials: dict[str, str] = {}
    for cred_key in preset.required_credentials:
        hide = cred_key.lower() in ("app_secret", "secret", "password")
        value = click.prompt(cred_key.upper(), hide_input=hide)
        credentials[cred_key] = value

    # 5) Account 생성
    new_account = Account(
        account_id=account_id,
        name=name,
        exchange=preset.exchange,
        currency=preset.currency,
        timezone=preset.timezone,
        trading_hours_start=preset.trading_hours_start,
        trading_hours_end=preset.trading_hours_end,
        trading_mode=trading_mode,
        broker_type=broker_type,
        credentials=credentials,
        buy_commission_rate=preset.buy_commission_rate,
        sell_commission_rate=preset.sell_commission_rate,
    )

    async def _do_create() -> Account:
        svc, db = await _create_account_service()
        try:
            return await svc.create(new_account)
        finally:
            await db.close()

    try:
        created = _run(_do_create())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(
        f'계좌 "{created.account_id}" 생성 완료 '
        f"({created.exchange} / {created.currency} / {created.broker_type})",
        data={
            "account_id": created.account_id,
            "exchange": created.exchange,
            "currency": created.currency,
            "broker_type": created.broker_type,
        },
    )


# ── list ──────────────────────────────────────


@account.command("list")
@click.option(
    "--status",
    "status_filter",
    default=None,
    help="상태 필터 (active/suspended/deleted)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_list(ctx: click.Context, status_filter: str | None) -> None:
    """계좌 목록 조회."""
    fmt = get_formatter(ctx)

    from ante.account.models import AccountStatus

    async def _do_list() -> list[dict]:
        svc, db = await _create_account_service()
        try:
            status = AccountStatus(status_filter) if status_filter else None
            accounts = await svc.list(status=status)
            return [_account_to_row(a) for a in accounts]
        finally:
            await db.close()

    try:
        rows = _run(_do_list())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if not rows:
        fmt.output({"message": "등록된 계좌가 없습니다.", "accounts": []})
        return

    if fmt.is_json:
        fmt.output({"accounts": rows})
    else:
        fmt.table(
            rows,
            ["account_id", "name", "exchange", "currency", "broker_type", "status"],
        )


# ── info ──────────────────────────────────────


@account.command("info")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_info(ctx: click.Context, account_id: str) -> None:
    """계좌 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _do_info() -> dict:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            return _account_to_detail(acct)
        finally:
            await db.close()

    try:
        detail = _run(_do_info())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(detail)
    else:
        _print_account_detail(detail)


# ── suspend ──────────────────────────────────────


@account.command("suspend")
@click.argument("account_id")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_suspend(ctx: click.Context, account_id: str) -> None:
    """계좌 거래 정지."""
    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    async def _do_suspend() -> None:
        svc, db = await _create_account_service()
        try:
            await svc.suspend(
                account_id, reason="CLI 수동 정지", suspended_by=member_id
            )
        finally:
            await db.close()

    try:
        _run(_do_suspend())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 정지 완료')


# ── activate ──────────────────────────────────────


@account.command("activate")
@click.argument("account_id")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_activate(ctx: click.Context, account_id: str) -> None:
    """계좌 활성화."""
    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    async def _do_activate() -> None:
        svc, db = await _create_account_service()
        try:
            await svc.activate(account_id, activated_by=member_id)
        finally:
            await db.close()

    try:
        _run(_do_activate())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 활성화 완료')


# ── delete ──────────────────────────────────────


@account.command("delete")
@click.argument("account_id")
@click.option(
    "--yes", "skip_confirm", is_flag=True, default=False, help="확인 없이 삭제"
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_delete(ctx: click.Context, account_id: str, skip_confirm: bool) -> None:
    """계좌 삭제 (소프트 딜리트)."""
    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    if not skip_confirm:
        click.confirm(f'계좌 "{account_id}"를 삭제하시겠습니까?', abort=True)

    async def _do_delete() -> None:
        svc, db = await _create_account_service()
        try:
            await svc.delete(account_id, deleted_by=member_id)
        finally:
            await db.close()

    try:
        _run(_do_delete())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 삭제 완료')


# ── credentials ──────────────────────────────────────


@account.command("credentials")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_credentials(ctx: click.Context, account_id: str) -> None:
    """인증 정보 조회 (마스킹)."""
    fmt = get_formatter(ctx)

    async def _do_credentials() -> dict[str, str]:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            return {k: mask_value(k, v) for k, v in acct.credentials.items()}
        finally:
            await db.close()

    try:
        masked = _run(_do_credentials())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if not masked:
        fmt.output({"message": "등록된 인증 정보가 없습니다.", "credentials": {}})
        return

    if fmt.is_json:
        fmt.output({"account_id": account_id, "credentials": masked})
    else:
        click.echo(f"\n인증 정보 ({account_id})")
        click.echo("-" * 35)
        for key, value in masked.items():
            click.echo(f"  {key.upper():14s}: {value}")


# ── set-credentials ──────────────────────────────────────


@account.command("set-credentials")
@click.argument("account_id")
@click.option("--app-key", default=None, help="APP_KEY (비대화형)")
@click.option("--app-secret", default=None, help="APP_SECRET (비대화형)")
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_set_credentials(
    ctx: click.Context,
    account_id: str,
    app_key: str | None,
    app_secret: str | None,
) -> None:
    """인증 정보 재설정 (대화형 또는 --app-key/--app-secret 옵션)."""
    fmt = get_formatter(ctx)

    from ante.account.presets import BROKER_PRESETS

    async def _do_set_credentials() -> None:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            preset = BROKER_PRESETS.get(acct.broker_type)
            if not preset or not preset.required_credentials:
                msg = f"브로커 '{acct.broker_type}'에는 인증 정보가 필요하지 않습니다."
                fmt.output({"message": msg})
                return

            # CLI 옵션으로 전달된 인증 정보가 있으면 비대화형 처리
            cli_creds: dict[str, str] = {}
            if app_key is not None:
                cli_creds["app_key"] = app_key
            if app_secret is not None:
                cli_creds["app_secret"] = app_secret

            if cli_creds:
                # CLI 옵션으로 전달된 값 사용
                new_credentials = cli_creds
            else:
                # 대화형 입력
                new_credentials = {}
                click.echo(f"\n인증 정보 재설정 ({account_id})")
                for cred_key in preset.required_credentials:
                    hide = cred_key.lower() in ("app_secret", "secret", "password")
                    value = click.prompt(cred_key.upper(), hide_input=hide)
                    new_credentials[cred_key] = value

            await svc.update(account_id, credentials=new_credentials)
            fmt.success(f'계좌 "{account_id}" 인증 정보 재설정 완료')
        finally:
            await db.close()

    try:
        _run(_do_set_credentials())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e


# ── 유틸리티 ──────────────────────────────────────


def _account_to_row(acct: Account) -> dict:
    """Account를 테이블 행 dict로 변환."""
    return {
        "account_id": acct.account_id,
        "name": acct.name,
        "exchange": acct.exchange,
        "currency": acct.currency,
        "broker_type": acct.broker_type,
        "status": acct.status.value,
    }


def _account_to_detail(acct: Account) -> dict:
    """Account를 상세 dict로 변환."""
    return {
        "account_id": acct.account_id,
        "name": acct.name,
        "exchange": acct.exchange,
        "currency": acct.currency,
        "broker_type": acct.broker_type,
        "trading_mode": acct.trading_mode.value,
        "buy_commission_rate": str(acct.buy_commission_rate),
        "sell_commission_rate": str(acct.sell_commission_rate),
        "status": acct.status.value,
        "timezone": acct.timezone,
        "trading_hours": f"{acct.trading_hours_start}-{acct.trading_hours_end}",
        "created_at": str(acct.created_at) if acct.created_at else "",
    }


def _print_account_detail(detail: dict) -> None:
    """텍스트 모드로 계좌 상세 출력."""
    click.echo("\n계좌 정보")
    click.echo("-" * 35)
    labels = {
        "account_id": "ID",
        "name": "이름",
        "exchange": "거래소",
        "currency": "통화",
        "broker_type": "브로커",
        "trading_mode": "거래 모드",
        "buy_commission_rate": "매수 수수료",
        "sell_commission_rate": "매도 수수료",
        "status": "상태",
        "timezone": "시간대",
        "trading_hours": "거래 시간",
        "created_at": "생성일",
    }
    for key, label in labels.items():
        value = detail.get(key, "")
        if key in ("buy_commission_rate", "sell_commission_rate") and value:
            # 퍼센트로 표시
            try:
                pct = float(value) * 100
                value = f"{pct:.3f}%"
            except ValueError:
                pass
        click.echo(f"  {label:14s}: {value}")
