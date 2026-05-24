"""Member 모듈 예외.

Refs #1805: ``MemberNotFoundError`` 를 신규 도입해 service 의 missing-member
경로가 ``ValueError`` 대신 typed exception 을 raise 한다. CLI 6 mutation
surface (set-emoji/suspend/reactivate/revoke/rotate-token, register 는 not-found
경로 부재) 가 envelope 코드 ``"MEMBER_NOT_FOUND"`` 를 stable 하게 surface 한다.
``ApprovalNotFoundError`` (#1798) 와 동형 패턴이다.

Refs #1814 (Group Q sweep): ``MemberStateConflictError`` 를 신규 도입해
``suspend``/``reactivate`` 표면의 state 위반 (이미 SUSPENDED 인 멤버
재정지, 이미 ACTIVE 인 멤버 재활성화) 을 ``PermissionError`` 대신 typed
exception 으로 raise 한다. CLI envelope 이 ``"MEMBER_STATE_CONFLICT"``
안정 코드를 surface 한다. ``ValueError`` 다중상속으로 #1805
``MemberNotFoundError`` 패턴을 따른다.
"""


class MemberError(Exception):
    """Member 기본 예외."""


class PermissionDeniedError(MemberError):
    """권한 부족 — master만 수행 가능한 작업을 비-master가 시도."""


class MemberNotFoundError(MemberError, ValueError):
    """멤버를 찾을 수 없음 (#1805).

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_NOT_FOUND"`` 로 surface 하도록 한다.

    ``MemberError`` 와 ``ValueError`` 의 다중상속으로 둔다 — ``_get_or_raise``
    가 본 서비스 전체에서 공유되는 헬퍼이므로, ``except ValueError`` 로
    missing-member 를 받아온 기존 caller (CLI ``update-scopes``/``reset-password``
    /``regenerate-recovery-key`` 등 5+ 표면, ``test_member.py:582``,
    ``test_cli_member_non_interactive.py`` mock 시나리오) 가 회귀 없이
    동일하게 잡히도록 한다. ``except MemberNotFoundError`` 를 먼저 둔
    caller (#1805 의 5 mutation surface) 는 typed 분기를 우선 매칭해 안정
    코드 envelope 을 surface 한다 (Python MRO 가 보장).
    """

    code: str = "MEMBER_NOT_FOUND"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"존재하지 않는 멤버: {member_id}")


class MemberStateConflictError(MemberError, ValueError):
    """멤버 state flow 위반 (#1814 Group Q sweep).

    ``suspend`` 메서드가 이미 SUSPENDED 인 멤버 (혹은 ACTIVE 가 아닌 상태)
    를 재정지하려 할 때, ``reactivate`` 메서드가 이미 ACTIVE 인 멤버 (혹은
    SUSPENDED 가 아닌 상태) 를 재활성화하려 할 때 raise 한다.

    ``MemberError`` 와 ``ValueError`` 다중상속으로 둔다 — #1805
    ``MemberNotFoundError`` 패턴 1:1 미러. 기존 caller (CLI ``suspend``
    /``reactivate`` 의 ``except (ValueError, PermissionError)`` generic
    fallback line 657/692, ``test_member_service.py:98`` 등) 가 회귀 없이
    동일하게 잡히도록 한다. ``except MemberStateConflictError`` 를 먼저 둔
    caller (#1814 의 2 mutation surface) 는 typed 분기를 우선 매칭해 안정
    코드 envelope 을 surface 한다 (Python MRO 보장).

    이전 (#1814 이전): ``_assert_status`` helper 가 ``PermissionError`` 를
    raise 했으나, state-conflict 는 권한 부족이 아닌 상태 흐름 위반이라
    의미가 모호했다. Group Q sweep 은 ``suspend``/``reactivate`` 의 state
    체크를 인라인 typed raise 로 좁히고, ``revoke`` (plan scope 외, 다중
    상태 허용) 는 기존 ``_assert_status`` helper 를 그대로 사용한다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_STATE_CONFLICT"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_STATE_CONFLICT"

    def __init__(
        self,
        member_id: str,
        current_status: str,
        requested_action: str,
    ) -> None:
        self.member_id = member_id
        self.current_status = current_status
        self.requested_action = requested_action
        super().__init__(
            f"멤버 '{member_id}' 상태 '{current_status}' 에서 "
            f"'{requested_action}' 작업을 수행할 수 없습니다."
        )
