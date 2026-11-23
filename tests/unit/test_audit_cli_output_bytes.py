"""audit 1개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. 명령은 IPC를
부르지 않는다(사례마다 IPC 호출 0회를 단언한다). 감사 기록의 ``detail`` 에 든
값은 지금처럼 JSON에만 나가고 text 표에는 나가지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_SECRET = "tok-audit-fixture-0001"

_ROWS: list[dict[str, Any]] = [
    {
        "id": 2,
        "member_id": "agent-1",
        "action": "member.rotate_token",
        "resource": "member:agent-1",
        "detail": f'{{"token": "{_SECRET}"}}',
        "ip": "",
        "created_at": "2026-01-02 09:00:00",
    },
    {
        "id": 1,
        "member_id": "test-master",
        "action": "config.set",
        "resource": "config:system.log_level",
        "detail": "",
        "ip": "127.0.0.1",
        "created_at": "2026-01-01 08:30:00",
    },
]

_CASES: dict[str, list[str]] = {
    "list_empty": ["audit", "list"],
    "list_rows": ["audit", "list"],
    "list_filtered": [
        "audit",
        "list",
        "--member",
        "agent-1",
        "--action",
        "member.",
        "--from-date",
        "2026-01-01",
        "--to-date",
        "2026-01-31",
        "--limit",
        "5",
        "--offset",
        "1",
    ],
}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock, AsyncMock]:
    from ante.cli.main import cli

    rows = [] if branch == "list_empty" else [dict(r) for r in _ROWS]
    query = AsyncMock(return_value=rows)

    class _FakeLogger:
        def __init__(self, db: Any) -> None:
            self.query = query

        async def initialize(self) -> None:
            return None

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    ipc_send = AsyncMock(side_effect=AssertionError("IPC를 부르면 안 된다"))
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.audit.open_cli_db", _open_cli_db),
            ("ante.audit.AuditLogger", _FakeLogger),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send, query


_AUDIT_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("{'message': '감사 로그가 없습니다.', 'logs': []}\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "감사 로그가 없습니다.",\n'
        '    "logs": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "          id |    member_id |       action |     resource |   created_at\n"
        "------------------------------------------------------------------------\n"
        "           2 |      agent-1 | member.rotate_token | member:agent-1 | 2026-01"
        "-02 09:00:00\n"
        "           1 |  test-master |   config.set | config:system.log_level | 2026-"
        "01-01 08:30:00\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "logs": [\n'
        "      {\n"
        '        "id": 2,\n'
        '        "member_id": "agent-1",\n'
        '        "action": "member.rotate_token",\n'
        '        "resource": "member:agent-1",\n'
        '        "detail": "{\\"token\\": \\"tok-audit-fixture-0001\\"}",\n'
        '        "ip": "",\n'
        '        "created_at": "2026-01-02 09:00:00"\n'
        "      },\n"
        "      {\n"
        '        "id": 1,\n'
        '        "member_id": "test-master",\n'
        '        "action": "config.set",\n'
        '        "resource": "config:system.log_level",\n'
        '        "detail": "",\n'
        '        "ip": "127.0.0.1",\n'
        '        "created_at": "2026-01-01 08:30:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_filtered", "text"): (
        "          id |    member_id |       action |     resource |   created_at\n"
        "------------------------------------------------------------------------\n"
        "           2 |      agent-1 | member.rotate_token | member:agent-1 | 2026-01"
        "-02 09:00:00\n"
        "           1 |  test-master |   config.set | config:system.log_level | 2026-"
        "01-01 08:30:00\n"
    ),
    ("list_filtered", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "logs": [\n'
        "      {\n"
        '        "id": 2,\n'
        '        "member_id": "agent-1",\n'
        '        "action": "member.rotate_token",\n'
        '        "resource": "member:agent-1",\n'
        '        "detail": "{\\"token\\": \\"tok-audit-fixture-0001\\"}",\n'
        '        "ip": "",\n'
        '        "created_at": "2026-01-02 09:00:00"\n'
        "      },\n"
        "      {\n"
        '        "id": 1,\n'
        '        "member_id": "test-master",\n'
        '        "action": "config.set",\n'
        '        "resource": "config:system.log_level",\n'
        '        "detail": "",\n'
        '        "ip": "127.0.0.1",\n'
        '        "created_at": "2026-01-01 08:30:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
}


class TestAuditOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_AUDIT_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send, query = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _AUDIT_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == 0
        assert query.await_count == 1

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _AUDIT_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""

    def test_filters_reach_query(self) -> None:
        _, _, query = _invoke_case("list_filtered", "text")
        assert query.await_args.kwargs == {
            "member_id": "agent-1",
            "action": "member.",
            "from_date": "2026-01-01",
            "to_date": "2026-01-31",
            "limit": 5,
            "offset": 1,
        }

    @pytest.mark.parametrize(("mode", "count"), [("text", 0), ("json", 1)])
    def test_detail_value_appears_as_now(self, mode: str, count: int) -> None:
        result, _, _ = _invoke_case("list_rows", mode, mix_stderr=False)
        assert result.stdout.count(_SECRET) == count
        assert _SECRET not in result.stderr
