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
        "PYTHONPATH=$PWD/src .venv/bin/pytest tests/unit -q 2>&1 | tail -5",
        "PYTHONPATH=src:tests pytest -q | tail",
        "python -m pytest -q | grep passed",
        "uv run pytest | head",
        "cd x && pytest -q |& tee out.txt",
        "pytest -q|&tee o",
        "timeout 600 pytest | cat",
        "ls\npytest -q | tail",
        "$VENV/bin/pytest | tail",
        "${VENV}/bin/pytest | tail",
        "/Users/홍길동/.venv/bin/pytest | tail",
        "pytest -q tests/unit \\\n  | tail -5",
        'git commit -m "#2537 fix" && pytest -q | tail -5',
        "for i in 1 2 3; do pytest -q tests/x.py | tail -3; done",
        "if pytest -q | tail; then echo; fi",
        "! pytest -q | tail",
        "(pytest -q 2>&1 | tail -5)",
        'bash -c "pytest -q | tail"',
    ],
)
def test_denies_piped_pytest(command: str) -> None:
    assert hook.find_piped_pytest(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q > out.txt 2>&1",
        "pytest -q; echo exit=$?",
        "cat out.txt | grep passed",
        "ls | grep pytest",
        "pytest -q && echo ok | cat",
        "pytest -q > out.txt 2>&1\ngrep passed out.txt | tail",
        "pytest -q > out.txt 2>&1; grep passed out.txt | tail",
        "false || pytest -q",
        "pytest -q 2>&1 > o",
        "pytest -q >| o",
        "pip install pytest-xdist | tail",
        "cat pytest.ini | head",
        "ls tests/unit/test_pytest_x.py | head",
        "pip list | grep pytest",
        "grep -rn 'py[t]est' . | head",
        "echo ok",
    ],
)
def test_allows_other_commands(command: str) -> None:
    assert hook.find_piped_pytest(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "grep pytest notes.txt | head",
        'echo "pytest | tail"',
        "uv pip install pytest | tail",
        "pytest --version | cat",
        "rg pytest -l | wc -l",
        'grep -rn "pytest" . | head',
        "cat > x.md <<'EOF'\n# notes\npytest -q | tail -5\nEOF",
    ],
)
def test_accepted_false_positives_are_denied(command: str) -> None:
    assert hook.find_piped_pytest(command) is not None


def _run_main(monkeypatch: pytest.MonkeyPatch, stdin_text: str) -> tuple[int, str]:
    stdin = io.TextIOWrapper(io.BytesIO(stdin_text.encode("utf-8")), encoding="ascii")
    monkeypatch.setattr(sys, "stdin", stdin)
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
    assert out.isascii()
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    reason = decision["permissionDecisionReason"]
    assert "passed" in reason
    assert "> out.txt 2>&1" in reason


def test_main_decodes_utf8_regardless_of_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = "/Users/홍길동/.venv/bin/pytest | tail"
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    rc, out = _run_main(monkeypatch, json.dumps(payload, ensure_ascii=False))
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


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


def test_main_ignores_non_string_command(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": ["pytest", "|", "tail"]}}
    rc, out = _run_main(monkeypatch, json.dumps(payload))
    assert rc == 0
    assert out == ""
