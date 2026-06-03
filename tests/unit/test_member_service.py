"""``MemberService.find_invalid_role_members`` 회귀 (#1468).

#1465(write path 차단), #1466(auth read-path guard) 이후 신규 invalid-role row
는 생성되지 않지만 legacy row 가 DB 에 남아 있을 수 있다. 본 모듈은
``find_invalid_role_members`` 의 두 카테고리 분리(``actionable`` /
``legacy_revoked``) 와 CLI revoke 후 이동 동작을 잠근다.

write path 가 invalid role 을 거부하므로 (`MemberService._assert_role_enum`),
legacy row 재현은 정상 ``register`` 후 DB 를 직접 ``UPDATE`` 해 ``role`` 을 변조한다
(``test_member_auth_invalid_role.py`` 의 ``_seed_invalid_role_*`` 패턴 재사용).
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.member.models import MemberStatus, MemberType
from ante.member.service import InvalidRoleScan, MemberService


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def service(db, eventbus) -> MemberService:
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


async def _seed_invalid_role_row(
    db: Database,
    service: MemberService,
    *,
    member_id: str,
    invalid_role: str = "oracle_invalid_role",
) -> None:
    """write path 를 우회해 legacy invalid-role agent row 를 심는다."""
    # #2294: register 는 무조건 master actor 를 요구한다. 본 helper 의 caller 는
    # 모두 사전에 ``bootstrap_master("owner", ...)`` 를 수행한다.
    await service.register(member_id, MemberType.AGENT, registered_by="owner")
    await db.execute(
        "UPDATE members SET role = ? WHERE member_id = ?",
        (invalid_role, member_id),
    )


# ── Service-layer regression ───────────────────────────────────────


class TestFindInvalidRoleMembers:
    """``MemberService.find_invalid_role_members`` 의 카테고리 분리 회귀.

    본 클래스의 ``test_find_invalid_role_members_*`` 메소드 이름은 본문 task
    bullet 과 1:1 매핑된다. 추가로 동일 모듈 하단에 ``test_member_invalid_role_*``
    모듈-level 함수가 같은 어서션을 호출하는 thin alias 로 노출된다. 이는
    본문 verification command ``pytest -k "member_invalid_role or
    list_invalid_roles"`` 의 substring 매칭 요구를 충족시키기 위함이다 (pytest
    -k 는 literal underscore substring 을 요구한다).
    """

    async def test_find_invalid_role_members_empty(
        self, service: MemberService
    ) -> None:
        """정상 role row 만 있을 때 두 리스트 모두 비어 있다."""
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-ok-1", MemberType.AGENT, registered_by="owner")
        await service.register("agent-ok-2", MemberType.AGENT, registered_by="owner")

        scan = await service.find_invalid_role_members()

        assert isinstance(scan, InvalidRoleScan)
        assert scan.actionable == []
        assert scan.legacy_revoked == []

    async def test_find_invalid_role_members_with_invalid_rows(
        self, service: MemberService, db: Database
    ) -> None:
        """invalid role row 2건(active 1, suspended 1) + 정상 2건 → actionable 2건.

        suspended 도 ``status != revoked`` 이므로 actionable 로 분류된다.
        """
        await service.bootstrap_master("owner", "pass123")
        await _seed_invalid_role_row(db, service, member_id="agent-bad-active")
        await _seed_invalid_role_row(db, service, member_id="agent-bad-suspended")
        # suspended 상태로 전환 (invalid-role row 라도 suspend 자체는 service-layer
        # 가 role enum 을 검증하지 않으므로 동작한다).
        await service.suspend("agent-bad-suspended", suspended_by="owner")
        # 정상 row 도 같이 둔다.
        await service.register("agent-ok", MemberType.AGENT, registered_by="owner")

        scan = await service.find_invalid_role_members()

        ids = {m.member_id for m in scan.actionable}
        assert ids == {"agent-bad-active", "agent-bad-suspended"}
        assert scan.legacy_revoked == []
        # actionable 안의 status 분포 검증 (active 1 + suspended 1).
        statuses = {m.status for m in scan.actionable}
        assert statuses == {MemberStatus.ACTIVE.value, MemberStatus.SUSPENDED.value}

    async def test_find_invalid_role_members_legacy_revoked_category(
        self, service: MemberService, db: Database
    ) -> None:
        """invalid role + ``status=revoked`` 인 row 는 ``legacy_revoked`` 로 분리."""
        await service.bootstrap_master("owner", "pass123")
        await _seed_invalid_role_row(db, service, member_id="agent-bad-revoked")
        # 정상 register 후 revoke 한 다음, role 만 invalid 로 변조하면 status=revoked
        # 이면서 role invalid 인 legacy row 가 된다. 단 revoke 후 role 변조는
        # service-layer 가 막지 않는다(DB 직접 UPDATE).
        await db.execute(
            "UPDATE members SET status = ?, revoked_at = '2026-01-01 00:00:00', "
            "token_hash = '' WHERE member_id = ?",
            (MemberStatus.REVOKED.value, "agent-bad-revoked"),
        )
        # 정상 row 1건.
        await service.register("agent-ok", MemberType.AGENT, registered_by="owner")

        scan = await service.find_invalid_role_members()

        assert scan.actionable == []
        assert len(scan.legacy_revoked) == 1
        assert scan.legacy_revoked[0].member_id == "agent-bad-revoked"
        assert scan.legacy_revoked[0].status == MemberStatus.REVOKED.value

    async def test_find_invalid_role_members_after_cli_revoke(
        self, service: MemberService, db: Database
    ) -> None:
        """actionable invalid row 를 ``revoke`` 후 같은 row 가 legacy_revoked 로 이동.

        본 테스트는 본문 task 의 핵심 invariant 를 잠근다: revoke 후
        ``actionable_count == 0`` 이고, ``legacy_revoked_count`` 는 누적된다.
        """
        await service.bootstrap_master("owner", "pass123")
        await _seed_invalid_role_row(db, service, member_id="agent-bad")

        scan_before = await service.find_invalid_role_members()
        assert [m.member_id for m in scan_before.actionable] == ["agent-bad"]
        assert scan_before.legacy_revoked == []

        # ``ante member revoke`` 와 동일 service call.
        revoked = await service.revoke("agent-bad", revoked_by="owner")
        assert revoked.status == MemberStatus.REVOKED.value
        assert revoked.token_hash == ""

        scan_after = await service.find_invalid_role_members()
        assert scan_after.actionable == []
        assert [m.member_id for m in scan_after.legacy_revoked] == ["agent-bad"]
        # revoke 가 token_hash 를 무효화했다 — has_token 비노출 회귀 보호.
        assert scan_after.legacy_revoked[0].token_hash == ""


# ── pytest -k "member_invalid_role" alias 함수 ───────────────────────
#
# 본문 verification command 의 keyword expression 은 substring 매칭 (literal
# underscore 포함) 이므로, 모듈-level 함수 이름에 ``member_invalid_role`` 토큰을
# 포함시킨다. 각 alias 는 위 ``TestFindInvalidRoleMembers`` 의 메소드를 동일
# fixture 로 호출해 동일 invariant 를 재검증한다. test count 가 늘어나지만
# 회귀 보호 측면에서는 동일 어서션이며, alias 라는 의도를 docstring 으로 명시한다.


async def test_member_invalid_role_finder_empty(service: MemberService) -> None:
    """alias of ``test_find_invalid_role_members_empty`` (-k 매칭용)."""
    await TestFindInvalidRoleMembers().test_find_invalid_role_members_empty(service)


async def test_member_invalid_role_finder_with_invalid_rows(
    service: MemberService, db: Database
) -> None:
    """alias of ``test_find_invalid_role_members_with_invalid_rows`` (-k 매칭용)."""
    await TestFindInvalidRoleMembers().test_find_invalid_role_members_with_invalid_rows(
        service, db
    )


async def test_member_invalid_role_finder_legacy_revoked_category(
    service: MemberService, db: Database
) -> None:
    """``test_find_invalid_role_members_legacy_revoked_category`` alias (-k 매칭)."""
    instance = TestFindInvalidRoleMembers()
    await instance.test_find_invalid_role_members_legacy_revoked_category(service, db)


async def test_member_invalid_role_finder_after_cli_revoke(
    service: MemberService, db: Database
) -> None:
    """alias of ``test_find_invalid_role_members_after_cli_revoke`` (-k 매칭용)."""
    await TestFindInvalidRoleMembers().test_find_invalid_role_members_after_cli_revoke(
        service, db
    )
