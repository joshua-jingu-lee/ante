"""e2e 시나리오의 fixture, 테스트별 제한 시간, 세션 판정."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.e2e import harness

_RESULTS: list[tuple[str, str]] = []


@pytest.fixture
def daemon() -> Iterator[harness.DaemonHarness]:
    """임시 루트 하나. 정리는 테스트의 성패와 상관없이 돈다."""
    env = harness.DaemonHarness.create()
    try:
        yield env
    finally:
        env.cleanup()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    with harness.time_limit(harness.TEST_TIME_LIMIT_SECONDS):
        return (yield)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> None:
    if call.excinfo is None:
        return
    env = getattr(item, "funcargs", {}).get("daemon")
    if isinstance(env, harness.DaemonHarness):
        item.add_report_section(call.when, "e2e diagnostics", env.diagnostics())


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    outcome = harness.report_outcome(
        report.when or "",
        passed=report.passed,
        skipped=report.skipped,
        wasxfail=hasattr(report, "wasxfail"),
    )
    _RESULTS.append((report.nodeid, outcome))


def pytest_sessionfinish(session: pytest.Session) -> None:
    if hasattr(session.config, "workerinput"):
        return
    reason = harness.session_failure_reason(_RESULTS)
    if reason is None:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write("\n")
        reporter.write_line(f"e2e 세션 판정: {reason}", red=True)
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
