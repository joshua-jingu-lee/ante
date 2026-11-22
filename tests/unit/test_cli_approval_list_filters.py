"""CLI ``approval list`` invalid `--status`/`--type` preflight 회귀 테스트 (#1462).

`ante --format json approval list --status <invalid>` /
`ante --format json approval list --type <invalid>`가 Python traceback 없이
flat JSON error (`APPROVAL_INVALID_STATUS` / `APPROVAL_INVALID_TYPE`)로 종료하고,
DB 접속(`ante.core.database.Database`)이 일어나기 전에 차단되는지 검증한다.

SSOT:
- enum: ``src/ante/approval/models.py::ApprovalStatus``,
  ``src/ante/approval/models.py::ApprovalType``
- 패턴: ``src/ante/cli/commands/strategy.py:204-210``
- 계약: ``docs/specs/cli/02-design-decisions.md`` (structured error)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """auth bypass가 적용된 CliRunner.

    `ante.cli.main.authenticate_member`를 patch하여 root group의 인증 검사를
    우회한다 (CLI 테스트 표준 패턴).
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_service_layer(requests=None):
    """`Database` + `ApprovalService` 생성자 patch 헬퍼.

    valid 입력 케이스에서 list_approvals이 결과를 반환할 수 있도록
    Database / ApprovalService 가 모두 호출 가능하게 mock한다.
    """
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db_cls = MagicMock(return_value=db)

    service = MagicMock()
    service.initialize = AsyncMock()
    service.list_approvals = AsyncMock(return_value=requests or [])
    service_cls = MagicMock(return_value=service)

    return db_cls, service_cls, service


class TestApprovalListInvalidPreflight:
    """`approval list` invalid status/type → DB 접속 전 차단 (#1462)."""

    def test_approval_list_invalid_status_rejected_before_db(self, runner) -> None:
        """invalid `--status`는 `Database` 생성 전 차단된다.

        ApprovalStatus enum (SSOT)에 없는 값이 들어오면 preflight가
        `APPROVAL_INVALID_STATUS` 구조화 에러로 종료시키며, DB 생성자는
        호출되지 않아야 한다.
        """
        db_cls = MagicMock()
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.cli.main.get_db_path", return_value="/tmp/unused-approval.db"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--status",
                    "sample_invalid_status",
                ],
            )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "APPROVAL_INVALID_STATUS"
        assert "sample_invalid_status" in data["message"]
        assert "Traceback" not in result.output
        db_cls.assert_not_called()

    def test_approval_list_invalid_type_rejected_before_db(self, runner) -> None:
        """invalid `--type`는 `Database` 생성 전 차단된다.

        ApprovalType enum (SSOT)에 없는 값이 들어오면 preflight가
        `APPROVAL_INVALID_TYPE` 구조화 에러로 종료시키며, DB 생성자는
        호출되지 않아야 한다.
        """
        db_cls = MagicMock()
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.cli.main.get_db_path", return_value="/tmp/unused-approval.db"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--type",
                    "sample_invalid_type",
                ],
            )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "APPROVAL_INVALID_TYPE"
        assert "sample_invalid_type" in data["message"]
        assert "Traceback" not in result.output
        db_cls.assert_not_called()

    def test_approval_list_invalid_status_takes_priority_over_invalid_type(
        self, runner
    ) -> None:
        """status invalid가 type invalid보다 먼저 평가된다.

        구현 순서를 회귀 보호 (status check 먼저 → type check 다음).
        """
        db_cls = MagicMock()
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.cli.main.get_db_path", return_value="/tmp/unused-approval.db"),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--status",
                    "bogus_status",
                    "--type",
                    "bogus_type",
                ],
            )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output.strip())
        assert data["code"] == "APPROVAL_INVALID_STATUS"
        db_cls.assert_not_called()


class TestApprovalListValidFilters:
    """`approval list` valid status/type은 회귀 없이 정상 동작 (#1462)."""

    def test_approval_list_valid_status_still_works(self, runner, tmp_path) -> None:
        """valid `--status`는 preflight 통과 후 ApprovalService.list_approvals 호출.

        #1856: ``approval list`` 가 ``open_cli_db`` factory 경로로 전환된 후,
        ``Database`` 생성은 ``ante.cli.db_context`` 모듈의 binding 을 통해
        일어난다. 따라서 patch 도 ``ante.cli.db_context.Database`` 로 정렬한다.
        """
        db_cls, service_cls, service = _mock_service_layer([])
        db_path = str(tmp_path / "approval.db")
        with (
            patch("ante.cli.db_context.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch("ante.cli.main.get_db_path", return_value=db_path),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--status",
                    "pending",
                ],
            )
        assert result.exit_code == 0, result.output
        db_cls.assert_called_once_with(db_path)
        service.list_approvals.assert_awaited_once_with(status="pending", type=None)

    def test_approval_list_valid_type_still_works(self, runner, tmp_path) -> None:
        """valid `--type`은 preflight 통과 후 ApprovalService.list_approvals 호출."""
        db_cls, service_cls, service = _mock_service_layer([])
        db_path = str(tmp_path / "approval.db")
        with (
            patch("ante.cli.db_context.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch("ante.cli.main.get_db_path", return_value=db_path),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--type",
                    "strategy_adopt",
                ],
            )
        assert result.exit_code == 0, result.output
        service.list_approvals.assert_awaited_once_with(
            status=None, type="strategy_adopt"
        )

    def test_approval_list_no_filter_still_works(self, runner, tmp_path) -> None:
        """필터 미지정 시 status=None, type=None으로 호출."""
        db_cls, service_cls, service = _mock_service_layer([])
        db_path = str(tmp_path / "approval.db")
        with (
            patch("ante.cli.db_context.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
            patch("ante.cli.main.get_db_path", return_value=db_path),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "approval", "list"],
            )
        assert result.exit_code == 0, result.output
        service.list_approvals.assert_awaited_once_with(status=None, type=None)


@pytest.fixture
def split_runner() -> CliRunner:
    """stderr 를 stdout 에 섞지 않는 인증 우회 CliRunner."""
    r = CliRunner(mix_stderr=False)
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


class _ListQueryError(Exception):
    """테스트 전용: 조회 단계의 임의 실패."""


class TestApprovalListClosesDatabase:
    """``approval list`` 는 정상·예외 경로 모두에서 연 ``Database`` 를 닫는다."""

    @pytest.mark.parametrize("fails", [False, True], ids=["normal", "query-raises"])
    def test_database_closed(self, split_runner, tmp_path, fails: bool) -> None:
        db_cls, service_cls, service = _mock_service_layer([])
        if fails:
            service.list_approvals = AsyncMock(side_effect=_ListQueryError("boom"))
        with (
            patch("ante.core.database.Database", db_cls),
            patch("ante.approval.ApprovalService", service_cls),
        ):
            result = split_runner.invoke(
                cli,
                [
                    "--config-dir",
                    str(tmp_path),
                    "--format",
                    "json",
                    "approval",
                    "list",
                    "--db-path",
                    str(tmp_path / "approval.db"),
                ],
            )
        service.list_approvals.assert_awaited_once()
        db_cls.return_value.connect.assert_awaited_once()
        assert db_cls.return_value.close.await_count == 1, result.output


class TestApprovalListRealDatabase:
    """실제 DB 파일로 `--db-path` 전달과 스키마 초기화를 확인한다."""

    @staticmethod
    async def _seed(db_path: str, title: str) -> None:
        from ante.approval import ApprovalService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus

        db = Database(db_path)
        await db.connect()
        try:
            service = ApprovalService(db=db, eventbus=EventBus())
            await service.initialize()
            await service.create(
                type="strategy_retire", requester="agent-x", title=title
            )
        finally:
            await db.close()

    @staticmethod
    def _tables(db_path: str) -> set[str]:
        import sqlite3

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows}

    def test_db_path_option_overrides_config_dir_db(
        self, split_runner, tmp_path
    ) -> None:
        """`--db-path`로 준 파일의 결재가 보이고 config_dir 의 DB는 쓰지 않는다."""
        import asyncio

        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        asyncio.run(self._seed(str(config_dir / "db" / "ante.db"), "config-dir-row"))
        override = tmp_path / "override.db"
        asyncio.run(self._seed(str(override), "override-row"))

        result = split_runner.invoke(
            cli,
            [
                "--config-dir",
                str(config_dir),
                "--format",
                "json",
                "approval",
                "list",
                "--db-path",
                str(override),
            ],
        )
        rows = json.loads(result.stdout)["data"]["approvals"]
        assert [r["title"] for r in rows] == ["override-row"]

    def test_list_initializes_schema_on_fresh_db(self, split_runner, tmp_path) -> None:
        """테이블이 없는 새 DB에서도 list 는 스키마를 만들고 빈 목록으로 끝난다."""
        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        fresh = tmp_path / "fresh.db"

        result = split_runner.invoke(
            cli,
            [
                "--config-dir",
                str(config_dir),
                "--format",
                "json",
                "approval",
                "list",
                "--db-path",
                str(fresh),
            ],
        )
        assert "approvals" in self._tables(str(fresh)), result.output
