#!/usr/bin/env python3
"""Git 파일 트리 기반 project-structure.md 생성/check.

Ante의 Agent용 프로젝트 구조 INDEX를 생성한다.
기존 generated 문서의 경로별 설명을 재사용해 curated 설명을 보존하고,
현재 Git 추적/비무시 파일 트리에 없는 stale path는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "architecture" / "generated" / "project-structure.md"
)
KST = timezone(timedelta(hours=9))
COMMENT_COLUMN = 38


@dataclass(frozen=True)
class Section:
    title: str
    base_path: str
    root_label: str
    recursive: bool = True


@dataclass
class TreeNode:
    name: str
    path: str
    is_dir: bool
    children: dict[str, TreeNode] = field(default_factory=dict)


SECTIONS: tuple[Section, ...] = (
    Section("최상위 구조", "", "ante/", recursive=False),
    Section("src/ante/ — Python 백엔드", "src/ante", "src/ante/"),
    Section("tests/ — 테스트", "tests", "tests/"),
    Section("deploy/ — 서비스 배포", "deploy", "deploy/"),
    Section("strategies/ — 전략 템플릿과 예제", "strategies", "strategies/"),
    Section("scripts/ — 설치·운영·문서 생성 스크립트", "scripts", "scripts/"),
    Section("docs/ — 설계 문서", "docs", "docs/"),
    Section("guide/ — 사용자·운용 가이드", "guide", "guide/"),
    Section("frontend/ — React 대시보드", "frontend/src", "frontend/src/"),
)

ROOT_ENTRIES: tuple[str, ...] = (
    "src/ante",
    "tests",
    "frontend",
    "guide",
    "docs",
    "deploy",
    "scripts",
    "strategies",
    "config",
    ".agent",
    ".claude",
    ".github",
    "Dockerfile",
    "docker-compose.yml",
    "AGENTS.md",
    "CHANGELOG.md",
    "README.md",
    "CLAUDE.md",
    "LICENSE",
)

DEFAULT_DESCRIPTIONS: dict[str, str] = {
    ".agent": "에이전트 정의/명령/스킬",
    ".claude": "Claude Code 설정 + .agent 호환 링크",
    ".github": "GitHub 워크플로/이슈 템플릿/로컬 인증 파일",
    "AGENTS.md": "개발 Agent 마스터 가이드",
    "CHANGELOG.md": "변경 이력",
    "CLAUDE.md": "Claude Code 호환 가이드",
    "Dockerfile": "프로덕션 Docker 이미지",
    "LICENSE": "라이선스",
    "README.md": "프로젝트 개요",
    "config": "런타임 설정 예시와 의존성 스냅샷",
    "deploy": "서비스 배포 파일 (systemd, launchd)",
    "docker-compose.yml": "프로덕션 Docker Compose",
    "docs": "설계 문서",
    "frontend": "React 대시보드 (Vite + TypeScript)",
    "guide": "사용자·운용 가이드 문서",
    "scripts": "설치·운영·문서 생성 스크립트",
    "scripts/generate_db_schema.py": "DB 스키마 문서 자동 생성",
    "scripts/generate_project_structure.py": "프로젝트 구조 Agent INDEX 생성/check",
    "src/ante": "Python 백엔드 패키지",
    "strategies": "전략 템플릿과 예제",
    "tests": "단위·통합 테스트",
}


TREE_LINE_RE = re.compile(
    r"^(?P<prefix>[│ ]*)(?:├|└)── (?P<name>.*?)(?:\s+#\s*(?P<comment>.*))?$"
)
GENERATED_AT_RE = re.compile(r"^> 마지막 생성 시점: (?P<value>.+)$", re.MULTILINE)


def _run_git_ls_files() -> list[str]:
    """Git이 추적하거나 무시하지 않는 파일 목록을 반환한다."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def _section_base_from_title(title: str) -> str:
    if title == "최상위 구조":
        return ""
    return title.split(" — ", maxsplit=1)[0].rstrip("/")


def _parse_existing_doc(
    path: Path,
) -> tuple[dict[str, str], dict[str, int], str | None]:
    """기존 generated 문서에서 경로별 설명과 표시 순서를 읽는다."""
    if not path.exists():
        return {}, {}, None

    text = path.read_text(encoding="utf-8")
    comments: dict[str, str] = {}
    order: dict[str, int] = {}
    generated_at = _extract_generated_at(text)

    current_base = ""
    in_fence = False
    stack: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            current_base = _section_base_from_title(line.removeprefix("## ").strip())
            continue

        if line == "```":
            in_fence = not in_fence
            stack = []
            continue

        if not in_fence:
            continue

        match = TREE_LINE_RE.match(line)
        if match is None:
            continue

        depth = len(match.group("prefix")) // 4
        raw_name = match.group("name").rstrip()
        name = raw_name.rstrip("/")
        is_dir = raw_name.endswith("/")
        stack = stack[:depth]

        parts = [part for part in (current_base, *stack, name) if part]
        rel_path = "/".join(parts)
        order.setdefault(rel_path, len(order))

        comment = match.group("comment")
        if comment:
            comments[rel_path] = comment.rstrip()

        if is_dir:
            stack.append(name)

    return comments, order, generated_at


def _extract_generated_at(text: str) -> str | None:
    match = GENERATED_AT_RE.search(text)
    if match is None:
        return None
    return match.group("value")


def _path_exists(path: str, files: list[str]) -> bool:
    prefix = f"{path}/"
    return path in files or any(file_path.startswith(prefix) for file_path in files)


def _build_tree(base_path: str, files: list[str]) -> TreeNode:
    root = TreeNode(
        name=base_path.rsplit("/", maxsplit=1)[-1],
        path=base_path,
        is_dir=True,
    )
    prefix = f"{base_path}/" if base_path else ""
    base_parts = [part for part in base_path.split("/") if part]

    for file_path in files:
        if prefix and not file_path.startswith(prefix):
            continue
        if not prefix and "/" not in file_path:
            continue

        relative = file_path.removeprefix(prefix)
        parts = [part for part in relative.split("/") if part]
        if not parts:
            continue

        node = root
        for index, part in enumerate(parts):
            rel_path = "/".join((*base_parts, *parts[: index + 1]))
            is_dir = index < len(parts) - 1
            child = node.children.get(part)
            if child is None:
                child = TreeNode(name=part, path=rel_path, is_dir=is_dir)
                node.children[part] = child
            elif is_dir:
                child.is_dir = True
            node = child

    return root


def _sort_children(nodes: dict[str, TreeNode], order: dict[str, int]) -> list[TreeNode]:
    unknown_order = len(order) + 1
    return sorted(
        nodes.values(),
        key=lambda node: (
            order.get(node.path, unknown_order),
            0 if node.is_dir else 1,
            node.name.lower(),
        ),
    )


def _format_tree(
    root: TreeNode,
    comments: dict[str, str],
    order: dict[str, int],
) -> list[str]:
    lines = [root.path + "/" if root.path else "ante/"]
    children = _sort_children(root.children, order)
    for index, child in enumerate(children):
        lines.extend(
            _format_node(
                child,
                prefix="",
                is_last=index == len(children) - 1,
                comments=comments,
                order=order,
            )
        )
    return lines


def _format_node(
    node: TreeNode,
    prefix: str,
    is_last: bool,
    comments: dict[str, str],
    order: dict[str, int],
) -> list[str]:
    connector = "└── " if is_last else "├── "
    display_name = f"{node.name}/" if node.is_dir else node.name
    line = _append_comment(
        f"{prefix}{connector}{display_name}",
        _comment_for(node.path, comments),
    )
    lines = [line]

    if node.is_dir and node.children:
        child_prefix = prefix + ("    " if is_last else "│   ")
        children = _sort_children(node.children, order)
        for index, child in enumerate(children):
            lines.extend(
                _format_node(
                    child,
                    prefix=child_prefix,
                    is_last=index == len(children) - 1,
                    comments=comments,
                    order=order,
                )
            )

    return lines


def _format_root_tree(
    files: list[str],
    comments: dict[str, str],
) -> list[str]:
    entries = [entry for entry in ROOT_ENTRIES if _path_exists(entry, files)]
    lines = ["ante/"]
    for index, entry in enumerate(entries):
        is_last = index == len(entries) - 1
        connector = "└── " if is_last else "├── "
        is_dir = any(file_path.startswith(f"{entry}/") for file_path in files)
        display_name = f"{entry}/" if is_dir else entry
        lines.append(
            _append_comment(
                f"{connector}{display_name}",
                _comment_for(entry, comments),
            )
        )
    return lines


def _comment_for(path: str, comments: dict[str, str]) -> str | None:
    return comments.get(path) or DEFAULT_DESCRIPTIONS.get(path)


def _append_comment(line: str, comment: str | None) -> str:
    if not comment:
        return line
    spacing = max(1, COMMENT_COLUMN - len(line))
    return f"{line}{' ' * spacing}# {comment}"


def _write_section(
    out: TextIO,
    section: Section,
    files: list[str],
    comments: dict[str, str],
    order: dict[str, int],
) -> None:
    out.write(f"## {section.title}\n\n")
    out.write("```\n")

    if section.recursive:
        tree = _build_tree(section.base_path, files)
        lines = _format_tree(tree, comments, order)
    else:
        lines = _format_root_tree(files, comments)

    out.write("\n".join(lines))
    out.write("\n```\n\n")


def _render_markdown(
    files: list[str],
    comments: dict[str, str],
    order: dict[str, int],
    generated_at: str,
) -> str:
    from io import StringIO

    out = StringIO()
    out.write("# Ante 프로젝트 디렉토리 구조\n\n")
    out.write("> 역할: Agent용 프로젝트 구조 INDEX의 단일 SSOT입니다.\n")
    out.write("> 생성 명령: `.venv/bin/python scripts/generate_project_structure.py`\n")
    out.write(
        "> Check 명령: "
        "`.venv/bin/python scripts/generate_project_structure.py --check`\n"
    )
    out.write(
        "> 생성 기준: 현재 Git 추적/비무시 파일 트리 "
        "(`git ls-files --cached --others --exclude-standard`)\n"
    )
    out.write(f"> 마지막 생성 시점: {generated_at}\n\n")

    for section in SECTIONS:
        if section.base_path and not _path_exists(section.base_path, files):
            continue
        _write_section(out, section, files, comments, order)

    return out.getvalue().rstrip() + "\n"


def generate(output_path: Path, *, generated_at: str | None = None) -> str:
    comments, order, _existing_generated_at = _parse_existing_doc(output_path)
    files = _run_git_ls_files()
    generated_at = generated_at or _today_kst()
    return _render_markdown(files, comments, order, generated_at)


def _today_kst() -> str:
    return datetime.now(tz=KST).strftime("%Y-%m-%d (KST)")


def _write_output(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def _check_output(output_path: Path, content: str) -> int:
    current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    if current == content:
        print(f"{output_path.relative_to(PROJECT_ROOT)} is up to date.")
        return 0

    rel_output = output_path.relative_to(PROJECT_ROOT)
    print(f"{rel_output} is stale.")
    print("Run: .venv/bin/python scripts/generate_project_structure.py")
    print()
    _print_diff_summary(current, content, rel_output)
    return 1


def _print_diff_summary(current: str, expected: str, rel_output: Path) -> None:
    diff = list(
        difflib.unified_diff(
            current.splitlines(),
            expected.splitlines(),
            fromfile=f"a/{rel_output}",
            tofile=f"b/{rel_output}",
            lineterm="",
        )
    )
    max_lines = 120
    for line in diff[:max_lines]:
        print(line)
    if len(diff) > max_lines:
        print(f"... diff truncated ({len(diff) - max_lines} more lines)")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Git 파일 트리 기반 project-structure.md 생성/check",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="생성할 project-structure.md 경로",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 수정하지 않고 generated 문서가 최신인지 확인",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_path = args.output
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    generated_at = _existing_or_today(output_path) if args.check else None
    content = generate(output_path, generated_at=generated_at)

    if args.check:
        return _check_output(output_path, content)

    _write_output(output_path, content)
    print(f"Generated {output_path.relative_to(PROJECT_ROOT)}")
    return 0


def _existing_or_today(output_path: Path) -> str:
    if output_path.exists():
        existing = _extract_generated_at(output_path.read_text(encoding="utf-8"))
        if existing:
            return existing
    return _today_kst()


if __name__ == "__main__":
    raise SystemExit(main())
