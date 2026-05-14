"""ante approval — 결재 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.approval.models import ApprovalStatus, ApprovalType
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

# `ApprovalStatus`/`ApprovalType` enum이 `--status`/`--type` 필터의 SSOT다.
# `approval list`는 DB 진입 전 preflight에서 invalid 값을 차단해야 하며 (#1462),
# 이를 위해 함수 내부 import 대신 모듈 상단 import을 사용한다.
# `ante.approval.models`은 dataclass + StrEnum 만 노출하는 light 모듈이라
# `tests/unit/test_cli_dependency_isolation.py`가 회귀를 차단한다.


@click.group()
def approval() -> None:
    """결재 관리."""


@approval.command()
@click.option("--type", "approval_type", required=True, help="결재 유형")
@click.option("--title", required=True, help="요청 제목")
@click.option("--body", default="", help="본문 (사유, 현황, 기대 효과 등)")
@click.option("--params", "params_json", default="{}", help="실행 파라미터 (JSON)")
@click.option("--reference-id", default="", help="참조 ID (report_id 등)")
@click.option("--expires-in", default="", help="만료 기한 (예: 72h, 7d)")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:write")
def request(
    ctx: click.Context,
    approval_type: str,
    title: str,
    body: str,
    params_json: str,
    reference_id: str,
    expires_in: str,
) -> None:
    """결재 요청 생성."""
    # ApprovalType SSOT 검증. `ante.approval.models`는 모듈 상단에서 import한다
    # (#1462; #1469 lazy 패턴은 dependency-isolation smoke가 회귀 차단).

    fmt = get_formatter(ctx)
    requester = get_member_id(ctx)

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        fmt.error(f"잘못된 JSON 형식: {e}", code="INVALID_JSON")
        raise SystemExit(1) from e

    # ``--params`` 는 service ``params.get()`` 호출의 SSOT 입력이므로 JSON
    # object (dict) 만 허용한다. string/list/number/bool/null 같은 non-dict
    # JSON value 가 통과하면 service 단에서 ``AttributeError`` traceback 이
    # 노출된다 (#1519). 같은 함수 line 57-58 / 62-66 패턴과 동형.
    # service/IPC defense-in-depth 는 본 PR Non-Goals (follow-up).
    if not isinstance(params, dict):
        params_type = type(params).__name__
        fmt.error(
            f"--params는 JSON object여야 합니다 (현재 타입: {params_type})",
            code="APPROVAL_VALIDATION_ERROR",
        )
        raise SystemExit(1)

    valid_types = {t.value for t in ApprovalType}
    if approval_type not in valid_types:
        fmt.error(
            f"invalid approval type: {approval_type!r}",
            code="APPROVAL_VALIDATION_ERROR",
        )
        raise SystemExit(1)

    if expires_in:
        try:
            expires_at = _parse_expires_in(expires_in)
        except (ValueError, OverflowError) as e:
            # ``_parse_expires_in`` 은 invalid format 시 ``ValueError`` 를,
            # 너무 큰 숫자 + h/d 입력 시 ``timedelta`` 에서 ``OverflowError``
            # 를 raise 한다. 둘 다 ingress validation 실패이므로 동일하게
            # ``APPROVAL_VALIDATION_ERROR`` 구조화 에러로 종료시켜 Python
            # traceback 노출을 차단한다 (#1518; line 57-58 / 92-94 패턴과 동형).
            fmt.error(
                f"잘못된 expires-in: {e}",
                code="APPROVAL_VALIDATION_ERROR",
            )
            raise SystemExit(1) from e
    else:
        expires_at = ""

    async def _create() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "approval.request",
            {
                "type": approval_type,
                "requester": requester,
                "title": title,
                "body": body,
                "params": params,
                "reference_id": reference_id,
                "expires_at": expires_at,
            },
            actor=requester,
        )

    try:
        result = asyncio.run(_create())
        fmt.success(f"결재 요청 생성: {result.get('id', '')}", result)
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("list")
@click.option("--status", default=None, help="상태 필터")
@click.option("--type", "approval_type", default=None, help="유형 필터")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:read")
def approval_list(
    ctx: click.Context,
    status: str | None,
    approval_type: str | None,
    db_path: str | None,
) -> None:
    """결재 목록 조회."""
    from ante.cli.main import get_db_path

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    # Preflight: invalid `--status`/`--type`는 `Database` 생성 전에 차단한다.
    # `ApprovalStatus`/`ApprovalType` enum이 SSOT이며 (#1462) inline 비교한다.
    # strategy.py:204-210 패턴과 동형이다.
    if status is not None and status not in {s.value for s in ApprovalStatus}:
        fmt.error(
            f"잘못된 status 값: {status!r}. "
            f"허용값: {sorted(s.value for s in ApprovalStatus)}",
            code="APPROVAL_INVALID_STATUS",
        )
        raise SystemExit(1)

    if approval_type is not None and approval_type not in {
        t.value for t in ApprovalType
    }:
        fmt.error(
            f"잘못된 type 값: {approval_type!r}. "
            f"허용값: {sorted(t.value for t in ApprovalType)}",
            code="APPROVAL_INVALID_TYPE",
        )
        raise SystemExit(1)

    async def _list() -> list[dict]:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(resolved_db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        requests = await service.list_approvals(status=status, type=approval_type)
        await db.close()
        return [
            {
                "id": r.id[:8],
                "type": r.type,
                "status": r.status,
                "requester": r.requester,
                "title": r.title,
                "created_at": r.created_at,
            }
            for r in requests
        ]

    try:
        rows = asyncio.run(_list())
        fmt.table(rows, ["id", "type", "status", "requester", "title", "created_at"])
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command()
@click.argument("id")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:read")
def info(ctx: click.Context, id: str, db_path: str | None) -> None:
    """결재 상세 조회."""
    from ante.cli.main import get_db_path

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    async def _info() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(resolved_db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await _find_request(service, id)
        await db.close()
        return {
            "id": req.id,
            "type": req.type,
            "status": req.status,
            "requester": req.requester,
            "title": req.title,
            "body": req.body,
            "params": req.params,
            "reviews": req.reviews,
            "history": req.history,
            "reference_id": req.reference_id,
            "expires_at": req.expires_at,
            "created_at": req.created_at,
            "resolved_at": req.resolved_at,
            "resolved_by": req.resolved_by,
            "reject_reason": req.reject_reason,
        }

    try:
        result = asyncio.run(_info())
        fmt.output(result)
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command()
@click.argument("id")
@click.option(
    "--result",
    "review_result",
    required=True,
    type=click.Choice(["pass", "warn", "fail"]),
    help="검토 결과",
)
@click.option("--detail", default="", help="검토 상세")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:read")
def review(
    ctx: click.Context,
    id: str,
    review_result: str,
    detail: str,
    db_path: str | None,
) -> None:
    """검토 의견 추가."""
    from ante.cli.main import get_db_path

    fmt = get_formatter(ctx)
    reviewer = get_member_id(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    async def _review() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(resolved_db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await service.add_review(
            id=id,
            reviewer=reviewer,
            result=review_result,
            detail=detail,
        )
        await db.close()
        return {
            "id": req.id,
            "reviewer": reviewer,
            "result": review_result,
            "reviews_count": len(req.reviews),
        }

    try:
        result = asyncio.run(_review())
        fmt.success(f"검토 의견 추가: {reviewer} → {review_result}", result)
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("reopen")
@click.argument("id")
@click.option("--body", default=None, help="수정할 본문 (미지정 시 기존 값 유지)")
@click.option(
    "--params",
    "params_json",
    default=None,
    help="수정할 파라미터 (JSON, 미지정 시 기존 값 유지)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("approval:write")
def reopen(
    ctx: click.Context,
    id: str,
    body: str | None,
    params_json: str | None,
) -> None:
    """거절된 결재 재상신."""
    fmt = get_formatter(ctx)
    requester = get_member_id(ctx)

    params = None
    if params_json is not None:
        try:
            params = json.loads(params_json)
        except json.JSONDecodeError as e:
            fmt.error(f"잘못된 JSON 형식: {e}", code="INVALID_JSON")
            raise SystemExit(1) from e
        # ``--params`` 는 service ``params.get()`` 의 SSOT 입력이므로 JSON
        # object 만 허용한다 (#1519; ``request`` 사이트와 동형).
        # ``--params`` 옵션 미지정 (``params_json is None``) 시에는 이 분기에
        # 진입하지 않아 ``params=None`` sentinel 이 보존되어 IPC payload 에
        # ``params`` 키가 빠지고 기존 값 유지 invariant 가 지켜진다.
        # ``--params null`` 명시적 입력은 ``json.loads`` → ``None`` 으로
        # 이 가드에서 거부된다.
        if not isinstance(params, dict):
            params_type = type(params).__name__
            fmt.error(
                f"--params는 JSON object여야 합니다 (현재 타입: {params_type})",
                code="APPROVAL_VALIDATION_ERROR",
            )
            raise SystemExit(1)

    async def _reopen() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        args: dict = {"approval_id": id}
        if body is not None:
            args["body"] = body
        if params is not None:
            args["params"] = params
        return await ipc_send("approval.reopen", args, actor=requester)

    try:
        result = asyncio.run(_reopen())
        fmt.success(f"결재 재상신: {result.get('id', id)}", result)
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("audit-types")
@click.option("--status", default=None, help="상태 필터 (예: pending)")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:read")
def audit_types(
    ctx: click.Context,
    status: str | None,
    db_path: str | None,
) -> None:
    """``ApprovalType`` enum 외 ``type`` 을 가진 legacy invalid row 식별 (#1472).

    분류는 ``offline`` (DB 직접 조회) 이며 ``approval list`` 와 동일하게
    ``ApprovalService.initialize()`` 가 수반된다. 정상 type row 는 enum SSOT
    의 모든 멤버를 ``NOT IN`` 으로 제외하므로 결과에서 자동으로 빠진다.

    출력 컬럼: id, type, status, requester, created_at, expires_at.
    """
    from ante.cli.main import get_db_path

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    # status 는 enum 외의 invalid 값을 허용해야 하는가? 일반 운영자가 자유 입력
    # 으로 잘못된 status 필터를 지정하면 즉시 에러로 알리는 것이 안전하다.
    # ``approval list`` 와 같은 preflight 패턴을 사용한다.
    if status is not None and status not in {s.value for s in ApprovalStatus}:
        fmt.error(
            f"잘못된 status 값: {status!r}. "
            f"허용값: {sorted(s.value for s in ApprovalStatus)}",
            code="APPROVAL_INVALID_STATUS",
        )
        raise SystemExit(1)

    async def _list() -> list[dict]:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(resolved_db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()
        try:
            requests = await service.list_invalid_type_requests(status=status)
        finally:
            await db.close()
        return [
            {
                "id": r.id,
                "type": r.type,
                "status": r.status,
                "requester": r.requester,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
            }
            for r in requests
        ]

    try:
        rows = asyncio.run(_list())
        fmt.table(
            rows,
            ["id", "type", "status", "requester", "created_at", "expires_at"],
        )
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("cancel-invalid")
@click.argument("id")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:admin")
def cancel_invalid(ctx: click.Context, id: str) -> None:
    """legacy invalid-type approval row 의 administrative cancellation (#1472).

    일반 ``ante approval cancel`` 의 requester ownership rule 을 우회한다 —
    invalid-type row 의 requester 는 신뢰할 수 없거나 사라졌을 수 있다. 이
    명령은 ``approval:admin`` scope 가 필수이며, 정상 type row 는 서비스 가드
    에서 거부된다.

    분류는 ``runtime IPC`` 이므로 서버 가동 중에만 동작하며, 서버 정지 시에는
    ``ante system start`` 후 다시 실행한다. cold-path fallback 은 제공하지
    않는다 (Non-goal).
    """
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _cancel() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "approval.cancel_invalid",
            {"approval_id": id},
            actor=actor,
        )

    try:
        result = asyncio.run(_cancel())
        fmt.success(
            f"invalid-type 결재 cleanup: {result.get('id', id)}",
            result,
        )
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("cancel")
@click.argument("id")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:write")
def cancel(ctx: click.Context, id: str) -> None:
    """결재 철회 (요청자만 가능)."""
    fmt = get_formatter(ctx)
    requester = get_member_id(ctx)

    async def _cancel() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("approval.cancel", {"approval_id": id}, actor=requester)

    try:
        result = asyncio.run(_cancel())
        fmt.success(f"결재 철회: {result.get('id', id)}", result)
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("approve")
@click.argument("id")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:admin")
def approve(ctx: click.Context, id: str) -> None:
    """결재 승인."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _approve() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("approval.approve", {"approval_id": id}, actor=actor)

    try:
        result = asyncio.run(_approve())
        fmt.success(f"결재 승인: {result.get('id', id)}", result)
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("reject")
@click.argument("id")
@click.option("--reason", default="", help="거절 사유")
@format_option
@click.pass_context
@require_auth
@require_scope("approval:admin")
def reject(ctx: click.Context, id: str, reason: str) -> None:
    """결재 거절."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _reject() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "approval.reject",
            {"approval_id": id, "reason": reason},
            actor=actor,
        )

    try:
        result = asyncio.run(_reject())
        fmt.success(f"결재 거절: {result.get('id', id)}", result)
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


async def _find_request(service, id: str):  # type: ignore[no-untyped-def]
    """ID 전체 또는 prefix로 결재 요청 검색."""
    req = await service.get(id)
    if req:
        return req

    # prefix 검색
    all_requests = await service.list_approvals(limit=100)
    matches = [r for r in all_requests if r.id.startswith(id)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(m.id[:8] for m in matches)
        msg = f"여러 건이 일치합니다: {ids}"
        raise ValueError(msg)

    msg = f"결재 요청을 찾을 수 없음: {id}"
    raise ValueError(msg)


def _parse_expires_in(expires_in: str) -> str:
    """'72h', '7d' 같은 상대 시간을 절대 시각 ISO 문자열로 변환."""
    from datetime import UTC, datetime, timedelta

    value = expires_in.rstrip("hHdD")
    try:
        num = int(value)
    except ValueError as e:
        msg = f"잘못된 expires-in 형식: {expires_in}"
        raise ValueError(msg) from e

    unit = expires_in[-1].lower()
    if unit == "h":
        delta = timedelta(hours=num)
    elif unit == "d":
        delta = timedelta(days=num)
    else:
        msg = f"지원하지 않는 시간 단위: {unit} (h 또는 d만 가능)"
        raise ValueError(msg)

    return (datetime.now(UTC) + delta).isoformat()
