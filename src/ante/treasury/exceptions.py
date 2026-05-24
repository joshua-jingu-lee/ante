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


# --------------------------------------------------------------------------
# #1809 (oracle A7 @ a5d8edf): allocate/deallocate reject reason typed
# exceptions.
#
# ``Treasury.allocate``/``Treasury.deallocate`` 가 reject 시 ``bool=False``
# 를 반환하던 SSOT 회귀(JSON envelope ``code=""``)를 typed exception 으로
# 교체하기 위한 reject reason 별 클래스. IPC server 의
# ``getattr(e, "code", "EXECUTION_ERROR")`` 매핑(server.py:322)을 통해 stable
# ``SCREAMING_SNAKE_CASE`` 코드(``docs/specs/cli/02-design-decisions.md:83-89``)
# 로 surface 된다.
#
# - ``TreasuryInvalidAmountError``        : amount 가 NaN/±Inf/<=0 (음수/0).
#   ``Treasury.allocate``/``deallocate`` 모두 ``math.isfinite(amount) and
#   amount > 0`` 가드(#1411) 위반 시 raise. CLI ingress(``validate_positive_
#   finite_amount``)가 1차 거부하지만 service layer 가 2차 invariant 로 raise.
# - ``TreasuryInsufficientUnallocatedError``: ``allocate`` 시 ``self._unallocated
#   < amount`` (미할당 잔액 부족). caller 가 받은 reject reason 으로
#   ``InsufficientFundsError`` 를 만들거나 ``code=TREASURY_INSUFFICIENT_BALANCE``
#   envelope 으로 surface.
# - ``TreasuryBudgetNotFoundError``       : ``deallocate`` 시 ``self._budgets``
#   에 해당 ``bot_id`` budget record 부재. (IPC handler 는 ``BotNotFoundError``
#   로 cross-module 검증을 선행하므로 이 reject 는 budget record 만 없는
#   드문 경로이지만 invariant 로 명시한다.)
# - ``TreasuryDeallocateExceedsAvailableError`` : ``deallocate`` 시 요청
#   amount 가 ``budget.available`` 초과 (over-deallocate).
#
# `.code` 속성은 IPC server.py:322 의 ``getattr(e, "code", ...)`` 가 직접
# 참조하는 SSOT 이며 spec ``docs/specs/cli/02-design-decisions.md:83-89``
# SCREAMING_SNAKE_CASE 규약을 따른다.


class TreasuryInvalidAmountError(TreasuryError):
    """``allocate``/``deallocate`` amount 가 finite-positive 가 아님.

    #1411 finite-positive 가드(``math.isfinite(amount) and amount > 0``)
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
