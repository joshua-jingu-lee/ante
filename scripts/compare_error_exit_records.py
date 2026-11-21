#!/usr/bin/env python3
"""Build the preservation table of #2664 from recorder output.

The recorder is ``tests/preservation_recorder.py``. Run with ``src`` on
``PYTHONPATH``: the text-mode test reads the entry hook and the error registry.

``compare BEFORE BEFORE_AGAIN AFTER [--intended NODEID#N ...]``

Rows are matched on ``(nodeid, n)``. Rows that differ between the two before
records, or exist in only one of them, are ``비결정`` and leave the
comparison. Each other before row is:

- ``같음``: exit code, stdout, stderr and raised type are byte-identical.
- ``의도한 동작 변경``: the row is named with ``--intended``.
- ``text 형식``: a text-mode call whose exit code, raised type and stdout are
  the same and whose stderr differs in exactly one line, ``Error: <m>`` before
  and ``Error: <C>: <m>`` after, where ``<C>`` is a registry code. For a call
  without a separate stderr the same test applies to stdout.
- ``다름``: any other difference, and a before row missing after.

Rows only in AFTER are counted and listed, not classified.

``cover DATA RECORDS FILE...``

Run on the before tree. For each error call and exit in FILE (the
definitions of ``scripts/check_entry_ratchet.py``), report whether a recorded
call in JSON mode and one in text mode ran that line. ``DATA`` is a coverage
data file written with the recorder active.

Exit 0: no ``다름`` row (compare) or every line ran in both modes (cover).
Exit 1: a ``다름`` row, or a line not run in a mode.
Exit 2: unreadable or empty input, or any other failure.
"""

from __future__ import annotations

import argparse
import ast
import base64
import importlib.util
import json
import shlex
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_DIFFERENT = 1
EXIT_ERROR = 2

SAME = "같음"
TEXT_FORMAT = "text 형식"
NONDETERMINISTIC = "비결정"
INTENDED = "의도한 동작 변경"
DIFFERENT = "다름"
CATEGORIES = (SAME, TEXT_FORMAT, INTENDED, DIFFERENT)

ERROR_PREFIX = "Error: "
RATCHET_PATH = Path(__file__).resolve().parent / "check_entry_ratchet.py"

Key = tuple[str, int]


class InputError(RuntimeError):
    """Raised when an input cannot be trusted."""


@dataclass(frozen=True)
class Row:
    nodeid: str
    n: int
    args: list[str]
    exit: int | None
    stdout: bytes | None
    stderr: bytes | None
    raised: str | None

    @property
    def key(self) -> Key:
        return (self.nodeid, self.n)

    @property
    def outcome(self) -> tuple[object, ...]:
        return (self.exit, self.stdout, self.stderr, self.raised)


def _decode(value: Any) -> bytes | None:
    if value is None:
        return None
    return base64.b64decode(value, validate=True)


def load_rows(path: Path) -> dict[Key, Row]:
    rows: dict[Key, Row] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InputError(f"cannot read {path}: {exc}") from exc
    for number, line in enumerate(lines, 1):
        try:
            data = json.loads(line)
            args = data["args"]
            row = Row(
                nodeid=data["nodeid"],
                n=data["n"],
                args=shlex.split(args) if isinstance(args, str) else list(args),
                exit=data["exit"],
                stdout=_decode(data["stdout"]),
                stderr=_decode(data["stderr"]),
                raised=data["raised"],
            )
        except Exception as exc:
            raise InputError(f"{path}:{number}: bad row: {exc}") from exc
        if row.key in rows:
            raise InputError(f"{path}:{number}: duplicate row {row.key}")
        rows[row.key] = row
    if not rows:
        raise InputError(f"{path}: no rows")
    return rows


def registry_codes() -> frozenset[str]:
    from ante.contracts import error_registry
    from ante.contracts.errors import ErrorSpec

    codes = {spec.code for spec in error_registry.EXCEPTION_TO_SPEC.values()}
    codes |= {v.code for v in vars(error_registry).values() if isinstance(v, ErrorSpec)}
    return frozenset(codes)


def is_text_mode(args: Sequence[str]) -> bool:
    from ante.cli.middleware import AuthenticatedGroup

    return AuthenticatedGroup._sniff_output_format(list(args)) != "json"


def one_line_code_prefix(before: bytes, after: bytes, codes: frozenset[str]) -> bool:
    old = before.decode("utf-8", "surrogateescape").splitlines(keepends=True)
    new = after.decode("utf-8", "surrogateescape").splitlines(keepends=True)
    if len(old) != len(new):
        return False
    changed = [i for i, (o, n) in enumerate(zip(old, new, strict=True)) if o != n]
    if len(changed) != 1:
        return False
    o, n = old[changed[0]], new[changed[0]]
    if not (o.startswith(ERROR_PREFIX) and n.startswith(ERROR_PREFIX)):
        return False
    code, sep, rest = n[len(ERROR_PREFIX) :].partition(": ")
    return bool(sep) and code in codes and rest == o[len(ERROR_PREFIX) :]


def is_text_format_change(before: Row, after: Row, codes: frozenset[str]) -> bool:
    if not is_text_mode(before.args):
        return False
    if (before.exit, before.raised) != (after.exit, after.raised):
        return False
    if before.stderr is None and after.stderr is None:
        if before.stdout is None or after.stdout is None:
            return False
        return one_line_code_prefix(before.stdout, after.stdout, codes)
    if before.stderr is None or after.stderr is None:
        return False
    return before.stdout == after.stdout and one_line_code_prefix(
        before.stderr, after.stderr, codes
    )


def classify(
    before: dict[Key, Row],
    before_again: dict[Key, Row],
    after: dict[Key, Row],
    intended: frozenset[Key],
    codes: frozenset[str],
) -> tuple[dict[Key, str], list[Key], list[Key]]:
    nondeterministic = sorted(
        k
        for k in before.keys() | before_again.keys()
        if k not in before
        or k not in before_again
        or before[k].outcome != before_again[k].outcome
    )
    excluded = set(nondeterministic)
    result: dict[Key, str] = {}
    for key in sorted(before):
        if key in excluded:
            continue
        row = before[key]
        new = after.get(key)
        if new is None:
            result[key] = DIFFERENT
        elif row.outcome == new.outcome:
            result[key] = SAME
        elif key in intended:
            result[key] = INTENDED
        elif is_text_format_change(row, new, codes):
            result[key] = TEXT_FORMAT
        else:
            result[key] = DIFFERENT
    after_only = sorted(after.keys() - before.keys() - excluded)
    return result, nondeterministic, after_only


def _label(key: Key) -> str:
    return f"{key[0]}#{key[1]}"


def _show(value: bytes | None) -> str:
    return "null" if value is None else repr(value.decode("utf-8", "replace"))


def compare_report(
    before: dict[Key, Row],
    after: dict[Key, Row],
    result: dict[Key, str],
    nondeterministic: list[Key],
    after_only: list[Key],
) -> str:
    lines = ["# 분류별 행 수"]
    for category in CATEGORIES:
        lines.append(f"{category}: {sum(v == category for v in result.values())}")
    lines.append(f"{NONDETERMINISTIC}: {len(nondeterministic)}")
    lines.append(f"후에만 있음: {len(after_only)}")
    for title, category in ((DIFFERENT, DIFFERENT), (TEXT_FORMAT, TEXT_FORMAT)):
        keys = [k for k, v in result.items() if v == category]
        lines.append("")
        lines.append(f"# {title} 행 ({len(keys)})")
        for key in keys:
            row = before[key]
            lines.append(f"- {_label(key)} args={row.args}")
            if category == DIFFERENT:
                new = after.get(key)
                lines.append(f"  전: exit={row.exit} raised={row.raised}")
                lines.append(f"      stdout={_show(row.stdout)}")
                lines.append(f"      stderr={_show(row.stderr)}")
                if new is None:
                    lines.append("  후: 없음")
                else:
                    lines.append(f"  후: exit={new.exit} raised={new.raised}")
                    lines.append(f"      stdout={_show(new.stdout)}")
                    lines.append(f"      stderr={_show(new.stderr)}")
    for title, keys in (
        (NONDETERMINISTIC, nondeterministic),
        ("후에만 있음", after_only),
    ):
        lines.append("")
        lines.append(f"# {title} 행 ({len(keys)})")
        lines.extend(f"- {_label(k)}" for k in keys)
    return "\n".join(lines) + "\n"


def _parse_intended(values: Sequence[str]) -> frozenset[Key]:
    keys: set[Key] = set()
    for value in values:
        nodeid, sep, n = value.rpartition("#")
        if not sep or not n.isdigit():
            raise InputError(f"bad --intended value: {value!r} (NODEID#N)")
        keys.add((nodeid, int(n)))
    return frozenset(keys)


def run_compare(args: argparse.Namespace) -> int:
    before = load_rows(Path(args.before))
    before_again = load_rows(Path(args.before_again))
    after = load_rows(Path(args.after))
    intended = _parse_intended(args.intended)
    result, nondeterministic, after_only = classify(
        before, before_again, after, intended, registry_codes()
    )
    sys.stdout.write(
        compare_report(before, after, result, nondeterministic, after_only)
    )
    return EXIT_DIFFERENT if DIFFERENT in result.values() else EXIT_OK


def _load_ratchet() -> Any:
    spec = importlib.util.spec_from_file_location("check_entry_ratchet", RATCHET_PATH)
    if spec is None or spec.loader is None:
        raise InputError(f"cannot load {RATCHET_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def exit_lines(path: Path) -> list[tuple[int, str]]:
    ratchet = _load_ratchet()
    try:
        tree = ast.parse(path.read_bytes(), filename=str(path))
    except Exception as exc:
        raise InputError(f"cannot read or parse {path}: {exc}") from exc
    skip: set[int] = set()
    if path.resolve().as_posix().endswith(ratchet.HOOK_PATH):
        skip = ratchet.hook_nodes(tree)
    sys_names = ratchet.sys_aliases(tree)
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if ratchet.is_error_call(node):
            found.add((node.lineno, "error"))
        elif ratchet.is_exit(node, sys_names):
            found.add((node.lineno, "exit"))
    return sorted(found)


def run_cover(args: argparse.Namespace) -> int:
    import coverage

    records = load_rows(Path(args.records))
    data_path = Path(args.data)
    if not data_path.is_file():
        raise InputError(f"no coverage data: {data_path}")
    data = coverage.CoverageData(basename=str(data_path))
    data.read()
    lines = ["# 덮개 (줄, 모드)"]
    missing = 0
    total = 0
    hits = {"json": 0, "text": 0}
    for name in args.files:
        path = Path(name)
        targets = exit_lines(path)
        if not targets:
            raise InputError(f"{path}: no error call or exit")
        contexts = data.contexts_by_lineno(str(path.resolve()))
        for lineno, kind in targets:
            total += 1
            modes: set[str] = set()
            for context in contexts.get(lineno, []):
                nodeid, _, n = context.rpartition("#")
                row = records.get((nodeid, int(n))) if n.isdigit() else None
                if row is not None:
                    modes.add("text" if is_text_mode(row.args) else "json")
            for mode in hits:
                hits[mode] += mode in modes
            gaps = sorted({"json", "text"} - modes)
            missing += bool(gaps)
            state = "ok" if not gaps else "없음: " + ", ".join(gaps)
            lines.append(f"{name}:{lineno} {kind} {state}")
    lines.append("")
    lines.append(f"옮기는 줄: {total}")
    lines.append(f"기록이 지난 줄(json): {hits['json']}")
    lines.append(f"기록이 지난 줄(text): {hits['text']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_DIFFERENT if missing else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("before")
    compare.add_argument("before_again")
    compare.add_argument("after")
    compare.add_argument("--intended", action="append", default=[])
    cover = sub.add_parser("cover")
    cover.add_argument("data")
    cover.add_argument("records")
    cover.add_argument("files", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_ERROR
    try:
        if args.command == "compare":
            return run_compare(args)
        return run_cover(args)
    except InputError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_ERROR
    except Exception as exc:
        sys.stderr.write(f"error: unexpected {type(exc).__name__}: {exc}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
