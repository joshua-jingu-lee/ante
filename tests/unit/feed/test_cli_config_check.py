"""ante feed config check CLI 커맨드 테스트 (#2046).

API 키 네트워크 유효성 3-state(valid/invalid/unknown) 출력을 검증한다.
실 네트워크 호출 없이 source.validate_credentials를 mock한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
    """인증된 상태의 CliRunner — stdout/stderr 분리."""
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx: object) -> None:
                import click

                ctx = click.get_current_context()
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def data_path(tmp_path: Path) -> str:
    """임시 데이터 디렉토리 경로 (문자열)."""
    return str(tmp_path / "data")


def _set_dart_key(data_path: str) -> None:
    """DART 키만 .env에 설정한다 (DATAGOKR는 미설정)."""
    from ante.feed.config import FeedConfig

    cfg = FeedConfig(data_path)
    cfg.set_api_key("ANTE_DART_API_KEY", "dart-key-value")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수 키가 .env를 가리지 않도록 제거한다."""
    monkeypatch.delenv("ANTE_DART_API_KEY", raising=False)
    monkeypatch.delenv("ANTE_DATAGOKR_API_KEY", raising=False)


class TestConfigCheckValid:
    """유효 키 3-state: ✓ 유효."""

    def test_text_shows_valid(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _ok(self: object) -> tuple[bool, None]:
            return True, None

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _ok)
        result = runner.invoke(
            cli, ["feed", "config", "check", "--data-path", data_path]
        )
        assert result.exit_code == 0
        assert "✓ 유효" in result.stdout
        # DATAGOKR는 미설정 → 검증 표시 생략.
        assert "✗ 미설정" in result.stdout

    def test_json_valid_field(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _ok(self: object) -> tuple[bool, None]:
            return True, None

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _ok)
        result = runner.invoke(
            cli,
            ["--format", "json", "feed", "config", "check", "--data-path", data_path],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        keys = {k["key"]: k for k in payload["keys"]}
        dart = keys["ANTE_DART_API_KEY"]
        assert dart["set"] is True
        assert dart["valid"] is True
        assert dart["detail"] is None
        # 미설정 키는 검증 생략 → valid=None.
        dg = keys["ANTE_DATAGOKR_API_KEY"]
        assert dg["set"] is False
        assert dg["valid"] is None


class TestConfigCheckInvalid:
    """인증 실패 3-state: ✗ 인증 실패."""

    def test_text_shows_auth_fail(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _invalid(self: object) -> tuple[bool, str]:
            return False, "인증 실패 (status=010): 등록되지 않은 키"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _invalid)
        result = runner.invoke(
            cli, ["feed", "config", "check", "--data-path", data_path]
        )
        assert result.exit_code == 0
        assert "✗ 인증 실패" in result.stdout

    def test_json_invalid_field(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _invalid(self: object) -> tuple[bool, str]:
            return False, "인증 실패 (status=010): 등록되지 않은 키"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _invalid)
        result = runner.invoke(
            cli,
            ["--format", "json", "feed", "config", "check", "--data-path", data_path],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        keys = {k["key"]: k for k in payload["keys"]}
        dart = keys["ANTE_DART_API_KEY"]
        assert dart["valid"] is False
        assert "010" in dart["detail"]


class TestConfigCheckUnknown:
    """검증 불가(네트워크) 3-state: ? 검증 불가."""

    def test_text_shows_unknown(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _unknown(self: object) -> tuple[None, str]:
            return None, "검증 불가 (네트워크): offline"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _unknown)
        result = runner.invoke(
            cli, ["feed", "config", "check", "--data-path", data_path]
        )
        assert result.exit_code == 0
        assert "? 검증 불가 (네트워크)" in result.stdout

    def test_json_unknown_field(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _unknown(self: object) -> tuple[None, str]:
            return None, "검증 불가 (네트워크): offline"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _unknown)
        result = runner.invoke(
            cli,
            ["--format", "json", "feed", "config", "check", "--data-path", data_path],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        keys = {k["key"]: k for k in payload["keys"]}
        dart = keys["ANTE_DART_API_KEY"]
        assert dart["valid"] is None
        assert dart["detail"] is not None
        assert "네트워크" in dart["detail"]


class TestConfigCheckOfflineGraceful:
    """offline: source.validate_credentials가 unknown으로 흡수 → 예외 미전파."""

    def test_offline_no_exception_propagation(
        self, runner: CliRunner, data_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_credentials가 unknown 반환 시 명령은 exit 0으로 graceful."""
        _set_dart_key(data_path)
        from ante.feed.sources import dart as dart_mod

        async def _offline(self: object) -> tuple[None, str]:
            return None, "검증 불가 (네트워크): Cannot connect to host"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _offline)
        result = runner.invoke(
            cli, ["feed", "config", "check", "--data-path", data_path]
        )
        assert result.exit_code == 0
        assert result.exception is None
