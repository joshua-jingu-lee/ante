"""ante member — 멤버 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope


@click.group()
def member() -> None:
    """멤버 등록·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


async def _create_service():  # noqa: ANN202
    """CLI용 MemberService 인스턴스 생성."""
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    service = MemberService(db, eventbus)
    await service.initialize()
    return service, db


@member.command()
@click.option("--id", "member_id", required=True, help="master 멤버 ID")
@click.option("--name", default="", help="표시 이름")
@click.pass_context
def bootstrap(ctx: click.Context, member_id: str, name: str) -> None:
    """최초 master 계정 생성 (인증 불필요)."""
    fmt = get_formatter(ctx)
    password = click.prompt("패스워드", hide_input=True, confirmation_prompt=True)

    async def _run_bootstrap() -> tuple[dict, str, str]:
        service, db = await _create_service()
        try:
            m, token, recovery_key = await service.bootstrap_master(
                member_id=member_id,
                password=password,
                name=name,
            )
            return (
                {
                    "member_id": m.member_id,
                    "role": m.role,
                    "emoji": m.emoji,
                },
                token,
                recovery_key,
            )
        finally:
            await db.close()

    try:
        result, token, recovery_key = _run(_run_bootstrap())
    except ValueError as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output({**result, "token": token, "recovery_key": recovery_key})
    else:
        fmt.success("master 계정 생성 완료", result)
        click.echo(f"\n🔑 토큰: {token}")
        click.echo(f"   export ANTE_MEMBER_TOKEN={token}")
        click.echo(f"\n⚠️  Recovery Key: {recovery_key}")
        click.echo("   이 키는 다시 표시되지 않습니다. 안전한 곳에 보관하세요.")


@member.command("list")
@click.option(
    "--type",
    "member_type",
    type=click.Choice(["human", "agent"]),
    help="멤버 타입 필터",
)
@click.option("--org", help="조직 필터")
@click.option(
    "--status", type=click.Choice(["active", "suspended", "revoked"]), help="상태 필터"
)
@format_option
@click.pass_context
@require_auth
@require_scope("member:read")
def member_list(
    ctx: click.Context, member_type: str | None, org: str | None, status: str | None
) -> None:
    """멤버 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        service, db = await _create_service()
        try:
            members = await service.list(
                member_type=member_type, org=org, status=status
            )
            return [
                {
                    "member_id": m.member_id,
                    "type": m.type,
                    "role": m.role,
                    "org": m.org,
                    "name": m.name,
                    "emoji": m.emoji,
                    "status": m.status,
                    "scopes": m.scopes,
                    "created_at": m.created_at,
                }
                for m in members
            ]
        finally:
            await db.close()

    result = _run(_run_list())
    if not result:
        fmt.output({"message": "등록된 멤버가 없습니다.", "members": []})
        return

    if fmt.is_json:
        fmt.output({"members": result})
    else:
        for m in result:
            scopes = ", ".join(m["scopes"]) if m["scopes"] else "-"
            emoji = m["emoji"] or "-"
            click.echo(
                f"  {emoji:2s} {m['member_id']:20s} {m['type']:6s} {m['role']:8s} "
                f"{m['org']:15s} {m['status']:10s} {scopes}"
            )


@member.command("info")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_scope("member:read")
def member_info(ctx: click.Context, member_id: str) -> None:
    """멤버 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _run_info() -> dict | None:
        service, db = await _create_service()
        try:
            m = await service.get(member_id)
            if not m:
                return None
            return {
                "member_id": m.member_id,
                "type": m.type,
                "role": m.role,
                "org": m.org,
                "name": m.name,
                "emoji": m.emoji,
                "status": m.status,
                "scopes": m.scopes,
                "created_at": m.created_at,
                "created_by": m.created_by,
                "last_active_at": m.last_active_at,
            }
        finally:
            await db.close()

    result = _run(_run_info())
    if not result:
        fmt.error(f"멤버를 찾을 수 없습니다: {member_id}")
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  Member ID : {result['member_id']}")
        click.echo(f"  타입      : {result['type']}")
        click.echo(f"  역할      : {result['role']}")
        click.echo(f"  조직      : {result['org']}")
        click.echo(f"  이름      : {result['name']}")
        click.echo(f"  이모지    : {result['emoji'] or '-'}")
        click.echo(f"  상태      : {result['status']}")
        click.echo(f"  권한      : {', '.join(result['scopes']) or '-'}")
        click.echo(f"  생성일    : {result['created_at']}")
        click.echo(f"  생성자    : {result['created_by']}")


@member.command("register")
@click.option("--id", "member_id", required=True, help="멤버 ID")
@click.option(
    "--type",
    "member_type",
    required=True,
    type=click.Choice(["human", "agent"]),
    help="멤버 타입",
)
@click.option("--org", default="default", help="소속 조직")
@click.option("--name", default="", help="표시 이름")
@click.option("--scopes", default="", help="권한 범위 (쉼표 구분)")
@format_option
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_register(
    ctx: click.Context,
    member_id: str,
    member_type: str,
    org: str,
    name: str,
    scopes: str,
) -> None:
    """멤버 등록 (토큰 발급)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else []

    async def _run_register() -> tuple[dict, str]:
        service, db = await _create_service()
        try:
            m, token = await service.register(
                member_id=member_id,
                member_type=member_type,
                org=org,
                name=name,
                scopes=scope_list,
                registered_by=actor,
            )
            return {
                "member_id": m.member_id,
                "type": m.type,
                "role": m.role,
                "org": m.org,
                "name": m.name,
            }, token
        finally:
            await db.close()

    try:
        result, token = _run(_run_register())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output({**result, "token": token})
    else:
        fmt.success("멤버 등록 완료", result)
        click.echo(f"  토큰: {token}")
        click.echo("  이 토큰은 다시 표시되지 않습니다.")


@member.command("set-emoji")
@click.argument("member_id")
@click.argument("emoji")
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_set_emoji(ctx: click.Context, member_id: str, emoji: str) -> None:
    """멤버 이모지 설정/변경."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_set_emoji() -> dict:
        service, db = await _create_service()
        try:
            m = await service.update_emoji(member_id, emoji, updated_by=actor)
            return {"member_id": m.member_id, "emoji": m.emoji}
        finally:
            await db.close()

    try:
        result = _run(_run_set_emoji())
    except ValueError as e:
        fmt.error(str(e))
        return

    fmt.success(f"이모지 설정 완료: {member_id} → {result['emoji']}", result)


@member.command("suspend")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_suspend(ctx: click.Context, member_id: str) -> None:
    """멤버 일시 정지."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_suspend() -> dict:
        service, db = await _create_service()
        try:
            m = await service.suspend(member_id, suspended_by=actor)
            return {"member_id": m.member_id, "status": m.status}
        finally:
            await db.close()

    try:
        result = _run(_run_suspend())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    fmt.success(f"멤버 정지 완료: {member_id}", result)


@member.command("reactivate")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_reactivate(ctx: click.Context, member_id: str) -> None:
    """멤버 재활성화."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_reactivate() -> dict:
        service, db = await _create_service()
        try:
            m = await service.reactivate(member_id, reactivated_by=actor)
            return {"member_id": m.member_id, "status": m.status}
        finally:
            await db.close()

    try:
        result = _run(_run_reactivate())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    fmt.success(f"멤버 재활성화 완료: {member_id}", result)


@member.command("revoke")
@click.argument("member_id")
@click.confirmation_option(prompt="이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?")
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_revoke(ctx: click.Context, member_id: str) -> None:
    """멤버 영구 폐기."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_revoke() -> dict:
        service, db = await _create_service()
        try:
            m = await service.revoke(member_id, revoked_by=actor)
            return {"member_id": m.member_id, "status": m.status}
        finally:
            await db.close()

    try:
        result = _run(_run_revoke())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    fmt.success(f"멤버 폐기 완료: {member_id}", result)


@member.command("rotate-token")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_scope("member:admin")
def member_rotate_token(ctx: click.Context, member_id: str) -> None:
    """토큰 재발급 (기존 토큰 즉시 무효화)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_rotate() -> tuple[dict, str]:
        service, db = await _create_service()
        try:
            m, token = await service.rotate_token(member_id, rotated_by=actor)
            return {"member_id": m.member_id}, token
        finally:
            await db.close()

    try:
        result, token = _run(_run_rotate())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output({**result, "token": token})
    else:
        click.echo("  기존 토큰이 즉시 무효화되었습니다.")
        click.echo(f"  새 토큰: {token}")
        click.echo("  이 토큰은 다시 표시되지 않습니다.")


@member.command("reset-password")
@click.option("--recovery-key", required=True, help="Recovery Key")
@click.pass_context
def member_reset_password(ctx: click.Context, recovery_key: str) -> None:
    """Recovery Key로 패스워드 리셋 (인증 불필요)."""
    fmt = get_formatter(ctx)
    new_password = click.prompt(
        "새 패스워드", hide_input=True, confirmation_prompt=True
    )

    async def _run_reset() -> None:
        service, db = await _create_service()
        try:
            members = await service.list(member_type="human")
            master = next((m for m in members if m.role == "master"), None)
            if not master:
                msg = "master 멤버가 존재하지 않습니다"
                raise ValueError(msg)
            await service.reset_password(master.member_id, recovery_key, new_password)
        finally:
            await db.close()

    try:
        _run(_run_reset())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    fmt.success("패스워드가 변경되었습니다.")


@member.command("regenerate-recovery-key")
@click.pass_context
def member_regenerate_recovery_key(ctx: click.Context) -> None:
    """Recovery Key 재발급 (인증 불필요)."""
    fmt = get_formatter(ctx)
    password = click.prompt("현재 패스워드", hide_input=True)

    async def _run_regen() -> str:
        service, db = await _create_service()
        try:
            members = await service.list(member_type="human")
            master = next((m for m in members if m.role == "master"), None)
            if not master:
                msg = "master 멤버가 존재하지 않습니다"
                raise ValueError(msg)
            return await service.regenerate_recovery_key(master.member_id, password)
        finally:
            await db.close()

    try:
        new_key = _run(_run_regen())
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output({"recovery_key": new_key})
    else:
        click.echo("  기존 복구 키가 폐기되었습니다.")
        click.echo(f"\n  새 복구 키: {new_key}")
        click.echo("\n  안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.")
