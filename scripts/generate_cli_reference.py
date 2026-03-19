#!/usr/bin/env python3
"""Click introspection 기반 CLI 레퍼런스 문서 자동 생성.

ante CLI의 Click 명령어 트리를 순회하며 guide/cli.md를 생성한다.
SSOT: Click 데코레이터 → guide/cli.md (자동 생성)

사용법:
    python scripts/generate_cli_reference.py
    python scripts/generate_cli_reference.py --output guide/cli.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

import click


def get_cli() -> click.Group:
    """ante CLI 루트 그룹을 가져온다."""
    from ante.cli.main import cli

    return cli


# ── Click introspection helpers ──────────────────────────────────────────────


def _collect_commands(
    group: click.Group,
    prefix: str = "",
) -> list[tuple[str, click.BaseCommand]]:
    """명령어 트리를 DFS로 순회하여 (full_name, command) 쌍을 수집한다."""
    results: list[tuple[str, click.BaseCommand]] = []
    ctx = click.Context(group, info_name=prefix or group.name or "ante")

    for name in sorted(group.list_commands(ctx)):
        cmd = group.get_command(ctx, name)
        if cmd is None:
            continue

        full_name = f"{prefix} {name}".strip() if prefix else name

        if isinstance(cmd, click.Group):
            # 그룹 자체도 기록 (설명 포함)
            results.append((full_name, cmd))
            # 하위 명령어 재귀 수집
            results.extend(_collect_commands(cmd, full_name))
        else:
            results.append((full_name, cmd))

    return results


def _get_params(cmd: click.BaseCommand) -> list[click.Parameter]:
    """명령어의 파라미터 목록을 반환한다 (help 옵션 제외)."""
    return [
        p for p in cmd.params if not (isinstance(p, click.Option) and p.name == "help")
    ]


def _format_param_type(param: click.Parameter) -> str:
    """파라미터 타입을 문자열로 포맷팅한다."""
    if isinstance(param.type, click.Choice):
        return " / ".join(param.type.choices)
    if isinstance(param.type, click.IntRange):
        parts = []
        if param.type.min is not None:
            parts.append(str(param.type.min))
        else:
            parts.append("")
        if param.type.max is not None:
            parts.append(str(param.type.max))
        else:
            parts.append("")
        return f"INT ({parts[0]}~{parts[1]})"
    if isinstance(param.type, click.Path):
        return "PATH"
    type_name = param.type.name.upper() if hasattr(param.type, "name") else "TEXT"
    return type_name


def _format_default(param: click.Parameter) -> str:
    """기본값을 문자열로 포맷팅한다."""
    default = param.default
    if default is None:
        return "\u2014"
    # Click 8.2+: multiple=True 옵션의 default가 Sentinel.UNSET일 수 있음
    if not isinstance(default, (bool, int, float, str, tuple, list)):
        return "\u2014"
    if isinstance(default, bool):
        return "false" if not default else "true"
    if isinstance(default, tuple) and len(default) == 0:
        return "\u2014"
    return str(default)


def _is_required(param: click.Parameter) -> str:
    """필수 여부를 O/- 로 반환한다."""
    if isinstance(param, click.Argument):
        return "O" if param.required else "-"
    if isinstance(param, click.Option):
        return "O" if param.required else "-"
    return "-"


def _param_display_name(param: click.Parameter) -> str:
    """파라미터의 표시 이름을 반환한다."""
    if isinstance(param, click.Argument):
        human = param.human_readable_name.upper()
        return f"`<{human}>`"
    if isinstance(param, click.Option):
        opts = param.opts + param.secondary_opts
        return ", ".join(f"`{o}`" for o in opts)
    return f"`{param.name}`"


# ── Markdown generation ──────────────────────────────────────────────────────


def _write_header(out: TextIO) -> None:
    """문서 헤더를 출력한다."""
    kst = timezone(timedelta(hours=9))
    today = datetime.now(tz=kst).strftime("%Y-%m-%d")
    out.write("# Ante CLI Reference\n\n")
    out.write(
        "> 이 문서는 `scripts/generate_cli_reference.py`에 의해 "
        "Click introspection으로 자동 생성됩니다.\n"
    )
    out.write("> 직접 수정하지 마세요. CLI 코드 변경 후 스크립트를 재실행하세요.\n")
    out.write(f">\n> 마지막 갱신: {today}\n\n")


def _write_global_options(out: TextIO, cli: click.Group) -> None:
    """글로벌 옵션 섹션을 출력한다."""
    out.write("## 글로벌 옵션\n\n")
    out.write("```bash\nante [OPTIONS] <command>\n```\n\n")

    params = _get_params(cli)
    if params:
        out.write("| 옵션 | 타입 | 기본값 | 설명 |\n")
        out.write("|------|------|--------|------|\n")
        for p in params:
            name = _param_display_name(p)
            ptype = _format_param_type(p)
            default = _format_default(p)
            desc = p.help or ""
            out.write(f"| {name} | {ptype} | {default} | {desc} |\n")
        out.write("\n")

    out.write("---\n\n")


def _write_summary_table(
    out: TextIO,
    commands: list[tuple[str, click.BaseCommand]],
) -> None:
    """명령어 요약 테이블을 출력한다."""
    out.write("## 명령어 요약\n\n")
    out.write("| 명령 | 설명 |\n")
    out.write("|------|------|\n")

    for full_name, cmd in commands:
        # 그룹 자체는 요약 테이블에 표시하되 하위 명령어가 있으면 별도 표시
        help_text = ""
        if cmd.help:
            # 첫 줄만 사용
            help_text = cmd.help.strip().split("\n")[0]

        out.write(f"| `ante {full_name}` | {help_text} |\n")

    out.write("\n---\n\n")


def _write_command_detail(
    out: TextIO,
    full_name: str,
    cmd: click.BaseCommand,
) -> None:
    """개별 명령어 상세 정보를 출력한다."""
    # 그룹이면서 직접 실행 불가한 경우 상세를 생략
    if isinstance(cmd, click.Group):
        return

    out.write(f"### ante {full_name}\n\n")

    # 설명
    if cmd.help:
        out.write(f"{cmd.help.strip()}\n\n")

    params = _get_params(cmd)
    arguments = [p for p in params if isinstance(p, click.Argument)]
    options = [p for p in params if isinstance(p, click.Option)]

    # 사용법
    usage_parts = [f"ante {full_name}"]
    for arg in arguments:
        usage_parts.append(f"<{arg.human_readable_name.upper()}>")
    if options:
        usage_parts.append("[OPTIONS]")
    out.write(f"```bash\n{' '.join(usage_parts)}\n```\n\n")

    # Arguments 테이블
    if arguments:
        out.write("**Arguments:**\n\n")
        out.write("| 인자 | 필수 | 설명 |\n")
        out.write("|------|------|------|\n")
        for arg in arguments:
            name = _param_display_name(arg)
            req = _is_required(arg)
            desc = getattr(arg, "help", "") or ""
            out.write(f"| {name} | {req} | {desc} |\n")
        out.write("\n")

    # Options 테이블
    if options:
        out.write("**Options:**\n\n")
        out.write("| 옵션 | 필수 | 타입 | 기본값 | 설명 |\n")
        out.write("|------|------|------|--------|------|\n")
        for opt in options:
            name = _param_display_name(opt)
            req = _is_required(opt)
            ptype = _format_param_type(opt)
            default = _format_default(opt)
            desc = opt.help or ""
            out.write(f"| {name} | {req} | {ptype} | {default} | {desc} |\n")
        out.write("\n")

    out.write("\n")


def _group_by_top_level(
    commands: list[tuple[str, click.BaseCommand]],
) -> dict[str, list[tuple[str, click.BaseCommand]]]:
    """명령어를 최상위 그룹 기준으로 분류한다."""
    groups: dict[str, list[tuple[str, click.BaseCommand]]] = {}
    for full_name, cmd in commands:
        top = full_name.split()[0]
        groups.setdefault(top, []).append((full_name, cmd))
    return groups


def generate_cli_reference(out: TextIO) -> int:
    """CLI 레퍼런스 문서를 생성하고 서브커맨드 수를 반환한다."""
    cli = get_cli()

    commands = _collect_commands(cli)
    leaf_commands = [(n, c) for n, c in commands if not isinstance(c, click.Group)]

    _write_header(out)
    _write_global_options(out, cli)
    _write_summary_table(out, leaf_commands)

    # 그룹별 상세
    grouped = _group_by_top_level(commands)
    for group_name in sorted(grouped):
        items = grouped[group_name]
        # 그룹 설명 찾기
        group_cmd = None
        for _, cmd in items:
            if isinstance(cmd, click.Group):
                group_cmd = cmd
                break

        group_help = ""
        if group_cmd and group_cmd.help:
            group_help = f" \u2014 {group_cmd.help.strip().split(chr(10))[0]}"

        out.write(f"## {group_name}{group_help}\n\n")

        for full_name, cmd in items:
            _write_command_detail(out, full_name, cmd)

        out.write("---\n\n")

    return len(leaf_commands)


# ── CLI entrypoint ───────────────────────────────────────────────────────────


def main() -> None:
    """스크립트 진입점."""
    parser = argparse.ArgumentParser(
        description="Click introspection 기반 CLI 레퍼런스 문서 자동 생성",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="guide/cli.md",
        help="출력 파일 경로 (기본: guide/cli.md)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="파일 대신 stdout으로 출력",
    )
    args = parser.parse_args()

    if args.stdout:
        count = generate_cli_reference(sys.stdout)
        print(f"\n<!-- {count} subcommands documented -->", file=sys.stderr)
    else:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as f:
            count = generate_cli_reference(f)

        print(f"Generated {output_path} ({count} subcommands)")


if __name__ == "__main__":
    main()
