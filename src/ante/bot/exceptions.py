"""Bot 모듈 예외.

Refs #1712: ``bot.start``/``bot.stop`` IPC handler 가 stable coded exception을
반환하도록 두 개를 추가했다 — ``BotAccountCredentialsNotConfigured``
(``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``, app_key 부재 preflight 실패) /
``BotStateConflict`` (``BOT_STATE_CONFLICT``, 상태머신 거부). IPC server.py
의 ``getattr(e, "code", ...)`` envelope 정렬 패턴(``BOT_NOT_FOUND_CODE`` 와
동형) 으로 일관된다.
"""

BOT_NOT_FOUND_CODE = "BOT_NOT_FOUND"
BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE = "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
BOT_STATE_CONFLICT_CODE = "BOT_STATE_CONFLICT"
BOT_NOT_ACCEPTING_SIGNALS_CODE = "BOT_NOT_ACCEPTING_SIGNALS"


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

    Refs #1712: 봇 시작 전 ``app_key`` preflight 거부
    (``계좌에 인증정보(app_key)가 설정되지 않았습니다``)를 표현하는 IPC
    오류. IPC ``server.py`` 의 ``getattr(e, "code", ...)`` 가
    ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` envelope 으로 변환한다.
    """

    code: str = BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE


class BotStateConflict(BotError):  # noqa: N818
    """봇 상태머신 충돌 (start_bot/stop_bot 가 ``BotError`` 로 거부).

    Refs #1712: ``BotError`` 상태머신 거부를 표현하는 IPC 오류. IPC
    ``server.py`` 의 ``getattr(e, "code", ...)`` 가 ``BOT_STATE_CONFLICT``
    envelope 으로 변환한다.
    """

    code: str = BOT_STATE_CONFLICT_CODE


class BotNotAcceptingSignals(BotError):  # noqa: N818
    """봇의 전략이 외부 시그널을 받지 않음 (``accepts_external_signals=False``).

    Refs #1761: ``bot signal-key --rotate`` 가 ``accepts_external_signals=False``
    전략에도 키를 발급해 orphan credential 이 생기던 회귀를 막는다.
    ``signal connect`` 가 동일 조건을 이미 ``BOT_NOT_ACCEPTING_SIGNALS`` 로
    거부(``ante/cli/commands/signal.py:70-75``)하고 있어 같은 코드를 재사용해
    IPC/CLI 표면 간 envelope 코드 일관성을 유지한다.
    """

    code: str = BOT_NOT_ACCEPTING_SIGNALS_CODE
