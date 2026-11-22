"""tests/conftest.py의 시계 누수 가드 (#2768).

가드는 ``pytest_runtest_teardown`` 훅이라 하위 pytest 프로세스에서 그
conftest를 플러그인으로 싣고 결과를 본다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_COMMON = """
import asyncio
from datetime import UTC, datetime

import pytest

from ante.core import clock


class Fixed:
    def now(self, tz):
        return datetime(2026, 1, 1, tzinfo=UTC).astimezone(tz)

    def monotonic(self):
        return 0.0


async def sleep_in_clock(c):
    with clock.use_clock(c):
        await asyncio.sleep(3600)


def is_system():
    return type(clock.current_clock()) is clock.SystemClock
"""

_CONFTEST = """
import pytest

from ante.core import clock
from clockcommon import Fixed


@pytest.fixture(autouse=True)
def aaa_restores_in_teardown():
    with clock.use_clock(Fixed()):
        yield


@pytest.fixture(autouse=True)
def zzz_restores_in_teardown():
    with clock.use_clock(Fixed()):
        yield
"""

_TEST_SUB = """
from ante.core import clock
from clockcommon import Fixed


def test_sub_clock_set_by_nested_conftest_fixtures():
    assert type(clock.current_clock()) is Fixed
"""

_TEST_MAIN = """
import asyncio

import pytest

from ante.core import clock
from clockcommon import Fixed, is_system, sleep_in_clock


@pytest.fixture
def fixed_clock():
    with clock.use_clock(Fixed()) as c:
        yield c


def test_a_leaks():
    clock.set_clock(Fixed())


def test_b_sees_system_clock_again():
    assert is_system()


def test_c_use_clock_is_fine():
    with clock.use_clock(Fixed()):
        pass


def test_d_fixture_restoring_in_teardown_is_fine(fixed_clock):
    assert clock.current_clock() is fixed_clock


async def test_e_bg_tasks_in_use_clock_then_leak():
    clock.set_clock(Fixed())
    asyncio.get_running_loop().create_task(sleep_in_clock(Fixed()))
    await asyncio.sleep(0)


def test_f_after_bg_tasks():
    assert is_system()


async def test_g_bg_task_in_use_clock_cancelled_by_cleanup():
    asyncio.get_running_loop().create_task(sleep_in_clock(Fixed()))
    await asyncio.sleep(0)
    assert not is_system()


def test_h_after_cancelled_bg_task():
    assert is_system()
"""

_TEST_MODULE_SCOPE = """
import pytest

from ante.core import clock
from clockcommon import Fixed, is_system


@pytest.fixture(scope="module", autouse=True)
def module_clock():
    with clock.use_clock(Fixed()):
        yield


def test_m1_first_in_module():
    pass


def test_m2_second_in_module():
    assert is_system()
"""


def _run_inner(root: Path) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root), str(_REPO / "tests"), str(_REPO / "src"), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "conftest",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:xdist",
            "-p",
            "no:randomly",
            "-o",
            "asyncio_mode=auto",
            "--rootdir",
            str(root),
            "-q",
            "-rA",
            "test_main.py",
            "test_module_scope.py",
            "sub",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    return f"exit={result.returncode}\n{result.stdout}{result.stderr}"


def test_guard_fails_only_the_test_that_left_the_clock_changed(
    tmp_path: Path,
) -> None:
    (tmp_path / "clockcommon.py").write_text(_COMMON, encoding="utf-8")
    (tmp_path / "test_main.py").write_text(_TEST_MAIN, encoding="utf-8")
    (tmp_path / "test_module_scope.py").write_text(_TEST_MODULE_SCOPE, encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (tmp_path / "sub" / "test_sub.py").write_text(_TEST_SUB, encoding="utf-8")

    out = _run_inner(tmp_path)

    assert out.startswith("exit=1\n"), out
    assert "11 passed, 3 errors" in out, out
    errors = sorted(
        line.split(" - ")[0] for line in out.splitlines() if line.startswith("ERROR ")
    )
    assert errors == [
        "ERROR test_main.py::test_a_leaks",
        "ERROR test_main.py::test_e_bg_tasks_in_use_clock_then_leak",
        "ERROR test_module_scope.py::test_m1_first_in_module",
    ], out
    assert "FAILED" not in out, out
    assert "테스트가 바꾼 시계를 되돌리지 않았다" in out, out
