"""CLI approval 서브커맨드 --format 옵션 등록 테스트.

이슈 #1078: approval 서브커맨드에 @format_option 누락으로
`--format json` 사용 시 'No such option: --format' 발생하던 문제 검증.
"""

from __future__ import annotations

import click
import pytest

from ante.cli.commands.approval import (
    approval_list,
    approve,
    cancel,
    info,
    reject,
    reopen,
    request,
    review,
)

_SUBCOMMANDS = [
    ("request", request),
    ("list", approval_list),
    ("info", info),
    ("review", review),
    ("reopen", reopen),
    ("cancel", cancel),
    ("approve", approve),
    ("reject", reject),
]


class TestApprovalFormatOptionRegistered:
    """모든 approval 서브커맨드에 --format 옵션이 등록되어 있는지 검증."""

    @pytest.mark.parametrize(
        "name,cmd",
        _SUBCOMMANDS,
        ids=[s[0] for s in _SUBCOMMANDS],
    )
    def test_format_option_exists(self, name: str, cmd: click.Command) -> None:
        """approval {name} 커맨드에 --format 옵션이 존재해야 한다."""
        param_names = [p.name for p in cmd.params]
        assert "output_format" in param_names, (
            f"approval {name} 커맨드에 --format 옵션이 없습니다"
        )

    @pytest.mark.parametrize(
        "name,cmd",
        _SUBCOMMANDS,
        ids=[s[0] for s in _SUBCOMMANDS],
    )
    def test_format_option_choices(self, name: str, cmd: click.Command) -> None:
        """--format 옵션은 text/json 중 선택 가능해야 한다."""
        fmt_param = next(p for p in cmd.params if p.name == "output_format")
        assert isinstance(fmt_param.type, click.Choice)
        assert "json" in fmt_param.type.choices
        assert "text" in fmt_param.type.choices
