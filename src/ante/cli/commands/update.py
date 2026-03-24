"""업데이트 관련 유틸리티."""

from __future__ import annotations

import os


def check_server_running() -> bool:
    """서버가 실행 중인지 PID 파일로 확인. stale PID는 무시."""
    from ante.main import read_pid_file

    pid = read_pid_file()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # 프로세스 존재 확인
        return True
    except (ProcessLookupError, PermissionError):
        return False
