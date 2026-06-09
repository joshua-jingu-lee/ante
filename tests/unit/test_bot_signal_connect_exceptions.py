"""signal.connect 핸드셰이크 typed exception byte-lock 테스트 (#2334/#2336 PR#1).

CLI 소스(``cli/commands/signal.py``)·error-taxonomy.md 와 byte-identical 한
``str(e)`` / ``.code`` / category 계약을 lock 한다. DB 불필요(순수 단위).

T6: ``InvalidSignalKey`` / ``BotNotRunning`` / ``SignalKeyManagerNotConfigured``
의 메시지·코드·redaction 불변.
"""

from __future__ import annotations

from ante.bot.config import BotStatus
from ante.bot.exceptions import (
    BotError,
    BotNotRunning,
    InvalidSignalKey,
    SignalKeyManagerNotConfigured,
)


class TestInvalidSignalKey:
    def test_str_byte_lock(self) -> None:
        """``str(InvalidSignalKey())`` 가 정확히 ``Invalid signal key``."""
        assert str(InvalidSignalKey()) == "Invalid signal key"

    def test_code(self) -> None:
        assert InvalidSignalKey.code == "INVALID_SIGNAL_KEY"
        assert InvalidSignalKey().code == "INVALID_SIGNAL_KEY"

    def test_no_args(self) -> None:
        """``__init__`` 인자 0개 — 키/bot_id 를 interpolate 할 경로 없음."""
        exc = InvalidSignalKey()
        assert isinstance(exc, BotError)

    def test_redaction(self) -> None:
        """메시지에 키 prefix(``sk_``)/bot_id 가 절대 새지 않는다."""
        msg = str(InvalidSignalKey())
        assert "sk_" not in msg
        assert "bot" not in msg.lower() or msg == "Invalid signal key"


class TestBotNotRunning:
    def test_str_byte_lock(self) -> None:
        """``str(BotNotRunning(bot_id, status))`` byte-exact 포맷."""
        exc = BotNotRunning("b1", "stopped")
        assert str(exc) == "Bot is not running: b1 (status: stopped)"

    def test_code(self) -> None:
        assert BotNotRunning.code == "BOT_NOT_RUNNING"
        assert BotNotRunning("b1", "stopped").code == "BOT_NOT_RUNNING"

    def test_fields_preserved(self) -> None:
        exc = BotNotRunning("b1", "stopped")
        assert exc.bot_id == "b1"
        assert exc.status == "stopped"

    def test_status_is_lowercase_botstatus_value(self) -> None:
        """caller 가 ``bot.status.value`` (소문자 StrEnum value) 를 넘기는
        계약을 lock — ``BotStatus.STOPPED.value`` 로 구성해 소문자 검증."""
        status = BotStatus.STOPPED.value
        assert status == "stopped"  # StrEnum value 소문자 sanity
        exc = BotNotRunning("b1", status)
        assert str(exc) == "Bot is not running: b1 (status: stopped)"
        # 대문자 name 을 쓰면 lock 이 깨진다(회귀 가드).
        assert BotStatus.STOPPED.name == "STOPPED"
        assert "STOPPED" not in str(exc)

    def test_is_bot_error(self) -> None:
        assert isinstance(BotNotRunning("b1", "stopped"), BotError)


class TestSignalKeyManagerNotConfigured:
    def test_str_byte_lock(self) -> None:
        """메시지에 관찰 가능한 ``signal_key_manager`` 토큰 포함, 키-free."""
        exc = SignalKeyManagerNotConfigured()
        assert str(exc) == "SignalKeyManager not configured: signal_key_manager"
        assert "signal_key_manager" in str(exc)

    def test_code_reuses_service_not_configured(self) -> None:
        """전용 코드 발명 금지 — 공통 ``SERVICE_NOT_CONFIGURED`` 재사용."""
        assert SignalKeyManagerNotConfigured.code == "SERVICE_NOT_CONFIGURED"
        assert SignalKeyManagerNotConfigured().code == "SERVICE_NOT_CONFIGURED"

    def test_redaction(self) -> None:
        assert "sk_" not in str(SignalKeyManagerNotConfigured())

    def test_is_bot_error(self) -> None:
        assert isinstance(SignalKeyManagerNotConfigured(), BotError)


def test_all_three_are_bot_error_subclasses_with_class_code() -> None:
    """3 클래스 모두 ``BotError`` 서브클래스 + class-level ``.code`` 존재."""
    for cls in (InvalidSignalKey, BotNotRunning, SignalKeyManagerNotConfigured):
        assert issubclass(cls, BotError)
        assert isinstance(cls.code, str) and cls.code
