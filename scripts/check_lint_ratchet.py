#!/usr/bin/env python3
"""Fail when ruff (BLE001, ASYNC, S608, C901) or ``mypy --strict`` counts differ.

Counts are per (file, rule or error code) over ``src/``, measured with
``python -m ruff`` and ``python -m mypy`` of this interpreter in ``--root``.

- ruff: the JSON output of ``RUFF_ARGS``. A non-zero exit, output that is not
  a JSON list, an item without a string ``filename``, a ``filename`` outside
  the root once both are resolved, or a ``code`` not matching ``CODE_RE`` is
  exit 2.
- mypy: stdout of ``MYPY_ARGS``; stderr is passed through, not parsed. Every
  non-empty line must match ``MYPY_LINE_RE``. Only ``error`` lines count, and
  each must end with ``  [<code>]``. Exit status 0 with errors, 1 without, or
  any other status is exit 2.

Baseline ``scripts/lint_baseline.json`` has exactly the keys ``tools``
(``{"ruff": version, "mypy": version}``), ``ruff`` and ``mypy`` (file -> code
-> positive count, no empty inner object). It must equal the measurement of
that commit's ``src/`` in CI. There is no flag that writes it.

Exit 0: installed tool versions equal ``tools`` and both counts equal the
baseline. Exit 1: a count differs (more, fewer or moved). Exit 2: anything
else, including a tool version that differs from ``tools``.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

BASELINE_PATH = Path("scripts") / "lint_baseline.json"
BASELINE_KEYS = frozenset({"tools", "ruff", "mypy"})
TOOLS = ("ruff", "mypy")

RUFF_ARGS = (
    "check",
    "src/",
    "--select",
    "BLE001,ASYNC,S608,C901",
    "--config",
    "lint.mccabe.max-complexity = 10",
    "--output-format",
    "json",
    "--no-fix",
    "--no-cache",
    "--exit-zero",
    "--ignore-noqa",
)
MYPY_ARGS = (
    "--strict",
    "--platform",
    "linux",
    "--cache-dir",
    ".mypy_cache/strict",
    "--no-error-summary",
    "--no-pretty",
    "--no-color-output",
    "src/",
)

CODE_RE = re.compile(r"^[A-Z]+[0-9]+$")
MYPY_LINE_RE = re.compile(
    r"^(?P<path>[^:]+):\d+(?::\d+)?: (?P<sev>error|note|warning): (?P<msg>.*)$"
)
MYPY_CODE_RE = re.compile(r"  \[(?P<code>[a-z0-9-]+)\]$")
REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

INSTALL_HINT = (
    'uv pip install -e ".[dev]" 또는 python -m pip install -e ".[dev]"로 '
    "고정 버전을 설치한다.\n"
    "기준선은 그 커밋의 src/를 CI 환경에서 잰 값과 같아야 한다.\n"
    "버전을 올리는 PR이면 같은 PR에서 기준선을 다시 잰다."
)
RUFF_ALTERNATIVES = (
    ("BLE001", "예외를 좁히거나 다시 던진다. 판정 값을 기본값으로 채우지 않는다."),
    ("ASYNC", "asyncio.to_thread나 비동기 API를 쓴다."),
    ("S608", "자리표시자를 쓴다."),
    ("C901", "함수를 나눈다."),
)
MYPY_ALTERNATIVE = "타입을 채우거나 좁힌다."
LOWER_HINT = "기준선을 낮춘다(0이면 키를 지운다)."
MOVE_HINT = "파일을 옮기거나 새로 만들었다면 기준선을 옮긴다."

Counts = dict[str, dict[str, int]]
Runner = Callable[[str, Sequence[str], Path], subprocess.CompletedProcess[str]]


class CheckError(RuntimeError):
    """Raised when the measurement or the baseline cannot be trusted."""


def run_tool(
    module: str, args: Sequence[str], root: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _add(counts: Counts, path: str, code: str) -> None:
    per_file = counts.setdefault(path, {})
    per_file[code] = per_file.get(code, 0) + 1


def parse_ruff_json(text: str, root: Path) -> Counts:
    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"ruff output is not JSON: {exc}") from exc
    if not isinstance(items, list):
        raise CheckError("ruff output is not a JSON list")
    base = root.resolve()
    counts: Counts = {}
    for item in items:
        if not isinstance(item, dict):
            raise CheckError(f"ruff item is not an object: {item!r}")
        filename = item.get("filename")
        code = item.get("code")
        if not isinstance(filename, str):
            raise CheckError(f"ruff item has no filename: {item!r}")
        if not isinstance(code, str) or not CODE_RE.match(code):
            raise CheckError(f"ruff item has no rule code: {filename}: {code!r}")
        try:
            rel = (base / filename).resolve().relative_to(base)
        except ValueError as exc:
            raise CheckError(
                f"ruff reported a file outside {base}: {filename}"
            ) from exc
        _add(counts, rel.as_posix(), code)
    return counts


def parse_mypy(text: str, returncode: int) -> Counts:
    if returncode not in (0, 1):
        raise CheckError(f"mypy exited with {returncode}")
    counts: Counts = {}
    errors = 0
    for line in text.splitlines():
        if not line:
            continue
        match = MYPY_LINE_RE.match(line)
        if match is None:
            raise CheckError(f"unexpected mypy output line: {line!r}")
        if match["sev"] != "error":
            continue
        code = MYPY_CODE_RE.search(match["msg"])
        if code is None:
            raise CheckError(f"mypy error without an error code: {line!r}")
        _add(counts, match["path"], code["code"])
        errors += 1
    if returncode == 0 and errors:
        raise CheckError(f"mypy exited with 0 but reported {errors} errors")
    if returncode == 1 and not errors:
        raise CheckError("mypy exited with 1 but reported no errors")
    return counts


def measure_ruff(root: Path, runner: Runner) -> Counts:
    proc = runner("ruff", RUFF_ARGS, root)
    if proc.returncode != 0:
        raise CheckError(f"ruff exited with {proc.returncode}: {proc.stderr.strip()}")
    return parse_ruff_json(proc.stdout, root)


def measure_mypy(root: Path, runner: Runner) -> Counts:
    proc = runner("mypy", MYPY_ARGS, root)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    return parse_mypy(proc.stdout, proc.returncode)


def tool_version(module: str, root: Path, runner: Runner) -> str:
    proc = runner(module, ("--version",), root)
    words = proc.stdout.split()
    if proc.returncode != 0 or len(words) < 2:
        raise CheckError(
            f"cannot read {module} version (exit {proc.returncode}): "
            f"{(proc.stdout + proc.stderr).strip()!r}\n{INSTALL_HINT}"
        )
    return words[1]


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _read_counts(data: dict[str, object], key: str) -> Counts:
    value = data[key]
    if not isinstance(value, dict):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be an object")
    counts: Counts = {}
    for path, codes in value.items():
        if not isinstance(codes, dict) or not codes:
            raise CheckError(
                f"{BASELINE_PATH}: {key}[{path!r}] must be a non-empty object"
            )
        for code, count in codes.items():
            if not _is_positive_int(count):
                raise CheckError(
                    f"{BASELINE_PATH}: {key}[{path!r}][{code!r}] must be a "
                    f"positive integer, got {count!r}"
                )
        counts[path] = dict(codes)
    return counts


def _read_tools(data: dict[str, object]) -> dict[str, str]:
    tools = data["tools"]
    if (
        not isinstance(tools, dict)
        or set(tools) != set(TOOLS)
        or not all(isinstance(tools[name], str) for name in TOOLS)
    ):
        raise CheckError(
            f"{BASELINE_PATH}: 'tools' must map exactly {list(TOOLS)} to strings, "
            f"got {tools!r}"
        )
    return dict(tools)


def parse_baseline(text: str) -> tuple[dict[str, str], Counts, Counts]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"{BASELINE_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"{BASELINE_PATH} must hold a JSON object")
    keys = set(data)
    if keys != BASELINE_KEYS:
        raise CheckError(
            f"{BASELINE_PATH} must have exactly the keys {sorted(BASELINE_KEYS)} "
            f"(missing {sorted(BASELINE_KEYS - keys)}, "
            f"extra {sorted(keys - BASELINE_KEYS)})"
        )
    return _read_tools(data), _read_counts(data, "ruff"), _read_counts(data, "mypy")


def read_baseline(root: Path) -> tuple[dict[str, str], Counts, Counts]:
    try:
        text = (root / BASELINE_PATH).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    return parse_baseline(text)


def _alternative(kind: str, code: str) -> str:
    if kind == "mypy":
        return MYPY_ALTERNATIVE
    return next(text for prefix, text in RUFF_ALTERNATIVES if code.startswith(prefix))


def _diff(kind: str, actual: Counts, baseline: Counts) -> list[str]:
    lines: list[str] = []
    for path in sorted(set(actual) | set(baseline)):
        got_codes = actual.get(path, {})
        want_codes = baseline.get(path, {})
        for code in sorted(set(got_codes) | set(want_codes)):
            got = got_codes.get(code, 0)
            want = want_codes.get(code, 0)
            if got == want:
                continue
            lines.append(
                f"{kind}\t{path}\t{code}: actual {got}, baseline {want} "
                f"({got - want:+d})"
            )
            if got > want:
                lines.append(f"  대안: {_alternative(kind, code)}")
                if path not in baseline:
                    lines.append(f"  {MOVE_HINT}")
            else:
                lines.append(f"  {LOWER_HINT}")
    return lines


def dependency_versions(root: Path) -> list[str]:
    try:
        with (root / "pyproject.toml").open("rb") as handle:
            requirements = tomllib.load(handle)["project"]["dependencies"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        return [f"  cannot read [project].dependencies: {type(exc).__name__}: {exc}"]
    lines: list[str] = []
    for requirement in requirements:
        match = REQUIREMENT_NAME_RE.match(str(requirement))
        if match is None:
            continue
        name = match.group(1)
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = "not installed"
        lines.append(f"  {name}=={version}")
    return lines


def judge(
    root: Path, actual: tuple[Counts, Counts], baseline: tuple[Counts, Counts]
) -> tuple[int, str]:
    ruff_lines = _diff("ruff", actual[0], baseline[0])
    mypy_lines = _diff("mypy", actual[1], baseline[1])
    if not ruff_lines and not mypy_lines:
        ruff_total = sum(sum(codes.values()) for codes in actual[0].values())
        mypy_total = sum(sum(codes.values()) for codes in actual[1].values())
        return EXIT_OK, (
            f"lint ratchet ok: {ruff_total} ruff findings, {mypy_total} mypy "
            f"--strict errors (baseline {BASELINE_PATH})"
        )
    parts = [f"lint ratchet failed against {BASELINE_PATH}:", *ruff_lines, *mypy_lines]
    if mypy_lines:
        parts.append("installed [project].dependencies:")
        parts.extend(dependency_versions(root))
    return EXIT_MISMATCH, "\n".join(parts)


def run(root: Path, runner: Runner = run_tool) -> tuple[int, str]:
    try:
        tools, ruff_baseline, mypy_baseline = read_baseline(root)
        for module in TOOLS:
            installed = tool_version(module, root, runner)
            if installed != tools[module]:
                raise CheckError(
                    f"{module} {installed} is installed, baseline needs "
                    f"{tools[module]}\n{INSTALL_HINT}"
                )
        actual = (measure_ruff(root, runner), measure_mypy(root, runner))
    except CheckError as exc:
        return EXIT_ERROR, str(exc)
    return judge(root, actual, (ruff_baseline, mypy_baseline))


def main(argv: Sequence[str] | None = None, runner: Runner = run_tool) -> int:
    parser = argparse.ArgumentParser(
        description="Check ruff and mypy --strict counts of src/ against a baseline."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    try:
        code, message = run(args.root, runner)
    except Exception as exc:
        code = EXIT_ERROR
        message = f"lint ratchet error: {type(exc).__name__}: {exc}"
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
