"""listed_only 필터 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.instrument.service import InstrumentService
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


class TestInstrumentServiceListedOnly:
    @pytest.mark.asyncio
    async def test_search_default_returns_all(self):
        """기본 검색은 모든 종목 반환."""
        db = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(
            side_effect=[
                [],  # _warm_cache
                [
                    {
                        "symbol": "005930",
                        "exchange": "KRX",
                        "name": "삼성전자",
                        "name_en": "Samsung",
                        "instrument_type": "stock",
                        "logo_url": "",
                        "listed": 1,
                        "updated_at": "",
                    },
                    {
                        "symbol": "000000",
                        "exchange": "KRX",
                        "name": "폐지종목",
                        "name_en": "Delisted",
                        "instrument_type": "stock",
                        "logo_url": "",
                        "listed": 0,
                        "updated_at": "",
                    },
                ],
            ]
        )

        svc = InstrumentService(db)
        await svc.initialize()
        results = await svc.search("종목")

        assert len(results) == 2
        # listed_only=False이므로 listed 필터 없어야 함
        call_args = db.fetch_all.call_args_list[-1]
        assert "AND listed = 1" not in call_args[0][0]

    @pytest.mark.asyncio
    async def test_search_listed_only_filters(self):
        """listed_only=True이면 상장 종목만 검색."""
        db = AsyncMock()
        db.execute_script = AsyncMock()
        db.fetch_all = AsyncMock(
            side_effect=[
                [],  # _warm_cache
                [
                    {
                        "symbol": "005930",
                        "exchange": "KRX",
                        "name": "삼성전자",
                        "name_en": "Samsung",
                        "instrument_type": "stock",
                        "logo_url": "",
                        "listed": 1,
                        "updated_at": "",
                    },
                ],
            ]
        )

        svc = InstrumentService(db)
        await svc.initialize()
        results = await svc.search("삼성", listed_only=True)

        assert len(results) == 1
        call_args = db.fetch_all.call_args_list[-1]
        assert "AND listed = 1" in call_args[0][0]


class TestListCLIListedOnly:
    def test_list_without_listed_only(self, runner):
        """기본 list는 모든 종목 표시."""
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "name_en": "Samsung",
                    "type": "stock",
                    "listed": "Y",
                },
                {
                    "symbol": "000000",
                    "name": "폐지종목",
                    "name_en": "Delisted",
                    "type": "stock",
                    "listed": "N",
                },
            ]
            result = runner.invoke(cli, ["instrument", "list"])
            assert result.exit_code == 0
            assert "005930" in result.output
            assert "000000" in result.output

    def test_list_with_listed_only(self, runner):
        """--listed-only 시 상장 종목만 표시."""
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "symbol": "005930",
                    "name": "삼성전자",
                    "name_en": "Samsung",
                    "type": "stock",
                    "listed": "Y",
                },
            ]
            result = runner.invoke(cli, ["instrument", "list", "--listed-only"])
            assert result.exit_code == 0
            assert "005930" in result.output


class TestSearchCLIListedOnly:
    def test_search_without_listed_only(self, runner):
        """기본 search는 모든 종목 검색."""
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "symbol": "005930",
                    "exchange": "KRX",
                    "name": "삼성전자",
                    "name_en": "Samsung",
                    "type": "stock",
                },
            ]
            result = runner.invoke(cli, ["instrument", "search", "삼성"])
            assert result.exit_code == 0
            assert "005930" in result.output

    def test_search_with_listed_only(self, runner):
        """--listed-only 시 상장 종목만 검색."""
        with patch("asyncio.run") as mock_run:
            mock_run.return_value = [
                {
                    "symbol": "005930",
                    "exchange": "KRX",
                    "name": "삼성전자",
                    "name_en": "Samsung",
                    "type": "stock",
                },
            ]
            result = runner.invoke(
                cli, ["instrument", "search", "--listed-only", "삼성"]
            )
            assert result.exit_code == 0
            assert "005930" in result.output
