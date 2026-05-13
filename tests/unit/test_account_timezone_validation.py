"""Account timezone IANA 검증 — HTTP PUT ingress + service boundary + 헬퍼.

SSOT:
- Python ``zoneinfo.ZoneInfo`` / IANA timezone database.
- ``src/ante/account/timezone.py`` (``validate_iana_timezone`` 헬퍼).
- ``src/ante/web/schemas.py`` (AccountCreate/UpdateRequest.timezone validator).
- ``src/ante/account/service.py`` (create/_create_seed_account/update boundary).
- ``src/ante/web/routes/accounts.py`` (PUT 422 매핑).

이슈 #1473 (split #1419/A): ``PUT /api/accounts/{id}`` 가 invalid IANA timezone
(예: ``"Mars/Olympus"``)을 200 으로 저장하지 않도록, Pydantic field_validator 와
service boundary 양쪽에서 검증한다.

회귀 보존:
- POST cold-path 409 (검증 대상 아님).
- 유효 IANA timezone (``Asia/Seoul``, ``US/Eastern``, ``America/New_York``)
  은 200 통과.
- ``Account.__post_init__`` hard 검증 미적용 (legacy DB row load 호환).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import (  # noqa: E402
    AccountDeletedError,
    AccountNotFoundError,
    InvalidBrokerTypeError,
)
from ante.account.models import Account, AccountStatus, TradingMode  # noqa: E402
from ante.account.service import AccountService  # noqa: E402
from ante.account.timezone import validate_iana_timezone  # noqa: E402
from ante.core.database import Database  # noqa: E402
from ante.eventbus.bus import EventBus  # noqa: E402
from ante.member.models import MemberRole  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from ante.web.schemas import AccountCreateRequest, AccountUpdateRequest  # noqa: E402
from tests.unit.conftest import make_authed_client  # noqa: E402

_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


# ── 헬퍼 단위 ────────────────────────────────────────────


class TestValidateIanaTimezoneHelper:
    """``validate_iana_timezone`` 헬퍼의 IANA 유효성 판정 단위."""

    def test_helper_accepts_asia_seoul(self) -> None:
        """유효한 ``Asia/Seoul`` 은 그대로 반환된다."""
        assert validate_iana_timezone("Asia/Seoul") == "Asia/Seoul"

    def test_helper_accepts_us_eastern(self) -> None:
        """유효한 legacy alias ``US/Eastern`` 은 그대로 반환된다.

        ``tests/unit/test_account_immutable_fields.py`` line 106 회귀 패턴.
        """
        assert validate_iana_timezone("US/Eastern") == "US/Eastern"

    def test_helper_accepts_america_new_york(self) -> None:
        """유효한 ``America/New_York`` 은 그대로 반환된다."""
        assert validate_iana_timezone("America/New_York") == "America/New_York"

    def test_helper_rejects_unknown_key(self) -> None:
        """존재하지 않는 IANA key 는 ``ValueError`` 로 거부된다."""
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            validate_iana_timezone("Mars/Olympus")

    def test_helper_rejects_empty_string(self) -> None:
        """빈 문자열은 ``ZoneInfoNotFoundError`` → ``ValueError`` 로 거부된다.

        caller(schema validator)가 빈 문자열 처리(default 보존)를 책임지며,
        헬퍼는 ZoneInfo 위임으로 ``""`` 도 invalid 로 본다.
        """
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            validate_iana_timezone("")


# ── Pydantic schema 단위 ────────────────────────────────────


class TestAccountCreateRequestTimezone:
    """AccountCreateRequest timezone validator (``""`` default 보존)."""

    @staticmethod
    def _base_kwargs() -> dict[str, str]:
        return {
            "account_id": "test-account",
            "name": "테스트 계좌",
        }

    def test_create_rejects_invalid_timezone(self) -> None:
        """invalid IANA timezone 은 ValidationError 로 거부된다."""
        with pytest.raises(ValidationError) as exc_info:
            AccountCreateRequest(
                **self._base_kwargs(),
                timezone="Mars/Olympus",
            )
        assert "timezone" in str(exc_info.value)

    def test_create_accepts_empty_default(self) -> None:
        """``""`` 는 default 의미 보존을 위해 통과한다.

        CLI/seed 경로에서 BrokerPreset fallback 이 ``""`` 를 preset value 로
        채우기 때문에 schema 에서 ``""`` 를 거부하지 않는다.
        """
        req = AccountCreateRequest(
            **self._base_kwargs(),
            timezone="",
        )
        assert req.timezone == ""

    def test_create_accepts_valid_timezone(self) -> None:
        """유효한 IANA timezone 은 통과한다."""
        for value in ("Asia/Seoul", "America/New_York", "US/Eastern"):
            req = AccountCreateRequest(
                **self._base_kwargs(),
                timezone=value,
            )
            assert req.timezone == value


class TestAccountUpdateRequestTimezone:
    """AccountUpdateRequest timezone validator (``None`` 만 통과, ``""`` 도 거부)."""

    def test_update_rejects_invalid_timezone(self) -> None:
        """invalid IANA timezone 은 ValidationError 로 거부된다."""
        with pytest.raises(ValidationError) as exc_info:
            AccountUpdateRequest(timezone="Mars/Olympus")
        assert "timezone" in str(exc_info.value)

    def test_update_rejects_empty_string(self) -> None:
        """``""`` 는 update 경로에서 거부된다 — broker preset fallback 없음.

        ``trading_hours_*`` update validator 패턴 (``""`` reject)과 일관.
        """
        with pytest.raises(ValidationError):
            AccountUpdateRequest(timezone="")

    def test_update_allows_none(self) -> None:
        """``None`` 은 필드 미제공 의미로 통과한다."""
        req = AccountUpdateRequest(timezone=None)
        assert req.timezone is None

    def test_update_accepts_valid_timezone(self) -> None:
        """유효한 IANA timezone 은 통과한다."""
        for value in ("Asia/Seoul", "America/New_York", "US/Eastern"):
            req = AccountUpdateRequest(timezone=value)
            assert req.timezone == value


# ── HTTP PUT/POST 통합 ────────────────────────────────────


@dataclass
class _StubMember:
    member_id: str
    role: str = "default"
    type: str = "agent"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = dc_field(default_factory=list)


class _StubMemberService:
    def __init__(self) -> None:
        self._members: dict[str, _StubMember] = {
            "master-user": _StubMember(
                member_id="master-user", role=MemberRole.MASTER.value
            ),
        }
        self._tokens: dict[str, str] = {"master-token": "master-user"}

    async def authenticate(self, token: str) -> _StubMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _StubMember | None:
        return self._members.get(member_id)


class _FakeAccountService:
    """테스트용 AccountService 모의 — PUT 통합 테스트 전용."""

    UPDATABLE_FIELDS = frozenset(
        {
            "name",
            "timezone",
            "trading_hours_start",
            "trading_hours_end",
            "credentials",
            "broker_config",
            "buy_commission_rate",
            "sell_commission_rate",
        }
    )
    IMMUTABLE_FIELDS = frozenset(
        {"exchange", "currency", "trading_mode", "broker_type"}
    )

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        return list(self._accounts.values())

    async def update(self, account_id: str, **fields: Any) -> Account:
        from ante.account.errors import AccountImmutableFieldError

        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )

        attempted_immutable = set(fields.keys()) & self.IMMUTABLE_FIELDS
        if attempted_immutable:
            raise AccountImmutableFieldError(
                f"다음 필드는 수정할 수 없습니다: {sorted(attempted_immutable)}"
            )
        unrecognized = (
            set(fields.keys()) - self.UPDATABLE_FIELDS - self.IMMUTABLE_FIELDS
        )
        if unrecognized:
            raise ValueError(f"인식할 수 없는 필드입니다: {sorted(unrecognized)}")
        for key, value in fields.items():
            setattr(account, key, value)
        account.updated_at = datetime.now(UTC)
        return account

    async def get_broker(self, account_id: str) -> Any:  # pragma: no cover
        raise InvalidBrokerTypeError("not used in this suite")


def _make_account(account_id: str = "test-account") -> Account:
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        credentials={"secret_key": "hidden"},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def account_service() -> _FakeAccountService:
    return _FakeAccountService()


@pytest.fixture
def client(account_service: _FakeAccountService) -> TestClient:
    app = create_app(
        account_service=account_service,
        member_service=_StubMemberService(),
    )
    client = make_authed_client(app)
    client.headers.update(_MASTER_HEADERS)
    return client


class TestPutTimezoneIngress:
    """``PUT /api/accounts/{id}`` 의 timezone ingress 검증."""

    def test_put_invalid_timezone_returns_422(
        self,
        client: TestClient,
        account_service: _FakeAccountService,
    ) -> None:
        """invalid IANA timezone (``Mars/Olympus``) 은 422 로 거부된다.

        이슈 #1473 직접 회귀: 변경 전에는 200 + invalid 값 저장이었다.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": "Mars/Olympus"},
        )
        assert resp.status_code == 422
        # service 미호출 — 계좌 timezone 변경되지 않음
        assert account_service._accounts["test-account"].timezone == "Asia/Seoul"

    def test_put_empty_timezone_returns_422(
        self,
        client: TestClient,
        account_service: _FakeAccountService,
    ) -> None:
        """``""`` 는 update 경로에서 422 — broker preset fallback 없음.

        ``trading_hours_*`` ``""`` reject 패턴과 일관 (#1334).
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": ""},
        )
        assert resp.status_code == 422
        assert account_service._accounts["test-account"].timezone == "Asia/Seoul"

    def test_put_valid_asia_seoul_returns_200(
        self,
        client: TestClient,
        account_service: _FakeAccountService,
    ) -> None:
        """유효한 ``Asia/Seoul`` 회귀."""
        account = _make_account()
        account.timezone = "America/New_York"  # 변경 회귀를 위해 다른 값으로 시작
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": "Asia/Seoul"},
        )
        assert resp.status_code == 200
        assert resp.json()["account"]["timezone"] == "Asia/Seoul"
        assert account_service._accounts["test-account"].timezone == "Asia/Seoul"

    def test_put_valid_us_eastern_returns_200(
        self,
        client: TestClient,
        account_service: _FakeAccountService,
    ) -> None:
        """유효한 legacy alias ``US/Eastern`` 회귀.

        ``tests/unit/test_account_immutable_fields.py`` line 106 패턴.
        """
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"timezone": "US/Eastern"},
        )
        assert resp.status_code == 200
        assert resp.json()["account"]["timezone"] == "US/Eastern"
        assert account_service._accounts["test-account"].timezone == "US/Eastern"

    def test_post_cold_path_returns_409(
        self,
        client: TestClient,
    ) -> None:
        """POST cold-path 409 회귀 — invalid timezone 이어도 409 (검증 대상 아님)."""
        resp = client.post(
            "/api/accounts",
            json={
                "account_id": "another-acct",
                "name": "테스트",
                "exchange": "TEST",
                "currency": "KRW",
                "broker_type": "test",
                "timezone": "Mars/Olympus",
            },
        )
        # cold-path 가드가 body validation 전에 즉시 409 를 반환한다.
        assert resp.status_code == 409


# ── Service boundary (defense-in-depth) ──────────────────────


@pytest_asyncio.fixture
async def real_db(tmp_path):
    db_path = str(tmp_path / "test_timezone_service.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def real_service(real_db):
    svc = AccountService(real_db, EventBus())
    await svc.initialize()
    return svc


def _service_account(account_id: str = "main", timezone: str = "Asia/Seoul") -> Account:
    return Account(
        account_id=account_id,
        name="테스트",
        exchange="TEST",
        currency="KRW",
        timezone=timezone,
        broker_type="test",
        credentials={"app_key": "test", "app_secret": "test"},
    )


class TestServiceTimezoneBoundary:
    """AccountService boundary defense-in-depth — 비-HTTP caller 보호."""

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_timezone(self, real_service) -> None:
        """``create()`` 에 invalid timezone 인 Account 를 직접 넣으면 ValueError."""
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            await real_service.create(_service_account(timezone="Mars/Olympus"))

    @pytest.mark.asyncio
    async def test_create_accepts_valid_timezone(self, real_service) -> None:
        """유효한 timezone 으로 ``create()`` 는 성공한다."""
        account = await real_service.create(
            _service_account(timezone="America/New_York")
        )
        assert account.timezone == "America/New_York"

    @pytest.mark.asyncio
    async def test_create_accepts_empty_default(self, real_service) -> None:
        """``""`` 는 default 의미 보존을 위해 service 단에서도 통과."""
        account = await real_service.create(
            _service_account(account_id="empty-tz", timezone="")
        )
        assert account.timezone == ""

    @pytest.mark.asyncio
    async def test_update_rejects_invalid_timezone(self, real_service) -> None:
        """``update()`` 의 invalid timezone 은 ValueError."""
        await real_service.create(_service_account())
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            await real_service.update("main", timezone="Mars/Olympus")

    @pytest.mark.asyncio
    async def test_update_accepts_valid_timezone(self, real_service) -> None:
        """``update()`` 유효 timezone 회귀."""
        await real_service.create(_service_account())
        updated = await real_service.update("main", timezone="US/Eastern")
        assert updated.timezone == "US/Eastern"

    @pytest.mark.asyncio
    async def test_create_seed_account_rejects_invalid_timezone(
        self, real_service
    ) -> None:
        """``_create_seed_account()`` 도 invalid timezone 거부.

        seed 경로는 (broker_type, default_account_id) pair 가드 + account_id
        형식 검증을 통과한 뒤 timezone defense-in-depth 가 적용된다.
        BROKER_PRESETS 의 ``test`` preset 은 ``default_account_id="test"`` 다.
        """
        seed_account = Account(
            account_id="test",
            name="seed",
            exchange="TEST",
            currency="KRW",
            timezone="Mars/Olympus",
            broker_type="test",
            credentials={"app_key": "test", "app_secret": "test"},
        )
        with pytest.raises(ValueError, match="invalid IANA timezone"):
            await real_service._create_seed_account(seed_account)
