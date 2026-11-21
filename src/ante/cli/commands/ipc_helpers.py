"""CLI IPC 공통 헬퍼."""

from __future__ import annotations

from pathlib import Path

import click

from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError


def get_socket_path(config_dir: Path | None = None) -> str:
    """IPC 소켓 경로 반환.

    ``runtime.socket_path`` resolver를 통해 ``<config_dir>/run/ante.sock``
    (default)을 산출한다. ``[runtime] socket_path`` override가 ``system.toml``
    에 있으면 사용자 값이 우선한다.

    Returns:
        IPC 유닉스 소켓 절대 경로 문자열.
    """
    from ante.config import Config

    if config_dir is None:
        from ante.cli.main import get_config_dir

        config_dir = get_config_dir()

    config = Config.load(config_dir=config_dir)
    return str(config.runtime_socket_path())


_get_socket_path = get_socket_path


async def ipc_send(
    command: str,
    args: dict,
    actor: str = "cli",
    config_dir: Path | None = None,
) -> dict:
    """IPC 커맨드 전송. 서버 미기동 시 사용자 친화적 에러 출력.

    Returns:
        서버 응답 dict.
        - "result" 키가 존재하면 해당 값만 반환 (변경 커맨드).
        - 그 외에는 전체 응답을 반환 (기존 호환).

    Raises:
        click.ClickException: 서버 미기동 또는 타임아웃
    """
    try:
        client = IPCClient(socket_path=get_socket_path(config_dir=config_dir))
        response = await client.send(command, args, actor)
    except ServerNotRunningError:
        exc = click.ClickException(
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
        )
        exc.ipc_error_code = "IPC_SERVER_NOT_RUNNING"  # type: ignore[attr-defined]
        exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
        raise exc
    except IPCTimeoutError:
        exc = click.ClickException("서버 응답 시간 초과")
        exc.ipc_error_code = "IPC_TIMEOUT"  # type: ignore[attr-defined]
        exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
        raise exc

    if response.get("status") == "error":
        error = response.get("error", {})
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "알 수 없는 오류")
        exc = click.ClickException(f"{code}: {message}")
        exc.ipc_error_code = code  # type: ignore[attr-defined]
        exc.ipc_error_message = message  # type: ignore[attr-defined]
        raise exc

    return response.get("result", response)
