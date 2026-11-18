#!/usr/bin/env python3
"""Claude Code PreToolUse hook: deny piping pytest output into another command (#2537).

A pipe swallows pytest's exit code, so a run that collected 0 tests can be
reported as passing. Redirect output to a file and judge by exit code and the
``N passed`` line instead.

The rule is a plain string rule. It does not interpret shell syntax (quotes,
comments, heredocs, reserved words, variable expansion):

1. No ``pytest``/``py.test`` in the command -> allow.
2. Backslash-newline becomes a space.
3. Split into fragments on ``&&``, ``||``, ``;`` and newline.
4. Deny if, inside a fragment, a pytest word is followed by a single pipe
   (``|`` or ``|&``; ``||`` and ``>|`` are not pipes).

Standard library only. Any error ends with exit 0 (fail-open) so a hook bug
never blocks every Bash call. Denial is an ASCII JSON object on stdout plus
exit 0.
"""

from __future__ import annotations

import json
import re
import sys

FRAGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n")
PYTEST_WORD_RE = re.compile(r"(?<![\w.-])(?:pytest|py\.test)(?![\w.-])")
SINGLE_PIPE_RE = re.compile(r"(?<![|>])\|(?!\|)")

DENY_REASON = (
    "pytest 출력을 파이프로 넘기면 파이프가 pytest의 종료 코드를 삼킨다 "
    "(0건 실행이 통과로 보일 수 있다). "
    "출력을 파일로 리다이렉트하고(`pytest … > out.txt 2>&1; echo exit=$?`) "
    "종료 코드와 `N passed` 문자열(예: `grep -E 'passed|failed' out.txt`)로 판정하라. "
    "명령이 아니라 텍스트(이슈 본문, heredoc)에 이 형태가 들어 있어 걸린 것이면 "
    "그 텍스트를 파일로 써서 넘겨라. "
    "검색 패턴으로 쓴 것이면 패턴을 `py[t]est`로 쓰거나 파이프 대신 "
    "`-m N`·`-c` 옵션을 써라."
)


def find_piped_pytest(command: str) -> str | None:
    """Return the offending fragment if pytest output is piped, else None."""
    if "pytest" not in command and "py.test" not in command:
        return None
    normalized = command.replace("\\\n", " ")
    for fragment in FRAGMENT_SPLIT_RE.split(normalized):
        match = PYTEST_WORD_RE.search(fragment)
        if match is None:
            continue
        if SINGLE_PIPE_RE.search(fragment, match.end()):
            return fragment
    return None


def main() -> int:
    try:
        # Read bytes so the locale encoding never affects decoding (JSON is UTF-8).
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
            return 0
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        command = tool_input.get("command")
        if not isinstance(command, str):
            return 0
        if find_piped_pytest(command) is None:
            return 0
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": DENY_REASON,
            }
        }
        sys.stdout.write(json.dumps(output) + "\n")
    except Exception:  # noqa: BLE001 - fail-open by design
        return 0
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - fail-open by design
        pass
    sys.exit(0)
