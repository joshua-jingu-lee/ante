"""Account 모듈 예외."""


class AccountError(Exception):
    """Account 기본 예외."""

    pass


class AccountNotFoundError(AccountError):
    """계좌를 찾을 수 없음."""

    pass


class AccountAlreadyExistsError(AccountError):
    """동일 account_id가 이미 존재."""

    pass


class InvalidBrokerTypeError(AccountError):
    """등록되지 않은 broker_type."""

    pass


class MissingCredentialsError(AccountError):
    """필수 credentials 키 누락."""

    pass


class AccountAlreadySuspendedError(AccountError):
    """이미 정지 상태인 계좌에 대한 재정지 시도."""

    pass


class AccountDeletedError(AccountError):
    """DELETED 상태 계좌에 대한 수정/활성화 시도."""

    pass


class AccountSuspendedError(AccountError):
    """정지(SUSPENDED) 상태 계좌에 대한 작업 시도."""

    pass


class InvalidAccountIdError(AccountError):
    """account_id 형식이 올바르지 않음."""

    pass


class AccountImmutableFieldError(AccountError):
    """불변 필드 수정 시도."""

    pass


class BrokerReconnectFailedError(AccountError):
    """계좌 설정 변경 후 브로커 재연결에 실패했음.

    update() 자체는 DB에 반영되지만, 새 자격증명/설정으로 broker connect()가
    실패했을 때 발생한다. 운영자는 설정을 교정한 뒤 재시도해야 한다.
    """

    pass


class AccountHasActiveBotsError(AccountError):
    """delete() 시 해당 계좌에 활성(non-deleted) 봇이 남아 있음 (#1139).

    cold-path AccountService.delete()는 status mutation 전에 ``bots`` 테이블을
    조회하여 동일 ``account_id``의 활성 봇이 있으면 삭제를 거부한다. 이는
    봇이 가리키는 계좌가 사라져 orphan bot이 되는 무결성 위반을 막는다.
    운영자는 봇을 먼저 제거(`ante bot remove ...`)한 뒤 계좌를 삭제해야 한다.
    """

    def __init__(self, account_id: str, bot_count: int) -> None:
        self.account_id = account_id
        self.bot_count = bot_count
        super().__init__(
            f"계좌 '{account_id}'에 활성 봇이 {bot_count}개 남아 있어 "
            f"삭제할 수 없습니다."
        )


# 하위 호환용 별칭
AccountDeletedException = AccountDeletedError
