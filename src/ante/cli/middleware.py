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
    3. /run/ante-token 파일 (컨테이너/서비스 환경의 기본 토큰 파일 경로)
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
        from ante.cli.main import get_db_path

        member = _run_authenticate(token, get_db_path(ctx))
        ctx.obj["member"] = member
        logger.debug("CLI 인증 성공: %s", member.member_id)
    except PermissionError as e:
        click.echo(f"인증 실패: {e}", err=True)
        raise SystemExit(1) from e


def _run_authenticate(token: str, db_path: str) -> Member:
    """동기 컨텍스트에서 MemberService.authenticate 호출.

    Args:
        token: 인증할 멤버 토큰.
        db_path: 사용할 SQLite DB 파일 경로. `ante init`이 생성한 위치와
            동일해야 하므로 `get_db_path(ctx)`로부터 전달한다.

    Raises:
        PermissionError: 토큰이 유효하지 않거나, DB를 열 수 없는 경우
            (예: `ante init`이 아직 실행되지 않아 `<config_dir>/db/ante.db`가
            없음). DB I/O 오류도 PermissionError로 통일하여 동일한
            "인증 실패" 경로로 에러를 노출한다.
    """
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    async def _auth() -> Member:
        db = Database(db_path)
        try:
            await db.connect()
        except Exception as e:  # noqa: BLE001 — sqlite/OS 오류 통일 처리
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

    멱등(idempotent) — 이미 같은 가드가 부착된 함수에 재적용되어도 한 번만
    감싸지도록 ``_require_auth_applied`` sentinel marker로 dedupe한다. #1404
    ``authenticated_group`` factory가 leaf command callback을 자동 wrapping할 때,
    명령 자체에 이미 명시적으로 부착된 ``@require_auth`` 또는 ``@require_scope``의
    내부 가드와 중복 호출되는 것을 방지한다.
    """
    if getattr(fn, "_require_auth_applied", False):
        return fn

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

    wrapper._require_auth_applied = True  # type: ignore[attr-defined]
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
        # @require_scope wrapper도 member==None을 직접 검사한다. #1404
        # ``authenticated_group``이 leaf callback을 자동으로 ``require_auth``로
        # wrapping할 때 같은 검사가 두 번 발화하지 않도록 sentinel marker로
        # dedupe 신호를 남긴다.
        wrapper._require_auth_applied = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


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

    동작 (#1404 P2 정정):

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
         발화한다. (#1404 P2 정정)
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
        # 1. _LeafPathMixin: 전체 커맨드 경로 tuple을 ctx.obj에 저장.
        ctx.ensure_object(dict)
        all_args = [*ctx.protected_args, *ctx.args]
        path = self._resolve_command_path(ctx, all_args)
        if path:
            ctx.obj["_leaf_command_path"] = path
            ctx.obj["_leaf_command"] = path[-1]

        # 2. root callback의 글로벌 옵션을 ``ctx.obj``로 미리 미러링한다.
        #    (#1404 P1 정정) ``Group.invoke``는 ``super().invoke(ctx)`` 안에서
        #    root callback을 실행하지만, 인증 게이트는 그보다 먼저 발화한다.
        #    ``--config-dir`` 같이 인증 시점에 영향을 주는 옵션은 root callback
        #    실행을 기다리지 않고 ``ctx.params`` 에서 직접 읽어 ``ctx.obj`` 에
        #    반영해 두어야 ``authenticate_member`` 가 정확한 DB 경로를 본다.
        _mirror_root_globals_to_obj(ctx)

        # 3. invoke 단계 인증 게이트 — super().invoke(ctx) 호출 전에 발화.
        if self._should_invoke_auth_gate(ctx, all_args, path):
            self._enforce_invoke_auth_gate(ctx, path)

        # 4. click의 정상 디스패치로 진행 (자식 make_context + invoke).
        return super(_LeafPathMixin, self).invoke(ctx)

    def _should_invoke_auth_gate(
        self,
        ctx: click.Context,
        all_args: list[str],
        path: tuple[str, ...],
    ) -> bool:
        """invoke 단계 인증 게이트를 발화할지 여부.

        skip 조건은 본 클래스 docstring의 (1) 항목 참조.
        """
        # resilient parsing(shell completion 등)은 부작용 없는 파싱이므로 skip.
        if ctx.resilient_parsing:
            return False

        # args 안에 메타 옵션(--help / -h)이 ``--`` 앞에 존재하면
        # click이 callback에 도달하기 전에 ctx.exit()하므로 가드 skip.
        # ``--version`` 은 root ``@click.version_option`` 에서만 면제되며,
        # nested 위치(예: ``ante bot list --version``)는 인증 게이트가 발화해야
        # parse error 응답이 인증 없이 노출되지 않는다. (#1404 P2 정정)
        if _has_meta_help_before_dashdash(all_args):
            return False

        # path가 비어 있거나 leaf까지 도달하지 못한 경우(=group으로 끝남)는
        # click이 ``no_args_is_help`` 또는 ``Missing command``로 처리하므로 skip.
        if not path:
            return False
        if not self._path_resolves_to_leaf(ctx, path):
            return False

        # 공개 명령 allowlist는 면제.
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
        """invoke 단계 인증 게이트 본체 — 실패 시 SystemExit(1).

        - ``ante.cli.main.authenticate_member`` 의 최신 attribute를 호출 시점에
          동적 lookup하여 ``patch("ante.cli.main.authenticate_member")`` 기반의
          기존 테스트가 그대로 동작하도록 한다.
        - 토큰이 비어 있거나 검증이 실패하면 ``authenticate_member`` 내부에서
          ``ctx.obj["member"] = None`` 또는 직접 ``SystemExit(1)``로 차단한다.
        - 본 메서드는 path가 leaf로 끝나고 allowlist에 없는 경우에만 호출된다.
          따라서 ``member is None`` 이면 default-deny ("인증이 필요합니다", exit 1)
          를 발화시킨다.
        - 성공 시 ``ctx.obj["_auth_gate_invoked"] = True``로 marker를 남겨,
          callback 단계 이중 방어 wrapper가 ``authenticate_member``를 중복
          호출하지 않도록 한다.
        """
        from ante.cli import main as _main

        _main.authenticate_member(ctx)

        member = ctx.obj.get("member") if isinstance(ctx.obj, dict) else None
        if member is None:
            click.echo(
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
                err=True,
            )
            raise SystemExit(1)

        # callback 단계 wrapper가 같은 가드를 다시 발화시키지 않도록 marker.
        ctx.obj["_auth_gate_invoked"] = True

    def add_command(self, cmd: click.Command, name: str | None = None) -> None:
        """등록되는 자식 command/group에 인증 가드를 자동 부착 (이중 방어)."""
        _attach_auth_guard_recursive(cmd)
        super().add_command(cmd, name)


# click이 callback에 도달하기 전에 ``ctx.exit()`` 시키는 메타 옵션 토큰.
# ``_has_meta_help_before_dashdash``가 사용한다.
#
# (#1404 P2 정정) ``--version`` 은 ``@click.version_option`` 이 root 콜백
# 진입 **이전**에 ``ctx.exit()`` 시키므로 root 수준의 ``ante --version`` 은
# 이미 면제가 보장된다. nested 위치 (``ante bot list --version`` 등) 에서는
# Click parse error 응답이 인증 없이 노출되는 부작용을 막아야 하므로 메타
# 면제 토큰에서 ``--version`` 을 제거하고 invoke 단계 가드가 정상적으로
# 발화하도록 한다.
_META_HELP_TOKENS: frozenset[str] = frozenset({"--help", "-h"})


def _has_meta_help_before_dashdash(args: list[str]) -> bool:
    """args에 ``--help`` / ``-h`` 토큰이 ``--`` 앞에 있는지 검사.

    H1 invariant: ``ante --help``, ``ante member list --help`` 등 모든
    깊이의 ``--help`` / ``-h`` 는 click이 callback에 도달하기 전에
    ``ctx.exit()`` 하므로 invoke 단계 가드를 발화시키지 않는다.

    H2 invariant: ``ante bot info -- --help`` 처럼 ``--`` 이후 위치 인자로
    들어간 ``--help`` 는 click이 메타로 해석하지 않으므로 본 함수는
    이 케이스를 메타로 간주하지 **않는다**.

    H3(``--version``) 처리는 root ``@click.version_option`` 에 위임한다.
    nested 위치에 ``--version`` 이 등장하면 본 함수는 면제하지 않으므로
    invoke 단계 가드가 정상 발화한다.
    """
    for tok in args:
        if tok == "--":
            return False
        if tok in _META_HELP_TOKENS:
            return True
    return False


def _mirror_root_globals_to_obj(ctx: click.Context) -> None:
    """root callback의 글로벌 옵션을 ``ctx.obj`` 에 미러링.

    (#1404 P1 정정) ``AuthenticatedGroup.invoke`` 의 인증 게이트는
    ``super().invoke(ctx)`` 호출 **이전** 에 발화하므로, 같은
    ``super().invoke(ctx)`` 안에서 실행되는 root callback의 부작용
    (``ctx.obj["config_dir"] = ...`` 등) 이 아직 반영되지 않은 상태다.
    인증 시점에 ``--config-dir`` 등을 정확히 반영하지 못하면
    ``authenticate_member`` 가 default config dir의 DB를 보게 되어,
    명시한 인스턴스의 토큰이 어긋난 DB에서 인증 실패하는 회귀가 발생한다.

    본 헬퍼는 ``ctx.params`` 에 이미 파싱돼 들어 있는 root 옵션을 읽어
    ``ctx.obj`` 키로 동일하게 반영한다. root callback이 나중에
    재실행되어 같은 값을 덮어쓰더라도 의미는 동일하다.

    현재 미러링 대상:

    - ``config_dir`` (str → ``pathlib.Path``): ``--config-dir`` /
      ``ANTE_CONFIG_DIR``. ``authenticate_member`` → ``get_db_path`` →
      ``get_config_dir`` 가 ``ctx.obj["config_dir"]`` 를 우선 참조한다.
    """
    if not isinstance(ctx.obj, dict):
        return

    params = getattr(ctx, "params", None) or {}
    raw_config_dir = params.get("config_dir")
    if raw_config_dir and "config_dir" not in ctx.obj:
        from pathlib import Path

        ctx.obj["config_dir"] = (
            raw_config_dir if isinstance(raw_config_dir, Path) else Path(raw_config_dir)
        )


def _attach_auth_guard_recursive(cmd: click.Command) -> None:
    """leaf command callback에만 인증 가드를 부착하고, group이면 자식까지 재귀.

    ``click.Group``의 callback에는 인증 가드를 부착하지 **않는다**. nested
    ``--help`` 처리 시 click은 leaf command callback은 호출하지 않지만 부모
    group callback은 그대로 호출한다(예: ``ante member list --help``는
    ``member`` group의 callback을 호출한 뒤 ``list`` 명령의 help를 출력하고
    종료). 부모 group callback에 인증 가드를 부착하면 nested ``--help``에서
    부수적으로 default-deny가 발화해 H1 invariant(모든 깊이 ``--help`` 통과)가
    깨진다. 따라서 인증 가드는 leaf command(=non-Group ``click.Command``)에만
    부착한다. 자식 group/명령은 재귀로 순회한다.
    """
    if isinstance(cmd, click.Group):
        for sub in list(cmd.commands.values()):
            _attach_auth_guard_recursive(sub)
        return
    if cmd.callback is not None:
        cmd.callback = _wrap_callback_with_auth(cmd.callback)


def _wrap_callback_with_auth(callback: Callable) -> Callable:
    """callback을 default-deny 인증 가드 wrapper로 감싼다.

    동작:

    1. ``ctx.resilient_parsing == True``: shell completion 등 부작용 없는
       파싱이므로 인증 단계를 건너뛴다.
    2. 명령 경로가 ``_AUTH_EXEMPT_COMMAND_PATHS``에 포함되면 callback을
       바로 호출 (공개 명령 allowlist).
    3. 그 외에는 ``authenticate_member(ctx)``를 호출해 ``ctx.obj["member"]``를
       채운다. 토큰 검증이 실패하면 ``authenticate_member`` 내부에서 exit 1.
    4. callback에 이미 ``@require_auth`` / ``@require_scope`` sentinel
       marker(``_require_auth_applied``)가 있으면 None 체크를 ``@require_auth``
       데코레이터에 위임한다. 그렇지 않으면 본 wrapper가 직접 ``member is None``
       에 대해 default-deny ("인증이 필요합니다", exit 1)를 발화한다.

    멱등 (idempotent): wrapper 자체에 sentinel marker를 부착해, 같은 callback이
    여러 번 wrapping되어도 한 번만 감싸진다.

    ``ante.cli.main``이 ``authenticate_member``를 re-export하므로 기존 테스트
    suite는 ``patch("ante.cli.main.authenticate_member")``로 인증을 mock한다.
    그 patch가 본 wrapper에서도 효과가 있도록 ``ante.cli.main``의 최신 심볼을
    동적으로 조회해 호출한다.
    """
    if getattr(callback, "_wrapped_by_authenticated_group", False):
        return callback

    has_auth_decorator = getattr(callback, "_require_auth_applied", False)

    @functools.wraps(callback)
    def wrapper(*args: object, **kwargs: object) -> object:
        ctx = click.get_current_context()
        # 1. resilient parsing은 부작용 없는 파싱 시도이므로 skip.
        if ctx.resilient_parsing:
            return callback(*args, **kwargs)

        # 2. invoke 단계 가드가 이미 발화한 경우(#1404 P2 정정),
        #    ``authenticate_member`` 중복 호출 비용을 피하기 위해 callback 단계는
        #    skip한다. invoke 단계가 ``ctx.obj["_auth_gate_invoked"] = True``
        #    marker를 남기므로 이를 확인. invoke 단계가 어떤 이유로든 발화하지
        #    않은 경우(예: 자식 group이 직접 ``click.Group``으로 만들어진 경우)
        #    에는 본 wrapper가 fallback으로 동작.
        if isinstance(ctx.obj, dict) and ctx.obj.get("_auth_gate_invoked"):
            return callback(*args, **kwargs)

        # 3. allowlist 등재 명령은 인증 면제.
        path = _get_invoked_command_path(ctx)
        if path is not None and path in _AUTH_EXEMPT_COMMAND_PATHS:
            return callback(*args, **kwargs)

        # 4. 토큰 검증 — 기존 테스트 다수가 ``ante.cli.main.authenticate_member``를
        #    monkeypatch하므로(root callback이 그 심볼을 호출하던 시절의 패턴),
        #    main 모듈의 최신 attribute를 호출 시점에 동적으로 lookup하여
        #    backward compatibility를 보장한다.
        from ante.cli import main as _main

        _main.authenticate_member(ctx)

        # 5. ``@require_auth`` / ``@require_scope`` 데코레이터가 이미 부착된
        #    callback은 자체적으로 ``member is None`` 검사 + 메시지를 처리한다.
        #    중복 호출 방지를 위해 None 검사를 위임.
        if not has_auth_decorator:
            member = ctx.obj.get("member") if isinstance(ctx.obj, dict) else None
            if member is None:
                click.echo(
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
                    err=True,
                )
                raise SystemExit(1)

        return callback(*args, **kwargs)

    wrapper._wrapped_by_authenticated_group = True  # type: ignore[attr-defined]
    # 본 wrapper가 None 검사를 직접 수행한 경우에만 sentinel marker를 노출해야
    # 한다(보호하지 않는 wrapper에 ``@require_auth`` dedupe marker를 붙이면
    # 후속 wrap이 잘못 skip된다). ``has_auth_decorator``인 경우엔 이미 안쪽
    # callback에 marker가 있으므로 굳이 새 marker를 노출할 필요 없다.
    if not has_auth_decorator:
        wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    return wrapper


def authenticated_group(name: str | None = None, **attrs: object) -> Callable:
    """``@click.group`` 호환 데코레이터. ``AuthenticatedGroup``으로 그룹을 생성.

    사용 예::

        @authenticated_group(context_settings={"help_option_names": ["-h", "--help"]})
        @click.pass_context
        def cli(ctx: click.Context) -> None:
            ...

    동작 상세는 :class:`AuthenticatedGroup` docstring 참조.
    """
    attrs.setdefault("cls", AuthenticatedGroup)
    return click.group(name=name, **attrs)  # type: ignore[arg-type]
