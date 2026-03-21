"""ante treasury snapshot CLI 커맨드 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.treasury import treasury
from ante.cli.formatter import OutputFormatter


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth():
    """인증 미들웨어를 우회하는 픽스처."""
    with (
        patch("ante.cli.middleware.authenticate_member"),
        patch("ante.cli.middleware._run_authenticate"),
    ):
        yield


SAMPLE_SNAPSHOT = {
    "account_id": "domestic",
    "snapshot_date": "2026-03-21",
    "total_asset": 12_650_000.0,
    "ante_eval_amount": 2_650_000.0,
    "ante_purchase_amount": 2_500_000.0,
    "unallocated": 10_000_000.0,
    "account_balance": 10_000_000.0,
    "total_allocated": 2_500_000.0,
    "bot_count": 3,
    "daily_pnl": 150_000.0,
    "daily_return": 1.23,
    "net_trade_amount": 0.0,
    "unrealized_pnl": 150_000.0,
    "created_at": "2026-03-21T23:59:00+00:00",
}

SAMPLE_SNAPSHOT_2 = {
    **SAMPLE_SNAPSHOT,
    "snapshot_date": "2026-03-20",
    "total_asset": 12_500_000.0,
    "daily_pnl": -50_000.0,
    "daily_return": -0.40,
    "unrealized_pnl": 0.0,
}


def _make_mock_treasury(get_daily_return=None, get_range_return=None):
    """_create_treasury를 모킹하는 컨텍스트 매니저를 반환."""
    mock_treasury = AsyncMock()
    mock_treasury.get_daily_snapshot = AsyncMock(return_value=get_daily_return)
    mock_treasury.get_snapshots = AsyncMock(return_value=get_range_return or [])

    mock_db = AsyncMock()
    mock_db.close = AsyncMock()

    async def _fake_create(account_id=None):
        return mock_treasury, mock_db

    return patch(
        "ante.cli.commands.treasury._create_treasury",
        side_effect=_fake_create,
    ), mock_treasury


def _invoke(runner, args, mock_auth):
    """인증을 우회하면서 CLI를 실행하는 헬퍼."""
    from ante.member.models import Member, MemberType

    mock_member = Member(
        member_id="test-user",
        name="테스트",
        type=MemberType.HUMAN,
        role="master",
    )
    return runner.invoke(
        treasury,
        args,
        obj={
            "format": "text",
            "formatter": OutputFormatter("text"),
            "member": mock_member,
        },
        catch_exceptions=False,
    )


class TestSnapshotDefault:
    """인자 없이 호출 시 오늘 날짜 스냅샷 조회."""

    def test_default_today(self, runner, mock_auth):
        ctx_patch, mock_t = _make_mock_treasury(get_daily_return=SAMPLE_SNAPSHOT)
        with ctx_patch:
            result = _invoke(runner, ["snapshot"], mock_auth)

        assert result.exit_code == 0
        assert "일별 자산 스냅샷" in result.output
        assert "12,650,000" in result.output
        assert "2,650,000" in result.output
        mock_t.get_daily_snapshot.assert_awaited_once()

    def test_default_no_data(self, runner, mock_auth):
        ctx_patch, _ = _make_mock_treasury(get_daily_return=None)
        with ctx_patch:
            result = _invoke(runner, ["snapshot"], mock_auth)

        assert result.exit_code == 0
        assert "스냅샷이 없습니다" in result.output


class TestSnapshotDate:
    """--date 옵션으로 특정 날짜 조회."""

    def test_specific_date(self, runner, mock_auth):
        ctx_patch, mock_t = _make_mock_treasury(get_daily_return=SAMPLE_SNAPSHOT)
        with ctx_patch:
            result = _invoke(runner, ["snapshot", "--date", "2026-03-21"], mock_auth)

        assert result.exit_code == 0
        assert "2026-03-21" in result.output
        mock_t.get_daily_snapshot.assert_awaited_once_with("2026-03-21")

    def test_specific_date_not_found(self, runner, mock_auth):
        ctx_patch, _ = _make_mock_treasury(get_daily_return=None)
        with ctx_patch:
            result = _invoke(runner, ["snapshot", "--date", "2026-01-01"], mock_auth)

        assert result.exit_code == 0
        assert "2026-01-01" in result.output
        assert "스냅샷이 없습니다" in result.output


class TestSnapshotRange:
    """--from/--to 옵션으로 기간 조회."""

    def test_range_query(self, runner, mock_auth):
        snapshots = [SAMPLE_SNAPSHOT_2, SAMPLE_SNAPSHOT]
        ctx_patch, mock_t = _make_mock_treasury(get_range_return=snapshots)
        with ctx_patch:
            result = _invoke(
                runner,
                ["snapshot", "--from", "2026-03-20", "--to", "2026-03-21"],
                mock_auth,
            )

        assert result.exit_code == 0
        assert "2026-03-20" in result.output
        assert "2026-03-21" in result.output
        mock_t.get_snapshots.assert_awaited_once_with("2026-03-20", "2026-03-21")

    def test_from_only(self, runner, mock_auth):
        """--from만 지정하면 오늘까지 조회."""
        ctx_patch, mock_t = _make_mock_treasury(get_range_return=[SAMPLE_SNAPSHOT])
        with ctx_patch:
            result = _invoke(runner, ["snapshot", "--from", "2026-03-20"], mock_auth)

        assert result.exit_code == 0
        # get_snapshots가 호출되었는지 확인
        mock_t.get_snapshots.assert_awaited_once()
        call_args = mock_t.get_snapshots.call_args[0]
        assert call_args[0] == "2026-03-20"

    def test_empty_range(self, runner, mock_auth):
        ctx_patch, _ = _make_mock_treasury(get_range_return=[])
        with ctx_patch:
            result = _invoke(
                runner,
                ["snapshot", "--from", "2026-01-01", "--to", "2026-01-02"],
                mock_auth,
            )

        assert result.exit_code == 0
        assert "스냅샷 없음" in result.output


class TestSnapshotJson:
    """--format json 출력."""

    def test_json_single(self, runner, mock_auth):
        import json

        from ante.member.models import Member, MemberType

        mock_member = Member(
            member_id="test-user",
            name="테스트",
            type=MemberType.HUMAN,
            role="master",
        )
        ctx_patch, _ = _make_mock_treasury(get_daily_return=SAMPLE_SNAPSHOT)
        with ctx_patch:
            result = runner.invoke(
                treasury,
                ["snapshot", "--date", "2026-03-21", "--format", "json"],
                obj={
                    "format": "json",
                    "formatter": OutputFormatter("json"),
                    "member": mock_member,
                },
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_asset"] == 12_650_000.0
        assert data["snapshot_date"] == "2026-03-21"

    def test_json_range(self, runner, mock_auth):
        import json

        from ante.member.models import Member, MemberType

        mock_member = Member(
            member_id="test-user",
            name="테스트",
            type=MemberType.HUMAN,
            role="master",
        )
        snapshots = [SAMPLE_SNAPSHOT_2, SAMPLE_SNAPSHOT]
        ctx_patch, _ = _make_mock_treasury(get_range_return=snapshots)
        with ctx_patch:
            result = runner.invoke(
                treasury,
                [
                    "snapshot",
                    "--from",
                    "2026-03-20",
                    "--to",
                    "2026-03-21",
                    "--format",
                    "json",
                ],
                obj={
                    "format": "json",
                    "formatter": OutputFormatter("json"),
                    "member": mock_member,
                },
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 2


class TestSnapshotValidation:
    """옵션 조합 검증."""

    def test_date_and_from_conflict(self, runner, mock_auth):
        """--date와 --from을 동시에 사용하면 에러."""
        ctx_patch, _ = _make_mock_treasury()
        with ctx_patch:
            result = _invoke(
                runner,
                ["snapshot", "--date", "2026-03-21", "--from", "2026-03-20"],
                mock_auth,
            )

        assert result.exit_code == 0
        assert "동시에 사용할 수 없습니다" in result.output


class TestSnapshotAccount:
    """--account 필터링."""

    def test_account_filter(self, runner, mock_auth):
        ctx_patch, mock_t = _make_mock_treasury(get_daily_return=SAMPLE_SNAPSHOT)
        with ctx_patch as p:
            result = _invoke(
                runner,
                ["snapshot", "--account", "domestic", "--date", "2026-03-21"],
                mock_auth,
            )

        assert result.exit_code == 0
        # _create_treasury가 account_id="domestic"으로 호출되었는지 확인
        p.assert_called_with("domestic")
