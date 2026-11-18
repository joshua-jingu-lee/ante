"""PreToolUse hook that denies piping pytest output (#2537)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_hook() -> ModuleType:
    hook_path = REPO_ROOT / ".claude" / "hooks" / "block_pytest_pipe.py"
    spec = importlib.util.spec_from_file_location("block_pytest_pipe", hook_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load hook: {hook_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load_hook()


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q | tail -5",
        "PYTHONPATH=src .venv/bin/pytest tests/unit -n auto 2>&1 | tail -3",
        "python -m pytest -q | grep passed",
        "uv run pytest | head",
        "cd x && pytest -q |& tee out.txt",
        "pytest -q|&tee o",
        "timeout 600 pytest | cat",
        "pytest -q a#b | tail",
        "ls\npytest -q | tail",
    ],
)
def test_denies_piped_pytest(command: str) -> None:
    assert hook.find_piped_pytest(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q > out.txt 2>&1",
        "pytest -q; echo exit=$?",
        "grep pytest notes.txt | head",
        "cat out.txt | grep passed",
        'echo "pytest | tail"',
        "ls | grep pytest",
        "pytest -q && echo ok | cat",
        "pytest -q > out.txt 2>&1\ngrep passed out.txt | tail",
        "pytest -q #c\nls | cat",
        "echo a#b | cat",
        "pytest -q # | tail",
        "pytest -q 2>&1 > o",
        "pytest -q >| o",
        "false || pytest -q",
        "a;;b",
        "uv pip install pytest | tail",
        "poetry add --dev pytest | tail",
        'echo "unclosed',
    ],
)
def test_allows_other_commands(command: str) -> None:
    assert hook.find_piped_pytest(command) is None


def _run_main(monkeypatch: pytest.MonkeyPatch, stdin_text: str) -> tuple[int, str]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = hook.main()
    return rc, out.getvalue()


def test_main_ignores_non_bash_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"tool_name": "Edit", "tool_input": {"command": "pytest -q | tail -5"}}
    rc, out = _run_main(monkeypatch, json.dumps(payload))
    assert rc == 0
    assert out == ""


def test_main_denies_piped_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": "pytest -q | tail -5"}}
    rc, out = _run_main(monkeypatch, json.dumps(payload))
    assert rc == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert "passed" in reason
    assert "> out.txt 2>&1" in reason


def test_main_allows_redirected_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q > out.txt 2>&1"},
    }
    rc, out = _run_main(monkeypatch, json.dumps(payload))
    assert rc == 0
    assert out == ""


def test_main_fails_open_on_broken_json(monkeypatch: pytest.MonkeyPatch) -> None:
    rc, out = _run_main(monkeypatch, "{not json")
    assert rc == 0
    assert out == ""
