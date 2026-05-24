"""Member 모듈 예외.

Refs #1805: ``MemberNotFoundError`` 를 신규 도입해 service 의 missing-member
경로가 ``ValueError`` 대신 typed exception 을 raise 한다. CLI 6 mutation
surface (set-emoji/suspend/reactivate/revoke/rotate-token, register 는 not-found
경로 부재) 가 envelope 코드 ``"MEMBER_NOT_FOUND"`` 를 stable 하게 surface 한다.
``ApprovalNotFoundError`` (#1798) 와 동형 패턴이다.
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
