"""리포트 상태와 IPC 서버 상태 전이의 특성 테스트 (#2688).

두 상태를 쓰는 자리에는 가드가 없다. 지금 코드가 모든 (이전, 다음) 쌍을
예외 없이 통과시킨다는 것을 공개 API로 잠근다. 누가 쓰는 자리에 가드를
더하면 이 테스트가 실패하고, 그 변경은 전이표를 함께 좁혀야 한다.

리포트는 실제 DB의 ``ReportStore`` 로 6개 이전 상태 × 6개 대상을 지난다.
이전 상태는 ``submit`` 으로 그 상태의 행을 넣어 만든다. 이전 행에
``reviewed_at``·``user_notes`` 가 있는 사례는 ``submit`` 뒤
``update_status(..., REVIEWED, user_notes="이전")`` 로 만든다.

IPC 서버는 공개 메서드만으로 4개 이전 상태를 만들고, 네 수명주기 메서드,
``drain_connections``, ``stop()`` 을 부른다. 각 사례 끝에 테스트가 만든
listener를 모두 닫는다.

뒤쪽은 두 전이표가 리터럴로 적은 쌍(36쌍, 16쌍)과 같은지 본다.

기대값은 모두 리터럴(상태 문자열, 열 값)이다.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPC_SERVER_STATE_TRANSITIONS, IPCServer
from ante.report.models import (
    REPORT_STATUS_TRANSITIONS,
    ReportStatus,
    StrategyReport,
)
from ante.report.store import ReportStore

REPORT_ID = "rpt-2688"
OTHER_ID = "rpt-2688-other"

REPORT_STATUSES = ("draft", "submitted", "reviewed", "adopted", "rejected", "archived")

REPORT_TARGETS = (
    ("draft", False),
    ("submitted", False),
    ("reviewed", True),
    ("adopted", True),
    ("rejected", True),
    ("archived", False),
)

NOTES = (
    (None, ""),
    ("결정 메모", "결정 메모"),
)


# ── 리포트 ───────────────────────────────────────────────────────


@pytest.fixture
async def store(tmp_path: Any) -> AsyncIterator[ReportStore]:
    database = Database(str(tmp_path / "state-2688.db"))
    await database.connect()
    try:
        report_store = ReportStore(database)
        await report_store.initialize()
        yield report_store
    finally:
        await database.close()


def _report(report_id: str, status: str) -> StrategyReport:
    return StrategyReport(
        report_id=report_id,
        strategy_name=f"strategy-{report_id}",
        strategy_version="1.0.0",
        strategy_path="strategies/s2688.py",
        status=ReportStatus(status),
        submitted_at=datetime(2026, 11, 22, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2025-01 ~ 2026-01",
        total_return_pct=1.0,
        total_trades=3,
        sharpe_ratio=0.5,
        max_drawdown_pct=-2.0,
        win_rate=50.0,
        summary="요약",
        rationale="근거",
        risks="위험",
        recommendations="권고",
        detail_json="{}",
    )


async def _row(store: ReportStore, report_id: str) -> dict[str, Any] | None:
    return await store._db.fetch_one(
        "SELECT status, user_notes, reviewed_at FROM reports WHERE report_id = ?",
        (report_id,),
    )


async def _row_count(store: ReportStore) -> int:
    row = await store._db.fetch_one("SELECT COUNT(*) AS n FROM reports")
    assert row is not None
    return int(row["n"])


async def _update(
    store: ReportStore, report_id: str, target: str, notes: str | None
) -> None:
    if notes is None:
        await store.update_status(report_id, ReportStatus(target))
    else:
        await store.update_status(report_id, ReportStatus(target), user_notes=notes)


@pytest.mark.parametrize(("notes", "expected_notes"), NOTES)
@pytest.mark.parametrize(("target", "reviewed"), REPORT_TARGETS)
@pytest.mark.parametrize("prior", REPORT_STATUSES)
async def test_report_update_status_passes_every_pair(
    store, prior, target, reviewed, notes, expected_notes
):
    await store.submit(_report(REPORT_ID, prior))
    before = await _row(store, REPORT_ID)
    assert before == {"status": prior, "user_notes": "", "reviewed_at": None}

    await _update(store, REPORT_ID, target, notes)

    after = await _row(store, REPORT_ID)
    assert after is not None
    assert after["status"] == target
    assert after["user_notes"] == expected_notes
    assert (after["reviewed_at"] is not None) is reviewed
    assert await _row_count(store) == 1


@pytest.mark.parametrize(("notes", "expected_notes"), NOTES)
@pytest.mark.parametrize(("target", "reviewed"), REPORT_TARGETS)
async def test_report_update_status_overwrites_prior_review_fields(
    store, target, reviewed, notes, expected_notes
):
    await store.submit(_report(REPORT_ID, "submitted"))
    await store.update_status(REPORT_ID, ReportStatus.REVIEWED, user_notes="이전")
    before = await _row(store, REPORT_ID)
    assert before is not None
    assert before["status"] == "reviewed"
    assert before["user_notes"] == "이전"
    assert before["reviewed_at"] is not None

    await _update(store, REPORT_ID, target, notes)

    after = await _row(store, REPORT_ID)
    assert after is not None
    assert after["status"] == target
    assert after["user_notes"] == expected_notes
    assert (after["reviewed_at"] is not None) is reviewed
    if not reviewed:
        assert after["reviewed_at"] is None


@pytest.mark.parametrize(("target", "reviewed"), REPORT_TARGETS)
async def test_report_update_status_on_missing_id_changes_nothing(
    store, target, reviewed
):
    await store.submit(_report(OTHER_ID, "submitted"))
    await store.update_status(OTHER_ID, ReportStatus.REVIEWED, user_notes="이전")
    before = await _row(store, OTHER_ID)

    await _update(store, REPORT_ID, target, "결정 메모")

    assert await _row_count(store) == 1
    assert await _row(store, REPORT_ID) is None
    after = await _row(store, OTHER_ID)
    assert after == before
    assert after is not None
    assert after["status"] == "reviewed"
    assert after["user_notes"] == "이전"


# ── IPC 서버 ─────────────────────────────────────────────────────


def _registry() -> ServiceRegistry:
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
    )


class _Harness:
    def __init__(self, socket_path: str) -> None:
        self.server = IPCServer(socket_path, _registry(), CommandRegistry())
        self._listeners: list[Any] = []

    def remember(self) -> None:
        for listener in (self.server._server, self.server._closing_server):
            if listener is not None and all(
                listener is not seen for seen in self._listeners
            ):
                self._listeners.append(listener)

    async def call(self, step: Callable[[IPCServer], Awaitable[None] | None]) -> None:
        self.remember()
        result = step(self.server)
        if result is not None:
            await result
        self.remember()

    async def close(self) -> None:
        self.remember()
        for listener in self._listeners:
            listener.close()
            await listener.wait_closed()
        self.server._server = None
        self.server._closing_server = None


async def _start(server: IPCServer) -> None:
    await server.start()


async def _stop_accepting(server: IPCServer) -> None:
    await server.stop_accepting()


def _stop_dispatching(server: IPCServer) -> None:
    server.stop_dispatching()


def _unlink_socket(server: IPCServer) -> None:
    server.unlink_socket()


async def _drain(server: IPCServer) -> None:
    await server.drain_connections(timeout=1.0)


async def _stop(server: IPCServer) -> None:
    await server.stop()


PRIOR_STEPS: dict[str, tuple[Callable[[IPCServer], Any], ...]] = {
    "stopped": (),
    "running": (_start,),
    "shutting_down": (_start, _stop_accepting),
    "draining": (_start, _stop_accepting, _stop_dispatching),
}

IPC_PRIORS = ("stopped", "running", "shutting_down", "draining")

IPC_METHODS = (
    ("start", _start, "running"),
    ("stop_accepting", _stop_accepting, "shutting_down"),
    ("stop_dispatching", _stop_dispatching, "draining"),
    ("unlink_socket", _unlink_socket, "stopped"),
)


@pytest.fixture
async def harness() -> AsyncIterator[_Harness]:
    directory = tempfile.mkdtemp(prefix="ipc2688", dir="/tmp")
    h = _Harness(str(Path(directory) / "s.sock"))
    try:
        yield h
    finally:
        await h.close()
        shutil.rmtree(directory, ignore_errors=True)


async def _enter(h: _Harness, prior: str) -> None:
    for step in PRIOR_STEPS[prior]:
        await h.call(step)
    assert h.server.state.value == prior


@pytest.mark.parametrize(
    ("method", "step", "target"),
    IPC_METHODS,
    ids=[name for name, _, _ in IPC_METHODS],
)
@pytest.mark.parametrize("prior", IPC_PRIORS)
async def test_ipc_lifecycle_method_passes_every_pair(
    harness, prior, method, step, target
):
    await _enter(harness, prior)

    await harness.call(step)

    assert harness.server.state.value == target


@pytest.mark.parametrize("prior", IPC_PRIORS)
async def test_ipc_drain_connections_keeps_state(harness, prior):
    await _enter(harness, prior)

    await harness.call(_drain)

    assert harness.server.state.value == prior


@pytest.mark.parametrize("prior", IPC_PRIORS)
async def test_ipc_stop_ends_stopped_from_every_state(harness, prior):
    await _enter(harness, prior)

    await harness.call(_stop)

    assert harness.server.state.value == "stopped"


# ── 전이표 ───────────────────────────────────────────────────────


def test_report_status_transition_table_allows_every_pair():
    assert {
        k.value: {v.value for v in vs} for k, vs in REPORT_STATUS_TRANSITIONS.items()
    } == {
        "draft": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
        "submitted": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
        "reviewed": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
        "adopted": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
        "rejected": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
        "archived": {
            "draft",
            "submitted",
            "reviewed",
            "adopted",
            "rejected",
            "archived",
        },
    }


def test_ipc_server_state_transition_table_allows_every_pair():
    assert {
        k.value: {v.value for v in vs} for k, vs in IPC_SERVER_STATE_TRANSITIONS.items()
    } == {
        "running": {
            "running",
            "shutting_down",
            "draining",
            "stopped",
        },
        "shutting_down": {
            "running",
            "shutting_down",
            "draining",
            "stopped",
        },
        "draining": {
            "running",
            "shutting_down",
            "draining",
            "stopped",
        },
        "stopped": {
            "running",
            "shutting_down",
            "draining",
            "stopped",
        },
    }
