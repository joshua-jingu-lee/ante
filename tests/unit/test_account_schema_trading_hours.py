"""AccountCreateRequest / AccountUpdateRequest의 trading_hours strict HH:MM 검증.

SSOT:
- docs/specs/account/03-data-model.md (HH:MM 형식)
- docs/specs/account/10-web-api.md (Account API 입력 invariant)
- src/ante/web/schemas.py (HH_MM_PATTERN, field_validator)

이슈 #1334: invalid `trading_hours_start`(예: "99:99")가 schema에 그대로
저장되어 generic preflight error로 주문이 반복 거부되는 문제를
schema-level 422로 차단한다.

- AccountCreateRequest: ``""`` 통과(default 의미 보존), non-empty는 strict
  HH:MM regex + ``time.fromisoformat`` 이중 검증.
- AccountUpdateRequest: ``None`` 통과(필드 미제공), 그 외(``""`` 포함)는
  검증 적용. update 경로는 broker preset fallback이 없으므로 ``""``는 invalid.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ante.web.schemas import AccountCreateRequest, AccountUpdateRequest

# ── AccountCreateRequest ──────────────────────────────────────────


class TestAccountCreateRequestTradingHours:
    """AccountCreateRequest의 trading_hours strict HH:MM 검증."""

    @staticmethod
    def _base_kwargs() -> dict[str, str]:
        return {
            "account_id": "test-account",
            "name": "테스트 계좌",
        }

    def test_account_create_rejects_invalid_99_99(self) -> None:
        """trading_hours_start='99:99'는 422로 거부된다 (이슈 #1334 회귀)."""
        with pytest.raises(ValidationError) as exc_info:
            AccountCreateRequest(
                **self._base_kwargs(),
                trading_hours_start="99:99",
            )
        assert "trading_hours_start" in str(exc_info.value)

    def test_account_create_rejects_alphabetic(self) -> None:
        """알파벳 포함 입력은 422로 거부된다."""
        with pytest.raises(ValidationError):
            AccountCreateRequest(
                **self._base_kwargs(),
                trading_hours_start="ab:cd",
            )

    def test_account_create_rejects_with_seconds(self) -> None:
        """초까지 포함된 입력(예: '09:30:00')은 422로 거부된다."""
        with pytest.raises(ValidationError):
            AccountCreateRequest(
                **self._base_kwargs(),
                trading_hours_end="09:30:00",
            )

    def test_account_create_accepts_empty_default(self) -> None:
        """``""``는 default 의미 보존을 위해 통과한다.

        CLI/seed 경로에서 BrokerPreset fallback이 ``""``를 preset value로
        채우므로 schema에서 ``""``를 거부하면 안 된다 (#1334 plan v5 stop
        condition).
        """
        req = AccountCreateRequest(
            **self._base_kwargs(),
            trading_hours_start="",
            trading_hours_end="",
        )
        assert req.trading_hours_start == ""
        assert req.trading_hours_end == ""

    def test_account_create_accepts_valid_hhmm_boundaries(self) -> None:
        """경계값 HH:MM은 통과한다 (00:00, 09:30, 23:59)."""
        for value in ("00:00", "09:30", "23:59"):
            req = AccountCreateRequest(
                **self._base_kwargs(),
                trading_hours_start=value,
                trading_hours_end=value,
            )
            assert req.trading_hours_start == value
            assert req.trading_hours_end == value


# ── AccountUpdateRequest ──────────────────────────────────────────


class TestAccountUpdateRequestTradingHours:
    """AccountUpdateRequest의 trading_hours strict HH:MM 검증.

    update 경로는 broker preset fallback이 없으므로 ``""``도 거부한다.
    """

    def test_account_update_rejects_invalid_99_99(self) -> None:
        """update 경로의 '99:99'도 422로 거부된다 (이슈 #1334 직접 회귀)."""
        with pytest.raises(ValidationError) as exc_info:
            AccountUpdateRequest(trading_hours_start="99:99")
        assert "trading_hours_start" in str(exc_info.value)

    def test_account_update_rejects_empty_string(self) -> None:
        """update 경로의 ``""``는 422 — broker preset fallback이 없다."""
        with pytest.raises(ValidationError):
            AccountUpdateRequest(trading_hours_end="")

    def test_account_update_rejects_with_seconds(self) -> None:
        """초까지 포함된 '09:30:00'은 422로 거부된다."""
        with pytest.raises(ValidationError):
            AccountUpdateRequest(trading_hours_start="09:30:00")

    def test_account_update_allows_none(self) -> None:
        """``None``은 필드 미제공 의미로 통과한다."""
        req = AccountUpdateRequest(trading_hours_start=None, trading_hours_end=None)
        assert req.trading_hours_start is None
        assert req.trading_hours_end is None

    def test_account_update_accepts_valid(self) -> None:
        """유효한 HH:MM은 통과한다."""
        req = AccountUpdateRequest(
            trading_hours_start="09:30",
            trading_hours_end="16:00",
        )
        assert req.trading_hours_start == "09:30"
        assert req.trading_hours_end == "16:00"
