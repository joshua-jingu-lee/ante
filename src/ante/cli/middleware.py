"""CLI 인증 미들웨어 — 토큰 인증 + 권한 검증."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import TYPE_CHECKING, Any, cast

import click

from ante.cli.formatter import CommandResult, OutputFormatter
from ante.contracts.cli_errors import (
    CliAuthFailedError,
    CliAuthRequiredError,
    CliPermissionDeniedError,
)
from ante.contracts.cli_registry import get_contract
from ante.contracts.helpers import error_spec_for_exception, ipc_error_payload

if TYPE_CHECKING:
    from collections.abc import Callable

    from ante.member.models import Member

logger = logging.getLogger(__name__)

_AUTH_EXEMPT_COMMAND_PATHS: set[tuple[str, ...]] = {
    ("init",),
    ("member", "reset-password"),
    ("member", "regenerate-recovery-key"),
}

_ENCRYPTION_EXEMPT_COMMAND_PATHS: set[tuple[str, ...]] = {
    ("init",),
    ("member", "reset-password"),
    ("member", "regenerate-recovery-key"),
    ("feed", "init"),
}


def _resolve_token() -> str:
    """ANTE_MEMBER_TOKEN을 환경변수 또는 토큰 파일에서 확보한다."""
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

    path = _get_invoked_command_path(ctx)
    if path is not None and path in _AUTH_EXEMPT_COMMAND_PATHS:
        ctx.obj["member"] = None
        return

    token = _resolve_token()
    if not token:
        ctx.obj["member"] = None
        return

    try:
        from ante.cli.main import get_db_path

        member = _run_authenticate(token, get_db_path(ctx))
        ctx.obj["member"] = member
        logger.debug("CLI 인증 성공: %s", member.member_id)
    except PermissionError as e:
        raise CliAuthFailedError(f"인증 실패: {e}") from e


def _run_authenticate(token: str, db_path: str) -> Member:
    """동기 컨텍스트에서 MemberService.authenticate 호출."""
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    async def _auth() -> Member:
        db = Database(db_path)
        try:
            await db.connect()
        except Exception as e:
            try:
                await db.close()
            except Exception:
                logger.debug(
                    "db.close() after failed connect raised — ignored", exc_info=True
                )
            msg = (
                f"DB 접근 불가 ({db_path}): {e}. "
                "`ante init --dir <config_dir>` 이후 동일 `--config-dir`로 실행하세요."
            )
            raise PermissionError(msg) from e
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus)
            await service.initialize()
            return await service.authenticate(token)
        finally:
            await db.close()

    return asyncio.run(_auth())


def _emit_command_result(ctx: click.Context, rv: object) -> None:
    if not isinstance(rv, CommandResult):
        return
    path = tuple(ctx.obj.get("_leaf_command_path", ()))
    contract = get_contract(path)
    if contract is None:
        raise TypeError(f"CommandResult from {path!r} without a CLI contract")
    if contract.output.envelope != "standard":
        raise TypeError(
            f"CommandResult from {path!r} with envelope "
            f"{contract.output.envelope!r}; the contract must be 'standard'"
        )
    data = rv.data
    if isinstance(data, list):
        if contract.output.data_key is None:
            raise TypeError(f"list data from {path!r} needs a contract data_key")
        data = {contract.output.data_key: data}
    fmt: OutputFormatter = ctx.obj["formatter"]
    if fmt.is_json or rv.text is None:
        fmt.success(rv.message, data)
        return
    for line in rv.text:
        click.echo(line)


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


def require_auth(fn: Callable[..., Any]) -> Callable[..., Any]:
    """인증 필수 데코레이터.

    @click.pass_context 아래에 배치한다.
    ctx.obj["member"]가 None이면 ``CliAuthRequiredError``를 던진다.

    멱등(idempotent) — 이미 같은 가드가 부착된 함수에 재적용되어도 한 번만
    감싸지도록 ``_require_auth_applied`` sentinel marker로 dedupe한다.
    """
    if getattr(fn, "_require_auth_applied", False):
        return fn

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        ctx = click.get_current_context()
        member = ctx.obj.get("member")
        if member is None:
            raise CliAuthRequiredError(
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
            )
        return fn(*args, **kwargs)

    wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    return wrapper


def require_master(fn: Callable[..., Any]) -> Callable[..., Any]:
    """master-only 데코레이터 (HUMAN type + master role만 통과).

    멱등(idempotent) — 이미 ``require_master`` 가 부착된 함수에 재적용되어도
    한 번만 감싸지도록 자체 ``_require_master_applied`` sentinel marker 로
    dedupe 한다. ``_require_auth_applied`` 를 dedupe key 로 쓰면, callback 에
    ``@require_auth`` 가 먼저 적용되어 있을 때 ``@require_master`` 가 자체 wrap
    을 건너뛰어 master 검증이 발화하지 않는 idempotent 버그가 생기므로 자체
    marker 를 분리한다.
    """
    if getattr(fn, "_require_master_applied", False):
        return fn

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        from ante.member.models import MemberRole, MemberType

        ctx = click.get_current_context()
        member: Member | None = (
            ctx.obj.get("member") if isinstance(ctx.obj, dict) else None
        )
        if member is None:
            raise CliAuthRequiredError(
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
            )

        member_type_value = getattr(member.type, "value", member.type)
        member_role_value = getattr(member.role, "value", member.role)
        if (
            member_type_value != MemberType.HUMAN.value
            or member_role_value != MemberRole.MASTER.value
        ):
            raise CliPermissionDeniedError("이 작업은 master 권한이 필요합니다.")

        return fn(*args, **kwargs)

    wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    wrapper._require_master_applied = True  # type: ignore[attr-defined]
    return wrapper


def require_scope(*scopes: str) -> Callable[..., Any]:
    """권한 검증 데코레이터.

    @click.pass_context 아래에 배치한다.
    Human 멤버(master, admin)는 scope 제한 없이 통과.
    Agent 멤버는 등록된 scope에 필요 scope가 모두 포함되어야 한다.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            from ante.member.models import MemberType

            ctx = click.get_current_context()
            member: Member | None = ctx.obj.get("member")
            if member is None:
                raise CliAuthRequiredError(
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
                )

            if member.type == MemberType.HUMAN:
                return fn(*args, **kwargs)

            missing = [s for s in scopes if s not in member.scopes]
            if missing:
                raise CliPermissionDeniedError(
                    f"권한이 부족합니다. 필요 권한: {', '.join(missing)}"
                )

            return fn(*args, **kwargs)

        wrapper._required_scopes = scopes  # type: ignore[attr-defined]
        wrapper._require_auth_applied = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def enforce_scope(ctx: click.Context, *scopes: str) -> None:
    """명령 내부에서 조건부로 scope를 검증한다(imperative).

    ``require_scope`` 데코레이터와 동일 규칙을 적용한다:

    - ``ctx.obj["member"]`` 가 ``None`` 이면 ``CliAuthRequiredError``
      (``auth_required``).
    - Agent 멤버는 ``scopes`` 를 모두 보유해야 한다. 부족 시
      부족 scope를 담은 ``CliPermissionDeniedError`` (``permission_denied``).
    """
    from ante.member.models import MemberType

    member: Member | None = ctx.obj.get("member")
    if member is None:
        raise CliAuthRequiredError(
            "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
        )

    if member.type == MemberType.HUMAN:
        return

    missing = [s for s in scopes if s not in member.scopes]
    if missing:
        raise CliPermissionDeniedError(
            f"권한이 부족합니다. 필요 권한: {', '.join(missing)}"
        )


def get_member_id(ctx: click.Context) -> str:
    """인증된 멤버 ID를 반환. 미인증 시 'unknown'."""
    member: Member | None = ctx.obj.get("member")
    return member.member_id if member else "unknown"


class _LeafPathMixin(click.Group):
    """root부터 leaf까지의 커맨드 경로 tuple을 ``ctx.obj``에 저장하는 mixin.

    ``LeafAwareGroup``(main.py) 및 :class:`AuthenticatedGroup`이 공유한다.
    """

    def invoke(self, ctx: click.Context) -> object:
        ctx.ensure_object(dict)
        all_args = [*ctx.protected_args, *ctx.args]
        path = self._resolve_command_path(ctx, all_args)
        if path:
            ctx.obj["_leaf_command_path"] = path
            ctx.obj["_leaf_command"] = path[-1]
        return super().invoke(ctx)

    def _resolve_command_path(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str, ...]:
        """root부터 leaf까지의 커맨드 경로 tuple을 반환."""
        cmd: click.Command = self
        path: list[str] = []
        i = 0
        while i < len(args) and isinstance(cmd, click.Group):
            token = args[i]
            if token.startswith("-"):
                i += 1
                continue
            sub = cmd.get_command(ctx, token)
            if sub is None:
                break
            path.append(token)
            cmd = sub
            i += 1
        return tuple(path)


class AuthenticatedGroup(_LeafPathMixin):
    """default-deny 인증 게이트가 자동으로 부착되는 ``click.Group``.

    정책 SSOT:

    - `D-015 default-deny 인증 게이트 <../decisions/D-015-default-deny-auth-gate.md>`_
    - `cli/02-design-decisions.md — default-deny CLI 인증 게이트`
    - `cli/03-commands.md — 공개 명령 allowlist`

    동작:

    1. **invoke 단계 가드 (primary, H2 강화)**:
       ``Group.invoke(ctx)`` 진입 직후 ``super().invoke(ctx)`` 호출 **전에**
       인증 가드를 발화시킨다. click 8.1의 ``MultiCommand.invoke``는 자식
       명령의 ``make_context``(=``parse_args``)를 ``super().invoke(ctx)`` 내부
       에서 호출하므로, 가드를 ``super().invoke(ctx)`` 직전에 두면 자식
       명령의 type/argument validation(예: ``click.Path(exists=True)``)이
       발화하기 **전에** 인증 검사가 끝난다. 미인증 사용자는 어떤 형태의
       parameter validation 응답도 받을 수 없다.

       단, 다음 경로는 invoke 단계 가드를 skip한다:

       - ``ctx.resilient_parsing == True``: shell completion 등 부작용 없는
         파싱.
       - args 토큰열에 ``--help`` / ``-h`` 메타 옵션이 포함되어 있고, 그
         토큰이 ``--`` separator **앞**에 있는 경우 (click이 도움말로 처리해
         callback에 도달하지 않으므로 H1 invariant 만족).
       - ``--version`` 은 root ``@click.version_option`` 이 root callback 진입
         이전에 ``ctx.exit()`` 시키므로 ``ante --version`` 만 면제되고, nested
         위치(``ante bot list --version`` 등) 는 invoke 단계 가드가 정상
         발화한다.
       - 경로 해석이 leaf command까지 도달하지 못한 경우(=group으로 끝남):
         click이 ``no_args_is_help`` 또는 ``Missing command`` 처리로
         callback에 도달하지 않는다.
       - 경로가 ``_AUTH_EXEMPT_COMMAND_PATHS`` allowlist에 포함되는 경우.

    2. **callback 단계 가드 (secondary, 이중 방어)**:
       :meth:`add_command`에서 자식 ``click.Command``의 ``callback``을
       ``_wrap_callback_with_auth``로 감싼다. invoke 단계 가드가 어떤
       이유로든 발화하지 못해도 callback 진입 직전에 같은 정책이 발화한다.
       두 가드는 idempotent(sentinel marker로 dedupe)하므로
       ``authenticate_member`` 가 한 번만 실행된다.

    3. ``ante <cmd> -- --help``처럼 ``--`` 이후 위치 인자로 들어간 ``--help``는
       click이 도움말로 해석하지 않으므로 invoke 단계에서 default-deny가
       발화한다 — H2 invariant 만족.

    자식 group이 같은 정책 클래스를 상속하지 않더라도, leaf callback wrapping은
    ``Group.add_command``/``Group.command`` decorator 양쪽에서 자동으로 이뤄지므로
    nested sub-group의 leaf까지 default-deny가 도달한다.
    """

    def invoke(self, ctx: click.Context) -> object:
        """``super().invoke(ctx)`` 호출 전에 인증 게이트를 발화시킨다.

        click의 ``MultiCommand.invoke``는 ``super().invoke(ctx)`` 내부에서
        자식 명령의 ``make_context`` (=``parse_args``)를 호출한다. 따라서
        본 메서드에서 가드를 먼저 발화시키면 자식 명령의
        ``click.Path(exists=True)`` 같은 parameter type validation이
        인증 검사 **이전에** 트리거되는 H2 invariant 위반을 막을 수 있다.
        """
        ctx.ensure_object(dict)
        all_args = [*ctx.protected_args, *ctx.args]
        path = self._resolve_command_path(ctx, all_args)
        if path:
            ctx.obj["_leaf_command_path"] = path
            ctx.obj["_leaf_command"] = path[-1]

        _mirror_root_globals_to_obj(ctx)

        if self._should_enforce_encryption_gate(ctx, all_args, path):
            self._enforce_db_encryption_key_gate(ctx)

        if self._should_invoke_auth_gate(ctx, all_args, path):
            self._enforce_invoke_auth_gate(ctx, path)

        rv = super(_LeafPathMixin, self).invoke(ctx)
        _emit_command_result(ctx, rv)
        return rv

    def _should_enforce_encryption_gate(
        self,
        ctx: click.Context,
        all_args: list[str],
        path: tuple[str, ...],
    ) -> bool:
        """DB encryption key chokepoint 발화 여부."""
        if ctx.resilient_parsing:
            return False
        if _has_meta_help_before_dashdash(all_args):
            return False
        if not path:
            return False
        if not self._path_resolves_to_leaf(ctx, path):
            return False
        if path in _ENCRYPTION_EXEMPT_COMMAND_PATHS:
            return False
        return True

    def _enforce_db_encryption_key_gate(self, ctx: click.Context) -> None:
        """DB encryption key chokepoint 본체 — 실패 시 ``EncryptionKeyError`` 하위."""
        import tomllib

        from ante.account.crypto import (
            EncryptionKeyInvalidError,
            EncryptionKeyMissingError,
            _validate_fernet_key,
        )
        from ante.cli.main import get_config_dir
        from ante.config.config import Config
        from ante.config.exceptions import ConfigError

        try:
            Config.load(config_dir=get_config_dir(ctx))
        except (OSError, tomllib.TOMLDecodeError, ConfigError) as exc:
            logger.debug(
                "Config.load failed in DB encryption chokepoint; "
                "falling back to env-only validation: %s",
                exc,
            )

        key = os.environ.get("ANTE_DB_ENCRYPTION_KEY")
        if not key:
            raise EncryptionKeyMissingError(
                "ANTE_DB_ENCRYPTION_KEY 환경변수가 설정되지 않았습니다. "
                "`ante init` 또는 `secrets.env` 의 키 행을 확인하세요."
            )
        if not _validate_fernet_key(key):
            raise EncryptionKeyInvalidError(
                "ANTE_DB_ENCRYPTION_KEY 형식이 유효하지 않습니다 "
                "(Fernet.generate_key() 출력 형식이어야 합니다)."
            )

        if isinstance(ctx.obj, dict):
            ctx.obj["_db_encryption_key_validated"] = True

    def _should_invoke_auth_gate(
        self,
        ctx: click.Context,
        all_args: list[str],
        path: tuple[str, ...],
    ) -> bool:
        """invoke 단계 인증 게이트를 발화할지 여부."""
        if ctx.resilient_parsing:
            return False

        if _has_meta_help_before_dashdash(all_args):
            return False

        if not path:
            return False
        if not self._path_resolves_to_leaf(ctx, path):
            return False

        if path in _AUTH_EXEMPT_COMMAND_PATHS:
            return False

        return True

    def _path_resolves_to_leaf(self, ctx: click.Context, path: tuple[str, ...]) -> bool:
        """경로가 leaf(=non-Group ``click.Command``)로 끝나는지 확인."""
        cmd: click.Command = self
        for name in path:
            if not isinstance(cmd, click.Group):
                return False
            sub = cmd.get_command(ctx, name)
            if sub is None:
                return False
            cmd = sub
        return not isinstance(cmd, click.Group)

    def _enforce_invoke_auth_gate(
        self, ctx: click.Context, path: tuple[str, ...]
    ) -> None:
        """invoke 단계 인증 게이트 본체 — 실패 시 ``CliAuthRequiredError``."""
        from ante.cli import main as _main

        _main.authenticate_member(ctx)

        member = ctx.obj.get("member") if isinstance(ctx.obj, dict) else None
        if member is None:
            raise CliAuthRequiredError(
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
            )

        ctx.obj["_auth_gate_invoked"] = True

    def add_command(self, cmd: click.Command, name: str | None = None) -> None:
        """등록되는 자식 command/group에 인증 가드를 자동 부착 (이중 방어)."""
        _attach_auth_guard_recursive(cmd)
        super().add_command(cmd, name)

    def main(  # type: ignore[override]
        self,
        args: list[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: object,
    ) -> object:
        """``BaseCommand.main`` 오버라이드 — 명령 밖으로 나온 예외의 단일 출구.

        ``--format`` raw 토큰을 sniff 해 json 모드면 click 을 ``standalone_mode=False``
        로 불러 ``UsageError`` 와 ``ClickException`` 을 envelope 으로 낸다.
        텍스트 모드의 click 예외는 click 기본 동작(``UsageError`` 는 exit 2)을 따른다.
        처리되지 않은 ``Exception`` 은 두 모드 모두 에러 레지스트리의 코드로 끝난다.
        json 모드는 envelope, 텍스트 모드는 stderr 의 ``Error: <code>: <message>`` 한
        줄(메시지가 이미 ``<code>: `` 로 시작하면 접두를 다시 붙이지 않는다)이고, 종료
        코드는 ``ErrorSpec.exit_code`` (0 이면 1) 이다.
        """
        output_format = self._sniff_output_format(args)
        if output_format != "json" and not standalone_mode:
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )

        try:
            rv = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=output_format != "json",
                **extra,
            )
        except click.UsageError as e:
            from ante.cli.formatter import OutputFormatter

            fmt = OutputFormatter("json")
            fmt.error(e.format_message(), code="CLI_USAGE_ERROR")
            import sys as _sys

            _sys.exit(1)
        except click.ClickException as e:
            from ante.cli.formatter import OutputFormatter

            fmt = OutputFormatter("json")
            fmt.error(e.message, code="IPC_ERROR")
            import sys as _sys

            exit_code = e.exit_code if isinstance(e.exit_code, int) else 1
            _sys.exit(exit_code if exit_code != 0 else 1)
        except click.exceptions.Abort:
            if standalone_mode:
                click.echo("Aborted!", err=True)
                import sys as _sys

                _sys.exit(1)
            raise
        except Exception as e:
            if not standalone_mode:
                raise
            from ante.cli.formatter import OutputFormatter

            error = ipc_error_payload(e)
            if output_format == "json":
                OutputFormatter("json").error(
                    error["message"],
                    code=error["code"],
                    details=getattr(e, "cli_details", None),
                )
            else:
                click.echo(_text_error_line(error["code"], error["message"]), err=True)
                _echo_detail_lines(e)
            import sys as _sys

            _sys.exit(error_spec_for_exception(e).exit_code or 1)

        if standalone_mode:
            import sys as _sys

            _sys.exit(rv if isinstance(rv, int) else 0)
        return rv

    @staticmethod
    def _sniff_output_format(args: list[str] | None) -> str:
        """raw args 토큰열에서 ``--format`` 값을 추출 (click parse 이전)."""
        import sys as _sys

        tokens = list(args) if args is not None else _sys.argv[1:]
        result = "text"
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok == "--format" and i + 1 < len(tokens):
                result = tokens[i + 1]
                i += 2
                continue
            if tok.startswith("--format="):
                result = tok.split("=", 1)[1]
            i += 1
        return result


_META_HELP_TOKENS: frozenset[str] = frozenset({"--help", "-h"})


def _echo_detail_lines(exc: BaseException) -> None:
    for line in getattr(exc, "cli_detail_lines", ()):
        click.echo(line, err=True)


def _text_error_line(code: str, message: str) -> str:
    prefix = f"{code}: "
    if message.startswith(prefix):
        return f"Error: {message}"
    return f"Error: {prefix}{message}"


def _has_meta_help_before_dashdash(args: list[str]) -> bool:
    """args에 ``--help`` / ``-h`` 토큰이 ``--`` 앞에 있는지 검사."""
    for tok in args:
        if tok == "--":
            return False
        if tok in _META_HELP_TOKENS:
            return True
    return False


def _mirror_root_globals_to_obj(ctx: click.Context) -> None:
    """root callback의 글로벌 옵션을 ``ctx.obj`` 에 미러링."""
    if not isinstance(ctx.obj, dict):
        return

    params = getattr(ctx, "params", None) or {}
    raw_config_dir = params.get("config_dir")
    if raw_config_dir and "config_dir" not in ctx.obj:
        from pathlib import Path

        ctx.obj["config_dir"] = (
            raw_config_dir if isinstance(raw_config_dir, Path) else Path(raw_config_dir)
        )

    if "formatter" not in ctx.obj:
        from ante.cli.formatter import OutputFormatter

        raw_format = params.get("output_format") or "text"
        ctx.obj["format"] = raw_format
        ctx.obj["formatter"] = OutputFormatter(raw_format)


def _attach_auth_guard_recursive(cmd: click.Command) -> None:
    """leaf command callback에만 인증 가드를 부착하고, group이면 자식까지 재귀."""
    if isinstance(cmd, click.Group):
        for sub in list(cmd.commands.values()):
            _attach_auth_guard_recursive(sub)
        return
    if cmd.callback is not None:
        cmd.callback = _wrap_callback_with_auth(cmd.callback)


def _wrap_callback_with_auth(callback: Callable[..., Any]) -> Callable[..., Any]:
    """callback을 default-deny 인증 가드 wrapper로 감싼다."""
    if getattr(callback, "_wrapped_by_authenticated_group", False):
        return callback

    has_auth_decorator = getattr(callback, "_require_auth_applied", False)

    @functools.wraps(callback)
    def wrapper(*args: object, **kwargs: object) -> object:
        ctx = click.get_current_context()
        if ctx.resilient_parsing:
            return callback(*args, **kwargs)

        if isinstance(ctx.obj, dict) and ctx.obj.get("_auth_gate_invoked"):
            return callback(*args, **kwargs)

        path = _get_invoked_command_path(ctx)
        if path is not None and path in _AUTH_EXEMPT_COMMAND_PATHS:
            return callback(*args, **kwargs)

        from ante.cli import main as _main

        _main.authenticate_member(ctx)

        if not has_auth_decorator:
            member = ctx.obj.get("member") if isinstance(ctx.obj, dict) else None
            if member is None:
                raise CliAuthRequiredError(
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
                )

        return callback(*args, **kwargs)

    wrapper._wrapped_by_authenticated_group = True  # type: ignore[attr-defined]
    if not has_auth_decorator:
        wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    return wrapper


def authenticated_group(name: str | None = None, **attrs: object) -> Callable[..., Any]:
    """``@click.group`` 호환 데코레이터. ``AuthenticatedGroup``으로 그룹을 생성.

    사용 예::

        @authenticated_group(context_settings={"help_option_names": ["-h", "--help"]})
        @click.pass_context
        def cli(ctx: click.Context) -> None:
            ...
    """
    attrs.setdefault("cls", AuthenticatedGroup)
    return cast("Callable[..., Any]", click.group(name=name, **attrs))  # type: ignore[call-overload]
