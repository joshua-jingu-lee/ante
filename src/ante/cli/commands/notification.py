"""ante notification — 알림 관리 커맨드.

notification_history 테이블 제거 후 이력 조회 커맨드는 삭제되었다.
텔레그램 채팅방 자체가 발송 이력을 담당한다.
"""

from __future__ import annotations

import click


@click.group()
def notification() -> None:
    """알림 관리."""
