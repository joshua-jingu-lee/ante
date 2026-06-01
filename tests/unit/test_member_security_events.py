"""멤버 보안 이벤트 3종 발행 테스트 (#2147).

`MemberTokenRotatedEvent` / `MemberPasswordChangedEvent` /
`MemberRecoveryKeyRegeneratedEvent` dataclass 존재 + MemberService mutation
경로의 발행을 검증한다. 발행 검증은 EventBus 를 type 별로 subscribe 해 published
이벤트를 type 필터로 수집하므로 NotificationEvent 등 다른 이벤트와의 상대 순서에
의존하지 않는다(순서 비의존). 실패 경로(mutation raise)에서는 도메인 이벤트가
발행되지 않음을 lock 한다.
"""

from __future__ import annotations

import pytest

import ante.eventbus.events as events_module
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    MemberPasswordChangedEvent,
    MemberRecoveryKeyRegeneratedEvent,
    MemberTokenRotatedEvent,
    NotificationEvent,
)
from ante.member.errors import (
    MemberInvalidRecoveryCredentialError,
    PermissionDeniedError,
)
from ante.member.service import MemberService


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


# ── (a) import 가능 ─────────────────────────────────


class TestEventImport:
    """이슈 재현: 3 이벤트 dataclass 가 events 모듈에 존재해야 한다."""

    @pytest.mark.parametrize(
        "name",
        [
            "MemberTokenRotatedEvent",
            "MemberPasswordChangedEvent",
            "MemberRecoveryKeyRegeneratedEvent",
        ],
    )
    def test_event_attr_exists(self, name):
        assert hasattr(events_module, name)

    def test_event_fields(self):
        """필드명이 스펙(eventbus.md L194~196)과 일치한다."""
        rotated = MemberTokenRotatedEvent(member_id="m1", rotated_by="owner")
        assert rotated.member_id == "m1"
        assert rotated.rotated_by == "owner"

        changed = MemberPasswordChangedEvent(
            member_id="m1", changed_by="m1", reason="change"
        )
        assert changed.member_id == "m1"
        assert changed.changed_by == "m1"
        assert changed.reason == "change"

        regen = MemberRecoveryKeyRegeneratedEvent(member_id="m1", regenerated_by="m1")
        assert regen.member_id == "m1"
        assert regen.regenerated_by == "m1"

    def test_no_account_marker(self):
        """member-scoped — account marker(__post_init__ 검증) 가 없어 빈 생성 허용."""
        # marker 가 적용됐다면 account_id 미전달 시 raise 됐을 것이다.
        assert MemberTokenRotatedEvent().member_id == ""
        assert MemberPasswordChangedEvent().reason == ""
        assert MemberRecoveryKeyRegeneratedEvent().regenerated_by == ""


# ── (b) rotate_token ────────────────────────────────


class TestRotateTokenEvent:
    async def test_token_rotated_event_published(self, service, eventbus):
        """rotate_token 성공 시 MemberTokenRotatedEvent 1회 발행."""
        captured: list[MemberTokenRotatedEvent] = []
        eventbus.subscribe(MemberTokenRotatedEvent, lambda e: captured.append(e))

        await service.bootstrap_master("owner", "pass123")
        member, new_token = await service.rotate_token("owner", rotated_by="owner")

        # 반환값 보존
        assert member.member_id == "owner"
        assert isinstance(new_token, str)
        assert new_token

        assert len(captured) == 1
        evt = captured[0]
        assert evt.member_id == "owner"
        assert evt.rotated_by == "owner"

    async def test_no_event_on_non_master_rotated_by(self, service, eventbus):
        """(g) 비-master rotated_by → _assert_master raise → 미발행."""
        captured: list[MemberTokenRotatedEvent] = []
        eventbus.subscribe(MemberTokenRotatedEvent, lambda e: captured.append(e))

        await service.bootstrap_master("owner", "pass123")

        with pytest.raises(PermissionDeniedError):
            await service.rotate_token("owner", rotated_by="stranger")

        assert captured == []


# ── (c)(d) password changed/reset ───────────────────


class TestPasswordChangedEvent:
    async def test_change_password_event_reason_change(self, service, eventbus):
        """change_password 성공 시 reason='change' 인 MemberPasswordChangedEvent."""
        captured: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: captured.append(e))

        await service.bootstrap_master("owner", "pass123")
        await service.change_password("owner", "pass123", "newpass")

        assert len(captured) == 1
        evt = captured[0]
        assert evt.member_id == "owner"
        assert evt.changed_by == "owner"
        assert evt.reason == "change"

    async def test_reset_password_event_reason_reset(self, service, eventbus):
        """reset_password 성공 시 reason='reset' 인 MemberPasswordChangedEvent."""
        captured: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: captured.append(e))

        _, _token, recovery_key = await service.bootstrap_master("owner", "pass123")
        await service.reset_password("owner", recovery_key, "resetpass")

        assert len(captured) == 1
        evt = captured[0]
        assert evt.member_id == "owner"
        assert evt.changed_by == "owner"
        assert evt.reason == "reset"

    async def test_no_event_on_wrong_old_password(self, service, eventbus):
        """(g) old_password 불일치 → PermissionError raise → 미발행."""
        captured: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: captured.append(e))

        await service.bootstrap_master("owner", "pass123")

        with pytest.raises(PermissionError):
            await service.change_password("owner", "wrong", "newpass")

        assert captured == []

    async def test_no_event_on_wrong_recovery_key(self, service, eventbus):
        """(g) recovery key 불일치 → raise → MemberPasswordChangedEvent 미발행."""
        captured: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: captured.append(e))

        await service.bootstrap_master("owner", "pass123")

        with pytest.raises(MemberInvalidRecoveryCredentialError):
            await service.reset_password("owner", "wrong-key", "resetpass")

        assert captured == []


# ── (e) recovery key regenerated ────────────────────


class TestRecoveryKeyRegeneratedEvent:
    async def test_regenerate_recovery_key_event_published(self, service, eventbus):
        """regenerate_recovery_key 성공 시 이벤트 발행 + 반환값(새 key) 보존."""
        captured: list[MemberRecoveryKeyRegeneratedEvent] = []
        eventbus.subscribe(
            MemberRecoveryKeyRegeneratedEvent, lambda e: captured.append(e)
        )

        _, _token, old_key = await service.bootstrap_master("owner", "pass123")
        new_key = await service.regenerate_recovery_key("owner", "pass123")

        # 반환값 보존: 새 recovery key
        assert isinstance(new_key, str)
        assert new_key
        assert new_key != old_key

        assert len(captured) == 1
        evt = captured[0]
        assert evt.member_id == "owner"
        assert evt.regenerated_by == "owner"

    async def test_no_event_on_wrong_password(self, service, eventbus):
        """(g) password 불일치 → raise → 미발행."""
        captured: list[MemberRecoveryKeyRegeneratedEvent] = []
        eventbus.subscribe(
            MemberRecoveryKeyRegeneratedEvent, lambda e: captured.append(e)
        )

        await service.bootstrap_master("owner", "pass123")

        with pytest.raises(MemberInvalidRecoveryCredentialError):
            await service.regenerate_recovery_key("owner", "wrong")

        assert captured == []


# ── (f) 기존 동작 회귀 없음 + (h) 순서 비의존 ─────────


class TestNoRegression:
    """기존 직접 NotificationEvent / 토큰 무효화 동작이 보존된다."""

    async def test_change_password_still_notifies_and_invalidates(
        self, service, eventbus, db
    ):
        """change_password: 도메인 이벤트 추가에도 NotificationEvent/토큰 무효화 보존.

        (h) 도메인 이벤트와 NotificationEvent 를 각각 type 별로 수집해
        상대 순서에 의존하지 않고 둘 다 존재함을 단언한다.
        """
        notif: list[NotificationEvent] = []
        domain: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notif.append(e))
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: domain.append(e))

        await service.bootstrap_master("owner", "pass123")
        await service.change_password("owner", "pass123", "newpass")

        # 기존 NotificationEvent 보존 (회귀 없음)
        security = [e for e in notif if e.category == "security" and "변경" in e.title]
        assert len(security) == 1
        assert security[0].title == "패스워드 변경"

        # 신규 도메인 이벤트도 존재 (순서 무관)
        assert len(domain) == 1
        assert domain[0].reason == "change"

        # 토큰 무효화 보존
        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is None
        assert row["token_expires_at"] is None

    async def test_reset_password_still_notifies_and_invalidates(
        self, service, eventbus, db
    ):
        """reset_password: NotificationEvent/토큰 무효화 보존 + 도메인 이벤트 공존."""
        notif: list[NotificationEvent] = []
        domain: list[MemberPasswordChangedEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notif.append(e))
        eventbus.subscribe(MemberPasswordChangedEvent, lambda e: domain.append(e))

        _, _token, recovery_key = await service.bootstrap_master("owner", "pass123")
        await service.reset_password("owner", recovery_key, "resetpass")

        security = [e for e in notif if e.category == "security" and "리셋" in e.title]
        assert len(security) == 1
        assert security[0].title == "패스워드 리셋"

        assert len(domain) == 1
        assert domain[0].reason == "reset"

        row = await db.fetch_one(
            "SELECT token_hash, token_expires_at FROM members WHERE member_id = ?",
            ("owner",),
        )
        assert row["token_hash"] is None
        assert row["token_expires_at"] is None
