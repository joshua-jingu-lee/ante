"""ante member — 멤버 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click

from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import (
    get_member_id,
    require_auth,
    require_master,
    require_scope,
)

if TYPE_CHECKING:
    from ante.member.service import MemberService
from ante.contracts.cli_errors import (
    CliConfirmationRequiredError,
    CliMemberNotFoundError,
    CliMissingRequiredInputError,
    MemberPasswordEnvNotSetError,
    MemberPasswordFileNotFoundError,
)
from ante.member.errors import MemberNotFoundError, PermissionDeniedError
from ante.member.models import MemberRole

logger = logging.getLogger(__name__)

_MASTER_REQUIRED_MESSAGE = "권한이 없습니다: master만 수행할 수 있습니다."


@click.group()
def member() -> None:
    """멤버 등록·관리."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_secret_non_interactive(
    fmt: Any,
    *,
    env_name: str | None,
    file_path: str | None,
    env_option_label: str,
    file_option_label: str,
    missing_input_message: str,
) -> str:
    """``--*-env`` / ``--*-file`` 채널에서 비밀값을 비대화형으로 읽어들인다."""
    if env_name is None and file_path is None:
        raise CliMissingRequiredInputError(
            missing_input_message
            + f" {env_option_label} 또는 {file_option_label} 중 하나를 지정하세요."
        )

    if env_name is not None and file_path is not None:
        raise CliMissingRequiredInputError(
            f"{env_option_label}와 {file_option_label}는 동시에 지정할 수 없습니다."
            " 둘 중 하나만 사용하세요."
        )

    if env_name is not None:
        value = os.environ.get(env_name)
        if value is None or value.strip() == "":
            raise MemberPasswordEnvNotSetError(
                f"환경변수 {env_name}이(가) 설정되어 있지 않거나 공란입니다."
                f" {env_option_label}는 비밀값이 든 환경변수의 *이름*만 받습니다."
            )
        return value.strip()

    assert file_path is not None
    path = Path(file_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise MemberPasswordFileNotFoundError(
            f"{file_option_label} 파일을 읽을 수 없습니다: {file_path} ({e})"
        ) from e
    value = raw.strip()
    if value == "":
        raise MemberPasswordFileNotFoundError(
            f"{file_option_label} 파일이 비어 있습니다: {file_path}"
        )
    return value


@asynccontextmanager
async def _create_service(
    ctx: click.Context | None = None,
) -> AsyncIterator[MemberService]:
    """CLI용 ``MemberService`` async context manager."""
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService as _MemberService

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_service requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        eventbus = EventBus()
        service = _MemberService(db, eventbus)
        await service.initialize()
        yield service


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
) -> CommandResult:
    """멤버 목록 조회."""

    async def _run_list() -> list[dict[str, Any]]:
        async with _create_service(ctx) as service:
            members = await service.list_members(
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

    result = _run(_run_list())
    if not result:
        empty: dict[str, Any] = {"message": "등록된 멤버가 없습니다.", "members": []}
        return CommandResult(data=empty, text=(str(empty),))

    lines = []
    for m in result:
        scopes = ", ".join(m["scopes"]) if m["scopes"] else "-"
        emoji = m["emoji"] or "-"
        lines.append(
            f"  {emoji:2s} {m['member_id']:20s} {m['type']:6s} {m['role']:8s} "
            f"{m['org']:15s} {m['status']:10s} {scopes}"
        )
    return CommandResult(data={"members": result}, text=tuple(lines))


@member.command("info")
@click.argument("member_id")
@format_option
@click.pass_context
@require_auth
@require_scope("member:read")
def member_info(ctx: click.Context, member_id: str) -> CommandResult:
    """멤버 상세 정보 조회."""

    async def _run_info() -> dict[str, Any] | None:
        async with _create_service(ctx) as service:
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

    result = _run(_run_info())
    if not result:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}")

    return CommandResult(
        data=result,
        text=(
            f"  Member ID : {result['member_id']}",
            f"  타입      : {result['type']}",
            f"  역할      : {result['role']}",
            f"  조직      : {result['org']}",
            f"  이름      : {result['name']}",
            f"  이모지    : {result['emoji'] or '-'}",
            f"  상태      : {result['status']}",
            f"  권한      : {', '.join(result['scopes']) or '-'}",
            f"  생성일    : {result['created_at']}",
            f"  생성자    : {result['created_by']}",
        ),
    )


def _explicit_config_dir(ctx: click.Context) -> str | None:
    """config_dir override(옵션·``ANTE_CONFIG_DIR``)를 절대 경로로, 없으면 ``None``."""
    obj = getattr(ctx, "obj", None)
    if not isinstance(obj, dict):
        return None
    raw = obj.get("config_dir")
    if raw is None:
        return None
    return str(Path(raw).expanduser().resolve())


def _build_revoke_command(member_id: str, *, config_dir: str | None) -> str:
    """``ante member revoke`` payload 명령 문자열을 생성한다."""
    parts = ["ante"]
    if config_dir is not None:
        parts.append(f"--config-dir {shlex.quote(config_dir)}")
    parts.append(f"member revoke --yes -- {shlex.quote(member_id)}")
    return " ".join(parts)


def _invalid_role_row_dict(
    m: Any,
    *,
    actionable: bool,
    config_dir: str | None = None,
) -> dict[str, Any]:
    """``Member`` row 를 CLI 출력용 dict 로 변환."""
    has_token = bool(m.token_hash)
    row: dict[str, Any] = {
        "member_id": m.member_id,
        "role": m.role,
        "type": m.type,
        "name": m.name,
        "status": m.status,
        "created_at": m.created_at,
        "has_token": has_token,
        "token_expires_at": m.token_expires_at or None,
    }
    if actionable:
        row["revoke_command"] = _build_revoke_command(
            m.member_id, config_dir=config_dir
        )
    return row


@member.command("list-invalid-roles")
@format_option
@click.pass_context
@require_auth
@require_scope("member:read")
def member_list_invalid_roles(
    ctx: click.Context,
) -> CommandResult:
    """``MemberRole`` enum 외 role 을 가진 legacy member row 식별.

    본 명령은 canonical config 의 ``db.path`` (``get_db_path()``) 단일 DB 에
    대해서만 invalid-role row 를 식별한다. 다른 DB 파일 대상 점검은 본 PR scope
    가 아니며, 필요하면 별도 이슈로 분리한다.

    ``actionable`` 카테고리는 ``status != revoked`` 인 invalid-role row 이며,
    운영자가 ``ante member revoke --yes -- <member_id>`` 로 cleanup 해야 한다.
    ``legacy_revoked`` 는 이미 revoke 된 historical row 다.

    분류는 ``offline`` 이지만 ``MemberService.initialize()`` 가 schema migration
    DDL 을 수반한다 — 따라서 "read-only" 가 아니다. ``ante member list`` /
    ``info`` 와 동일한 ``_create_service()`` 패턴을 사용하며 runtime IPC 는
    우회한다.

    ``token_hash`` 는 모든 출력 모드에서 노출되지 않는다 (보안 SSOT).
    """
    valid_roles = [member.value for member in MemberRole]
    config_dir_override = _explicit_config_dir(ctx)

    async def _run_scan() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        async with _create_service(ctx) as service:
            scan = await service.find_invalid_role_members()
            actionable = [
                _invalid_role_row_dict(
                    m, actionable=True, config_dir=config_dir_override
                )
                for m in scan.actionable
            ]
            legacy = [
                _invalid_role_row_dict(
                    m, actionable=False, config_dir=config_dir_override
                )
                for m in scan.legacy_revoked
            ]
            return actionable, legacy

    actionable_rows, legacy_rows = _run(_run_scan())

    logger.info(
        "MEMBER_INVALID_ROLE_FOUND actionable=%d legacy_revoked=%d",
        len(actionable_rows),
        len(legacy_rows),
    )

    payload = {
        "recommended_action": "review_then_revoke",
        "valid_roles": valid_roles,
        "actionable_count": len(actionable_rows),
        "legacy_revoked_count": len(legacy_rows),
        "actionable": actionable_rows,
        "legacy_revoked": legacy_rows,
    }

    def _section_lines(title: str, rows: list[dict[str, Any]]) -> list[str]:
        lines = ["", f"[{title}]"]
        if not rows:
            lines.append("  (none)")
            return lines
        for row in rows:
            lines.append(
                f"  {row['member_id']:20s} role={row['role']:20s} "
                f"status={row['status']:10s} "
                f"created_at={row['created_at']:20s} "
                f"has_token={row['has_token']!s}"
            )
        return lines

    return CommandResult(
        data=payload,
        text=(
            f"  recommended_action : {payload['recommended_action']}",
            f"  valid_roles        : {', '.join(valid_roles)}",
            f"  actionable         : {payload['actionable_count']}건",
            f"  legacy_revoked     : {payload['legacy_revoked_count']}건",
            *_section_lines("actionable", actionable_rows),
            *_section_lines("legacy_revoked", legacy_rows),
        ),
    )


def _parse_scope_csv(scopes: str) -> list[str]:
    """정확히 빈 문자열만 빈 목록으로, 그 밖의 빈 조각은 ``""`` 원소로 남긴다."""
    if scopes == "":
        return []
    return [s.strip() for s in scopes.split(",")]


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
@require_master
def member_register(
    ctx: click.Context,
    member_id: str,
    member_type: str,
    org: str,
    name: str,
    scopes: str,
) -> CommandResult:
    """멤버 등록 (토큰 발급)."""
    actor = get_member_id(ctx)
    scope_list = _parse_scope_csv(scopes)

    async def _run_register() -> tuple[dict[str, Any], str]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            payload = await ipc_send(
                "member.register",
                {
                    "member_id": member_id,
                    "member_type": member_type,
                    "org": org,
                    "name": name,
                    "scopes": scope_list,
                },
                actor=actor,
                required=("token",),
            )
            token = payload["token"]
            return {
                "member_id": payload.get("member_id", member_id),
                "type": payload.get("type", member_type),
                "role": payload.get("role", ""),
                "org": payload.get("org", org),
                "name": payload.get("name", name),
            }, token

        async with _create_service(ctx) as service:
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

    try:
        result, token = _run(_run_register())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None

    return CommandResult(
        data={**result, "token": token},
        text=(
            "멤버 등록 완료",
            f"  토큰: {token}",
            "  이 토큰은 다시 표시되지 않습니다.",
        ),
    )


@member.command("set-emoji")
@click.argument("member_id")
@click.argument("emoji")
@click.pass_context
@require_auth
@require_master
def member_set_emoji(ctx: click.Context, member_id: str, emoji: str) -> CommandResult:
    """멤버 이모지 설정/변경."""
    actor = get_member_id(ctx)

    async def _run_set_emoji() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "member.set_emoji",
                {"member_id": member_id, "emoji": emoji},
                actor=actor,
            )

        async with _create_service(ctx) as service:
            m = await service.update_emoji(member_id, emoji, updated_by=actor)
            return {"member_id": m.member_id, "emoji": m.emoji}

    try:
        result = _run(_run_set_emoji())
    except MemberNotFoundError:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}") from None

    return CommandResult(
        data=result, message=f"이모지 설정 완료: {member_id} → {result['emoji']}"
    )


@member.command("update-scopes")
@click.argument("member_id")
@click.option(
    "--scopes",
    required=True,
    help="권한 범위 목록 (쉼표 구분, 빈 문자열은 권한 없음)",
)
@format_option
@click.pass_context
@require_auth
@require_master
def member_update_scopes(
    ctx: click.Context, member_id: str, scopes: str
) -> CommandResult:
    """멤버 권한 범위 변경."""
    actor = get_member_id(ctx)
    scope_list = _parse_scope_csv(scopes)

    async def _run_update_scopes() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "member.update_scopes",
                {"member_id": member_id, "scopes": scope_list},
                actor=actor,
            )

        async with _create_service(ctx) as service:
            m = await service.update_scopes(
                member_id,
                scope_list,
                updated_by=actor,
            )
            return {
                "member_id": m.member_id,
                "scopes": m.scopes,
                "status": m.status,
            }

    try:
        result = _run(_run_update_scopes())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None

    return CommandResult(data=result, text=(f"멤버 권한 변경 완료: {member_id}",))


@member.command("suspend")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_master
def member_suspend(ctx: click.Context, member_id: str) -> CommandResult:
    """멤버 일시 정지."""
    actor = get_member_id(ctx)

    async def _run_suspend() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "member.suspend",
                {"member_id": member_id},
                actor=actor,
            )

        async with _create_service(ctx) as service:
            m = await service.suspend(member_id, suspended_by=actor)
            return {"member_id": m.member_id, "status": m.status}

    try:
        result = _run(_run_suspend())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None
    except MemberNotFoundError:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}") from None

    return CommandResult(data=result, message=f"멤버 정지 완료: {member_id}")


@member.command("reactivate")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_master
def member_reactivate(ctx: click.Context, member_id: str) -> CommandResult:
    """멤버 재활성화."""
    actor = get_member_id(ctx)

    async def _run_reactivate() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "member.reactivate",
                {"member_id": member_id},
                actor=actor,
            )

        async with _create_service(ctx) as service:
            m = await service.reactivate(member_id, reactivated_by=actor)
            return {"member_id": m.member_id, "status": m.status}

    try:
        result = _run(_run_reactivate())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None
    except MemberNotFoundError:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}") from None

    return CommandResult(data=result, message=f"멤버 재활성화 완료: {member_id}")


@member.command("revoke")
@click.argument("member_id")
@click.option(
    "--yes",
    "yes",
    is_flag=True,
    default=False,
    help="삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패",
)
@click.pass_context
@require_auth
@require_master
def member_revoke(ctx: click.Context, member_id: str, yes: bool) -> CommandResult:
    """멤버 영구 폐기.

    ``--yes`` 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED`` 에러로 종료한다.
    """
    actor = get_member_id(ctx)

    if not yes:
        raise CliConfirmationRequiredError(
            "위험 명령입니다. --yes를 명시해야 멤버를 폐기합니다."
            " 이 작업은 되돌릴 수 없습니다."
        )

    async def _run_revoke() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "member.revoke",
                {"member_id": member_id},
                actor=actor,
            )

        async with _create_service(ctx) as service:
            m = await service.revoke(member_id, revoked_by=actor)
            return {"member_id": m.member_id, "status": m.status}

    try:
        result = _run(_run_revoke())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None
    except MemberNotFoundError:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}") from None

    return CommandResult(data=result, message=f"멤버 폐기 완료: {member_id}")


@member.command("rotate-token")
@click.argument("member_id")
@click.pass_context
@require_auth
@require_master
def member_rotate_token(ctx: click.Context, member_id: str) -> CommandResult:
    """토큰 재발급 (기존 토큰 즉시 무효화)."""
    actor = get_member_id(ctx)

    async def _run_rotate() -> tuple[dict[str, Any], str]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            payload = await ipc_send(
                "member.rotate_token",
                {"member_id": member_id},
                actor=actor,
                required=("token",),
            )
            return {"member_id": payload.get("member_id", member_id)}, payload["token"]

        async with _create_service(ctx) as service:
            m, token = await service.rotate_token(member_id, rotated_by=actor)
            return {"member_id": m.member_id}, token

    try:
        result, token = _run(_run_rotate())
    except PermissionDeniedError:
        raise PermissionDeniedError(_MASTER_REQUIRED_MESSAGE) from None
    except MemberNotFoundError:
        raise CliMemberNotFoundError(f"멤버를 찾을 수 없습니다: {member_id}") from None

    return CommandResult(
        data={**result, "token": token},
        text=(
            "  기존 토큰이 즉시 무효화되었습니다.",
            f"  새 토큰: {token}",
            "  이 토큰은 다시 표시되지 않습니다.",
        ),
    )


@member.command("reset-password")
@click.option("--recovery-key", required=True, help="Recovery Key")
@click.option(
    "--new-password-env",
    "new_password_env",
    default=None,
    help="새 패스워드를 담은 환경변수의 *이름* (값이 아닌 변수명만 받음)",
)
@click.option(
    "--new-password-file",
    "new_password_file",
    default=None,
    type=click.Path(dir_okay=False),
    help="새 패스워드를 담은 파일의 경로 (파일 내용 strip)",
)
@click.pass_context
def member_reset_password(
    ctx: click.Context,
    recovery_key: str,
    new_password_env: str | None,
    new_password_file: str | None,
) -> CommandResult:
    """Recovery Key로 패스워드 리셋 (인증 불필요).

    새 패스워드는 ``--new-password-env <ENV_NAME>`` 또는
    ``--new-password-file <PATH>``로만 받으며, 둘 다 없거나 둘 다 지정하면 prompt
    없이 ``CLI_MISSING_REQUIRED_INPUT``로 실패한다.
    """
    fmt = get_formatter(ctx)
    new_password = _resolve_secret_non_interactive(
        fmt,
        env_name=new_password_env,
        file_path=new_password_file,
        env_option_label="--new-password-env",
        file_option_label="--new-password-file",
        missing_input_message="새 패스워드 입력이 필요합니다.",
    )

    async def _run_reset() -> None:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            await ipc_send(
                "member.reset_password",
                {"recovery_key": recovery_key, "new_password": new_password},
            )
            return

        async with _create_service(ctx) as service:
            members = await service.list_members(member_type="human")
            master = next((m for m in members if m.role == "master"), None)
            if not master:
                msg = "master 멤버가 존재하지 않습니다"
                raise ValueError(msg)
            await service.reset_password(master.member_id, recovery_key, new_password)

    _run(_run_reset())

    return CommandResult(message="패스워드가 변경되었습니다.")


@member.command("regenerate-recovery-key")
@click.option(
    "--password-env",
    "password_env",
    default=None,
    help="현재 패스워드를 담은 환경변수의 *이름* (값이 아닌 변수명만 받음)",
)
@click.option(
    "--password-file",
    "password_file",
    default=None,
    type=click.Path(dir_okay=False),
    help="현재 패스워드를 담은 파일의 경로 (파일 내용 strip)",
)
@click.pass_context
def member_regenerate_recovery_key(
    ctx: click.Context,
    password_env: str | None,
    password_file: str | None,
) -> CommandResult:
    """Recovery Key 재발급 (인증 불필요).

    현재 패스워드는 ``--password-env <ENV_NAME>`` 또는 ``--password-file <PATH>``로만
    받으며, 둘 다 없거나 둘 다 지정하면 prompt 없이 ``CLI_MISSING_REQUIRED_INPUT``로
    실패한다.
    """
    fmt = get_formatter(ctx)
    password = _resolve_secret_non_interactive(
        fmt,
        env_name=password_env,
        file_path=password_file,
        env_option_label="--password-env",
        file_option_label="--password-file",
        missing_input_message="현재 패스워드 입력이 필요합니다.",
    )

    async def _run_regen() -> str:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            payload = await ipc_send(
                "member.regenerate_recovery_key",
                {"password": password},
                required=("recovery_key",),
            )
            return cast("str", payload["recovery_key"])

        async with _create_service(ctx) as service:
            members = await service.list_members(member_type="human")
            master = next((m for m in members if m.role == "master"), None)
            if not master:
                msg = "master 멤버가 존재하지 않습니다"
                raise ValueError(msg)
            return await service.regenerate_recovery_key(master.member_id, password)

    new_key = _run(_run_regen())

    return CommandResult(
        data={"recovery_key": new_key},
        text=(
            "  기존 복구 키가 폐기되었습니다.",
            "",
            f"  새 복구 키: {new_key}",
            "",
            "  안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.",
        ),
    )
