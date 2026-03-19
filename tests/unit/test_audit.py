"""감사 로그(AuditLogger) 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ante.audit import AuditLogger
from ante.core.database import Database


@pytest.fixture
async def db(tmp_path):
    """임시 파일 DB."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def audit_logger(db: Database) -> AuditLogger:
    """AuditLogger 인스턴스."""
    al = AuditLogger(db=db)
    await al.initialize()
    return al


# ── 기록 ─────────────────────────────────────────


class TestAuditLog:
    """감사 로그 기록 테스트."""

    async def test_log_and_query(self, audit_logger: AuditLogger) -> None:
        """로그 기록 후 조회."""
        await audit_logger.log(
            member_id="agent-01",
            action="bot.create",
            resource="bot:bot-momentum-01",
            detail='{"strategy": "momentum_v1"}',
        )
        logs = await audit_logger.query()
        assert len(logs) == 1
        assert logs[0]["member_id"] == "agent-01"
        assert logs[0]["action"] == "bot.create"
        assert logs[0]["resource"] == "bot:bot-momentum-01"

    async def test_log_multiple(self, audit_logger: AuditLogger) -> None:
        """여러 건 기록 후 최신순 조회."""
        await audit_logger.log(member_id="user-01", action="auth.login")
        await audit_logger.log(member_id="user-01", action="bot.create")
        await audit_logger.log(member_id="agent-01", action="report.submitted")

        logs = await audit_logger.query()
        assert len(logs) == 3
        # 최신순 (id DESC)
        assert logs[0]["action"] == "report.submitted"
        assert logs[2]["action"] == "auth.login"

    async def test_log_with_ip(self, audit_logger: AuditLogger) -> None:
        """IP 주소 포함 기록."""
        await audit_logger.log(
            member_id="user-01",
            action="auth.login",
            ip="127.0.0.1",
        )
        logs = await audit_logger.query()
        assert logs[0]["ip"] == "127.0.0.1"


# ── 필터 조회 ────────────────────────────────────


class TestAuditQuery:
    """감사 로그 필터 조회 테스트."""

    async def test_filter_by_member(self, audit_logger: AuditLogger) -> None:
        """member_id로 필터링."""
        await audit_logger.log(member_id="user-01", action="auth.login")
        await audit_logger.log(member_id="agent-01", action="bot.create")

        logs = await audit_logger.query(member_id="agent-01")
        assert len(logs) == 1
        assert logs[0]["member_id"] == "agent-01"

    async def test_filter_by_action_prefix(self, audit_logger: AuditLogger) -> None:
        """action prefix로 필터링."""
        await audit_logger.log(member_id="user-01", action="auth.login")
        await audit_logger.log(member_id="user-01", action="auth.failed")
        await audit_logger.log(member_id="user-01", action="bot.create")

        logs = await audit_logger.query(action="auth")
        assert len(logs) == 2

    async def test_filter_combined(self, audit_logger: AuditLogger) -> None:
        """member_id + action 복합 필터."""
        await audit_logger.log(member_id="user-01", action="auth.login")
        await audit_logger.log(member_id="agent-01", action="auth.login")
        await audit_logger.log(member_id="agent-01", action="bot.create")

        logs = await audit_logger.query(member_id="agent-01", action="auth")
        assert len(logs) == 1
        assert logs[0]["member_id"] == "agent-01"
        assert logs[0]["action"] == "auth.login"

    async def test_limit_and_offset(self, audit_logger: AuditLogger) -> None:
        """페이지네이션 (limit, offset)."""
        for i in range(10):
            await audit_logger.log(member_id="user-01", action=f"action.{i}")

        page1 = await audit_logger.query(limit=3, offset=0)
        assert len(page1) == 3

        page2 = await audit_logger.query(limit=3, offset=3)
        assert len(page2) == 3
        assert page1[0]["id"] != page2[0]["id"]


# ── 건수 조회 ────────────────────────────────────


class TestAuditCount:
    """감사 로그 건수 조회."""

    async def test_count_all(self, audit_logger: AuditLogger) -> None:
        """전체 건수."""
        for _ in range(5):
            await audit_logger.log(member_id="user-01", action="auth.login")
        assert await audit_logger.count() == 5

    async def test_count_filtered(self, audit_logger: AuditLogger) -> None:
        """필터 건수."""
        await audit_logger.log(member_id="user-01", action="auth.login")
        await audit_logger.log(member_id="agent-01", action="bot.create")

        assert await audit_logger.count(member_id="user-01") == 1
        assert await audit_logger.count(action="bot") == 1

    async def test_count_empty(self, audit_logger: AuditLogger) -> None:
        """빈 테이블."""
        assert await audit_logger.count() == 0


# ── 스키마 멱등성 ────────────────────────────────


class TestAuditInit:
    """초기화 멱등성."""

    async def test_initialize_idempotent(self, db: Database) -> None:
        """initialize()를 여러 번 호출해도 안전."""
        al = AuditLogger(db=db)
        await al.initialize()
        await al.initialize()
        await al.log(member_id="test", action="test.action")
        assert await al.count() == 1


# ── 보존 기간 정리 ────────────────────────────────


class TestAuditCleanup:
    """감사 로그 보존 기간(retention) 정리 테스트."""

    async def test_cleanup_deletes_old_logs(
        self, audit_logger: AuditLogger, db: Database
    ) -> None:
        """retention_days 이전 로그가 삭제된다."""
        # 현재 로그 1건 기록
        await audit_logger.log(member_id="user-01", action="auth.login")

        # 100일 전 로그를 직접 INSERT
        old_time = (datetime.now(UTC) - timedelta(days=100)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        await db.execute(
            "INSERT INTO audit_log"
            " (member_id, action, resource, detail, ip, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("user-01", "old.action", "", "", "", old_time),
        )
        assert await audit_logger.count() == 2

        deleted = await audit_logger.cleanup(retention_days=90)
        assert deleted == 1
        assert await audit_logger.count() == 1

        # 남은 건은 최근 로그
        logs = await audit_logger.query()
        assert logs[0]["action"] == "auth.login"

    async def test_cleanup_keeps_recent_logs(
        self, audit_logger: AuditLogger, db: Database
    ) -> None:
        """보존 기간 이내 로그는 삭제되지 않는다."""
        # 30일 전 로그 (retention 90일 이내)
        recent_time = (datetime.now(UTC) - timedelta(days=30)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        await db.execute(
            "INSERT INTO audit_log"
            " (member_id, action, resource, detail, ip, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("user-01", "recent.action", "", "", "", recent_time),
        )
        await audit_logger.log(member_id="user-01", action="auth.login")

        deleted = await audit_logger.cleanup(retention_days=90)
        assert deleted == 0
        assert await audit_logger.count() == 2

    async def test_cleanup_zero_retention_disabled(
        self, audit_logger: AuditLogger, db: Database
    ) -> None:
        """retention_days=0이면 삭제하지 않는다."""
        old_time = (datetime.now(UTC) - timedelta(days=1000)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        await db.execute(
            "INSERT INTO audit_log"
            " (member_id, action, resource, detail, ip, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("user-01", "ancient.action", "", "", "", old_time),
        )
        assert await audit_logger.count() == 1

        deleted = await audit_logger.cleanup(retention_days=0)
        assert deleted == 0
        assert await audit_logger.count() == 1

    async def test_cleanup_empty_table(self, audit_logger: AuditLogger) -> None:
        """빈 테이블에서 cleanup 호출해도 안전."""
        deleted = await audit_logger.cleanup(retention_days=90)
        assert deleted == 0

    async def test_cleanup_multiple_old_logs(
        self, audit_logger: AuditLogger, db: Database
    ) -> None:
        """여러 건의 오래된 로그가 한 번에 삭제된다."""
        old_time = (datetime.now(UTC) - timedelta(days=100)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        for i in range(5):
            await db.execute(
                "INSERT INTO audit_log"
                " (member_id, action, resource, detail, ip, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("user-01", f"old.action.{i}", "", "", "", old_time),
            )
        await audit_logger.log(member_id="user-01", action="recent.action")
        assert await audit_logger.count() == 6

        deleted = await audit_logger.cleanup(retention_days=90)
        assert deleted == 5
        assert await audit_logger.count() == 1
