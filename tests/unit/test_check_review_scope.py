"""Gate A scope decision script tests (#2534)."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_review_scope.py"


def _load_scope_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_review_scope", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load scope script: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scope = _load_scope_module()


def _git_env() -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.env = _git_env()
        root.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.write("README.md", "# repo\n")
        self.commit("init")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def write(self, rel: str, content: str | bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def mark_base(self) -> None:
        self.base = self.git("rev-parse", "HEAD").strip()

    def check(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", self.base, "--head", "HEAD"],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


SRC = '''"""Module doc."""

import os


def f(x):
    """Function doc."""
    # inline note
    return os.path.join(x, "a")  # trailing note


class C:
    """Class doc."""

    async def g(self):
        """Async doc."""
        return 1
'''


def _with_src(repo: Repo, content: str = SRC) -> None:
    repo.write("src/ante/m.py", content)
    repo.commit("add src")
    repo.mark_base()


# ── 순수 함수 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/a.md", True),
        ("docs/sub/x.png", True),
        (".agent/commands/x.md", True),
        ("guide/cli.md", True),
        ("README.md", True),
        ("docs/한글.md", True),
        ("src/ante/README.md", False),
        ("tests/unit/a.md", False),
        (".github/workflows/ci.yml", False),
        (".claude/settings.json", False),
        ("scripts/x.py", False),
        ("pyproject.toml", False),
        ("documents/a.md", False),
    ],
)
def test_is_doc_path(path: str, expected: bool) -> None:
    assert scope.is_doc_path(path) is expected


def test_ast_compare_ignores_comments_and_docstrings() -> None:
    new = SRC.replace('"""Function doc."""', '"""Changed."""').replace(
        "    # inline note\n", ""
    )
    assert scope.ast_identical_without_docstrings(SRC.encode(), new.encode())


def test_ast_compare_detects_token_change() -> None:
    new = SRC.replace('"a"', '"b"')
    assert not scope.ast_identical_without_docstrings(SRC.encode(), new.encode())


def test_ast_compare_syntax_error_is_not_identical() -> None:
    assert not scope.ast_identical_without_docstrings(b"x = 1\n", b"x = (\n")


def test_ast_compare_bytes_and_fstring_are_not_docstrings() -> None:
    old = b'def f():\n    "doc"\n    return 1\n'
    assert not scope.ast_identical_without_docstrings(
        old, b'def f():\n    b"doc"\n    return 1\n'
    )
    assert not scope.ast_identical_without_docstrings(
        old, b'def f():\n    f"doc"\n    return 1\n'
    )


def test_parse_raw_diff_handles_rename_and_non_ascii() -> None:
    raw = (
        b":100644 100644 aaa bbb R090\0docs/old.md\0docs/\xed\x95\x9c.md\0"
        b":000000 100644 000 ccc A\0src/ante/x.py\0"
    )
    changes = scope.parse_raw_diff(raw)
    assert [c.status for c in changes] == ["R", "A"]
    assert changes[0].old_path == "docs/old.md"
    assert changes[0].path == "docs/한.md"
    assert changes[1].path == "src/ante/x.py"


# ── 리뷰 생략 ──────────────────────────────────────────────


def test_docs_only_skips(repo: Repo) -> None:
    repo.write("docs/a.md", "a\n")
    repo.write(".agent/commands/x.md", "x\n")
    repo.write("guide/g.md", "g\n")
    repo.write("README.md", "# changed\n")
    repo.commit("docs")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verdict: SKIP" in result.stdout


def test_comment_only_change_skips(repo: Repo) -> None:
    _with_src(repo)
    repo.write(
        "src/ante/m.py",
        SRC.replace("    # inline note\n", "").replace("  # trailing note", ""),
    )
    repo.commit("drop comments")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ast-identical\tM\tsrc/ante/m.py" in result.stdout


def test_docstring_only_change_skips(repo: Repo) -> None:
    _with_src(repo)
    repo.write(
        "src/ante/m.py",
        SRC.replace('"""Module doc."""', '"""Other."""')
        .replace('    """Class doc."""\n\n', "")
        .replace('"""Async doc."""', '"""Rewritten\n        across lines."""'),
    )
    repo.commit("docstrings")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr


def test_docs_plus_ast_identical_skips(repo: Repo) -> None:
    _with_src(repo)
    repo.write("src/ante/m.py", SRC.replace("  # trailing note", ""))
    repo.write("docs/a.md", "a\n")
    repo.commit("mixed")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "doc\tA\tdocs/a.md" in result.stdout
    assert "ast-identical\tM\tsrc/ante/m.py" in result.stdout


# ── 리뷰 대상 ──────────────────────────────────────────────


def test_token_change_requires_review(repo: Repo) -> None:
    _with_src(repo)
    repo.write("src/ante/m.py", SRC.replace("return 1", "return 2"))
    repo.commit("token")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tM\tsrc/ante/m.py" in result.stdout


def test_src_file_added_or_deleted_requires_review(repo: Repo) -> None:
    _with_src(repo)
    repo.write("src/ante/new.py", "")
    repo.commit("add")
    assert repo.check().returncode == 1

    repo.git("rm", "-q", "src/ante/new.py")
    repo.commit("drop new")
    repo.mark_base()
    repo.git("rm", "-q", "src/ante/m.py")
    repo.commit("delete")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tD\tsrc/ante/m.py" in result.stdout


def test_tests_change_requires_review(repo: Repo) -> None:
    repo.write("tests/unit/test_x.py", "# only a comment\n")
    repo.write("docs/a.md", "a\n")
    repo.commit("tests")
    assert repo.check().returncode == 1


def test_workflow_change_requires_review(repo: Repo) -> None:
    repo.write(".github/workflows/ci.yml", "name: ci\n")
    repo.commit("wf")
    assert repo.check().returncode == 1


def test_empty_diff_requires_review(repo: Repo) -> None:
    repo.commit("empty")
    result = repo.check()
    assert result.returncode == 1
    assert "empty diff" in result.stdout


def test_rename_doc_to_non_doc_requires_review(repo: Repo) -> None:
    repo.write("docs/moved.md", "line\n" * 20)
    repo.commit("doc")
    repo.mark_base()
    (repo.root / "scripts").mkdir()
    repo.git("mv", "docs/moved.md", "scripts/moved.md")
    repo.commit("rename")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tR\tdocs/moved.md -> scripts/moved.md" in result.stdout


# ── 경계 ──────────────────────────────────────────────


def test_docstring_replaced_by_pass_requires_review(repo: Repo) -> None:
    _with_src(repo, 'def f():\n    """Only doc."""\n')
    repo.write("src/ante/m.py", "def f():\n    pass\n")
    repo.commit("pass")
    assert repo.check().returncode == 1


@pytest.mark.parametrize("replacement", ['b"""doc"""', 'f"""doc"""'])
def test_docstring_to_bytes_or_fstring_requires_review(
    repo: Repo, replacement: str
) -> None:
    _with_src(repo, 'def f():\n    """doc"""\n    return 1\n')
    repo.write("src/ante/m.py", f"def f():\n    {replacement}\n    return 1\n")
    repo.commit("non-docstring")
    assert repo.check().returncode == 1


def test_mode_only_change_requires_review(repo: Repo) -> None:
    _with_src(repo)
    repo.git("update-index", "--chmod=+x", "src/ante/m.py")
    repo.git("commit", "-q", "-m", "chmod")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tM\tsrc/ante/m.py" in result.stdout


def test_symlink_requires_review(repo: Repo) -> None:
    repo.write("docs/target.md", "t\n")
    repo.commit("target")
    repo.mark_base()
    (repo.root / "docs" / "link.md").symlink_to("target.md")
    repo.commit("symlink")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tA\tdocs/link.md" in result.stdout


def test_non_ascii_doc_path_skips(repo: Repo) -> None:
    repo.write("docs/설계.md", "내용\n")
    repo.commit("hangul")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "doc\tA\tdocs/설계.md" in result.stdout


def test_src_pure_rename_requires_review(repo: Repo) -> None:
    _with_src(repo)
    repo.git("mv", "src/ante/m.py", "src/ante/n.py")
    repo.commit("rename")
    result = repo.check()
    assert result.returncode == 1
    assert "review\tR\tsrc/ante/m.py -> src/ante/n.py" in result.stdout


def test_coding_cookie_change_on_ascii_is_ast_identical(repo: Repo) -> None:
    _with_src(repo, "# -*- coding: utf-8 -*-\nx = 'a'\n")
    repo.write("src/ante/m.py", b"# -*- coding: latin-1 -*-\nx = 'a'\n")
    repo.commit("cookie")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ast-identical\tM\tsrc/ante/m.py" in result.stdout


def test_non_python_src_file_requires_review(repo: Repo) -> None:
    repo.write("src/ante/data.json", "{}\n")
    repo.commit("json")
    repo.mark_base()
    repo.write("src/ante/data.json", '{"a": 1}\n')
    repo.commit("json change")
    assert repo.check().returncode == 1


def test_merge_base_excludes_base_side_changes(repo: Repo) -> None:
    repo.git("switch", "-q", "-c", "feature")
    repo.write("docs/a.md", "a\n")
    repo.commit("feature doc")
    repo.git("switch", "-q", "main")
    repo.write("scripts/x.py", "x = 1\n")
    repo.commit("main moves on")
    main_tip = repo.git("rev-parse", "HEAD").strip()
    repo.git("switch", "-q", "feature")
    repo.base = main_tip
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "scripts/x.py" not in result.stdout


def test_bad_ref_is_undecidable(repo: Repo) -> None:
    repo.base = "no-such-ref"
    result = repo.check()
    assert result.returncode == 2
    assert "verdict: ERROR" in result.stderr


# ── 기준선 감소 ──────────────────────────────────────────────

BASELINE = "scripts/comment_baseline.json"


def _baseline_json(
    comments: dict[str, int] | None = None,
    history: dict[str, int] | None = None,
    lines: int = 10,
) -> str:
    return json.dumps(
        {
            "comments": {"src/ante/a.py": 3, "src/ante/b.py": 2}
            if comments is None
            else comments,
            "docstring_history": {"src/ante/a.py": 1} if history is None else history,
            "docstring_lines": lines,
        },
        indent=2,
    )


BASE_BASELINE = _baseline_json()
EMPTY_BASELINE = _baseline_json(comments={}, history={}, lines=0)

BASELINE_CASES = [
    pytest.param(
        _baseline_json(comments={"src/ante/a.py": 1, "src/ante/b.py": 2}),
        True,
        id="decrease",
    ),
    pytest.param(_baseline_json(comments={"src/ante/a.py": 3}), True, id="key-removed"),
    pytest.param(EMPTY_BASELINE, True, id="emptied"),
    pytest.param(BASE_BASELINE + "\n", True, id="values-equal"),
    pytest.param(
        _baseline_json(comments={"src/ante/a.py": 4, "src/ante/b.py": 1}),
        False,
        id="value-increase",
    ),
    pytest.param(
        _baseline_json(history={"src/ante/a.py": 2}), False, id="history-increase"
    ),
    pytest.param(
        _baseline_json(comments={"src/ante/a.py": 1, "src/ante/c.py": 1}),
        False,
        id="new-key",
    ),
    pytest.param(
        _baseline_json(history={"src/ante/b.py": 1}), False, id="new-history-key"
    ),
    pytest.param(_baseline_json(lines=11), False, id="docstring-lines-increase"),
    pytest.param("{not json", False, id="head-broken-json"),
    pytest.param(
        _baseline_json(comments={"src/ante/a.py": 0}), False, id="head-zero-value"
    ),
    pytest.param(
        json.dumps({"comments": {}, "docstring_history": {}}),
        False,
        id="head-missing-key",
    ),
    pytest.param(
        json.dumps(
            {
                "comments": {},
                "docstring_history": {},
                "docstring_lines": 0,
                "extra": {},
            }
        ),
        False,
        id="head-extra-key",
    ),
]


@pytest.mark.parametrize(("head", "lowered"), BASELINE_CASES)
def test_baseline_lowered_in_process(head: str, lowered: bool) -> None:
    assert scope.baseline_lowered(BASE_BASELINE.encode(), head.encode()) is lowered


@pytest.mark.parametrize(("head", "lowered"), BASELINE_CASES)
def test_baseline_lowered_subprocess(repo: Repo, head: str, lowered: bool) -> None:
    repo.write(BASELINE, BASE_BASELINE)
    repo.commit("baseline")
    repo.mark_base()
    repo.write(BASELINE, head)
    repo.commit("change baseline")
    result = repo.check()
    if lowered:
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"baseline-lowered\tM\t{BASELINE}" in result.stdout
        assert "verdict: SKIP (baseline-lowered)" in result.stdout
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert f"review\tM\t{BASELINE}" in result.stdout


def test_baseline_path_matches_comment_checker() -> None:
    checker_path = REPO_ROOT / "scripts" / "check_comments.py"
    spec = importlib.util.spec_from_file_location("_baseline_path_probe", checker_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    assert module.BASELINE_PATH.as_posix() == scope.COMMENT_BASELINE_PATH == BASELINE
    assert scope.CHECK_COMMENTS_PATH == checker_path


@pytest.mark.parametrize(
    "old",
    [
        pytest.param(b"{not json", id="base-broken-json"),
        pytest.param(b'{"comments": {}}', id="base-missing-key"),
        pytest.param("﻿".encode() + BASE_BASELINE.encode(), id="base-bom"),
        pytest.param(b"\xff\xfe", id="base-not-utf8"),
    ],
)
def test_malformed_base_baseline_is_not_lowered(old: bytes) -> None:
    assert not scope.baseline_lowered(old, EMPTY_BASELINE.encode())


def test_malformed_base_baseline_requires_review(repo: Repo) -> None:
    repo.write(BASELINE, '{"comments": {}}')
    repo.commit("bad baseline")
    repo.mark_base()
    repo.write(BASELINE, EMPTY_BASELINE)
    repo.commit("fix baseline")
    result = repo.check()
    assert result.returncode == 1
    assert f"review\tM\t{BASELINE}" in result.stdout


def test_baseline_parser_load_failure_is_not_lowered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scope, "CHECK_COMMENTS_PATH", tmp_path / "missing.py")
    assert not scope.baseline_lowered(BASE_BASELINE.encode(), EMPTY_BASELINE.encode())


def test_baseline_load_removes_its_module_name() -> None:
    assert scope.baseline_lowered(BASE_BASELINE.encode(), BASE_BASELINE.encode())
    assert "_check_review_scope_comments" not in sys.modules


def test_baseline_parser_result_without_fields_is_not_lowered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scope, "_load_baseline_parser", lambda: lambda _text: object())
    assert not scope.baseline_lowered(BASE_BASELINE.encode(), EMPTY_BASELINE.encode())


def test_baseline_added_or_deleted_requires_review(repo: Repo) -> None:
    repo.write(BASELINE, BASE_BASELINE)
    repo.commit("add baseline")
    result = repo.check()
    assert result.returncode == 1
    assert f"review\tA\t{BASELINE}" in result.stdout

    repo.mark_base()
    repo.git("rm", "-q", BASELINE)
    repo.commit("delete baseline")
    result = repo.check()
    assert result.returncode == 1
    assert f"review\tD\t{BASELINE}" in result.stdout


def test_baseline_mode_change_requires_review(repo: Repo) -> None:
    repo.write(BASELINE, BASE_BASELINE)
    repo.commit("baseline")
    repo.mark_base()
    repo.write(BASELINE, EMPTY_BASELINE)
    repo.git("add", BASELINE)
    repo.git("update-index", "--chmod=+x", BASELINE)
    repo.git("commit", "-q", "-m", "lower and chmod")
    result = repo.check()
    assert result.returncode == 1
    assert f"review\tM\t{BASELINE}" in result.stdout


def test_baseline_elsewhere_requires_review(repo: Repo) -> None:
    other = "scripts/sub/comment_baseline.json"
    repo.write(other, BASE_BASELINE)
    repo.commit("baseline copy")
    repo.mark_base()
    repo.write(other, EMPTY_BASELINE)
    repo.commit("lower copy")
    result = repo.check()
    assert result.returncode == 1
    assert f"review\tM\t{other}" in result.stdout


def test_comment_removal_with_lowered_baseline_skips(repo: Repo) -> None:
    repo.write(BASELINE, _baseline_json(comments={"src/ante/m.py": 2}, history={}))
    _with_src(repo)
    repo.write("src/ante/m.py", SRC.replace("    # inline note\n", ""))
    repo.write(BASELINE, _baseline_json(comments={"src/ante/m.py": 1}, history={}))
    repo.commit("drop comment")
    result = repo.check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ast-identical\tM\tsrc/ante/m.py" in result.stdout
    assert f"baseline-lowered\tM\t{BASELINE}" in result.stdout
    assert "verdict: SKIP (ast-identical, baseline-lowered)" in result.stdout


def test_comment_addition_with_raised_baseline_requires_review(repo: Repo) -> None:
    repo.write(BASELINE, _baseline_json(comments={"src/ante/m.py": 2}, history={}))
    _with_src(repo)
    repo.write("src/ante/m.py", SRC.replace("return 1", "return 1  # new note"))
    repo.write(BASELINE, _baseline_json(comments={"src/ante/m.py": 3}, history={}))
    repo.commit("add comment")
    result = repo.check()
    assert result.returncode == 1
    assert "ast-identical\tM\tsrc/ante/m.py" in result.stdout
    assert f"review\tM\t{BASELINE}" in result.stdout
