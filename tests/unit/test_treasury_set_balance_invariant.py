"""Treasury.set_account_balance 입력 invariant 단위 테스트.

이슈 #1340: 음수/NaN/Inf 잔고는 계좌 잔고/미할당의 모든 다운스트림 계산을
오염시킨다. service 진입에 finite + non-negative 가드를 두어 방어한다.
라우트 단의 Pydantic validation과 함께 다층 방어 (defense in depth)를 구성한다.
"""

from __future__ import annotations

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.treasury import Treasury

ACCOUNT_ID = "domestic"
CURRENCY = "KRW"


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def treasury(db, eventbus):
    t = Treasury(
        db=db,
        eventbus=eventbus,
        account_id=ACCOUNT_ID,
        currency=CURRENCY,
        buy_commission_rate=0.00015,
        sell_commission_rate=0.00195,
    )
    await t.initialize()
    return t


class TestSetAccountBalanceInvariant:
    """set_account_balance 입력 invariant: balance는 finite이며 >= 0."""

    async def test_set_account_balance_rejects_negative(self, treasury):
        """음수 → ValueError."""
        with pytest.raises(ValueError, match="must be finite and >= 0"):
            await treasury.set_account_balance(-1.0)

    async def test_set_account_balance_rejects_nan(self, treasury):
        """NaN → ValueError."""
        with pytest.raises(ValueError, match="must be finite and >= 0"):
            await treasury.set_account_balance(float("nan"))

    async def test_set_account_balance_rejects_positive_inf(self, treasury):
        """+Inf → ValueError."""
        with pytest.raises(ValueError, match="must be finite and >= 0"):
            await treasury.set_account_balance(float("inf"))

    async def test_set_account_balance_rejects_negative_inf(self, treasury):
        """-Inf → ValueError."""
        with pytest.raises(ValueError, match="must be finite and >= 0"):
            await treasury.set_account_balance(-float("inf"))

    async def test_set_account_balance_rejected_does_not_mutate_state(self, treasury):
        """거부 시 _account_balance와 _unallocated가 호출 전 상태 유지."""
        # 정상 잔고 설정으로 baseline 구축
        await treasury.set_account_balance(100.0)
        assert treasury.account_balance == 100.0
        assert treasury.unallocated == 100.0

        # 음수 거부 시 상태 변경 없음
        with pytest.raises(ValueError):
            await treasury.set_account_balance(-1.0)
        assert treasury.account_balance == 100.0
        assert treasury.unallocated == 100.0

        # NaN 거부 시 상태 변경 없음
        with pytest.raises(ValueError):
            await treasury.set_account_balance(float("nan"))
        assert treasury.account_balance == 100.0
        assert treasury.unallocated == 100.0

        # +Inf 거부 시 상태 변경 없음
        with pytest.raises(ValueError):
            await treasury.set_account_balance(float("inf"))
        assert treasury.account_balance == 100.0
        assert treasury.unallocated == 100.0

    async def test_set_account_balance_accepts_zero(self, treasury):
        """0은 경계 허용 — 잔고 0/미할당 0으로 정상 설정."""
        await treasury.set_account_balance(0.0)
        assert treasury.account_balance == 0.0
        assert treasury.unallocated == 0.0

    async def test_set_account_balance_accepts_positive(self, treasury):
        """양수 정상 경로."""
        await treasury.set_account_balance(10_000_000.0)
        assert treasury.account_balance == 10_000_000.0
        assert treasury.unallocated == 10_000_000.0
