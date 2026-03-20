"""ante init CLI 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberStatus, MemberType


@pytest.fixture
def runner():
    return CliRunner()


_MOCK_MEMBER = Member(
    member_id="owner",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="홈트레이더",
    emoji="🦊",
    status=MemberStatus.ACTIVE,
    scopes=[],
    token_hash="hash",
    password_hash="hash",
    recovery_key_hash="hash",
    created_at="2026-01-01 00:00:00",
    created_by="system",
    token_expires_at="2026-04-01 00:00:00",
)

_MOCK_TOKEN = "ante_hk_test_token_123"
_MOCK_RECOVERY_KEY = "ANTE-RK-XXXX-YYYY-ZZZZ-AAAA-BBBB-CCCC"


_MOCK_RESULT = {
    "member_id": _MOCK_MEMBER.member_id,
    "role": _MOCK_MEMBER.role,
    "emoji": _MOCK_MEMBER.emoji,
}


def _mock_bootstrap(*args, **kwargs):
    """bootstrap_master mock — 3-tuple (dict, token, recovery_key) 반환."""
    return _MOCK_RESULT, _MOCK_TOKEN, _MOCK_RECOVERY_KEY


def _patch_bootstrap_and_auth():
    """bootstrap_master + authenticate_member + DB를 모두 mock."""
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


class TestInitInteractive:
    """ante init 대화형 통합 흐름 테스트."""

    def test_init_full_with_kis(self, runner, tmp_path):
        """KIS 연동 입력 시 secrets.env에 키가 기록된다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",  # Member ID
                "홈트레이더",  # 이름
                "pass1234",  # 패스워드
                "pass1234",  # 패스워드 확인
                "y",  # KIS 연동? y
                "PSxxxxxxx",  # APP KEY
                "secretkey123",  # APP SECRET
                "50123456-01",  # 계좌번호
                "n",  # 모의투자? n
                "n",  # 텔레그램? n
                "n",  # data.go.kr? n
                "n",  # DART? n
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "초기 설정 완료" in result.output
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output

        # secrets.env에 KIS 키가 기록됨
        secrets_env = target / "secrets.env"
        assert secrets_env.exists()
        content = secrets_env.read_text()
        assert "KIS_APP_KEY=PSxxxxxxx" in content
        assert "KIS_APP_SECRET=secretkey123" in content
        assert "KIS_ACCOUNT_NO=50123456-01" in content

    def test_init_skip_kis_sets_test_broker(self, runner, tmp_path):
        """KIS 스킵 시 system.toml에 broker.type = 'test' 설정."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # KIS 스킵
                "n",  # 텔레그램 스킵
                "n",  # data.go.kr 스킵
                "n",  # DART 스킵
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "Test" in result.output

        system_toml = target / "system.toml"
        content = system_toml.read_text()
        assert "[broker]" in content
        assert 'type = "test"' in content

    def test_init_skip_telegram(self, runner, tmp_path):
        """텔레그램 스킵 시 secrets.env에 텔레그램 키가 없다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # KIS 스킵
                "n",  # 텔레그램 스킵
                "n",  # data.go.kr 스킵
                "n",  # DART 스킵
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        secrets_env = target / "secrets.env"
        content = secrets_env.read_text()
        assert "TELEGRAM_BOT_TOKEN=" not in content.replace("# TELEGRAM_BOT_TOKEN=", "")

    def test_init_with_telegram(self, runner, tmp_path):
        """텔레그램 입력 시 secrets.env에 키가 기록된다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # KIS 스킵
                "y",  # 텔레그램? y
                "bot123token",  # 봇 토큰
                "12345678",  # 채팅 ID
                "n",  # data.go.kr 스킵
                "n",  # DART 스킵
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        secrets_env = target / "secrets.env"
        content = secrets_env.read_text()
        assert "TELEGRAM_BOT_TOKEN=bot123token" in content
        assert "TELEGRAM_CHAT_ID=12345678" in content

    def test_init_with_datafeed(self, runner, tmp_path):
        """DataFeed API 키 입력 시 .feed/.env에 기록된다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # KIS 스킵
                "n",  # 텔레그램 스킵
                "y",  # data.go.kr? y
                "datagokr_key",  # data.go.kr API 키
                "y",  # DART? y
                "dart_key",  # DART API 키
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output

        # .feed/.env에 키가 기록됨
        feed_env = target / "data" / ".feed" / ".env"
        assert feed_env.exists()
        content = feed_env.read_text()
        assert "ANTE_DATAGOKR_API_KEY=datagokr_key" in content
        assert "ANTE_DART_API_KEY=dart_key" in content

    def test_init_skip_datafeed(self, runner, tmp_path):
        """DataFeed 스킵 시 .feed/.env에 키가 없다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # KIS 스킵
                "n",  # 텔레그램 스킵
                "n",  # data.go.kr 스킵
                "n",  # DART 스킵
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        feed_env = target / "data" / ".feed" / ".env"
        assert not feed_env.exists()

    def test_init_json_output(self, runner, tmp_path):
        """--format json 시 JSON 출력."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",
                "n",
                "n",
                "n",
            ]
        )

        patches = _patch_bootstrap_and_auth()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["--format", "json", "init", "--dir", str(target)],
                input=input_lines,
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        # JSON 출력은 대화형 프롬프트 텍스트 뒤에 위치
        lines = result.output.strip().splitlines()
        # 마지막 }를 포함하는 JSON 블록 추출
        json_start = None
        for i, line in enumerate(lines):
            if line.strip().startswith("{"):
                json_start = i
                break
        assert json_start is not None, "JSON output not found"
        json_text = "\n".join(lines[json_start:])
        data = json.loads(json_text)
        assert data["member_id"] == "owner"
        assert data["token"] == _MOCK_TOKEN
        assert data["recovery_key"] == _MOCK_RECOVERY_KEY


class TestInitIdempotent:
    """멱등성: 설정이 이미 존재하면 거부."""

    def test_init_existing_config_rejected(self, runner, tmp_path):
        target = tmp_path / "config"
        target.mkdir()
        (target / "system.toml").write_text("existing")

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        assert result.exit_code == 0
        assert "이미 존재합니다" in result.output


class TestBootstrapTokenReturn:
    """bootstrap_master가 3-tuple (member, token, recovery_key)을 반환하는지 검증."""

    async def test_bootstrap_returns_3_tuple(self, tmp_path):
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.member.service import MemberService

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        try:
            svc = MemberService(db, EventBus())
            await svc.initialize()
            member, token, recovery_key = await svc.bootstrap_master(
                member_id="owner", password="pass123", name="대표"
            )
            assert member.member_id == "owner"
            assert token.startswith("ante_hk_")
            assert recovery_key.startswith("ANTE-RK-")
        finally:
            await db.close()

    async def test_bootstrap_token_authenticates(self, tmp_path):
        """bootstrap에서 발급된 토큰으로 인증이 성공한다."""
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.member.service import MemberService

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        try:
            svc = MemberService(db, EventBus())
            await svc.initialize()
            _, token, _ = await svc.bootstrap_master("owner", "pass123")
            member = await svc.authenticate(token)
            assert member.member_id == "owner"
            assert member.role == MemberRole.MASTER
        finally:
            await db.close()
