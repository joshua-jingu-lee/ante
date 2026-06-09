"""signal.connect 신규 4코드 category-resolution lock (#2334/#2336 PR#1).

이 테스트의 회귀 가드는 ``error_drift`` 스캐너가 아니라 **category 정확성**이다:
``helpers.error_spec_for_exception`` 은 ``EXCEPTION_TO_SPEC`` registry miss 시
bare ``.code`` 를 ``category="internal"`` 로 보수적 wrap 한다(helpers.py:74-76).
따라서 typed exception(``InvalidSignalKey``/``BotNotRunning``) 은 class-level
``.code`` (server.py getattr 경로) **그리고** ``EXCEPTION_TO_SPEC`` entry
(category) 둘 다 필요하다 — entry 가 빠지면 코드는 맞지만 category 가
``internal`` 로 drift 한다. 이 테스트가 그 trap 을 lock 한다.

또한 신규 4코드(typed 2 + inline 2)가 모두 ErrorSpec 상수로 present 함을
확인한다 — ``BOT_SIGNAL_CHANNEL_BUSY`` 는 PR#1 에 raiser 가 없지만(PR#2 #2337)
#2335 contract-drift 종료를 위해 상수로 등록된다.
"""

from __future__ import annotations

from ante.bot.exceptions import (
    BotNotRunning,
    InvalidSignalKey,
    SignalKeyManagerNotConfigured,
)
from ante.contracts import error_spec_for_exception
from ante.contracts.error_registry import (
    _BOT_NOT_RUNNING_SPEC,
    _BOT_SIGNAL_CHANNEL_BUSY_SPEC,
    _INVALID_SIGNAL_KEY_SPEC,
    _MALFORMED_REQUEST_SPEC,
)


class TestCategoryResolutionLock:
    """typed exception 의 category 가 ``internal`` 로 wrap 되지 않음을 lock."""

    def test_invalid_signal_key_resolves_validation(self) -> None:
        spec = error_spec_for_exception(InvalidSignalKey())
        assert spec.code == "INVALID_SIGNAL_KEY"
        # entry 누락 시 helpers 가 bare .code 를 internal 로 wrap → 회귀 검출.
        assert spec.category == "validation"

    def test_bot_not_running_resolves_state_conflict(self) -> None:
        spec = error_spec_for_exception(BotNotRunning("b1", "stopped"))
        assert spec.code == "BOT_NOT_RUNNING"
        assert spec.category == "state_conflict"

    def test_signal_key_manager_not_configured_reuses_service_not_configured(
        self,
    ) -> None:
        """``SignalKeyManagerNotConfigured`` 는 기존 ``SERVICE_NOT_CONFIGURED``
        spec 재사용 — category ``service_unavailable`` (internal 아님)."""
        spec = error_spec_for_exception(SignalKeyManagerNotConfigured())
        assert spec.code == "SERVICE_NOT_CONFIGURED"
        assert spec.category == "service_unavailable"


class TestAllFourCodesRegistered:
    """신규 4코드(typed 2 + inline 2) 가 모두 ErrorSpec 상수로 present."""

    def test_invalid_signal_key_spec(self) -> None:
        assert _INVALID_SIGNAL_KEY_SPEC.code == "INVALID_SIGNAL_KEY"
        assert _INVALID_SIGNAL_KEY_SPEC.category == "validation"

    def test_bot_not_running_spec(self) -> None:
        assert _BOT_NOT_RUNNING_SPEC.code == "BOT_NOT_RUNNING"
        assert _BOT_NOT_RUNNING_SPEC.category == "state_conflict"

    def test_malformed_request_spec(self) -> None:
        assert _MALFORMED_REQUEST_SPEC.code == "MALFORMED_REQUEST"
        assert _MALFORMED_REQUEST_SPEC.category == "validation"

    def test_bot_signal_channel_busy_spec(self) -> None:
        """PR#1 에 raiser 없음(PR#2 #2337) — 상수만 등록(#2335 drift 종료)."""
        assert _BOT_SIGNAL_CHANNEL_BUSY_SPEC.code == "BOT_SIGNAL_CHANNEL_BUSY"
        assert _BOT_SIGNAL_CHANNEL_BUSY_SPEC.category == "state_conflict"
