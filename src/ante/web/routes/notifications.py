"""알림 API (stub).

notification_history 테이블 제거 후 이력 조회 엔드포인트는 삭제되었다.
텔레그램 채팅방 자체가 발송 이력을 담당한다.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()
