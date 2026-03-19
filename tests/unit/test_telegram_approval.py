"""텔레그램 결재 연동 테스트.

TelegramAdapter.send_with_buttons(), TelegramCommandReceiver 콜백/명령어,
NotificationService의 ApprovalEvent 구독을 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.notification.base import NotificationLevel
from ante.notification.telegram import TelegramAdapter
from ante.notification.telegram_receiver import TelegramCommandReceiver

# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def adapter():
    """TelegramAdapter mock."""
    mock = MagicMock(spec=TelegramAdapter)
    mock._api_base = "https://api.telegram.org/botTEST"
    mock._bot_token = "TEST"
    mock._chat_id = "123"
    mock.send = AsyncMock(return_value=True)
    mock.send_rich = AsyncMock(return_value=True)
    mock.send_with_buttons = AsyncMock(return_value=True)
    mock.answer_callback_query = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def approval_service():
    """ApprovalService mock."""
    mock = MagicMock()
    mock.approve = AsyncMock()
    mock.reject = AsyncMock()
    return mock


@pytest.fixture
def receiver(adapter, approval_service):
    """approval_service가 주입된 TelegramCommandReceiver."""
    return TelegramCommandReceiver(
        adapter=adapter,
        allowed_user_ids=[12345],
        approval_service=approval_service,
    )


# ── TelegramAdapter.send_with_buttons ─────────────


class TestSendWithButtons:
    """send_with_buttons() 단위 테스트."""

    async def test_send_with_buttons_calls_api(self):
        """send_with_buttons가 reply_markup과 함께 _send_message를 호출한다."""
        adapter = TelegramAdapter(bot_token="TEST", chat_id="123")
        adapter._send_message = AsyncMock(return_value=True)

        buttons = [[{"text": "승인", "callback_data": "approve:abc"}]]
        result = await adapter.send_with_buttons(
            NotificationLevel.INFO, "테스트 메시지", buttons
        )

        assert result is True
        adapter._send_message.assert_called_once()
        call_kwargs = adapter._send_message.call_args
        assert call_kwargs[1]["reply_markup"] == {"inline_keyboard": buttons}

    async def test_send_with_buttons_includes_emoji(self):
        """send_with_buttons가 레벨 이모지를 포함한다."""
        adapter = TelegramAdapter(bot_token="TEST", chat_id="123")
        adapter._send_message = AsyncMock(return_value=True)

        await adapter.send_with_buttons(
            NotificationLevel.INFO,
            "테스트",
            [[{"text": "OK", "callback_data": "ok"}]],
        )

        text_arg = adapter._send_message.call_args[0][0]
        assert "\u2139\ufe0f" in text_arg  # INFO 이모지


class TestAnswerCallbackQuery:
    """answer_callback_query() 단위 테스트."""

    async def test_answer_callback_query_success(self):
        """answerCallbackQuery API 호출 성공."""
        adapter = TelegramAdapter(bot_token="TEST", chat_id="123")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await adapter.answer_callback_query("cb123", "완료")

        assert result is True


# ── Callback Query 처리 ──────────────────────────


class TestCallbackQuery:
    """인라인 버튼 콜백 처리 테스트."""

    async def test_approve_callback(self, receiver, approval_service):
        """approve 콜백이 ApprovalService.approve()를 호출한다."""
        update = {
            "callback_query": {
                "id": "cb1",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "approve:abc123",
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)

        approval_service.approve.assert_called_once_with(
            "abc123", resolved_by="telegram"
        )

    async def test_reject_callback(self, receiver, approval_service):
        """reject 콜백이 ApprovalService.reject()를 호출한다."""
        update = {
            "callback_query": {
                "id": "cb2",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "reject:abc123",
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)

        approval_service.reject.assert_called_once_with(
            "abc123", resolved_by="telegram", reject_reason="사용자 거절"
        )

    async def test_callback_unauthorized(self, receiver, adapter):
        """미인가 사용자의 콜백은 거부된다."""
        update = {
            "callback_query": {
                "id": "cb3",
                "from": {"id": 99999},
                "message": {"chat": {"id": 100}},
                "data": "approve:abc123",
            }
        }
        await receiver._handle_update(update)
        adapter.answer_callback_query.assert_called_once()
        assert "권한" in adapter.answer_callback_query.call_args[0][1]

    async def test_callback_invalid_data(self, receiver, adapter):
        """잘못된 callback_data 형식 처리."""
        update = {
            "callback_query": {
                "id": "cb4",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "invalid",
            }
        }
        await receiver._handle_update(update)
        adapter.answer_callback_query.assert_called_once()
        assert "잘못된" in adapter.answer_callback_query.call_args[0][1]

    async def test_callback_unknown_action(self, receiver, adapter):
        """알 수 없는 action 처리."""
        update = {
            "callback_query": {
                "id": "cb5",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "hold:abc123",
            }
        }
        await receiver._handle_update(update)
        adapter.answer_callback_query.assert_called()
        assert "알 수 없는" in adapter.answer_callback_query.call_args[0][1]

    async def test_callback_approve_error(self, receiver, approval_service, adapter):
        """approve 실패 시 에러 메시지를 반환한다."""
        approval_service.approve.side_effect = ValueError("pending 상태가 아님")
        update = {
            "callback_query": {
                "id": "cb6",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "approve:abc123",
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)
        adapter.answer_callback_query.assert_called_once()
        assert "실패" in adapter.answer_callback_query.call_args[0][1]

    async def test_callback_no_approval_service(self, adapter):
        """approval_service 없으면 안내 메시지."""
        r = TelegramCommandReceiver(
            adapter=adapter, allowed_user_ids=[12345], approval_service=None
        )
        update = {
            "callback_query": {
                "id": "cb7",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "approve:abc123",
            }
        }
        await r._handle_update(update)
        adapter.answer_callback_query.assert_called_once()
        assert "ApprovalService" in adapter.answer_callback_query.call_args[0][1]

    async def test_callback_sends_reply(self, receiver, adapter, approval_service):
        """콜백 처리 후 결과 메시지를 chat에 발송한다."""
        update = {
            "callback_query": {
                "id": "cb8",
                "from": {"id": 12345},
                "message": {"chat": {"id": 100}},
                "data": "approve:abc123",
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)
        receiver._reply.assert_called_once()
        assert "승인 완료" in receiver._reply.call_args[0][1]


# ── /approve, /reject 명령어 ─────────────────────


class TestApproveRejectCommands:
    """텍스트 명령어 /approve, /reject 테스트."""

    async def test_approve_command(self, receiver, approval_service):
        """/approve <id> 명령이 ApprovalService.approve()를 호출한다."""
        result = await receiver._cmd_approve(["abc123"])
        assert "승인 완료" in result
        approval_service.approve.assert_called_once_with(
            "abc123", resolved_by="telegram"
        )

    async def test_approve_no_args(self, receiver):
        """/approve 인자 없으면 안내 메시지."""
        result = await receiver._cmd_approve([])
        assert "ID를 지정" in result

    async def test_approve_no_service(self, adapter):
        """approval_service 없으면 안내 메시지."""
        r = TelegramCommandReceiver(
            adapter=adapter, allowed_user_ids=[12345], approval_service=None
        )
        result = await r._cmd_approve(["abc123"])
        assert "연결되지 않았습니다" in result

    async def test_approve_error(self, receiver, approval_service):
        """approve 실패 시 에러 메시지."""
        approval_service.approve.side_effect = ValueError("찾을 수 없음")
        result = await receiver._cmd_approve(["abc123"])
        assert "실패" in result

    async def test_reject_command(self, receiver, approval_service):
        """/reject <id> [reason] 명령이 reject를 호출한다."""
        result = await receiver._cmd_reject(["abc123", "리스크", "과다"])
        assert "거절 완료" in result
        approval_service.reject.assert_called_once_with(
            "abc123", resolved_by="telegram", reject_reason="리스크 과다"
        )

    async def test_reject_default_reason(self, receiver, approval_service):
        """/reject <id> 사유 미지정 시 기본 사유."""
        await receiver._cmd_reject(["abc123"])
        approval_service.reject.assert_called_once_with(
            "abc123", resolved_by="telegram", reject_reason="사용자 거절"
        )

    async def test_reject_no_args(self, receiver):
        """/reject 인자 없으면 안내 메시지."""
        result = await receiver._cmd_reject([])
        assert "ID를 지정" in result

    async def test_reject_no_service(self, adapter):
        """approval_service 없으면 안내 메시지."""
        r = TelegramCommandReceiver(
            adapter=adapter, allowed_user_ids=[12345], approval_service=None
        )
        result = await r._cmd_reject(["abc123"])
        assert "연결되지 않았습니다" in result

    async def test_reject_error(self, receiver, approval_service):
        """reject 실패 시 에러 메시지."""
        approval_service.reject.side_effect = ValueError("이미 처리됨")
        result = await receiver._cmd_reject(["abc123"])
        assert "실패" in result

    async def test_help_includes_approval_commands(self, receiver):
        """/help에 /approve, /reject 명령이 포함된다."""
        result = receiver._cmd_help([])
        assert "/approve" in result
        assert "/reject" in result

    async def test_execute_approve(self, receiver, approval_service):
        """_execute를 통해 /approve가 라우팅된다."""
        result = await receiver._execute("approve", ["abc123"], 12345, 100)
        assert "승인 완료" in result

    async def test_execute_reject(self, receiver, approval_service):
        """_execute를 통해 /reject가 라우팅된다."""
        result = await receiver._execute("reject", ["abc123"], 12345, 100)
        assert "거절 완료" in result


# ── NotificationService 결재 이벤트 구독 ─────────
# NotificationService는 이제 NotificationEvent 단일 구독 구조.
# ApprovalCreatedEvent/ApprovalResolvedEvent 개별 핸들러는 제거됨.
# 결재 알림은 ApprovalService가 NotificationEvent를
# 직접 발행하는 방식으로 전환 예정 (#5).
