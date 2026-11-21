"""Approval 모듈 예외."""


class ApprovalError(Exception):
    """Approval 기본 예외."""

    pass


class ApprovalNotFoundError(ApprovalError):
    """결재 요청을 찾을 수 없음.

    클래스 레벨 ``code`` 속성은 IPC 서버 envelope 이 안정 코드
    ``"APPROVAL_NOT_FOUND"`` 로 surface 하도록 한다. ``ValueError`` 와
    분리해 호출자가 vocabulary/state 검증 오류와 not-found 의미를
    명확히 구분할 수 있게 한다.
    """

    code: str = "APPROVAL_NOT_FOUND"

    def __init__(self, approval_id: str) -> None:
        self.approval_id = approval_id
        super().__init__(f"결재 요청을 찾을 수 없음: {approval_id}")


class ApprovalStatusConflictError(ApprovalError, ValueError):
    """결재 status flow 위반.

    ``approve``/``reject`` 메서드가 현재 status 가 허용 전이 집합에 포함되지
    않을 때 raise 한다. 예시:

    - ``rejected`` 상태에서 ``reject`` 재시도 (이미 거절됨)
    - ``approved`` 상태에서 ``approve`` 재시도 (이미 승인됨)
    - ``cancelled`` 상태에서 ``approve``/``reject`` 시도
    """

    code: str = "APPROVAL_STATUS_CONFLICT"

    def __init__(
        self,
        approval_id: str,
        current_status: str,
        requested_action: str,
    ) -> None:
        self.approval_id = approval_id
        self.current_status = current_status
        self.requested_action = requested_action
        super().__init__(
            f"결재 '{approval_id}' 상태 '{current_status}' 에서 "
            f"'{requested_action}' 작업을 수행할 수 없습니다."
        )
