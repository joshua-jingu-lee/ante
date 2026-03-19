"""Parquet 파일 무결성 검증 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.data.store import ParquetStore
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


@pytest.fixture
def tmp_store(tmp_path):
    """임시 디렉토리 기반 ParquetStore."""
    return ParquetStore(base_path=tmp_path)


def _create_valid_parquet(path: Path) -> None:
    """유효한 Parquet 파일 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame({"timestamp": ["2026-01-01"], "close": [100.0]})
    df.write_parquet(str(path))


def _create_corrupted_parquet(path: Path) -> None:
    """손상된 Parquet 파일 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"NOT_A_PARQUET_FILE")


class TestParquetValidate:
    @pytest.mark.asyncio
    async def test_validate_all_valid(self, tmp_store, tmp_path):
        _create_valid_parquet(tmp_path / "ohlcv" / "1d" / "005930" / "2026-01.parquet")
        _create_valid_parquet(tmp_path / "ohlcv" / "1d" / "005930" / "2026-02.parquet")

        result = tmp_store.validate("005930", "1d")

        assert result["total"] == 2
        assert result["valid"] == 2
        assert result["corrupted"] == 0
        assert result["corrupted_files"] == []

    @pytest.mark.asyncio
    async def test_validate_corrupted_file(self, tmp_store, tmp_path):
        _create_valid_parquet(tmp_path / "ohlcv" / "1d" / "005930" / "2026-01.parquet")
        _create_corrupted_parquet(
            tmp_path / "ohlcv" / "1d" / "005930" / "2026-02.parquet"
        )

        result = tmp_store.validate("005930", "1d")

        assert result["total"] == 2
        assert result["valid"] == 1
        assert result["corrupted"] == 1
        assert len(result["corrupted_files"]) == 1

    @pytest.mark.asyncio
    async def test_validate_fix_moves_corrupted(self, tmp_store, tmp_path):
        corrupted_path = tmp_path / "ohlcv" / "1d" / "005930" / "2026-02.parquet"
        _create_corrupted_parquet(corrupted_path)

        result = tmp_store.validate("005930", "1d", fix=True)

        assert result["corrupted"] == 1
        assert not corrupted_path.exists()
        assert corrupted_path.with_suffix(".corrupted").exists()

    @pytest.mark.asyncio
    async def test_validate_no_data(self, tmp_store):
        result = tmp_store.validate("NONE", "1d")

        assert result["total"] == 0
        assert result["valid"] == 0
        assert result["corrupted"] == 0

    @pytest.mark.asyncio
    async def test_validate_empty_directory(self, tmp_store, tmp_path):
        (tmp_path / "ohlcv" / "1d" / "005930").mkdir(parents=True)

        result = tmp_store.validate("005930", "1d")

        assert result["total"] == 0


class TestValidateCLI:
    def test_validate_specific_symbol(self, runner):
        with patch("ante.data.store.ParquetStore.validate") as mock_validate:
            mock_validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 3,
                "valid": 3,
                "corrupted": 0,
                "corrupted_files": [],
            }
            result = runner.invoke(cli, ["data", "validate", "--symbol", "005930"])
            assert result.exit_code == 0
            assert "정상 3개" in result.output

    def test_validate_with_corrupted(self, runner):
        with patch("ante.data.store.ParquetStore.validate") as mock_validate:
            mock_validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 3,
                "valid": 2,
                "corrupted": 1,
                "corrupted_files": ["/data/ohlcv/1d/005930/2026-01.parquet"],
            }
            result = runner.invoke(cli, ["data", "validate", "--symbol", "005930"])
            assert result.exit_code == 0
            assert "손상 1개" in result.output

    def test_validate_json_output(self, runner):
        with patch("ante.data.store.ParquetStore.validate") as mock_validate:
            mock_validate.return_value = {
                "symbol": "005930",
                "timeframe": "1d",
                "total": 2,
                "valid": 2,
                "corrupted": 0,
                "corrupted_files": [],
            }
            result = runner.invoke(
                cli,
                ["--format", "json", "data", "validate", "--symbol", "005930"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["summary"]["total_files"] == 2
            assert data["summary"]["valid"] == 2

    def test_validate_no_data(self, runner):
        with patch("ante.data.store.ParquetStore.list_symbols") as mock_list:
            mock_list.return_value = []
            result = runner.invoke(cli, ["data", "validate"])
            assert result.exit_code == 0
            assert "없습니다" in result.output

    def test_validate_all_symbols(self, runner):
        with (
            patch("ante.data.store.ParquetStore.validate") as mock_validate,
            patch("ante.data.store.ParquetStore.list_symbols") as mock_list,
        ):
            mock_list.return_value = ["005930", "000660"]
            mock_validate.side_effect = [
                {
                    "symbol": "005930",
                    "timeframe": "1d",
                    "total": 2,
                    "valid": 2,
                    "corrupted": 0,
                    "corrupted_files": [],
                },
                {
                    "symbol": "000660",
                    "timeframe": "1d",
                    "total": 1,
                    "valid": 1,
                    "corrupted": 0,
                    "corrupted_files": [],
                },
            ]
            result = runner.invoke(cli, ["data", "validate"])
            assert result.exit_code == 0
            assert "전체 3개" in result.output
