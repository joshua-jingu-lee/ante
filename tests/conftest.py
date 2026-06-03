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
def _sync_boundary_cleanup():
    """모든 테스트(sync + async) 경계에서 결정적 GC + patch.stopall 보장.

    Refs #2304: 기존 ``_cleanup_tasks`` 는 ``async def`` autouse fixture 라
    async 테스트 경계에서만 ``gc.collect()`` / ``mock.patch.stopall()`` 을
    수행한다. 반면 sync 테스트(예: ``CliRunner.invoke`` 가 내부적으로
    ``asyncio.run(coro)`` 을 호출하는 ``ante bot remove`` 표면)는 같은 보장
    밖에 있어, 직전 async IPC 테스트가 누수한 ``_SelectorTransport`` /
    ``aiosqlite.Connection`` 이 sync 테스트의 ``asyncio.run`` cleanup 또는
    GC 단계에서 ``RuntimeError: Event loop is closed`` 로 표출되며 원래
    ClickException(예: ``BOT_NOT_FOUND``) 을 마스킹해 ``EXECUTION_ERROR`` 로
    오분류되는 cross-test contamination 이 발생한다(full-suite ``-n auto``
    flaky).

    본 sync autouse fixture 는 sync + async 두 경계 **모두** 에서 매 테스트
    종료 직후 ``gc.collect()`` 와 ``mock.patch.stopall()`` 을 한 번 더 수행해,
    leak source 정리(IPC fixture 명시 close)의 보강 안전망으로 작동한다.
    비용은 테스트당 ms 급(빈 GC + idempotent stopall)으로 suite 시간에
    유의미한 영향이 없다. ``_cleanup_tasks`` (async) 와 중복으로 호출되어도
    둘 다 멱등하므로 회귀가 없다.
    """
    yield
    # Refs #2304: 남은 transport / DB Connection 객체를 결정적으로 정리.
    gc.collect()
    # Refs #1904 / #2304: stop-orphaned patch leak 방어 (idempotent).
    mock.patch.stopall()


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

    Refs #2304: 잔여 task 획득에 deprecated ``asyncio.get_event_loop()`` 대신
    ``asyncio.get_running_loop()`` 을 사용한다. async 테스트 경계에서는 항상
    running loop 이 존재하므로 정상 동작하며, 닫힌/신규 loop 을 잘못 획득해
    엉뚱한 loop 의 task 를 건드리거나 ``DeprecationWarning`` 을 유발하는 경로를
    제거한다.
    """
    yield
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # running loop 이 없으면(async fixture teardown 에서는 정상적으로
        # 발생하지 않음) task 정리를 건너뛰고 GC/stopall 만 수행한다.
        gc.collect()
        mock.patch.stopall()
        return
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
