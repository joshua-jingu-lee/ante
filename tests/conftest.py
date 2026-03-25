"""공통 pytest 설정."""

from __future__ import annotations

import asyncio
import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _set_encryption_key():
    """테스트용 Fernet 키 자동 설정 (session scope — 전체 세션에서 1회만 생성)."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    os.environ["ANTE_DB_ENCRYPTION_KEY"] = key
    yield
    os.environ.pop("ANTE_DB_ENCRYPTION_KEY", None)


@pytest.fixture(autouse=True)
async def _cleanup_tasks():
    """각 async 테스트 후 잔여 asyncio 태스크를 강제 정리.

    pytest-asyncio가 function-scope event loop를 사용할 때,
    start된 봇의 background task가 남아있으면 다음 테스트에서
    event loop 생성이 블로킹될 수 있음 (Python 3.11 Ubuntu 환경).
    """
    yield
    loop = asyncio.get_event_loop()
    pending = [
        t
        for t in asyncio.all_tasks(loop)
        if not t.done() and t is not asyncio.current_task()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
