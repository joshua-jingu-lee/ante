"""Bot 모듈 예외.

Refs #1712: ``bot.start``/``bot.stop`` IPC handler 가 Web API
(``POST /api/bots/{bot_id}/start``/``/stop``) 와 동일한 거부 경로를 가지도록
coded exception 두 개를 추가했다 — ``BotAccountCredentialsNotConfigured``
(``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``, app_key 부재 preflight 실패) /
``BotStateConflict`` (``BOT_STATE_CONFLICT``, 상태머신 거부). IPC server.py
의 ``getattr(e, "code", ...)`` envelope 정렬 패턴(``BOT_NOT_FOUND_CODE`` 와
동형) 으로 일관된다.
"""

BOT_NOT_FOUND_CODE = "BOT_NOT_FOUND"
BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE = "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
BOT_STATE_CONFLICT_CODE = "BOT_STATE_CONFLICT"


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

    Refs #1712: ``POST /api/bots/{bot_id}/start`` 의 422 preflight 거부
    (``계좌에 인증정보(app_key)가 설정되지 않았습니다``) 와 정렬되는 IPC
    오류. IPC ``server.py`` 의 ``getattr(e, "code", ...)`` 가
    ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` envelope 으로 변환한다.
    """

    code: str = BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE


class BotStateConflict(BotError):  # noqa: N818
    """봇 상태머신 충돌 (start_bot/stop_bot 가 ``BotError`` 로 거부).

    Refs #1712: Web API ``POST /api/bots/{bot_id}/start``/``/stop`` 의 409
    ``BotError`` → ``HTTPException`` 매핑과 정렬되는 IPC 오류. IPC
    ``server.py`` 의 ``getattr(e, "code", ...)`` 가 ``BOT_STATE_CONFLICT``
    envelope 으로 변환한다.
    """

    code: str = BOT_STATE_CONFLICT_CODE
