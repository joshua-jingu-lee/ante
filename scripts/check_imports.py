#!/usr/bin/env python3
"""Fail when the import boundaries of ``src/ante/`` differ from the baseline.

A module is the name of a package directly under ``src/ante`` or of a ``.py``
file directly under it; ``src/ante/__init__.py`` belongs to no module.

The targets of one import statement are the modules it names: ``x`` for
``import ante.x.y`` and ``from ante.x... import ...``, and the imported names
that are modules for ``from ante import a, b``. Relative imports are resolved
from the file location first. ``import ante`` alone, names outside ``ante``
and the importing module itself are no target. ``importlib`` and
``__import__`` are not read.

An import is not a runtime import when it sits in the body of an ``if`` whose
test is the name ``TYPE_CHECKING`` or an attribute ``<x>.TYPE_CHECKING``,
including ``elif`` and ``if`` inside functions. Every other import, ``else``
branches included, is a runtime import. A lazy import is a runtime import
with a function (``def``, ``async def``, ``lambda``) anywhere in its enclosing
scopes.

Measured values:

- ``edges``: ``"A->B"`` for every runtime import from module A to target B.
- ``cycles``: the strongly connected components of ``edges`` with two or more
  modules, each sorted.
- ``lazy_imports``: the number of targets summed over all lazy imports.
- ``sqlite_files``: repository-relative paths of files outside the ``core`` and
  ``db`` modules with an import whose imported name has ``sqlite3`` or
  ``aiosqlite`` as its first component, runtime or not.

Known limits: an alias of ``TYPE_CHECKING`` counts as a runtime test, and
dynamic imports are not counted.

Exit 0: all four values equal ``scripts/import_baseline.json``.
Exit 1: any value differs from the baseline, smaller ones included. Only the
comparison produces this code.
Exit 2: every other failure: a missing or malformed baseline, a source file
that cannot be read or parsed, a relative import beyond the top package, or
any unexpected exception.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

BASELINE_PATH = Path("scripts") / "import_baseline.json"
SOURCE_DIR = Path("src") / "ante"
PACKAGE = "ante"
SQLITE_DRIVERS = frozenset({"sqlite3", "aiosqlite"})
SQLITE_ALLOWED_MODULES = frozenset({"core", "db"})
EDGES = "edges"
CYCLES = "cycles"
LAZY_IMPORTS = "lazy_imports"
SQLITE_FILES = "sqlite_files"
BASELINE_KEYS = frozenset({EDGES, CYCLES, LAZY_IMPORTS, SQLITE_FILES})
EDGE_RE = re.compile(r"([a-z_]+)->([a-z_]+)")
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

EDGE_ADDED = (
    "호출부를 옮기거나 값을 주입한다. "
    "의도한 변경이면 기준선에 더하고 PR 본문에 이유를 쓴다"
)
REMOVE_FROM_BASELINE = "기준선에서 지운다"
CYCLE_GREW = "구성원 증가"
CYCLE_SHRANK = "구성원 감소: 기준선을 맞춘다"
CYCLE_NEW = "새 순환"
CYCLE_CHANGED = "순환 구성 변화"
CYCLE_GONE = "사라진 순환: 기준선에서 지운다"
LAZY_GREW = "최상위 import로 옮기거나 의존을 뒤집는다"
LAZY_SHRANK = "기준선을 낮춘다"
SQLITE_ADDED = "DB 접근은 `core`의 래퍼를 지난다"
SQLITE_MOVED = "파일을 옮긴 것이면 기준선 경로를 고친다"


class CheckError(RuntimeError):
    """Raised when the measurement or the baseline cannot be trusted."""


def source_files(root: Path) -> list[Path]:
    source_dir = root / SOURCE_DIR
    if not source_dir.is_dir():
        raise CheckError(f"source directory not found: {SOURCE_DIR}")
    return sorted(path for path in source_dir.rglob("*.py") if path.is_file())


def module_names(root: Path) -> frozenset[str]:
    source_dir = root / SOURCE_DIR
    packages = {
        path.name
        for path in source_dir.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    files = {
        path.stem for path in source_dir.glob("*.py") if path.name != "__init__.py"
    }
    return frozenset(packages | files)


def module_of(rel: Path) -> str | None:
    if rel.parts == ("__init__.py",):
        return None
    return rel.stem if len(rel.parts) == 1 else rel.parts[0]


def package_parts(rel: Path) -> list[str]:
    return [PACKAGE, *rel.parts[:-1]]


def is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def iter_imports(
    node: ast.AST, runtime: bool = True, lazy: bool = False
) -> Iterator[tuple[ast.Import | ast.ImportFrom, bool, bool]]:
    """Yield every import under ``node`` with its (runtime, lazy) flags."""
    for child in ast.iter_child_nodes(node):
        yield from _visit(child, runtime, lazy)


def _visit(
    node: ast.AST, runtime: bool, lazy: bool
) -> Iterator[tuple[ast.Import | ast.ImportFrom, bool, bool]]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        yield node, runtime, lazy and runtime
    elif isinstance(node, ast.If) and is_type_checking(node.test):
        for stmt in node.body:
            yield from _visit(stmt, False, lazy)
        for stmt in node.orelse:
            yield from _visit(stmt, runtime, lazy)
    else:
        yield from iter_imports(node, runtime, lazy or isinstance(node, FUNCTION_NODES))


def absolute_module(node: ast.ImportFrom, rel: Path) -> str:
    if not node.level:
        return node.module or ""
    package = package_parts(rel)
    if node.level > len(package):
        raise CheckError(
            f"{(SOURCE_DIR / rel).as_posix()}:{node.lineno}: relative import "
            f"of level {node.level} goes beyond the {PACKAGE} package"
        )
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def import_names(node: ast.Import | ast.ImportFrom, rel: Path) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return [absolute_module(node, rel)]


def targets(
    node: ast.Import | ast.ImportFrom, rel: Path, modules: frozenset[str]
) -> set[str]:
    found: set[str] = set()
    for name in import_names(node, rel):
        parts = name.split(".")
        if parts[0] != PACKAGE:
            continue
        if len(parts) > 1:
            found.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names if alias.name in modules)
    found.discard(module_of(rel) or "")
    return found


def is_sqlite_import(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    elif node.level == 0 and node.module:
        names = [node.module]
    else:
        names = []
    return any(name.split(".")[0] in SQLITE_DRIVERS for name in names)


def strongly_connected(edges: Iterable[str]) -> list[list[str]]:
    """Return the components with two or more nodes, sorted, of an edge set."""
    graph: dict[str, set[str]] = {}
    for edge in edges:
        source, target = edge.split("->")
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph[node]):
            if nxt not in index:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])
        if low[node] == index[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return sorted(components)


def measure(root: Path) -> dict[str, Any]:
    files = source_files(root)
    modules = module_names(root)
    edges: set[str] = set()
    lazy_imports = 0
    sqlite_files: set[str] = set()
    for path in files:
        rel = path.relative_to(root / SOURCE_DIR)
        label = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=label)
        except Exception as exc:
            raise CheckError(
                f"cannot read or parse {label}: {type(exc).__name__}: {exc}"
            ) from exc
        source = module_of(rel)
        for node, runtime, lazy in iter_imports(tree):
            found = targets(node, rel, modules)
            if runtime and source is not None:
                edges.update(f"{source}->{target}" for target in found)
            if lazy:
                lazy_imports += len(found)
            if source not in SQLITE_ALLOWED_MODULES and is_sqlite_import(node):
                sqlite_files.add(label)
    return {
        EDGES: sorted(edges),
        CYCLES: strongly_connected(edges),
        LAZY_IMPORTS: lazy_imports,
        SQLITE_FILES: sorted(sqlite_files),
    }


def _check_strings(key: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be a list of strings")
    _check_sorted_unique(key, value)
    return value


def _check_sorted_unique(key: str, value: Sequence[Any]) -> None:
    if len(set(map(_freeze, value))) != len(value):
        raise CheckError(f"{BASELINE_PATH}: {key!r} has duplicates")
    if list(value) != sorted(value):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be sorted")


def _freeze(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def read_baseline(root: Path) -> dict[str, Any]:
    path = root / BASELINE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    return parse_baseline(text)


def parse_baseline(text: str) -> dict[str, Any]:
    """Validate baseline JSON text; raise ``CheckError`` when it is malformed."""
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
    edges = _check_strings(EDGES, data[EDGES])
    for edge in edges:
        match = EDGE_RE.fullmatch(edge)
        if match is None or match.group(1) == match.group(2):
            raise CheckError(
                f"{BASELINE_PATH}: edge {edge!r} must look like 'a->b' with a != b"
            )
    sqlite_files = _check_strings(SQLITE_FILES, data[SQLITE_FILES])
    cycles = data[CYCLES]
    if not isinstance(cycles, list) or not all(isinstance(c, list) for c in cycles):
        raise CheckError(f"{BASELINE_PATH}: {CYCLES!r} must be a list of lists")
    for component in cycles:
        _check_strings(CYCLES, component)
    _check_sorted_unique(CYCLES, cycles)
    if cycles != strongly_connected(edges):
        raise CheckError(
            f"{BASELINE_PATH}: {CYCLES!r} must be the strongly connected "
            f"components of {EDGES!r}: {strongly_connected(edges)}"
        )
    lazy = data[LAZY_IMPORTS]
    if not isinstance(lazy, int) or isinstance(lazy, bool) or lazy < 0:
        raise CheckError(
            f"{BASELINE_PATH}: {LAZY_IMPORTS!r} must be a non-negative integer, "
            f"got {lazy!r}"
        )
    return {
        EDGES: edges,
        CYCLES: cycles,
        LAZY_IMPORTS: lazy,
        SQLITE_FILES: sqlite_files,
    }


def _cycle_verdict(
    component: frozenset[str], baseline: list[frozenset[str]]
) -> str | None:
    if component in baseline:
        return None
    if any(component > other for other in baseline):
        return CYCLE_GREW
    if any(component < other for other in baseline):
        return CYCLE_SHRANK
    if all(component.isdisjoint(other) for other in baseline):
        return CYCLE_NEW
    return CYCLE_CHANGED


def _cycle_lines(
    actual: list[frozenset[str]], baseline: list[frozenset[str]]
) -> list[str]:
    lines: list[str] = []
    for component in actual:
        verdict = _cycle_verdict(component, baseline)
        if verdict is not None:
            lines.append(f"{CYCLES} {sorted(component)}: {verdict}")
    for component in baseline:
        if all(component.isdisjoint(other) for other in actual):
            lines.append(f"{CYCLES} {sorted(component)}: {CYCLE_GONE}")
    return lines


def compare(
    measured: Mapping[str, Any], baseline: Mapping[str, Any]
) -> tuple[int, str]:
    lines: list[str] = []
    actual_edges, base_edges = set(measured[EDGES]), set(baseline[EDGES])
    lines += [f"{EDGES} +{e}: {EDGE_ADDED}" for e in sorted(actual_edges - base_edges)]
    lines += [
        f"{EDGES} -{e}: {REMOVE_FROM_BASELINE}"
        for e in sorted(base_edges - actual_edges)
    ]
    actual_cycles = [frozenset(c) for c in measured[CYCLES]]
    base_cycles = [frozenset(c) for c in baseline[CYCLES]]
    if set(actual_cycles) != set(base_cycles):
        lines += _cycle_lines(actual_cycles, base_cycles)
    got, want = measured[LAZY_IMPORTS], baseline[LAZY_IMPORTS]
    if got != want:
        hint = LAZY_GREW if got > want else LAZY_SHRANK
        lines.append(
            f"{LAZY_IMPORTS}: actual {got}, baseline {want} ({got - want:+d}): {hint}"
        )
    actual_sqlite, base_sqlite = (
        set(measured[SQLITE_FILES]),
        set(baseline[SQLITE_FILES]),
    )
    added, removed = actual_sqlite - base_sqlite, base_sqlite - actual_sqlite
    if added and removed:
        added_hint = removed_hint = SQLITE_MOVED
    else:
        added_hint, removed_hint = SQLITE_ADDED, REMOVE_FROM_BASELINE
    lines += [f"{SQLITE_FILES} +{p}: {added_hint}" for p in sorted(added)]
    lines += [f"{SQLITE_FILES} -{p}: {removed_hint}" for p in sorted(removed)]
    if not lines:
        return EXIT_OK, (
            f"import check ok: {len(actual_edges)} edges, {len(actual_cycles)} "
            f"cycles, {got} lazy imports, {len(actual_sqlite)} sqlite files "
            f"(baseline {BASELINE_PATH})"
        )
    return EXIT_MISMATCH, "\n".join(
        [f"import check failed against {BASELINE_PATH}:", *lines]
    )


def run(root: Path) -> tuple[int, str]:
    try:
        baseline = read_baseline(root)
        measured = measure(root)
    except CheckError as exc:
        return EXIT_ERROR, str(exc)
    return compare(measured, baseline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check src/ante import boundaries against a baseline."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    try:
        code, message = run(args.root)
    except Exception as exc:
        code = EXIT_ERROR
        message = f"import check error: {type(exc).__name__}: {exc}"
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
