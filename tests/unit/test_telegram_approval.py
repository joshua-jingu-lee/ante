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


def _make_approval_request(
    *,
    approval_id: str = "abc123",
    title: str = "테스트 결재",
    status: str = "approved",
    history: list | None = None,
) -> MagicMock:
    """ApprovalRequest mock 생성."""
    req = MagicMock()
    req.id = approval_id
    req.title = title
    req.status = status
    req.history = history or []
    return req


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
    mock.approve = AsyncMock(return_value=_make_approval_request(status="approved"))
    mock.reject = AsyncMock(return_value=_make_approval_request(status="rejected"))
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
        """approve 콜백이 suppress_notification=True로 호출한다."""
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
            "abc123", resolved_by="telegram", suppress_notification=True
        )

    async def test_approve_callback_response_format(self, receiver, approval_service):
        """approve 콜백 성공 시 스펙 형식의 응답을 반환한다."""
        approval_service.approve.return_value = _make_approval_request(
            title="예산 증액", status="approved"
        )
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

        reply_text = receiver._reply.call_args[0][1]
        assert "✅ 결재 승인 완료" in reply_text
        assert "제목: 예산 증액" in reply_text
        assert "ID: abc123" in reply_text

    async def test_approve_callback_execution_failed(self, receiver, approval_service):
        """approve 콜백 executor 실행 실패 시 경고 메시지."""
        approval_service.approve.return_value = _make_approval_request(
            title="봇 중지",
            status="execution_failed",
            history=[{"action": "execution_failed", "detail": "봇 미존재"}],
        )
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

        reply_text = receiver._reply.call_args[0][1]
        assert "⚠️ 승인되었으나 실행 실패" in reply_text
        assert "봇 미존재" in reply_text

    async def test_reject_callback(self, receiver, approval_service):
        """reject 콜백이 suppress_notification=True로 호출한다."""
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
            "abc123",
            resolved_by="telegram",
            reject_reason="사용자 거절",
            suppress_notification=True,
        )

    async def test_reject_callback_response_format(self, receiver, approval_service):
        """reject 콜백 성공 시 스펙 형식의 응답을 반환한다."""
        approval_service.reject.return_value = _make_approval_request(
            title="예산 증액", status="rejected"
        )
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

        reply_text = receiver._reply.call_args[0][1]
        assert "❌ 결재 거절 완료" in reply_text
        assert "제목: 예산 증액" in reply_text
        assert "사유: 사용자 거절" in reply_text

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
        """approve ValueError 시 스펙 형식 에러 메시지를 반환한다."""
        approval_service.approve.side_effect = ValueError(
            "pending/execution_failed 상태에서만 승인 가능 (현재: approved)"
        )
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
        reply_text = receiver._reply.call_args[0][1]
        assert "이미 처리된 결재입니다" in reply_text

    async def test_callback_approve_not_found(
        self, receiver, approval_service, adapter
    ):
        """approve 대상을 찾을 수 없을 때 스펙 형식 에러 메시지."""
        approval_service.approve.side_effect = ValueError(
            "결재 요청을 찾을 수 없음: abc123"
        )
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
        reply_text = receiver._reply.call_args[0][1]
        assert "결재를 찾을 수 없습니다" in reply_text
        assert "ID: abc123" in reply_text

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


# ── /approve, /reject 텍스트 명령 스펙아웃 회귀 (#2379) ──
# 텔레그램 결재는 인라인 버튼 callback 전용. 텍스트 명령 /approve·/reject는
# public contract에서 제거되었고, 알 수 없는 명령으로 폴스루해야 한다.
# (콜백 경로 approve:{id}/reject:{id}는 TestCallbackQuery에서 green 유지)


class TestApproveRejectTextCommandsRemoved:
    """텍스트 명령 /approve, /reject 스펙아웃 회귀 (#2379)."""

    async def test_approve_text_command_unknown(self, receiver, approval_service):
        """/approve <id> 텍스트 명령은 알 수 없는 명령으로 응답한다."""
        update = {
            "message": {
                "text": "/approve abc",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)

        reply_text = receiver._reply.call_args[0][1]
        assert reply_text == "알 수 없는 명령입니다. /help를 입력해 주세요."
        approval_service.approve.assert_not_called()

    async def test_reject_text_command_unknown(self, receiver, approval_service):
        """/reject <id> 텍스트 명령은 알 수 없는 명령으로 응답한다."""
        update = {
            "message": {
                "text": "/reject abc 사유",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)

        reply_text = receiver._reply.call_args[0][1]
        assert reply_text == "알 수 없는 명령입니다. /help를 입력해 주세요."
        approval_service.reject.assert_not_called()

    async def test_execute_approve_unknown(self, receiver, approval_service):
        """_execute 경로에서 approve 명령은 알 수 없는 명령으로 폴스루한다."""
        result = await receiver._execute("approve", ["abc"], 12345, 100)
        assert result == "알 수 없는 명령입니다. /help를 입력해 주세요."
        approval_service.approve.assert_not_called()

    async def test_execute_reject_unknown(self, receiver, approval_service):
        """_execute 경로에서 reject 명령은 알 수 없는 명령으로 폴스루한다."""
        result = await receiver._execute("reject", ["abc"], 12345, 100)
        assert result == "알 수 없는 명령입니다. /help를 입력해 주세요."
        approval_service.reject.assert_not_called()

    async def test_help_excludes_approval_text_commands(self, receiver):
        """/help에 /approve, /reject 텍스트 명령이 노출되지 않는다."""
        result = receiver._cmd_help([])
        assert "/approve" not in result
        assert "/reject" not in result

    def test_cmd_approve_reject_methods_removed(self, receiver):
        """_cmd_approve, _cmd_reject 메서드가 제거되었다."""
        assert not hasattr(receiver, "_cmd_approve")
        assert not hasattr(receiver, "_cmd_reject")


# ── NotificationService 결재 이벤트 구독 ─────────
# NotificationService는 이제 NotificationEvent 단일 구독 구조.
# ApprovalCreatedEvent/ApprovalResolvedEvent 개별 핸들러는 제거됨.
# 결재 알림은 ApprovalService가 NotificationEvent를
# 직접 발행하는 방식으로 전환 예정 (#5).
