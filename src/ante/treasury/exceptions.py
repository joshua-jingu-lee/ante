"""Treasury 모듈 예외."""


class TreasuryError(Exception):
    """Treasury 기본 예외."""

    pass


class InsufficientFundsError(TreasuryError):
    """자금 부족."""

    code = "TREASURY_INSUFFICIENT_FUNDS"


class BotNotStoppedError(TreasuryError):
    """봇이 중지 상태가 아니어서 예산 변경 불가.

    클래스 레벨 ``code`` 속성은 안정
    코드 ``TREASURY_BOT_NOT_STOPPED`` 다 — running 상태 봇의 예산 변경
    거부는 운영 상태 머신 위반 (taxonomy ``state_conflict``).
    """

    code = "TREASURY_BOT_NOT_STOPPED"


class TreasuryNotConfiguredError(TreasuryError):
    """계좌에 Treasury가 구성되지 않아 budget 작업을 수행할 수 없음.

    클래스 레벨 ``code`` 속성은 안정
    코드 ``TREASURY_NOT_CONFIGURED`` 다 — service 인프라 부재로 인한
    거부 (taxonomy ``service_unavailable``).
    """

    code = "TREASURY_NOT_CONFIGURED"


class TreasuryInvalidAmountError(TreasuryError):
    """``allocate``/``deallocate`` amount 가 finite-positive 가 아님.

    finite-positive 가드(``math.isfinite(amount) and amount > 0``)
    위반 — NaN/±Infinity/음수/0 일 때 raise.
    """

    code = "TREASURY_INVALID_AMOUNT"

    def __init__(self, amount: float, *, operation: str = "allocate") -> None:
        self.amount = amount
        self.operation = operation
        super().__init__(
            f"treasury.{operation}: amount는 유한한 양수여야 합니다 (요청={amount!r})"
        )


class TreasuryInsufficientUnallocatedError(TreasuryError):
    """``allocate`` 시 미할당 잔액 부족.

    ``self._unallocated < amount`` 일 때 raise. CLI/IPC 는
    ``TREASURY_INSUFFICIENT_BALANCE`` 코드로 surface.
    """

    code = "TREASURY_INSUFFICIENT_BALANCE"

    def __init__(
        self,
        bot_id: str,
        amount: float,
        unallocated: float,
    ) -> None:
        self.bot_id = bot_id
        self.amount = amount
        self.unallocated = unallocated
        super().__init__(
            f"treasury.allocate: 미할당 잔액 부족 "
            f"(요청={amount:,.0f}, 가용={unallocated:,.0f}, bot_id={bot_id})"
        )


class TreasuryBudgetNotFoundError(TreasuryError):
    """``deallocate`` 시 budget record 부재.

    ``self._budgets`` 에 해당 ``bot_id`` budget 이 없을 때 raise.
    """

    code = "TREASURY_BUDGET_NOT_FOUND"

    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        super().__init__(
            f"treasury.deallocate: bot '{bot_id}' 의 budget record 가 없습니다"
        )


class TreasuryDeallocateExceedsAvailableError(TreasuryError):
    """``deallocate`` 시 요청 amount 가 budget.available 초과.

    over-deallocate 시 raise.
    """

    code = "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE"

    def __init__(self, bot_id: str, amount: float, available: float) -> None:
        self.bot_id = bot_id
        self.amount = amount
        self.available = available
        super().__init__(
            f"treasury.deallocate: 가용 예산 초과 "
            f"(요청={amount:,.0f}, 가용={available:,.0f}, bot_id={bot_id})"
        )


class DuplicateReservationError(ValueError):
    """같은 ``order_id`` 의 예약 항목이 이미 있어 재예약을 거부함 (#2775)."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"order_id {order_id} 의 예약이 이미 있습니다")
