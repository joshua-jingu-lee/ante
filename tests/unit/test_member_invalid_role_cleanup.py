"""invalid-role member row cleanup 회귀 (#1468 — split #1417/D).

검증 대상:

- ``MemberService.audit_invalid_roles`` 는 ``MemberRole`` enum 외 ``role``
  값을 가진 row 만 반환한다 (정상 role row 영향 없음).
- ``MemberService.repair_role`` 은 master-only 이며 ``MemberRole`` enum 멤버
  로만 교정한다. ``master`` 로의 교정과 valid row 재교정을 거부한다.
- ``MemberRoleRepairedEvent`` 가 cleanup 시 발행된다 (audit/log 추적).
- ``ante member audit-roles`` CLI 는 invalid row 를 JSON / text 로 노출한다.
- ``ante member repair-role`` CLI 는 invalid → valid 로 교정한다 (master only).
- 정상 role row (master / admin / default) 는 audit / repair 영향 없음.

본 모듈은 ``test_member_auth_invalid_role.py`` 의 service-layer fixture 와
``test_cli_member_non_interactive.py`` 의 CLI runner 패턴을 재사용한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import MemberRoleRepairedEvent
from ante.member.errors import PermissionDeniedError
from ante.member.models import Member, MemberRole, MemberType
from ante.member.service import MemberService

# ── Service-layer fixtures ─────────────────────────────────────────


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


async def _seed_invalid_role_agent(
    db: Database,
    service: MemberService,
    member_id: str = "agent-bad",
    invalid_role: str = "oracle_invalid_role",
) -> str:
    """legacy invalid-role agent row 를 DB 에 심는다.

    ``register`` 가 #1465 이후 invalid role 입력을 막으므로 정상 register 후
    DB 직접 UPDATE 로 ``role`` 을 변조한다 (#1465 이전 row 재현).
    """
    await service.register(member_id, MemberType.AGENT)
    await db.execute(
        "UPDATE members SET role = ? WHERE member_id = ?",
        (invalid_role, member_id),
    )
    return member_id


# ── Service: audit_invalid_roles ───────────────────────────────────


class TestAuditInvalidRoles:
    """``MemberService.audit_invalid_roles`` 식별 정확도."""

    async def test_returns_empty_when_no_invalid_rows(
        self, service: MemberService
    ) -> None:
        """정상 role row 만 있으면 빈 list."""
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-ok", MemberType.AGENT, registered_by="owner")
        result = await service.audit_invalid_roles()
        assert result == []

    async def test_identifies_invalid_role_row(
        self, service: MemberService, db: Database
    ) -> None:
        """``MemberRole`` 외 role 값을 가진 row 를 식별한다."""
        member_id = await _seed_invalid_role_agent(db, service)
        result = await service.audit_invalid_roles()
        assert len(result) == 1
        assert result[0].member_id == member_id
        assert result[0].role == "oracle_invalid_role"

    async def test_does_not_include_valid_role_rows(
        self, service: MemberService, db: Database
    ) -> None:
        """정상 role row (master / admin / default) 는 결과에서 제외."""
        await service.bootstrap_master("owner", "pass123")
        await service.register(
            "admin-01",
            MemberType.HUMAN,
            role=MemberRole.ADMIN,
            registered_by="owner",
        )
        await service.register(
            "agent-default",
            MemberType.AGENT,
            registered_by="owner",
        )
        await _seed_invalid_role_agent(db, service, member_id="agent-leak")

        result = await service.audit_invalid_roles()
        ids = {m.member_id for m in result}
        assert ids == {"agent-leak"}

    async def test_identifies_multiple_invalid_rows(
        self, service: MemberService, db: Database
    ) -> None:
        """invalid row 가 여러 개여도 모두 반환."""
        await _seed_invalid_role_agent(db, service, member_id="agent-a")
        await _seed_invalid_role_agent(
            db, service, member_id="agent-b", invalid_role="another_invalid"
        )
        result = await service.audit_invalid_roles()
        assert {m.member_id for m in result} == {"agent-a", "agent-b"}

    async def test_audit_is_read_only(
        self, service: MemberService, db: Database
    ) -> None:
        """audit 호출 자체는 DB 를 변경하지 않는다."""
        member_id = await _seed_invalid_role_agent(db, service)
        await service.audit_invalid_roles()
        # role 값이 그대로 invalid 상태로 남아 있어야 한다.
        row = await db.fetch_one(
            "SELECT role FROM members WHERE member_id = ?", (member_id,)
        )
        assert row["role"] == "oracle_invalid_role"


# ── Service: repair_role ───────────────────────────────────────────


class TestRepairRoleService:
    """``MemberService.repair_role`` invariants."""

    async def test_repair_invalid_to_default_succeeds(
        self, service: MemberService, db: Database
    ) -> None:
        """master 가 invalid → default 로 교정."""
        await service.bootstrap_master("owner", "pass123")
        member_id = await _seed_invalid_role_agent(db, service)

        m = await service.repair_role(
            member_id, MemberRole.DEFAULT, repaired_by="owner"
        )
        assert m.role == "default"

        row = await db.fetch_one(
            "SELECT role FROM members WHERE member_id = ?", (member_id,)
        )
        assert row["role"] == "default"

    async def test_repair_invalid_to_admin_succeeds_for_human(
        self, service: MemberService, db: Database
    ) -> None:
        """human row 는 admin 으로 교정 가능."""
        await service.bootstrap_master("owner", "pass123")
        # human + invalid role row 시드
        await service.register("human-bad", MemberType.HUMAN, registered_by="owner")
        await db.execute(
            "UPDATE members SET role = ? WHERE member_id = ?",
            ("oracle_invalid_role", "human-bad"),
        )

        m = await service.repair_role(
            "human-bad", MemberRole.ADMIN, repaired_by="owner"
        )
        assert m.role == "admin"

    async def test_repair_rejects_non_master_caller(
        self, service: MemberService, db: Database
    ) -> None:
        """비-master caller 는 ``PermissionDeniedError``."""
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-actor", MemberType.AGENT, registered_by="owner")
        member_id = await _seed_invalid_role_agent(db, service, member_id="agent-leak")

        with pytest.raises(PermissionDeniedError):
            await service.repair_role(
                member_id, MemberRole.DEFAULT, repaired_by="agent-actor"
            )

    async def test_repair_rejects_empty_caller(
        self, service: MemberService, db: Database
    ) -> None:
        """빈 caller 도 거부 (``_assert_master`` 정책)."""
        member_id = await _seed_invalid_role_agent(db, service)
        with pytest.raises(PermissionDeniedError):
            await service.repair_role(member_id, MemberRole.DEFAULT, repaired_by="")

    async def test_repair_to_master_role_is_rejected(
        self, service: MemberService, db: Database
    ) -> None:
        """``MemberRole.MASTER`` 로의 교정은 거부 — 권한 상승 방지."""
        await service.bootstrap_master("owner", "pass123")
        member_id = await _seed_invalid_role_agent(db, service)

        with pytest.raises(ValueError, match="master"):
            await service.repair_role(member_id, MemberRole.MASTER, repaired_by="owner")

    async def test_repair_to_invalid_role_is_rejected(
        self, service: MemberService, db: Database
    ) -> None:
        """``MemberRole`` enum 외 ``new_role`` 은 ``ValueError``."""
        await service.bootstrap_master("owner", "pass123")
        member_id = await _seed_invalid_role_agent(db, service)

        with pytest.raises(ValueError, match="invalid role"):
            await service.repair_role(member_id, "still_bogus", repaired_by="owner")

    async def test_repair_does_not_touch_valid_row(
        self, service: MemberService, db: Database
    ) -> None:
        """이미 valid 한 row 를 본 메서드로 재교정하는 호출은 거부."""
        await service.bootstrap_master("owner", "pass123")
        await service.register("agent-ok", MemberType.AGENT, registered_by="owner")

        with pytest.raises(ValueError, match="valid role"):
            await service.repair_role(
                "agent-ok", MemberRole.DEFAULT, repaired_by="owner"
            )

        # role 값은 변경되지 않아야 한다.
        row = await db.fetch_one(
            "SELECT role FROM members WHERE member_id = ?", ("agent-ok",)
        )
        assert row["role"] == "default"

    async def test_repair_respects_type_role_invariant(
        self, service: MemberService, db: Database
    ) -> None:
        """agent → admin 교정은 ``_assert_type_role`` 로 거부."""
        await service.bootstrap_master("owner", "pass123")
        member_id = await _seed_invalid_role_agent(db, service)

        with pytest.raises(PermissionError, match="agent"):
            await service.repair_role(member_id, MemberRole.ADMIN, repaired_by="owner")

    async def test_repair_publishes_event(
        self,
        service: MemberService,
        db: Database,
        eventbus: EventBus,
    ) -> None:
        """성공 시 ``MemberRoleRepairedEvent`` 발행 — audit/log 추적."""
        await service.bootstrap_master("owner", "pass123")
        member_id = await _seed_invalid_role_agent(db, service)

        events: list[MemberRoleRepairedEvent] = []
        eventbus.subscribe(MemberRoleRepairedEvent, lambda e: events.append(e))

        await service.repair_role(member_id, MemberRole.DEFAULT, repaired_by="owner")

        assert len(events) == 1
        e = events[0]
        assert e.member_id == member_id
        assert e.old_role == "oracle_invalid_role"
        assert e.new_role == "default"
        assert e.repaired_by == "owner"


# ── CLI: audit-roles / repair-role ─────────────────────────────────


def _make_master() -> Member:
    """테스트용 master Member."""
    return Member(
        member_id="master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Master",
        status="active",
        scopes=[],
    )


def _mock_authenticate(ctx) -> None:  # noqa: ANN001
    """test runner 인증 우회."""
    ctx.obj["member"] = _make_master()


def _invoke_cli(args: list[str]):  # noqa: ANN202
    """CLI 를 실행하고 결과를 반환한다 (인증 우회)."""
    runner = CliRunner()
    with patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate):
        return runner.invoke(
            cli,
            args,
            obj={"member": _make_master()},
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )


def _patch_audit_repair_service(
    *,
    invalid_members: list[Member] | None = None,
    repair_return: Member | None = None,
    repair_side_effect: object | None = None,
):
    """``audit_invalid_roles`` / ``repair_role`` mock contextmanager."""
    service = MagicMock()
    service.audit_invalid_roles = AsyncMock(return_value=invalid_members or [])
    if repair_side_effect is not None:
        service.repair_role = AsyncMock(side_effect=repair_side_effect)
    else:
        service.repair_role = AsyncMock(
            return_value=repair_return
            if repair_return is not None
            else Member(
                member_id="agent-leak",
                type=MemberType.AGENT,
                role=MemberRole.DEFAULT,
                org="default",
                name="agent-leak",
                status="active",
                scopes=[],
            )
        )
    db = MagicMock()
    db.close = AsyncMock(return_value=None)
    return (
        patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(service, db),
        ),
        service,
    )


class TestAuditRolesCli:
    """``ante member audit-roles`` 출력."""

    def test_audit_roles_json_lists_invalid_members(self) -> None:
        invalid = Member(
            member_id="agent-leak",
            type=MemberType.AGENT,
            role="oracle_invalid_role",
            org="default",
            name="agent-leak",
            status="active",
            scopes=[],
            created_at="2026-05-09 10:01:23",
            created_by="oracle",
        )
        ctx, service = _patch_audit_repair_service(invalid_members=[invalid])
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "audit-roles"],
            )

        assert result.exit_code == 0, result.output
        service.audit_invalid_roles.assert_awaited_once()
        data = json.loads(result.output)
        assert "invalid_members" in data
        assert len(data["invalid_members"]) == 1
        row = data["invalid_members"][0]
        assert row["member_id"] == "agent-leak"
        assert row["role"] == "oracle_invalid_role"

    def test_audit_roles_json_empty_when_no_invalid(self) -> None:
        ctx, service = _patch_audit_repair_service(invalid_members=[])
        with ctx:
            result = _invoke_cli(
                ["--format", "json", "member", "audit-roles"],
            )

        assert result.exit_code == 0, result.output
        service.audit_invalid_roles.assert_awaited_once()
        data = json.loads(result.output)
        assert data == {"invalid_members": []}

    def test_audit_roles_text_outputs_count(self) -> None:
        invalid = Member(
            member_id="agent-leak",
            type=MemberType.AGENT,
            role="oracle_invalid_role",
            org="default",
            name="agent-leak",
            status="active",
            scopes=[],
        )
        ctx, _service = _patch_audit_repair_service(invalid_members=[invalid])
        with ctx:
            result = _invoke_cli(["member", "audit-roles"])

        assert result.exit_code == 0, result.output
        assert "1건" in result.output
        assert "agent-leak" in result.output
        assert "oracle_invalid_role" in result.output


class TestRepairRoleCli:
    """``ante member repair-role`` CLI."""

    def test_repair_role_succeeds(self) -> None:
        repaired = Member(
            member_id="agent-leak",
            type=MemberType.AGENT,
            role=MemberRole.DEFAULT,
            org="default",
            name="agent-leak",
            status="active",
            scopes=[],
        )
        ctx, service = _patch_audit_repair_service(repair_return=repaired)
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "repair-role",
                    "--member-id",
                    "agent-leak",
                    "--role",
                    "default",
                ],
            )

        assert result.exit_code == 0, result.output
        service.repair_role.assert_awaited_once()
        call = service.repair_role.await_args
        assert call.args[0] == "agent-leak"
        assert call.args[1] == "default"
        assert call.kwargs.get("repaired_by") == "master"
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["role"] == "default"

    def test_repair_role_master_choice_rejected_by_click(self) -> None:
        """CLI 옵션 단에서 ``master`` 는 ``click.Choice`` 로 거부."""
        ctx, service = _patch_audit_repair_service()
        with ctx:
            runner = CliRunner()
            with patch(
                "ante.cli.main.authenticate_member",
                side_effect=_mock_authenticate,
            ):
                result = runner.invoke(
                    cli,
                    [
                        "member",
                        "repair-role",
                        "--member-id",
                        "agent-leak",
                        "--role",
                        "master",
                    ],
                    obj={"member": _make_master()},
                    env={"ANTE_MEMBER_TOKEN": ""},
                )

        assert result.exit_code != 0
        service.repair_role.assert_not_awaited()

    def test_repair_role_non_master_exits_without_traceback(self) -> None:
        ctx, service = _patch_audit_repair_service(
            repair_side_effect=PermissionDeniedError(
                "'repair_role'은(는) master만 수행할 수 있습니다."
            )
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "repair-role",
                    "--member-id",
                    "agent-leak",
                    "--role",
                    "default",
                ],
            )

        assert result.exit_code == 1, result.output
        service.repair_role.assert_awaited_once()
        data = json.loads(result.output)
        assert "master" in data["message"]
        assert "Traceback" not in result.output

    def test_repair_role_value_error_exits_one(self) -> None:
        """이미 valid 한 row 재교정 시도 → ``ValueError`` → exit 1."""
        ctx, service = _patch_audit_repair_service(
            repair_side_effect=ValueError(
                "이미 valid role 입니다: 'default'."
                " repair_role 은 invalid-role row 만 교정합니다."
            )
        )
        with ctx:
            result = _invoke_cli(
                [
                    "--format",
                    "json",
                    "member",
                    "repair-role",
                    "--member-id",
                    "agent-ok",
                    "--role",
                    "default",
                ],
            )

        assert result.exit_code == 1, result.output
        service.repair_role.assert_awaited_once()
        data = json.loads(result.output)
        assert "valid role" in data["message"]
        assert "Traceback" not in result.output
