"""ante strategy — 전략 관리 커맨드."""

from __future__ import annotations

from pathlib import Path

import click

from ante.cli.main import get_formatter


@click.group()
def strategy() -> None:
    """전략 관리."""


@strategy.command()
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def validate(ctx: click.Context, path: str) -> None:
    """전략 파일 정적 검증 (AST 기반)."""
    from ante.strategy.validator import StrategyValidator

    fmt = get_formatter(ctx)
    validator = StrategyValidator()
    result = validator.validate(Path(path))

    data = {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }

    if result.valid:
        fmt.success(f"Strategy validation passed: {path}", data)
    else:
        fmt.error(f"Validation failed: {path}")
        if not fmt.is_json:
            for err in result.errors:
                click.echo(f"  - {err}", err=True)
            for warn in result.warnings:
                click.echo(f"  [warn] {warn}", err=True)
        else:
            fmt.output(data)


@strategy.command("list")
@click.pass_context
def strategy_list(ctx: click.Context) -> None:
    """등록된 전략 목록 조회."""
    fmt = get_formatter(ctx)
    fmt.output({"message": "Strategy list requires a running system."})
