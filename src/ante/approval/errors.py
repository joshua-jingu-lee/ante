"""Approval 모듈 예외.

Refs #1798: ``ApprovalNotFoundError`` 를 신규 도입해 service 가 missing
approval 을 ``ValueError`` 대신 typed exception 으로 raise 한다. IPC
``server.py`` 의 ``getattr(e, "code", "EXECUTION_ERROR")`` envelope 이
``APPROVAL_NOT_FOUND`` 로 변환한다. CLI ``approval cancel-invalid`` 도
``getattr(e, "code", ...)`` 패턴으로 typed code 를 surface 한다.

``ApprovalValidationError`` 는 호환을 위해 ``ante.approval.models`` 에
계속 존재하며, 본 모듈은 cleanup/cancel 표면의 typed not-found 만 추가
한다.
"""


class ApprovalError(Exception):
    """Approval 기본 예외."""

    pass


class ApprovalNotFoundError(ApprovalError):
    """결재 요청을 찾을 수 없음 (#1798).

    클래스 레벨 ``code`` 속성은 IPC 서버 envelope 이 안정 코드
    ``"APPROVAL_NOT_FOUND"`` 로 surface 하도록 한다. ``ValueError`` 와
    분리해 호출자가 vocabulary/state 검증 오류와 not-found 의미를
    명확히 구분할 수 있게 한다.
    """

    code: str = "APPROVAL_NOT_FOUND"

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"결재 요청을 찾을 수 없음: {approval_id}")
