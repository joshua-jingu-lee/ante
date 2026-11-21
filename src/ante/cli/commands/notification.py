"""ante notification — 알림 관리 커맨드."""

from __future__ import annotations

import click


@click.group(hidden=True)
def notification() -> None:
    """알림 관리."""
