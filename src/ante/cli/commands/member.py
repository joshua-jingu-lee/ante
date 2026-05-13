"""ante member — 멤버 관리 커맨드.

비대화형 입력 계약(SSOT: docs/specs/cli/02-design-decisions.md):
- ``member revoke``는 ``--yes`` 누락 시 prompt 없이
  ``CLI_CONFIRMATION_REQUIRED``로 실패한다.
- ``member reset-password`` / ``member regenerate-recovery-key``는 비밀값을
  ``--*-env <ENV_NAME>`` 또는 ``--*-file <PATH>`` 채널로만 받는다. 누락/공란/중복은
  도메인 prefix 에러 코드(``MEMBER_PASSWORD_ENV_NOT_SET``,
  ``MEMBER_PASSWORD_FILE_NOT_FOUND``, ``CLI_MISSING_REQUIRED_INPUT``)로 실패한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.member.errors import PermissionDeniedError
from ante.member.models import MemberRole
from ante.member.scopes import InvalidScopeError

logger = logging.getLogger(__name__)

# CLI 핸들러에서 master guard 위반을 사용자 친화 메시지로 종료하기 위한 메시지.
# ``MemberService._assert_master``가 raise하는 ``PermissionDeniedError``는 Python
# 내장 ``PermissionError``와 별개 계열(``MemberError`` → ``Exception``)이라 기존
# ``except (ValueError, PermissionError)``로는 잡히지 않고 traceback이 노출된다
# (이슈 #1351 1차 Codex review FAIL — Finding 2). suspend / reactivate / revoke /
# rotate-token 등 master 검증이 추가된 모든 CLI 핸들러에서 동일 메시지로 종료한다.
_MASTER_REQUIRED_MESSAGE = "권한이 없습니다: master만 수행할 수 있습니다."


@click.group()
def member() -> None:
    """멤버 등록·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_secret_non_interactive(
    fmt,  # noqa: ANN001
    *,
    env_name: str | None,
    file_path: str | None,
    env_option_label: str,
    file_option_label: str,
    missing_input_message: str,
) -> str:
    """``--*-env`` / ``--*-file`` 채널에서 비밀값을 비대화형으로 읽어들인다.

    - 둘 다 없으면 ``CLI_MISSING_REQUIRED_INPUT``로 실패한다.
    - 둘 다 지정되면 (상호 배타) ``CLI_MISSING_REQUIRED_INPUT``로 실패한다.
    - env 부재/공란이면 ``MEMBER_PASSWORD_ENV_NOT_SET``로 실패한다.
    - file 부재/읽기 실패/공란이면 ``MEMBER_PASSWORD_FILE_NOT_FOUND``로 실패한다.

    실패는 모두 ``fmt.error(..., code=...)`` 출력 후 ``SystemExit(1)``로 종료한다.
    """
    if env_name is None and file_path is None:
        fmt.error(
            missing_input_message
            + f" {env_option_label} 또는 {file_option_label} 중 하나를 지정하세요.",
            code="CLI_MISSING_REQUIRED_INPUT",
        )
        raise SystemExit(1)

    if env_name is not None and file_path is not None:
        fmt.error(
            f"{env_option_label}와 {file_option_label}는 동시에 지정할 수 없습니다."
            " 둘 중 하나만 사용하세요.",
            code="CLI_MISSING_REQUIRED_INPUT",
        )
        raise SystemExit(1)

    if env_name is not None:
        value = os.environ.get(env_name)
        if value is None or value.strip() == "":
            fmt.error(
                f"환경변수 {env_name}이(가) 설정되어 있지 않거나 공란입니다."
                f" {env_option_label}는 비밀값이 든 환경변수의 *이름*만 받습니다.",
                code="MEMBER_PASSWORD_ENV_NOT_SET",
            )
            raise SystemExit(1)
        return value.strip()

    # file_path is not None
    assert file_path is not None  # noqa: S101 — 위 분기로 보장
    path = Path(file_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        fmt.error(
            f"{file_option_label} 파일을 읽을 수 없습니다: {file_path} ({e})",
            code="MEMBER_PASSWORD_FILE_NOT_FOUND",
        )
        raise SystemExit(1) from e
    value = raw.strip()
    if value == "":
        fmt.error(
            f"{file_option_label} 파일이 비어 있습니다: {file_path}",
            code="MEMBER_PASSWORD_FILE_NOT_FOUND",
        )
        raise SystemExit(1)
    return value


async def _create_service():  # noqa: ANN202
    """CLI용 MemberService 인스턴스 생성."""
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    service = MemberService(db, eventbus)
    await service.initialize()
    return service, db


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


def _invalid_role_row_dict(m) -> dict:  # noqa: ANN001
    """``Member`` row 를 CLI 출력용 dict 로 변환.

    ``token_hash`` 는 보안상 절대 노출하지 않는다 (#1468 secret-exposure). 토큰
    존재 여부는 ``has_token: bool`` 로만 표현하고 만료시각은 그대로 표시한다.
    ``valid_roles`` 는 row-level 이 아니라 top-level scan summary 에만 노출한다.
    """
    has_token = bool(m.token_hash)
    return {
        "member_id": m.member_id,
        "role": m.role,
        "type": m.type,
        "name": m.name,
        "status": m.status,
        "created_at": m.created_at,
        "has_token": has_token,
        "token_expires_at": m.token_expires_at or None,
        # ``member revoke`` 는 ``--yes`` 누락 시 ``CLI_CONFIRMATION_REQUIRED`` 로
        # 실패하므로 (`member_revoke` 본문 참조), JSON payload 의 권장 명령은
        # ``--yes`` 를 포함해 즉시 실행 가능하게 출력한다.
        "revoke_command": f"ante member revoke {m.member_id} --yes",
    }


@member.command("list-invalid-roles")
@format_option
@click.pass_context
@require_auth
@require_scope("member:read")
def member_list_invalid_roles(
    ctx: click.Context,
) -> None:
    """``MemberRole`` enum 외 role 을 가진 legacy member row 식별 (#1468).

    본 명령은 canonical config 의 ``db.path`` (``get_db_path()``) 단일 DB 에
    대해서만 invalid-role row 를 식별한다. 다른 DB 파일 대상 점검은 본 PR scope
    가 아니며, 필요하면 별도 이슈로 분리한다.

    ``actionable`` 카테고리는 ``status != revoked`` 인 invalid-role row 이며,
    운영자가 ``ante member revoke <member_id> --yes`` 로 cleanup 해야 한다.
    ``legacy_revoked`` 는 이미 revoke 된 historical row 다.

    분류는 ``offline`` 이지만 ``MemberService.initialize()`` 가 schema migration
    DDL 을 수반한다 — 따라서 "read-only" 가 아니다. ``ante member list`` /
    ``info`` 와 동일한 ``_create_service()`` 패턴을 사용하며 runtime IPC 는
    우회한다.

    ``token_hash`` 는 모든 출력 모드에서 노출되지 않는다 (보안 SSOT).
    """
    fmt = get_formatter(ctx)
    valid_roles = [member.value for member in MemberRole]

    async def _run_scan() -> tuple[list[dict], list[dict]]:
        service, db = await _create_service()
        try:
            scan = await service.find_invalid_role_members()
            actionable = [_invalid_role_row_dict(m) for m in scan.actionable]
            legacy = [_invalid_role_row_dict(m) for m in scan.legacy_revoked]
            return actionable, legacy
        finally:
            await db.close()

    actionable_rows, legacy_rows = _run(_run_scan())

    # structured log: 운영자가 invocation 시점마다 count 흐름을 추적한다.
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

    if fmt.is_json:
        fmt.output(payload)
        return

    # text 모드 — 두 섹션 분리.
    click.echo(f"  recommended_action : {payload['recommended_action']}")
    click.echo(f"  valid_roles        : {', '.join(valid_roles)}")
    click.echo(f"  actionable         : {payload['actionable_count']}건")
    click.echo(f"  legacy_revoked     : {payload['legacy_revoked_count']}건")

    def _emit_section(title: str, rows: list[dict]) -> None:
        click.echo("")
        click.echo(f"[{title}]")
        if not rows:
            click.echo("  (none)")
            return
        for row in rows:
            click.echo(
                f"  {row['member_id']:20s} role={row['role']:20s} "
                f"status={row['status']:10s} "
                f"created_at={row['created_at']:20s} "
                f"has_token={row['has_token']!s}"
            )

    _emit_section("actionable", actionable_rows)
    _emit_section("legacy_revoked", legacy_rows)


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
    except PermissionDeniedError:
        fmt.error(_MASTER_REQUIRED_MESSAGE)
        raise SystemExit(1) from None
    except InvalidScopeError as e:
        # SCOPE_VOCABULARY (#1439) 위반은 ``ValueError`` 서브클래스이지만
        # CLI direct path 회귀를 위해 비-0 exit code 로 명시 종료한다.
        # 다음 분기의 ``except (ValueError, ...)`` 가 먼저 매칭되면 ``return``
        # 으로 빠져 exit code 0 이 되므로 별도 분기로 둔다.
        fmt.error(str(e), code="MEMBER_INVALID_SCOPE")
        raise SystemExit(1) from None
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
    except PermissionDeniedError:
        fmt.error(_MASTER_REQUIRED_MESSAGE)
        raise SystemExit(1) from None
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
    except PermissionDeniedError:
        fmt.error(_MASTER_REQUIRED_MESSAGE)
        raise SystemExit(1) from None
    except (ValueError, PermissionError) as e:
        fmt.error(str(e))
        return

    fmt.success(f"멤버 재활성화 완료: {member_id}", result)


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
@require_scope("member:admin")
def member_revoke(ctx: click.Context, member_id: str, yes: bool) -> None:
    """멤버 영구 폐기.

    ``--yes`` 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED`` 에러로 종료한다.
    """
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    if not yes:
        fmt.error(
            "위험 명령입니다. --yes를 명시해야 멤버를 폐기합니다."
            " 이 작업은 되돌릴 수 없습니다.",
            code="CLI_CONFIRMATION_REQUIRED",
        )
        raise SystemExit(1)

    async def _run_revoke() -> dict:
        service, db = await _create_service()
        try:
            m = await service.revoke(member_id, revoked_by=actor)
            return {"member_id": m.member_id, "status": m.status}
        finally:
            await db.close()

    try:
        result = _run(_run_revoke())
    except PermissionDeniedError:
        fmt.error(_MASTER_REQUIRED_MESSAGE)
        raise SystemExit(1) from None
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
    except PermissionDeniedError:
        fmt.error(_MASTER_REQUIRED_MESSAGE)
        raise SystemExit(1) from None
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
) -> None:
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
        service, db = await _create_service()
        try:
            members = await service.list_members(member_type="human")
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
) -> None:
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
        service, db = await _create_service()
        try:
            members = await service.list_members(member_type="human")
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
