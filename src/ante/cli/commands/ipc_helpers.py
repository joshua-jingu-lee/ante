"""CLI IPC 공통 헬퍼.

IPCClient를 통해 실행 중인 서버에 커맨드를 전송하는 유틸리티.
"""

from __future__ import annotations

from pathlib import Path

import click

from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError


def get_socket_path(config_dir: Path | None = None) -> str:
    """IPC 소켓 경로 반환.

    Refs #1157: ``runtime.socket_path`` resolver를 통해 ``<config_dir>/run/
    ante.sock``(default)을 산출한다. ``[runtime] socket_path`` override가
    ``system.toml``에 있으면 사용자 값이 우선한다.

    Args:
        config_dir: 선택적 설정 디렉토리. None이면 현재 Click 컨텍스트의
            ``ctx.obj["config_dir"]``을 자동 추출하고, 그것도 없으면
            ``resolve_config_dir()`` 폴백으로 자동 탐색한다.

    Returns:
        IPC 유닉스 소켓 절대 경로 문자열.
    """
    from ante.config import Config

    if config_dir is None:
        # 호출자가 명시하지 않으면 현재 Click 컨텍스트에서 자동 추출
        from ante.cli.main import get_config_dir

        config_dir = get_config_dir()

    config = Config.load(config_dir=config_dir)
    return str(config.runtime_socket_path())


# _ipc.py 호환 별칭
_get_socket_path = get_socket_path


async def ipc_send(
    command: str,
    args: dict,
    actor: str = "cli",
    config_dir: Path | None = None,
) -> dict:
    """IPC 커맨드 전송. 서버 미기동 시 사용자 친화적 에러 출력.

    Args:
        command: 실행할 커맨드 이름 (예: "system.halt")
        args: 커맨드 인자
        actor: 요청자 식별자 (기본 "cli")
        config_dir: 선택적 설정 디렉토리. None이면 현재 Click 컨텍스트에서
            자동 추출되어 IPC 소켓 경로 계산에 전파된다.

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
        # #1754: middleware ClickException fallback 이 IPC 미기동/타임아웃
        # 케이스를 stable code 로 매핑할 수 있도록 ``ipc_error_code`` /
        # ``ipc_error_message`` 속성을 부착한다. ``raise`` 시그니처와 메시지
        # 본문은 기존 호출자(__str__ 가 그대로 사용자 메시지를 반환)와의
        # 호환을 위해 변경하지 않는다 (서버 error envelope 경로의 attrs
        # 부착 #1673 과 동형 패턴).
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

    # 서버 응답에서 에러 상태 처리
    if response.get("status") == "error":
        error = response.get("error", {})
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "알 수 없는 오류")
        # 기존 소비자 호환: ``str(exc)`` 는 종전과 동일하게
        # ``"{code}: {message}"`` 를 반환한다(동작 불변, 순수 additive).
        # config set 처럼 JSON envelope를 직접 만들어야 하는 호출자가
        # 원본 code/message 를 split 없이 복원할 수 있도록 속성을
        # 부착한다 (#1673 택A — ipc_send 변경이 다수 명령에 회귀를
        # 유발하지 않도록 raise 문자열·시그니처는 그대로 둔다).
        exc = click.ClickException(f"{code}: {message}")
        exc.ipc_error_code = code  # type: ignore[attr-defined]
        exc.ipc_error_message = message  # type: ignore[attr-defined]
        raise exc

    # "result" 키가 있으면 inner result만, 없으면 전체 응답 반환
    return response.get("result", response)
