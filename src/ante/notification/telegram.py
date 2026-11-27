"""TelegramAdapter — 텔레그램 봇 API 기반 알림."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

from ante.notification.base import NotificationAdapter, NotificationLevel

logger = logging.getLogger(__name__)

TELEGRAM_REQUEST_TIMEOUT = 5.0

_BOT_PATH_RE = re.compile(r"/bot[^/?#\s'\"]+")

LEVEL_EMOJI = {
    NotificationLevel.CRITICAL: "\U0001f6a8",
    NotificationLevel.ERROR: "\u274c",
    NotificationLevel.WARNING: "\u26a0\ufe0f",
    NotificationLevel.INFO: "\u2139\ufe0f",
}


TELEGRAM_SECRET_ATTR = "_telegram_secret"

_FILTER_FAILURE_MESSAGE = "텔레그램 로그 가림 실패 — 원본 메시지와 예외를 버렸다"

_EXC_FORMATTER = logging.Formatter()


def _redact(text: str, token: object) -> str:
    """주소 꼴의 봇 경로와, 주어지면 원본·인코딩된 토큰을 가린다."""
    text = _BOT_PATH_RE.sub("/bot***", text)
    if isinstance(token, str) and token:
        for secret in (token, quote(token, safe="")):
            text = text.replace(secret, "***")
    return text


def describe_telegram_error(exc: BaseException, token: str) -> str:
    """텔레그램 요청 예외를 봇 토큰을 가린 "종류: 메시지" 문자열로 설명한다."""
    message = _redact(str(exc), token)
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


class TelegramLogRedactFilter(logging.Filter):
    """텔레그램 모듈 로그의 메시지와 트레이스백에서 봇 토큰을 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        """레코드를 가린 완성 문자열과 가린 예외 텍스트로 바꿔 통과시킨다."""
        token = record.__dict__.pop(TELEGRAM_SECRET_ATTR, "")
        try:
            record.msg = _redact(record.getMessage(), token)
            record.args = None
            if record.exc_info and record.exc_info[1] is not None:
                text = _EXC_FORMATTER.formatException(record.exc_info)
                record.exc_text = _redact(text, token)
            elif record.exc_text:
                record.exc_text = _redact(record.exc_text, token)
        except (TypeError, ValueError, LookupError, AttributeError, RuntimeError):
            record.msg = _FILTER_FAILURE_MESSAGE
            record.args = None
            record.exc_text = None
        record.exc_info = None
        return True


logger.addFilter(TelegramLogRedactFilter())


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
        metadata: dict[str, Any] | None = None,
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
        buttons: list[list[dict[str, Any]]],
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
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TELEGRAM_REQUEST_TIMEOUT)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.warning(
                "answerCallbackQuery 오류: %s",
                describe_telegram_error(e, self._bot_token),
            )
            return False

    async def _send_message(
        self,
        text: str,
        parse_mode: str = "",
        reply_markup: dict[str, Any] | None = None,
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
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        title = text.split("\n", 1)[0][:80]
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=TELEGRAM_REQUEST_TIMEOUT)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        return True
                    logger.warning(
                        "텔레그램 발송 실패: status=%d, 알림=%s", resp.status, title
                    )
                    return False
        except Exception as e:
            logger.error(
                "텔레그램 발송 오류: %s, 알림=%s",
                describe_telegram_error(e, self._bot_token),
                title,
            )
            return False
