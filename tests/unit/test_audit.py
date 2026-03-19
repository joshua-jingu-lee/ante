"""감사 로그(AuditLogger) 단위 테스트."""

from __future__ import annotations

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

    async def test_filter_by_from_date(self, audit_logger: AuditLogger) -> None:
        """from_date로 필터링."""
        # 직접 SQL로 과거 날짜 로그 삽입
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "old.action", "2025-01-01T00:00:00"),
        )
        await audit_logger.log(member_id="user-01", action="new.action")

        logs = await audit_logger.query(from_date="2026-01-01")
        assert len(logs) == 1
        assert logs[0]["action"] == "new.action"

    async def test_filter_by_to_date(self, audit_logger: AuditLogger) -> None:
        """to_date로 필터링."""
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "old.action", "2025-01-01T10:00:00"),
        )
        await audit_logger.log(member_id="user-01", action="new.action")

        logs = await audit_logger.query(to_date="2025-12-31")
        assert len(logs) == 1
        assert logs[0]["action"] == "old.action"

    async def test_filter_by_date_range(self, audit_logger: AuditLogger) -> None:
        """from_date + to_date 범위 필터."""
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "jan.action", "2025-01-15T12:00:00"),
        )
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "mar.action", "2025-03-15T12:00:00"),
        )
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "jun.action", "2025-06-15T12:00:00"),
        )

        logs = await audit_logger.query(from_date="2025-02-01", to_date="2025-04-30")
        assert len(logs) == 1
        assert logs[0]["action"] == "mar.action"

    async def test_to_date_includes_full_day(self, audit_logger: AuditLogger) -> None:
        """to_date가 YYYY-MM-DD이면 해당 일자 끝까지 포함."""
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "evening.action", "2025-03-15T23:30:00"),
        )

        logs = await audit_logger.query(to_date="2025-03-15")
        assert len(logs) == 1
        assert logs[0]["action"] == "evening.action"


# ── limit 클램핑 ─────────────────────────────────


class TestAuditLimitClamping:
    """limit 200 클램핑 테스트."""

    async def test_limit_clamped_to_200(self, audit_logger: AuditLogger) -> None:
        """limit > 200이면 200으로 클램핑."""
        for i in range(5):
            await audit_logger.log(member_id="user-01", action=f"action.{i}")

        # limit=500을 전달해도 오류 없이 동작 (내부에서 200으로 클램핑)
        logs = await audit_logger.query(limit=500)
        assert len(logs) == 5  # 데이터가 5건이므로 5건 반환

    async def test_limit_exactly_200(self, audit_logger: AuditLogger) -> None:
        """limit=200은 그대로 통과."""
        await audit_logger.log(member_id="user-01", action="test.action")
        logs = await audit_logger.query(limit=200)
        assert len(logs) == 1


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

    async def test_count_with_date_filter(self, audit_logger: AuditLogger) -> None:
        """날짜 필터 적용 건수."""
        await audit_logger._db.execute(
            """INSERT INTO audit_log (member_id, action, created_at)
               VALUES (?, ?, ?)""",
            ("user-01", "old.action", "2025-01-01T00:00:00"),
        )
        await audit_logger.log(member_id="user-01", action="new.action")

        assert await audit_logger.count(from_date="2026-01-01") == 1
        assert await audit_logger.count(to_date="2025-12-31") == 1
        assert await audit_logger.count() == 2


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
