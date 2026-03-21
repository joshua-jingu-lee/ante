"""ante approval — 결재 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope


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
    fmt = get_formatter(ctx)
    requester = get_member_id(ctx)

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        fmt.error(f"잘못된 JSON 형식: {e}", code="INVALID_JSON")
        raise SystemExit(1) from e

    expires_at = _parse_expires_in(expires_in) if expires_in else ""

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
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("approval:read")
def approval_list(
    ctx: click.Context,
    status: str | None,
    approval_type: str | None,
    db_path: str,
) -> None:
    """결재 목록 조회."""
    fmt = get_formatter(ctx)

    async def _list() -> list[dict]:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        requests = await service.list(status=status, type=approval_type)
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
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("approval:read")
def info(ctx: click.Context, id: str, db_path: str) -> None:
    """결재 상세 조회."""
    fmt = get_formatter(ctx)

    async def _info() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
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
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("approval:read")
def review(
    ctx: click.Context,
    id: str,
    review_result: str,
    detail: str,
    db_path: str,
) -> None:
    """검토 의견 추가."""
    fmt = get_formatter(ctx)
    reviewer = get_member_id(ctx)

    async def _review() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
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


@approval.command("cancel")
@click.argument("id")
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
    all_requests = await service.list(limit=100)
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
