"""Comment check tests (#2539)."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_comments.py"
    spec = importlib.util.spec_from_file_location("check_comments", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load comment check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

Capsys = pytest.CaptureFixture[str]


def _write_source(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_baseline(root: Path, data: object) -> None:
    path = root / "scripts" / "comment_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _baseline(
    comments: dict[str, int] | None = None,
    history: dict[str, int] | None = None,
    excess: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "comments": comments or {},
        "docstring_history": history or {},
        "docstring_excess": excess or {},
    }


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _comments(text: str) -> int:
    return checker.count_comments(text.encode("utf-8"))


def _history(text: str) -> int:
    return checker.count_history_lines(text.encode("utf-8"))


def _spans(text: str) -> list[tuple[int, int]]:
    return checker.docstring_spans(ast.parse(text))


def test_standalone_comment_is_counted() -> None:
    assert _comments("# 설명\nx = 1\n") == 1


def test_inline_comment_is_counted() -> None:
    assert _comments("x = 1  # 설명\n") == 1


@pytest.mark.parametrize(
    "source",
    [
        "x = '# not a comment'\n",
        'x = """\n# not a comment\n"""\n',
        "x = f'{1} # not a comment'\n",
    ],
)
def test_hash_inside_string_is_not_a_comment(source: str) -> None:
    assert _comments(source) == 0


@pytest.mark.parametrize(
    "source",
    [
        "import os  # noqa: F401\n",
        "import os  # noqa: F401, E501\n",
        "x: int = 'a'  # type: ignore[assignment]\n",
        "x: int = 'a'  # type: ignore[assignment, arg-type]\n",
        "if x:  # pragma: no cover\n    pass\n",
        "#!/usr/bin/env python3\nx = 1\n",
        "x = 1  # type: ignore[assignment]  # noqa: E501\n",
        "x = 1  # noqa: E501 # pragma: no cover\n",
    ],
)
def test_allow_list_passes(source: str) -> None:
    assert _comments(source) == 0


def test_shebang_only_allowed_on_first_line() -> None:
    assert _comments("x = 1\n#!/usr/bin/env python3\n") == 1


@pytest.mark.parametrize(
    "source",
    [
        "import os  # noqa\n",
        "x: int = 'a'  # type: ignore\n",
        "import os  # noqa: F401 — 재수출\n",
        "import os  # 재수출  # noqa: F401\n",
        "x = 1  # pragma: no cover because\n",
    ],
)
def test_directive_without_code_or_with_text_is_counted(source: str) -> None:
    assert _comments(source) == 1


@pytest.mark.parametrize(
    "line",
    [
        "Fixes #1234.",
        "Refs the old issue.",
        "attempt 3 fixed this.",
        "Attempt-2 changed it.",
        "Codex review said so.",
        "Finding P2 here.",
        "Two findings remain.",
        "SPLIT-4 owns this.",
    ],
)
def test_docstring_history_forms_are_counted(line: str) -> None:
    source = f'def f():\n    """Summary.\n\n    {line}\n    """\n'
    assert _history(source) == 1


def test_docstring_history_counts_lines_not_matches() -> None:
    source = '"""#1234 Refs codex finding SPLIT-1 attempt 2."""\n'
    assert _history(source) == 1


@pytest.mark.parametrize("owner", ["module", "class", "def", "async def"])
def test_docstring_owners(owner: str) -> None:
    if owner == "module":
        source = '"""See #1234."""\n'
    elif owner == "class":
        source = 'class C:\n    """See #1234."""\n'
    else:
        source = f'{owner} f():\n    """See #1234."""\n'
    assert _history(source) == 1


@pytest.mark.parametrize(
    "source",
    [
        'x = "See #1234 and Refs and codex"\n',
        'def f():\n    return "Finding attempt 2 SPLIT-3"\n',
        'print("See #1234")\n',
        'f"See #1234 {x}"\n',
        'b"See #1234"\n',
        "# See #1234\nx = 1\n",
        'def f():\n    """No history in #12 or Refsheet or attempts."""\n',
    ],
)
def test_non_docstring_or_non_matching_text_is_not_history(source: str) -> None:
    assert _history(source) == 0


@pytest.mark.parametrize(
    "source",
    [
        'def f():\n    x = 1\n    """See #1234."""\n',
        'class C:\n    x: int = 1\n    """See #1234."""\n',
        'x = 1\n"""See #1234."""\n',
        'if x:\n    """See #1234."""\n',
    ],
)
def test_string_statement_in_body_is_counted_as_docstring(source: str) -> None:
    assert _history(source) == 1
    assert len(_spans(source)) == 1


def test_docstring_spans_cover_every_string_statement() -> None:
    source = (
        '"""Module."""\n'
        "class C:\n"
        '    """Class\n'
        "\n"
        '    body."""\n'
        "    def m(self):\n"
        '        """Method\n'
        '        doc."""\n'
        "        x = 1\n"
        '        """mid-body\n'
        '        string."""\n'
        '        y = "not a statement"\n'
    )
    assert _spans(source) == [(1, 1), (3, 5), (7, 8), (10, 11)]


def _tree(root: Path) -> dict[str, Any]:
    _write_source(
        root,
        "src/ante/a.py",
        '"""Refs #1234."""\n# one\nx = 1  # two\n',
    )
    _write_source(root, "src/ante/sub/b.py", "y = 1  # three\n")
    _write_source(root, "src/ante/clean.py", "z = 1\n")
    _write_source(root, "src/other/c.py", "# outside target\n")
    _write_source(root, "tests/d.py", "# outside target\n")
    return _baseline(
        comments={"src/ante/a.py": 2, "src/ante/sub/b.py": 1},
        history={"src/ante/a.py": 1},
    )


def test_measure_uses_posix_paths_and_skips_zero_files(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = checker.measure(tmp_path)

    assert result.comments == {"src/ante/a.py": 2, "src/ante/sub/b.py": 1}
    assert result.docstring_history == {"src/ante/a.py": 1}


def test_equal_baseline_passes(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))

    code, _ = _run(tmp_path, capsys)

    assert code == 0


def test_added_comment_fails_with_path_and_alternatives(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/sub/b.py", "y = 1  # three\n# four\n")

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "src/ante/sub/b.py: actual 2, baseline 1" in message
    assert "함수로 추출한다" in message
    assert "assert" in message
    assert "커밋 메시지" in message
    assert "기준선의 키를 새 경로로 옮긴다" in message


def test_comment_in_new_file_fails(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/new.py", "# new\n")

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "src/ante/new.py: actual 1, baseline 0" in message


def test_removed_comment_without_baseline_update_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/a.py", '"""Refs #1234."""\nx = 1  # two\n')

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "src/ante/a.py: actual 1, baseline 2" in message
    assert "낮춘다" in message
    assert "함수로 추출한다" not in message
    assert "새 경로로 옮긴다" not in message


def test_file_dropping_to_zero_asks_to_remove_key(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/sub/b.py", "y = 1\n")

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "'src/ante/sub/b.py' 키를 지운다" in message


def test_history_increase_fails(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/clean.py", '"""Codex said."""\nz = 1\n')

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_history\tsrc/ante/clean.py: actual 1, baseline 0" in message
    assert "커밋 메시지" in message


def test_longer_docstring_within_limit_passes(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/clean.py", '"""Doc\n\nmore."""\nz = 1\n')

    code, message = _run(tmp_path, capsys)

    assert code == 0, message
    assert "docstring lines" not in message


def test_empty_objects_are_valid(tmp_path: Path, capsys: Capsys) -> None:
    _write_source(tmp_path, "src/ante/clean.py", "z = 1\n")
    _write_baseline(tmp_path, _baseline())

    code, _ = _run(tmp_path, capsys)

    assert code == 0


def test_missing_baseline_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "comment_baseline.json" in message


def test_broken_json_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path)
    path = tmp_path / "scripts" / "comment_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    code, _ = _run(tmp_path, capsys)

    assert code == 2


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.pop("comments"), id="missing-key"),
        pytest.param(lambda d: d.update(extra={}), id="extra-key"),
        pytest.param(lambda d: d["comments"].update({"src/ante/a.py": 0}), id="zero"),
        pytest.param(lambda d: d["comments"].update({"src/ante/a.py": -1}), id="neg"),
        pytest.param(
            lambda d: d["comments"].update({"src/ante/a.py": True}), id="bool"
        ),
        pytest.param(
            lambda d: d["docstring_history"].update({"src/ante/a.py": 1.0}),
            id="float",
        ),
        pytest.param(
            lambda d: d["docstring_history"].update({"src/ante/a.py": "1"}),
            id="string",
        ),
        pytest.param(lambda d: d.update(comments=[]), id="comments-not-object"),
        pytest.param(lambda d: d.update(docstring_lines=0), id="legacy-lines-key"),
        pytest.param(lambda d: d.update(docstring_excess=[]), id="excess-not-object"),
        pytest.param(
            lambda d: d["docstring_excess"].update({"src/ante/a.py": 0}),
            id="excess-zero",
        ),
        pytest.param(
            lambda d: d["docstring_excess"].update({"src/ante/a.py": -1}),
            id="excess-neg",
        ),
        pytest.param(
            lambda d: d["docstring_excess"].update({"src/ante/a.py": 1.0}),
            id="excess-float",
        ),
        pytest.param(
            lambda d: d["docstring_excess"].update({"src/ante/a.py": "1"}),
            id="excess-string",
        ),
        pytest.param(
            lambda d: d["docstring_excess"].update({"src/ante/a.py": True}),
            id="excess-bool",
        ),
    ],
)
def test_malformed_baseline_exits_2(
    tmp_path: Path, capsys: Capsys, mutate: Callable[[dict[str, Any]], object]
) -> None:
    baseline = _tree(tmp_path)
    mutate(baseline)
    _write_baseline(tmp_path, baseline)

    code, _ = _run(tmp_path, capsys)

    assert code == 2


def test_baseline_not_an_object_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path)
    _write_baseline(tmp_path, [1, 2])

    code, _ = _run(tmp_path, capsys)

    assert code == 2


def test_parse_baseline_matches_read_baseline(tmp_path: Path) -> None:
    baseline = _tree(tmp_path)
    _write_baseline(tmp_path, baseline)
    text = (tmp_path / "scripts" / "comment_baseline.json").read_text("utf-8")

    parsed = checker.parse_baseline(text)

    assert parsed == checker.read_baseline(tmp_path)
    assert parsed == checker.Measurement(
        baseline["comments"], baseline["docstring_history"], {}
    )


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("{not json", id="broken-json"),
        pytest.param("[1, 2]", id="not-object"),
        pytest.param('{"comments": {}, "docstring_history": {}}', id="missing-key"),
        pytest.param(
            '{"comments": {"a": 0}, "docstring_history": {}, "docstring_excess": {}}',
            id="zero-count",
        ),
        pytest.param(
            '{"comments": {}, "docstring_history": {}, "docstring_excess": {}, '
            '"docstring_lines": 0}',
            id="legacy-lines-key",
        ),
    ],
)
def test_parse_baseline_rejects_malformed_text(text: str) -> None:
    with pytest.raises(checker.CheckError):
        checker.parse_baseline(text)


def test_unparsable_source_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/broken.py", "def f(:\n")

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "src/ante/broken.py" in message


def test_moved_file_asks_to_move_baseline_key(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    (tmp_path / "src/ante/sub/b.py").rename(tmp_path / "src/ante/sub/moved.py")

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "src/ante/sub/moved.py: actual 1, baseline 0" in message
    assert "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다" in message


def test_unreadable_source_exits_2(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    target = tmp_path / "src/ante/sub/b.py"
    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        if self == target:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "src/ante/sub/b.py" in message
    assert "PermissionError" in message


def test_too_deep_source_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(
        tmp_path, "src/ante/deep.py", "x = " + "+".join(["1"] * 200_000) + "\n"
    )

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "src/ante/deep.py" in message


def test_parser_stack_overflow_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/stack.py", "x = " + "-" * 100_000 + "1\n")

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "src/ante/stack.py" in message


def test_old_python_exits_2(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    monkeypatch.setattr(checker, "MIN_PYTHON", (99, 0))

    code, _ = _run(tmp_path, capsys)

    assert code == 2


class _InjectedError(Exception):
    pass


def _raise_injected(*_args: object) -> None:
    raise _InjectedError("injected")


@pytest.mark.parametrize("function", ["read_baseline", "measure"])
def test_any_exception_exits_2(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch, function: str
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    monkeypatch.setattr(checker, function, _raise_injected)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "_InjectedError" in message


def _doc(lines: int, indent: str = "    ") -> str:
    if lines == 1:
        return f'{indent}"""Doc."""\n'
    body = "".join(f"{indent}line {i}\n" for i in range(lines - 2))
    return f'{indent}"""Doc.\n{body}{indent}"""\n'


def _last(source: str) -> Any:
    return checker.classify_docstrings(ast.parse(source))[-1]


OWNER_SOURCES: dict[str, Callable[[int], str]] = {
    "private": lambda n: "def _f():\n" + _doc(n),
    "public": lambda n: "def f():\n" + _doc(n),
    "async-public": lambda n: "async def f():\n" + _doc(n),
    "class": lambda n: "class C:\n" + _doc(n),
    "module": lambda n: _doc(n, ""),
    "module-attribute": lambda n: '"""M."""\nx = 1\n' + _doc(n, ""),
    "module-annotated-attribute": lambda n: '"""M."""\nx: int\n' + _doc(n, ""),
    "class-attribute": lambda n: 'class C:\n    """C."""\n    x: int = 1\n' + _doc(n),
    "function-after-assign": lambda n: 'def f():\n    """F."""\n    x = 1\n' + _doc(n),
    "module-not-after-assign": lambda n: '"""M."""\nimport os\n' + _doc(n, ""),
    "class-not-after-assign": lambda n: (
        'class C:\n    """C."""\n    def m(self):\n        """M."""\n' + _doc(n)
    ),
}
OWNER_EXPECTED = {
    "private": ("private", 1),
    "public": ("public", 10),
    "async-public": ("public", 10),
    "class": ("class", 10),
    "module": ("module", 3),
    "module-attribute": ("attribute", 3),
    "module-annotated-attribute": ("attribute", 3),
    "class-attribute": ("attribute", 3),
    "function-after-assign": ("other", 0),
    "module-not-after-assign": ("other", 0),
    "class-not-after-assign": ("other", 0),
}
LIMIT_CASES = [
    pytest.param(case, n, id=f"{case}-{n}")
    for case, (_, limit) in OWNER_EXPECTED.items()
    for n in (limit - 1, limit, limit + 1, limit + 3)
    if n >= 1
]


@pytest.mark.parametrize(("case", "lines"), LIMIT_CASES)
def test_owner_limit_and_excess(case: str, lines: int) -> None:
    owner, limit = OWNER_EXPECTED[case]
    source = OWNER_SOURCES[case](lines)

    doc = _last(source)

    assert (doc.owner, doc.limit, doc.lines) == (owner, limit, lines)
    assert doc.excess == max(0, lines - limit)
    oversized = checker.oversized_docstrings(source.encode())
    assert sum(d.excess for d in oversized) == max(0, lines - limit)


@pytest.mark.parametrize(
    "decorator",
    [
        "@cli.command()",
        '@group.command("name")',
        "@click.group()",
        "@x.command",
        "@x.group",
        "@a.b.command(name='x', help='y')",
        pytest.param("@functools.wraps(g)\n@cli.command()", id="click-not-first"),
        pytest.param("@cli.command()\n@click.option('--x')", id="click-not-last"),
        pytest.param(
            "@staticmethod\n@cli.group()\n@click.pass_context", id="click-middle"
        ),
    ],
)
@pytest.mark.parametrize("name", ["run", "_run"])
def test_click_command_has_no_limit(decorator: str, name: str) -> None:
    source = f"{decorator}\ndef {name}():\n" + _doc(40)

    doc = _last(source)

    assert (doc.owner, doc.limit, doc.lines, doc.excess) == ("click", None, 40, 0)
    assert checker.oversized_docstrings(source.encode()) == []


@pytest.mark.parametrize(
    "decorator",
    ["@command", "@command()", "@cli.commands()", "@functools.wraps(g)"],
)
def test_non_click_decorator_keeps_function_owner(decorator: str) -> None:
    assert _last(f"{decorator}\ndef _run():\n" + _doc(1)).owner == "private"
    assert _last(f"{decorator}\ndef run():\n" + _doc(1)).owner == "public"


@pytest.mark.parametrize(
    ("source", "owner", "name", "excess"),
    [
        pytest.param(
            "class C:\n    def __init__(self):\n" + _doc(11, "        "),
            "public",
            "C.__init__",
            1,
            id="dunder-is-public",
        ),
        pytest.param(
            "def __getattr__(name):\n" + _doc(11),
            "public",
            "__getattr__",
            1,
            id="module-dunder-is-public",
        ),
        pytest.param(
            "class C:\n    def _private(self):\n" + _doc(2, "        "),
            "private",
            "C._private",
            1,
            id="private-method",
        ),
        pytest.param(
            "class C:\n    def __mangled(self):\n" + _doc(2, "        "),
            "private",
            "C.__mangled",
            1,
            id="name-mangled-is-private",
        ),
        pytest.param(
            'def f():\n    """F."""\n    def _inner():\n' + _doc(2, "        "),
            "private",
            "f._inner",
            1,
            id="nested-private",
        ),
        pytest.param(
            'def f():\n    """F."""\n    def inner():\n' + _doc(11, "        "),
            "public",
            "f.inner",
            1,
            id="nested-public",
        ),
        pytest.param(
            'class _P:\n    """P."""\n    def m(self):\n' + _doc(11, "        "),
            "public",
            "_P.m",
            1,
            id="private-class-public-method",
        ),
        pytest.param(
            "class _P:\n" + _doc(11),
            "class",
            "_P",
            1,
            id="private-class",
        ),
        pytest.param(
            'class C:\n    """C."""\n    x, y = 1, 2\n' + _doc(4),
            "attribute",
            "C.(x,y)",
            1,
            id="attribute-name",
        ),
    ],
)
def test_owner_and_name(source: str, owner: str, name: str, excess: int) -> None:
    doc = _last(source)

    assert (doc.owner, doc.name, doc.excess) == (owner, name, excess)


NESTED_BODIES = (
    '"""M."""\n'
    "x = 1\n"
    '"""attr."""\n'
    "if x:\n"
    '    """if."""\n'
    "    y = 1\n"
    '    """after assign in if."""\n'
    "else:\n"
    '    """else."""\n'
    "for i in x:\n"
    '    """for."""\n'
    "while x:\n"
    '    """while."""\n'
    "with x:\n"
    '    """with."""\n'
    "try:\n"
    '    """try."""\n'
    "except E:\n"
    '    """except."""\n'
    "finally:\n"
    '    """finally."""\n'
    "match x:\n"
    "    case 1:\n"
    '        """case."""\n'
    "def f():\n"
    "    class D:\n"
    '        """D."""\n'
    "        z = 1\n"
    '        """D.z."""\n'
)


def test_every_string_statement_gets_an_owner() -> None:
    tree = ast.parse(NESTED_BODIES)

    docs = checker.classify_docstrings(tree)

    assert [(d.start, d.end) for d in docs] == checker.docstring_spans(tree)
    assert [d.owner for d in docs] == [
        "module",
        "attribute",
        *["other"] * 10,
        "class",
        "attribute",
    ]
    assert [d.name for d in docs][-2:] == ["f.D", "f.D.z"]


def test_classification_covers_repository_docstrings() -> None:
    files = checker.target_files(REPO_ROOT)
    assert files
    for path in files:
        tree = ast.parse(path.read_bytes())
        spans = [(d.start, d.end) for d in checker.classify_docstrings(tree)]
        assert spans == checker.docstring_spans(tree), path


def _excess_tree(root: Path, private_lines: int = 3) -> dict[str, Any]:
    _write_source(
        root,
        "src/ante/m.py",
        '"""Module."""\n\n\ndef _f():\n'
        + _doc(private_lines)
        + '\n\ndef g():\n    """G."""\n',
    )
    _write_source(root, "src/ante/other.py", "def _h():\n" + _doc(2))
    measured = checker.measure(root)
    return _baseline(excess=measured.docstring_excess)


def test_measure_sums_excess_per_file(tmp_path: Path) -> None:
    _excess_tree(tmp_path, private_lines=4)
    _write_source(tmp_path, "src/ante/clean.py", 'def _ok():\n    """Ok."""\n')

    result = checker.measure(tmp_path)

    assert result.docstring_excess == {"src/ante/m.py": 3, "src/ante/other.py": 1}
    assert [(d.start, d.owner, d.name) for d in result.oversized["src/ante/m.py"]] == [
        (5, "private", "_f")
    ]


def test_equal_excess_passes(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _excess_tree(tmp_path))

    code, message = _run(tmp_path, capsys)

    assert code == 0, message
    assert "3 docstring excess lines" in message


def test_private_docstring_growth_fails_and_lists_docstrings(
    tmp_path: Path, capsys: Capsys
) -> None:
    baseline = _excess_tree(tmp_path, private_lines=1)
    _write_source(
        tmp_path,
        "src/ante/m.py",
        '"""Module."""\n\n\ndef _f():\n' + _doc(2) + '\n\ndef g():\n    """G."""\n',
    )
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_excess\tsrc/ante/m.py: actual 1, baseline 0 (+1)" in message
    assert "  src/ante/m.py:5 private _f 2>1" in message
    assert "src/ante/other.py:" not in message
    assert "독스트링을 줄인다" in message
    assert "불변식은 테스트로 옮긴다" in message
    assert "함수로 추출한다" not in message
    assert message.count("기준선의 키를 새 경로로 옮긴다") == 1
    assert "docstring_lines" not in message


def test_excess_growth_lists_every_oversized_docstring_of_the_file(
    tmp_path: Path, capsys: Capsys
) -> None:
    baseline = _excess_tree(tmp_path)
    _write_source(
        tmp_path,
        "src/ante/m.py",
        _doc(5, "") + "\n\ndef _f():\n" + _doc(3) + "\n\nclass C:\n" + _doc(12),
    )
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_excess\tsrc/ante/m.py: actual 6, baseline 2 (+4)" in message
    assert "  src/ante/m.py:1 module <module> 5>3" in message
    assert "  src/ante/m.py:9 private _f 3>1" in message
    assert "  src/ante/m.py:15 class C 12>10" in message


def test_comment_and_excess_growth_give_move_hint_once(
    tmp_path: Path, capsys: Capsys
) -> None:
    baseline = _excess_tree(tmp_path, private_lines=1)
    _write_source(
        tmp_path,
        "src/ante/m.py",
        '"""Module."""\n\n\ndef _f():  # note\n'
        + _doc(2)
        + '\n\ndef g():\n    """G."""\n',
    )
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "comments\tsrc/ante/m.py: actual 1, baseline 0 (+1)" in message
    assert "docstring_excess\tsrc/ante/m.py: actual 1, baseline 0 (+1)" in message
    assert "함수로 추출한다" in message
    assert "독스트링을 줄인다" in message
    assert message.count("기준선의 키를 새 경로로 옮긴다") == 1


def test_shortened_docstring_without_lowering_baseline_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    baseline = _excess_tree(tmp_path, private_lines=4)
    _write_source(tmp_path, "src/ante/m.py", '"""Module."""\n\n\ndef _f():\n' + _doc(3))
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_excess\tsrc/ante/m.py: actual 2, baseline 3 (-1)" in message
    assert "docstring_excess['src/ante/m.py']를 2로 낮춘다" in message
    assert "상한을 넘는 독스트링" not in message


def test_docstring_within_limit_asks_to_remove_key(
    tmp_path: Path, capsys: Capsys
) -> None:
    baseline = _excess_tree(tmp_path)
    _write_source(tmp_path, "src/ante/other.py", 'def _h():\n    """H."""\n')
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_excess에서 'src/ante/other.py' 키를 지운다" in message


def test_baseline_without_excess_key_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    baseline = _tree(tmp_path)
    del baseline["docstring_excess"]
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "missing ['docstring_excess']" in message


def test_oversized_docstring_on_empty_excess_baseline_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_source(tmp_path, "src/ante/clean.py", 'def _ok():\n    """Ok."""\n')
    _write_baseline(tmp_path, _baseline())
    assert _run(tmp_path, capsys)[0] == 0
    _write_source(tmp_path, "src/ante/new.py", "def _f():\n" + _doc(2))

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_excess\tsrc/ante/new.py: actual 1, baseline 0 (+1)" in message
    assert "  src/ante/new.py:2 private _f 2>1" in message
