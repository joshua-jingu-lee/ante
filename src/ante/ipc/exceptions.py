"""IPC 모듈 예외 클래스."""


class IPCError(Exception):
    """IPC 기본 예외."""


class ServerNotRunningError(IPCError):
    """서버가 실행 중이지 않을 때 (소켓 파일 없음 또는 연결 거부)."""


class IPCTimeoutError(IPCError):
    """요청 타임아웃 초과."""


class MessageTooLargeError(IPCError):
    """메시지 크기가 최대 제한(1MB)을 초과."""
