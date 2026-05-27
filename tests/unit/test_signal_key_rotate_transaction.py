"""Refs #1901 — ``SignalKeyManager.rotate`` partial-failure rollback 가드.

## 배경

기존 ``rotate`` 는 ``revoke`` (DELETE) 와 ``INSERT`` 를 별개 ``execute`` 로 호출
했다. ``Database.execute`` 는 ``_in_transaction=False`` 일 때 매 호출마다 즉시
``commit`` 하므로:

1. DELETE 가 커밋된다 — 기존 키가 폐기된다.
2. INSERT 가 실패한다 (예: UNIQUE 위반, 디스크 I/O, 연결 단절).
3. 결과: bot 에 시그널 키가 **없는** 상태로 남는다 (orphan revoke). 외부
   신호 송신자는 인증 실패, 운영자는 키를 "신뢰할 수 없게" 잃는다.

수정: ``rotate`` 는 DELETE+INSERT 를 단일 트랜잭션 (``Database.transaction()``)
으로 묶는다. INSERT 실패 시 컨텍스트 매니저가 ROLLBACK 하여 기존 키가 보존
된다.

## 회귀 lock

- R1: 정상 rotate — DELETE+INSERT 모두 트랜잭션 안에서 호출되고 새 키 반환.
- R2: INSERT 실패 주입 → 예외 재전파 + 트랜잭션 컨텍스트 매니저가 ROLLBACK
  까지 호출 (DELETE 와 INSERT 가 동일 트랜잭션에 묶였음을 lock).
- R3: 트랜잭션 컨텍스트 진입 순서 — DELETE 와 INSERT 가 **모두**
  ``transaction()`` 컨텍스트 안에서 실행된다 (mock 진입/종료 시점 검증).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.signal_key import SignalKeyManager


def _tx_factory(db: MagicMock, *, on_enter=None, on_exit=None):  # noqa: ANN001, ANN202
    """Database.transaction() async-context mock factory.

    on_enter / on_exit 콜백으로 컨텍스트 진입/종료 시점을 호출 순서에 기록할
    수 있다 (R3 검증용).
    """

    @asynccontextmanager
    async def _tx():  # noqa: ANN202
        if on_enter is not None:
            on_enter()
        try:
            yield db
        finally:
            if on_exit is not None:
                on_exit()

    return _tx


@pytest.fixture
def db() -> MagicMock:
    """Database mock with transaction() context manager."""
    mock_db = MagicMock()
    mock_db.execute = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value=None)
    mock_db.transaction = MagicMock(side_effect=_tx_factory(mock_db))
    return mock_db


@pytest.fixture
def skm(db: MagicMock) -> SignalKeyManager:
    return SignalKeyManager(db)


# ── R1: 정상 rotate ─────────────────────────────────────


class TestRotateHappyPath:
    """정상 rotate — 새 키 반환 + DELETE+INSERT 모두 호출."""

    async def test_rotate_returns_new_key(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """rotate 가 새 sk_ 키를 반환한다."""
        new_key = await skm.rotate("bot-001")
        assert new_key.startswith("sk_")
        assert len(new_key) == 3 + 32

    async def test_rotate_calls_delete_then_insert(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """rotate 가 DELETE → INSERT 순서로 호출한다."""
        new_key = await skm.rotate("bot-001")
        assert db.execute.call_count == 2

        delete_call = db.execute.call_args_list[0]
        insert_call = db.execute.call_args_list[1]

        assert "DELETE FROM signal_keys" in delete_call[0][0]
        assert delete_call[0][1] == ("bot-001",)

        assert "INSERT INTO signal_keys" in insert_call[0][0]
        assert insert_call[0][1] == (new_key, "bot-001")

    async def test_rotate_opens_single_transaction(
        self, skm: SignalKeyManager, db: MagicMock
    ) -> None:
        """rotate 가 transaction() 컨텍스트를 정확히 한 번 연다."""
        await skm.rotate("bot-001")
        assert db.transaction.call_count == 1


# ── R2: INSERT 실패 주입 → rollback 보존 ────────────────


class TestRotatePartialFailureRollback:
    """INSERT 실패 시 트랜잭션 ROLLBACK — orphan revoke 차단."""

    async def test_insert_failure_rolls_back_via_context_exit(
        self,
    ) -> None:
        """INSERT 가 실패하면 transaction context 가 __aexit__ 경로로
        ROLLBACK 을 수행한다 (mock 호출 순서로 검증).

        실제 ``Database.transaction()`` 은 예외 발생 시 ROLLBACK 후 재전파
        하므로 mock 도 동일 시맨틱을 모사한다. 핵심 invariant: DELETE 와
        INSERT 가 **같은** transaction context 안에서 실행된다.
        """
        call_log: list[str] = []

        mock_db = MagicMock()

        async def _execute(sql: str, params: tuple = ()) -> None:
            if sql.startswith("DELETE"):
                call_log.append("delete")
            elif sql.startswith("INSERT"):
                call_log.append("insert")
                raise RuntimeError("INSERT 실패 주입 (예: UNIQUE 위반)")

        mock_db.execute = AsyncMock(side_effect=_execute)

        rolled_back: list[bool] = []

        @asynccontextmanager
        async def _tx():  # noqa: ANN202
            call_log.append("tx_enter")
            try:
                yield mock_db
                call_log.append("tx_commit")
            except Exception:
                call_log.append("tx_rollback")
                rolled_back.append(True)
                raise

        mock_db.transaction = MagicMock(side_effect=_tx)

        skm = SignalKeyManager(mock_db)

        with pytest.raises(RuntimeError, match="INSERT 실패 주입"):
            await skm.rotate("bot-001")

        # R2 핵심 lock: DELETE 와 INSERT 가 동일 트랜잭션 안에서 발생했고,
        # INSERT 예외가 ROLLBACK 경로를 트리거했다.
        assert call_log == ["tx_enter", "delete", "insert", "tx_rollback"]
        assert rolled_back == [True]

    async def test_insert_failure_does_not_swallow_exception(
        self,
    ) -> None:
        """INSERT 실패 예외가 호출자에게 그대로 전파된다 (rotate 가 silent
        failure 로 키 손실을 숨기지 않는다)."""
        mock_db = MagicMock()

        async def _execute(sql: str, params: tuple = ()) -> None:
            if sql.startswith("INSERT"):
                raise ValueError("디스크 실패")

        mock_db.execute = AsyncMock(side_effect=_execute)

        @asynccontextmanager
        async def _tx():  # noqa: ANN202
            try:
                yield mock_db
            except Exception:
                raise

        mock_db.transaction = MagicMock(side_effect=_tx)

        skm = SignalKeyManager(mock_db)

        with pytest.raises(ValueError, match="디스크 실패"):
            await skm.rotate("bot-001")


# ── R3: DELETE+INSERT 가 같은 transaction context 안 ──


class TestRotateBothStatementsInsideSameTransaction:
    """DELETE 와 INSERT 가 트랜잭션 컨텍스트 진입 후 / 종료 전 사이에 실행."""

    async def test_execute_calls_bracketed_by_transaction_context(
        self,
    ) -> None:
        """tx_enter → DELETE → INSERT → tx_commit 순서가 보장된다.

        이 순서가 깨지면 (예: DELETE 가 컨텍스트 진입 **전** 실행되면) 부분
        성공이 다시 가능해진다. 본 테스트는 그 회귀를 lock 한다.
        """
        call_log: list[str] = []

        mock_db = MagicMock()

        async def _execute(sql: str, params: tuple = ()) -> None:
            if sql.startswith("DELETE"):
                call_log.append("delete")
            elif sql.startswith("INSERT"):
                call_log.append("insert")

        mock_db.execute = AsyncMock(side_effect=_execute)

        @asynccontextmanager
        async def _tx():  # noqa: ANN202
            call_log.append("tx_enter")
            try:
                yield mock_db
                call_log.append("tx_commit")
            except Exception:
                call_log.append("tx_rollback")
                raise

        mock_db.transaction = MagicMock(side_effect=_tx)

        skm = SignalKeyManager(mock_db)
        new_key = await skm.rotate("bot-001")

        assert new_key.startswith("sk_")
        assert call_log == ["tx_enter", "delete", "insert", "tx_commit"]


# ── Integration: 실제 Database 와 sqlite UNIQUE 위반 ──


class TestRotateIntegrationRealDatabase:
    """실제 ``Database`` + sqlite 로 partial-failure 시 기존 키 보존 검증.

    mock 만으로는 ``transaction()`` 의 commit/rollback 시맨틱이 실제 SQLite
    동작과 일치하는지 확인할 수 없다. 본 통합 케이스는 ``token_hex`` 를
    monkeypatch 해 INSERT 가 UNIQUE 위반을 일으키도록 유도하고, ROLLBACK
    후 기존 키가 그대로 남는지 확인한다.
    """

    async def test_insert_unique_violation_preserves_existing_key(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ante.core.database import Database

        db = Database(str(tmp_path / "rotate_rollback.db"))
        await db.connect()
        try:
            skm = SignalKeyManager(db)
            await skm.initialize()

            # 1) 두 봇에 각각 키 발급 (key collision 시나리오 준비).
            #    monkeypatch 로 generate 가 deterministic 한 키를 반환하게
            #    만들어, bot-other 의 키가 "충돌 키" 역할을 한다.
            monkeypatch.setattr(
                "ante.bot.signal_key.secrets.token_hex",
                lambda nbytes: "a" * (nbytes * 2),  # → sk_aaaa...
            )
            await skm.generate("bot-other")
            existing_other = await skm.get_key("bot-other")
            assert existing_other == "sk_" + "a" * 32

            # bot-target 에는 다른 키를 부여 (직접 INSERT).
            await db.execute(
                "INSERT INTO signal_keys (key_id, bot_id) VALUES (?, ?)",
                ("sk_target_original_key_value_xxxxx", "bot-target"),
            )
            assert await skm.get_key("bot-target") == (
                "sk_target_original_key_value_xxxxx"
            )

            # 2) bot-target 의 rotate 가 같은 deterministic 키 (= bot-other 가
            #    이미 점유) 를 발급하려 시도 → UNIQUE(bot_id) 가 아니라
            #    PRIMARY KEY(key_id) 위반으로 INSERT 실패.
            with pytest.raises(Exception):  # noqa: BLE001 — sqlite IntegrityError 우회
                await skm.rotate("bot-target")

            # 3) ROLLBACK 가드 lock: bot-target 의 기존 키가 보존된다.
            preserved = await skm.get_key("bot-target")
            assert preserved == "sk_target_original_key_value_xxxxx", (
                "INSERT 실패 시 DELETE 가 롤백되지 않아 키가 사라졌습니다 (#1901 회귀)."
            )

            # bot-other 키도 그대로.
            assert await skm.get_key("bot-other") == "sk_" + "a" * 32
        finally:
            await db.close()
