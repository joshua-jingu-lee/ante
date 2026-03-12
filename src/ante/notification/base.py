"""Notification Adapter ABC + 알림 레벨."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum


class NotificationLevel(StrEnum):
    """알림 레벨."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class NotificationAdapter(ABC):
    """알림 채널 추상 기본 클래스."""

    @abstractmethod
    async def send(self, level: NotificationLevel, message: str) -> bool:
        """알림 발송. 성공 시 True."""

    @abstractmethod
    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        """서식이 있는 알림 발송."""
