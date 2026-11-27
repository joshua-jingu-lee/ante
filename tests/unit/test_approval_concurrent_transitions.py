"""결재 상태 전이의 조건부 갱신 — 겹친 처리에서 한 호출만 전이한다 (#3116).

겹침은 sleep 없이 「첫 읽기 직후 Event에서 멈춤」으로 결정적으로 만든다.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.approval.errors import ApprovalStatusConflictError
from ante.approval.models import ApprovalStatus
from ante.approval.service import ApprovalService
from ante.contracts import ipc_error_payload
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalResolvedEvent
from ante.notification.telegram_receiver import TelegramCommandReceiver

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ante"
SERVICE_PATH = SRC_ROOT / "approval" / "service.py"
PAST = "2000-01-01T00:00:00+00:00"


class CountingExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, params: dict[str, Any]) -> None:
        self.calls += 1


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "approval.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def executor() -> CountingExecutor:
    return CountingExecutor()


@pytest.fixture
def resolved_events() -> list[ApprovalResolvedEvent]:
    return []


@pytest.fixture
async def svc(db, executor, resolved_events):
    bus = EventBus()

    async def _collect(event: ApprovalResolvedEvent) -> None:
        resolved_events.append(event)

    bus.subscribe(ApprovalResolvedEvent, _collect)
    service = ApprovalService(db=db, eventbus=bus, executors={"bot_stop": executor})
    await service.initialize()
    return service


class PauseFirstGet:
    """svc.get의 첫 호출을 읽은 직후 멈춘다."""

    def __init__(self, service: ApprovalService) -> None:
        self._orig = service.get
        self.read = asyncio.Event()
        self.release = asyncio.Event()
        self._calls = 0
        service.get = self._get  # type: ignore[method-assign]

    async def _get(self, id: str):
        self._calls += 1
        result = await self._orig(id)
        if self._calls == 1:
            self.read.set()
            await self.release.wait()
        return result


async def _race(service: ApprovalService, first, second) -> tuple[Any, Any]:
    pause = PauseFirstGet(service)
    task = asyncio.create_task(first())
    await pause.read.wait()
    second_result = await second()
    pause.release.set()
    try:
        first_result = await task
    except Exception as exc:
        first_result = exc
    return first_result, second_result


async def _status(db: Database, id: str) -> str:
    row = await db.fetch_one("SELECT status FROM approvals WHERE id = ?", (id,))
    assert row is not None
    return str(row["status"])


async def _create(service: ApprovalService, **kwargs: Any):
    return await service.create(
        "bot_stop", "agent", "t", params={"bot_id": "b1"}, **kwargs
    )


async def _seed_invalid(db: Database, id: str) -> None:
    history = [{"action": "created", "actor": "agent", "at": PAST, "detail": ""}]
    await db.execute(
        """INSERT INTO approvals
           (id, type, status, requester, title, body, params,
            reviews, history, reference_id, expires_at, created_at,
            resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, "legacy_type", "pending", "agent", "t", "", "{}", "[]",
         json.dumps(history), "", "", PAST, "", ""),
    )  # fmt: skip


class TestApproveRaces:
    async def test_approve_twice_runs_executor_once(self, svc, db, executor):
        req = await _create(svc)
        first, second = await _race(
            svc,
            lambda: svc.approve(req.id, "cli"),
            lambda: svc.approve(req.id, "telegram"),
        )
        assert isinstance(first, ApprovalStatusConflictError)
        assert first.current_status == "approved"
        assert first.requested_action == "approve"
        assert second.status == ApprovalStatus.APPROVED
        assert executor.calls == 1
        stored = await svc.get(req.id)
        assert [h["action"] for h in stored.history].count("approved") == 1
        assert await _status(db, req.id) == "approved"

    async def test_reject_loses_to_approve(self, svc, db, executor):
        req = await _create(svc)
        first, _ = await _race(
            svc,
            lambda: svc.reject(req.id, "telegram"),
            lambda: svc.approve(req.id, "cli"),
        )
        assert isinstance(first, ApprovalStatusConflictError)
        assert str(first) == (
            f"결재 '{req.id}' 상태 'approved' 에서 'reject' 작업을 수행할 수 없습니다."
        )
        assert executor.calls == 1
        assert await _status(db, req.id) == "approved"

    async def test_approve_loses_to_reject(self, svc, db, executor):
        req = await _create(svc)
        first, _ = await _race(
            svc,
            lambda: svc.approve(req.id, "cli"),
            lambda: svc.reject(req.id, "telegram"),
        )
        assert isinstance(first, ApprovalStatusConflictError)
        assert first.current_status == "rejected"
        assert executor.calls == 0
        assert await _status(db, req.id) == "rejected"


class TestLoserMatchesSequentialError:
    async def _assert_same_as_sequential(self, loser_exc, sequential, literal):
        with pytest.raises(type(loser_exc)) as seq:
            await sequential()
        assert type(loser_exc) is type(seq.value)
        assert str(loser_exc) == literal
        assert str(seq.value) == literal

    async def test_cancel_loses_to_approve(self, svc):
        req = await _create(svc)
        first, _ = await _race(
            svc,
            lambda: svc.cancel(req.id, "agent"),
            lambda: svc.approve(req.id, "cli"),
        )
        assert type(first) is ValueError
        await self._assert_same_as_sequential(
            first,
            lambda: svc.cancel(req.id, "agent"),
            "pending/on_hold/execution_failed 상태에서만 철회 가능 (현재: approved)",
        )

    async def test_hold_loses_to_approve(self, svc):
        req = await _create(svc)
        first, _ = await _race(
            svc, lambda: svc.hold(req.id), lambda: svc.approve(req.id, "cli")
        )
        assert type(first) is ValueError
        await self._assert_same_as_sequential(
            first,
            lambda: svc.hold(req.id),
            "pending/execution_failed 상태에서만 보류 가능 (현재: approved)",
        )

    async def test_resume_loses_to_cancel(self, svc):
        req = await _create(svc)
        await svc.hold(req.id)
        first, _ = await _race(
            svc, lambda: svc.resume(req.id), lambda: svc.cancel(req.id, "agent")
        )
        assert type(first) is ValueError
        await self._assert_same_as_sequential(
            first,
            lambda: svc.resume(req.id),
            "on_hold 상태에서만 재개 가능 (현재: cancelled)",
        )

    async def test_reopen_loses_to_reopen(self, svc, executor):
        req = await _create(svc)
        await svc.reject(req.id, "user", "no")
        first, _ = await _race(
            svc,
            lambda: svc.reopen(req.id, "agent", body="a"),
            lambda: svc.reopen(req.id, "agent", body="b"),
        )
        assert type(first) is ValueError
        await self._assert_same_as_sequential(
            first,
            lambda: svc.reopen(req.id, "agent"),
            "rejected 상태에서만 reopen 가능 (현재: pending)",
        )
        stored = await svc.get(req.id)
        assert stored.body == "b"
        assert [h["action"] for h in stored.history].count("reopened") == 1

    async def test_cancel_invalid_loses_to_cancel_invalid(self, svc, db):
        await _seed_invalid(db, "legacy-1")
        first, _ = await _race(
            svc,
            lambda: svc.cancel_invalid_type_request("legacy-1", resolved_by="a"),
            lambda: svc.cancel_invalid_type_request("legacy-1", resolved_by="b"),
        )
        assert type(first) is ValueError
        await self._assert_same_as_sequential(
            first,
            lambda: svc.cancel_invalid_type_request("legacy-1", resolved_by="a"),
            "pending/on_hold/execution_failed 상태에서만 cancel-invalid 가능"
            " (현재: cancelled)",
        )
        stored = await svc.get("legacy-1")
        assert stored.resolved_by == "b"


class TestLoserWhoseRereadStillPassesGuard:
    async def test_cancel_loses_to_hold_gets_status_conflict_code(
        self, svc, db, resolved_events
    ):
        req = await _create(svc)
        first, _ = await _race(
            svc, lambda: svc.cancel(req.id, "agent"), lambda: svc.hold(req.id)
        )
        assert isinstance(first, ApprovalStatusConflictError)
        assert str(first) == (
            f"결재 '{req.id}' 상태 'on_hold' 에서 'cancel' 작업을 수행할 수 없습니다."
        )
        assert ipc_error_payload(first)["code"] == "APPROVAL_STATUS_CONFLICT"
        assert await _status(db, req.id) == "on_hold"
        assert resolved_events == []


class TestExpireRaces:
    async def test_approve_loses_to_expire_telegram_reply(self, svc, db, executor):
        req = await _create(svc, expires_at=PAST)
        adapter = MagicMock()
        adapter.answer_callback_query = AsyncMock(return_value=True)
        receiver = TelegramCommandReceiver(
            adapter=adapter, allowed_user_ids=[1], approval_service=svc
        )
        receiver._reply = AsyncMock()  # type: ignore[method-assign]
        callback = {
            "id": "cb",
            "from": {"id": 1},
            "message": {"chat": {"id": 7}},
            "data": f"approve:{req.id}",
        }
        try:
            first, expired = await _race(
                svc,
                lambda: receiver._handle_callback_query(callback),
                svc.expire_stale,
            )
            await receiver._jobs.join()
            assert first is None
            assert expired == 1
            assert executor.calls == 0
            assert await _status(db, req.id) == "expired"
            literal = (
                f"ℹ️ 이미 처리된 결재입니다 (결재 '{req.id}' 상태 'expired' 에서 "
                f"'approve' 작업을 수행할 수 없습니다.)\nID: {req.id}"
            )
            assert adapter.answer_callback_query.call_args.args == (
                "cb",
                "⏳ 처리 중입니다",
            )
            assert receiver._reply.call_args.args == (7, literal)
            await receiver._handle_callback_query(callback)
            await receiver._jobs.join()
            assert receiver._reply.call_args.args == (7, literal)
            assert receiver._reply.await_count == 2
        finally:
            await receiver.stop()

    async def test_expire_loses_to_approve(
        self, svc, db, executor, resolved_events, caplog
    ):
        req = await _create(svc, expires_at=PAST)
        orig = db.fetch_all
        read = asyncio.Event()
        release = asyncio.Event()

        async def _paused_fetch_all(sql, params=()):
            rows = await orig(sql, params)
            read.set()
            await release.wait()
            return rows

        db.fetch_all = _paused_fetch_all
        task = asyncio.create_task(svc.expire_stale())
        await read.wait()
        await svc.approve(req.id, "cli")
        release.set()
        with caplog.at_level(logging.DEBUG, logger="ante.approval.service"):
            assert await task == 0
        assert await _status(db, req.id) == "approved"
        assert executor.calls == 1
        assert [e.resolution for e in resolved_events] == ["approved"]
        assert any(
            r.levelno == logging.DEBUG and r.name == "ante.approval.service"
            for r in caplog.records
        )


class TestExecutionFailedBranchLoses:
    async def _force(self, svc, db, req) -> None:
        await db.execute(
            "UPDATE approvals SET status = 'rejected' WHERE id = ?", (req.id,)
        )
        req.status = ApprovalStatus.APPROVED

    async def test_executor_error_branch_loses(self, db, resolved_events, svc, caplog):
        async def _boom(params: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        svc._executors["bot_stop"] = _boom
        req = await _create(svc)
        await self._force(svc, db, req)
        with caplog.at_level(logging.WARNING, logger="ante.approval.service"):
            await svc._execute_approved(req, "cli")
        assert await _status(db, req.id) == "rejected"
        assert resolved_events == []
        assert any(
            r.levelno == logging.WARNING and r.name == "ante.approval.service"
            for r in caplog.records
        )

    async def test_no_executor_branch_loses(self, db, resolved_events, svc, caplog):
        svc._executors.clear()
        req = await _create(svc)
        await self._force(svc, db, req)
        with caplog.at_level(logging.WARNING, logger="ante.approval.service"):
            await svc._execute_approved(req, "cli")
        assert await _status(db, req.id) == "rejected"
        assert resolved_events == []
        assert any(
            r.levelno == logging.WARNING and r.name == "ante.approval.service"
            for r in caplog.records
        )


_STATUS_WRITES: list[tuple[str, ...]] = [
    ("status", "resolved_at", "resolved_by", "history"),
    ("status", "resolved_at", "resolved_by", "reject_reason", "history"),
    ("status", "body", "params", "reviews", "history", "reject_reason",
     "resolved_at", "resolved_by"),
    ("status", "resolved_at", "resolved_by", "history"),
    ("status", "history"),
    ("status", "history"),
    ("status", "resolved_at", "resolved_by", "history"),
    ("status", "resolved_at", "resolved_by", "history"),
    ("status", "history"),
    ("status", "history"),
]  # fmt: skip
_OTHER_WRITES: list[tuple[str, ...]] = [("reviews", "history"), ("history",)]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _set_clause(columns: tuple[str, ...]) -> str:
    return "update approvals set " + ", ".join(f"{c} = ?" for c in columns)


def _approval_update_literals() -> dict[Path, list[str]]:
    found: dict[Path, list[str]] = {}
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = _normalize(node.value)
                if "update approvals" in text:
                    found.setdefault(path, []).append(text)
    return found


class TestStaticInvariant:
    def test_update_literals_only_in_service(self):
        found = _approval_update_literals()
        assert sum(len(v) for v in found.values()) > 0
        assert list(found) == [SERVICE_PATH]

    def test_status_writes_are_conditional_and_match_base_columns(self):
        literals = _approval_update_literals()[SERVICE_PATH]
        expected_status = sorted(
            _set_clause(cols) + " where id = ? and status = ? returning id"
            for cols in _STATUS_WRITES
        )
        expected_other = sorted(
            _set_clause(cols) + " where id = ?" for cols in _OTHER_WRITES
        )
        status_literals = sorted(t for t in literals if "set status" in t)
        other_literals = sorted(t for t in literals if "set status" not in t)
        assert len(status_literals) == 10
        assert status_literals == expected_status
        assert all("and status = ?" in t and "returning" in t for t in status_literals)
        assert other_literals == expected_other

    def test_write_calls_take_string_constant_sql(self):
        tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
        checked = 0
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr
                in {"execute", "execute_fetch_one", "execute_fetch_all"}
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_db"
            ):
                continue
            checked += 1
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                ast.dump(first)
            )
        assert checked >= 13
