"""Cold-path runtime guard helpers shared by CLI commands."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.cli.formatter import OutputFormatter

ACCOUNT_COLD_PATH_BLOCKED_CODE = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"
BOT_COLD_PATH_REMOVE_BLOCKED_CODE = "BOT_COLD_PATH_REMOVE_REQUIRES_STOPPED_SERVER"


def is_active_runtime(
    *,
    kill: Callable[[int, int], None] | None = None,
) -> bool:
    """Return True when the canonical PID/socket pair marks an active runtime.

    Refs #1157/#1160/#1161. The guard uses the current CLI ``config_dir`` and
    treats a matching startup marker as active while the IPC socket is still
    being created. Local imports preserve existing tests that monkeypatch
    ``ante.main.read_pid_file`` and ``ante.cli.commands.ipc_helpers.get_socket_path``.
    """
    from ante.cli.main import get_config_dir
    from ante.config import Config
    from ante.main import _read_starting_marker_pid, read_pid_file

    config_dir = get_config_dir()
    config = Config.load(config_dir=config_dir)

    pid = read_pid_file(config)
    if pid is None:
        return False

    kill_fn = kill or os.kill
    try:
        kill_fn(pid, 0)
    except OSError:
        return False

    from ante.cli.commands.ipc_helpers import get_socket_path

    try:
        socket_path = get_socket_path(config_dir=config_dir)
    except Exception:
        return False

    if Path(socket_path).exists():
        return True

    # Refs #1160: PID alive + matching marker means the server is booting.
    marker_pid = _read_starting_marker_pid(config)
    return marker_pid == pid


def assert_no_active_runtime(
    fmt: OutputFormatter,
    *,
    code: str,
    message: str,
    kill: Callable[[int, int], None] | None = None,
) -> None:
    """Raise ``SystemExit(1)`` after printing ``code`` if runtime is active."""
    if not is_active_runtime(kill=kill):
        return

    fmt.error(f"{code}: {message}", code=code)
    raise SystemExit(1)
