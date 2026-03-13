"""알림 이력 저장 + 조회 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BotErrorEvent, NotificationEvent, OrderFilledEvent
from ante.notification.base import NotificationAdapter, NotificationLevel
from ante.notification.service import NOTIFICATION_HISTORY_SCHEMA, NotificationService


class MockAdapter(NotificationAdapter):
    """테스트용 Mock 어댑터."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[NotificationLevel, str]] = []
        self.fail = fail

    async def send(self, level: NotificationLevel, message: str) -> bool:
        if self.fail:
            msg = "send failed"
            raise ConnectionError(msg)
        self.sent.append((level, message))
        return True

    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        if self.fail:
            msg = "send_rich failed"
            raise ConnectionError(msg)
        self.sent.append((level, title))
        return True


@pytest.fixture
async def db(tmp_path):
    """테스트용 DB."""
    _db = Database(str(tmp_path / "test.db"))
    await _db.connect()
    yield _db
    await _db.close()


@pytest.fixture
def adapter():
    return MockAdapter()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def service(adapter, eventbus, db):
    svc = NotificationService(adapter=adapter, eventbus=eventbus, db=db)
    await svc.initialize()
    svc.subscribe()
    return svc


class TestNotificationHistory:
    """알림 이력 DB 저장 테스트."""

    async def test_send_records_history(self, service, db):
        """send 호출 후 이력이 DB에 기록된다."""
        await service._send_and_record(
            NotificationLevel.INFO,
            "테스트 메시지",
            event_type="TestEvent",
            bot_id="bot1",
        )

        rows = await service.get_history()
        assert len(rows) == 1
        assert rows[0]["level"] == "info"
        assert rows[0]["message"] == "테스트 메시지"
        assert rows[0]["success"] == 1
        assert rows[0]["event_type"] == "TestEvent"
        assert rows[0]["bot_id"] == "bot1"

    async def test_send_rich_records_history(self, service, db):
        """send_rich 호출 후 이력이 DB에 기록된다."""
        await service._send_rich_and_record(
            NotificationLevel.WARNING,
            title="경고 제목",
            body="경고 상세",
            event_type="NotificationEvent",
        )

        rows = await service.get_history()
        assert len(rows) == 1
        assert rows[0]["title"] == "경고 제목"
        assert rows[0]["message"] == "경고 상세"
        assert rows[0]["level"] == "warning"

    async def test_failed_send_records_error(self, eventbus, db):
        """발송 실패 시 error_message가 기록된다."""
        fail_adapter = MockAdapter(fail=True)
        svc = NotificationService(adapter=fail_adapter, eventbus=eventbus, db=db)
        await svc.initialize()

        await svc._send_and_record(
            NotificationLevel.ERROR,
            "실패할 메시지",
        )

        rows = await svc.get_history()
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert "send failed" in rows[0]["error_message"]

    async def test_event_handler_records_history(self, service, eventbus, db):
        """이벤트 핸들러를 통한 발송도 이력이 기록된다."""
        await eventbus.publish(BotErrorEvent(bot_id="bot1", error_message="timeout"))

        rows = await service.get_history()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "BotErrorEvent"
        assert rows[0]["bot_id"] == "bot1"

    async def test_notification_event_records_history(self, service, eventbus, db):
        """NotificationEvent도 이력이 기록된다."""
        await eventbus.publish(
            NotificationEvent(level="info", message="알림 제목", detail="알림 본문")
        )

        rows = await service.get_history()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "NotificationEvent"
        assert rows[0]["title"] == "알림 제목"

    async def test_order_filled_records_history(self, service, eventbus, db):
        """OrderFilledEvent도 이력이 기록된다."""
        await eventbus.publish(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=100.0,
                price=72000.0,
                order_type="market",
            )
        )

        rows = await service.get_history()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "OrderFilledEvent"
        assert rows[0]["bot_id"] == "bot1"

    async def test_adapter_type_recorded(self, service, db):
        """adapter_type에 어댑터 클래스 이름이 기록된다."""
        await service._send_and_record(NotificationLevel.INFO, "test")

        rows = await service.get_history()
        assert rows[0]["adapter_type"] == "MockAdapter"


class TestGetHistory:
    """이력 조회 테스트."""

    async def test_limit(self, service, db):
        """limit 파라미터로 조회 건수 제한."""
        for i in range(10):
            await service._send_and_record(NotificationLevel.INFO, f"msg-{i}")

        rows = await service.get_history(limit=3)
        assert len(rows) == 3

    async def test_level_filter(self, service, db):
        """level 필터링."""
        await service._send_and_record(NotificationLevel.INFO, "info msg")
        await service._send_and_record(NotificationLevel.ERROR, "error msg")

        rows = await service.get_history(level="error")
        assert len(rows) == 1
        assert rows[0]["level"] == "error"

    async def test_success_filter(self, eventbus, db):
        """실패 건만 필터링."""
        adapter = MockAdapter()
        svc = NotificationService(adapter=adapter, eventbus=eventbus, db=db)
        await svc.initialize()

        await svc._send_and_record(NotificationLevel.INFO, "success msg")

        fail_adapter = MockAdapter(fail=True)
        svc2 = NotificationService(adapter=fail_adapter, eventbus=eventbus, db=db)
        await svc2._send_and_record(NotificationLevel.ERROR, "fail msg")

        rows = await svc.get_history(success_only=False)
        assert len(rows) == 1
        assert rows[0]["success"] == 0

    async def test_reverse_chronological(self, service, db):
        """최근 알림부터 역순 조회."""
        await service._send_and_record(NotificationLevel.INFO, "first")
        await service._send_and_record(NotificationLevel.INFO, "second")

        rows = await service.get_history()
        assert rows[0]["message"] == "second"
        assert rows[1]["message"] == "first"

    async def test_no_db_returns_empty(self, adapter, eventbus):
        """DB 없는 서비스는 빈 리스트 반환."""
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        rows = await svc.get_history()
        assert rows == []


class TestServiceWithoutDB:
    """DB 없이도 기존 기능이 정상 동작하는지 테스트."""

    async def test_send_works_without_db(self, adapter, eventbus):
        """DB 없이도 알림 발송은 정상 동작."""
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        svc.subscribe()

        await eventbus.publish(BotErrorEvent(bot_id="bot1", error_message="test error"))
        assert len(adapter.sent) == 1

    async def test_initialize_without_db(self, adapter, eventbus):
        """DB 없이 initialize() 호출해도 에러 없음."""
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        await svc.initialize()


# ── CLI 테스트 ──────────────────────────────────────


class TestNotificationCLI:
    @pytest.fixture
    def cli_runner(self):
        from click.testing import CliRunner

        from ante.member.models import Member, MemberRole, MemberType

        mock_master = Member(
            member_id="test-master",
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            org="default",
            name="Test Master",
            status="active",
            scopes=[],
        )

        r = CliRunner()
        original_invoke = r.invoke

        def _invoke_with_auth(cli_cmd, args=None, **kwargs):
            with patch("ante.cli.main.authenticate_member") as mock_auth:

                def _set_member(ctx):
                    ctx.obj = ctx.obj or {}
                    ctx.obj["member"] = mock_master

                mock_auth.side_effect = _set_member
                return original_invoke(cli_cmd, args, **kwargs)

        r.invoke = _invoke_with_auth
        return r

    def test_notification_help(self, cli_runner):
        """notification --help 동작."""
        from ante.cli.main import cli

        result = cli_runner.invoke(cli, ["notification", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output

    def test_notification_list_empty(self, cli_runner, tmp_path):
        """빈 DB에서 notification list 실행."""
        from ante.cli.main import cli

        db_path = str(tmp_path / "test.db")
        import asyncio

        async def _init():
            d = Database(db_path)
            await d.connect()
            await d.execute_script(NOTIFICATION_HISTORY_SCHEMA)
            await d.close()

        asyncio.run(_init())

        result = cli_runner.invoke(cli, ["notification", "list", "--db-path", db_path])
        assert result.exit_code == 0

    def test_notification_list_json(self, cli_runner, tmp_path):
        """JSON 출력 모드."""
        from ante.cli.main import cli

        db_path = str(tmp_path / "test.db")
        import asyncio

        async def _init():
            d = Database(db_path)
            await d.connect()
            await d.execute_script(NOTIFICATION_HISTORY_SCHEMA)
            await d.execute(
                """INSERT INTO notification_history
                   (level, message, adapter_type, success)
                   VALUES (?, ?, ?, ?)""",
                ("info", "test msg", "MockAdapter", True),
            )
            await d.close()

        asyncio.run(_init())

        result = cli_runner.invoke(
            cli, ["--format", "json", "notification", "list", "--db-path", db_path]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert data["notifications"][0]["message"] == "test msg"
