"""Group P missing-resource typed code sweep (#1805 / #1808 / #1810 / #1811).

4 oracle A7 missing-resource issue sweep — 각 CLI 표면이 안정 typed code
envelope 를 surface 함을 subprocess 로 verify 한다 (Group A #1784/#1798
sweep 동형 패턴).

R-case 매트릭스:
  R1 #1805 ``ante member suspend <missing-member> --format json``
         → exit 1, code=``MEMBER_NOT_FOUND``
  R2 #1808 ``ante bot signal-key <bot-without-key> --format json``
         → exit 1, code=``SIGNAL_KEY_NOT_SET`` (in-process CliRunner;
         signal_key 미발급 분기는 실재 bot 시드를 요구하므로 mock 으로
         정확히 재현. subprocess 변형은 ``test_cli_missing_resource_exit.py
         ::TestBotSignalKeyMissingExit`` 가 추가 회귀로 보장)
  R3 #1810 ``ante bot positions <missing-bot> --format json``
         → exit 1, code=``BOT_NOT_FOUND``
  R4 #1811 ``ante approval info <missing-approval> --format json``
         → exit 1, code=``APPROVAL_NOT_FOUND``

R1/R3/R4 는 ``ante init`` 만 완료된 깨끗한 config 에서 missing-id 를
바로 호출하면 typed not-found 가 즉시 발화하므로 subprocess 로 검증한다.
``_clean_env`` / ``initialized_config`` 헬퍼는 ``test_cli_error_code_naming_sweep.py``
패턴 1:1 미러로 부모 환경 누설을 차단한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 5초 마진으로 차단한다.
_SUBPROCESS_TIMEOUT_S = 10.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path,
    *,
    encryption_key: str | None = None,
    token: str | None = None,
) -> dict[str, str]:
    """subprocess 환경 격리 — 부모 ANTE_* 변수가 새지 않도록 명시 전달."""
    env: dict[str, str] = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(config_dir)),
        "ANTE_CONFIG_DIR": str(config_dir),
        "PYTHONPATH": str(_repo_root() / "src"),
    }
    if encryption_key is not None:
        env["ANTE_DB_ENCRYPTION_KEY"] = encryption_key
    if token is not None:
        env["ANTE_MEMBER_TOKEN"] = token
    return env


def _parse_json_last(stdout: str) -> dict:
    """stdout 에서 JSON dict payload 를 추출 (error 한 줄 또는 indent 멀티라인)."""
    stripped = stdout.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    last_obj: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
    assert last_obj is not None, f"JSON dict 라인을 stdout 에서 찾지 못함: {stdout!r}"
    return last_obj


def _run_cli(
    config_dir: Path,
    args: list[str],
    *,
    token: str | None = None,
    encryption_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """``ante --format json <args>`` 를 subprocess 로 실행."""
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _run_init(config_dir: Path, encryption_key: str) -> tuple[str, str]:
    """``ante init`` 후 (token, encryption_key) 반환."""
    init_env = _clean_env(config_dir, encryption_key=encryption_key)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ante",
            "--format",
            "json",
            "init",
            "--name",
            "GroupP",
        ],
        env=init_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"init 실패: exit={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    token = payload.get("token")
    assert token, f"init 출력에 token 없음: {payload}"
    return token, encryption_key


@pytest.fixture
def initialized_config(tmp_path: Path) -> tuple[Path, str, str]:
    """``ante init`` 을 완료한 (config_dir, token, encryption_key) 튜플."""
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()
    token, _ = _run_init(config_dir, key)
    return config_dir, token, key


# ────────────────────────────────────────────────────────────────────
# R1 #1805 — member suspend <missing-member> → MEMBER_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestMemberSuspendMissingMemberTypedCode:
    """``ante member suspend <missing> --format json`` →
    exit 1, code=``MEMBER_NOT_FOUND``.

    service ``_get_or_raise`` 가 ``MemberNotFoundError`` 를 raise 하고 CLI
    ``member suspend`` 의 typed catch 분기가 안정 코드 envelope 으로
    surface 한다.
    """

    def test_suspend_missing_member_emits_typed_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["member", "suspend", "mbr-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R2 #1808 — bot signal-key <bot-without-key> → SIGNAL_KEY_NOT_SET
# (in-process CliRunner — 실재 bot 시드 + signal_key None 분기 mock 재현)
# ────────────────────────────────────────────────────────────────────


class TestBotSignalKeyNotSetTypedCode:
    """``ante bot signal-key <bot-without-key> --format json`` →
    exit 1, code=``SIGNAL_KEY_NOT_SET``.

    실재 bot 인데 ``signal key`` 가 발급되지 않은 분기 (#1808). 미존재 bot
    (#1810 ``BOT_NOT_FOUND``) 과 envelope code 로 의미를 구분한다.
    """

    def test_signal_key_not_set_emits_typed_code(self) -> None:
        from ante.cli.main import cli
        from ante.member.models import Member, MemberRole, MemberType

        master = Member(
            member_id="grp-p-master",
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            org="default",
            name="Group P Master",
            status="active",
            scopes=[],
        )

        runner = CliRunner(mix_stderr=False)

        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        # 실재 bot row (status != deleted) — bots row 존재.
        mock_db.fetch_one = AsyncMock(return_value={"strategy_id": "stg-1"})
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value=None)

        def _auth_set(ctx):  # noqa: ANN001, ANN202
            ctx.obj = ctx.obj or {}
            ctx.obj["member"] = master

        with (
            patch("ante.cli.main.authenticate_member", side_effect=_auth_set),
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "signal-key",
                    "bot-without-key",
                ],
            )

        assert result.exit_code == 1, (
            f"exit={result.exit_code}\nstdout={result.stdout!r}\n"
            f"stderr={result.stderr!r}"
        )
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["status"] == "error", payload
        assert payload["code"] == "SIGNAL_KEY_NOT_SET", payload
        assert "bot-without-key" in payload["message"], payload


# ────────────────────────────────────────────────────────────────────
# R3 #1810 — bot positions <missing-bot> → BOT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestBotPositionsMissingBotTypedCode:
    """``ante bot positions <missing> --format json`` →
    exit 1, code=``BOT_NOT_FOUND``.

    형제 명령 ``bot info`` / ``bot remove`` 와 envelope code 정렬 (#1810).
    """

    def test_positions_missing_bot_emits_typed_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["bot", "positions", "bot-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "BOT_NOT_FOUND", payload
        # 결함 시점의 success envelope 가 더는 새지 않아야 한다.
        assert "보유 포지션 없음" not in result.stdout, result.stdout


# ────────────────────────────────────────────────────────────────────
# R4 #1811 — approval info <missing-approval> → APPROVAL_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestApprovalInfoMissingTypedCode:
    """``ante approval info <missing> --format json`` →
    exit 1, code=``APPROVAL_NOT_FOUND``.

    ``_find_request`` 가 ``ApprovalNotFoundError`` 를 raise 하고 CLI
    ``approval info`` 의 typed catch 분기가 안정 코드 envelope 으로
    surface 한다 (Group A #1798 ``cancel_invalid_type_request`` 동형 패턴).
    """

    def test_info_missing_approval_emits_typed_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["approval", "info", "appr-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "APPROVAL_NOT_FOUND", payload
