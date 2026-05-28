"""CLI `--data-path` resolver helper.

Spec: docs/specs/config/03-design-decisions.md `Ante instance/path contract`
(특히 `data.path` SSOT 행과 "명시적 CLI override는 작업 대상만 바꾸며 인스턴스
경계 불변" 규약).

이 helper는 CLI 커맨드들이 `--data-path` 옵션을 처리할 때 단일 경로 해석
지점을 갖도록 한다:

  * override 가 명시적으로 주어지면(``None`` 도 ``""`` 도 아님) 그 값을 그대로
    반환한다. `resolve()`/`absolute()` 등으로 변형하지 않는다. 이는 사용자가
    상대 경로를 의도적으로 넘겼을 때 그대로 사용할 수 있게 하고, 테스트가
    임시 디렉토리 등을 그대로 주입할 수 있게 한다.
  * override 가 없으면 ``Config.resolve_path("data.path", "data")`` 로
    ``config_dir`` 기준 절대 경로를 만든 뒤, ``Path.resolve()`` 로 정규화하여
    문자열로 반환한다. CWD 와 무관하게 server runtime / CLI 가 동일한
    canonical data root 를 본다.

helper 자체는 ``Config`` 로딩이 부수효과(예: secrets.env 의 fernet key 검증)를
일으킬 수 있으므로, override 가 있을 때는 ``Config`` 로딩을 건너뛰어 불필요한
부수효과를 피한다.
"""

from __future__ import annotations

import click

from ante.config.config import Config


def resolve_data_path(ctx: click.Context | None, override: str | None) -> str:
    """`--data-path` 옵션 값을 config-resolved data root 로 정합한다.

    Args:
        ctx: Click 컨텍스트. ``None`` 이면 현재 컨텍스트를 자동 조회한다
            (`get_config_dir` 가 내부에서 처리).
        override: 사용자가 명시한 `--data-path` 값. ``None`` 또는 빈 문자열이면
            config-resolved default 로 폴백한다.

    Returns:
        - override 가 명시되면 그 값을 변형 없이 그대로 반환.
        - 미명시이면 ``Config.resolve_path("data.path", "data").resolve()`` 의
          문자열(절대 경로).
    """
    if override is not None and override != "":
        return override
    # Lazy import: ante.cli.main 은 본 모듈을 사용하는 commands 모듈을
    # import 하므로 top-level import 로 두면 순환 import 가 된다.
    from ante.cli.main import get_config_dir

    cfg = Config.load(config_dir=get_config_dir(ctx))
    return str(cfg.resolve_path("data.path", "data").resolve())
