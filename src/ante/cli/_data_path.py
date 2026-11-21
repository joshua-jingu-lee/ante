"""CLI `--data-path` resolver helper."""

from __future__ import annotations

import click

from ante.config.config import Config


def resolve_data_path(ctx: click.Context | None, override: str | None) -> str:
    """`--data-path` 옵션 값을 config-resolved data root 로 정합한다.

    Returns:
        - override 가 명시되면 그 값을 변형 없이 그대로 반환.
        - 미명시이면 ``Config.resolve_path("data.path", "data").resolve()`` 의
          문자열(절대 경로).
    """
    if override is not None and override != "":
        return override
    from ante.cli.main import get_config_dir

    cfg = Config.load(config_dir=get_config_dir(ctx))
    return str(cfg.resolve_path("data.path", "data").resolve())
