"""Prose budget check tests (#2535)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_budget() -> ModuleType:
    script_path = REPO_ROOT / "scripts" / "check_prose_budget.py"
    spec = importlib.util.spec_from_file_location("check_prose_budget", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load prose budget check: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


budget = _load_budget()


def _write(root: Path, rel: str, lines: int, newline: bytes = b"\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(b"line" + newline for _ in range(lines)))
    return path


def _make_tree(root: Path) -> int:
    """Create one file per measured pattern and return the total line count."""
    _write(root, ".agent/commands/cmd.md", 3)
    _write(root, ".agent/agents/agent.md", 2)
    _write(root, ".agent/skills/skill.md", 4)
    _write(root, "AGENTS.md", 5)
    _write(root, "docs/runbooks/01-dev.md", 6)
    _write(root, "docs/runbooks/README.md", 1)
    return 3 + 2 + 4 + 5 + 6 + 1


def _set_baseline(root: Path, value: str) -> None:
    path = root / ".agent" / "prose-baseline.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


Capsys = pytest.CaptureFixture[str]


def _run(root: Path, capsys: Capsys) -> tuple[int, str]:
    code = budget.main(["--root", str(root)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_equal_baseline_passes(tmp_path: Path, capsys: Capsys) -> None:
    total = _make_tree(tmp_path)
    _set_baseline(tmp_path, f"{total}\n")

    code, _ = _run(tmp_path, capsys)

    assert code == 0


def test_added_line_fails_with_both_numbers(tmp_path: Path, capsys: Capsys) -> None:
    total = _make_tree(tmp_path)
    _set_baseline(tmp_path, f"{total}\n")
    _write(tmp_path, ".agent/skills/skill.md", 5)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert f"{total + 1} lines" in message
    assert f"baseline {total}" in message


def test_removed_line_without_baseline_update_fails(
    tmp_path: Path, capsys: Capsys
) -> None:
    total = _make_tree(tmp_path)
    _set_baseline(tmp_path, f"{total}\n")
    _write(tmp_path, "docs/runbooks/01-dev.md", 5)

    code, message = _run(tmp_path, capsys)

    assert code == 1
    assert f"{total - 1} lines" in message
    assert f"baseline {total}" in message
    assert "prose-baseline.txt" in message


def test_removed_line_with_baseline_update_passes(
    tmp_path: Path, capsys: Capsys
) -> None:
    total = _make_tree(tmp_path)
    _write(tmp_path, "docs/runbooks/01-dev.md", 5)
    _set_baseline(tmp_path, f"{total - 1}\n")

    code, _ = _run(tmp_path, capsys)

    assert code == 0


def test_missing_baseline_exits_2(tmp_path: Path, capsys: Capsys) -> None:
    _make_tree(tmp_path)

    code, message = _run(tmp_path, capsys)

    assert code == 2
    assert "prose-baseline.txt" in message


@pytest.mark.parametrize(
    "content", ["", "abc\n", "12 lines\n", "-3\n", "1.5\n", "\u0661\u0662\n"]
)
def test_malformed_baseline_exits_2(
    tmp_path: Path, capsys: Capsys, content: str
) -> None:
    _make_tree(tmp_path)
    _set_baseline(tmp_path, content)

    code, _ = _run(tmp_path, capsys)

    assert code == 2


def test_files_outside_targets_are_ignored(tmp_path: Path) -> None:
    total = _make_tree(tmp_path)
    _write(tmp_path, "docs/runbooks/archive/x.md", 10)
    _write(tmp_path, "docs/specs/x.md", 10)
    _write(tmp_path, "docs/decisions/x.md", 10)
    _write(tmp_path, "docs/runbooks/notes.md", 10)
    _write(tmp_path, ".agent/commands/nested/deep.md", 10)

    assert budget.measure(tmp_path) == total


def test_hidden_files_and_symlinks_are_ignored(tmp_path: Path) -> None:
    total = _make_tree(tmp_path)
    _write(tmp_path, ".agent/skills/.hidden.md", 10)
    (tmp_path / ".agent" / "commands" / "link.md").symlink_to(
        tmp_path / ".agent" / "skills" / "skill.md"
    )
    (tmp_path / "CLAUDE.md").symlink_to(tmp_path / "AGENTS.md")

    assert budget.measure(tmp_path) == total


def test_symlinked_agents_md_is_not_counted(tmp_path: Path) -> None:
    total = _make_tree(tmp_path)
    agents = tmp_path / "AGENTS.md"
    real = tmp_path / "REAL.md"
    agents.rename(real)
    agents.symlink_to(real)

    assert budget.measure(tmp_path) == total - 5


def test_crlf_lines_count_once(tmp_path: Path) -> None:
    _write(tmp_path, "docs/runbooks/02-crlf.md", 7, newline=b"\r\n")

    assert budget.measure(tmp_path) == 7


def test_missing_trailing_newline_matches_wc(tmp_path: Path) -> None:
    path = tmp_path / "AGENTS.md"
    path.write_bytes(b"a\nb\nc")

    assert budget.measure(tmp_path) == 2


@pytest.mark.parametrize(
    ("text", "expected"), [("0", 0), ("12\n", 12), ("  7 \n\n", 7)]
)
def test_parse_baseline_reads_one_number(text: str, expected: int) -> None:
    assert budget.parse_baseline(text) == expected


@pytest.mark.parametrize("text", ["", "abc\n", "12 lines\n", "-3\n", "1.5\n", "١٢\n"])
def test_parse_baseline_rejects_malformed_text(text: str) -> None:
    with pytest.raises(budget.BaselineError, match="must hold one non-negative"):
        budget.parse_baseline(text)
