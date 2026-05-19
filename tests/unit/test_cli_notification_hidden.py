"""notification 빈 그룹의 public 표면(root help) 숨김 회귀 테스트 (#1682).

oracle A7: `ante --help` 가 public leaf 가 없는 `notification` 그룹을
광고하지만 `ante notification --help` 에는 실행 가능한 subcommand 가
없었다(dead-end). `@click.group(hidden=True)` 로 root help 에서 숨기되,
`cli.add_command(notification)` 은 유지하여 직접 invoke 는 보존한다.
"""

from __future__ import annotations

import click
from click.testing import CliRunner

from ante.cli.main import cli


def _commands_section_lines(help_text: str) -> list[str]:
    """`--help` 출력의 ``Commands:`` 섹션 라인만 추출한다."""
    lines = help_text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == "Commands:":
            in_section = True
            continue
        if in_section:
            # Click 은 Commands 섹션이 출력의 마지막 블록이다.
            if line and not line.startswith(" "):
                break
            out.append(line)
    return out


class TestNotificationHidden:
    """notification 그룹이 hidden 이지만 직접 invoke 는 보존됨을 검증."""

    def test_notification_group_is_hidden(self) -> None:
        """introspection: ``cli.commands['notification'].hidden is True``."""
        notification = cli.commands["notification"]
        assert isinstance(notification, click.Group)
        assert notification.hidden is True

    def test_root_help_does_not_advertise_notification(self) -> None:
        """root ``--help`` 의 Commands 섹션에 notification 라인 부재.

        oracle probe ``root_advertises_group`` 의 동치(→False).
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        section = _commands_section_lines(result.output)
        # Commands 섹션 라인 단위로 notification 토큰 부재
        for line in section:
            tokens = line.split()
            assert "notification" not in tokens, (
                f"root help Commands 섹션에 notification 노출: {line!r}"
            )
        # 전체 출력에서도 command-list 항목으로 등장하지 않음
        assert "\n  notification " not in result.output

    def test_notification_direct_invoke_preserved(self) -> None:
        """직접 invoke 보존: ``ante notification --help`` exit_code == 0."""
        runner = CliRunner()
        result = runner.invoke(cli, ["notification", "--help"])
        assert result.exit_code == 0
        assert "notification" in result.output

    def test_other_groups_still_advertised(self) -> None:
        """회귀 0: 다른 그룹은 여전히 root help 에 노출된다."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for group_name in ("broker", "config", "bot", "strategy", "trade"):
            grp = cli.commands[group_name]
            assert isinstance(grp, click.Group)
            assert grp.hidden is False
            assert group_name in result.output, (
                f"root help 에 {group_name} 그룹이 사라짐 (회귀)"
            )
