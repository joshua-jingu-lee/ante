"""CLI runtime DB encryption key chokepoint 단위 테스트 (#1913).

본 테스트는 ``src/ante/cli/middleware.py`` 의 ``AuthenticatedGroup.invoke`` 에
부착된 단일 chokepoint(``_enforce_db_encryption_key_gate``) 가 다음을 보장하는지
검증한다:

1. ``ANTE_DB_ENCRYPTION_KEY`` 환경변수가 미설정/빈 → exit 1, JSON envelope
   ``code="DB_ENCRYPTION_KEY_MISSING"``, traceback 미노출.
2. ``ANTE_DB_ENCRYPTION_KEY`` 환경변수가 Fernet canonical 형식 위반 → exit 1,
   JSON envelope ``code="DB_ENCRYPTION_KEY_INVALID"``, traceback 미노출.
3. 면제 4 경로 (``("init",)`` / ``("member", "reset-password")`` /
   ``("member", "regenerate-recovery-key")`` / ``("feed", "init")``) 는 키 누락
   상태에서도 chokepoint 를 우회한다.
4. 3 oracle 표면 회귀: ``bot list`` / ``treasury status`` / ``broker status``
   각각이 키 누락 시 traceback/timeout 대신 동일 envelope 으로 정합된다.

SSOT 재사용:
- ``src/ante/account/crypto.py`` — typed exceptions + ``_validate_fernet_key``.
- ``src/ante/cli/middleware.py`` — chokepoint helper.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet

if TYPE_CHECKING:
    from collections.abc import Iterator

from ante.cli.main import cli
from ante.cli.middleware import _ENCRYPTION_EXEMPT_COMMAND_PATHS
from tests.unit.contracts.helpers import iter_click_leaf_commands

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """기본 CliRunner."""
    return CliRunner()


@pytest.fixture()
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """``ANTE_DB_ENCRYPTION_KEY`` / ``ANTE_MEMBER_TOKEN`` 부재 + 빈 config_dir.

    chokepoint 검증을 위해:
    - ``ANTE_DB_ENCRYPTION_KEY`` 를 ``os.environ`` 에서 명시 제거.
    - ``ANTE_CONFIG_DIR`` 을 빈 tmp_path 로 고정 (``Config.load`` 가 file_key
      fallback 으로 export 하지 못하도록 ``secrets.env`` 부재).
    - ``ANTE_MEMBER_TOKEN`` / ``ANTE_TOKEN_FILE`` 도 차단 (인증 게이트 영향 분리).

    chokepoint 가 인증 게이트 **이전** 에 발화하므로, 토큰 유무와 무관하게
    encryption error envelope 이 우선 노출되어야 한다.
    """
    monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    yield config_dir


@pytest.fixture()
def valid_key_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """valid Fernet key + 빈 config_dir + 토큰 차단.

    chokepoint 가 정상적으로 통과하는지 검증할 때 사용한다 (regression).
    """
    monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    yield config_dir


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────


def _parse_json_error_envelope(output: str) -> dict:
    """stdout 의 마지막 JSON dict 라인을 추출한다.

    ``OutputFormatter.error`` 는 JSON 모드에서 한 줄로 dump 한다. 부가 출력이
    있을 수 있으므로 마지막 JSON dict 라인을 찾는다.
    """
    last_obj: dict | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
    assert last_obj is not None, (
        f"JSON dict envelope 을 stdout 에서 찾지 못함: {output!r}"
    )
    return last_obj


# ── 기본 chokepoint 동작: missing key ────────────────────────────────────────


class TestChokepointMissingKey:
    """``ANTE_DB_ENCRYPTION_KEY`` 미설정 시 envelope error."""

    def test_bot_list_json_missing_key(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante --format json bot list`` → exit 1, code=DB_ENCRYPTION_KEY_MISSING.

        oracle 표면 1/3 (#1913 재현 case). 기존 회귀: traceback leak.

        Invariant 4 (r1 보강): success shape 누설 차단. ``bot list`` 의 success
        payload 는 ``list[dict[{bot_id, name, strategy_id, account_id, status,
        created_at}]]`` 이므로, 해당 raw 키가 envelope 에 단 한 글자도 새지
        않아야 한다. 또한 envelope 키 집합은 정확히 ``{status, code, message}``
        3 개로 한정된다 (``OutputFormatter.error`` SSOT).
        """
        result = runner.invoke(cli, ["--format", "json", "bot", "list"])
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING", payload
        # traceback 이 stdout/stderr 로 누출되지 않아야 한다.
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        # envelope 키 집합 강제: error shape 은 정확히 3 키.
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        # ``OutputFormatter.success`` 의 wrapping 키도 새지 않아야 한다.
        assert "data" not in payload, payload
        # ``bot list`` raw row 키 누설 차단 (stdout 전체 grep).
        for leaked_key in ("bot_id", "strategy_id", "created_at"):
            assert leaked_key not in result.output, (leaked_key, result.output)

    def test_treasury_status_json_missing_key(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante --format json treasury status --account test`` → exit 1, MISSING.

        oracle 표면 2/3.

        Invariant 4 (r1 보강): success shape 누설 차단. ``treasury status``
        의 success payload 는 ``{account_balance, purchasable_amount,
        total_evaluation, total_profit_loss, ...}`` dict 이므로 해당 키가
        envelope 에 새지 않아야 한다.
        """
        result = runner.invoke(
            cli,
            ["--format", "json", "treasury", "status", "--account", "test"],
        )
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING", payload
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        assert "data" not in payload, payload
        for leaked_key in (
            "account_balance",
            "purchasable_amount",
            "total_evaluation",
            "total_profit_loss",
        ):
            assert leaked_key not in result.output, (leaked_key, result.output)

    def test_broker_status_json_missing_key(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante --format json broker status --account test`` → exit 1, MISSING.

        oracle 표면 3/3. 기존 회귀: exit 124 (timeout) + `{connected,error,healthy}`
        shape leak. chokepoint 통과 후에는 typed envelope 으로 정합되어 IPC 호출
        자체가 발생하지 않으므로 timeout 도 사라진다.

        Invariant 4 (r1 보강): broker status success payload 는
        ``{connected, healthy, exchange}`` 또는 폴백 시 ``{connected, healthy,
        error}`` 형태이므로, ``healthy`` / ``exchange`` / ``error`` 키가 단 한
        글자도 새지 않아야 한다. envelope 키 집합도 정확히 3 키로 한정한다.
        """
        result = runner.invoke(
            cli,
            ["--format", "json", "broker", "status", "--account", "test"],
        )
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING", payload
        # 성공형 broker status payload 가 새지 않아야 한다.
        assert "connected" not in result.output, result.output
        assert "healthy" not in result.output, result.output
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        assert "data" not in payload, payload
        # ``{connected, healthy, exchange}`` / fallback ``{connected, healthy,
        # error}`` 모두 차단. envelope error 의 ``message`` 가 ``"..."`` 영문
        # ``error`` 단어를 포함할 가능성을 피하기 위해 payload 키만 검사한다.
        assert "exchange" not in payload, payload
        assert "error" not in payload, payload
        # r2 보강: stdout 전체 grep — invalid 케이스와 동형으로 ``exchange``
        # 단어가 message/추가 출력에 새지 않도록 검사한다.
        assert "exchange" not in result.output, result.output

    def test_text_mode_missing_key_no_json_envelope(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """text 모드는 한국어 메시지 + exit 1, JSON envelope shape 미노출.

        click 8.1 CliRunner 는 기본적으로 stderr 를 stdout 으로 합치므로(=mix
        stderr), output 에 한국어 메시지가 포함되고 JSON envelope key
        (``"code":``) 는 등장하지 않는다.
        """
        result = runner.invoke(cli, ["bot", "list"])
        assert result.exit_code == 1, result.output
        # 한국어 메시지(=ANTE_DB_ENCRYPTION_KEY 환경변수 안내) 포함.
        assert "ANTE_DB_ENCRYPTION_KEY" in result.output, result.output
        # JSON envelope shape 이 새지 않아야 한다.
        assert '"code"' not in result.output, result.output
        assert '"status"' not in result.output, result.output


# ── chokepoint 동작: invalid key ────────────────────────────────────────────


class TestChokepointInvalidKey:
    """``ANTE_DB_ENCRYPTION_KEY`` 형식 위반 시 envelope error."""

    def test_bot_list_json_invalid_key(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """garbage key → exit 1, code=DB_ENCRYPTION_KEY_INVALID.

        Invariant 4 (r1 보강): success ``bot list`` payload 키 누설 차단.
        """
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "not-a-valid-fernet-key")
        result = runner.invoke(cli, ["--format", "json", "bot", "list"])
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_INVALID", payload
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        assert "data" not in payload, payload
        for leaked_key in ("bot_id", "strategy_id", "created_at"):
            assert leaked_key not in result.output, (leaked_key, result.output)

    def test_treasury_status_json_invalid_key(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """garbage key + treasury status → INVALID envelope.

        Invariant 4 (r1 보강): success ``treasury status`` payload 키 누설
        차단.
        """
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "garbage")
        result = runner.invoke(
            cli,
            ["--format", "json", "treasury", "status", "--account", "test"],
        )
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_INVALID", payload
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        assert "data" not in payload, payload
        for leaked_key in (
            "account_balance",
            "purchasable_amount",
            "total_evaluation",
            "total_profit_loss",
        ):
            assert leaked_key not in result.output, (leaked_key, result.output)

    def test_broker_status_json_invalid_key(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """garbage key + broker status → INVALID envelope (timeout 회피).

        Invariant 4 (r1 보강): ``broker status`` success payload 는
        ``{connected, healthy, exchange}`` 또는 fallback ``{connected, healthy,
        error}`` 이므로 ``healthy`` / ``exchange`` / ``error`` 키가 envelope 에
        새지 않아야 한다.
        """
        # 길이는 맞지만 invalid base64 padding/charset → Fernet 생성 실패.
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "x" * 44)
        result = runner.invoke(
            cli,
            ["--format", "json", "broker", "status", "--account", "test"],
        )
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "DB_ENCRYPTION_KEY_INVALID", payload
        assert "connected" not in result.output, result.output
        assert "Traceback" not in result.output, result.output
        # ── Invariant 4 (r1 보강): success payload leak 차단 ────────────────
        # envelope 키 집합 강제 + ``healthy`` / ``exchange`` / ``error`` 부재.
        assert set(payload.keys()) == {"status", "code", "message"}, payload
        assert "data" not in payload, payload
        assert "healthy" not in payload, payload
        assert "exchange" not in payload, payload
        assert "error" not in payload, payload
        # stdout 전체 grep — ``healthy`` 단어가 message 등에 새지 않도록 검사.
        assert "healthy" not in result.output, result.output
        assert "exchange" not in result.output, result.output


# ── 면제 경로: chokepoint 우회 ───────────────────────────────────────────────


class TestEncryptionExemptPaths:
    """``_ENCRYPTION_EXEMPT_COMMAND_PATHS`` 4 경로는 키 누락 시에도 우회한다."""

    def test_exempt_paths_match_normative_set(self) -> None:
        """SSOT: encryption exempt 4 경로가 정확히 일치한다."""
        assert _ENCRYPTION_EXEMPT_COMMAND_PATHS == {
            ("init",),
            ("member", "reset-password"),
            ("member", "regenerate-recovery-key"),
            ("feed", "init"),
        }

    def test_encryption_exempt_paths_resolve_to_real_leaves(self) -> None:
        """면제 4 튜플 전건이 실제 Click leaf 로 존재한다.

        ``_ENCRYPTION_EXEMPT_COMMAND_PATHS`` 는 문자열 literal 집합이라 CLI
        트리 개편에 따라 drift 해도 정적으로는 잡히지 않는다. 실제 leaf
        path 집합과 대조해 전건 실존을 검증한다.
        """
        leaf_paths = {leaf.path for leaf in iter_click_leaf_commands()}
        assert _ENCRYPTION_EXEMPT_COMMAND_PATHS <= leaf_paths, (
            _ENCRYPTION_EXEMPT_COMMAND_PATHS - leaf_paths
        )

    def test_init_help_passes_without_key(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante init --help`` → 키 없이도 exit 0 (help 출력)."""
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        # encryption error envelope 이 새지 않아야 한다.
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output

    def test_init_callback_runs_without_key(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante init --dir ...`` 은 키 없이 callback 진입.

        실제 부트스트랩 mutation 은 mock 으로 차단하고, encryption envelope 이
        새지 않는지 + chokepoint 가 발화하지 않는지만 확인한다.
        """
        target = isolated_env.parent / "init-target"
        bootstrap_mock = AsyncMock()
        create_acc_mock = AsyncMock()

        with (
            patch("ante.cli.commands.init._bootstrap_master", new=bootstrap_mock),
            patch(
                "ante.cli.commands.init._create_test_account",
                new=create_acc_mock,
            ),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])

        # chokepoint 가 발화하지 않아야 한다.
        assert "DB_ENCRYPTION_KEY_MISSING" not in result.output, result.output
        assert "DB_ENCRYPTION_KEY_INVALID" not in result.output, result.output

    def test_member_reset_password_exempt(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ante member reset-password`` 는 키 없이 callback 단계까지 진입."""
        from contextlib import asynccontextmanager

        monkeypatch.setenv("RESET_PW_ENV", "newpass123")

        @asynccontextmanager
        async def _raising_factory(ctx=None):  # noqa: ANN001, ANN202
            raise RuntimeError("stop-here")
            yield  # pragma: no cover

        with patch(
            "ante.cli.commands.member._create_service",
            new=_raising_factory,
        ):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "ANTE-RK-test",
                    "--new-password-env",
                    "RESET_PW_ENV",
                ],
            )

        # chokepoint 가 발화하지 않아야 한다 — DB_ENCRYPTION_KEY_* 라우팅 없음.
        assert "DB_ENCRYPTION_KEY_MISSING" not in result.output, result.output
        assert "DB_ENCRYPTION_KEY_INVALID" not in result.output, result.output

    def test_member_regenerate_recovery_key_exempt(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ante member regenerate-recovery-key`` 면제 진입 확인."""
        from contextlib import asynccontextmanager

        monkeypatch.setenv("CURRENT_PW_ENV", "currentpass")

        @asynccontextmanager
        async def _raising_factory(ctx=None):  # noqa: ANN001, ANN202
            raise RuntimeError("stop-here")
            yield  # pragma: no cover

        with patch(
            "ante.cli.commands.member._create_service",
            new=_raising_factory,
        ):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "CURRENT_PW_ENV",
                ],
            )

        assert "DB_ENCRYPTION_KEY_MISSING" not in result.output, result.output
        assert "DB_ENCRYPTION_KEY_INVALID" not in result.output, result.output

    def test_feed_init_exempt(self, runner: CliRunner, isolated_env: Path) -> None:
        """``ante feed init`` 은 ``FeedConfig.init`` 만 호출하므로 encryption 면제.

        토큰이 없으므로 auth 게이트에서 차단되겠지만, chokepoint(=encryption
        gate)는 발화하지 않아야 한다.
        """
        result = runner.invoke(cli, ["feed", "init"])
        # chokepoint(encryption gate)는 발화하지 않아야 한다.
        assert "DB_ENCRYPTION_KEY_MISSING" not in result.output, result.output
        assert "DB_ENCRYPTION_KEY_INVALID" not in result.output, result.output

    def test_init_does_not_get_blocked_by_chokepoint_when_key_invalid(
        self,
        runner: CliRunner,
        isolated_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``init`` 면제는 invalid key 상태에서도 동일하게 우회한다."""
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "garbage-not-fernet")
        result = runner.invoke(cli, ["init", "--help"])
        assert result.exit_code == 0, result.output
        assert "DB_ENCRYPTION_KEY_INVALID" not in result.output, result.output


# ── 메타 면제 경로: --help / -h 는 chokepoint skip ───────────────────────────


class TestMetaExemptInteraction:
    """``--help`` / ``-h`` 메타 옵션은 chokepoint 발화 전에 click 이 처리한다."""

    def test_root_help_skips_chokepoint(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante --help`` → key 없이 exit 0."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0, result.output
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output

    def test_leaf_help_skips_chokepoint(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante bot list --help`` → key 없이 exit 0."""
        result = runner.invoke(cli, ["bot", "list", "--help"])
        assert result.exit_code == 0, result.output
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output

    def test_no_args_shows_help_without_chokepoint(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante`` (no args) → no_args_is_help → exit 0."""
        result = runner.invoke(cli, [])
        assert result.exit_code == 0, result.output
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output

    def test_version_skips_chokepoint(
        self, runner: CliRunner, isolated_env: Path
    ) -> None:
        """``ante --version`` 은 root ``@click.version_option`` 이 처리 → exit 0."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0, result.output
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output


# ── chokepoint 정상 통과: valid key ─────────────────────────────────────────


class TestChokepointPassesWithValidKey:
    """valid Fernet key 가 설정되어 있으면 chokepoint 는 통과한다."""

    def test_bot_list_passes_chokepoint_then_auth_gate(
        self, runner: CliRunner, valid_key_env: Path
    ) -> None:
        """valid key + 토큰 없음 → chokepoint 통과 후 auth 게이트에서 exit 1.

        chokepoint 가 envelope 을 출력하지 않고, 인증 게이트의 "인증이 필요합니다"
        메시지가 발화한다는 점이 정상 통과의 증거다.
        """
        result = runner.invoke(cli, ["bot", "list"])
        assert result.exit_code == 1, result.output
        # encryption envelope 이 아닌 인증 메시지가 나와야 한다.
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output
        assert "인증이 필요합니다" in result.output, result.output


# ── secrets.env fallback: Config.load 가 키를 export 시키는 경로 ─────────────


class TestChokepointConfigLoadFallback:
    """``secrets.env`` 의 ``ANTE_DB_ENCRYPTION_KEY`` 행이 valid 면 chokepoint 통과.

    ``Config.load`` 의 export fallback 이 chokepoint 발화 **이전** 에 실행되어
    env 가 비어 있어도 ``secrets.env`` 행만으로 통과해야 한다 (Implementation
    Plan v2 — "환경변수 fallback 이 정상 동작한 뒤에야 검증이 호출된다" invariant).
    """

    def test_secrets_env_key_is_exported_before_chokepoint(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``secrets.env`` 에 valid Fernet 행 + env 미설정 → 통과."""
        # env 명시 차단
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))

        # config_dir + secrets.env 에 valid Fernet 행 작성
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        valid_key = Fernet.generate_key().decode()
        (config_dir / "secrets.env").write_text(f"ANTE_DB_ENCRYPTION_KEY={valid_key}\n")
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))

        result = runner.invoke(cli, ["bot", "list"])
        # chokepoint 가 통과되어 인증 게이트로 진입 → 인증 실패.
        assert result.exit_code == 1, result.output
        assert "DB_ENCRYPTION_KEY" not in result.output, result.output
        assert "인증이 필요합니다" in result.output, result.output

    def test_secrets_env_with_invalid_key_still_fails(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``secrets.env`` 의 invalid 키는 ``Config.load`` 가 export 하지 않으므로
        env 도 비어 있는 상태가 유지되어 ``DB_ENCRYPTION_KEY_MISSING`` 으로 종료.
        """
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent.token"))

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "secrets.env").write_text(
            "ANTE_DB_ENCRYPTION_KEY=not-a-valid-fernet-key\n"
        )
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))

        result = runner.invoke(cli, ["--format", "json", "bot", "list"])
        assert result.exit_code == 1, result.output
        payload = _parse_json_error_envelope(result.output)
        # invalid file_key 는 Config.load 가 export 하지 않으므로 env 가 빈 상태로
        # 유지되어 MISSING 으로 종료한다 (Config.load:128-139 게이트).
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING", payload
