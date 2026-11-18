#!/usr/bin/env python3
"""Claude Code PreToolUse hook: deny piping pytest output into another command (#2537).

A pipe swallows pytest's exit code, so a run that collected 0 tests can be
reported as passing. Redirect output to a file and judge by exit code and the
``N passed`` line instead.

Standard library only. Any error ends with exit 0 (fail-open) so a hook bug
never blocks every Bash call. Denial is a JSON object on stdout plus exit 0.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys

PIPELINE_SEPARATORS = frozenset({";", ";;", ";&", "&&", "||", "&", "\n"})
PIPE_OPERATORS = frozenset({"|", "|&"})
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PYTHON_RE = re.compile(r"^python(3(\.\d+)?)?$")
PYTEST_NAMES = frozenset({"pytest", "py.test"})
SIMPLE_WRAPPERS = frozenset({"time", "nohup", "command", "exec"})

DENY_REASON = (
    "pytest 출력을 파이프로 넘기면 파이프가 pytest의 종료 코드를 삼킨다 "
    "(0건 실행이 통과로 보일 수 있다). 출력을 파일로 리다이렉트하라: "
    "`pytest … > out.txt 2>&1; echo exit=$?` 그런 뒤 종료 코드와 "
    "`N passed` 문자열(예: `grep -E 'passed|failed' out.txt`)로 판정하라."
)


def _tokenize(command: str) -> list[str]:
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace = " \t\r"
    lex.commenters = ""
    lex.wordchars += "#"
    tokens: list[str] = []
    in_comment = False
    for token in lex:
        if in_comment:
            if token == "\n":
                in_comment = False
                tokens.append(token)
            continue
        if token.startswith("#"):
            in_comment = True
            continue
        tokens.append(token)
    return tokens


def _command_index(segment: list[str]) -> int | None:
    """Return the index of the real command token in a pipeline segment."""
    i = 0
    n = len(segment)
    while i < n and ASSIGNMENT_RE.match(segment[i]):
        i += 1
    while i < n:
        name = segment[i]
        if name in SIMPLE_WRAPPERS:
            i += 1
        elif name == "env":
            i += 1
            while i < n and (
                ASSIGNMENT_RE.match(segment[i]) or segment[i].startswith("-")
            ):
                i += 1
        elif name == "timeout":
            i += 1
            while i < n and segment[i].startswith("-"):
                i += 1
            i += 1  # duration
        elif name in ("uv", "poetry"):
            if i + 1 < n and segment[i + 1] == "run":
                i += 2
                while i < n and segment[i].startswith("-"):
                    i += 1
            else:
                return i
        else:
            return i
    return None


def _is_pytest(segment: list[str]) -> bool:
    idx = _command_index(segment)
    if idx is None:
        return False
    base = os.path.basename(segment[idx])
    if base in PYTEST_NAMES:
        return True
    if PYTHON_RE.match(base):
        rest = segment[idx + 1 :]
        return any(
            rest[j] == "-m" and rest[j + 1] == "pytest" for j in range(len(rest) - 1)
        )
    return False


def find_piped_pytest(command: str) -> str | None:
    """Return a deny reason if pytest output is piped to another command."""
    try:
        tokens = _tokenize(command)
    except ValueError:
        return None

    pipelines: list[list[str]] = [[]]
    for token in tokens:
        if token in PIPELINE_SEPARATORS:
            pipelines.append([])
        else:
            pipelines[-1].append(token)

    for pipeline in pipelines:
        segments: list[list[str]] = [[]]
        for token in pipeline:
            if token in PIPE_OPERATORS:
                segments.append([])
            else:
                segments[-1].append(token)
        for segment in segments[:-1]:
            if _is_pytest(segment):
                return DENY_REASON
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            return 0
        reason = find_piped_pytest(command)
        if reason is None:
            return 0
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - fail-open by design
        return 0
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - fail-open by design
        pass
    sys.exit(0)
