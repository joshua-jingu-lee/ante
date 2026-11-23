"""member CLI의 ``--scopes`` 쉼표 목록은 정확히 빈 문자열만 빈 목록이다 (#2876).

공백·쉼표만 있는 입력과 빈 조각이 섞인 입력은 빈 조각을 ``""`` 원소로 남겨
서비스의 scope 검증(``MEMBER_INVALID_SCOPE``)이 DB 쓰기 전에 거부하게 한다.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.ipc.client import IPCClient
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberType
from ante.member.service import MemberService

BLANK_INPUTS = (" ", ",", " , ", "a,,b", "data:read,")
KEPT_SCOPES = ["data:read", "report:read"]


def _cli_master(member_id: str = "test-master") -> Member:
    return Member(
        member_id=member_id,
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="master",
        status="active",
        scopes=[],
    )


def _invoke(args: list[str], master: Member | None = None) -> Any:
    member = master or _cli_master()

    def _set_member(ctx: Any) -> None:
        ctx.obj = ctx.obj or {}
        ctx.obj["member"] = member

    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_member),
        patch("ante.cli.cold_path.is_active_runtime", return_value=False),
    ):
        return CliRunner().invoke(cli, ["--format", "json", *args])


def _envelope(output: str) -> dict[str, Any]:
    line = next(raw for raw in output.splitlines() if raw.startswith("{"))
    return json.loads(line)


def _mock_service(svc: Any) -> Any:
    @asynccontextmanager
    async def _create_service(ctx: Any = None) -> AsyncIterator[Any]:
        yield svc

    return patch("ante.cli.commands.member._create_service", _create_service)


def _sent_update_scopes(value: str) -> list[str]:
    svc = AsyncMock()
    svc.update_scopes.return_value = MagicMock(
        member_id="m1", scopes=[], status="active"
    )
    with _mock_service(svc):
        _invoke(["member", "update-scopes", "m1", "--scopes", value])
    return svc.update_scopes.await_args.args[1]


def _sent_register(extra: list[str]) -> list[str]:
    svc = AsyncMock()
    svc.register.return_value = (
        MagicMock(member_id="m1", type="agent", role="default", org="o", name=""),
        "tok",
    )
    with _mock_service(svc):
        _invoke(["member", "register", "--id", "m1", "--type", "agent", *extra])
    return svc.register.await_args.kwargs["scopes"]


@pytest.mark.parametrize("value", BLANK_INPUTS)
def test_update_scopes_keeps_blank_pieces(value: str) -> None:
    sent = _sent_update_scopes(value)
    assert sent != []
    assert "" in sent


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", []), ("data:read, report:read", KEPT_SCOPES), ("a,b", ["a", "b"])],
)
def test_update_scopes_parses_valid_lists(value: str, expected: list[str]) -> None:
    assert _sent_update_scopes(value) == expected


@pytest.mark.parametrize("value", BLANK_INPUTS)
def test_register_keeps_blank_pieces(value: str) -> None:
    assert "" in _sent_register(["--scopes", value])


@pytest.mark.parametrize(
    ("extra", "expected"),
    [([], []), (["--scopes", ""], []), (["--scopes", "a, b"], ["a", "b"])],
)
def test_register_parses_valid_lists(extra: list[str], expected: list[str]) -> None:
    assert _sent_register(extra) == expected


async def _seed(db_path: Path) -> str:
    db = Database(str(db_path))
    await db.connect()
    try:
        service = MemberService(db, EventBus())
        await service.initialize()
        master, _token, _rk = await service.bootstrap_master("owner", "pw-123456!")
        await service.register(
            member_id="agent-1",
            member_type="agent",
            scopes=KEPT_SCOPES,
            registered_by=master.member_id,
        )
        return master.member_id
    finally:
        await db.close()


async def _stored(db_path: Path, member_id: str) -> Member | None:
    db = Database(str(db_path))
    await db.connect()
    try:
        service = MemberService(db, EventBus())
        await service.initialize()
        return await service.get(member_id)
    finally:
        await db.close()


def _real_service(db_path: Path) -> Any:
    @asynccontextmanager
    async def _create_service(ctx: Any = None) -> AsyncIterator[MemberService]:
        db = Database(str(db_path))
        await db.connect()
        try:
            service = MemberService(db, EventBus())
            await service.initialize()
            yield service
        finally:
            await db.close()

    return patch("ante.cli.commands.member._create_service", _create_service)


@pytest.mark.parametrize("value", BLANK_INPUTS)
def test_real_service_rejects_blank_update_before_write(
    value: str, tmp_path: Path
) -> None:
    db_path = tmp_path / "member.db"
    master_id = asyncio.run(_seed(db_path))

    with _real_service(db_path):
        result = _invoke(
            ["member", "update-scopes", "agent-1", "--scopes", value],
            master=_cli_master(master_id),
        )

    assert result.exit_code != 0
    assert _envelope(result.output)["code"] == "MEMBER_INVALID_SCOPE"
    stored = asyncio.run(_stored(db_path, "agent-1"))
    assert stored is not None
    assert stored.scopes == KEPT_SCOPES


def test_real_service_rejects_blank_register(tmp_path: Path) -> None:
    db_path = tmp_path / "member.db"
    master_id = asyncio.run(_seed(db_path))

    with _real_service(db_path):
        result = _invoke(
            ["member", "register", "--id", "agent-2", "--type", "agent"]
            + ["--scopes", " "],
            master=_cli_master(master_id),
        )

    assert result.exit_code != 0
    assert _envelope(result.output)["code"] == "MEMBER_INVALID_SCOPE"
    assert asyncio.run(_stored(db_path, "agent-2")) is None


def test_real_service_empty_string_clears_scopes(tmp_path: Path) -> None:
    db_path = tmp_path / "member.db"
    master_id = asyncio.run(_seed(db_path))

    with _real_service(db_path):
        result = _invoke(
            ["member", "update-scopes", "agent-1", "--scopes", ""],
            master=_cli_master(master_id),
        )

    assert result.exit_code == 0, result.output
    stored = asyncio.run(_stored(db_path, "agent-1"))
    assert stored is not None
    assert stored.scopes == []


@pytest.mark.asyncio
async def test_real_ipc_handler_rejects_blank_scope_before_write(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "member.db"
    master_id = await _seed(db_path)
    socket_dir = tempfile.mkdtemp(prefix="ipc_scope_csv", dir="/tmp")
    socket_path = str(Path(socket_dir) / "t.sock")

    db = Database(str(db_path))
    await db.connect()
    try:
        service = MemberService(db, EventBus())
        await service.initialize()
        svc_registry = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            member_service=service,
            audit_logger=MagicMock(),
        )
        cmd_registry = CommandRegistry()
        register_all_handlers(cmd_registry)
        server = IPCServer(socket_path, svc_registry, cmd_registry)
        await server.start()
        try:
            response = await IPCClient(socket_path, timeout=5.0).send(
                "member.update_scopes",
                {"member_id": "agent-1", "scopes": [""]},
                actor=master_id,
            )
        finally:
            await server.stop()
        stored = await service.get("agent-1")
    finally:
        await db.close()

    assert response["status"] == "error"
    assert response["error"]["code"] == "MEMBER_INVALID_SCOPE"
    assert stored is not None
    assert stored.scopes == KEPT_SCOPES
