"""인증 토큰의 만료 시각과 만료 판정을 고정 시계로 단언한다 (#2768).

발급(``register``·``rotate_token``)이 적는 ``token_expires_at``이 고정 시각 +
TTL과 같은지, 인증(``authenticate``)이 그 시각까지(정확히 그 시각 포함)
통과하고 직후에는 거부하는지 본다. 만료 판정은 SQL이 아니라
``TokenManager.check_token_expiry``가 ``ante.core.clock``으로 한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.member.models import MemberType
from ante.member.service import MemberService

_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
_TTL_DAYS = 30
_EXPIRES_AT = _AT + timedelta(days=_TTL_DAYS)
_FORMAT = "%Y-%m-%d %H:%M:%S"

pytestmark = pytest.mark.parametrize("manual_clock", [_AT], indirect=True)


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def service(manual_clock: Any, db: Database) -> MemberService:
    svc = MemberService(db, EventBus(), token_ttl_days=_TTL_DAYS)
    await svc.initialize()
    await svc.bootstrap_master("owner", "pass123")
    return svc


async def _stored_expiry(db: Database, member_id: str) -> str:
    row = await db.fetch_one(
        "SELECT token_expires_at FROM members WHERE member_id = ?", (member_id,)
    )
    assert row is not None
    return str(row["token_expires_at"])


async def test_issued_token_expires_at_clock_plus_ttl(
    service: MemberService, db: Database
) -> None:
    member, _ = await service.register(
        "agent-1", MemberType.AGENT, registered_by="owner"
    )

    assert member.token_expires_at == _EXPIRES_AT.strftime(_FORMAT)
    assert await _stored_expiry(db, "agent-1") == _EXPIRES_AT.strftime(_FORMAT)


async def test_rotated_token_expires_at_rotation_time_plus_ttl(
    service: MemberService, db: Database, manual_clock: Any
) -> None:
    await service.register("agent-1", MemberType.AGENT, registered_by="owner")
    manual_clock.advance(3600.0)

    await service.rotate_token("agent-1", rotated_by="owner")

    expected = (_EXPIRES_AT + timedelta(hours=1)).strftime(_FORMAT)
    assert await _stored_expiry(db, "agent-1") == expected


async def test_token_is_accepted_until_expiry_and_rejected_after(
    service: MemberService, manual_clock: Any
) -> None:
    _, token = await service.register(
        "agent-1", MemberType.AGENT, registered_by="owner"
    )

    manual_clock.advance(_TTL_DAYS * 86400 - 1)
    assert (await service.authenticate(token)).member_id == "agent-1"

    manual_clock.advance(1)
    assert manual_clock.now(UTC) == _EXPIRES_AT
    assert (await service.authenticate(token)).member_id == "agent-1"

    manual_clock.advance(1)
    with pytest.raises(PermissionError, match="만료"):
        await service.authenticate(token)
