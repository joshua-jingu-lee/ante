"""CLI IPC 공통 헬퍼."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError


def get_socket_path(config_dir: Path | None = None) -> str:
    """IPC 소켓 경로 반환.

    ``runtime.socket_path`` resolver를 통해 ``<config_dir>/run/ante.sock``
    (default)을 산출한다. ``[runtime] socket_path`` override가 ``system.toml``
    에 있으면 사용자 값이 우선한다.
    """
    from ante.config import Config

    if config_dir is None:
        from ante.cli.main import get_config_dir

        config_dir = get_config_dir()

    config = Config.load(config_dir=config_dir)
    return str(config.runtime_socket_path())


_get_socket_path = get_socket_path

_MALFORMED_RESPONSE_MESSAGE = "IPC 응답이 계약과 다릅니다"
_TIMEOUT_MESSAGE = "서버 응답 시간 초과"


def _with_outcome_hint(message: str, unknown_outcome: str) -> str:
    """결과 미상 안내가 있으면 ``<기본 문구> — <안내>``로 잇는다."""
    return f"{message} — {unknown_outcome}" if unknown_outcome else message


async def ipc_send(
    command: str,
    args: dict[str, Any],
    actor: str = "cli",
    config_dir: Path | None = None,
    *,
    required: tuple[str, ...] = (),
    unknown_outcome: str = "",
) -> dict[str, Any]:
    """IPC 커맨드를 보내고 성공 응답의 ``result``를 돌려준다.

    응답 모양이 계약과 다르거나 ``required`` 키가 ``result``에 없으면
    ``UNKNOWN``인 ``IPCRemoteError``로 실패한다. ``unknown_outcome``은
    이 실패와 시간 초과의 메시지 뒤에만 덧붙인다.

    Raises:
        IPCServerNotRunningError | IPCClientTimeoutError | IPCRemoteError
    """
    try:
        client = IPCClient(socket_path=get_socket_path(config_dir=config_dir))
        response = await client.send(command, args, actor)
    except ServerNotRunningError:
        raise IPCServerNotRunningError(
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
        )
    except IPCTimeoutError:
        raise IPCClientTimeoutError(
            _with_outcome_hint(_TIMEOUT_MESSAGE, unknown_outcome)
        )

    malformed = _with_outcome_hint(_MALFORMED_RESPONSE_MESSAGE, unknown_outcome)
    if not isinstance(response, dict):
        raise IPCRemoteError("UNKNOWN", malformed)

    if response.get("status") == "error":
        error = response.get("error")
        if not isinstance(error, dict):
            error = {}
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "알 수 없는 오류")
        raise IPCRemoteError(code, message)

    result = response.get("result")
    if (
        response.get("status") != "ok"
        or not isinstance(result, dict)
        or any(key not in result for key in required)
    ):
        raise IPCRemoteError("UNKNOWN", malformed)
    return result
