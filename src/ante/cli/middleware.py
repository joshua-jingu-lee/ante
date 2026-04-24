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

# 인증 면제 커맨드 경로 목록 (루트부터 leaf까지의 전체 경로)
# - ("init",): 최초 1회 실행이므로 토큰이 아직 없음
# - ("member", "reset-password") / ("member", "regenerate-recovery-key"):
#   인증 수단 분실 시 복구 경로
#
# NOTE: 전체 경로 tuple로 매칭한다. leaf 이름만 비교하면 `ante feed init`처럼
# leaf 이름이 우연히 "init"인 다른 서브커맨드까지 면제 대상으로 오인된다.
# (`ante feed init`은 `@require_auth` + `@require_scope("data:write")`로 반드시
# 인증이 필요하다.)
_AUTH_EXEMPT_COMMAND_PATHS: set[tuple[str, ...]] = {
    ("init",),
    ("member", "reset-password"),
    ("member", "regenerate-recovery-key"),
}


def _resolve_token() -> str:
    """ANTE_MEMBER_TOKEN을 환경변수 또는 토큰 파일에서 확보한다.

    우선순위:
    1. ANTE_MEMBER_TOKEN 환경변수
    2. ANTE_TOKEN_FILE 환경변수가 가리키는 파일
    3. /run/ante-token 파일 (QA 컨테이너 기본 경로)
    """
    token = os.environ.get("ANTE_MEMBER_TOKEN", "")
    if token:
        return token

    token_file = os.environ.get("ANTE_TOKEN_FILE", "/run/ante-token")
    try:
        with open(token_file) as f:
            token = f.read().strip()
    except (FileNotFoundError, PermissionError):
        pass

    return token


def authenticate_member(ctx: click.Context) -> None:
    """ANTE_MEMBER_TOKEN 환경변수 또는 토큰 파일로 멤버 인증.

    인증된 Member를 ctx.obj["member"]에 저장한다.
    면제 커맨드이거나 --help 플래그가 있으면 건너뛴다.
    """
    if ctx.resilient_parsing:
        return

    # 면제 커맨드 판별 — 루트부터 leaf까지의 전체 커맨드 경로로 매칭한다.
    # (`ante member reset-password` → ("member", "reset-password"))
    # LeafAwareGroup(main.py)이 ctx.obj["_leaf_command_path"]에 tuple을 저장.
    path = _get_invoked_command_path(ctx)
    if path is not None and path in _AUTH_EXEMPT_COMMAND_PATHS:
        ctx.obj["member"] = None
        return

    token = _resolve_token()
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


def _get_invoked_command_path(ctx: click.Context) -> tuple[str, ...] | None:
    """호출된 서브커맨드의 전체 경로 tuple을 반환.

    `ante init` → ("init",)
    `ante member list` → ("member", "list")
    `ante member reset-password` → ("member", "reset-password")
    `ante feed init` → ("feed", "init")

    Click 8.x의 `Group.invoke`는 root 콜백이 실행되기 직전에
    `ctx.protected_args`/`ctx.args`를 비운다 (core.py:1680-1682). 따라서
    root 콜백 시점에 `ctx.invoked_subcommand`는 1단계 서브커맨드 이름만
    담고 있고, `ctx.args`/`ctx.protected_args`도 비어 있어 nested
    subcommand path를 직접 추출할 수 없다.

    대신 루트 그룹을 `LeafAwareGroup`(main.py)로 설정해, `invoke()`의
    `super().invoke(ctx)` 호출 **전에** 전체 커맨드 경로를 tuple로
    `ctx.obj["_leaf_command_path"]`에 저장한다. 이 값이 있으면 우선 사용하고,
    없으면 `ctx.invoked_subcommand`로 부분 fallback한다.
    """
    obj = getattr(ctx, "obj", None)
    if isinstance(obj, dict):
        path = obj.get("_leaf_command_path")
        if path:
            return tuple(path)
    if hasattr(ctx, "invoked_subcommand") and ctx.invoked_subcommand:
        return (ctx.invoked_subcommand,)
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

        wrapper._required_scopes = scopes  # type: ignore[attr-defined]
        return wrapper

    return decorator


def get_member_id(ctx: click.Context) -> str:
    """인증된 멤버 ID를 반환. 미인증 시 'unknown'."""
    member: Member | None = ctx.obj.get("member")
    return member.member_id if member else "unknown"
