"""project-structure.md 생성기의 정렬과 `tests/` 절의 깊이를 잠그는 테스트.

모든 절은 기존 문서의 줄 순서와 무관하게 「디렉터리 먼저, 그다음 파일,
각각 이름순(대소문자 무시)」으로 정렬되고, `tests/` 절은 디렉터리까지만 싣는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate_project_structure.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "generate_project_structure", _SCRIPT_PATH
)
assert _SPEC is not None
assert _SPEC.loader is not None

generator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = generator
_SPEC.loader.exec_module(generator)

GENERATED_AT = "2026-11-22 (KST)"

BASE_FILES: tuple[str, ...] = (
    "README.md",
    "src/ante/__init__.py",
    "src/ante/alpha.py",
    "src/ante/core/__init__.py",
    "src/ante/zeta.py",
    "tests/conftest.py",
    "tests/unit/test_a.py",
)

# 기존 문서: src/ante/ 의 파일을 이름순이 아닌 순서로 적는다.
EXISTING_DOC = """\
# Ante 프로젝트 디렉토리 구조

## src/ante/ — Python 백엔드

```
src/ante/
├── zeta.py                           # Z 모듈
├── alpha.py                          # A 모듈
├── __init__.py
└── core/                             # 코어
    └── __init__.py
```

## tests/ — 테스트

```
tests/
├── unit/                             # 단위 테스트
│   └── test_a.py                     # 파일 설명
└── conftest.py
```
"""

# 같은 경로·같은 설명을 다른 줄 순서로 적은 기존 문서.
EXISTING_DOC_REORDERED = """\
# Ante 프로젝트 디렉토리 구조

## src/ante/ — Python 백엔드

```
src/ante/
├── core/                             # 코어
│   └── __init__.py
├── __init__.py
├── alpha.py                          # A 모듈
└── zeta.py                           # Z 모듈
```

## tests/ — 테스트

```
tests/
├── conftest.py
└── unit/                             # 단위 테스트
    └── test_a.py                     # 파일 설명
```
"""


def _generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: tuple[str, ...],
    existing_doc: str = EXISTING_DOC,
    name: str = "project-structure.md",
) -> str:
    output_path = tmp_path / name
    output_path.write_text(existing_doc, encoding="utf-8")
    monkeypatch.setattr(generator, "_run_git_ls_files", lambda: sorted(files))
    return generator.generate(output_path, generated_at=GENERATED_AT)


def _section(content: str, title: str) -> str:
    header = f"## {title}\n\n```\n"
    start = content.index(header) + len(header)
    end = content.index("\n```", start)
    return content[start:end]


def test_adding_test_file_does_not_change_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(가) tests/ 아래에 파일을 더해도 출력이 바이트 단위로 같다."""
    before = _generate(tmp_path, monkeypatch, BASE_FILES)
    after = _generate(tmp_path, monkeypatch, (*BASE_FILES, "tests/unit/test_b.py"))

    assert after == before
    assert _section(after, "tests/ — 테스트") == (
        "tests/\n└── unit/                             # 단위 테스트"
    )


def test_adding_test_directory_adds_directory_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(나) tests/ 아래에 새 디렉터리를 더하면 그 디렉터리 줄이 생긴다."""
    content = _generate(
        tmp_path, monkeypatch, (*BASE_FILES, "tests/integration/test_x.py")
    )

    assert _section(content, "tests/ — 테스트") == (
        "tests/\n├── integration/\n└── unit/                             # 단위 테스트"
    )


def test_new_src_file_lands_in_name_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(다) src/ante/ 의 새 파일은 디렉터리 끝이 아니라 이름순의 제자리에 생긴다."""
    content = _generate(tmp_path, monkeypatch, (*BASE_FILES, "src/ante/beta.py"))

    assert _section(content, "src/ante/ — Python 백엔드") == (
        "src/ante/\n"
        "├── core/                             # 코어\n"
        "│   └── __init__.py\n"
        "├── __init__.py\n"
        "├── alpha.py                          # A 모듈\n"
        "├── beta.py\n"
        "└── zeta.py                           # Z 모듈"
    )


def test_existing_doc_line_order_does_not_affect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(라) 줄 순서만 다른 기존 문서 둘은 같은 출력을 내고, 설명은 남는다."""
    first = _generate(tmp_path, monkeypatch, BASE_FILES, EXISTING_DOC, "a.md")
    second = _generate(
        tmp_path, monkeypatch, BASE_FILES, EXISTING_DOC_REORDERED, "b.md"
    )

    assert first == second
    assert _section(first, "src/ante/ — Python 백엔드") == (
        "src/ante/\n"
        "├── core/                             # 코어\n"
        "│   └── __init__.py\n"
        "├── __init__.py\n"
        "├── alpha.py                          # A 모듈\n"
        "└── zeta.py                           # Z 모듈"
    )
