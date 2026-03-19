"""TelegramAdapter — 텔레그램 봇 API 기반 알림."""

from __future__ import annotations

import logging

from ante.notification.base import NotificationAdapter, NotificationLevel

logger = logging.getLogger(__name__)

LEVEL_EMOJI = {
    NotificationLevel.CRITICAL: "\U0001f6a8",
    NotificationLevel.ERROR: "\u274c",
    NotificationLevel.WARNING: "\u26a0\ufe0f",
    NotificationLevel.INFO: "\u2139\ufe0f",
}


class TelegramAdapter(NotificationAdapter):
    """텔레그램 봇 API 기반 알림."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._api_base = f"https://api.telegram.org/bot{bot_token}"

    async def send(self, level: NotificationLevel, message: str) -> bool:
        """알림 발송."""
        emoji = LEVEL_EMOJI.get(level, "\U0001f4cc")
        text = f"{emoji} [{level.value.upper()}] {message}"
        return await self._send_message(text)

    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        """서식이 있는 알림 발송."""
        emoji = LEVEL_EMOJI.get(level, "\U0001f4cc")
        parts = [f"{emoji} *{title}*", body]
        if metadata:
            details = "\n".join(f"  `{k}`: {v}" for k, v in metadata.items())
            parts.append(f"\n{details}")
        text = "\n".join(parts)
        return await self._send_message(text, parse_mode="Markdown")

    async def send_with_buttons(
        self,
        level: NotificationLevel,
        message: str,
        buttons: list[list[dict]],
    ) -> bool:
        """인라인 버튼이 포함된 알림 발송.

        Args:
            level: 알림 레벨.
            message: 메시지 본문.
            buttons: 인라인 키보드 버튼 행 목록.
                [[{"text": "승인", "callback_data": "approve:id"}, ...], ...]
        """
        emoji = LEVEL_EMOJI.get(level, "\U0001f4cc")
        text = f"{emoji} {message}"
        reply_markup = {
            "inline_keyboard": buttons,
        }
        return await self._send_message(
            text, parse_mode="Markdown", reply_markup=reply_markup
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str = "",
    ) -> bool:
        """answerCallbackQuery API 호출 (버튼 로딩 해제)."""
        try:
            import aiohttp
        except ImportError:
            return False

        url = f"{self._api_base}/answerCallbackQuery"
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning("answerCallbackQuery 오류: %s", e)
            return False

    async def _send_message(
        self,
        text: str,
        parse_mode: str = "",
        reply_markup: dict | None = None,
    ) -> bool:
        """텔레그램 sendMessage API 호출."""
        try:
            import aiohttp
        except ImportError:
            logger.error(
                "aiohttp가 설치되지 않았습니다. pip install aiohttp로 설치하세요."
            )
            return False

        url = f"{self._api_base}/sendMessage"
        payload: dict = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    logger.warning("텔레그램 발송 실패: status=%d", resp.status)
                    return False
        except Exception as e:
            logger.error("텔레그램 발송 오류: %s", e)
            return False
