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
def _reset_kis_token_state():
    """매 테스트 전후 KIS module-level 토큰 캐시/lock/cooldown 초기화 (#2399).

    글로벌 격리(메타 P2): EGW00133 ``_token_cooldowns`` 상태가 테스트 간 누출되면
    KIS 토큰을 건드리는 후속 테스트의 발급이 cooldown 내로 오판돼 flaky 가 된다.
    기존엔 토큰 single-flight/backoff 테스트 2개 파일에만 reset autouse fixture 가
    있어 cross-test 오염 위험이 있었으므로, 전 테스트가 공유하는 본 글로벌 conftest
    autouse fixture 로 승격해 ``_token_cache``/``_token_locks``/``_token_cooldowns``
    를 매 테스트 경계에서 초기화한다. closed event loop 에 묶인 Lock 재사용(T1
    closed-loop) 방지도 겸한다. ``ante.broker.kis`` 는 import 가드 안에서 안전하게
    lazy import 한다(collection 시 부작용 회피).
    """
    from ante.broker.kis import _reset_token_cache

    _reset_token_cache()
    yield
    _reset_token_cache()


@pytest.fixture(autouse=True)
def _sync_boundary_cleanup():
    """모든 테스트(sync + async) 경계에서 ``patch.stopall`` 보장.

    Refs #2304: 기존 ``_cleanup_tasks`` 는 ``async def`` autouse fixture 라
    async 테스트 경계에서만 ``mock.patch.stopall()`` 을 수행한다. 반면 sync
    테스트(예: ``CliRunner.invoke`` 가 내부적으로 ``asyncio.run(coro)`` 을
    호출하는 ``ante bot remove`` 표면)는 같은 보장 밖에 있어, ``patch.start()``
    후 ``stop()`` 누락(예: ``try`` 진입 전 예외)으로 module attribute 가 mock
    으로 영구 leak 되는 cross-test contamination 이 발생할 수 있다. 본 sync
    autouse fixture 는 sync + async 두 경계 **모두** 에서 매 테스트 종료 직후
    ``mock.patch.stopall()`` 을 한 번 더 수행해 그 leak 을 차단한다(idempotent —
    ``_cleanup_tasks`` async 와 중복 호출되어도 회귀 없음).

    Refs #2309: 본 fixture 에서 매-테스트 ``gc.collect()`` 는 제거했다.
    - ``#2304`` 의 실제 flaky(``test_cli_direct_not_found_via_remove`` 의
      ``EXECUTION_ERROR`` 오분류)는 GC 가능한 누수가 아니라 ``bot remove`` 의
      ``is_active_runtime()`` runtime-state 분기가 비결정적이었던 것이며, 해당
      테스트에 ``is_active_runtime`` mock 을 추가해 결정화했다. broad
      ``gc.collect()`` 는 이 flaky 에 무효였다.
    - ``#2304`` transport 누수는 ``test_server_client.py`` 의 server-side
      transport 명시 ``close()`` (source-close, ``_settle_server_side_transports``)
      로 이미 결정적으로 해소돼 broad GC 안전망이 불필요하다.
    - 매-테스트 ``gc.collect()`` 는 full-suite 시간을 ~2x 로 회귀시키는 고비용
      연산이라 제거해 성능을 회복한다.
    - async 경계의 ``gc.collect()`` 는 ``_cleanup_tasks`` (Refs #1897) 에 그대로
      유지된다.
    """
    yield
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
