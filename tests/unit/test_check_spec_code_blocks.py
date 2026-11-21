"""Spec code block ratchet check tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_spec_code_blocks.py"
    spec = importlib.util.spec_from_file_location("check_spec_code_blocks", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load spec code block check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()

Capsys = pytest.CaptureFixture[str]


def _counts(text: str) -> tuple[int, int, int]:
    counts = checker.count_text(text)
    return counts.python, counts.sql, counts.py_line_refs


def _spec(root: Path, rel: str, text: str | bytes) -> Path:
    path = root / "docs" / "specs" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _baseline(root: Path, content: str | dict[str, object]) -> None:
    path = root / "scripts" / "spec_code_block_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        content = json.dumps(content, indent=2) + "\n"
    path.write_text(content, encoding="utf-8")


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = checker.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


TREE = (
    "# spec\n"
    "```python\n"
    "class A:\n"
    "    x: int\n"
    "```\n"
    "```sql\n"
    "CREATE TABLE t (id INTEGER);\n"
    "```\n"
    "see `src/ante/a.py:10` and b.py:3-4\n"
)
TREE_COUNTS = {"python": 2, "sql": 1, "py_line_refs": 2}


def _tree(root: Path) -> None:
    _spec(root, "mod/a.md", TREE)


# ── 정의역 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "fence",
    [
        pytest.param("```", id="indent-0"),
        pytest.param("  ```", id="indent-2"),
        pytest.param("      ```", id="indent-6"),
        pytest.param("\t```", id="tab"),
        pytest.param("~~~", id="tilde"),
        pytest.param("````", id="backtick-4"),
    ],
)
def test_opening_fence_any_indent_backtick_or_tilde(fence: str) -> None:
    text = f"{fence}python\nx = 1\n{fence}\n"
    assert _counts(text) == (1, 0, 0)


def test_backtick_in_backtick_info_string_is_not_fence() -> None:
    assert _counts("```python `x` a.py:1\nx = 1\n") == (0, 0, 1)
    assert _counts("~~~python `x`\nx = 1\n~~~\n") == (1, 0, 0)


@pytest.mark.parametrize(
    ("closing", "closes"),
    [
        pytest.param("```", True, id="same"),
        pytest.param("`````", True, id="longer"),
        pytest.param("```  \t", True, id="trailing-space"),
        pytest.param("   ```", True, id="indented"),
        pytest.param("``", False, id="shorter"),
        pytest.param("~~~", False, id="other-char"),
        pytest.param("```x", False, id="trailing-text"),
        pytest.param("```python", False, id="info-string"),
    ],
)
def test_closing_line(closing: str, closes: bool) -> None:
    text = f"```python\nx = 1\n{closing}\n"
    if closes:
        assert _counts(text) == (1, 0, 0)
    else:
        with pytest.raises(checker.CheckError):
            checker.count_text(text)
        assert _counts(text + "```\n") == (2, 0, 0)


def test_closing_line_must_be_as_long_as_opening() -> None:
    assert _counts("````python\nx\n```\n````\n") == (2, 0, 0)


def test_fence_lines_are_not_counted() -> None:
    assert _counts("```python\na\nb\nc\n```\n") == (3, 0, 0)


def test_fence_shaped_line_inside_block_is_content() -> None:
    text = "````python\na\n```sql\nb\n```\n````\n"
    assert _counts(text) == (4, 0, 0)
    assert _counts("~~~python\n```\nx\n```\n~~~\n") == (3, 0, 0)


def test_empty_block_counts_zero() -> None:
    assert _counts("```python\n```\n```sql\n```\n") == (0, 0, 0)


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        pytest.param("python", (1, 0, 0), id="python"),
        pytest.param("sql", (0, 1, 0), id="sql"),
        pytest.param("Python", (1, 0, 0), id="upper"),
        pytest.param("SQL", (0, 1, 0), id="upper-sql"),
        pytest.param(" python title=x", (1, 0, 0), id="attribute"),
        pytest.param("py", (0, 0, 0), id="alias"),
        pytest.param("python3", (0, 0, 0), id="python3"),
        pytest.param("sqlite", (0, 0, 0), id="sqlite"),
        pytest.param("{.python}", (0, 0, 0), id="braced"),
        pytest.param("", (0, 0, 0), id="none"),
        pytest.param("bash", (0, 0, 0), id="bash"),
    ],
)
def test_language_is_lowercased_first_word(
    info: str, expected: tuple[int, int, int]
) -> None:
    assert _counts(f"```{info}\nx\n```\n") == expected


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("```python\nx = 1\n", id="unclosed"),
        pytest.param(b"# \xff\xfe\n", id="not-utf8"),
    ],
)
def test_unclosed_block_or_non_utf8_exits_2(
    tmp_path: Path, capsys: Capsys, content: str | bytes
) -> None:
    _tree(tmp_path)
    _spec(tmp_path, "mod/bad.md", content)
    _baseline(tmp_path, TREE_COUNTS)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "docs/specs/mod/bad.md" in message


@pytest.mark.parametrize(
    ("line", "refs"),
    [
        pytest.param("a.py:1", 1, id="single"),
        pytest.param("a.py:10-20", 1, id="range"),
        pytest.param("a.py:1,5,9", 3, id="list"),
        pytest.param("a.py:1-3,7,10-12", 3, id="mixed-list"),
        pytest.param("src/ante/x/y.py:12", 1, id="src-prefix"),
        pytest.param("tests/unit/test_y.py:12", 1, id="tests-prefix"),
        pytest.param(".py:3", 1, id="no-path"),
        pytest.param("`src/a.py:12`", 1, id="in-backticks"),
        pytest.param("(see a.py:12)", 1, id="outside-backticks"),
        pytest.param("a.py:1 and b.py:2-3", 2, id="two-tokens"),
        pytest.param("a.py:12, 13", 1, id="comma-space-ends-list"),
        pytest.param("a.py:", 0, id="no-number"),
        pytest.param("a.py:x", 0, id="not-a-number"),
        pytest.param("a.py:١٢", 0, id="non-ascii-digits"),
        pytest.param("a.py 12행", 0, id="prose"),
        pytest.param("`a.py`:12", 0, id="split-by-backtick"),
        pytest.param("a.py:L12", 0, id="L-prefix"),
    ],
)
def test_py_line_reference_counts_each_item(line: str, refs: int) -> None:
    assert _counts(f"{line}\n") == (0, 0, refs)


def test_py_line_reference_inside_block_is_not_counted() -> None:
    text = "```bash\npytest tests/a.py:1\n```\n```\nsrc/b.py:2\n```\nc.py:3\n"
    assert _counts(text) == (0, 0, 1)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("a.md:12", id="md"),
        pytest.param("a.pyi:12", id="pyi"),
        pytest.param("a.py#L12", id="anchor"),
        pytest.param("https://x/a.py#L12-L20", id="url-anchor"),
    ],
)
def test_other_line_references_are_not_counted(line: str) -> None:
    assert _counts(f"{line}\n") == (0, 0, 0)


# ── 대상 파일 ──────────────────────────────────────────────


def test_hidden_symlinked_and_other_files_are_ignored(tmp_path: Path) -> None:
    _tree(tmp_path)
    block = "```python\nx\n```\na.py:1\n"
    _spec(tmp_path, "mod/.hidden.md", block)
    _spec(tmp_path, "mod/notes.txt", block)
    (tmp_path / "docs" / "specs" / "mod" / "link.md").symlink_to(
        tmp_path / "docs" / "specs" / "mod" / "a.md"
    )
    (tmp_path / "docs" / "other.md").write_text(block, encoding="utf-8")

    assert checker.measure(tmp_path).as_dict() == TREE_COUNTS


def test_nested_files_are_summed(tmp_path: Path) -> None:
    _tree(tmp_path)
    _spec(tmp_path, "mod/sub/b.md", "```sql\nx\ny\n```\n")

    assert checker.measure(tmp_path).as_dict() == {
        "python": 2,
        "sql": 3,
        "py_line_refs": 2,
    }


# ── 기준선 비교 ──────────────────────────────────────────────


def test_equal_baseline_passes(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path)
    _baseline(tmp_path, TREE_COUNTS)

    code, message = _run(tmp_path, capsys)

    assert code == 0
    assert "python 2, sql 1, py_line_refs 2" in message


@pytest.mark.parametrize(
    ("addition", "key", "actual"),
    [
        pytest.param("```python\nx = 2\n```\n", "python", 3, id="python-line"),
        pytest.param("```sql\nSELECT 1;\n```\n", "sql", 2, id="sql-line"),
        pytest.param("see `src/x.py:123`\n", "py_line_refs", 3, id="line-ref"),
    ],
)
def test_growth_fails_with_numbers_and_three_paths(
    tmp_path: Path, capsys: Capsys, addition: str, key: str, actual: int
) -> None:
    _tree(tmp_path)
    _spec(tmp_path, "mod/new.md", addition)
    _baseline(tmp_path, TREE_COUNTS)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    want = TREE_COUNTS[key]
    assert f"{key}: actual {actual}, baseline {want} (+{actual - want})" in message
    assert "docs/architecture/generated/" in message
    assert "no line numbers" in message
    assert "raise the baseline" in message
    assert "Gate A" in message
    assert "changing the block's language" in message
    assert "Lower" not in message


def test_shrink_without_baseline_update_fails(tmp_path: Path, capsys: Capsys) -> None:
    _spec(tmp_path, "mod/a.md", TREE.replace("    x: int\n", ""))
    _baseline(tmp_path, TREE_COUNTS)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert "python: actual 1, baseline 2 (-1)" in message
    assert "Lower python to 1." in message
    assert "raise the baseline" not in message


def test_shrink_with_baseline_update_passes(tmp_path: Path, capsys: Capsys) -> None:
    _spec(tmp_path, "mod/a.md", TREE.replace("    x: int\n", ""))
    _baseline(tmp_path, {**TREE_COUNTS, "python": 1})

    code, _ = _run(tmp_path, capsys)

    assert code == 0


def test_missing_baseline_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _tree(tmp_path)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "spec_code_block_baseline.json" in message


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty"),
        pytest.param("{not json", id="not-json"),
        pytest.param("[1, 2, 3]", id="not-object"),
        pytest.param({"python": 2, "sql": 1}, id="key-missing"),
        pytest.param({**TREE_COUNTS, "bash": 0}, id="key-extra"),
        pytest.param({**TREE_COUNTS, "sql": -1}, id="negative"),
        pytest.param({**TREE_COUNTS, "sql": True}, id="bool"),
        pytest.param({**TREE_COUNTS, "sql": 1.0}, id="float"),
        pytest.param({**TREE_COUNTS, "sql": "1"}, id="string"),
        pytest.param({**TREE_COUNTS, "sql": None}, id="null"),
    ],
)
def test_malformed_baseline_exits_2(
    tmp_path: Path, capsys: Capsys, content: str | dict[str, object]
) -> None:
    _tree(tmp_path)
    _baseline(tmp_path, content)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "spec_code_block_baseline.json" in message


def test_parse_baseline_returns_the_three_keys() -> None:
    text = json.dumps({"py_line_refs": 0, "sql": 5, "python": 7})
    assert checker.parse_baseline(text) == {"python": 7, "sql": 5, "py_line_refs": 0}


def test_repository_baseline_has_one_key_per_line() -> None:
    text = (REPO_ROOT / checker.BASELINE_PATH).read_text(encoding="utf-8")
    values = checker.parse_baseline(text)
    assert text == json.dumps(values, indent=2) + "\n"
