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


class TreasuryNotConfiguredError(TreasuryError):
    """계좌에 Treasury가 구성되지 않아 budget 작업을 수행할 수 없음.

    Refs #1335: budget 배정 요청이 들어왔지만 ``TreasuryManager`` 자체가
    주입되지 않았거나, 해당 ``account_id`` 에 등록된 Treasury 가 없어
    예산을 할당할 수 없을 때 발생한다. 라우트 계층은 이 예외를 422 로
    매핑한다 (`TreasuryError` 하위 클래스이므로 기존 422 매핑이 자동
    적용된다).
    """

    pass
