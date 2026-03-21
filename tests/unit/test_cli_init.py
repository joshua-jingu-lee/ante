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


_MOCK_TEST_ACCOUNT = [
    {
        "account_id": "test",
        "broker_type": "test",
        "exchange": "TEST",
    }
]


def _mock_bootstrap(*args, **kwargs):
    """bootstrap_master mock — 3-tuple (dict, token, recovery_key) 반환."""
    return _MOCK_RESULT, _MOCK_TOKEN, _MOCK_RECOVERY_KEY


def _mock_create_accounts_test_only(*args, **kwargs):
    """_create_accounts mock — 테스트 계좌만 생성."""
    return _MOCK_TEST_ACCOUNT


def _mock_create_accounts_with_real(*args, **kwargs):
    """_create_accounts mock — 테스트 + 실제 계좌."""
    return [
        *_MOCK_TEST_ACCOUNT,
        {
            "account_id": "domestic",
            "broker_type": "kis-domestic",
            "exchange": "KRX",
        },
    ]


def _patch_bootstrap_and_auth():
    """bootstrap_master + _create_accounts + authenticate_member mock."""
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_accounts",
            new=AsyncMock(side_effect=_mock_create_accounts_test_only),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


def _patch_with_real_account():
    """실제 계좌 등록 포함 mock."""
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_accounts",
            new=AsyncMock(side_effect=_mock_create_accounts_with_real),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


class TestInitInteractive:
    """ante init 대화형 통합 흐름 테스트."""

    def test_init_skip_account_creates_test(self, runner, tmp_path):
        """계좌 등록 스킵 시 테스트 계좌만 생성된다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",  # Member ID
                "홈트레이더",  # 이름
                "pass1234",  # 패스워드
                "pass1234",  # 패스워드 확인
                "n",  # 실제 계좌 등록? n
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
        assert "test (테스트 계좌만)" in result.output
        assert _MOCK_TOKEN in result.output
        assert _MOCK_RECOVERY_KEY in result.output

    def test_init_with_real_account(self, runner, tmp_path):
        """실제 계좌 등록 시 계좌 정보가 표시된다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",  # Member ID
                "홈트레이더",  # 이름
                "pass1234",  # 패스워드
                "pass1234",  # 패스워드 확인
                "y",  # 실제 계좌 등록? y
                "1",  # 브로커 선택 (kis-domestic)
                "domestic",  # 계좌 ID
                "국내 주식",  # 이름
                "PSxxxxxxxx",  # app_key
                "secretkey123",  # app_secret
                "50123456-01",  # account_no
                "n",  # 추가 계좌? n
                "n",  # 텔레그램? n
                "n",  # data.go.kr? n
                "n",  # DART? n
            ]
        )

        patches = _patch_with_real_account()
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

    def test_init_no_kis_keys_in_secrets_env(self, runner, tmp_path):
        """계좌 스킵 시 secrets.env에 KIS 키가 없다 (Account.credentials로 이동)."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # 계좌 스킵
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
        # KIS 관련 키가 secrets.env에 없어야 함
        assert "KIS_APP_KEY" not in content
        assert "KIS_APP_SECRET" not in content
        assert "KIS_ACCOUNT_NO" not in content

    def test_init_no_broker_in_system_toml(self, runner, tmp_path):
        """계좌 스킵 시 system.toml에 [broker] 섹션이 추가되지 않는다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # 계좌 스킵
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
        system_toml = target / "system.toml"
        content = system_toml.read_text()
        # 이전에는 KIS 스킵 시 [broker] type = "test" 추가했으나,
        # 이제는 Account 모델로 관리하므로 system.toml에 [broker] 없어야 함
        assert "[broker]" not in content

    def test_init_skip_telegram(self, runner, tmp_path):
        """텔레그램 스킵 시 secrets.env에 텔레그램 키가 없다."""
        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",
                "홈트레이더",
                "pass1234",
                "pass1234",
                "n",  # 계좌 스킵
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
                "n",  # 계좌 스킵
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
                "n",  # 계좌 스킵
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
                "n",  # 계좌 스킵
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

    def test_init_dart_prompt_eof_defaults_no(self, runner, tmp_path):
        """DART 프롬프트에서 EOF 수신 시 Abort 없이 기본값 'N'으로 처리된다 (#673)."""
        target = tmp_path / "config"
        # 7개 입력만 제공 — DART 프롬프트에서 EOF 발생
        input_lines = "\n".join(
            [
                "owner",  # Member ID
                "홈트레이더",  # 이름
                "pass1234",  # 패스워드
                "pass1234",  # 패스워드 확인
                "n",  # 계좌 등록? n
                "n",  # 텔레그램? n
                "n",  # data.go.kr? n
                # DART 입력 없음 → EOF
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
        # DART 키가 저장되지 않아야 함
        feed_env = target / "data" / ".feed" / ".env"
        assert not feed_env.exists()

    def test_init_json_output(self, runner, tmp_path):
        """--format json 시 JSON 출력에 accounts 포함."""
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
        assert "accounts" in data
        assert data["accounts"][0]["account_id"] == "test"


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


class TestPromptAccount:
    """_prompt_account / _get_available_brokers 단위 테스트."""

    def test_kis_overseas_excluded(self):
        """kis-overseas가 브로커 선택지에서 제외된다."""
        from ante.cli.commands.init import _get_available_brokers

        brokers = _get_available_brokers()
        broker_types = [bt for bt, _ in brokers]
        assert "kis-overseas" not in broker_types
        assert "test" not in broker_types
        assert "kis-domestic" in broker_types


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
