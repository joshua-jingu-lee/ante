"""post-merge.yml이 완료 조건 파서를 불러 쓰는 배선을 잠근다 (#2524).

파서의 행동은 `.github/scripts/mark-done-criteria.test.js`가 `node --test`로 본다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "post-merge.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
NODE_TEST_CMD = "node --test .github/scripts/*.test.js"
SCRIPTS_DIR = ".github/scripts"
REQUIRE_PREFIX = "${process.env.GITHUB_WORKSPACE}/"
REQUIRE_CALL = re.compile(r"require\(\s*`([^`]*)`\s*,?\s*\)")


def _steps() -> list[dict[str, Any]]:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return list(data["jobs"]["post-merge"]["steps"])


def _index_of(steps: list[dict[str, Any]], action: str) -> int:
    matches = [
        i
        for i, step in enumerate(steps)
        if str(step.get("uses", "")).startswith(action)
    ]
    assert len(matches) == 1, f"{action} 단계 {len(matches)}개(기대 1)"
    return matches[0]


def _script() -> str:
    steps = _steps()
    return str(steps[_index_of(steps, "actions/github-script@")]["with"]["script"])


def _checkout_with() -> dict[str, Any]:
    steps = _steps()
    return dict(steps[_index_of(steps, "actions/checkout@")].get("with") or {})


def test_require_paths_are_workspace_absolute_and_exist():
    script = _script()
    targets = REQUIRE_CALL.findall(script)
    assert targets, "script가 파일을 불러오지 않는다"
    assert len(targets) == script.count("require("), (
        "템플릿 리터럴이 아닌 require가 있다"
    )
    for target in targets:
        assert target.startswith(REQUIRE_PREFIX), target
        suffix = target[len(REQUIRE_PREFIX) :]
        assert suffix.startswith(f"{SCRIPTS_DIR}/"), suffix
        assert (REPO_ROOT / suffix).is_file(), suffix


def test_checkout_runs_before_github_script():
    steps = _steps()
    assert _index_of(steps, "actions/checkout@") < _index_of(
        steps, "actions/github-script@"
    )


def test_sparse_checkout_includes_scripts_dir():
    entries = str(_checkout_with().get("sparse-checkout", "")).split()
    assert SCRIPTS_DIR in entries, entries


def test_checkout_does_not_persist_credentials():
    assert _checkout_with().get("persist-credentials") is False


def test_checkout_ref_is_the_running_workflow_commit():
    assert _checkout_with().get("ref") == "${{ github.sha }}"


def test_ci_node_test_step_fails_on_unmatched_glob():
    data = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step
        for step in data["jobs"]["lint"]["steps"]
        if NODE_TEST_CMD in str(step.get("run", ""))
    ]
    assert len(steps) == 1, f"lint 잡의 node --test 단계 {len(steps)}개(기대 1)"
    assert steps[0].get("shell") == "bash"
    commands = [line.strip() for line in str(steps[0]["run"]).splitlines()]
    assert "shopt -s failglob" in commands
    assert commands.index("shopt -s failglob") < commands.index(NODE_TEST_CMD)
