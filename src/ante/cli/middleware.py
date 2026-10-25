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

# DB encryption key chokepoint 면제 커맨드 경로 목록.
#
# auth exempt와 의미가 다르므로 별도 정의한다. 면제 4 경로는 각자
# ``ANTE_DB_ENCRYPTION_KEY`` 를 요구하지 않는 cold path이다:
#
# - ``("init",)``: 키 생성/주입 자체가 책임 (``commands/init.py`` 의
#   ``_ensure_encryption_key_in_secrets_env``).
# - ``("member", "reset-password")``: recovery key 인증, account credential
#   decrypt 경로 없음.
# - ``("member", "regenerate-recovery-key")``: 현재 패스워드 인증, account
#   credential decrypt 경로 없음.
# - ``("feed", "init")``: ``FeedConfig.init()`` 만 호출, encryption 무관.
#
_ENCRYPTION_EXEMPT_COMMAND_PATHS: set[tuple[str, ...]] = {
    ("init",),
    ("member", "reset-password"),
    ("member", "regenerate-recovery-key"),
    ("feed", "init"),
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
        _emit_auth_error(ctx, "auth_failed", f"인증 실패: {e}")
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
            # connect 실패 경로에서도 ``db.close()`` 를 보장한다. ``connect()`` 가
            # 부분적으로 성공(writer만 열림)한 뒤 raise되면 aiosqlite worker
            # thread가 leak되어, JSON envelope 출력 **이후** ``asyncio.run`` 종료
            # 시 닫힌 이벤트 루프를 건드려 stderr에 ``RuntimeError: Event loop
            # is closed`` traceback을 남긴다(#1965). 이는 ``--format json`` 의
            # stderr 청결 계약을 위반한다. ``report.py`` / ``db_context.py`` 의
            # ``except BaseException`` cleanup 패턴을 미러한다.
            #
            # NOTE: ``Database.connect()`` 자체도 부분 연결을 정리하므로
            # (``core/database.py``) 통상 ``db.close()`` 는 no-op이지만, auth
            # 표면에서도 동일 invariant를 이중 방어로 보장한다. ``close()`` 실패는
            # 원본 ``PermissionError`` 를 가리지 않도록 swallow한다.
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
    감싸지도록 ``_require_auth_applied`` sentinel marker로 dedupe한다.
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
            _emit_auth_error(
                ctx,
                "auth_required",
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
            )
            raise SystemExit(1)
        return fn(*args, **kwargs)

    wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    return wrapper


def require_master(fn: Callable) -> Callable:
    """master-only 데코레이터 (HUMAN type + master role만 통과).

    @click.pass_context 아래에 배치한다.
    ``ctx.obj["member"]``가 ``None`` 이면 ``auth_required`` 로 종료.
    member.type != ``MemberType.HUMAN`` 또는 member.role != ``MemberRole.MASTER``
    이면 ``permission_denied`` 로 종료.

    member admin mutation 은 master-only 계약이다. CLI 표면 가드는 동일한
    invariant 를 진입점에서 적용한다.

    멱등(idempotent) — 이미 ``require_master`` 가 부착된 함수에 재적용되어도
    한 번만 감싸지도록 자체 ``_require_master_applied`` sentinel marker 로
    dedupe 한다. ``_require_auth_applied`` 를 dedupe key 로 쓰면, callback 에
    ``@require_auth`` 가 먼저 적용되어 있을 때 ``@require_master`` 가 자체 wrap
    을 건너뛰어 master 검증이 발화하지 않는 idempotent 버그가 생기므로 자체
    marker 를 분리한다.

    동시에 ``_require_auth_applied`` marker 도 함께 set 한다. 본 가드는 자체
    적으로 ``member is None`` 인증 검증을 포함하므로, ``authenticated_group``
    factory 가 leaf command callback 을 ``require_auth`` 로 자동 wrap 할 때
    중복 wrap 을 방지하기 위함이다 (``require_auth`` / ``require_scope`` 와
    동일한 보호 패턴).

    Note:
        ``member:admin`` scope vocabulary 는 reserved 상태로 유지된다
        (``src/ante/member/scopes.py`` SSOT). 본 데코레이터는 scope 보유 여부를
        검사하지 않으며, master 가 아니면 무조건 거부한다.
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
            _emit_auth_error(
                ctx,
                "auth_required",
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
            )
            raise SystemExit(1)

        # MemberType.HUMAN + role == MASTER 만 통과.
        member_type_value = getattr(member.type, "value", member.type)
        member_role_value = getattr(member.role, "value", member.role)
        if (
            member_type_value != MemberType.HUMAN.value
            or member_role_value != MemberRole.MASTER.value
        ):
            _emit_auth_error(
                ctx,
                "permission_denied",
                "이 작업은 master 권한이 필요합니다.",
            )
            raise SystemExit(1)

        return fn(*args, **kwargs)

    wrapper._require_auth_applied = True  # type: ignore[attr-defined]
    wrapper._require_master_applied = True  # type: ignore[attr-defined]
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
                _emit_auth_error(
                    ctx,
                    "auth_required",
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
                )
                raise SystemExit(1)

            # Human(master, admin)은 scope 무제한
            if member.type == MemberType.HUMAN:
                return fn(*args, **kwargs)

            # Agent는 scope 검증
            missing = [s for s in scopes if s not in member.scopes]
            if missing:
                _emit_auth_error(
                    ctx,
                    "permission_denied",
                    f"권한이 부족합니다. 필요 권한: {', '.join(missing)}",
                )
                raise SystemExit(1)

            return fn(*args, **kwargs)

        wrapper._required_scopes = scopes  # type: ignore[attr-defined]
        # @require_scope wrapper도 member==None을 직접 검사한다.
        # ``authenticated_group``이 leaf callback을 자동으로 ``require_auth``로
        # wrapping할 때 같은 검사가 두 번 발화하지 않도록 sentinel marker로
        # dedupe 신호를 남긴다.
        wrapper._require_auth_applied = True  # type: ignore[attr-defined]
        return wrapper

    return decorator


def enforce_scope(ctx: click.Context, *scopes: str) -> None:
    """명령 내부에서 조건부로 scope를 검증한다(imperative).

    ``require_scope`` 데코레이터는 명령 진입 시점에 고정 scope를 강제하지만,
    일부 명령은 입력 옵션에 따라 mutating 경로로 분기한다(예:
    ``data validate --fix`` 는 손상 파일을 ``.corrupted`` 로 격리하므로 read
    검증에 더해 write 권한이 필요하다). 이런 조건부 권한 경계를 데코레이터로
    표현할 수 없으므로, 명령 본문에서 mutation 직전에 호출하는 imperative
    헬퍼를 제공한다.

    ``require_scope`` 데코레이터와 동일 규칙을 적용한다:

    - ``ctx.obj["member"]`` 가 ``None`` 이면 ``auth_required`` emit 후
      ``SystemExit(1)``.
    - Human(master, admin) 멤버는 scope 제한 없이 통과.
    - Agent 멤버는 ``scopes`` 를 모두 보유해야 한다. 부족 시
      ``permission_denied`` 를 부족 scope와 함께 emit 후 ``SystemExit(1)``.

    SCOPE_VOCABULARY 는 flat frozenset(계층 없음)이므로 ``data:write`` 가
    ``data:read`` 를 함의하지 않는다. 따라서 ``@require_scope("data:read")`` 데코
    레이터와 본 헬퍼의 ``enforce_scope(ctx, "data:write")`` 호출이 결합되면
    Agent는 두 scope를 모두 보유한 토큰만 통과한다(검증 read + 격리 write).
    """
    from ante.member.models import MemberType

    member: Member | None = ctx.obj.get("member")
    if member is None:
        _emit_auth_error(
            ctx,
            "auth_required",
            "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
        )
        raise SystemExit(1)

    # Human(master, admin)은 scope 무제한 — require_scope 와 동일.
    if member.type == MemberType.HUMAN:
        return

    # Agent는 scope 검증 — require_scope 와 동일 규칙/메시지.
    missing = [s for s in scopes if s not in member.scopes]
    if missing:
        _emit_auth_error(
            ctx,
            "permission_denied",
            f"권한이 부족합니다. 필요 권한: {', '.join(missing)}",
        )
        raise SystemExit(1)


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
        # 1. _LeafPathMixin: 전체 커맨드 경로 tuple을 ctx.obj에 저장.
        ctx.ensure_object(dict)
        all_args = [*ctx.protected_args, *ctx.args]
        path = self._resolve_command_path(ctx, all_args)
        if path:
            ctx.obj["_leaf_command_path"] = path
            ctx.obj["_leaf_command"] = path[-1]

        # 2. root callback의 글로벌 옵션을 ``ctx.obj``로 미리 미러링한다.
        #    ``Group.invoke``는 ``super().invoke(ctx)`` 안에서 root callback을
        #    실행하지만, 인증 게이트는 그보다 먼저 발화한다. ``--config-dir``
        #    같이 인증 시점에 영향을 주는 옵션은 root callback 실행을 기다리지
        #    않고 ``ctx.params`` 에서 직접 읽어 ``ctx.obj`` 에 반영해 두어야
        #    ``authenticate_member`` 가 정확한 DB 경로를 본다.
        _mirror_root_globals_to_obj(ctx)

        # 3. DB encryption key chokepoint.
        #    invoke 단계 인증 게이트 직전에 ``ANTE_DB_ENCRYPTION_KEY`` 가 설정
        #    되어 있고 Fernet canonical 형식을 만족하는지 단일 chokepoint에서
        #    검증한다. 미설정/형식 위반 시 typed exception을 envelope error로
        #    변환해 즉시 종료(traceback/timeout 방지). 면제 4 경로
        #    (``_ENCRYPTION_EXEMPT_COMMAND_PATHS``) 는 우회한다.
        #
        #    ``Config.load`` 가 호출되는 시점은 leaf callback 진입 이후이지만,
        #    본 chokepoint도 같은 fallback 정책을 그대로 적용한다: ``Config.
        #    load(config_dir=get_config_dir(ctx))`` 를 먼저 호출해 ``secrets.env``
        #    의 ``ANTE_DB_ENCRYPTION_KEY`` 행을 ``os.environ`` 으로 export시킨 뒤
        #    검증한다. 환경변수 fallback이 정상 동작한 뒤에야 검증이 호출되는
        #    invariant를 보장한다.
        if self._should_enforce_encryption_gate(ctx, all_args, path):
            self._enforce_db_encryption_key_gate(ctx)

        # 4. invoke 단계 인증 게이트 — super().invoke(ctx) 호출 전에 발화.
        if self._should_invoke_auth_gate(ctx, all_args, path):
            self._enforce_invoke_auth_gate(ctx, path)

        # 5. click의 정상 디스패치로 진행 (자식 make_context + invoke).
        return super(_LeafPathMixin, self).invoke(ctx)

    def _should_enforce_encryption_gate(
        self,
        ctx: click.Context,
        all_args: list[str],
        path: tuple[str, ...],
    ) -> bool:
        """DB encryption key chokepoint 발화 여부.

        skip 조건은 auth 게이트와 동일한 메타 면제 정책을 공유한다:

        - ``ctx.resilient_parsing`` (shell completion 등).
        - ``--help`` / ``-h`` 메타 토큰이 ``--`` 앞에 있는 경우 — click이
          callback에 도달하기 전에 ``ctx.exit()`` 하므로 가드 불필요.
        - path가 비어 있거나 leaf까지 도달하지 못한 경우 — click이 도움말
          처리 또는 ``Missing command`` 로 응답하므로 가드 불필요.
        - path가 ``_ENCRYPTION_EXEMPT_COMMAND_PATHS`` allowlist에 포함되는
          경우 (init / member reset-password / member regenerate-recovery-key
          / feed init).
        """
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
        """DB encryption key chokepoint 본체 — 실패 시 envelope + SystemExit(1).

        동작:

        1. ``Config.load(config_dir=...)`` 를 호출해 ``secrets.env`` 의
           ``ANTE_DB_ENCRYPTION_KEY`` 행을 ``os.environ`` 으로 export 시키는
           기존 fallback (``ante.config.config:110-140``) 을 먼저 실행한다.
           정상 경로에서 ``Config.load`` 가 raise 하지 않는 한, secrets.env
           export 가 env 검증보다 먼저 끝난다는 Plan v2 ordering invariant
           는 유지된다.

           단, 테스트/CI fixture 가 ``pathlib.Path.exists`` 를 전역 mock 하거나
           config_dir 가 비어 있어 TOML/.env open 단계에서 ``OSError`` /
           ``tomllib.TOMLDecodeError`` / ``ConfigError`` 가 발생할 수 있다.
           이 경우 본 chokepoint 의 책임은 ``DB_ENCRYPTION_KEY_*`` 두 코드의
           envelope 라우팅이므로, env 에 valid key 가 이미 설정되어 있으면
           Config.load fallback 없이도 통과한다. env 가 비어 있다면 이어지는
           검증 단계에서 ``EncryptionKeyMissingError`` 가 발화한다 (어느
           경로든 secrets-only / env-only 모두 동일한 envelope 으로 수렴).
        2. ``os.environ.get("ANTE_DB_ENCRYPTION_KEY")`` 를 검증한다:
           - 미설정/빈 → :class:`EncryptionKeyMissingError` (``code=
             "DB_ENCRYPTION_KEY_MISSING"``).
           - 형식 위반 (Fernet canonical 44-byte URL-safe base64 미충족)
             → :class:`EncryptionKeyInvalidError` (``code=
             "DB_ENCRYPTION_KEY_INVALID"``).
        3. raise된 typed exception은 본 메서드에서 catch해 ``OutputFormatter.
           error`` 또는 텍스트 메시지로 envelope 출력 후 ``SystemExit(1)``.
        4. 검증 성공 시 ``ctx.obj["_db_encryption_key_validated"] = True`` marker.
        """
        # 지연 import: crypto / config 모듈은 본 미들웨어가 import될 때마다
        # eager로 끌어올리지 않는다. AuthenticatedGroup 자체는 cryptography
        # 의존성과 무관해야 한다 (단위 테스트가 다른 경로로 import할 수 있음).
        import tomllib

        from ante.account.crypto import (
            EncryptionKeyError,
            EncryptionKeyInvalidError,
            EncryptionKeyMissingError,
            _validate_fernet_key,
        )
        from ante.cli.main import get_config_dir
        from ante.config.config import Config
        from ante.config.exceptions import ConfigError

        # secrets.env → os.environ export fallback (``ante.config.config:110-140``).
        # config_dir 미설정 시 ``resolve_config_dir()`` 기본값을 따른다.
        #
        # Config.load 가 raise 하는 경로 (예: 테스트 fixture 가 ``pathlib.Path.
        # exists`` 를 전역 mock 한 상태에서 실제 system.toml 이 존재하지 않으면
        # ``FileNotFoundError`` 가 발생) 는 env-only 검증으로 fallback 한다.
        # env 에 valid key 가 있으면 통과하고, 없으면 다음 단계에서
        # ``EncryptionKeyMissingError`` 로 envelope 라우팅된다. 어느 경우든
        # 본 chokepoint 의 책임 (``DB_ENCRYPTION_KEY_*`` 두 코드의 envelope
        # 라우팅) 은 유지된다.
        try:
            Config.load(config_dir=get_config_dir(ctx))
        except (OSError, tomllib.TOMLDecodeError, ConfigError) as exc:
            logger.debug(
                "Config.load failed in DB encryption chokepoint; "
                "falling back to env-only validation: %s",
                exc,
            )

        try:
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
        except EncryptionKeyError as e:
            _emit_error_envelope(ctx, str(e), code=e.code)
            raise SystemExit(1) from e

        if isinstance(ctx.obj, dict):
            ctx.obj["_db_encryption_key_validated"] = True

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
        # parse error 응답이 인증 없이 노출되지 않는다.
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
            _emit_auth_error(
                ctx,
                "auth_required",
                "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
            )
            raise SystemExit(1)

        # callback 단계 wrapper가 같은 가드를 다시 발화시키지 않도록 marker.
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
        """``BaseCommand.main`` 오버라이드 — JSON 모드 parsing-stage 에러 envelope 변환.

        Click 8.x의 ``BaseCommand.main()`` 은 ``parse_args``/``invoke`` 를 try/except
        로 감싸 :class:`click.UsageError` (subclass: ``MissingParameter``,
        ``BadParameter``, ``BadArgumentUsage``, ``NoSuchOption``) 를 catch 하면
        ``e.show()`` 로 stderr 에 ``Usage: ... Error: ...`` 텍스트를 출력하고
        ``sys.exit(e.exit_code)`` (보통 2) 한다. 이는 ``--format json`` 모드의
        구조화 에러 계약 (스펙 ``docs/specs/cli/02-design-decisions.md:78-81``,
        ``{status, code, message}`` envelope + exit 1) 과 어긋난다.

        본 오버라이드는 ``--format`` raw 토큰을 sniff 해 json 모드일 때만 click
        의 ``standalone_mode=False`` 로 호출하고 ``UsageError`` 를 직접 catch 해
        :meth:`OutputFormatter.error` 로 envelope 출력 + ``sys.exit(1)`` 한다.

        텍스트 모드 (`--format text` 기본) 에서는 click 기본 동작
        (``Usage: ... Error: ...`` stderr + exit 2) 을 그대로 유지한다.

        gate-exempt 경로 (``--help`` / ``--version`` / completion) 는 click 이
        ``BaseCommand.main`` 내부에서 자체 ``ctx.exit()`` 처리하므로 본 try/except
        블록에는 진입하지 않는다.
        """
        output_format = self._sniff_output_format(args)
        if output_format != "json":
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=standalone_mode,
                **extra,
            )

        # JSON 모드: UsageError 를 직접 catch 해 envelope 출력 + exit 1.
        # super().main(standalone_mode=False) 는 click ``ClickException`` /
        # ``Abort`` 를 re-raise 하고, 정상/``Exit`` 케이스는 값을 반환한다
        # (click core.py:1083-1120).
        try:
            rv = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )
        except click.UsageError as e:
            from ante.cli.formatter import OutputFormatter

            fmt = OutputFormatter("json")
            # Click 의 ``UsageError.format_message()`` 는 메시지 본문만 반환
            # (예: ``Missing argument 'VALUE'.``). ``CLI_USAGE_ERROR`` 코드는
            # 스펙 ``02-design-decisions.md:84-87`` 의 ``CLI_*`` prefix 명명 규칙을
            # 따른다 (코드 내부 상수, 스펙 정식 등재 없음).
            fmt.error(e.format_message(), code="CLI_USAGE_ERROR")
            import sys as _sys

            _sys.exit(1)
        except click.ClickException as e:
            # IPC 미기동/타임아웃 등 비-``UsageError`` ``ClickException``
            # 도 JSON 모드 구조화 에러 계약 (``{status, code, message}``
            # envelope + exit non-zero, ``docs/specs/cli/02-design-decisions.md
            # :78-81``) 을 만족해야 한다.
            #
            # ``UsageError`` 가 ``ClickException`` 의 subclass 이므로 Python
            # ``except`` 순서 매칭상 본 분기는 ``UsageError`` 가 아닌 일반
            # ``ClickException`` (예: ``ipc_send`` 가 raise 하는
            # ``ServerNotRunningError`` / ``IPCTimeoutError`` 변환 + 서버 error
            # envelope) 만 처리한다.
            #
            # ``ipc_send`` (``ante.cli.commands.ipc_helpers``) 는
            # ``ClickException`` 인스턴스에 ``ipc_error_code`` /
            # ``ipc_error_message`` 속성을 부착하므로 그 stable code 를 우선
            # 사용하고, 없으면 ``IPC_ERROR`` fallback 으로 envelope 을 출력한다
            # (``commands/bot.py``, ``commands/treasury.py``, ``commands/
            # strategy.py``, ``commands/rule.py``, ``commands/member.py`` 의 호출
            # 표면 try/except 매핑과 동형 fallback code).
            from ante.cli.formatter import OutputFormatter

            fmt = OutputFormatter("json")
            code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
            message = getattr(e, "ipc_error_message", None) or e.message
            fmt.error(message, code=code)
            import sys as _sys

            exit_code = e.exit_code if isinstance(e.exit_code, int) else 1
            _sys.exit(exit_code if exit_code != 0 else 1)
        except click.exceptions.Abort:
            # ``standalone_mode=True`` 호출자 호환을 위해 click 기본 Abort 동작
            # (``Aborted!`` stderr + exit 1) 을 그대로 보존한다.
            if standalone_mode:
                click.echo("Aborted!", err=True)
                import sys as _sys

                _sys.exit(1)
            raise

        # standalone_mode=True 호출자 호환: click 기본은 정상 ``ctx.exit(rv)``
        # 또는 ``Exit`` 예외 시 ``sys.exit(rv)`` 를 호출한다 (core.py:1092,
        # 1109-1110). 우리는 standalone_mode=False 로 호출했으므로 click 이
        # sys.exit 를 부르지 않고 값을 반환한다. 호출 일관성을 위해 standalone
        # 모드에서 우리도 명시적으로 sys.exit 를 호출한다.
        if standalone_mode:
            import sys as _sys

            _sys.exit(rv if isinstance(rv, int) else 0)
        return rv

    @staticmethod
    def _sniff_output_format(args: list[str] | None) -> str:
        """raw args 토큰열에서 ``--format`` 값을 추출 (click parse 이전).

        서브커맨드 ``--format`` 이 root ``--format`` 을 오버라이드하는 패턴
        (:func:`ante.cli.formatter.format_option`) 을 따라 args 의 **마지막**
        ``--format`` 값을 우선한다.

        예::

            ante --format json bot list --format text  → "text"
            ante --format text some cmd --format json  → "json"
            ante bot list                              → "text" (기본값)

        ``--format=value`` (등호 형태) 와 ``--format value`` (공백 형태) 모두
        지원한다.
        """
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


# click이 callback에 도달하기 전에 ``ctx.exit()`` 시키는 메타 옵션 토큰.
# ``_has_meta_help_before_dashdash``가 사용한다.
#
# ``--version`` 은 ``@click.version_option`` 이 root 콜백 진입 **이전**에
# ``ctx.exit()`` 시키므로 root 수준의 ``ante --version`` 은 이미 면제가
# 보장된다. nested 위치 (``ante bot list --version`` 등) 에서는 Click parse
# error 응답이 인증 없이 노출되는 부작용을 막아야 하므로 메타 면제 토큰에서
# ``--version`` 을 제거하고 invoke 단계 가드가 정상적으로 발화하도록 한다.
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

    ``AuthenticatedGroup.invoke`` 의 인증 게이트는 ``super().invoke(ctx)``
    호출 **이전** 에 발화하므로, 같은 ``super().invoke(ctx)`` 안에서 실행되는
    root callback의 부작용 (``ctx.obj["config_dir"] = ...`` 등) 이 아직 반영되지
    않은 상태다. 인증 시점에 ``--config-dir`` 등을 정확히 반영하지 못하면
    ``authenticate_member`` 가 default config dir의 DB를 보게 되어, 명시한
    인스턴스의 토큰이 어긋난 DB에서 인증 실패하는 회귀가 발생한다.

    본 헬퍼는 ``ctx.params`` 에 이미 파싱돼 들어 있는 root 옵션을 읽어
    ``ctx.obj`` 키로 동일하게 반영한다. root callback이 나중에
    재실행되어 같은 값을 덮어쓰더라도 의미는 동일하다.

    현재 미러링 대상:

    - ``config_dir`` (str → ``pathlib.Path``): ``--config-dir`` /
      ``ANTE_CONFIG_DIR``. ``authenticate_member`` → ``get_db_path`` →
      ``get_config_dir`` 가 ``ctx.obj["config_dir"]`` 를 우선 참조한다.
    - ``output_format`` (str → ``OutputFormatter``): ``--format``.
      인증/권한 실패 경로가 JSON 모드에서 구조화 에러를 stdout으로
      출력하려면 ``ctx.obj["formatter"]`` 가 인증 게이트 발화 시점에도
      존재해야 한다. root callback이 같은 키를 다시 채우더라도 의미는
      동일하다.
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

    # output_format (--format) 사전 미러링. root callback이 실행되기 전에
    # ``_emit_auth_error`` 가 ``ctx.obj["formatter"]`` 를 사용할 수 있어야 한다.
    if "formatter" not in ctx.obj:
        from ante.cli.formatter import OutputFormatter

        raw_format = params.get("output_format") or "text"
        ctx.obj["format"] = raw_format
        ctx.obj["formatter"] = OutputFormatter(raw_format)


def _emit_auth_error(ctx: click.Context, code: str, message: str) -> None:
    """인증/권한 실패 메시지를 출력 모드에 맞게 발화한다.

    - JSON 모드 (``ctx.obj["formatter"]`` 의 ``is_json``): ``OutputFormatter.error``
      를 통해 ``{"status":"error","code":<code>,"message":<message>}`` JSON을
      stdout으로 출력. 자동화 호출자(ante-oracle host probe 등)가 JSON 파서로
      직접 소비할 수 있게 한다.
    - 텍스트 모드 또는 ``formatter`` 미설정 fallback: 기존 동작 그대로 한국어
      메시지를 ``click.echo(..., err=True)`` 로 stderr 에 출력.

    본 헬퍼는 출력만 책임지며 종료는 호출자가 ``raise SystemExit(1)`` 로
    수행한다 (필요 시 ``raise SystemExit(1) from e`` 형태로 cause 보존).
    """
    obj = getattr(ctx, "obj", None)
    formatter = obj.get("formatter") if isinstance(obj, dict) else None
    if formatter is not None and getattr(formatter, "is_json", False):
        formatter.error(message, code=code)
    else:
        click.echo(message, err=True)


def _emit_error_envelope(ctx: click.Context, message: str, *, code: str) -> None:
    """generic stable-code error envelope 출력.

    인증 실패 외 typed exception (예: ``EncryptionKeyMissingError`` /
    ``EncryptionKeyInvalidError``) 을 JSON envelope 또는 텍스트 메시지로
    노출한다. 의미상 :func:`_emit_auth_error` 와 동일한 두 모드 분기를 따르지만
    호출자 의도를 분명히 하기 위해 별도 이름으로 노출한다.

    - JSON 모드 (``ctx.obj["formatter"]`` 의 ``is_json``): ``OutputFormatter.error``
      → ``{"status":"error","code":<code>,"message":<message>}`` JSON stdout.
    - 텍스트 모드 또는 ``formatter`` 미설정: ``click.echo(..., err=True)`` stderr.

    종료는 호출자가 ``raise SystemExit(1) from e`` 로 수행한다.
    """
    obj = getattr(ctx, "obj", None)
    formatter = obj.get("formatter") if isinstance(obj, dict) else None
    if formatter is not None and getattr(formatter, "is_json", False):
        formatter.error(message, code=code)
    else:
        click.echo(message, err=True)


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

        # 2. invoke 단계 가드가 이미 발화한 경우,
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
                _emit_auth_error(
                    ctx,
                    "auth_required",
                    "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요.",
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
    return click.group(name=name, **attrs)  # type: ignore[call-overload]
