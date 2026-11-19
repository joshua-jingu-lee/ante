"""Comment check tests (#2539)."""

from __future__ import annotations

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
    lines: int = 0,
) -> dict[str, Any]:
    return {
        "comments": comments or {},
        "docstring_history": history or {},
        "docstring_lines": lines,
    }


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _comments(text: str) -> int:
    return checker.count_comments(text.encode("utf-8"))


def _history(text: str) -> int:
    return checker.measure_docstrings(text.encode("utf-8"))[0]


def _docstring_lines(text: str) -> int:
    return checker.measure_docstrings(text.encode("utf-8"))[1]


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
        'def f():\n    x = 1\n    """See #1234."""\n',
        'def f():\n    return "Finding attempt 2 SPLIT-3"\n',
        "# See #1234\nx = 1\n",
        'def f():\n    """No history in #12 or Refsheet or attempts."""\n',
    ],
)
def test_non_docstring_or_non_matching_text_is_not_history(source: str) -> None:
    assert _history(source) == 0


def test_docstring_total_lines() -> None:
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
        '        """not a docstring"""\n'
    )
    assert _docstring_lines(source) == 1 + 3 + 2


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
        lines=1,
    )


def test_measure_uses_posix_paths_and_skips_zero_files(tmp_path: Path) -> None:
    _tree(tmp_path)

    result = checker.measure(tmp_path)

    assert result.comments == {"src/ante/a.py": 2, "src/ante/sub/b.py": 1}
    assert result.docstring_history == {"src/ante/a.py": 1}
    assert result.docstring_lines == 1


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


def test_docstring_lines_increase_asks_to_shrink_others(
    tmp_path: Path, capsys: Capsys
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/clean.py", '"""Doc\n\nmore."""\nz = 1\n')

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_lines: actual 4, baseline 1" in message
    assert "다른 독스트링을 그만큼 줄인다" in message


def test_docstring_lines_decrease_fails(tmp_path: Path, capsys: Capsys) -> None:
    baseline = _tree(tmp_path)
    baseline["docstring_lines"] = 5
    _write_baseline(tmp_path, baseline)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "docstring_lines를 1로 낮춘다" in message


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
        pytest.param(lambda d: d.update(docstring_lines=-1), id="lines-negative"),
        pytest.param(lambda d: d.update(docstring_lines=True), id="lines-bool"),
        pytest.param(lambda d: d.update(docstring_lines=1.0), id="lines-float"),
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


def test_unparsable_source_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    _write_source(tmp_path, "src/ante/broken.py", "def f(:\n")

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "src/ante/broken.py" in message


def test_old_python_exits_2(
    tmp_path: Path, capsys: Capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_baseline(tmp_path, _tree(tmp_path))
    monkeypatch.setattr(checker.sys, "version_info", (3, 12, 9))

    code, _ = _run(tmp_path, capsys)

    assert code == 2


def test_repository_baseline_matches_source(capsys: Capsys) -> None:
    code, message = _run(REPO_ROOT, capsys)

    assert code == 0, message
