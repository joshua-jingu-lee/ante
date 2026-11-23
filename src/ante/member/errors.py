"""Member 모듈 예외."""


class MemberError(Exception):
    """Member 기본 예외."""


class PermissionDeniedError(MemberError):
    """권한 부족 — master만 수행 가능한 작업을 비-master가 시도.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"PERMISSION_DENIED"`` 로 surface 하도록 한다.
    """

    code: str = "PERMISSION_DENIED"


class MemberNotFoundError(MemberError, ValueError):
    """멤버를 찾을 수 없음.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_NOT_FOUND"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_NOT_FOUND"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"존재하지 않는 멤버: {member_id}")


class MemberStateConflictError(MemberError, ValueError):
    """멤버 state flow 위반.

    ``suspend`` 메서드가 이미 SUSPENDED 인 멤버 (혹은 ACTIVE 가 아닌 상태)
    를 재정지하려 할 때, ``reactivate`` 메서드가 이미 ACTIVE 인 멤버 (혹은
    SUSPENDED 가 아닌 상태) 를 재활성화하려 할 때 raise 한다.

    state-conflict 는 권한 부족이 아닌 상태 흐름 위반이다. ``revoke`` 의
    재폐기도 같다. 세 메서드의 state 체크는 모두 인라인 typed raise 다.
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


class MemberAlreadyExistsError(MemberError, ValueError):
    """동일 ``member_id`` 멤버가 이미 등록됨.

    bootstrap_master 의 ``master가 이미 존재합니다`` ValueError 는 ``ante
    init`` 별도 표면이다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_ALREADY_EXISTS"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_ALREADY_EXISTS"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"이미 존재하는 member_id: {member_id}")


class ReservedMemberIdError(MemberError, ValueError):
    """reserved ``system:`` prefix member_id 등록 거부.

    ``register`` 가 ``member_id.startswith("system:")`` 등록 요청을 받았을 때
    raise 한다. ``system:`` 는 system audit sentinel 네임스페이스
    (``system:kill_switch`` / ``system:recovery``) 전용 reserved prefix 이며,
    사용자/agent member_id 가 이를 점유하면 audit 행위자 식별이 오염된다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_ID_RESERVED"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_ID_RESERVED"

    def __init__(self, member_id: str) -> None:
        self.member_id = member_id
        super().__init__(f"예약된 member_id prefix 는 사용할 수 없습니다: {member_id}")


class MemberInvalidRecoveryCredentialError(MemberError, ValueError, PermissionError):
    """recovery credential validation 거부.

    ``reset_password`` 가 잘못된 recovery key 를 받았을 때, 또는
    ``regenerate_recovery_key`` 가 잘못된 현재 패스워드를 받았을 때 raise
    한다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_INVALID_RECOVERY_CREDENTIAL"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_INVALID_RECOVERY_CREDENTIAL"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MemberInvalidEmojiError(MemberError, ValueError):
    """emoji 형식 검증 거부.

    ``_validate_emoji_unique`` (emoji 중복 거부) 는 별도 표면이다.
    ``register`` / ``bootstrap_master``
    가 호출하는 형식 검증도 동일 typed exception 으로 자동 정렬된다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_INVALID_EMOJI"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_INVALID_EMOJI"


class MemberMasterProtectedError(MemberError, PermissionError):
    """master 보호 위반.

    ``MemberService._assert_not_master`` 가 master role 멤버에 대한
    ``suspend`` / ``revoke`` 요청을 거부할 때 raise 한다. master 보호 동작
    자체는 그대로 유지되며, raise 타입만 typed exception 으로 좁힌다.

    클래스 레벨 ``code`` 속성은 CLI/IPC envelope 이 안정 코드
    ``"MEMBER_MASTER_PROTECTED"`` 로 surface 하도록 한다.
    """

    code: str = "MEMBER_MASTER_PROTECTED"
