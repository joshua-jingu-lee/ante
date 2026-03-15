"""Treasury 모듈 예외."""


class TreasuryError(Exception):
    """Treasury 기본 예외."""

    pass


class InsufficientFundsError(TreasuryError):
    """자금 부족."""

    pass


class BotNotStoppedError(TreasuryError):
    """봇이 중지 상태가 아니어서 예산 변경 불가."""

    pass
