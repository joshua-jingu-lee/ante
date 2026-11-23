"""e2e 시나리오의 fixture, 테스트별 제한 시간, 세션 판정, 실행 기록."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

from tests.e2e import harness

_RESULTS: list[tuple[str, str]] = []
_PHASES = pytest.StashKey[dict[str, str]]()


@pytest.fixture
def daemon(request: pytest.FixtureRequest) -> Iterator[harness.DaemonHarness]:
    """임시 루트 하나. 정리는 테스트의 성패와 상관없이 돈다.

    ``ANTE_E2E_RECORD_DIR``이 있으면 정리 뒤에 실행 기록을 쓴다.
    """
    started = time.monotonic()
    env = harness.DaemonHarness.create()
    try:
        yield env
    finally:
        try:
            env.cleanup()
        finally:
            harness.save_record(
                env,
                request.node.nodeid,
                _scenario_outcome(request.node.stash.get(_PHASES, {})),
                time.monotonic() - started,
            )


def _scenario_outcome(phases: dict[str, str]) -> str:
    """설치·본문 단계의 리포트로 시나리오의 결과를 정한다(정리 단계는 아직 없다)."""
    if "failed" in phases.values():
        return "failed"
    if phases.get("call") == "passed":
        return "passed"
    if "skipped" in phases.values():
        return "skipped"
    return "unknown"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Iterator[None]:
    with harness.time_limit(harness.TEST_TIME_LIMIT_SECONDS):
        return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[Any]
) -> Iterator[None]:
    if call.excinfo is not None:
        env = getattr(item, "funcargs", {}).get("daemon")
        if isinstance(env, harness.DaemonHarness):
            item.add_report_section(call.when, "e2e diagnostics", env.diagnostics())
    report = yield
    item.stash.setdefault(_PHASES, {})[call.when] = report.outcome
    return report


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
