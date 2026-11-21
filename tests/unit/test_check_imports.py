"""Import boundary check tests."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SQLITE_FILES_CAP = 10


def _load_checker() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_imports.py"
    spec = importlib.util.spec_from_file_location("check_imports", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

Capsys = pytest.CaptureFixture[str]
PACKAGES = ("a", "b", "c", "core", "db")


def _tree(root: Path, files: dict[str, str]) -> Path:
    base = root / "src" / "ante"
    for package in PACKAGES:
        (base / package).mkdir(parents=True, exist_ok=True)
        (base / package / "__init__.py").write_text("", encoding="utf-8")
    (base / "__init__.py").write_text("", encoding="utf-8")
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _baseline(
    edges: list[str] | None = None,
    cycles: list[list[str]] | None = None,
    lazy: int = 0,
    sqlite: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "edges": edges or [],
        "cycles": cycles or [],
        "lazy_imports": lazy,
        "sqlite_files": sqlite or [],
    }


def _write_baseline(root: Path, data: object) -> None:
    path = root / "scripts" / "import_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    path.write_text(text, encoding="utf-8")


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _measure(tmp_path: Path, files: dict[str, str]) -> dict[str, Any]:
    return checker.measure(_tree(tmp_path, files))


def _message_lines(message: str) -> list[str]:
    return message.splitlines()[1:]


TC = "from typing import TYPE_CHECKING\n"

DEFINITION_ROWS = [
    ("top-level", {"a/m.py": "import ante.b\n"}, {"a->b"}, 0),
    ("def", {"a/m.py": "def f():\n    import ante.b\n"}, {"a->b"}, 1),
    ("async-def", {"a/m.py": "async def f():\n    import ante.b\n"}, {"a->b"}, 1),
    (
        "nested-function",
        {"a/m.py": "def f():\n    def g():\n        import ante.b\n"},
        {"a->b"},
        1,
    ),
    ("class-body", {"a/m.py": "class C:\n    import ante.b\n"}, {"a->b"}, 0),
    (
        "class-in-function",
        {"a/m.py": "def f():\n    class C:\n        import ante.b\n"},
        {"a->b"},
        1,
    ),
    (
        "module-try",
        {"a/m.py": "try:\n    import ante.b\nexcept ImportError:\n    pass\n"},
        {"a->b"},
        0,
    ),
    ("module-if", {"a/m.py": "if X:\n    import ante.b\n"}, {"a->b"}, 0),
    (
        "type-checking-name",
        {"a/m.py": TC + "if TYPE_CHECKING:\n    import ante.b\n"},
        set(),
        0,
    ),
    (
        "type-checking-attribute",
        {"a/m.py": "import typing\nif typing.TYPE_CHECKING:\n    import ante.b\n"},
        set(),
        0,
    ),
    (
        "elif-type-checking",
        {"a/m.py": TC + "if X:\n    pass\nelif TYPE_CHECKING:\n    import ante.b\n"},
        set(),
        0,
    ),
    (
        "type-checking-else",
        {
            "a/m.py": TC
            + "if TYPE_CHECKING:\n    import ante.b\nelse:\n    import ante.c\n"
        },
        {"a->c"},
        0,
    ),
    (
        "type-checking-in-function",
        {"a/m.py": TC + "def f():\n    if TYPE_CHECKING:\n        import ante.b\n"},
        set(),
        0,
    ),
    ("relative-level-1", {"main.py": "from . import b\n"}, {"main->b"}, 0),
    ("relative-level-2", {"a/m.py": "from ..b import x\n"}, {"a->b"}, 0),
    ("from-ante-module", {"a/m.py": "from ante import b\n"}, {"a->b"}, 0),
    ("from-ante-non-module", {"a/m.py": "from ante import version\n"}, set(), 0),
    ("from-ante-two", {"a/m.py": "from ante import b, c\n"}, {"a->b", "a->c"}, 0),
    (
        "function-from-ante-two",
        {"a/m.py": "def f():\n    from ante import b, c\n"},
        {"a->b", "a->c"},
        2,
    ),
    (
        "function-import-two",
        {"a/m.py": "def f():\n    import ante.b, ante.c\n"},
        {"a->b", "a->c"},
        2,
    ),
    ("import-ante", {"a/m.py": "import ante\n"}, set(), 0),
    ("import-ante-x-y", {"a/m.py": "import ante.b.x\n"}, {"a->b"}, 0),
    ("outside-ante", {"a/m.py": "import os\nfrom os import path\n"}, set(), 0),
    (
        "importlib",
        {"a/m.py": "import importlib\nimportlib.import_module('ante.b')\n"},
        set(),
        0,
    ),
    ("same-module", {"a/m.py": "def f():\n    import ante.a.x\n"}, set(), 0),
    ("package-init", {"__init__.py": "import ante.b\n"}, set(), 0),
    (
        "package-init-function",
        {"__init__.py": "def f():\n    import ante.b\n"},
        set(),
        1,
    ),
]


@pytest.mark.parametrize(
    ("files", "edges", "lazy"),
    [row[1:] for row in DEFINITION_ROWS],
    ids=[row[0] for row in DEFINITION_ROWS],
)
def test_definition(
    tmp_path: Path, files: dict[str, str], edges: set[str], lazy: int
) -> None:
    measured = _measure(tmp_path, files)
    assert set(measured["edges"]) == edges
    assert measured["lazy_imports"] == lazy


SQLITE_STATEMENTS = [
    "import sqlite3\n",
    "import sqlite3 as s\n",
    "from sqlite3 import Error\n",
    "import sqlite3.dbapi2\n",
    "import aiosqlite\n",
]


@pytest.mark.parametrize("statement", SQLITE_STATEMENTS)
@pytest.mark.parametrize(
    ("package", "listed"), [("a", True), ("core", False), ("db", False)]
)
def test_sqlite_import(
    tmp_path: Path, statement: str, package: str, listed: bool
) -> None:
    measured = _measure(tmp_path, {f"{package}/m.py": statement})
    expected = [f"src/ante/{package}/m.py"] if listed else []
    assert measured["sqlite_files"] == expected


@pytest.mark.parametrize(
    "source",
    [TC + "if TYPE_CHECKING:\n    import sqlite3\n", "def f():\n    import sqlite3\n"],
    ids=["type-checking", "function"],
)
def test_sqlite_import_not_at_runtime_top_level_is_listed(
    tmp_path: Path, source: str
) -> None:
    measured = _measure(tmp_path, {"a/m.py": source})
    assert measured["sqlite_files"] == ["src/ante/a/m.py"]


def test_cycle_closed_by_lazy_imports_only(tmp_path: Path) -> None:
    measured = _measure(
        tmp_path,
        {
            "a/m.py": "def f():\n    import ante.b\n",
            "b/m.py": "def g():\n    from ante import a\n",
        },
    )
    assert measured["cycles"] == [["a", "b"]]
    assert measured["lazy_imports"] == 2


@pytest.mark.parametrize(
    "files",
    [{"a/m.py": "from ... import b\n"}, {"a/m.py": "def broken(:\n"}],
    ids=["relative-beyond-package", "unparsable"],
)
def test_unreadable_source_is_error(
    tmp_path: Path, capsys: Capsys, files: dict[str, str]
) -> None:
    _tree(tmp_path, files)
    _write_baseline(tmp_path, _baseline())
    code, output = _run(tmp_path, capsys)
    assert code == 2
    assert "src/ante/a/m.py" in output


# ── 판정 ──────────────────────────────────────────────

EDGE_A_B = {"a/m.py": "import ante.b\n"}

JUDGMENT_ROWS = [
    ("edges-match", EDGE_A_B, _baseline(edges=["a->b"]), 0, []),
    (
        "edges-grew",
        {"a/m.py": "import ante.b\nimport ante.c\n"},
        _baseline(edges=["a->b"]),
        1,
        ["edges +a->c: " + checker.EDGE_ADDED],
    ),
    (
        "edges-shrank",
        {},
        _baseline(edges=["a->b"]),
        1,
        ["edges -a->b: " + checker.REMOVE_FROM_BASELINE],
    ),
    (
        "edges-swapped",
        {"a/m.py": "import ante.c\n"},
        _baseline(edges=["a->b"]),
        1,
        [
            "edges +a->c: " + checker.EDGE_ADDED,
            "edges -a->b: " + checker.REMOVE_FROM_BASELINE,
        ],
    ),
    (
        "lazy-match",
        {"a/m.py": "import ante.b\ndef f():\n    import ante.b\n"},
        _baseline(edges=["a->b"], lazy=1),
        0,
        [],
    ),
    (
        "lazy-grew",
        {"a/m.py": "import ante.b\ndef f():\n    import ante.b\n    import ante.b\n"},
        _baseline(edges=["a->b"], lazy=1),
        1,
        [checker.LAZY_GREW],
    ),
    (
        "lazy-shrank",
        EDGE_A_B,
        _baseline(edges=["a->b"], lazy=1),
        1,
        [checker.LAZY_SHRANK],
    ),
    (
        "sqlite-match",
        {"a/m.py": "import sqlite3\n"},
        _baseline(sqlite=["src/ante/a/m.py"]),
        0,
        [],
    ),
    (
        "sqlite-added",
        {"a/m.py": "import sqlite3\n", "b/m.py": "import sqlite3\n"},
        _baseline(sqlite=["src/ante/a/m.py"]),
        1,
        ["sqlite_files +src/ante/b/m.py: " + checker.SQLITE_ADDED],
    ),
    (
        "sqlite-removed",
        {},
        _baseline(sqlite=["src/ante/a/m.py"]),
        1,
        ["sqlite_files -src/ante/a/m.py: " + checker.REMOVE_FROM_BASELINE],
    ),
    (
        "sqlite-moved",
        {"b/m.py": "import sqlite3\n"},
        _baseline(sqlite=["src/ante/a/m.py"]),
        1,
        [
            "sqlite_files +src/ante/b/m.py: " + checker.SQLITE_MOVED,
            "sqlite_files -src/ante/a/m.py: " + checker.SQLITE_MOVED,
        ],
    ),
]


@pytest.mark.parametrize(
    ("files", "baseline", "code", "messages"),
    [row[1:] for row in JUDGMENT_ROWS],
    ids=[row[0] for row in JUDGMENT_ROWS],
)
def test_judgment(
    tmp_path: Path,
    capsys: Capsys,
    files: dict[str, str],
    baseline: dict[str, Any],
    code: int,
    messages: list[str],
) -> None:
    _tree(tmp_path, files)
    _write_baseline(tmp_path, baseline)
    actual, output = _run(tmp_path, capsys)
    assert actual == code, output
    if code:
        lines = _message_lines(output)
        assert len(lines) == len(messages), output
        for line, message in zip(lines, messages, strict=True):
            assert message in line, output


AB, ABC, CD, XY = ["a", "b"], ["a", "b", "c"], ["c", "d"], ["x", "y"]

CYCLE_ROWS = [
    ("match", [AB], [AB], []),
    ("grew", [ABC], [AB], [(ABC, checker.CYCLE_GREW)]),
    (
        "merged",
        [["a", "b", "c", "d"]],
        [AB, CD],
        [(["a", "b", "c", "d"], checker.CYCLE_GREW)],
    ),
    ("shrank", [AB], [ABC], [(AB, checker.CYCLE_SHRANK)]),
    ("new", [AB, CD], [AB], [(CD, checker.CYCLE_NEW)]),
    ("changed", [["b", "c"]], [AB], [(["b", "c"], checker.CYCLE_CHANGED)]),
    ("gone", [], [AB], [(AB, checker.CYCLE_GONE)]),
    ("swapped", [CD], [AB], [(CD, checker.CYCLE_NEW), (AB, checker.CYCLE_GONE)]),
    ("two-match", [AB, XY], [AB, XY], []),
    ("two-grew", [ABC, XY], [AB, XY], [(ABC, checker.CYCLE_GREW)]),
    ("two-shrank", [AB, XY], [ABC, XY], [(AB, checker.CYCLE_SHRANK)]),
    ("two-new", [AB, CD, XY], [AB, XY], [(CD, checker.CYCLE_NEW)]),
    (
        "two-changed",
        [["b", "c"]],
        [AB, XY],
        [(["b", "c"], checker.CYCLE_CHANGED), (XY, checker.CYCLE_GONE)],
    ),
    (
        "two-changed-across",
        [["b", "x"]],
        [AB, XY],
        [(["b", "x"], checker.CYCLE_CHANGED)],
    ),
    ("two-gone", [AB], [AB, XY], [(XY, checker.CYCLE_GONE)]),
    (
        "two-merged-with-new",
        [["a", "b", "x", "y"], CD],
        [AB, XY],
        [(["a", "b", "x", "y"], checker.CYCLE_GREW), (CD, checker.CYCLE_NEW)],
    ),
]


@pytest.mark.parametrize(
    ("actual", "baseline", "expected"),
    [row[1:] for row in CYCLE_ROWS],
    ids=[row[0] for row in CYCLE_ROWS],
)
def test_cycle_judgment(
    actual: list[list[str]],
    baseline: list[list[str]],
    expected: list[tuple[list[str], str]],
) -> None:
    code, output = checker.compare(_baseline(cycles=actual), _baseline(cycles=baseline))
    assert code == (1 if expected else 0), output
    if expected:
        lines = [f"cycles {component}: {verdict}" for component, verdict in expected]
        assert _message_lines(output) == lines, output


# ── 기준선 형식 ──────────────────────────────────────────────

VALID = _baseline(edges=["a->b", "b->a"], cycles=[AB], sqlite=["x", "y"])

STRINGS = "must be a list of strings"
SORTED = "must be sorted"
DUPLICATES = "has duplicates"
EDGE_SHAPE = "must look like 'a->b' with a != b"
COMPONENTS = "must be the strongly connected components"
LAZY = "must be a non-negative integer"


def _edge_only(edge: str) -> dict[str, Any]:
    return {**VALID, "edges": [edge], "cycles": []}


FORMAT_ROWS = [
    ("broken-json", "{", "is not valid JSON"),
    ("not-object", "[]", "must hold a JSON object"),
    (
        "key-missing",
        {k: v for k, v in VALID.items() if k != "lazy_imports"},
        "missing ['lazy_imports']",
    ),
    ("key-extra", {**VALID, "extra": []}, "extra ['extra']"),
    ("edges-not-list", {**VALID, "edges": "a->b"}, f"'edges' {STRINGS}"),
    ("edges-not-strings", {**VALID, "edges": [1]}, f"'edges' {STRINGS}"),
    ("sqlite-not-list", {**VALID, "sqlite_files": "x"}, f"'sqlite_files' {STRINGS}"),
    ("sqlite-not-strings", {**VALID, "sqlite_files": [1]}, f"'sqlite_files' {STRINGS}"),
    ("cycles-not-list", {**VALID, "cycles": {}}, "must be a list of lists"),
    ("cycles-not-lists", {**VALID, "cycles": ["a"]}, "must be a list of lists"),
    ("cycle-not-strings", {**VALID, "cycles": [[1, 2]]}, f"'cycles' {STRINGS}"),
    ("lazy-not-int", {**VALID, "lazy_imports": "1"}, LAZY),
    ("lazy-float", {**VALID, "lazy_imports": 1.0}, LAZY),
    ("lazy-bool", {**VALID, "lazy_imports": True}, LAZY),
    ("lazy-negative", {**VALID, "lazy_imports": -1}, LAZY),
    ("edges-unsorted", {**VALID, "edges": ["b->a", "a->b"]}, f"'edges' {SORTED}"),
    (
        "sqlite-unsorted",
        {**VALID, "sqlite_files": ["y", "x"]},
        f"'sqlite_files' {SORTED}",
    ),
    ("cycle-unsorted", {**VALID, "cycles": [["b", "a"]]}, f"'cycles' {SORTED}"),
    (
        "cycles-unsorted",
        {
            **VALID,
            "edges": ["a->b", "b->a", "c->d", "d->c"],
            "cycles": [CD, AB],
        },
        f"'cycles' {SORTED}",
    ),
    (
        "edges-duplicate",
        {**VALID, "edges": ["a->b", "a->b", "b->a"]},
        f"'edges' {DUPLICATES}",
    ),
    (
        "sqlite-duplicate",
        {**VALID, "sqlite_files": ["x", "x"]},
        f"'sqlite_files' {DUPLICATES}",
    ),
    ("cycles-duplicate", {**VALID, "cycles": [AB, AB]}, f"'cycles' {DUPLICATES}"),
    (
        "cycle-member-duplicate",
        {**VALID, "cycles": [["a", "a", "b"]]},
        f"'cycles' {DUPLICATES}",
    ),
    ("edge-no-arrow", _edge_only("a-b"), EDGE_SHAPE),
    ("edge-left-upper", _edge_only("A->b"), EDGE_SHAPE),
    ("edge-right-upper", _edge_only("a->B"), EDGE_SHAPE),
    ("edge-left-digit", _edge_only("a1->b"), EDGE_SHAPE),
    ("edge-right-digit", _edge_only("a->b1"), EDGE_SHAPE),
    ("edge-space", _edge_only("a ->b"), EDGE_SHAPE),
    ("edge-trailing-newline", _edge_only("a->b\n"), EDGE_SHAPE),
    ("edge-leading-text", _edge_only("x a->b"), EDGE_SHAPE),
    ("edge-empty-left", _edge_only("->b"), EDGE_SHAPE),
    ("edge-three", _edge_only("a->b->c"), EDGE_SHAPE),
    ("edge-self", _edge_only("a->a"), EDGE_SHAPE),
    ("cycles-not-components", {**VALID, "cycles": []}, COMPONENTS),
    ("cycles-not-edges", {**VALID, "edges": ["a->b"]}, COMPONENTS),
]


def test_valid_baseline_parses() -> None:
    assert checker.parse_baseline(json.dumps(VALID)) == VALID


@pytest.mark.parametrize(
    ("data", "message"),
    [row[1:] for row in FORMAT_ROWS],
    ids=[row[0] for row in FORMAT_ROWS],
)
def test_malformed_baseline_is_error(
    tmp_path: Path, capsys: Capsys, data: object, message: str
) -> None:
    _tree(tmp_path, {})
    _write_baseline(tmp_path, data)
    code, output = _run(tmp_path, capsys)
    assert code == 2, output
    assert f"{checker.BASELINE_PATH}" in output
    assert message in output, output


def test_missing_baseline_is_error(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path, {})
    code, output = _run(tmp_path, capsys)
    assert code == 2
    assert "baseline file not found" in output


def test_missing_source_directory_is_error(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _baseline())
    code, output = _run(tmp_path, capsys)
    assert code == 2
    assert "source directory not found" in output


def test_unexpected_exception_is_error(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tree(tmp_path, {})
    _write_baseline(tmp_path, _baseline())

    def explode(_root: Path) -> dict[str, Any]:
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(checker, "measure", explode)
    code, output = _run(tmp_path, capsys)
    assert code == 2
    assert "ZeroDivisionError" in output


def test_baseline_sqlite_files_stay_under_cap() -> None:
    baseline = checker.read_baseline(REPO_ROOT)
    assert len(baseline["sqlite_files"]) <= SQLITE_FILES_CAP


# ── 실제 트리 ──────────────────────────────────────────────


def test_checkout_matches_baseline(capsys: Capsys) -> None:
    code, output = _run(REPO_ROOT, capsys)
    assert code == 0, output


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "copy"
    shutil.copytree(
        REPO_ROOT / "src" / "ante",
        root / "src" / "ante",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (root / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / checker.BASELINE_PATH, root / checker.BASELINE_PATH)
    return root


def _changed_axes(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    return {key for key in before if before[key] != after[key]}


def test_unmodified_copy_matches_baseline(copy_root: Path, capsys: Capsys) -> None:
    code, output = _run(copy_root, capsys)
    assert code == 0, output


def _insert_after_future(path: Path, line: str) -> None:
    text = path.read_text(encoding="utf-8")
    anchor = "from __future__ import annotations\n"
    assert anchor in text
    path.write_text(text.replace(anchor, anchor + line, 1), encoding="utf-8")


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


@pytest.mark.parametrize(
    ("rel", "edit", "axes"),
    [
        (
            "eventbus/bus.py",
            lambda path: _insert_after_future(path, "from ante.rule import engine\n"),
            {"edges", "cycles"},
        ),
        (
            "rule/engine.py",
            lambda path: _append(
                path, "\n\ndef _probe() -> None:\n    from ante.eventbus import bus\n"
            ),
            {"lazy_imports"},
        ),
        (
            "audit/logger.py",
            lambda path: _append(path, "\nimport sqlite3\n"),
            {"sqlite_files"},
        ),
    ],
    ids=["cycle", "lazy-import", "sqlite"],
)
def test_copy_edit_changes_only_its_axes(
    copy_root: Path,
    capsys: Capsys,
    rel: str,
    edit: Callable[[Path], None],
    axes: set[str],
) -> None:
    before = checker.measure(copy_root)
    edit(copy_root / "src" / "ante" / rel)
    after = checker.measure(copy_root)
    code, output = _run(copy_root, capsys)
    assert code == 1, output
    assert _changed_axes(before, after) == axes
    if rel == "eventbus/bus.py":
        assert set(after["edges"]) - set(before["edges"]) == {"eventbus->rule"}
