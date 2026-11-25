"""Account 모듈 예외."""

from ante.core.account_id import AccountError as AccountError
from ante.core.account_id import InvalidAccountIdError as InvalidAccountIdError


class AccountNotFoundError(AccountError):
    """계좌를 찾을 수 없음.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_NOT_FOUND"``를 노출하도록 한다. CLI
    ``account suspend``/``account activate`` 등이 IPC error envelope 의
    typed code 를 그대로 surface 해 not-found 의미가 일반
    ``EXECUTION_ERROR`` 로 분실되지 않게 한다.
    """

    code: str = "ACCOUNT_NOT_FOUND"


class AccountAlreadyExistsError(AccountError):
    """동일 account_id가 이미 존재.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_ALREADY_EXISTS"``를 노출하도록 한다
    (state-conflict / duplicate-resource typed code 정합).
    """

    code: str = "ACCOUNT_ALREADY_EXISTS"


class InvalidBrokerTypeError(AccountError):
    """등록되지 않은 broker_type.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_INVALID_BROKER_TYPE"``를 노출하도록 한다.
    """

    code: str = "ACCOUNT_INVALID_BROKER_TYPE"


class InvalidExchangeError(AccountError):
    """canonical vocabulary에 없는 exchange (`*`/non-canonical).

    account 입력 경계는 ``ante.core.exchange`` SSOT의 canonical 5종만
    허용한다(core.md ``## Canonical Exchange Vocabulary`` 축 A). `*` 는
    ``StrategyMeta.exchange`` 전용 wildcard이므로 account 표면에서는 거부된다.
    """

    code: str = "VALIDATION_ERROR"


class InvalidBrokerConfigError(AccountError):
    """계좌 생성 때 ``broker_config`` 값이 브로커의 정의를 어김.

    ``mock`` 계좌의 ``prices``·``default_price`` 가 가격 정의(불리언이 아닌
    유한한 수, 0 초과)를 어기면 raise 한다. 안정 코드는 계좌 입력 검증의
    ``VALIDATION_ERROR`` 다.
    """

    code: str = "VALIDATION_ERROR"


class MissingCredentialsError(AccountError):
    """필수 credentials 키 누락.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_MISSING_CREDENTIALS"``를 노출하도록 한다.
    """

    code: str = "ACCOUNT_MISSING_CREDENTIALS"


class AccountAlreadySuspendedError(AccountError):
    """이미 정지 상태인 계좌에 대한 재정지 시도.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_ALREADY_SUSPENDED"``를 노출하도록 한다
    (state-conflict typed code 정합. CLI ``account suspend`` 가 IPC envelope
    의 typed code 를 진입점 훅에서 그대로
    surface 한다).
    """

    code: str = "ACCOUNT_ALREADY_SUSPENDED"


class AccountDeletedError(AccountError):
    """DELETED 상태 계좌에 대한 수정/활성화 시도.

    NOTE: CLI ``account delete`` 의 ``except AccountDeletedError`` 분기는
    명시적으로 ``code="ACCOUNT_ALREADY_DELETED"`` 를 출력해 already-deleted
    UX 의미를 보존한다 (CLI surface override). 본 클래스 레벨 ``code`` 는
    IPC envelope 의 fallback 코드 (직접 catch 가 없는 표면)를 의미한다.
    """

    code: str = "ACCOUNT_DELETED"


class AccountSuspendedError(AccountError):
    """정지(SUSPENDED) 상태 계좌에 대한 작업 시도.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_SUSPENDED"``를 노출하도록 한다.
    """

    code: str = "ACCOUNT_SUSPENDED"


class AccountImmutableFieldError(AccountError):
    """불변 필드 수정 시도.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"ACCOUNT_IMMUTABLE_FIELD"``를 노출하도록 한다.
    """

    code: str = "ACCOUNT_IMMUTABLE_FIELD"


class BrokerReconnectFailedError(AccountError):
    """계좌 설정 변경 후 브로커 재연결에 실패했음.

    update() 자체는 DB에 반영되지만, 새 자격증명/설정으로 broker connect()가
    실패했을 때 발생한다. 운영자는 설정을 교정한 뒤 재시도해야 한다.

    클래스 레벨 ``code`` 속성은 IPC 서버가
    ``ipc_error_payload``로 안정 코드
    ``"BROKER_RECONNECT_FAILED"``를 노출하도록 한다.
    """

    code: str = "BROKER_RECONNECT_FAILED"


class AccountStructuralChangeRequiresStoppedServerError(AccountError):
    """런타임에 계좌 structural 필드/메서드 변경을 시도했을 때 raise.

    AccountService는 boot/cold-path/runtime을 구분하는 ``_runtime_started``
    플래그를 갖는다. 서버 부팅이 완료된 뒤 이 플래그가 활성화되면 ``create()``,
    ``delete()``, structural 키를 포함한 ``update()`` 호출은 즉시 이 예외로
    차단된다 — DB는 수정되지 않는다.
    """

    code: str = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


class AccountHasActiveBotsError(AccountError):
    """delete() 시 해당 계좌에 활성(non-deleted) 봇이 남아 있음.

    cold-path AccountService.delete()는 status mutation 전에 ``bots`` 테이블을
    조회하여 동일 ``account_id``의 활성 봇이 있으면 삭제를 거부한다. 이는
    봇이 가리키는 계좌가 사라져 orphan bot이 되는 무결성 위반을 막는다.
    """

    code: str = "ACCOUNT_HAS_ACTIVE_BOTS"

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


class AccountReconcileNotApplicableError(AccountError):
    """수동 대사를 할 수 없는 계좌(D-ACC-09 매트릭스의 reconcile 면제, 가상).

    가상 계좌의 포지션은 내부 기록이 권위라 브로커와 비교하거나 덮어쓰지 않는다.
    """

    code: str = "ACCOUNT_RECONCILE_NOT_APPLICABLE"


class AccountSuspendAllFailedError(AccountError):
    """일괄 정지에서 한 계좌 이상의 정지가 실패함.

    나머지 계좌를 모두 시도한 뒤 올린다. 실패한 계좌 id와 이번 호출에서
    정지된 계좌 수를 싣고, 원인 예외는 메시지에 싣지 않는다.
    """

    code: str = "ACCOUNT_SUSPEND_ALL_FAILED"

    def __init__(
        self, failed_account_ids: tuple[str, ...], suspended_count: int
    ) -> None:
        self.failed_account_ids = failed_account_ids
        self.suspended_count = suspended_count
        super().__init__(
            f"전체 계좌 정지가 {len(failed_account_ids)}개 계좌에서 실패했습니다: "
            f"{', '.join(failed_account_ids)}. "
            f"이번 요청으로 정지된 계좌는 {suspended_count}개입니다."
        )


class AccountSuspendNotPersistedError(AccountError):
    """계좌 정지는 메모리에 적용됐지만 DB 쓰기가 실패함.

    재시작하면 계좌가 활성으로 돌아온다. 같은 계좌에 정지를 다시 보내면 DB
    쓰기를 다시 시도한다. 코드는 날 DB 예외와 같은 ``EXECUTION_ERROR`` 이고,
    원인 예외는 ``__cause__``로 잇고 메시지에 싣지 않는다.
    """

    code: str = "EXECUTION_ERROR"


class AccountActivateAllFailedError(AccountError):
    """일괄 활성화가 한 계좌의 실패에서 멈춤.

    실패한 계좌 id와 그 전에 활성화된 계좌 수를 싣는다. 원인 예외는
    ``__cause__``로 잇고 메시지에 싣지 않는다.
    """

    code: str = "ACCOUNT_ACTIVATE_ALL_FAILED"

    def __init__(self, failed_account_id: str, activated_count: int) -> None:
        self.failed_account_id = failed_account_id
        self.activated_count = activated_count
        super().__init__(
            f"전체 계좌 활성화가 계좌 '{failed_account_id}'에서 실패해 멈췄습니다. "
            f"그 전에 활성화된 계좌는 {activated_count}개이고, "
            "뒤의 계좌는 시도하지 않았습니다."
        )


AccountDeletedException = AccountDeletedError
