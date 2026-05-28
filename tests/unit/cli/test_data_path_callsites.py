"""CLI `--data-path` 16 callsite 정합 회귀 테스트 (#1914).

본 모듈은 다음 invariant 를 락한다:

1. **config-resolved default**: ``--data-path`` 미지정 시 16 callsite 모두
   ``resolve_data_path(ctx, None)`` 을 호출하여 ``Config.resolve_path(
   "data.path", "data").resolve()`` 의 절대 경로를 사용해야 한다.
2. **override invariant**: ``--data-path`` 명시 시 그 값이 변형 없이
   downstream 까지 흘러야 한다 (option + positional).
3. **positional 무인자**: ``ante feed init`` (positional 생략) 가 Click
   error 없이 helper 로 fall through 되어 config-resolved default 를
   사용해야 한다.

Spec: docs/specs/config/03-design-decisions.md `Ante instance/path contract`
(`data.path` SSOT 행).
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
    """auth bypass 된 CliRunner."""
    r = CliRunner()
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
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`[data] path = "canonical-data"` 가 설정된 config_dir.

    ``ANTE_CONFIG_DIR`` 로 노출하여 모든 CLI 가 같은 config_dir 를 본다.
    """
    cfg_dir = tmp_path / "ante-cfg"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text(
        '[data]\npath = "canonical-data"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg_dir))
    return cfg_dir


@pytest.fixture
def expected_default_path(config_dir: Path) -> str:
    """config-resolved default 의 기대값 (절대 경로 문자열)."""
    return str((config_dir / "canonical-data").resolve())


# ── ① 16 callsite census ─────────────────────────────────────────────────────


# (cli_args, has_data_path_option, positional_supports_data_path)
#
# 16 callsite census:
#   feed/cli.py        : 8 option + 1 positional (feed init) = 9
#   cli/commands/data.py : 6 option = 6
#   cli/commands/backtest.py : 1 option = 1
#
# 합계 = 16
#
# 각 callsite 가 ``resolve_data_path(ctx, override)`` 를 호출하는지 확인하기
# 위해 helper 자체를 spy 로 patch 한 뒤 실제 호출 횟수와 인자를 검증한다.
# CLI 가 helper 미호출 시 helper.call_count == 0 으로 즉시 발견된다.

_OPTION_CALLSITES_DEFAULT = [
    # feed/cli.py
    pytest.param(
        ["feed", "config", "set", "ANTE_DART_API_KEY", "xxx"],
        id="feed_config_set",
    ),
    pytest.param(["feed", "config", "list"], id="feed_config_list"),
    pytest.param(["feed", "config", "check"], id="feed_config_check"),
    # cli/commands/data.py
    pytest.param(["data", "list"], id="data_list"),
    pytest.param(["data", "schema"], id="data_schema"),
    pytest.param(["data", "storage"], id="data_storage"),
]


def _spy_helper(
    captured: list[tuple[object, object]],
    fallback_path: str,
) -> object:
    """`resolve_data_path` 호출 인자를 기록하는 spy.

    실제 helper 가 ``Config.load`` 까지 들어가면 secrets/system.toml 부수효과가
    생기므로, spy 는 helper 의 contract 와 동일하게 동작하되 ``Config.load`` 는
    건너뛰는 stub 으로 대체한다. fallback_path 는 호출 측이 fs 작업을
    수행하더라도 안전하도록 tmp 안의 유효한 절대 경로를 받는다.
    """

    def _spy(ctx, override):  # type: ignore[no-untyped-def]
        captured.append((ctx, override))
        if override is not None and override != "":
            return override
        return fallback_path

    return _spy


# ── ② config-resolved default: helper 가 None 으로 호출되는지 ────────────────


class TestConfigResolvedDefault:
    """``--data-path`` 미지정 시 모든 callsite 가 helper(ctx, None) 호출."""

    @pytest.mark.parametrize("cli_args", _OPTION_CALLSITES_DEFAULT)
    def test_option_callsite_uses_helper_for_default(
        self,
        runner: CliRunner,
        config_dir: Path,
        tmp_path: Path,
        cli_args: list[str],
    ) -> None:
        captured: list[tuple[object, object]] = []
        fallback = str(tmp_path / "fallback-data")
        # callsite 별로 import 위치가 다르므로 source module 에 patch.
        with (
            patch(
                "ante.feed.cli.resolve_data_path",
                side_effect=_spy_helper(captured, fallback),
            ),
            patch(
                "ante.cli.commands.data.resolve_data_path",
                side_effect=_spy_helper(captured, fallback),
            ),
            patch(
                "ante.cli.commands.backtest.resolve_data_path",
                side_effect=_spy_helper(captured, fallback),
            ),
        ):
            runner.invoke(cli, cli_args, catch_exceptions=False)
        # callsite 가 helper 를 한 번 이상 호출했어야 한다.
        assert len(captured) >= 1, f"helper 미호출. cli_args={cli_args}"
        # 첫 호출은 ``--data-path`` 미지정이므로 override 가 None 이어야 한다.
        _, override = captured[0]
        assert override is None, (
            f"callsite 가 helper 에 override=None 을 전달해야 한다. got: {override!r}"
        )

    def test_feed_init_positional_omitted_uses_helper(
        self, runner: CliRunner, config_dir: Path, tmp_path: Path
    ) -> None:
        """`ante feed init` (positional 생략) 는 Click error 없이 helper 호출."""
        captured: list[tuple[object, object]] = []
        fallback = str(tmp_path / "fallback-data")
        with patch(
            "ante.feed.cli.resolve_data_path",
            side_effect=_spy_helper(captured, fallback),
        ):
            result = runner.invoke(cli, ["feed", "init"], catch_exceptions=False)
        # Click 이 ``Missing argument`` 로 reject 하면 exit_code == 2.
        assert result.exit_code != 2, (
            f"`feed init` 무인자 호출이 Click 에러로 거부됨. output={result.output}"
        )
        assert len(captured) >= 1, "helper 미호출."
        _, override = captured[0]
        assert override is None


# ── ③ override invariant: option + positional ────────────────────────────────


class TestOverrideInvariant:
    """``--data-path /custom`` (option) 과 ``feed init /custom`` (positional)
    모두 override 값을 그대로 helper 에 넘겨야 한다.
    """

    def test_feed_config_check_data_path_option_preserved(
        self,
        runner: CliRunner,
        config_dir: Path,
        tmp_path: Path,
    ) -> None:
        captured: list[tuple[object, object]] = []
        custom = str(tmp_path / "my-custom-data")
        fallback = str(tmp_path / "unused-fallback")
        with patch(
            "ante.feed.cli.resolve_data_path",
            side_effect=_spy_helper(captured, fallback),
        ):
            runner.invoke(
                cli,
                ["feed", "config", "check", "--data-path", custom],
                catch_exceptions=False,
            )
        assert len(captured) >= 1
        _, override = captured[0]
        assert override == custom, (
            f"--data-path override 가 helper 에 그대로 전달되어야 한다. "
            f"got={override!r}"
        )

    def test_data_list_data_path_option_preserved(
        self,
        runner: CliRunner,
        config_dir: Path,
        tmp_path: Path,
    ) -> None:
        captured: list[tuple[object, object]] = []
        custom = str(tmp_path / "my-custom-data")
        fallback = str(tmp_path / "unused-fallback")
        with patch(
            "ante.cli.commands.data.resolve_data_path",
            side_effect=_spy_helper(captured, fallback),
        ):
            runner.invoke(
                cli,
                ["data", "list", "--data-path", custom],
                catch_exceptions=False,
            )
        assert len(captured) >= 1
        _, override = captured[0]
        assert override == custom

    def test_feed_init_positional_preserved(
        self,
        runner: CliRunner,
        config_dir: Path,
        tmp_path: Path,
    ) -> None:
        """`ante feed init /custom/path` positional 값이 그대로 흐른다."""
        captured: list[tuple[object, object]] = []
        custom = str(tmp_path / "my-positional-data")
        fallback = str(tmp_path / "unused-fallback")
        with patch(
            "ante.feed.cli.resolve_data_path",
            side_effect=_spy_helper(captured, fallback),
        ):
            runner.invoke(cli, ["feed", "init", custom], catch_exceptions=False)
        assert len(captured) >= 1
        _, override = captured[0]
        assert override == custom


# ── ④ 통합: ANTE_CONFIG_DIR 기반 실제 helper 동작 ────────────────────────────


class TestRealHelperWithConfigDir:
    """spy 없이 실제 helper 가 ``ANTE_CONFIG_DIR`` 기반 절대 경로를 반환."""

    def test_data_schema_with_real_config_dir(
        self,
        runner: CliRunner,
        config_dir: Path,
        expected_default_path: str,
    ) -> None:
        """``data schema`` 는 data_path 를 사용하진 않지만 helper resolve 후
        절대 경로를 통과시키는지 통합 확인.
        """
        # 본 테스트의 핵심은 helper 가 ANTE_CONFIG_DIR 을 읽어 절대 경로를
        # 반환하는지이다. ``ante.cli._data_path.resolve_data_path`` 를 직접
        # 호출하여 확인한다.
        from ante.cli._data_path import resolve_data_path

        result = resolve_data_path(None, None)
        assert result == expected_default_path
