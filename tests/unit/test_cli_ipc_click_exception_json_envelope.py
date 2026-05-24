"""IPC ``ClickException`` 경로의 ``--format json`` envelope 회귀 (#1754).

IPC 런타임이 없는 상태에서 다음 명령들이 ``--format json`` 모드에서
구조화 에러 envelope (``{status: "error", code, message}``) 을 stdout 으로
방출하고 stderr 에는 Python traceback 을 노출하지 않아야 한다.

회귀 매트릭스:

- R1: ``system halt --reason test --format json`` (IPC 미기동) → exit 1,
  stdout JSON ``code="IPC_SERVER_NOT_RUNNING"``, stderr 에 ``Traceback`` 없음.
- R2: ``treasury allocate <bot> <amount> --account <id> --format json``
  (IPC 미기동) → exit 1, stdout JSON ``code="IPC_SERVER_NOT_RUNNING"``,
  stderr 에 ``Traceback`` 없음.
- R3: ``approval cancel <id> --format json`` (IPC 미기동) → exit 1, stdout
  JSON ``code="IPC_SERVER_NOT_RUNNING"``, stderr 에 ``Traceback`` 없음.
- R4 (sanity, text mode): 동일 명령 + ``--format text`` → exit 1, stderr
  에 기존 사용자 메시지 ("서버가 실행 중이 아닙니다") 보존, JSON envelope
  로 변환되지 않음 (text 모드 회귀 락).

``_clean_env`` + ``subprocess.run`` 패턴은
``tests/unit/test_cli_fresh_init_read_contract.py`` (#1753) 및
``tests/unit/test_cli_account_crypto_error.py`` (#1722) 와 동형이다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 10초 마진으로 차단한다. 정상 종료는 1-2초.
_SUBPROCESS_TIMEOUT_S = 10.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path, *, encryption_key: str, token: str | None = None
) -> dict[str, str]:
    """subprocess 환경 격리 헬퍼.

    부모 프로세스의 ``ANTE_DB_ENCRYPTION_KEY`` / ``ANTE_MEMBER_TOKEN`` 등이
    새는 것을 막기 위해 ``PATH`` / ``HOME`` / ``ANTE_CONFIG_DIR`` /
    ``ANTE_DB_ENCRYPTION_KEY`` / ``PYTHONPATH`` 만 명시 전달한다
    (``test_cli_fresh_init_read_contract.py`` _clean_env 동형).
    """
    env: dict[str, str] = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(config_dir)),
        "ANTE_CONFIG_DIR": str(config_dir),
        "PYTHONPATH": str(_repo_root() / "src"),
        "ANTE_DB_ENCRYPTION_KEY": encryption_key,
    }
    if token is not None:
        env["ANTE_MEMBER_TOKEN"] = token
    return env


@pytest.fixture
def fresh_init(tmp_path: Path) -> tuple[Path, str, str]:
    """``ante init`` 만 수행한 fresh config dir + member token + key 페어.

    IPC 서버는 시작하지 않는다. ``ipc_send`` 호출 시 ``ServerNotRunningError``
    가 즉시 발생해 ``ClickException`` 으로 raise 되는 시나리오를 재현한다.
    """
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()

    init_env = _clean_env(config_dir, encryption_key=key)
    result = subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", "init", "--name", "Repro"],
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
    return config_dir, token, key


def _run_cli(
    config_dir: Path,
    token: str,
    key: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """``ante <args>`` 를 subprocess 로 실행한다."""
    env = _clean_env(config_dir, encryption_key=key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _parse_last_json_dict(stdout: str) -> dict:
    """stdout 의 (마지막) JSON dict 라인을 추출한다.

    ``OutputFormatter.error`` 는 JSON 모드에서 한 줄로 dump 한다. 전체가 단일
    객체인 경우는 ``json.loads(stdout)`` 가 가장 robust 하므로 먼저 시도한다.
    """
    stripped = stdout.strip()
    if stripped:
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


def _assert_no_traceback(stderr: str) -> None:
    """stderr 에 Python traceback 흔적이 없는지 검증.

    ``Traceback (most recent call last)`` 헤더, ``click.exceptions`` 모듈
    경로, ``ipc_helpers`` 경로 등 #1754 재현 시 새던 흔적을 차단한다.
    """
    assert "Traceback" not in stderr, f"stderr 에 traceback 노출: {stderr!r}"
    assert "ipc_helpers" not in stderr, (
        f"stderr 에 ipc_helpers 모듈 경로 노출: {stderr!r}"
    )
    assert "click.exceptions" not in stderr, (
        f"stderr 에 click.exceptions 노출: {stderr!r}"
    )


# ────────────────────────────────────────────────────────────────────
# R1 — system halt (IPC 미기동, JSON mode)
# ────────────────────────────────────────────────────────────────────


class TestSystemHaltJsonEnvelope:
    def test_system_halt_no_runtime_returns_ipc_envelope(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(
            config_dir,
            token,
            key,
            ["--format", "json", "system", "halt", "--reason", "test"],
        )

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "IPC_SERVER_NOT_RUNNING", payload
        # 사용자 친화 메시지가 그대로 envelope ``message`` 로 노출되어야 한다.
        assert "서버가 실행 중이 아닙니다" in payload.get("message", ""), payload


# ────────────────────────────────────────────────────────────────────
# R2 — treasury allocate (IPC 미기동, JSON mode)
# ────────────────────────────────────────────────────────────────────


class TestTreasuryAllocateJsonEnvelope:
    def test_treasury_allocate_no_runtime_returns_ipc_envelope(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        # account_id 는 ``ACCOUNT_ID_PATTERN``(^[a-zA-Z0-9\-]{3,30}$) 을 통과
        # 하는 합법 값을 사용해 ingress validation(``reject_invalid_account_id``)
        # 을 통과시켜야 ``ipc_send`` 로 진입한다(#1754 회귀 표적).
        result = _run_cli(
            config_dir,
            token,
            key,
            [
                "--format",
                "json",
                "treasury",
                "allocate",
                "bot-1",
                "1000",
                "--account",
                "acct-test-1",
            ],
        )

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "IPC_SERVER_NOT_RUNNING", payload
        assert "서버가 실행 중이 아닙니다" in payload.get("message", ""), payload


# ────────────────────────────────────────────────────────────────────
# R3 — approval cancel (IPC 미기동, JSON mode)
# ────────────────────────────────────────────────────────────────────


class TestApprovalCancelJsonEnvelope:
    def test_approval_cancel_no_runtime_returns_ipc_envelope(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(
            config_dir,
            token,
            key,
            ["--format", "json", "approval", "cancel", "missing-approval-id"],
        )

        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        _assert_no_traceback(result.stderr)

        payload = _parse_last_json_dict(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "IPC_SERVER_NOT_RUNNING", payload
        assert "서버가 실행 중이 아닙니다" in payload.get("message", ""), payload


# ────────────────────────────────────────────────────────────────────
# R4 — text mode sanity (회귀 보존)
# ────────────────────────────────────────────────────────────────────


class TestTextModeRegressionPreservation:
    """text 모드에서는 기존 click 동작 (stderr 한국어 메시지) 을 그대로 보존.

    middleware 의 ``ClickException`` catch 분기는 ``--format json`` 모드에서만
    발화한다 (``_sniff_output_format`` 가 json 이 아니면 ``super().main()`` 으로
    바로 위임). 본 테스트가 text 모드 출력 회귀를 잠근다.
    """

    def test_system_halt_no_runtime_text_mode_preserves_stderr(
        self, fresh_init: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = fresh_init
        result = _run_cli(
            config_dir,
            token,
            key,
            ["--format", "text", "system", "halt", "--reason", "test"],
        )

        # text 모드의 click 기본 ClickException 동작: exit 1 + stderr 메시지.
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        # 기존 사용자 메시지가 stderr 또는 stdout 어느 한쪽에는 그대로 노출되어야
        # 한다 (click 기본은 stderr; 회귀 보존 락).
        combined = result.stderr + result.stdout
        assert "서버가 실행 중이 아닙니다" in combined, (
            f"기존 사용자 메시지 누락: stderr={result.stderr!r}, "
            f"stdout={result.stdout!r}"
        )
        # text 모드 stdout 은 JSON envelope 으로 변환되지 **않아야** 한다.
        stdout_stripped = result.stdout.strip()
        if stdout_stripped.startswith("{"):
            try:
                obj = json.loads(stdout_stripped)
                # JSON 객체가 파싱된다면 ``status: error`` envelope 형태여서는 안
                # 된다 — text 모드 회귀.
                assert obj.get("status") != "error" or obj.get("code") != (
                    "IPC_SERVER_NOT_RUNNING"
                ), (
                    f"text 모드 stdout 이 JSON envelope 으로 변환되었습니다: "
                    f"{stdout_stripped!r}"
                )
            except json.JSONDecodeError:
                pass
