"""approval 10개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. DB를 읽는 명령은
``ApprovalService`` 를, 서버에 위임하는 명령은 ``ipc_send`` 를 대역으로 둔다.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.approval.models import ApprovalRequest
from ante.member.models import Member

_FULL_ID = "abcd1234-aaaa-bbbb-cccc-1234567890ab"

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)


def _request(**overrides: Any) -> ApprovalRequest:
    fields: dict[str, Any] = {
        "id": _FULL_ID,
        "type": "bot_create",
        "status": "pending",
        "requester": "test-master",
        "title": "Test 결재",
        "body": "",
        "params": {},
        "reviews": [],
        "history": [],
        "reference_id": "",
        "expires_at": "",
        "created_at": "2026-01-01T00:00:00",
        "resolved_at": "",
        "resolved_by": "",
        "reject_reason": "",
    }
    fields.update(overrides)
    return ApprovalRequest(**fields)


_CASES: dict[str, list[str]] = {
    "list_empty": ["approval", "list"],
    "list_rows": ["approval", "list"],
    "info": ["approval", "info", _FULL_ID],
    "review": ["approval", "review", _FULL_ID, "--result", "pass"],
    "audit_types_empty": ["approval", "audit-types"],
    "audit_types_rows": ["approval", "audit-types"],
    "request": ["approval", "request", "--type", "bot_create", "--title", "Test 결재"],
    "reopen": ["approval", "reopen", _FULL_ID],
    "cancel": ["approval", "cancel", _FULL_ID],
    "approve": ["approval", "approve", _FULL_ID],
    "reject": ["approval", "reject", _FULL_ID, "--reason", "검토 미흡"],
    "cancel_invalid": ["approval", "cancel-invalid", "invalid-row-1"],
}

_IPC_RESULTS: dict[str, dict[str, Any]] = {
    "request": {
        "id": _FULL_ID,
        "type": "bot_create",
        "status": "pending",
        "requester": "test-master",
        "title": "Test 결재",
    },
    "reopen": {"id": _FULL_ID, "status": "pending"},
    "cancel": {"id": _FULL_ID, "status": "cancelled"},
    "approve": {"id": _FULL_ID, "status": "approved"},
    "reject": {"id": _FULL_ID, "status": "rejected", "reject_reason": "검토 미흡"},
    "cancel_invalid": {"id": "invalid-row-1", "status": "cancelled", "cleanup": True},
}


def _prepare_service(branch: str, service: AsyncMock) -> None:
    service.list_approvals.return_value = []
    service.list_invalid_type_requests.return_value = []
    detail = _request(
        body="본문",
        params={"bot_id": "bot-1"},
        history=[{"action": "created", "actor": "test-master"}],
    )
    service.get.return_value = detail
    service.add_review.return_value = _request(
        reviews=[{"reviewer": "test-master", "result": "pass", "detail": ""}]
    )
    if branch == "list_rows":
        service.list_approvals.return_value = [
            _request(),
            _request(
                id="ffff0000-1111-2222-3333-444455556666",
                type="strategy_adopt",
                status="approved",
                requester="agent-1",
                title="전략 채택",
            ),
        ]
    elif branch == "audit_types_rows":
        service.list_invalid_type_requests.return_value = [
            _request(
                id="invalid-row-1",
                type="legacy_invalid_type",
                expires_at="2026-12-31T00:00:00",
            )
        ]


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    service = AsyncMock()
    _prepare_service(branch, service)
    ipc_send = AsyncMock(return_value=_IPC_RESULTS.get(branch, {}))
    args = _CASES[branch]
    full_args = ["--format", "json", *args] if mode == "json" else list(args)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.approval.ApprovalService", return_value=service)
        )
        stack.enter_context(
            patch("ante.core.database.Database", return_value=AsyncMock())
        )
        stack.enter_context(
            patch("ante.eventbus.bus.EventBus", return_value=MagicMock())
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send)
        )
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_APPROVAL_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("(no data)\n"),
    ("list_empty", "json"): ("[]\n"),
    ("list_rows", "text"): (
        "          id |         type |       status |    requester |        title |"
        "   created_at\n"
        "--------------------------------------------------------------------------"
        "-------------\n"
        "    abcd1234 |   bot_create |      pending |  test-master |      Test 결재"
        " | 2026-01-01T00:00:00\n"
        "    ffff0000 | strategy_adopt |     approved |      agent-1 |        전략 "
        "채택 | 2026-01-01T00:00:00\n"
    ),
    ("list_rows", "json"): (
        "[\n"
        "  {\n"
        '    "id": "abcd1234",\n'
        '    "type": "bot_create",\n'
        '    "status": "pending",\n'
        '    "requester": "test-master",\n'
        '    "title": "Test 결재",\n'
        '    "created_at": "2026-01-01T00:00:00"\n'
        "  },\n"
        "  {\n"
        '    "id": "ffff0000",\n'
        '    "type": "strategy_adopt",\n'
        '    "status": "approved",\n'
        '    "requester": "agent-1",\n'
        '    "title": "전략 채택",\n'
        '    "created_at": "2026-01-01T00:00:00"\n'
        "  }\n"
        "]\n"
    ),
    ("info", "text"): (
        "{'id': 'abcd1234-aaaa-bbbb-cccc-1234567890ab', 'type': 'bot_create', 'stat"
        "us': 'pending', 'requester': 'test-master', 'title': 'Test 결재', 'body': "
        "'본문', 'params': {'bot_id': 'bot-1'}, 'reviews': [], 'history': [{'action"
        "': 'created', 'actor': 'test-master'}], 'reference_id': '', 'expires_at': "
        "'', 'created_at': '2026-01-01T00:00:00', 'resolved_at': '', 'resolved_by':"
        " '', 'reject_reason': ''}\n"
    ),
    ("info", "json"): (
        "{\n"
        '  "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "type": "bot_create",\n'
        '  "status": "pending",\n'
        '  "requester": "test-master",\n'
        '  "title": "Test 결재",\n'
        '  "body": "본문",\n'
        '  "params": {\n'
        '    "bot_id": "bot-1"\n'
        "  },\n"
        '  "reviews": [],\n'
        '  "history": [\n'
        "    {\n"
        '      "action": "created",\n'
        '      "actor": "test-master"\n'
        "    }\n"
        "  ],\n"
        '  "reference_id": "",\n'
        '  "expires_at": "",\n'
        '  "created_at": "2026-01-01T00:00:00",\n'
        '  "resolved_at": "",\n'
        '  "resolved_by": "",\n'
        '  "reject_reason": ""\n'
        "}\n"
    ),
    ("review", "text"): ("검토 의견 추가: test-master → pass\n"),
    ("review", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "검토 의견 추가: test-master → pass",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "reviewer": "test-master",\n'
        '    "result": "pass",\n'
        '    "reviews_count": 1\n'
        "  }\n"
        "}\n"
    ),
    ("audit_types_empty", "text"): ("(no data)\n"),
    ("audit_types_empty", "json"): ("[]\n"),
    ("audit_types_rows", "text"): (
        "          id |         type |       status |    requester |   created_at |"
        "   expires_at\n"
        "--------------------------------------------------------------------------"
        "-------------\n"
        "invalid-row-1 | legacy_invalid_type |      pending |  test-master | 2026-0"
        "1-01T00:00:00 | 2026-12-31T00:00:00\n"
    ),
    ("audit_types_rows", "json"): (
        "[\n"
        "  {\n"
        '    "id": "invalid-row-1",\n'
        '    "type": "legacy_invalid_type",\n'
        '    "status": "pending",\n'
        '    "requester": "test-master",\n'
        '    "created_at": "2026-01-01T00:00:00",\n'
        '    "expires_at": "2026-12-31T00:00:00"\n'
        "  }\n"
        "]\n"
    ),
    ("request", "text"): ("결재 요청 생성: abcd1234-aaaa-bbbb-cccc-1234567890ab\n"),
    ("request", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "결재 요청 생성: abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "type": "bot_create",\n'
        '    "status": "pending",\n'
        '    "requester": "test-master",\n'
        '    "title": "Test 결재"\n'
        "  }\n"
        "}\n"
    ),
    ("reopen", "text"): ("결재 재상신: abcd1234-aaaa-bbbb-cccc-1234567890ab\n"),
    ("reopen", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "결재 재상신: abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "status": "pending"\n'
        "  }\n"
        "}\n"
    ),
    ("cancel", "text"): ("결재 철회: abcd1234-aaaa-bbbb-cccc-1234567890ab\n"),
    ("cancel", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "결재 철회: abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "status": "cancelled"\n'
        "  }\n"
        "}\n"
    ),
    ("approve", "text"): ("결재 승인: abcd1234-aaaa-bbbb-cccc-1234567890ab\n"),
    ("approve", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "결재 승인: abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "status": "approved"\n'
        "  }\n"
        "}\n"
    ),
    ("reject", "text"): ("결재 거절: abcd1234-aaaa-bbbb-cccc-1234567890ab\n"),
    ("reject", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "결재 거절: abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '  "data": {\n'
        '    "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",\n'
        '    "status": "rejected",\n'
        '    "reject_reason": "검토 미흡"\n'
        "  }\n"
        "}\n"
    ),
    ("cancel_invalid", "text"): ("invalid-type 결재 cleanup: invalid-row-1\n"),
    ("cancel_invalid", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "invalid-type 결재 cleanup: invalid-row-1",\n'
        '  "data": {\n'
        '    "id": "invalid-row-1",\n'
        '    "status": "cancelled",\n'
        '    "cleanup": true\n'
        "  }\n"
        "}\n"
    ),
}


class TestApprovalOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_APPROVAL_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_APPROVAL_OUTPUT_BYTES) == 24

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _APPROVAL_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == (1 if branch in _IPC_RESULTS else 0)
