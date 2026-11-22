"""tests/conftest.py의 시계 누수 가드 (#2768).

가드는 autouse 픽스처라 하위 pytest 프로세스에서 그 conftest를 플러그인으로
싣고 결과를 본다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

_INNER = """
from datetime import UTC, datetime

import pytest

from ante.core import clock


class Fixed:
    def now(self, tz):
        return datetime(2026, 1, 1, tzinfo=UTC).astimezone(tz)

    def monotonic(self):
        return 0.0


@pytest.fixture
def fixed_clock():
    with clock.use_clock(Fixed()) as c:
        yield c


def test_a_leaks():
    clock.set_clock(Fixed())


def test_b_sees_system_clock_again():
    assert type(clock.current_clock()) is clock.SystemClock


def test_c_use_clock_is_fine():
    with clock.use_clock(Fixed()):
        assert clock.now(UTC).year == 2026


def test_d_fixture_restoring_in_teardown_is_fine(fixed_clock):
    assert clock.current_clock() is fixed_clock
"""


def test_unrestored_set_clock_fails_that_test_only(tmp_path: Path) -> None:
    (tmp_path / "test_inner.py").write_text(_INNER, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO / "tests"), str(_REPO / "src"), env.get("PYTHONPATH", "")]
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
            "-o",
            "asyncio_mode=auto",
            "--rootdir",
            str(tmp_path),
            "-q",
            "-rA",
            str(tmp_path / "test_inner.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "4 passed, 1 error" in out, out
    assert "ERROR test_inner.py::test_a_leaks" in out, out
    assert "테스트가 바꾼 시계를 되돌리지 않았다" in out, out
    for name in (
        "test_b_sees_system_clock_again",
        "test_c_use_clock_is_fine",
        "test_d_fixture_restoring_in_teardown_is_fine",
    ):
        assert f"PASSED test_inner.py::{name}" in out, out
