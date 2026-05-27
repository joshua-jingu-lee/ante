"""공통 pytest 설정."""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

import pytest


def _load_import_guard():
    guard_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_import_path.py"
    )
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pytest_configure(config: pytest.Config) -> None:
    """Fail collection if ``ante`` resolves outside this checkout."""
    guard = _load_import_guard()
    try:
        guard.check_import_path()
    except guard.ImportPathCheckError as exc:
        raise pytest.UsageError(str(exc)) from exc


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

    Refs #1897: 각 async 테스트 종료 직후 ``gc.collect()`` 를 한 번 강제해
    이전 테스트가 남긴 ``_SelectorTransport`` / ``aiosqlite.Connection`` /
    ``sqlite3.Connection`` 가 같은 테스트 경계 안에서 GC 되도록 한다. 다음
    테스트로 누수 attribution 이 전이되어 ``PytestUnraisableExceptionWarning``
    / ``ResourceWarning`` 이 무관 테스트에 표시되는 회귀를 방지한다.

    Refs #1904 follow-up: 매 테스트 종료 직후 ``mock.patch.stopall()`` 을
    호출해 ``patch.start()`` 후 ``stop()`` 누락(예: ``try`` 진입 전 예외)으로
    인해 module attribute (``ante.cli.commands.*._create_*``,
    ``ante.cli.main.authenticate_member`` 등) 가 mock 으로 영구 leak 되는
    cross-test contamination 을 차단한다. xdist 환경에서 worker 별 random
    fail (assert exit_code==0 인데 1, ``WARNING ante.config.config`` 가
    captured log 에 잡히는 패턴) 의 baseline 누수원이다.
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
    # Refs #1897: 남은 transport / DB Connection 객체를 결정적으로 정리한다.
    gc.collect()
    # Refs #1904: stop-orphaned patch leak 방어. 정상 패스의 with-block /
    # try-finally 는 already stop 했으므로 idempotent. start() 직후
    # stop() 호출 전 예외가 발생한 leak 만 정리한다.
    mock.patch.stopall()
