"""CLI -> IPC 공통 헬퍼.

서버가 실행 중인 상태에서 CLI 커맨드를 IPC로 전달하기 위한
유틸리티 함수를 제공한다.
"""

from __future__ import annotations

from pathlib import Path

import click

from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError


def _get_socket_path() -> str:
    """Config에서 DB 경로를 읽어 소켓 파일 경로를 반환."""
    from ante.config import Config

    config = Config.load()
    db_path = config.get("db.path", "db/ante.db")
    return str(Path(db_path).parent / "ante.sock")


async def ipc_send(command: str, args: dict, actor: str = "cli") -> dict:
    """IPC 커맨드를 서버에 전송하고 결과를 반환.

    성공 시 result dict를 반환하고,
    서버 미실행/타임아웃/실행 오류 시 click.ClickException을 발생시킨다.

    Returns:
        서버 응답의 "result" 필드 (status == "ok"인 경우).

    Raises:
        click.ClickException: 서버 미실행, 타임아웃, 서버 측 실행 오류 시.
    """
    try:
        client = IPCClient(socket_path=_get_socket_path())
        response = await client.send(command, args, actor)
    except ServerNotRunningError:
        raise click.ClickException(
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
        )
    except IPCTimeoutError:
        raise click.ClickException("서버 응답 시간 초과")

    if response.get("status") == "error":
        error = response.get("error", {})
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "알 수 없는 오류")
        raise click.ClickException(f"{code}: {message}")

    return response.get("result", {})
