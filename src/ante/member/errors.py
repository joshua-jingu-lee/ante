"""Member 모듈 예외."""


class MemberError(Exception):
    """Member 기본 예외."""


class PermissionDeniedError(MemberError):
    """권한 부족 — master만 수행 가능한 작업을 비-master가 시도."""
