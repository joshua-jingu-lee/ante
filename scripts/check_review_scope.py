#!/usr/bin/env python3
"""Decide whether a branch diff can skip Gate A (branch review).

Exit 0: every changed file is a doc path, an AST-identical ``src/`` file, or
the comment baseline with no value above base.
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
            or change.path == COMMENT_BASELINE_PATH
        )
        and change.old_mode == change.new_mode
        and change.new_mode in REGULAR_MODES
    ):
        return None
    return REVIEW


def _load_baseline_parser() -> Callable[[str], Any]:
    spec = importlib.util.spec_from_file_location(
        "_check_review_scope_comments", CHECK_COMMENTS_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {CHECK_COMMENTS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    parser: Callable[[str], Any] = module.parse_baseline
    return parser


def _not_above(head: dict[str, int], base: dict[str, int]) -> bool:
    return all(path in base and count <= base[path] for path, count in head.items())


def baseline_lowered(old: bytes, new: bytes) -> bool:
    """True when both sides are valid baselines and no head value exceeds base."""
    try:
        parse = _load_baseline_parser()
        before = parse(old.decode("utf-8"))
        after = parse(new.decode("utf-8"))
    except Exception:
        return False
    return (
        _not_above(after.comments, before.comments)
        and _not_above(after.docstring_history, before.docstring_history)
        and after.docstring_lines <= before.docstring_lines
    )


def classify(change: Change) -> str:
    decided = classify_without_content(change)
    if decided is not None:
        return decided
    old = _run_git(["cat-file", "blob", change.old_sha])
    new = _run_git(["cat-file", "blob", change.new_sha])
    if change.path == COMMENT_BASELINE_PATH:
        return BASELINE_LOWERED if baseline_lowered(old, new) else REVIEW
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
