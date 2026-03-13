"""CLI 인증 미들웨어 — 토큰 인증 + 권한 검증."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Callable

    from ante.member.models import Member

logger = logging.getLogger(__name__)

# 인증 면제 커맨드 목록 (커맨드 이름 기준)
_AUTH_EXEMPT_COMMANDS: set[str] = {
    "bootstrap",
    "reset-password",
    "regenerate-recovery-key",
}


def authenticate_member(ctx: click.Context) -> None:
    """ANTE_MEMBER_TOKEN 환경변수로 멤버 인증.

    인증된 Member를 ctx.obj["member"]에 저장한다.
    면제 커맨드이거나 --help 플래그가 있으면 건너뛴다.
    """
    if ctx.resilient_parsing:
        return

    # 면제 커맨드 판별
    invoked = _get_invoked_subcommand(ctx)
    if invoked in _AUTH_EXEMPT_COMMANDS:
        ctx.obj["member"] = None
        return

    token = os.environ.get("ANTE_MEMBER_TOKEN", "")
    if not token:
        ctx.obj["member"] = None
        return

    try:
        member = _run_authenticate(token)
        ctx.obj["member"] = member
        logger.debug("CLI 인증 성공: %s", member.member_id)
    except PermissionError as e:
        click.echo(f"인증 실패: {e}", err=True)
        raise SystemExit(1) from e


def _run_authenticate(token: str) -> Member:
    """동기 컨텍스트에서 MemberService.authenticate 호출."""
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    async def _auth() -> Member:
        db = Database("db/ante.db")
        await db.connect()
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus)
            await service.initialize()
            return await service.authenticate(token)
        finally:
            await db.close()

    return asyncio.run(_auth())


def _get_invoked_subcommand(ctx: click.Context) -> str | None:
    """현재 컨텍스트에서 호출된 하위 커맨드 이름을 반환."""
    if hasattr(ctx, "invoked_subcommand"):
        return ctx.invoked_subcommand
    return None


def require_auth(fn: Callable) -> Callable:
    """인증 필수 데코레이터.

    @click.pass_context 아래에 배치한다.
    ctx.obj["member"]가 None이면 에러 출력 후 종료.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        # Click이 ctx를 첫 인자로 전달
        ctx = click.get_current_context()
        member = ctx.obj.get("member")
        if member is None:
            click.echo(
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
                err=True,
            )
            raise SystemExit(1)
        return fn(*args, **kwargs)

    return wrapper


def require_scope(*scopes: str) -> Callable:
    """권한 검증 데코레이터.

    @click.pass_context 아래에 배치한다.
    Human 멤버(master, admin)는 scope 제한 없이 통과.
    Agent 멤버는 등록된 scope에 필요 scope가 모두 포함되어야 한다.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            from ante.member.models import MemberType

            ctx = click.get_current_context()
            member: Member | None = ctx.obj.get("member")
            if member is None:
                click.echo(
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
                    err=True,
                )
                raise SystemExit(1)

            # Human(master, admin)은 scope 무제한
            if member.type == MemberType.HUMAN:
                return fn(*args, **kwargs)

            # Agent는 scope 검증
            missing = [s for s in scopes if s not in member.scopes]
            if missing:
                click.echo(
                    f"권한이 부족합니다. 필요 권한: {', '.join(missing)}",
                    err=True,
                )
                raise SystemExit(1)

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def get_member_id(ctx: click.Context) -> str:
    """인증된 멤버 ID를 반환. 미인증 시 'unknown'."""
    member: Member | None = ctx.obj.get("member")
    return member.member_id if member else "unknown"
