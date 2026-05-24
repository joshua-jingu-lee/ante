"""Approval 모듈 예외.

Refs #1798: ``ApprovalNotFoundError`` 를 신규 도입해 service 가 missing
approval 을 ``ValueError`` 대신 typed exception 으로 raise 한다. IPC
``server.py`` 의 ``getattr(e, "code", "EXECUTION_ERROR")`` envelope 이
``APPROVAL_NOT_FOUND`` 로 변환한다. CLI ``approval cancel-invalid`` 도
``getattr(e, "code", ...)`` 패턴으로 typed code 를 surface 한다.

Refs #1813 (Group Q sweep): ``ApprovalStatusConflictError`` 를 신규 도입해
``approve``/``reject`` 표면의 status flow violation (rejected → 재reject,
approved → 재approve 등) 을 ``ValueError`` 대신 typed exception 으로
raise 한다. IPC envelope 이 ``APPROVAL_STATUS_CONFLICT`` 안정 코드를
surface 한다. ``ValueError`` 다중상속으로 기존 ``except ValueError`` caller
(CLI ``approval approve`` line 629 fallback 등) 회귀를 방지한다.

``ApprovalValidationError`` 는 호환을 위해 ``ante.approval.models`` 에
계속 존재하며, 본 모듈은 cleanup/cancel 표면의 typed not-found + Group Q
state-conflict 만 추가한다.
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


class ApprovalStatusConflictError(ApprovalError, ValueError):
    """결재 status flow 위반 (#1813 Group Q sweep).

    ``approve``/``reject`` 메서드가 현재 status 가 허용 전이 집합에 포함되지
    않을 때 raise 한다. 예시:

    - ``rejected`` 상태에서 ``reject`` 재시도 (이미 거절됨)
    - ``approved`` 상태에서 ``approve`` 재시도 (이미 승인됨)
    - ``cancelled`` 상태에서 ``approve``/``reject`` 시도

    ``ApprovalError`` 와 ``ValueError`` 다중상속으로 둔다 — ``approve``/
    ``reject`` 메서드 이전에 기존 ``except ValueError`` 로 status conflict
    를 받아온 caller (CLI ``approval approve`` line 629 generic fallback,
    test mock 시나리오) 가 회귀 없이 동일하게 잡히도록 한다.
    ``except ApprovalStatusConflictError`` 를 먼저 둔 caller 는 typed 분기
    를 우선 매칭해 안정 코드 envelope 을 surface 한다 (Python MRO 보장).

    IPC envelope 은 ``getattr(e, "code", "EXECUTION_ERROR")`` 로
    ``"APPROVAL_STATUS_CONFLICT"`` 코드를 자동 노출한다.
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
