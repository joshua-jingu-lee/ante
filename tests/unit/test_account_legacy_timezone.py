"""Legacy invalid timezone row tolerant load + repair 절차 단위 테스트 (#1474).

SSOT:

- ``src/ante/account/timezone.py`` (``is_valid_iana_timezone``,
  ``DEFAULT_FALLBACK_TIMEZONE``).
- ``src/ante/account/service.py`` (``_row_to_account`` tolerant load,
  ``AccountService.repair_timezone``).
- ``src/ante/web/routes/accounts.py`` (``_account_to_response``
  ``timezone_invalid`` 노출).
- ``src/ante/cli/commands/account.py`` (``account repair-timezone``).

이슈 #1474 (split #1419/B): #1473 이전에 저장된 invalid IANA timezone row
(예: ``Mars/Olympus``) 가 ``GET`` / ``load`` 경로를 깨지 않도록 fallback
대체 + 진단 플래그 + 명시적 repair 절차를 제공한다.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from click.testing import CliRunner

from ante.account.crypto import encrypt_credentials
from ante.account.errors import (
    AccountDeletedException,
    AccountNotFoundError,
    AccountStructuralChangeRequiresStoppedServerError,
)
from ante.account.models import Account, AccountStatus, TradingMode
from ante.account.service import AccountService, _row_to_account
from ante.account.timezone import (
    DEFAULT_FALLBACK_TIMEZONE,
    is_valid_iana_timezone,
    validate_iana_timezone,
)
from ante.core.database import Database
from ante.eventbus.bus import EventBus

# ── is_valid_iana_timezone 헬퍼 ────────────────────────────


class TestIsValidIanaTimezone:
    """``is_valid_iana_timezone`` 헬퍼의 raise 없는 bool 판정 단위."""

    def test_accepts_asia_seoul(self) -> None:
        assert is_valid_iana_timezone("Asia/Seoul") is True

    def test_accepts_us_eastern(self) -> None:
        assert is_valid_iana_timezone("US/Eastern") is True

    def test_accepts_america_new_york(self) -> None:
        assert is_valid_iana_timezone("America/New_York") is True

    def test_rejects_mars_olympus(self) -> None:
        assert is_valid_iana_timezone("Mars/Olympus") is False

    def test_rejects_empty_string(self) -> None:
        assert is_valid_iana_timezone("") is False

    def test_rejects_absolute_path(self) -> None:
        """절대 경로는 ZoneInfo 가 ValueError — invalid 로 판정."""
        assert is_valid_iana_timezone("/etc/localtime") is False

    def test_default_fallback_is_valid(self) -> None:
        """fallback timezone 자체는 valid IANA 여야 한다 (실수 방지)."""
        assert is_valid_iana_timezone(DEFAULT_FALLBACK_TIMEZONE) is True
        # 기존 validate_iana_timezone 도 동일하게 통과
        assert validate_iana_timezone(DEFAULT_FALLBACK_TIMEZONE) == "Asia/Seoul"


# ── _row_to_account tolerant load ────────────────────────────


def _row_template(
    account_id: str = "legacy",
    timezone: str = "Mars/Olympus",
) -> dict:
    """``_row_to_account`` 가 기대하는 DB row dict (모든 컬럼 채움)."""
    return {
        "account_id": account_id,
        "name": "legacy account",
        "exchange": "TEST",
        "currency": "KRW",
        "timezone": timezone,
        "trading_hours_start": "09:00",
        "trading_hours_end": "15:30",
        "trading_mode": "virtual",
        "broker_type": "test",
        "credentials": encrypt_credentials({"app_key": "k", "app_secret": "s"}),
        "broker_config": "{}",
        "buy_commission_rate": 0,
        "sell_commission_rate": 0,
        "market_order_reserve_buffer_rate": 0,
        "status": "active",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


class TestRowToAccountTolerantLoad:
    """``_row_to_account`` 의 invalid timezone fallback 단위."""

    def test_valid_timezone_passes_through(self) -> None:
        """유효 row 는 그대로 통과, ``timezone_invalid`` 는 False."""
        row = _row_template(timezone="Asia/Seoul")
        account = _row_to_account(row)
        assert account.timezone == "Asia/Seoul"
        assert account.timezone_invalid is False

    def test_us_eastern_legacy_alias_passes_through(self) -> None:
        """legacy alias ``US/Eastern`` 도 valid 로 인정 (회귀 보존)."""
        row = _row_template(timezone="US/Eastern")
        account = _row_to_account(row)
        assert account.timezone == "US/Eastern"
        assert account.timezone_invalid is False

    def test_invalid_timezone_falls_back(self) -> None:
        """invalid ``Mars/Olympus`` 는 fallback 으로 대체 + flag 세팅."""
        row = _row_template(timezone="Mars/Olympus")
        account = _row_to_account(row)
        assert account.timezone == DEFAULT_FALLBACK_TIMEZONE
        assert account.timezone == "Asia/Seoul"
        assert account.timezone_invalid is True

    def test_invalid_timezone_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """fallback 시 WARNING 로그가 남아 운영자가 식별할 수 있다."""
        row = _row_template(account_id="legacy-mars", timezone="Mars/Olympus")
        with caplog.at_level(logging.WARNING, logger="ante.account.service"):
            _row_to_account(row)
        # warning 메시지에 account_id 와 invalid 값이 포함되어야 한다.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "legacy-mars" in r.getMessage() and "Mars/Olympus" in r.getMessage()
            for r in warnings
        ), f"warning 누락: {[r.getMessage() for r in warnings]}"

    def test_empty_timezone_also_falls_back(self) -> None:
        """legacy 환경에서 ``""`` 가 발견되어도 fallback 처리."""
        row = _row_template(timezone="")
        account = _row_to_account(row)
        assert account.timezone == DEFAULT_FALLBACK_TIMEZONE
        assert account.timezone_invalid is True


# ── AccountService.initialize / get / list tolerant ────────────


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = str(tmp_path / "test_legacy_timezone.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def initialized_service(db):
    svc = AccountService(db, EventBus())
    await svc.initialize()
    return svc


async def _insert_legacy_row(
    db: Database,
    *,
    account_id: str = "legacy-mars",
    timezone: str = "Mars/Olympus",
    status: str = "active",
) -> None:
    """invalid timezone row 를 DB 에 직접 INSERT 한다 (#1473 service 가드 우회)."""
    await db.execute(
        """INSERT INTO accounts
           (account_id, name, exchange, currency, timezone,
            trading_hours_start, trading_hours_end, trading_mode,
            broker_type, credentials, broker_config,
            buy_commission_rate, sell_commission_rate,
            market_order_reserve_buffer_rate,
            status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            "legacy account",
            "TEST",
            "KRW",
            timezone,
            "09:00",
            "15:30",
            "virtual",
            "test",
            encrypt_credentials({"app_key": "k", "app_secret": "s"}),
            "{}",
            0,
            0,
            0,
            status,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )


class TestServiceTolerantLoad:
    """``initialize`` / ``get`` / ``list`` 가 invalid row 에도 crash 하지 않는다."""

    @pytest.mark.asyncio
    async def test_initialize_loads_invalid_row_without_crash(self, db) -> None:
        """invalid row 가 들어 있어도 ``initialize`` 가 성공해야 한다."""
        # service 의 initialize 가 schema 를 만들도록 한 번 통과시킨 뒤
        # legacy row 를 직접 INSERT 하고 fresh service 로 다시 load 한다.
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")

        svc = AccountService(db, EventBus())
        await svc.initialize()  # crash 하지 않아야 한다
        loaded = await svc.get("legacy-mars")
        assert loaded.timezone == DEFAULT_FALLBACK_TIMEZONE
        assert loaded.timezone_invalid is True
        # 다른 컬럼은 정상 로드
        assert loaded.name == "legacy account"
        assert loaded.exchange == "TEST"

    @pytest.mark.asyncio
    async def test_list_returns_invalid_row(self, db) -> None:
        """``list()`` 가 invalid row 를 포함해 정상 응답."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        await _insert_legacy_row(db, account_id="legacy-valid", timezone="Asia/Seoul")

        svc = AccountService(db, EventBus())
        await svc.initialize()
        accounts = await svc.list()
        ids = {a.account_id for a in accounts}
        assert ids == {"legacy-mars", "legacy-valid"}
        by_id = {a.account_id: a for a in accounts}
        assert by_id["legacy-mars"].timezone_invalid is True
        assert by_id["legacy-mars"].timezone == DEFAULT_FALLBACK_TIMEZONE
        assert by_id["legacy-valid"].timezone_invalid is False
        assert by_id["legacy-valid"].timezone == "Asia/Seoul"

    @pytest.mark.asyncio
    async def test_get_returns_fallback_with_flag(self, db) -> None:
        """``get()`` 도 fallback + flag 로 응답 (메모리 cache 경로)."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        svc = AccountService(db, EventBus())
        await svc.initialize()

        account = await svc.get("legacy-mars")
        assert account.timezone == "Asia/Seoul"
        assert account.timezone_invalid is True


# ── AccountService.repair_timezone ────────────────────────────


class TestRepairTimezone:
    """``AccountService.repair_timezone`` 의 cold-path repair 의미론."""

    @pytest.mark.asyncio
    async def test_repair_fixes_invalid_row(self, db) -> None:
        """invalid row 를 valid timezone 으로 교정하면 flag 가 사라진다."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        svc = AccountService(db, EventBus())
        await svc.initialize()

        # pre: fallback + flag
        before = await svc.get("legacy-mars")
        assert before.timezone_invalid is True

        # repair
        repaired = await svc.repair_timezone("legacy-mars", "US/Eastern")
        assert repaired.timezone == "US/Eastern"
        assert repaired.timezone_invalid is False

        # post: DB 에 영구 반영. fresh service 로 다시 load 해도 valid.
        svc2 = AccountService(db, EventBus())
        await svc2.initialize()
        after = await svc2.get("legacy-mars")
        assert after.timezone == "US/Eastern"
        assert after.timezone_invalid is False

    @pytest.mark.asyncio
    async def test_repair_rejects_invalid_new_timezone(self, db) -> None:
        """새 timezone 도 valid IANA 여야 한다 — invalid 면 ValueError."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        svc = AccountService(db, EventBus())
        await svc.initialize()

        with pytest.raises(ValueError, match="invalid IANA timezone"):
            await svc.repair_timezone("legacy-mars", "Atlantis/Capital")

        # row 변경 없음 — 여전히 fallback 응답.
        unchanged = await svc.get("legacy-mars")
        assert unchanged.timezone == DEFAULT_FALLBACK_TIMEZONE
        assert unchanged.timezone_invalid is True

    @pytest.mark.asyncio
    async def test_repair_rejects_runtime_started(self, db) -> None:
        """``mark_runtime_started()`` 후 호출은 cold-path 가드로 차단."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        svc = AccountService(db, EventBus())
        await svc.initialize()
        svc.mark_runtime_started()

        with pytest.raises(AccountStructuralChangeRequiresStoppedServerError):
            await svc.repair_timezone("legacy-mars", "Asia/Seoul")

    @pytest.mark.asyncio
    async def test_repair_not_found(self, initialized_service) -> None:
        """없는 계좌는 AccountNotFoundError."""
        with pytest.raises(AccountNotFoundError):
            await initialized_service.repair_timezone("ghost", "Asia/Seoul")

    @pytest.mark.asyncio
    async def test_repair_rejects_deleted_account(self, db) -> None:
        """DELETED 계좌는 복구 대상이 아니다."""
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(
            db, account_id="legacy-deleted", timezone="Mars/Olympus", status="deleted"
        )
        svc = AccountService(db, EventBus())
        await svc.initialize()

        with pytest.raises(AccountDeletedException):
            await svc.repair_timezone("legacy-deleted", "Asia/Seoul")

    @pytest.mark.asyncio
    async def test_repair_accepts_already_valid_row(self, db) -> None:
        """invalid 가 아니어도 repair 호출은 허용 — 명시적 rewrite 진입점."""
        # 정상 row 를 만들고 같은 명령으로 timezone 을 다른 valid 로 교정.
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="ok-row", timezone="Asia/Seoul")
        svc = AccountService(db, EventBus())
        await svc.initialize()

        repaired = await svc.repair_timezone("ok-row", "America/New_York")
        assert repaired.timezone == "America/New_York"
        assert repaired.timezone_invalid is False


# ── web route timezone_invalid 노출 ────────────────────────────


class TestRouteAccountToResponseFlag:
    """``_account_to_response`` 가 ``timezone_invalid`` 를 노출한다."""

    def test_response_includes_flag_true(self) -> None:
        from ante.web.routes.accounts import _account_to_response

        account = Account(
            account_id="legacy",
            name="legacy",
            exchange="TEST",
            currency="KRW",
            timezone="Asia/Seoul",
            broker_type="test",
            credentials={},
            timezone_invalid=True,
        )
        resp = _account_to_response(account)
        assert resp["timezone_invalid"] is True
        assert resp["timezone"] == "Asia/Seoul"

    def test_response_includes_flag_false_for_valid(self) -> None:
        from ante.web.routes.accounts import _account_to_response

        account = Account(
            account_id="valid",
            name="valid",
            exchange="TEST",
            currency="KRW",
            timezone="US/Eastern",
            broker_type="test",
            credentials={},
        )
        resp = _account_to_response(account)
        assert resp["timezone_invalid"] is False
        assert resp["timezone"] == "US/Eastern"


# ── CLI ante account repair-timezone ────────────────────────────


def _invoke(args: list[str]):
    """CLI runner 헬퍼 (test_account_cli 패턴)."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


@pytest.fixture
def mock_account_service():
    """AccountService mock fixture (test_account_cli 패턴)."""
    svc = AsyncMock()
    db = AsyncMock()

    async def _create_service():
        return svc, db

    with patch(
        "ante.cli.commands.account._create_account_service", new=_create_service
    ):
        yield svc


@pytest.fixture(autouse=True)
def bypass_auth():
    from ante.member.models import Member, MemberRole, MemberStatus, MemberType

    mock_member = Member(
        member_id="tester",
        name="테스터",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        status=MemberStatus.ACTIVE,
        scopes=[],
    )
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": mock_member}),
    ):
        yield


@pytest.fixture
def offline_runtime():
    """active runtime 부재를 모사한다 (cold-path 통과)."""
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_offline_runtime_repair_tz__.sock",
        ),
    ):
        yield


def _repaired_account() -> Account:
    return Account(
        account_id="legacy-mars",
        name="legacy",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        broker_type="test",
        credentials={},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        status=AccountStatus.ACTIVE,
        trading_mode=TradingMode.VIRTUAL,
        timezone_invalid=False,
    )


class TestCliAccountRepairTimezone:
    """``ante account repair-timezone`` 비대화형 CLI 계약."""

    def test_repair_success(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        mock_account_service.repair_timezone.return_value = _repaired_account()
        result = _invoke(
            [
                "account",
                "repair-timezone",
                "--account-id",
                "legacy-mars",
                "--timezone",
                "Asia/Seoul",
            ]
        )
        assert result.exit_code == 0, result.output
        # service 호출 인자 검증
        mock_account_service.repair_timezone.assert_awaited_once_with(
            "legacy-mars", "Asia/Seoul"
        )
        assert "legacy-mars" in result.output
        assert "Asia/Seoul" in result.output

    def test_repair_json_success(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        mock_account_service.repair_timezone.return_value = _repaired_account()
        result = _invoke(
            [
                "--format",
                "json",
                "account",
                "repair-timezone",
                "--account-id",
                "legacy-mars",
                "--timezone",
                "Asia/Seoul",
            ]
        )
        assert result.exit_code == 0, result.output
        # JSON 출력에 account_id / timezone / timezone_invalid 키가 노출된다.
        # OutputFormatter 의 success() 는 data dict 를 그대로 dump 한다.
        # 정확한 wrap 키 이름은 formatter 구현에 따라 다를 수 있으므로
        # substring 으로 검증한다.
        assert "legacy-mars" in result.output
        assert "Asia/Seoul" in result.output
        # 진단 플래그가 노출되어야 한다.
        assert "timezone_invalid" in result.output

    def test_repair_missing_account_id(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        result = _invoke(
            [
                "account",
                "repair-timezone",
                "--timezone",
                "Asia/Seoul",
            ]
        )
        assert result.exit_code == 1
        assert "CLI_MISSING_REQUIRED_INPUT" in result.output
        assert "--account-id" in result.output
        mock_account_service.repair_timezone.assert_not_called()

    def test_repair_missing_timezone(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        result = _invoke(
            [
                "account",
                "repair-timezone",
                "--account-id",
                "legacy-mars",
            ]
        )
        assert result.exit_code == 1
        assert "CLI_MISSING_REQUIRED_INPUT" in result.output
        assert "--timezone" in result.output
        mock_account_service.repair_timezone.assert_not_called()

    def test_repair_invalid_timezone_value_text(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        """service 가 ValueError 를 raise 하면 text 모드에서 message 노출."""
        mock_account_service.repair_timezone.side_effect = ValueError(
            "invalid IANA timezone: 'Mars/Olympus'"
        )
        result = _invoke(
            [
                "account",
                "repair-timezone",
                "--account-id",
                "legacy-mars",
                "--timezone",
                "Mars/Olympus",
            ]
        )
        assert result.exit_code == 1
        # text 모드 stderr 출력에 메시지가 포함된다.
        assert "invalid IANA timezone" in result.output

    def test_repair_invalid_timezone_value_json(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        """JSON 모드에서는 ACCOUNT_INVALID_TIMEZONE code 가 노출된다.

        ``OutputFormatter.error`` 는 JSON 모드에서만 ``code`` 를 dump 한다.
        """
        mock_account_service.repair_timezone.side_effect = ValueError(
            "invalid IANA timezone: 'Mars/Olympus'"
        )
        result = _invoke(
            [
                "--format",
                "json",
                "account",
                "repair-timezone",
                "--account-id",
                "legacy-mars",
                "--timezone",
                "Mars/Olympus",
            ]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "ACCOUNT_INVALID_TIMEZONE"
        assert "invalid IANA timezone" in payload["message"]

    def test_repair_not_found(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        mock_account_service.repair_timezone.side_effect = AccountNotFoundError(
            "계좌 'ghost'를 찾을 수 없습니다."
        )
        result = _invoke(
            [
                "--format",
                "json",
                "account",
                "repair-timezone",
                "--account-id",
                "ghost",
                "--timezone",
                "Asia/Seoul",
            ]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["code"] == "ACCOUNT_NOT_FOUND"

    def test_repair_deleted(
        self,
        offline_runtime,
        mock_account_service: AsyncMock,
    ) -> None:
        mock_account_service.repair_timezone.side_effect = AccountDeletedException(
            "삭제된 계좌"
        )
        result = _invoke(
            [
                "--format",
                "json",
                "account",
                "repair-timezone",
                "--account-id",
                "deleted-acct",
                "--timezone",
                "Asia/Seoul",
            ]
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["code"] == "ACCOUNT_ALREADY_DELETED"


# ── 회귀: 기존 valid timezone load + update 경로 ────────────────


class TestExistingValidTimezoneRegression:
    """기존 valid timezone load/update 경로가 깨지지 않아야 한다 (#1473 호환)."""

    @pytest.mark.asyncio
    async def test_create_load_roundtrip_no_flag(self, initialized_service) -> None:
        """정상 create → load 시 ``timezone_invalid`` 는 False 그대로."""
        created = await initialized_service.create(
            Account(
                account_id="main",
                name="ok",
                exchange="TEST",
                currency="KRW",
                timezone="US/Eastern",
                broker_type="test",
                credentials={"app_key": "k", "app_secret": "s"},
            )
        )
        assert created.timezone == "US/Eastern"
        assert created.timezone_invalid is False
        # cache 경로
        fetched = await initialized_service.get("main")
        assert fetched.timezone_invalid is False

    @pytest.mark.asyncio
    async def test_update_valid_timezone_does_not_set_flag(
        self, initialized_service
    ) -> None:
        await initialized_service.create(
            Account(
                account_id="main",
                name="ok",
                exchange="TEST",
                currency="KRW",
                timezone="Asia/Seoul",
                broker_type="test",
                credentials={"app_key": "k", "app_secret": "s"},
            )
        )
        updated = await initialized_service.update("main", timezone="America/New_York")
        assert updated.timezone == "America/New_York"
        assert updated.timezone_invalid is False

    @pytest.mark.asyncio
    async def test_update_rejects_invalid_timezone_preserves_flag(
        self, initialized_service, db
    ) -> None:
        """``update()`` 는 #1473 service 가드로 invalid timezone 을 거부해야 한다.

        결과적으로 legacy invalid row 에 update 로 invalid 값을 추가 저장하는
        경로가 막혀 있다.
        """
        await initialized_service.create(
            Account(
                account_id="main",
                name="ok",
                exchange="TEST",
                currency="KRW",
                timezone="Asia/Seoul",
                broker_type="test",
                credentials={"app_key": "k", "app_secret": "s"},
            )
        )
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            await initialized_service.update("main", timezone="Mars/Olympus")
        # row 는 그대로 valid
        fetched = await initialized_service.get("main")
        assert fetched.timezone == "Asia/Seoul"
        assert fetched.timezone_invalid is False


# ── _account_to_detail / _account_to_row 회귀 ──────────────────


def test_account_to_row_includes_existing_fields() -> None:
    """CLI ``list`` 헬퍼 ``_account_to_row`` 는 timezone_invalid 를 누락해도 무방.

    SSOT: CLI list 출력은 기존 컬럼만 보이며, ``timezone_invalid`` 진단 플래그는
    WEB API (``_account_to_response``) 와 ``repair-timezone`` 출력에서만 노출된다.
    list/info 의 출력 컬럼 contract 가 깨지지 않았는지 회귀로 보호한다.
    """
    from ante.cli.commands.account import _account_to_row

    account = Account(
        account_id="legacy",
        name="legacy",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        broker_type="test",
        credentials={},
        timezone_invalid=True,
    )
    row = _account_to_row(account)
    # 기존 6개 컬럼이 그대로 유지되어야 한다.
    assert row == {
        "account_id": "legacy",
        "name": "legacy",
        "exchange": "TEST",
        "currency": "KRW",
        "broker_type": "test",
        "status": "active",
    }


# ── repair_timezone 호출 후 후속 update timezone 회귀 ──────────


class TestRepairFollowedByUpdate:
    """repair 후 update 흐름이 깨지지 않는다 (cache 동기화 확인)."""

    @pytest.mark.asyncio
    async def test_repair_then_update_name(self, db) -> None:
        bootstrap = AccountService(db, EventBus())
        await bootstrap.initialize()
        await _insert_legacy_row(db, account_id="legacy-mars", timezone="Mars/Olympus")
        svc = AccountService(db, EventBus())
        await svc.initialize()

        await svc.repair_timezone("legacy-mars", "US/Eastern")
        # 후속 mutable update 도 정상 진행
        updated = await svc.update("legacy-mars", name="renamed")
        assert updated.name == "renamed"
        assert updated.timezone == "US/Eastern"
        assert updated.timezone_invalid is False


# Sanity: JSON 직렬화에 timezone_invalid 가 포함된다.


def test_account_to_response_json_serializable() -> None:
    from ante.web.routes.accounts import _account_to_response

    account = Account(
        account_id="legacy",
        name="legacy",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        broker_type="test",
        credentials={},
        timezone_invalid=True,
    )
    resp = _account_to_response(account)
    # JSON dump 가 가능해야 한다.
    serialized = json.loads(json.dumps(resp))
    assert serialized["timezone_invalid"] is True
