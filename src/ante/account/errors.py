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


class InvalidExchangeError(AccountError):
    """canonical vocabulary에 없는 exchange (`*`/non-canonical).

    account 입력 경계는 ``ante.core.exchange`` SSOT의 canonical 5종만
    허용한다(core.md ``## Canonical Exchange Vocabulary`` 축 A). `*` 는
    ``StrategyMeta.exchange`` 전용 wildcard이므로 account 표면에서는 거부된다.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``getattr(e, "code", "EXECUTION_ERROR")``로 안정 코드
    ``"VALIDATION_ERROR"``를 노출하도록 한다(``InvalidAccountIdError`` 와
    동일한 account 검증 에러 SSOT). Web API 라우트는 RFC 7807 422로 매핑된다.
    """

    code: str = "VALIDATION_ERROR"


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
    """account_id 형식 위반 또는 RESTRICTED/INVALID_RUNTIME 예약어 사용.

    클래스 레벨 ``code`` 속성은 IPC 서버가 ``getattr(e, "code", "EXECUTION_ERROR")``로
    안정 코드 ``"VALIDATION_ERROR"``를 노출하도록 한다. ``require_account_id``
    가 이 예외를 raise하는 모든 IPC 경로(bot.create, treasury.allocate/deallocate,
    broker.reconcile 등)가 자동으로 ``VALIDATION_ERROR``로 매핑된다.
    """

    code: str = "VALIDATION_ERROR"


class AccountImmutableFieldError(AccountError):
    """불변 필드 수정 시도."""

    pass


class BrokerReconnectFailedError(AccountError):
    """계좌 설정 변경 후 브로커 재연결에 실패했음.

    update() 자체는 DB에 반영되지만, 새 자격증명/설정으로 broker connect()가
    실패했을 때 발생한다. 운영자는 설정을 교정한 뒤 재시도해야 한다.
    """

    pass


class AccountStructuralChangeRequiresStoppedServerError(AccountError):
    """런타임에 계좌 structural 필드/메서드 변경을 시도했을 때 raise (#1144).

    AccountService는 boot/cold-path/runtime을 구분하는 ``_runtime_started``
    플래그를 갖는다. 서버 부팅이 완료된 뒤 이 플래그가 활성화되면 ``create()``,
    ``delete()``, structural 키를 포함한 ``update()`` 호출은 즉시 이 예외로
    차단된다 — DB는 수정되지 않는다.

    cold-path 경로(``ante account create/delete/set-credentials`` 등)는
    서버를 정지한 뒤에만 사용해야 한다. CLI는 별도의
    ``_assert_no_active_runtime`` 가드(PID alive + IPC socket exists)로
    1차 차단되며, 본 예외는 그 가드를 우회한 비정상 경로의 service-layer
    defense-in-depth 역할이다.

    클래스 레벨 ``code`` 속성은 IPC 서버가 ``getattr(e, "code", "EXECUTION_ERROR")``로
    안정 코드 ``"ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"``를 노출하도록
    한다. Web API 라우트는 별도 catch에서 409 + cold-path detail로 매핑한다.
    """

    code: str = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


class AccountHasActiveBotsError(AccountError):
    """delete() 시 해당 계좌에 활성(non-deleted) 봇이 남아 있음 (#1139).

    cold-path AccountService.delete()는 status mutation 전에 ``bots`` 테이블을
    조회하여 동일 ``account_id``의 활성 봇이 있으면 삭제를 거부한다. 이는
    봇이 가리키는 계좌가 사라져 orphan bot이 되는 무결성 위반을 막는다.

    1.0 운영 절차: ``ante account delete``는 cold-path 전용이며, 남아 있는
    봇은 ``ante bot remove``로 먼저 제거해야 한다. ``bot remove``는 서버 실행
    중에는 IPC, 서버 정지 상태에서는 cold-path cleanup으로 동작하므로 계좌
    삭제 복구 흐름에서 별도의 server start/stop 왕복이 필요하지 않다.
    """

    def __init__(self, account_id: str, bot_count: int) -> None:
        self.account_id = account_id
        self.bot_count = bot_count
        super().__init__(
            f"계좌 '{account_id}'에 연결된 활성 봇이 {bot_count}개 있어 "
            f"삭제할 수 없습니다. 다음 순서로 진행하세요:\n"
            f"  1) ante bot remove <bot_id>  "
            f"(각 봇에 대해 반복, 서버 정지 상태에서도 가능)\n"
            f"  2) ante account delete {account_id}"
        )


# 하위 호환용 별칭
AccountDeletedException = AccountDeletedError
