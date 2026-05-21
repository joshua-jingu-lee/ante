"""CLI ``ante signal connect`` JSON envelope 회귀 (#1705).

기존 4 validation 오류 경로 — invalid key / bot not found / bot not running /
bot not accepting signals — 가 raw stderr 로만 발화하여 ``--format json`` 호출이
``Error: No such option: --format`` 으로 거부되거나 JSON envelope 으로 normalize
되지 않던 ingress drift를 닫는다.

본 파일은 #1701 ``test_cli_format_option.py`` 의 ``runner`` 인증 fixture 패턴을
미러하여, ``ante.cli.main.authenticate_member`` 를 monkeypatch 해 leaf callback
의 ``require_auth`` 가드를 통과시킨다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.bot.config import BotStatus
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


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner — ``mix_stderr=False`` 로 stderr 분리."""
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


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


def _patch_signal_deps(
    *,
    bot_id_for_key: str | None,
    bot: MagicMock | None,
):
    """signal_connect 실행 환경의 Database/SignalKeyManager/BotManager mock 컨텍스트.

    Args:
        bot_id_for_key: ``validate_key(key)`` 반환값. ``None`` 이면 invalid key.
        bot: ``BotManager.get_bot()`` 반환값. ``None`` 이면 bot not found.
    """
    db = _mock_db()
    skm = MagicMock()
    skm.initialize = AsyncMock()
    skm.validate_key = AsyncMock(return_value=bot_id_for_key)

    manager = MagicMock()
    manager.initialize = AsyncMock()
    manager.get_bot = MagicMock(return_value=bot)

    patchers = [
        patch("ante.core.database.Database", return_value=db),
        patch("ante.bot.signal_key.SignalKeyManager", return_value=skm),
        patch("ante.bot.manager.BotManager", return_value=manager),
        patch("ante.eventbus.bus.EventBus", return_value=MagicMock()),
        patch("ante.cli.main.get_db_path", return_value=":memory:"),
    ]
    return patchers


def _make_bot(
    *,
    status: BotStatus = BotStatus.RUNNING,
    accepts_external_signals: bool = True,
    bot_id: str = "bot-1705",
) -> MagicMock:
    """validation-path mock Bot.

    status + strategy.meta.accepts_external_signals 만 사용.
    """
    bot = MagicMock()
    bot.status = status
    if accepts_external_signals:
        strategy = MagicMock()
        strategy.meta = MagicMock()
        strategy.meta.accepts_external_signals = True
        bot.strategy = strategy
    else:
        strategy = MagicMock()
        strategy.meta = MagicMock()
        strategy.meta.accepts_external_signals = False
        bot.strategy = strategy
    bot._ctx = MagicMock()
    return bot


# ──────────────────────────────────────────────────────────────
# A. 4 validation × JSON mode
# ──────────────────────────────────────────────────────────────


class TestSignalConnectJsonEnvelope1705:
    """``--format json`` 모드: stdout JSON envelope + stderr empty + exit 1."""

    def test_invalid_key(self, runner: CliRunner) -> None:
        patchers = _patch_signal_deps(bot_id_for_key=None, bot=None)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_invalid", "--format", "json"],
            )
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "INVALID_SIGNAL_KEY",
            "message": "Invalid signal key",
        }
        assert result.stderr == ""

    def test_bot_not_found(self, runner: CliRunner) -> None:
        patchers = _patch_signal_deps(bot_id_for_key="bot-missing", bot=None)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_FOUND",
            "message": "Bot not found: bot-missing",
        }
        assert result.stderr == ""

    def test_bot_not_running(self, runner: CliRunner) -> None:
        bot = _make_bot(status=BotStatus.STOPPED, bot_id="bot-1705")
        patchers = _patch_signal_deps(bot_id_for_key="bot-1705", bot=bot)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_RUNNING",
            "message": "Bot is not running: bot-1705 (status: stopped)",
        }
        assert result.stderr == ""

    def test_bot_not_accepting_signals(self, runner: CliRunner) -> None:
        bot = _make_bot(
            status=BotStatus.RUNNING,
            accepts_external_signals=False,
            bot_id="bot-1705",
        )
        patchers = _patch_signal_deps(bot_id_for_key="bot-1705", bot=bot)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_ACCEPTING_SIGNALS",
            "message": "Bot bot-1705 does not accept external signals",
        }
        assert result.stderr == ""


# ──────────────────────────────────────────────────────────────
# B. 4 validation × text mode (default — no Error: prefix)
# ──────────────────────────────────────────────────────────────


class TestSignalConnectTextMode1705:
    """default text 모드: stderr raw text + stdout empty + exit 1.

    ``Error: `` prefix 가 붙지 않아야 하며, 기존 ``_err()`` 동작
    (raw stderr + ``\\n``) 을 회귀 lock 한다.
    """

    def test_invalid_key_text(self, runner: CliRunner) -> None:
        patchers = _patch_signal_deps(bot_id_for_key=None, bot=None)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_invalid"])
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Invalid signal key\n"
        assert result.stdout == ""

    def test_bot_not_found_text(self, runner: CliRunner) -> None:
        patchers = _patch_signal_deps(bot_id_for_key="bot-missing", bot=None)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot not found: bot-missing\n"
        assert result.stdout == ""

    def test_bot_not_running_text(self, runner: CliRunner) -> None:
        bot = _make_bot(status=BotStatus.STOPPED, bot_id="bot-1705")
        patchers = _patch_signal_deps(bot_id_for_key="bot-1705", bot=bot)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot is not running: bot-1705 (status: stopped)\n"
        assert result.stdout == ""

    def test_bot_not_accepting_signals_text(self, runner: CliRunner) -> None:
        bot = _make_bot(
            status=BotStatus.RUNNING,
            accepts_external_signals=False,
            bot_id="bot-1705",
        )
        patchers = _patch_signal_deps(bot_id_for_key="bot-1705", bot=bot)
        for p in patchers:
            p.start()
        try:
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])
        finally:
            for p in patchers:
                p.stop()

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot bot-1705 does not accept external signals\n"
        assert result.stdout == ""


# ──────────────────────────────────────────────────────────────
# C. Informational stderr regression — 정상 path 의 2 informational 메시지
# ──────────────────────────────────────────────────────────────


class TestSignalConnectInformationalStderr1705:
    """정상 path (valid key + running + accepts_external_signals) 에서
    ``Connected to bot ...`` / ``Ready for JSON Lines ...`` 메시지가
    stderr 에 그대로 출력됨을 lock. ``channel.run()`` 은 mock 해
    채널 수립 직후 즉시 종료시킨다.
    """

    def test_informational_messages_to_stderr(self, runner: CliRunner) -> None:
        bot = _make_bot(
            status=BotStatus.RUNNING,
            accepts_external_signals=True,
            bot_id="bot-1705",
        )
        patchers = _patch_signal_deps(bot_id_for_key="bot-1705", bot=bot)
        # SignalChannel.run() 을 즉시 종료시킨다.
        mock_channel = MagicMock()
        mock_channel.run = AsyncMock(return_value=None)
        signal_channel_patch = patch(
            "ante.bot.signal_channel.SignalChannel", return_value=mock_channel
        )
        for p in patchers:
            p.start()
        signal_channel_patch.start()
        try:
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])
        finally:
            signal_channel_patch.stop()
            for p in patchers:
                p.stop()

        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert "Connected to bot bot-1705" in result.stderr
        assert "Ready for JSON Lines communication on stdin/stdout" in result.stderr


# ──────────────────────────────────────────────────────────────
# D. Optional auth-fail regression — root-level --format json
# ──────────────────────────────────────────────────────────────


class TestSignalConnectAuthFail1705:
    """no-token + root-level ``--format json signal connect`` →
    stdout ``auth_required`` JSON envelope (root-level Workaround sibling 정합).
    """

    def test_auth_required_json_envelope(self) -> None:
        r = CliRunner(mix_stderr=False)
        # authenticate_member 가 ctx.obj["member"] 를 채우지 않도록 monkeypatch.
        # require_auth 가드는 member is None 시 _emit_auth_error 로 종료.
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _no_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = None

            mock_auth.side_effect = _no_member
            result = r.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "signal",
                    "connect",
                    "--key",
                    "sk_anything",
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "auth_required"
