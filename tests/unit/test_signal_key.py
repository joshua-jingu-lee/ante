"""SignalKeyManager 및 BotManager 시그널 키 연동 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.signal_key import SignalKeyManager
from ante.strategy.base import Signal, Strategy, StrategyMeta

# ── SignalKeyManager 단독 테스트 ─────────────────────


@pytest.fixture
def db() -> MagicMock:
    """Database mock."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.execute_script = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value=None)
    mock_db.fetch_all = AsyncMock(return_value=[])
    return mock_db


@pytest.fixture
def skm(db: MagicMock) -> SignalKeyManager:
    """SignalKeyManager 인스턴스."""
    return SignalKeyManager(db)


class TestSignalKeyGenerate:
    """키 발급 테스트."""

    async def test_generate_key_format(self, skm: SignalKeyManager) -> None:
        """발급된 키가 sk_ 접두사 + hex 형식."""
        key = await skm.generate("bot-001")
        assert key.startswith("sk_")
        assert len(key) == 3 + 32  # "sk_" + 32 hex chars

    async def test_generate_unique_keys(self, skm: SignalKeyManager) -> None:
        """매번 고유한 키 발급."""
        key1 = await skm.generate("bot-001")
        # Reset mock to simulate no existing key
        skm._db.fetch_one = AsyncMock(return_value=None)
        key2 = await skm.generate("bot-002")
        assert key1 != key2

    async def test_generate_returns_existing(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """이미 키가 있으면 기존 키 반환."""
        db.fetch_one = AsyncMock(return_value={"key_id": "sk_existing123"})
        key = await skm.generate("bot-001")
        assert key == "sk_existing123"
        # INSERT 호출 안 됨
        db.execute.assert_not_called()

    async def test_generate_saves_to_db(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """키 발급 시 DB에 저장."""
        key = await skm.generate("bot-001")
        db.execute.assert_called_once()
        call_args = db.execute.call_args
        assert "INSERT INTO signal_keys" in call_args[0][0]
        assert call_args[0][1] == (key, "bot-001")


class TestSignalKeyGet:
    """키 조회 테스트."""

    async def test_get_existing_key(self, skm: SignalKeyManager, db: MagicMock) -> None:
        """존재하는 키 조회."""
        db.fetch_one = AsyncMock(return_value={"key_id": "sk_abc123"})
        key = await skm.get_key("bot-001")
        assert key == "sk_abc123"

    async def test_get_nonexistent_key(self, skm: SignalKeyManager) -> None:
        """없는 키 조회 시 None."""
        key = await skm.get_key("bot-999")
        assert key is None


class TestSignalKeyRotate:
    """키 재발급 테스트."""

    async def test_rotate_generates_new_key(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """재발급 시 새 키 반환."""
        db.fetch_one = AsyncMock(return_value={"key_id": "sk_old"})
        new_key = await skm.rotate("bot-001")
        assert new_key.startswith("sk_")
        assert new_key != "sk_old"

    async def test_rotate_deletes_old_key(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """재발급 시 기존 키 삭제."""
        db.fetch_one = AsyncMock(return_value={"key_id": "sk_old"})
        await skm.rotate("bot-001")
        # DELETE + INSERT 호출
        assert db.execute.call_count == 2
        delete_call = db.execute.call_args_list[0]
        assert "DELETE FROM signal_keys" in delete_call[0][0]


class TestSignalKeyRevoke:
    """키 폐기 테스트."""

    async def test_revoke_existing(self, skm: SignalKeyManager, db: MagicMock) -> None:
        """존재하는 키 폐기."""
        db.fetch_one = AsyncMock(return_value={"key_id": "sk_abc"})
        result = await skm.revoke("bot-001")
        assert result is True
        db.execute.assert_called_once()

    async def test_revoke_nonexistent(self, skm: SignalKeyManager) -> None:
        """없는 키 폐기 시 False."""
        result = await skm.revoke("bot-999")
        assert result is False


class TestSignalKeyValidate:
    """키 검증 테스트."""

    async def test_validate_valid_key(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """유효한 키 → bot_id 반환."""
        db.fetch_one = AsyncMock(return_value={"bot_id": "bot-001"})
        bot_id = await skm.validate_key("sk_valid123")
        assert bot_id == "bot-001"

    async def test_validate_invalid_key(self, skm: SignalKeyManager) -> None:
        """무효한 키 → None."""
        bot_id = await skm.validate_key("sk_invalid")
        assert bot_id is None


# ── BotManager 연동 테스트 ──────────────────────────


class _AcceptingStrategy(Strategy):
    """accepts_external_signals=True 전략."""

    meta = StrategyMeta(
        name="accepting",
        version="1.0.0",
        description="accepts signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []


class _NormalStrategy(Strategy):
    """accepts_external_signals=False 전략."""

    meta = StrategyMeta(
        name="normal",
        version="1.0.0",
        description="normal strategy",
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []


class TestBotManagerSignalKey:
    """BotManager 시그널 키 연동."""

    async def test_create_bot_auto_generates_key(self) -> None:
        """accepts_external_signals=True 전략 봇 생성 시 키 자동 발급."""
        from ante.bot.config import BotConfig
        from ante.bot.manager import BotManager

        db = MagicMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        eventbus = MagicMock()
        eventbus.subscribe = MagicMock()

        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_auto123")

        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)

        ctx = MagicMock()
        config = BotConfig(bot_id="bot-001", strategy_id="accepting")

        await manager.create_bot(config, _AcceptingStrategy, ctx=ctx)

        skm.generate.assert_called_once_with("bot-001")

    async def test_create_bot_no_key_for_normal(self) -> None:
        """accepts_external_signals=False 전략은 키 미발급."""
        from ante.bot.config import BotConfig
        from ante.bot.manager import BotManager

        db = MagicMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        eventbus = MagicMock()
        eventbus.subscribe = MagicMock()

        skm = MagicMock()
        skm.generate = AsyncMock()

        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)

        ctx = MagicMock()
        config = BotConfig(bot_id="bot-002", strategy_id="normal")

        await manager.create_bot(config, _NormalStrategy, ctx=ctx)

        skm.generate.assert_not_called()

    async def test_remove_bot_revokes_key(self) -> None:
        """봇 삭제 시 시그널 키 폐기."""
        from ante.bot.config import BotConfig
        from ante.bot.manager import BotManager

        db = MagicMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        eventbus = MagicMock()
        eventbus.subscribe = MagicMock()
        eventbus.unsubscribe = MagicMock()
        eventbus.publish = AsyncMock()

        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_test")
        skm.revoke = AsyncMock(return_value=True)

        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)

        ctx = MagicMock()
        config = BotConfig(bot_id="bot-003", strategy_id="accepting")
        await manager.create_bot(config, _AcceptingStrategy, ctx=ctx)

        await manager.remove_bot("bot-003")

        skm.revoke.assert_called_once_with("bot-003")

    async def test_rotate_signal_key(self) -> None:
        """시그널 키 재발급."""
        from ante.bot.config import BotConfig
        from ante.bot.manager import BotManager

        db = MagicMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        eventbus = MagicMock()
        eventbus.subscribe = MagicMock()

        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_old")
        skm.rotate = AsyncMock(return_value="sk_new123")

        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)

        ctx = MagicMock()
        config = BotConfig(bot_id="bot-004", strategy_id="accepting")
        await manager.create_bot(config, _AcceptingStrategy, ctx=ctx)

        new_key = await manager.rotate_signal_key("bot-004")
        assert new_key == "sk_new123"
        skm.rotate.assert_called_once_with("bot-004")

    async def test_get_signal_key(self) -> None:
        """시그널 키 조회."""
        from ante.bot.config import BotConfig
        from ante.bot.manager import BotManager

        db = MagicMock()
        db.execute = AsyncMock()
        db.execute_script = AsyncMock()
        eventbus = MagicMock()
        eventbus.subscribe = MagicMock()

        skm = MagicMock()
        skm.generate = AsyncMock(return_value="sk_test")
        skm.get_key = AsyncMock(return_value="sk_test")

        manager = BotManager(eventbus=eventbus, db=db, signal_key_manager=skm)

        ctx = MagicMock()
        config = BotConfig(bot_id="bot-005", strategy_id="accepting")
        await manager.create_bot(config, _AcceptingStrategy, ctx=ctx)

        key = await manager.get_signal_key("bot-005")
        assert key == "sk_test"
