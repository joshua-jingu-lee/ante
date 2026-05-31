"""``ante backtest history`` offline read-only 회귀 테스트 (#1974).

``backtest history`` 는 offline read 명령이므로 read-only DB 에서 schema DDL
(``BacktestRunStore.initialize()`` → ``CREATE TABLE backtest_runs``) 을 발화하면
안 된다 (offline-factory.md §2 옵션 B, §4.4 ``BacktestRunStore`` initialize skip
가능 후보). 핵심 회귀 락:

1. 기존 (스키마 없는) DB 에서 ``backtest_runs`` 테이블이 없어도 빈 이력으로
   정규화 (``"no such table"`` → ``[]``), 종료코드 0.
2. 명령 실행 후에도 ``backtest_runs`` 테이블이 **생성되지 않음** — read-only
   DDL 부작용 부재 (이게 #1974 의 핵심 수정이다).
3. JSON envelope shape 가 기존 빈 이력 응답 (``{"message": ..., "runs": []}``)
   과 동일.

CliRunner / auth 셋업은 ``tests/unit/test_cli_backtest_report.py`` 의
``require_auth`` 우회 fixture 를 미러한다.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core.database import Database
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
def runner():
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


def _make_empty_db(path: str) -> None:
    """``backtest_runs`` 테이블이 없는 기존 DB 파일을 사전 생성한다.

    파일이 존재하지 않으면 ``open_cli_db`` → ``Database.connect()`` 가 파일을
    새로 생성해 read-only 시나리오가 깨진다. 따라서 ``Database`` 를
    connect→close 만 수행해 빈 DB 파일 (스키마 없음) 을 미리 만든다.
    """

    async def _create() -> None:
        db = Database(path)
        await db.connect()
        await db.close()

    asyncio.run(_create())


def _backtest_runs_table_exists(path: str) -> bool:
    """``backtest_runs`` 테이블의 존재 여부를 sqlite3 로 직접 확인한다."""
    conn = sqlite3.connect(path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'backtest_runs'"
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


class TestBacktestHistoryReadOnly:
    def test_history_empty_does_not_create_backtest_runs_table(
        self, runner, tmp_path
    ) -> None:
        """read-only DB 에서 빈 이력 반환 + ``backtest_runs`` DDL 부작용 부재.

        - 종료코드 0 + 빈 이력 success envelope.
        - 실행 후 ``backtest_runs`` 테이블이 생성되지 않음 (핵심 회귀 락).
        - JSON envelope shape 가 기존 빈 이력 응답과 동일.
        """
        db_file = tmp_path / "ante.db"
        _make_empty_db(str(db_file))

        # 사전 조건: 스키마 없는 빈 DB (backtest_runs 테이블 부재).
        assert not _backtest_runs_table_exists(str(db_file))

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "history",
                "momentum",
                "--db-path",
                str(db_file),
            ],
        )

        # (a) 종료코드 0 + 빈 이력 success envelope.
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["runs"] == []
        # (c) JSON envelope shape 가 기존 빈 이력 응답과 동일
        #     (backtest.py history empty 분기: {"message": ..., "runs": []}).
        assert "이력이 없습니다" in data["message"]

        # (b) 핵심 회귀 락: 실행 후에도 backtest_runs 테이블이 생성되지 않음
        #     (read-only DDL 부작용 부재).
        assert not _backtest_runs_table_exists(str(db_file))
