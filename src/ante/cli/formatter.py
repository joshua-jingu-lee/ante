"""CLI 출력 포맷터 — text/json 모드 지원."""

from __future__ import annotations

import json

import click


class OutputFormatter:
    """CLI 출력 포맷터."""

    def __init__(self, fmt: str = "text") -> None:
        self._format = fmt

    @property
    def is_json(self) -> bool:
        return self._format == "json"

    def output(self, data: dict | list, text_template: str = "") -> None:
        """데이터 출력."""
        if self._format == "json":
            click.echo(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        elif text_template and isinstance(data, dict):
            click.echo(text_template.format(**data))
        else:
            click.echo(str(data))

    def table(self, rows: list[dict], columns: list[str]) -> None:
        """테이블 형태 출력."""
        if self._format == "json":
            click.echo(json.dumps(rows, indent=2, default=str, ensure_ascii=False))
            return

        if not rows:
            click.echo("(no data)")
            return

        header = " | ".join(f"{c:>12}" for c in columns)
        click.echo(header)
        click.echo("-" * len(header))
        for row in rows:
            line = " | ".join(f"{str(row.get(c, '')):>12}" for c in columns)
            click.echo(line)

    def error(self, message: str, code: str = "") -> None:
        """에러 출력."""
        if self._format == "json":
            click.echo(json.dumps({"error": message, "code": code}))
        else:
            click.echo(f"Error: {message}", err=True)

    def success(self, message: str, data: dict | None = None) -> None:
        """성공 메시지 출력."""
        if self._format == "json":
            result = {"status": "ok", "message": message}
            if data:
                result.update(data)
            click.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        else:
            click.echo(message)
