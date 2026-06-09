"""Bot 모듈 예외.

``bot.start``/``bot.stop`` IPC handler 는 stable coded exception 을
반환한다 — ``BotAccountCredentialsNotConfigured``
(``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``, app_key 부재 preflight 실패) /
``BotStateConflict`` (``BOT_STATE_CONFLICT``, 상태머신 거부). IPC server.py
의 ``getattr(e, "code", ...)`` envelope 정렬 패턴(``BOT_NOT_FOUND_CODE`` 와
동형) 으로 일관된다.
"""

BOT_NOT_FOUND_CODE = "BOT_NOT_FOUND"
BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE = "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
BOT_STATE_CONFLICT_CODE = "BOT_STATE_CONFLICT"
BOT_NOT_ACCEPTING_SIGNALS_CODE = "BOT_NOT_ACCEPTING_SIGNALS"
BOT_ALREADY_EXISTS_CODE = "BOT_ALREADY_EXISTS"
BOT_STRATEGY_ALREADY_RUNNING_CODE = "BOT_STRATEGY_ALREADY_RUNNING"
BOT_IMMUTABLE_FIELD_CODE = "BOT_IMMUTABLE_FIELD"
# Refs #2334 / #2336 (PR#1): signal.connect 핸드셰이크 4-게이트 stable code.
# ``SignalKeyManagerNotConfigured`` 는 전용 코드를 발명하지 않고 taxonomy
# SSOT(error-taxonomy.md) 의 공통 ``SERVICE_NOT_CONFIGURED`` 를 재사용한다.
INVALID_SIGNAL_KEY_CODE = "INVALID_SIGNAL_KEY"
BOT_NOT_RUNNING_CODE = "BOT_NOT_RUNNING"


class BotError(Exception):
    """Bot 기본 예외."""

    pass


class BotNotFoundError(BotError):
    """봇을 찾을 수 없음."""

    code: str = BOT_NOT_FOUND_CODE

    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        super().__init__(f"Bot not found: {bot_id}")


class BotAccountCredentialsNotConfigured(BotError):  # noqa: N818
    """봇 시작 시 account 의 ``app_key`` 가 부재.

    봇 시작 전 ``app_key`` preflight 거부 (``계좌에 인증정보(app_key)가
    설정되지 않았습니다``) 를 표현하는 IPC 오류. IPC ``server.py`` 의
    ``getattr(e, "code", ...)`` 가 ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``
    envelope 으로 변환한다.
    """

    code: str = BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE


class BotStateConflict(BotError):  # noqa: N818
    """봇 상태머신 충돌 (start_bot/stop_bot 가 ``BotError`` 로 거부).

    ``BotError`` 상태머신 거부를 표현하는 IPC 오류. IPC ``server.py`` 의
    ``getattr(e, "code", ...)`` 가 ``BOT_STATE_CONFLICT`` envelope 으로
    변환한다.
    """

    code: str = BOT_STATE_CONFLICT_CODE


class BotNotAcceptingSignals(BotError):  # noqa: N818
    """봇의 전략이 외부 시그널을 받지 않음 (``accepts_external_signals=False``).

    ``bot signal-key --rotate`` 가 ``accepts_external_signals=False`` 전략에
    키를 발급해 orphan credential 이 생기는 경로를 막는다. ``signal connect``
    가 동일 조건을 이미 ``BOT_NOT_ACCEPTING_SIGNALS`` 로 거부
    (``ante/cli/commands/signal.py:70-75``) 하고 있어 같은 코드를 재사용해
    IPC/CLI 표면 간 envelope 코드 일관성을 유지한다.
    """

    code: str = BOT_NOT_ACCEPTING_SIGNALS_CODE


class BotAlreadyExistsError(BotError):
    """동일 ``bot_id`` 가 이미 존재함.

    ``BotManager.create_bot`` 가 동일 bot_id 중복 등록을 거부할 때 raise
    한다. IPC ``server.py`` 의 ``getattr(e, "code", ...)`` envelope 이
    ``BOT_ALREADY_EXISTS`` 로 변환한다. CLI ``bot create`` 는 동 코드를
    surface 해 자동화가 중복 회피 처리할 수 있게 한다.
    """

    code: str = BOT_ALREADY_EXISTS_CODE


class BotStrategyAlreadyRunningError(BotError):
    """동일 ``strategy_id`` 가 이미 실행 중인 다른 봇에 의해 사용 중.

    "1전략 1봇" 정책에 따른 거부. IPC envelope 이
    ``BOT_STRATEGY_ALREADY_RUNNING`` 으로 변환되어 자동화/사용자가 동일
    전략의 다중 실행 시도를 명확히 식별할 수 있다.
    """

    code: str = BOT_STRATEGY_ALREADY_RUNNING_CODE


class BotImmutableFieldError(BotError):
    """봇 생성 후 변경할 수 없는 불변 필드 수정 시도 (#2282).

    ``account_id`` 는 봇이 참조하는 treasury 예산·broker credential·포지션
    격리가 모두 **account-bound** 라, ``update_bot`` 으로 변경하면 옛 account
    아래의 예산/credential/포지션이 새 account 로 재배치되지 않아 불일치가
    발생한다. 복잡한 re-isolation 대신 ``account_id`` 를 ``update_bot`` 의
    불변 필드로 제약하고, 변경이 필요하면 봇을 삭제 후 재생성하도록 안내한다
    (Account.update 의 ``AccountImmutableFieldError`` 선례 미러).

    클래스 레벨 ``code`` 속성은 IPC ``server.py`` 의
    ``getattr(e, "code", ...)`` 가 안정 코드 ``BOT_IMMUTABLE_FIELD`` 로
    변환하도록 한다. ``bot.update`` handler 의 ``except BotError: raise`` 가
    ``BotError`` 서브클래스인 본 예외를 그대로 surface 하므로 IPC/CLI 표면이
    동일 코드를 노출한다.
    """

    code: str = BOT_IMMUTABLE_FIELD_CODE


class InvalidSignalKey(BotError):  # noqa: N818
    """``signal.connect`` 핸드셰이크 게이트① — signal key 검증 실패 (#2334/#2336).

    ``validate_signal_key`` 가 ``None`` 을 반환한 경우(미발급/회전/오타 키)
    핸들러가 raise 한다. IPC ``server.py`` 의 ``getattr(e, "code", ...)`` 가
    안정 코드 ``INVALID_SIGNAL_KEY`` 로 변환한다.

    **redaction 불변**: 메시지에 키/bot_id 를 절대 interpolate 하지 않는다.
    ``__init__`` 인자를 0개로 강제해 호출처 실수로 키가 새는 경로를 차단한다
    (error-taxonomy.md ``validation`` 카테고리).
    """

    code: str = INVALID_SIGNAL_KEY_CODE

    def __init__(self) -> None:
        super().__init__("Invalid signal key")


class BotNotRunning(BotError):  # noqa: N818
    """``signal.connect`` 핸드셰이크 게이트③ — 봇이 RUNNING 아님 (#2334/#2336).

    handshake 시점에 ``bot.status != BotStatus.RUNNING`` 이면 핸들러가 raise
    한다. IPC ``server.py`` 의 ``getattr(e, "code", ...)`` 가 안정 코드
    ``BOT_NOT_RUNNING`` 으로 변환한다 (error-taxonomy.md ``state_conflict``).

    ``status`` 는 caller(핸들러 게이트③)가 ``bot.status.value`` 로 넘긴
    **소문자** ``BotStatus.value`` 다. 본 클래스는 받은 문자열을 그대로
    포맷하며 ``BotStatus.name``(대문자)/``repr`` 을 사용하지 않는다.
    """

    code: str = BOT_NOT_RUNNING_CODE

    def __init__(self, bot_id: str, status: str) -> None:
        self.bot_id = bot_id
        self.status = status
        super().__init__(f"Bot is not running: {bot_id} (status: {status})")


class SignalKeyManagerNotConfigured(BotError):  # noqa: N818
    """``signal.connect`` 키 검증에 필요한 ``SignalKeyManager`` 가 부재 (#2334/#2336).

    ``BotManager.validate_signal_key`` 가 ``_signal_key_manager is None`` 일 때
    raise 한다. ``rotate_signal_key`` 의 generic ``BotError``(EXECUTION_ERROR
    로 fold) 를 미러하지 않고, taxonomy SSOT 의 공통 안정 코드
    ``SERVICE_NOT_CONFIGURED``(``service_unavailable``) 를 재사용한다 —
    전용 코드를 발명하지 않는다. 메시지는 키-free 이며 관찰 가능한
    ``signal_key_manager`` 토큰만 포함한다.
    """

    code: str = "SERVICE_NOT_CONFIGURED"

    def __init__(self) -> None:
        super().__init__("SignalKeyManager not configured: signal_key_manager")
