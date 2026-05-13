"""CLI ``ante approval audit-types`` / ``cancel-invalid`` 테스트 (#1472).

운영자가 ``ApprovalType`` SSOT 에 없는 legacy invalid approval row 를
CLI 한 줄로 식별하고 정리하는 경로를 검증한다.

검증 대상:

- ``ante approval audit-types``
  - JSON 모드: invalid row 만 출력. 정렬은 ``created_at`` 오름차순.
  - JSON 모드: invalid row 가 없으면 빈 array.
  - admin scope 가 필요 (``approval:admin``).
- ``ante approval cancel-invalid --id <id>``
  - JSON 모드: invalid pending row → success + status=cancelled.
  - invalid row 가 force_cancelled history 와 함께 cancel 종결됨을 DB 로 검증.
  - 존재하지 않는 ID → exit 1.
  - 이미 종결된 invalid row → exit 1.
  - admin scope 가 필요.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.approval.models import ApprovalStatus
from ante.cli.main import cli
from ante.core.database import Database
from ante.member.models import Member, MemberRole, MemberType

# ── 인증 stub ─────────────────────────────────────────────────────

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture()
def runner() -> CliRunner:
    """master 인증 stub 이 적용된 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


# ── DB 시드 헬퍼 ──────────────────────────────────────────────────


async def _seed_db(db_path: str) -> None:
    """ApprovalService 스키마를 초기화한다."""
    from ante.approval.service import APPROVAL_SCHEMA

    db = Database(db_path)
    await db.connect()
    await db.execute_script(APPROVAL_SCHEMA)
    await db.close()


async def _insert_invalid_row(
    db_path: str,
    *,
    approval_id: str,
    approval_type: str = "oracle_invalid_type",
    requester: str = "agent-oracle",
    status: str = ApprovalStatus.PENDING,
    created_at: str = "2026-05-10T22:08:18+00:00",
    resolved_at: str = "",
    resolved_by: str = "",
) -> None:
    db = Database(db_path)
    await db.connect()
    await db.execute(
        """INSERT INTO approvals
           (id, type, status, requester, title, body, params,
            reviews, history, reference_id, expires_at, created_at,
            resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval_id,
            approval_type,
            status,
            requester,
            f"legacy {approval_type}",
            "",
            json.dumps({}),
            json.dumps([]),
            json.dumps(
                [
                    {
                        "action": "created",
                        "actor": requester,
                        "at": created_at,
                        "detail": "",
                    }
                ]
            ),
            "",
            "",
            created_at,
            resolved_at,
            resolved_by,
        ),
    )
    await db.close()


@pytest.fixture()
def seeded_db(tmp_path: Path) -> str:
    """invalid 2건 + valid 0건이 시드된 DB 경로를 반환한다."""
    db_path = str(tmp_path / "approval.db")
    asyncio.run(_seed_db(db_path))

    async def _seed() -> None:
        await _insert_invalid_row(
            db_path,
            approval_id="legacy-A",
            approval_type="oracle_invalid_type",
            created_at="2026-05-10T22:08:18+00:00",
        )
        await _insert_invalid_row(
            db_path,
            approval_id="legacy-B",
            approval_type="bogus_type_2",
            created_at="2026-05-11T01:00:00+00:00",
        )

    asyncio.run(_seed())
    return db_path


@pytest.fixture()
def empty_db(tmp_path: Path) -> str:
    """approvals 테이블이 비어있는 DB 경로."""
    db_path = str(tmp_path / "approval-empty.db")
    asyncio.run(_seed_db(db_path))
    return db_path


# ── audit-types ───────────────────────────────────────────────────


class TestAuditTypesCommand:
    """``ante approval audit-types`` 출력 계약."""

    def test_json_mode_lists_invalid_rows_sorted(
        self, runner: CliRunner, seeded_db: str
    ) -> None:
        """JSON 모드: invalid row 만, created_at 오름차순."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "approval",
                "audit-types",
                "--db-path",
                seeded_db,
            ],
        )

        assert result.exit_code == 0, result.output
        rows = json.loads(result.stdout)
        assert isinstance(rows, list)
        assert len(rows) == 2
        # 오래된 row 가 먼저
        assert rows[0]["id"] == "legacy-A"
        assert rows[1]["id"] == "legacy-B"
        # 모든 row 의 type 이 ApprovalType 에 없는 값
        types = {r["type"] for r in rows}
        assert types == {"oracle_invalid_type", "bogus_type_2"}
        # status / requester / title 컬럼 노출
        for row in rows:
            assert "status" in row
            assert "requester" in row
            assert "title" in row
            assert "created_at" in row
            assert "resolved_at" in row

    def test_json_mode_empty_db_returns_empty_list(
        self, runner: CliRunner, empty_db: str
    ) -> None:
        """invalid row 가 없으면 빈 array 반환."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "approval",
                "audit-types",
                "--db-path",
                empty_db,
            ],
        )
        assert result.exit_code == 0, result.output
        rows = json.loads(result.stdout)
        assert rows == []

    def test_text_mode_renders_table(self, runner: CliRunner, seeded_db: str) -> None:
        """text 모드: table 형식 (헤더 + row 라인)."""
        result = runner.invoke(
            cli,
            [
                "approval",
                "audit-types",
                "--db-path",
                seeded_db,
            ],
        )
        assert result.exit_code == 0, result.output
        assert "id" in result.output
        assert "type" in result.output
        assert "legacy-A" in result.output
        assert "legacy-B" in result.output
        assert "oracle_invalid_type" in result.output


# ── cancel-invalid ────────────────────────────────────────────────


class TestCancelInvalidCommand:
    """``ante approval cancel-invalid --id <id>``."""

    def test_cancel_invalid_pending_row(
        self, runner: CliRunner, seeded_db: str
    ) -> None:
        """invalid pending row → success + status=cancelled."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "approval",
                "cancel-invalid",
                "--id",
                "legacy-A",
                "--reason",
                "test cleanup",
                "--db-path",
                seeded_db,
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        data = payload["data"]
        assert data["id"] == "legacy-A"
        assert data["type"] == "oracle_invalid_type"
        assert data["status"] == ApprovalStatus.CANCELLED

        # DB 검증: force_cancelled history 가 기록되어야 함
        async def _fetch() -> dict[str, Any]:
            db = Database(seeded_db)
            await db.connect()
            row = await db.fetch_one(
                "SELECT status, history, resolved_by FROM approvals WHERE id = ?",
                ("legacy-A",),
            )
            await db.close()
            assert row is not None
            return dict(row)

        row = asyncio.run(_fetch())
        assert row["status"] == ApprovalStatus.CANCELLED
        assert row["resolved_by"] == "test-master"
        history = json.loads(row["history"])
        actions = [e["action"] for e in history]
        assert "force_cancelled" in actions

    def test_cancel_invalid_nonexistent_id_exits_with_error(
        self, runner: CliRunner, empty_db: str
    ) -> None:
        """존재하지 않는 ID → exit 1 + APPROVAL_ERROR."""
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "approval",
                "cancel-invalid",
                "--id",
                "does-not-exist",
                "--db-path",
                empty_db,
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_ERROR"

    def test_cancel_invalid_already_resolved_row_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """이미 종결된 invalid row → exit 1 (audit trail 보존)."""
        db_path = str(tmp_path / "approval.db")
        asyncio.run(_seed_db(db_path))
        asyncio.run(
            _insert_invalid_row(
                db_path,
                approval_id="already-rejected",
                status=ApprovalStatus.REJECTED,
                resolved_at="2026-05-11T00:00:00+00:00",
                resolved_by="user-master",
            )
        )

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "approval",
                "cancel-invalid",
                "--id",
                "already-rejected",
                "--db-path",
                db_path,
            ],
        )

        assert result.exit_code == 1
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "error"
        assert payload["code"] == "APPROVAL_ERROR"
        assert "이미 종결" in payload["message"]


# ── --format / scope 등록 회귀 ─────────────────────────────────────


class TestNewCommandsRegistered:
    """audit-types / cancel-invalid 가 click 그룹에 등록되고 --format 을 가진다."""

    def test_audit_types_registered(self) -> None:
        from ante.cli.commands.approval import approval

        audit_cmd = approval.commands.get("audit-types")
        assert audit_cmd is not None
        param_names = [p.name for p in audit_cmd.params]
        assert "output_format" in param_names
        assert "db_path" in param_names

    def test_cancel_invalid_registered(self) -> None:
        from ante.cli.commands.approval import approval

        cancel_cmd = approval.commands.get("cancel-invalid")
        assert cancel_cmd is not None
        param_names = [p.name for p in cancel_cmd.params]
        assert "output_format" in param_names
        assert "approval_id" in param_names
        assert "reason" in param_names
        assert "db_path" in param_names
