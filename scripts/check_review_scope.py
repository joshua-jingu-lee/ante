#!/usr/bin/env python3
"""Decide whether a branch diff can skip Gate A (branch review).

This docstring is the canonical definition of the skip classes. Each changed
file (base = merge-base of ``--base`` and ``--head``) gets one class:

A doc path is one under ``docs/``, ``.agent/`` or ``guide/``, or a ``*.md``
file at the repository root. A regular file mode is ``100644`` or ``100755``.

- ``doc``: a doc path that is added as a regular file, deleted from a regular
  file, or modified with the same regular file mode before and after; or a
  rename whose old and new paths are both doc paths, with the same regular
  file mode before and after.
- ``ast-identical``: a modified ``.py`` file under ``src/`` with the same
  regular file mode before and after, whose base and head both parse and give
  the same AST once every docstring is dropped. A docstring here is the first
  statement of a module, class or function body when it is a ``str``
  constant. Only comments and those docstrings changed.
- ``baseline-lowered``: ``scripts/comment_baseline.json`` modified with the
  same regular file mode before and after, both sides decoding as UTF-8 and
  passing ``parse_baseline`` of ``check_comments.py`` (loaded by file path
  next to this script), every head key of ``comments``, ``docstring_history``
  and ``docstring_excess`` present in base with a value not above base, and
  ``docstring_lines`` not above base. Equal values qualify. A key removed in
  head is a decrease. A head key missing from base, or a side that cannot be
  loaded or validated, is ``review``. Since both sides go through the same
  ``parse_baseline``, a base whose top-level keys differ from the ones it
  requires (a baseline from before a key was added or after one was removed)
  is ``review``. Also ``scripts/spec_code_block_baseline.json`` modified with
  the same regular file mode before and after, both sides decoding as UTF-8
  and passing ``parse_baseline`` of ``check_spec_code_blocks.py`` (loaded by
  file path next to this script), and every head value not above base. That
  ``parse_baseline`` requires the same three keys on both sides, so a key
  added or removed is ``review``.
- ``review``: anything else, including copies, type changes, symlinks,
  submodules and any rename outside doc paths.

Known limits of ``baseline-lowered``: it compares per-file counts only, so a
change that removes comments from a file and adds fewer new ones there, or
rewrites docstrings without adding lines, still skips. When ``comments`` in
the baseline is ``{}``, any added comment creates a new key and is ``review``.
A doc change that changes a block's language and lowers the spec code block
baseline skips.

Exit 0: every changed file is ``doc``, ``ast-identical`` or
``baseline-lowered``.
Exit 1: at least one file needs review, or the diff is empty.
Exit 2: the decision could not be made (git failure, bad ref).

Git runs in the current working directory.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOC = "doc"
AST_IDENTICAL = "ast-identical"
BASELINE_LOWERED = "baseline-lowered"
REVIEW = "review"

DOC_PREFIXES = ("docs/", ".agent/", "guide/")
REGULAR_MODES = frozenset({"100644", "100755"})
ABSENT_MODE = "000000"
DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
COMMENT_BASELINE_PATH = "scripts/comment_baseline.json"
CHECK_COMMENTS_PATH = Path(__file__).with_name("check_comments.py")
SPEC_BASELINE_PATH = "scripts/spec_code_block_baseline.json"
CHECK_SPEC_BLOCKS_PATH = Path(__file__).with_name("check_spec_code_blocks.py")


class ScopeError(RuntimeError):
    """Raised when git cannot answer a question the decision depends on."""


@dataclass(frozen=True)
class Change:
    status: str
    old_mode: str
    new_mode: str
    old_sha: str
    new_sha: str
    path: str
    old_path: str | None = None


def is_doc_path(path: str) -> bool:
    if path.startswith(DOC_PREFIXES):
        return True
    return "/" not in path and path.endswith(".md")


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_OWNERS) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = node.body[1:]
    return tree


def ast_identical_without_docstrings(old: bytes, new: bytes) -> bool:
    try:
        old_tree = _strip_docstrings(ast.parse(old))
        new_tree = _strip_docstrings(ast.parse(new))
    except (SyntaxError, ValueError, RecursionError):
        return False
    return ast.dump(old_tree) == ast.dump(new_tree)


def _run_git(args: Sequence[str]) -> bytes:
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ScopeError(f"git 실행 실패: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise ScopeError(
            f"git {' '.join(args)} 실패 (exit {proc.returncode}): {stderr}"
        )
    return proc.stdout


def _rev(ref: str) -> str:
    return (
        _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        .decode()
        .strip()
    )


def merge_base(base: str, head: str) -> str:
    return _run_git(["merge-base", base, head]).decode().strip()


def parse_raw_diff(raw: bytes) -> list[Change]:
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[Change] = []
    i = 0
    while i < len(fields):
        meta = fields[i].decode("ascii", "replace")
        if not meta.startswith(":"):
            raise ScopeError(f"git diff --raw 출력 해석 실패: {meta!r}")
        parts = meta[1:].split(" ")
        if len(parts) != 5:
            raise ScopeError(f"git diff --raw 출력 해석 실패: {meta!r}")
        old_mode, new_mode, old_sha, new_sha, status = parts
        letter = status[:1]
        if letter in ("R", "C"):
            if i + 2 >= len(fields):
                raise ScopeError("git diff --raw 출력이 잘렸다")
            old_path = os.fsdecode(fields[i + 1])
            path = os.fsdecode(fields[i + 2])
            i += 3
        else:
            if i + 1 >= len(fields):
                raise ScopeError("git diff --raw 출력이 잘렸다")
            old_path = None
            path = os.fsdecode(fields[i + 1])
            i += 2
        changes.append(
            Change(letter, old_mode, new_mode, old_sha, new_sha, path, old_path)
        )
    return changes


def _modes_ok_for_doc(change: Change) -> bool:
    if change.status == "A":
        return change.old_mode == ABSENT_MODE and change.new_mode in REGULAR_MODES
    if change.status == "D":
        return change.old_mode in REGULAR_MODES and change.new_mode == ABSENT_MODE
    return change.old_mode == change.new_mode and change.new_mode in REGULAR_MODES


def classify_without_content(change: Change) -> str | None:
    """Return DOC/REVIEW when paths and modes decide; None when content must be read."""
    if change.status not in ("A", "M", "D", "R"):
        return REVIEW
    if change.status == "R":
        assert change.old_path is not None
        if (
            is_doc_path(change.old_path)
            and is_doc_path(change.path)
            and _modes_ok_for_doc(change)
        ):
            return DOC
        return REVIEW
    if is_doc_path(change.path):
        return DOC if _modes_ok_for_doc(change) else REVIEW
    if (
        change.status == "M"
        and (
            (change.path.startswith("src/") and change.path.endswith(".py"))
            or change.path in (COMMENT_BASELINE_PATH, SPEC_BASELINE_PATH)
        )
        and change.old_mode == change.new_mode
        and change.new_mode in REGULAR_MODES
    ):
        return None
    return REVIEW


def _load_parser(name: str, path: Path) -> Callable[[str], Any]:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    parser: Callable[[str], Any] = module.parse_baseline
    return parser


def _load_baseline_parser() -> Callable[[str], Any]:
    return _load_parser("_check_review_scope_comments", CHECK_COMMENTS_PATH)


def _load_spec_baseline_parser() -> Callable[[str], Any]:
    return _load_parser("_check_review_scope_spec_blocks", CHECK_SPEC_BLOCKS_PATH)


def _not_above(head: dict[str, int], base: dict[str, int]) -> bool:
    return all(path in base and count <= base[path] for path, count in head.items())


def baseline_lowered(old: bytes, new: bytes) -> bool:
    """True when both sides are valid baselines and no head value exceeds base."""
    try:
        parse = _load_baseline_parser()
        before = parse(old.decode("utf-8"))
        after = parse(new.decode("utf-8"))
        return bool(
            _not_above(after.comments, before.comments)
            and _not_above(after.docstring_history, before.docstring_history)
            and _not_above(after.docstring_excess, before.docstring_excess)
            and after.docstring_lines <= before.docstring_lines
        )
    except (Exception, SystemExit):
        return False


def spec_baseline_lowered(old: bytes, new: bytes) -> bool:
    """True when both spec baselines are valid and no head value exceeds base."""
    try:
        parse = _load_spec_baseline_parser()
        before = parse(old.decode("utf-8"))
        after = parse(new.decode("utf-8"))
        return bool(
            isinstance(before, dict)
            and isinstance(after, dict)
            and set(after) == set(before)
            and _not_above(after, before)
        )
    except (Exception, SystemExit):
        return False


def classify(change: Change) -> str:
    decided = classify_without_content(change)
    if decided is not None:
        return decided
    old = _run_git(["cat-file", "blob", change.old_sha])
    new = _run_git(["cat-file", "blob", change.new_sha])
    if change.path == COMMENT_BASELINE_PATH:
        return BASELINE_LOWERED if baseline_lowered(old, new) else REVIEW
    if change.path == SPEC_BASELINE_PATH:
        return BASELINE_LOWERED if spec_baseline_lowered(old, new) else REVIEW
    return AST_IDENTICAL if ast_identical_without_docstrings(old, new) else REVIEW


def _display(change: Change) -> str:
    if change.old_path is not None:
        return f"{change.old_path} -> {change.path}"
    return change.path


def run(base: str, head: str) -> int:
    head_sha = _rev(head)
    base_sha = merge_base(base, head_sha)
    raw = _run_git(
        [
            "diff",
            "--raw",
            "-z",
            "-M",
            "--no-abbrev",
            "--no-ext-diff",
            base_sha,
            head_sha,
        ]
    )
    changes = parse_raw_diff(raw)
    print(f"scope: {base_sha}...{head_sha}")
    if not changes:
        print("verdict: REVIEW (empty diff)")
        return 1
    verdicts = [(classify(change), change) for change in changes]
    for kind, change in verdicts:
        print(f"{kind}\t{change.status}\t{_display(change)}")
    if all(kind in (DOC, AST_IDENTICAL, BASELINE_LOWERED) for kind, _ in verdicts):
        kinds = sorted({kind for kind, _ in verdicts})
        print(f"verdict: SKIP ({', '.join(kinds)})")
        return 0
    print("verdict: REVIEW")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", default="origin/main", help="base ref (merge-base is recomputed)"
    )
    parser.add_argument("--head", default="HEAD", help="head ref")
    args = parser.parse_args(argv)
    try:
        return run(args.base, args.head)
    except ScopeError as exc:
        print(f"verdict: ERROR ({exc})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
