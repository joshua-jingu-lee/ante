"""Bot 모듈 예외."""

BOT_NOT_FOUND_CODE = "BOT_NOT_FOUND"


class BotError(Exception):
    """Bot 기본 예외."""

    pass


class BotNotFoundError(BotError):
    """봇을 찾을 수 없음."""

    code: str = BOT_NOT_FOUND_CODE

    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        super().__init__(f"Bot not found: {bot_id}")
