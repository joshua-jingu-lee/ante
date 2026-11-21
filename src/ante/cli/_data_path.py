"""CLI `--data-path` resolver helper."""

from __future__ import annotations

import click

from ante.config.config import Config


def resolve_data_path(ctx: click.Context | None, override: str | None) -> str:
    """`--data-path` 옵션 값을 config-resolved data root 로 정합한다.

    Args:
        override: 사용자가 명시한 `--data-path` 값. ``None`` 또는 빈 문자열이면
            config-resolved default 로 폴백한다.
    """
    if override is not None and override != "":
        return override
    from ante.cli.main import get_config_dir

    cfg = Config.load(config_dir=get_config_dir(ctx))
    return str(cfg.resolve_path("data.path", "data").resolve())
