#!/usr/bin/env python3
"""Click introspection 기반 CLI 레퍼런스 문서 자동 생성/check.

ante CLI의 Click 명령어 트리를 순회하며 guide/cli.md를 생성한다.
SSOT: Click 데코레이터 → guide/cli.md (자동 생성)

사용법:
    python scripts/generate_cli_reference.py
    python scripts/generate_cli_reference.py --output <path>
    python scripts/generate_cli_reference.py --stdout
    python scripts/generate_cli_reference.py --check

    <path> 기본값: guide/cli.md
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import io
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TextIO

import click

# ── 프로젝트 루트 ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "guide" / "cli.md"
KST = timezone(timedelta(hours=9))
LAST_UPDATED_RE = re.compile(r"^> 마지막 갱신: (?P<value>.+)$", re.MULTILINE)


def _load_import_guard():
    guard_path = PROJECT_ROOT / "scripts" / "check_import_path.py"
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_current_worktree_import_path() -> None:
    guard = _load_import_guard()
    try:
        guard.check_import_path(PROJECT_ROOT)
    except guard.ImportPathCheckError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


CLI_GENERATED_NOTICE = (
    "> 이 문서는 `scripts/generate_cli_reference.py`로 자동 생성됩니다. "
    "명령어 상세를 직접 편집하지 말고 Click 데코레이터나 생성 스크립트를 "
    "수정한 뒤 재생성하세요."
)

CLI_MODULE_GUIDE_NOTICE = (
    "명령 그룹이 Ante의 어떤 모듈과 운영 영역을 제어하는지 먼저 보려면 "
    "[모듈과 운영 영역](modules.md)을 확인하세요."
)


def get_cli() -> click.Group:
    """ante CLI 루트 그룹을 가져온다."""
    from ante.cli.main import cli

    return cli


# ── Click introspection helpers ──────────────────────────────────────────────


def _registration_order(group: click.Group) -> list[str]:
    """Click Group의 내부 커맨드 dict 삽입 순서를 반환한다.

    click.Group._commands (Click 8+) 또는 commands dict의 키 순서가
    add_command() 호출 순서를 보존한다.
    """
    # Click 8+: group.commands 는 dict (삽입 순서 보존)
    if hasattr(group, "commands") and isinstance(group.commands, dict):
        return list(group.commands.keys())
    # fallback: list_commands (알파벳 정렬)
    ctx = click.Context(group, info_name=group.name or "ante")
    return list(group.list_commands(ctx))


def _collect_commands(
    group: click.Group,
    prefix: str = "",
) -> list[tuple[str, click.BaseCommand]]:
    """명령어 트리를 DFS로 순회하여 (full_name, command) 쌍을 수집한다."""
    results: list[tuple[str, click.BaseCommand]] = []
    ctx = click.Context(group, info_name=prefix or group.name or "ante")

    for name in _registration_order(group):
        cmd = group.get_command(ctx, name)
        if cmd is None:
            continue

        # hidden 명령은 public 표면(guide/cli.md)에서 제외한다.
        # 그룹이 hidden이면 그룹 자체뿐 아니라 하위 재귀도 skip한다.
        # generic·mechanism-agnostic: 임의의 hidden 명령을 자동 제외한다.
        if getattr(cmd, "hidden", False):
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


def _is_master_only(cmd: click.BaseCommand) -> bool:
    """커맨드의 콜백 체인에서 ``_require_master_applied`` 마커를 찾는다.

    ``ante.cli.middleware.require_master`` 가 부착하는 sentinel marker. master
    HUMAN 만 통과하는 명령(member admin mutation 등, #1543) 은 scope 가 비어
    있지만 인증이 필요하므로, ``_required_scopes`` 와 별도로 식별해 문서에
    명시한다.
    """
    cb = cmd.callback
    while cb:
        if getattr(cb, "_require_master_applied", False):
            return True
        cb = getattr(cb, "__wrapped__", None)
    return False


def _get_required_scopes(cmd: click.BaseCommand) -> tuple[str, ...]:
    """커맨드의 콜백 체인에서 _required_scopes를 추출한다."""
    cb = cmd.callback
    while cb:
        if hasattr(cb, "_required_scopes"):
            return cb._required_scopes
        cb = getattr(cb, "__wrapped__", None)
    return ()


def _format_scope_cell(scopes: tuple[str, ...], *, master_only: bool = False) -> str:
    """scope 목록을 마크다운 셀 텍스트로 포맷팅한다.

    master-only 명령(#1543 — ``@require_master``) 은 scope 가 비어 있어도
    ``master-only`` 로 표시한다. ``\u2014`` (인증 불필요) 와 혼동되지 않도록 한다.
    """
    if master_only:
        return "master-only"
    if not scopes:
        return "\u2014"
    return ", ".join(f"`{s}`" for s in scopes)


def _format_token_cell(scopes: tuple[str, ...], *, master_only: bool = False) -> str:
    """토큰 요구 사항을 마크다운 셀 텍스트로 포맷팅한다."""
    if master_only:
        return "H(master)"
    if not scopes:
        return "\u2014"
    return "H\u00b7A"


def _format_token_detail(scopes: tuple[str, ...], *, master_only: bool = False) -> str:
    """커맨드 상세 섹션용 토큰 정보를 포맷팅한다."""
    if master_only:
        return "\U0001f511 Human master 전용 (#1543)"
    if not scopes:
        return "인증 불필요"
    return "\U0001f511 Human(무제한) / Agent(scope 필요)"


# ── Markdown generation ──────────────────────────────────────────────────────


def _to_anchor(heading: str) -> str:
    """마크다운 헤딩을 GitHub 호환 앵커로 변환한다."""
    import re

    anchor = heading.lower()
    anchor = re.sub(r"[^\w\s가-힣-]", "", anchor)
    anchor = re.sub(r"\s+", "-", anchor.strip())
    return anchor


def _write_header(out: TextIO, *, generated_at: str | None = None) -> None:
    """문서 헤더를 출력한다."""
    today = generated_at or _today_kst()
    out.write("# Ante CLI Reference\n\n")
    out.write(
        "Ante가 제공하는 모든 CLI 명령어를 정리한 문서입니다. "
        "각 명령어의 사용법, 옵션, 필수 권한(scope)을 확인할 수 있습니다.\n\n"
    )
    out.write(f"> 마지막 갱신: {today}\n\n")
    out.write(f"{CLI_GENERATED_NOTICE}\n\n")
    out.write(f"{CLI_MODULE_GUIDE_NOTICE}\n\n")


def _write_toc(
    out: TextIO,
    grouped: dict[str, list[tuple[str, click.BaseCommand]]],
) -> None:
    """목차를 출력한다."""
    out.write("## 목차\n\n")
    out.write(f"- [글로벌 옵션](#{_to_anchor('글로벌 옵션')})\n")
    out.write(f"- [명령어 요약](#{_to_anchor('명령어 요약')})\n")

    for group_name in grouped:
        items = grouped[group_name]
        # 그룹 헤딩 텍스트 재현
        group_cmd = None
        for _, cmd in items:
            if isinstance(cmd, click.Group):
                group_cmd = cmd
                break

        group_help = ""
        if group_cmd and group_cmd.help:
            group_help = f" \u2014 {group_cmd.help.strip().split(chr(10))[0]}"

        heading = f"{group_name}{group_help}"
        out.write(f"- [{heading}](#{_to_anchor(heading)})\n")

        # 리프 커맨드 서브 항목
        for full_name, cmd in items:
            if isinstance(cmd, click.Group):
                continue
            sub_heading = f"ante {full_name}"
            out.write(f"  - [{sub_heading}](#{_to_anchor(sub_heading)})\n")

    out.write("\n---\n\n")


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
    out.write("| 명령 | 설명 | scope | 토큰 |\n")
    out.write("|------|------|-------|------|\n")

    for full_name, cmd in commands:
        # 그룹 자체는 요약 테이블에 표시하되 하위 명령어가 있으면 별도 표시
        help_text = ""
        if cmd.help:
            # 첫 줄만 사용
            help_text = cmd.help.strip().split("\n")[0]

        scopes = _get_required_scopes(cmd)
        master_only = _is_master_only(cmd)
        scope_cell = _format_scope_cell(scopes, master_only=master_only)
        token_cell = _format_token_cell(scopes, master_only=master_only)

        out.write(
            f"| `ante {full_name}` | {help_text} | {scope_cell} | {token_cell} |\n"
        )

    out.write("\n")
    out.write(
        "> **H**: Human 토큰 (scope 무제한) · "
        "**A**: Agent 토큰 (해당 scope 필요) · "
        "**H(master)**: Human master 전용 (#1543) · "
        "**\u2014**: 인증 불필요\n\n"
    )
    out.write("---\n\n")


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

    # scope·토큰 정보
    scopes = _get_required_scopes(cmd)
    master_only = _is_master_only(cmd)
    scope_text = _format_scope_cell(scopes, master_only=master_only)
    token_text = _format_token_detail(scopes, master_only=master_only)
    out.write(f"- **필요 scope**: {scope_text}\n")
    out.write(f"- **토큰**: {token_text}\n\n")

    params = _get_params(cmd)
    arguments = [p for p in params if isinstance(p, click.Argument)]
    options = [p for p in params if isinstance(p, click.Option)]

    # 사용법
    # required option은 인라인 표시, non-required는 [OPTIONS]로 축약 (#1696).
    usage_parts = [f"ante {full_name}"]
    for arg in arguments:
        arg_mv = arg.metavar or (arg.human_readable_name or arg.name).upper()
        usage_parts.append(f"<{arg_mv}>")
    req_options = [o for o in options if o.required]
    nonreq_options = [o for o in options if not o.required]
    for opt in req_options:
        opt_name = opt.opts[0] if opt.opts else f"--{opt.name.replace('_', '-')}"
        opt_mv = opt.metavar or (opt.human_readable_name or opt.name).upper()
        usage_parts.append(f"{opt_name} <{opt_mv}>")
    if nonreq_options:
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


def generate_cli_reference(
    out: TextIO,
    *,
    generated_at: str | None = None,
) -> int:
    """CLI 레퍼런스 문서를 생성하고 서브커맨드 수를 반환한다."""
    cli = get_cli()

    commands = _collect_commands(cli)
    leaf_commands = [(n, c) for n, c in commands if not isinstance(c, click.Group)]

    grouped = _group_by_top_level(commands)

    _write_header(out, generated_at=generated_at)
    _write_toc(out, grouped)
    _write_global_options(out, cli)
    _write_summary_table(out, leaf_commands)

    # 그룹별 상세
    for group_name in grouped:
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


# ── check 모드 헬퍼 ──────────────────────────────────────────────────────────


def _today_kst() -> str:
    return datetime.now(tz=KST).strftime("%Y-%m-%d")


def _extract_generated_at(text: str) -> str | None:
    match = LAST_UPDATED_RE.search(text)
    if match is None:
        return None
    return match.group("value")


def _existing_or_today(output_path: Path) -> str:
    if output_path.exists():
        existing = _extract_generated_at(output_path.read_text(encoding="utf-8"))
        if existing:
            return existing
    return _today_kst()


def _display_path(output_path: Path) -> Path:
    try:
        return output_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return output_path


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


def _check_output(output_path: Path, content: str) -> int:
    current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    rel_output = _display_path(output_path)
    if current == content:
        print(f"{rel_output} is up to date.")
        return 0

    print(f"{rel_output} is stale.")
    print("Run: PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_cli_reference.py")
    print()
    _print_diff_summary(current, content, rel_output)
    return 1


# ── CLI entrypoint ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """스크립트 진입점."""
    parser = argparse.ArgumentParser(
        description="Click introspection 기반 CLI 레퍼런스 문서 자동 생성/check",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "출력 파일 경로. 상대 경로는 저장소 루트 기준으로 해석한다 "
            "(기본: guide/cli.md)"
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="파일 대신 stdout으로 출력",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 수정하지 않고 generated 문서가 최신인지 확인",
    )
    args = parser.parse_args(argv)

    # 워크트리 import 가드는 argparse 처리 **뒤**에 둔다. main() 첫 줄에 두면
    # introspection이 필요 없는 `--help`까지 워크트리에서만 rc=1이 된다(#2472).
    # 상호배타 검사보다는 **앞**이어야 `--stdout --check`의 종료 코드가 형제
    # 생성기와 같은 순서를 유지한다.
    _assert_current_worktree_import_path()

    output_path = args.output
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if args.stdout and args.check:
        parser.error("--stdout and --check cannot be used together")

    if args.stdout:
        count = generate_cli_reference(sys.stdout)
        print(f"\n<!-- {count} subcommands documented -->", file=sys.stderr)
        return 0

    if args.check:
        buf = io.StringIO()
        generate_cli_reference(buf, generated_at=_existing_or_today(output_path))
        return _check_output(output_path, buf.getvalue())

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        count = generate_cli_reference(f)

    print(f"Generated {_display_path(output_path)} ({count} subcommands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
