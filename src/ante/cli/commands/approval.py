"""ante approval — 결재 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.main import get_formatter


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
@click.option("--requester", default="agent", help="요청자 식별")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def request(
    ctx: click.Context,
    approval_type: str,
    title: str,
    body: str,
    params_json: str,
    reference_id: str,
    expires_in: str,
    requester: str,
    db_path: str,
) -> None:
    """결재 요청 생성."""
    fmt = get_formatter(ctx)

    try:
        params = json.loads(params_json)
    except json.JSONDecodeError as e:
        fmt.error(f"잘못된 JSON 형식: {e}", code="INVALID_JSON")
        raise SystemExit(1) from e

    expires_at = _parse_expires_in(expires_in) if expires_in else ""

    async def _create() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await service.create(
            type=approval_type,
            requester=requester,
            title=title,
            body=body,
            params=params,
            reference_id=reference_id,
            expires_at=expires_at,
        )
        await db.close()
        return {
            "id": req.id,
            "type": req.type,
            "status": req.status,
            "title": req.title,
        }

    try:
        result = asyncio.run(_create())
        fmt.success(f"결재 요청 생성: {result['id']}", result)
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("list")
@click.option("--status", default=None, help="상태 필터")
@click.option("--type", "approval_type", default=None, help="유형 필터")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
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
@click.option("--reviewer", required=True, help="검토자 식별")
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
def review(
    ctx: click.Context,
    id: str,
    reviewer: str,
    review_result: str,
    detail: str,
    db_path: str,
) -> None:
    """검토 의견 추가."""
    fmt = get_formatter(ctx)

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


@approval.command("cancel")
@click.argument("id")
@click.option("--requester", required=True, help="요청자 식별 (본인 확인용)")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def cancel(ctx: click.Context, id: str, requester: str, db_path: str) -> None:
    """결재 철회 (요청자만 가능)."""
    fmt = get_formatter(ctx)

    async def _cancel() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await service.cancel(id=id, requester=requester)
        await db.close()
        return {"id": req.id, "status": req.status}

    try:
        result = asyncio.run(_cancel())
        fmt.success(f"결재 철회: {result['id']}", result)
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("approve")
@click.argument("id")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def approve(ctx: click.Context, id: str, db_path: str) -> None:
    """결재 승인."""
    fmt = get_formatter(ctx)

    async def _approve() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await service.approve(id=id)
        await db.close()
        return {"id": req.id, "status": req.status, "type": req.type}

    try:
        result = asyncio.run(_approve())
        fmt.success(f"결재 승인: {result['id']}", result)
    except Exception as e:
        fmt.error(str(e), code="APPROVAL_ERROR")
        raise SystemExit(1) from e


@approval.command("reject")
@click.argument("id")
@click.option("--reason", default="", help="거절 사유")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def reject(ctx: click.Context, id: str, reason: str, db_path: str) -> None:
    """결재 거절."""
    fmt = get_formatter(ctx)

    async def _reject() -> dict:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        eventbus = EventBus()
        service = ApprovalService(db=db, eventbus=eventbus)
        await service.initialize()

        req = await service.reject(id=id, reject_reason=reason)
        await db.close()
        return {"id": req.id, "status": req.status, "reject_reason": reason}

    try:
        result = asyncio.run(_reject())
        fmt.success(f"결재 거절: {result['id']}", result)
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
