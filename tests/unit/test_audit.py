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


# ── CLI ``ante audit list`` ─────────────────────────


class _AuditQueryError(Exception):
    """테스트 전용: 조회 단계의 임의 실패."""


def _invoke_audit_list(args: list[str]):  # noqa: ANN202
    from unittest.mock import patch

    from click.testing import CliRunner

    from ante.cli.main import cli
    from ante.member.models import Member, MemberRole, MemberType

    master = Member(
        member_id="test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Test Master",
        status="active",
        scopes=[],
    )

    def _set_member(ctx) -> None:  # noqa: ANN001
        ctx.obj = ctx.obj or {}
        ctx.obj["member"] = master

    with patch("ante.cli.main.authenticate_member", side_effect=_set_member):
        return CliRunner().invoke(cli, args)


class TestAuditListCli:
    """``audit list`` 의 DB 수명과 스키마 초기화."""

    def test_list_initializes_schema_on_fresh_db(self, tmp_path) -> None:
        """테이블이 없는 새 DB에서도 스키마를 만들고 빈 결과로 끝난다."""
        import json
        import sqlite3

        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)

        result = _invoke_audit_list(
            ["--config-dir", str(config_dir), "--format", "json", "audit", "list"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["logs"] == []
        conn = sqlite3.connect(config_dir / "db" / "ante.db")
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            conn.close()
        assert "audit_log" in tables

    def test_database_closed_when_query_raises(self, tmp_path) -> None:
        """조회가 실패해도 열린 ``Database`` 를 한 번 닫는다."""
        from unittest.mock import AsyncMock, MagicMock, patch

        db = MagicMock()
        db.connect = AsyncMock()
        db.close = AsyncMock()
        db_cls = MagicMock(return_value=db)
        logger = MagicMock()
        logger.initialize = AsyncMock()
        logger.query = AsyncMock(side_effect=_AuditQueryError("query failed"))

        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.audit.AuditLogger", MagicMock(return_value=logger)),
        ):
            result = _invoke_audit_list(
                ["--config-dir", str(tmp_path), "--format", "json", "audit", "list"]
            )

        assert isinstance(result.exception, _AuditQueryError)
        logger.query.assert_awaited_once()
        db.connect.assert_awaited_once()
        db.close.assert_awaited_once()
