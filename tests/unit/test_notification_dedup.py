"""알림 중복 방지 단위 테스트."""

from __future__ import annotations

import time as time_mod
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.notification.base import NotificationLevel
from ante.notification.service import NotificationService


@pytest.fixture
def service():
    adapter = AsyncMock()
    adapter.send = AsyncMock(return_value=True)
    adapter.send_rich = AsyncMock(return_value=True)
    eventbus = MagicMock()
    eventbus.subscribe = MagicMock()
    return NotificationService(
        adapter=adapter,
        eventbus=eventbus,
        dedup_window=1.0,
    )


class TestDedupBasic:
    @pytest.mark.asyncio
    async def test_first_send_passes(self, service):
        """첫 발송은 정상 통과."""
        result = await service._send(
            NotificationLevel.INFO,
            "테스트 메시지",
        )
        assert result is True
        service._adapter.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_suppressed(self, service):
        """동일 메시지 재발송 억제."""
        await service._send(
            NotificationLevel.INFO,
            "테스트 메시지",
        )
        result = await service._send(
            NotificationLevel.INFO,
            "테스트 메시지",
        )
        assert result is False
        assert service._adapter.send.call_count == 1

    @pytest.mark.asyncio
    async def test_different_message_not_suppressed(self, service):
        """다른 메시지는 억제 안 함."""
        await service._send(NotificationLevel.INFO, "메시지 A")
        result = await service._send(NotificationLevel.INFO, "메시지 B")
        assert result is True
        assert service._adapter.send.call_count == 2

    @pytest.mark.asyncio
    async def test_critical_never_suppressed(self, service):
        """CRITICAL 레벨은 항상 발송."""
        await service._send(
            NotificationLevel.CRITICAL,
            "긴급 알림",
        )
        result = await service._send(
            NotificationLevel.CRITICAL,
            "긴급 알림",
        )
        assert result is True
        assert service._adapter.send.call_count == 2

    @pytest.mark.asyncio
    async def test_after_window_sends_again(self, service):
        """dedup_window 경과 후 재발송 허용."""
        service._dedup_window = 0.1

        await service._send(
            NotificationLevel.INFO,
            "테스트 메시지",
        )

        time_mod.sleep(0.15)

        result = await service._send(
            NotificationLevel.INFO,
            "테스트 메시지",
        )
        assert result is True
        assert service._adapter.send.call_count == 2


class TestDedupSuffix:
    @pytest.mark.asyncio
    async def test_suppressed_count_appended(self, service):
        """억제 후 재발송 시 억제 건수 부기."""
        service._dedup_window = 0.1

        # 첫 발송
        await service._send(NotificationLevel.INFO, "반복 알림")
        # 억제 2건
        await service._send(NotificationLevel.INFO, "반복 알림")
        await service._send(NotificationLevel.INFO, "반복 알림")

        time_mod.sleep(0.15)

        # window 후 재발송 — 억제 건수 부기
        await service._send(NotificationLevel.INFO, "반복 알림")

        assert service._adapter.send.call_count == 2
        last_call = service._adapter.send.call_args_list[-1]
        sent_message = last_call[0][1]
        assert "(2건 억제됨)" in sent_message


class TestDedupRichSend:
    @pytest.mark.asyncio
    async def test_rich_send_dedup(self, service):
        """send_rich도 중복 방지 동작."""
        await service._send_rich(
            NotificationLevel.WARNING,
            "제목",
            "본문 내용",
        )
        result = await service._send_rich(
            NotificationLevel.WARNING,
            "제목",
            "본문 내용",
        )
        assert result is False
        assert service._adapter.send_rich.call_count == 1

    @pytest.mark.asyncio
    async def test_rich_critical_not_suppressed(self, service):
        """send_rich에서도 CRITICAL은 억제 안 함."""
        await service._send_rich(
            NotificationLevel.CRITICAL,
            "긴급",
            "긴급 상세",
        )
        result = await service._send_rich(
            NotificationLevel.CRITICAL,
            "긴급",
            "긴급 상세",
        )
        assert result is True
        assert service._adapter.send_rich.call_count == 2
