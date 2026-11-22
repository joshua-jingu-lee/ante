"""approval 명령 6개의 응답·서비스 호출·감사 기록 특성 테스트 (#2683 ④).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
``approval`` 메서드를 기록하는 대역이다. 요청자·행위자는 요청 인자가 아니라
요청 봉투의 ``actor``에서 온다. CLI 경로 테스트는 실제 ``cli.main``의 ``ipc_send``를
이 서버의 ``_dispatch``로 잇는다.
"""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.approval.models import ApprovalRequest
from ante.cli.main import cli
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState
from ante.member.models import Member, MemberRole, MemberType
from tests.unit.ipc.validation_messages import validation_message

ACTOR = "ops-lead"
CLI_MEMBER = "cli-master-7"
NESTED_PARAMS = {"bot_id": "b-1", "config": {"n": 2, "ratio": 0.5}, "tags": ["x", 3]}


def _approval(**overrides: Any) -> ApprovalRequest:
    base: dict[str, Any] = {
        "id": "apr-9",
        "type": "strategy_adopt",
        "status": "pending",
        "requester": ACTOR,
        "title": "t",
    }
    base.update(overrides)
    return ApprovalRequest(**base)


class _Harness:
    def __init__(self) -> None:
        approval = MagicMock()
        approval.create = AsyncMock(return_value=_approval())
        approval.approve = AsyncMock(return_value=_approval(status="approved"))
        approval.reject = AsyncMock(return_value=_approval(status="rejected"))
        approval.cancel = AsyncMock(return_value=_approval(status="cancelled"))
        approval.cancel_invalid_type_request = AsyncMock(
            return_value=_approval(type="legacy_kind", status="cancelled")
        )
        approval.reopen = AsyncMock(return_value=_approval(status="pending"))
        self.approval = approval
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=approval,
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            audit_logger=self.audit_logger,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any, actor: str = ACTOR) -> dict:
        return await self.server._dispatch(
            {"id": "req-1", "command": command, "args": args, "actor": actor}
        )

    def assert_audited(self, action: str, resource: str, detail: str = "") -> None:
        self.audit_logger.log.assert_awaited_once_with(
            member_id=ACTOR, action=action, resource=resource, detail=detail, ip=""
        )

    def assert_no_service_call(self) -> None:
        for name in (
            "create",
            "approve",
            "reject",
            "cancel",
            "cancel_invalid_type_request",
            "reopen",
        ):
            getattr(self.approval, name).assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


def _ok(result: dict) -> dict:
    return {"id": "req-1", "status": "ok", "result": result}


@pytest.mark.asyncio
async def test_request_passes_every_field_and_the_actor_as_requester() -> None:
    harness = _Harness()
    response = await harness.send(
        "approval.request",
        {
            "type": "strategy_adopt",
            "title": "t-2",
            "body": "b-2",
            "params": NESTED_PARAMS,
            "reference_id": "r-2",
            "expires_at": "2026-12-01T00:00:00+00:00",
        },
    )
    assert response == _ok({"id": "apr-9", "status": "pending"})
    harness.approval.create.assert_awaited_once_with(
        type="strategy_adopt",
        requester="ops-lead",
        title="t-2",
        body="b-2",
        params={"bot_id": "b-1", "config": {"n": 2, "ratio": 0.5}, "tags": ["x", 3]},
        reference_id="r-2",
        expires_at="2026-12-01T00:00:00+00:00",
    )
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_defaults() -> None:
    harness = _Harness()
    response = await harness.send(
        "approval.request", {"type": "strategy_adopt", "title": "t-2"}
    )
    assert response == _ok({"id": "apr-9", "status": "pending"})
    harness.approval.create.assert_awaited_once_with(
        type="strategy_adopt",
        requester="ops-lead",
        title="t-2",
        body="",
        params=None,
        reference_id="",
        expires_at="",
    )


@pytest.mark.asyncio
async def test_approve_passes_the_actor_and_audits() -> None:
    harness = _Harness()
    response = await harness.send("approval.approve", {"id": "apr-9"})
    assert response == _ok({"id": "apr-9", "status": "approved"})
    harness.approval.approve.assert_awaited_once_with("apr-9", resolved_by="ops-lead")
    harness.assert_audited("approval.approve", "approval:apr-9")


@pytest.mark.asyncio
async def test_reject_passes_the_reason_and_audits() -> None:
    harness = _Harness()
    response = await harness.send("approval.reject", {"id": "apr-9", "reason": "r-2"})
    assert response == _ok({"id": "apr-9", "status": "rejected"})
    harness.approval.reject.assert_awaited_once_with(
        "apr-9", resolved_by="ops-lead", reject_reason="r-2"
    )
    harness.assert_audited("approval.reject", "approval:apr-9", "reason=r-2")


@pytest.mark.asyncio
async def test_reject_without_a_reason_sends_an_empty_reason() -> None:
    harness = _Harness()
    response = await harness.send("approval.reject", {"id": "apr-9"})
    assert response["status"] == "ok", response
    harness.approval.reject.assert_awaited_once_with(
        "apr-9", resolved_by="ops-lead", reject_reason=""
    )
    harness.assert_audited("approval.reject", "approval:apr-9", "reason=")


@pytest.mark.asyncio
async def test_cancel_passes_the_actor_as_requester_and_audits() -> None:
    harness = _Harness()
    response = await harness.send("approval.cancel", {"id": "apr-9"})
    assert response == _ok({"id": "apr-9", "status": "cancelled"})
    harness.approval.cancel.assert_awaited_once_with("apr-9", requester="ops-lead")
    harness.assert_audited("approval.cancel", "approval:apr-9")


@pytest.mark.asyncio
async def test_cancel_invalid_passes_the_approval_id_and_audits_the_type() -> None:
    harness = _Harness()
    response = await harness.send("approval.cancel_invalid", {"approval_id": "apr-9"})
    assert response == _ok(
        {"id": "apr-9", "status": "cancelled", "type": "legacy_kind"}
    )
    harness.approval.cancel_invalid_type_request.assert_awaited_once_with(
        "apr-9", resolved_by="ops-lead"
    )
    harness.assert_audited("approval.cancel_invalid", "approval:apr-9", "legacy_kind")


@pytest.mark.asyncio
async def test_reopen_passes_body_and_nested_params() -> None:
    harness = _Harness()
    response = await harness.send(
        "approval.reopen", {"id": "apr-9", "body": "b-3", "params": NESTED_PARAMS}
    )
    assert response == _ok({"id": "apr-9", "status": "pending"})
    harness.approval.reopen.assert_awaited_once_with(
        "apr-9",
        requester="ops-lead",
        body="b-3",
        params={"bot_id": "b-1", "config": {"n": 2, "ratio": 0.5}, "tags": ["x", 3]},
    )
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_reopen_without_body_and_params_keeps_both() -> None:
    harness = _Harness()
    response = await harness.send("approval.reopen", {"id": "apr-9"})
    assert response["status"] == "ok", response
    harness.approval.reopen.assert_awaited_once_with(
        "apr-9", requester="ops-lead", body=None, params=None
    )


def _rejected(command: str, loc: str, kind: str) -> dict:
    return {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": validation_message(command, (loc, kind)),
        },
    }


@pytest.mark.asyncio
async def test_missing_id_is_rejected_in_full() -> None:
    harness = _Harness()
    response = await harness.send("approval.approve", {})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "approval.approve 인자 검증 실패: id(missing)",
        },
    }
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args", "loc", "kind"),
    [
        (
            "approval.request",
            {"type": "strategy_adopt", "title": "t", "requester": "someone-else"},
            "requester",
            "extra_forbidden",
        ),
        ("approval.request", {"type": "strategy_adopt"}, "title", "missing"),
        (
            "approval.request",
            {"type": "strategy_adopt", "title": "t", "body": None},
            "body",
            "string_type",
        ),
        (
            "approval.request",
            {"type": "strategy_adopt", "title": "t", "params": "a=1"},
            "params",
            "dict_type",
        ),
        (
            "approval.request",
            {"type": "strategy_adopt", "title": "t", "params": [["a", 1]]},
            "params",
            "dict_type",
        ),
        ("approval.reject", {"id": "apr-9", "reason": None}, "reason", "string_type"),
        ("approval.cancel_invalid", {}, "approval_id", "missing"),
        ("approval.reopen", {"id": "apr-9", "body": 7}, "body", "string_type"),
        ("approval.reopen", {"id": "apr-9", "params": []}, "params", "dict_type"),
        ("approval.cancel", {"id": 7}, "id", "string_type"),
    ],
)
async def test_request_outside_the_model_is_rejected(
    command: str, args: dict[str, Any], loc: str, kind: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response == _rejected(command, loc, kind)
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "params"),
    [
        ({"type": "strategy_adopt", "title": "t", "params": None}, None),
        ({"type": "strategy_adopt", "title": "t", "params": {}}, {}),
    ],
)
async def test_request_params_null_and_empty_are_accepted(
    args: dict[str, Any], params: Any
) -> None:
    harness = _Harness()
    response = await harness.send("approval.request", args)
    assert response["status"] == "ok", response
    assert harness.approval.create.await_args.kwargs["params"] == params


@pytest.mark.asyncio
async def test_params_value_is_not_in_the_response_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    harness = _Harness()
    response = await harness.send(
        "approval.reopen",
        {"id": "apr-9", "params": {"MARKPARAM01x": ["MARKPARAM01x"]}, "body": 7},
    )
    assert response == _rejected("approval.reopen", "body", "string_type")
    assert "MARKPARAM01x" not in json.dumps(response, ensure_ascii=False)
    assert "MARKPARAM01x" not in caplog.text
    harness.assert_no_service_call()


_CLI_MEMBER = Member(
    member_id=CLI_MEMBER,
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="CLI Master",
    status="active",
    scopes=[],
)


def _set_member(ctx: click.Context) -> None:
    ctx.obj = ctx.obj or {}
    ctx.obj["member"] = _CLI_MEMBER


def _run_cli(harness: _Harness, argv: list[str]) -> list[tuple[str, Any, str]]:
    sent: list[tuple[str, Any, str]] = []

    async def _send(command: str, args: Any, actor: str = "cli", **_: Any) -> dict:
        wire = json.loads(json.dumps(args))
        sent.append((command, wire, actor))
        response = await harness.server._dispatch(
            {"id": "req-1", "command": command, "args": wire, "actor": actor}
        )
        assert response["status"] == "ok", response
        return response["result"]

    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.main.authenticate_member", side_effect=_set_member)
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", side_effect=_send)
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=True)
        )
        result = CliRunner(mix_stderr=False).invoke(cli, argv)
    assert result.exit_code == 0, (result.output, result.stderr)
    return sent


def test_cli_request_records_the_logged_in_member_as_requester() -> None:
    harness = _Harness()
    sent = _run_cli(
        harness,
        [
            "approval",
            "request",
            "--type",
            "strategy_adopt",
            "--title",
            "t-4",
            "--body",
            "b-4",
            "--params",
            '{"bot_id": "b-1", "config": {"n": 2}}',
            "--reference-id",
            "r-4",
        ],
    )
    assert [(command, actor) for command, _, actor in sent] == [
        ("approval.request", "cli-master-7")
    ]
    harness.approval.create.assert_awaited_once_with(
        type="strategy_adopt",
        requester="cli-master-7",
        title="t-4",
        body="b-4",
        params={"bot_id": "b-1", "config": {"n": 2}},
        reference_id="r-4",
        expires_at="",
    )
    harness.audit_logger.log.assert_not_awaited()


@pytest.mark.parametrize(
    ("argv", "method", "args", "kwargs", "action", "detail"),
    [
        (
            ["approval", "approve", "apr-9"],
            "approve",
            ("apr-9",),
            {"resolved_by": "cli-master-7"},
            "approval.approve",
            "",
        ),
        (
            ["approval", "reject", "apr-9", "--reason", "r-5"],
            "reject",
            ("apr-9",),
            {"resolved_by": "cli-master-7", "reject_reason": "r-5"},
            "approval.reject",
            "reason=r-5",
        ),
        (
            ["approval", "cancel", "apr-9"],
            "cancel",
            ("apr-9",),
            {"requester": "cli-master-7"},
            "approval.cancel",
            "",
        ),
        (
            ["approval", "cancel-invalid", "apr-9"],
            "cancel_invalid_type_request",
            ("apr-9",),
            {"resolved_by": "cli-master-7"},
            "approval.cancel_invalid",
            "legacy_kind",
        ),
        (
            ["approval", "reopen", "apr-9", "--body", "b-6", "--params", '{"a": [1]}'],
            "reopen",
            ("apr-9",),
            {"requester": "cli-master-7", "body": "b-6", "params": {"a": [1]}},
            None,
            "",
        ),
    ],
)
def test_cli_commands_record_the_logged_in_member_as_actor(
    argv: list[str],
    method: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    action: str | None,
    detail: str,
) -> None:
    harness = _Harness()
    sent = _run_cli(harness, argv)
    assert [actor for _, _, actor in sent] == ["cli-master-7"]
    getattr(harness.approval, method).assert_awaited_once_with(*args, **kwargs)
    if action is None:
        harness.audit_logger.log.assert_not_awaited()
    else:
        harness.audit_logger.log.assert_awaited_once_with(
            member_id="cli-master-7",
            action=action,
            resource="approval:apr-9",
            detail=detail,
            ip="",
        )
