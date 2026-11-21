"""#2673: ``ante feed`` 명령 모듈의 자리가 바뀌어도 유지되는 동작."""

from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType

import click
import pytest

from ante.cli.main import cli

EXPECTED_FEED_PATHS = [
    "feed",
    "feed config",
    "feed config check",
    "feed config list",
    "feed config set",
    "feed init",
    "feed inject",
    "feed run",
    "feed run backfill",
    "feed run daily",
    "feed start",
    "feed status",
]


def _feed_module() -> ModuleType:
    group = cli.commands["feed"]
    assert group.callback is not None
    return sys.modules[group.callback.__module__]


def _walk(cmd: click.Command, path: list[str]):
    yield " ".join(path)
    if isinstance(cmd, click.Group):
        for name in sorted(cmd.commands):
            yield from _walk(cmd.commands[name], [*path, name])


@pytest.fixture
def restore_feed_logger_level():
    feed_logger = logging.getLogger("ante.feed")
    original = feed_logger.level
    yield
    feed_logger.setLevel(original)


def test_feed_command_logger_name() -> None:
    assert _feed_module().logger.name == "ante.feed.cli"


@pytest.mark.parametrize(
    ("log_level", "warning_enabled"),
    [("ERROR", False), ("WARNING", True)],
)
def test_feed_command_logger_follows_applied_level(
    restore_feed_logger_level: None, log_level: str, warning_enabled: bool
) -> None:
    module = _feed_module()
    module._apply_log_level({"general": {"log_level": log_level}}, None)

    assert module.logger.isEnabledFor(logging.WARNING) is warning_enabled


def test_registered_group_is_module_feed() -> None:
    assert cli.commands["feed"] is _feed_module().feed


def test_feed_command_paths() -> None:
    assert list(_walk(cli.commands["feed"], ["feed"])) == EXPECTED_FEED_PATHS


def test_feed_command_module_path() -> None:
    assert _feed_module().__name__ == "ante.cli.commands.feed"


def test_old_feed_cli_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ante.feed.cli")
