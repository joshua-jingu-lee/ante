"""CLI IPC 공통 헬퍼.

IPCClient를 통해 실행 중인 서버에 커맨드를 전송하는 유틸리티.
"""

from __future__ import annotations

from pathlib import Path

import click

from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError


def get_socket_path() -> str:
    """IPC 소켓 경로 반환.

    Config에서 db.path를 읽고, 그 부모 디렉토리에 ante.sock을 배치한다.
    """
    from ante.config import Config

    config = Config.load()
    db_path = config.get("db.path", "db/ante.db")
    return str(Path(db_path).parent / "ante.sock")


# _ipc.py 호환 별칭
_get_socket_path = get_socket_path


async def ipc_send(command: str, args: dict, actor: str = "cli") -> dict:
    """IPC 커맨드 전송. 서버 미기동 시 사용자 친화적 에러 출력.

    Args:
        command: 실행할 커맨드 이름 (예: "system.halt")
        args: 커맨드 인자
        actor: 요청자 식별자 (기본 "cli")

    Returns:
        서버 응답 dict.
        - "result" 키가 존재하면 해당 값만 반환 (변경 커맨드).
        - 그 외에는 전체 응답을 반환 (기존 호환).

    Raises:
        click.ClickException: 서버 미기동 또는 타임아웃
    """
    try:
        client = IPCClient(socket_path=get_socket_path())
        response = await client.send(command, args, actor)
    except ServerNotRunningError:
        raise click.ClickException(
            "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
        )
    except IPCTimeoutError:
        raise click.ClickException("서버 응답 시간 초과")

    # 서버 응답에서 에러 상태 처리
    if response.get("status") == "error":
        error = response.get("error", {})
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "알 수 없는 오류")
        raise click.ClickException(f"{code}: {message}")

    # "result" 키가 있으면 inner result만, 없으면 전체 응답 반환
    return response.get("result", response)
