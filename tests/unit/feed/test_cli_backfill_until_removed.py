"""``ante feed run backfill`` 의 ``--until`` ghost 옵션 제거 회귀 (#1690).

스펙(`docs/specs/cli/03-commands.md`, `docs/specs/data-feed/06-cli.md`)에는
`--until` 옵션이 정의돼 있지 않으며, 구현체에서도 ghost 상태였다(`until`
값은 어떤 소비자에게도 전달되지 않았다). 본 PR에서 Click 정의·테스트·생성
reference 모두에서 제거했으며, 그 후 다음 두 invariant가 깨지지 않아야
한다:

1. ``ante feed run backfill --until <…>`` 호출은 Click의 unknown-option
   경로로 실패한다 (별 Ante 구조화 에러 코드 신설 없이 Click 표준 메시지).
2. ``ante feed run backfill --help`` 출력에 ``--until`` 토큰이 나타나지
   않는다.

Click 표준 메시지 문구(``No such option: '--until'``)에 brittle하게 의존
하지 않도록, ``exit_code != 0`` + ``--until`` 토큰 substring + 표준
unknown-option 시그니처(``No such option`` / ``Got unexpected``) 가운데
하나가 포함되는지 substring 매칭으로 잠근다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """인증된 상태의 CliRunner. stderr 분리 캡처."""
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx: object) -> None:
                import click

                ctx = click.get_current_context()
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def initialized_data_path(tmp_path: Path) -> str:
    """초기화된 데이터 디렉토리 경로."""
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)

    config_toml = feed_dir / "config.toml"
    config_toml.write_text(
        "[schedule]\n"
        'daily_at = "16:00"\n'
        'backfill_at = "01:00"\n'
        'backfill_since = "2024-01-01"\n'
        "\n"
        "[guard]\n"
        "blocked_days = []\n"
        'blocked_hours = ["09:00-15:30"]\n'
        "pause_during_trading = true\n"
    )

    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()

    return str(data_dir)


class TestBackfillUntilRemoved:
    """``--until`` 옵션이 Click 정의·help 출력 모두에서 부재함을 잠근다 (#1690)."""

    def test_unknown_option_rejected_by_click(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """``--until <date>``는 Click unknown-option 경로로 종료된다.

        - exit_code != 0
        - 출력에 ``--until`` 토큰이 unknown-option 메시지와 함께 나타난다
        - Click 표준 unknown-option 시그니처 substring(``No such option``
          또는 ``Got unexpected``) 가운데 하나가 포함된다
        - 별 Ante 구조화 에러 코드(예: CLI_UNSUPPORTED_OPTION)를 신설하지
          않으며, CLI_INVALID_DATE도 발생하지 않는다 (Click이 먼저 차단).
        """
        result = runner.invoke(
            cli,
            [
                "feed",
                "run",
                "backfill",
                "--data-path",
                initialized_data_path,
                "--until",
                "2024-01-05",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code != 0
        combined = (result.stdout or "") + (result.stderr or "")
        assert "--until" in combined
        # Click 표준 unknown-option 시그니처 가운데 하나가 포함된다
        assert ("No such option" in combined) or ("Got unexpected" in combined)
        # 본 PR에서 신설하지 않기로 한 가짜 코드가 등장하지 않아야 한다
        assert "CLI_UNSUPPORTED_OPTION" not in combined
        # Click의 unknown-option 단계에서 차단되므로 date validator의 코드도
        # 발생하지 않는다
        assert "CLI_INVALID_DATE" not in combined

    def test_help_output_omits_until_token(self, runner: CliRunner) -> None:
        """``ante feed run backfill --help`` 출력에 ``--until``이 부재."""
        result = runner.invoke(
            cli,
            ["feed", "run", "backfill", "--help"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        combined = (result.stdout or "") + (result.stderr or "")
        assert "--until" not in combined
        # 잔존 옵션은 보존돼야 한다 — invariant 보강 (선택)
        assert "--since" in combined
        assert "--data-path" in combined
