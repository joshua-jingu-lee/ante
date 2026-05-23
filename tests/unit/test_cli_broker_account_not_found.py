"""broker CLI valid-but-missing account_id contract 회귀 (#1727).

다음 R-case들을 잠근다 (이슈 본문 v2 Implementation Plan):

- R1 (balance): ``ante broker balance --account acc-9999`` →
  ``subprocess.run(timeout=5)`` 내 종료 + ``exit 1`` + JSON
  ``code="ACCOUNT_NOT_FOUND"``. 이전 동작은 빈 ``code`` 와 raw
  ``AccountNotFoundError`` 메시지였다.
- R2 (positions): ``ante broker positions --account acc-9999`` → 동일하게
  ``exit 1`` + ``code="ACCOUNT_NOT_FOUND"``.
- R3 sanity (balance, invalid ``default``): ``broker balance --account
  default`` → exit 1, ``code="VALIDATION_ERROR"`` (기존
  ``reject_invalid_account_id`` 동작 보존, #1635 Split B Layer 1).

SSOT: ``test_cli_rule_account_not_found.py`` (#1726) 의 격리 패턴을
byte-for-byte 복사한다. conftest fixture 격리: 모든 subprocess 호출에
명시 ``env={"PATH", "HOME", "ANTE_CONFIG_DIR", "PYTHONPATH"}`` 만 전달하고
``ANTE_DB_ENCRYPTION_KEY`` / ``ANTE_MEMBER_TOKEN`` 은 명시 인자로만 주입한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 5초 마진으로 차단한다. 정상 종료는 1-2초.
_SUBPROCESS_TIMEOUT_S = 5.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path, *, encryption_key: str | None = None, token: str | None = None
) -> dict[str, str]:
    """subprocess 환경 격리 헬퍼.

    부모 프로세스의 ``ANTE_DB_ENCRYPTION_KEY`` / ``ANTE_MEMBER_TOKEN`` 등이
    새는 것을 막기 위해 ``PATH`` / ``HOME`` / ``ANTE_CONFIG_DIR`` /
    ``PYTHONPATH`` 만 명시적으로 전달한다 (#1722/#1726 동형).
    """
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


@pytest.fixture
def initialized_config(tmp_path: Path) -> tuple[Path, str, str]:
    """ante init을 완료한 (config_dir, token, encryption_key) 튜플을 만든다.

    init은 ``create_default_test_account()`` 경로로 ``account_id='test'`` 시드
    계좌를 자동 생성한다. token/key는 후속 subprocess 호출에서
    인증/암복호화에 쓰인다.
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


def _run_broker_cli(
    config_dir: Path,
    token: str,
    encryption_key: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """broker CLI를 subprocess로 실행한다. timeout=5로 hang 회귀를 차단한다."""
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _parse_json_last(stdout: str) -> dict:
    """JSON dict payload를 stdout에서 추출한다.

    ``OutputFormatter.error`` 는 single-line JSON 한 줄로 dump하지만
    ``OutputFormatter.output`` 은 indent=2로 multi-line dump한다. 우선 전체
    stdout을 한 번에 ``json.loads`` 로 시도하고(success path), 실패하면
    라인별 스캔으로 마지막 dict 라인을 찾는다 (error path: single-line).
    """
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
    assert last_obj is not None, f"JSON dict 라인을 stdout에서 찾지 못함: {stdout!r}"
    return last_obj


# ────────────────────────────────────────────────────────────────────
# R1 — balance, valid-but-missing account → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestBrokerBalanceValidAbsentAccount:
    def test_balance_acc9999_reports_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R1: balance --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND.

        이전 동작은 generic ``except Exception`` 분기에서 ``fmt.error(str(e))``
        를 호출하여 ``code=""`` 의 빈 envelope를 반환했다. v2 plan은
        typed ``except AccountNotFoundError`` 를 generic 앞에 두어
        ``code="ACCOUNT_NOT_FOUND"`` 로 변환하도록 한다 (Pattern A SSOT
        from ``broker status``, #1726).
        """
        config_dir, token, key = initialized_config

        result = _run_broker_cli(
            config_dir,
            token,
            key,
            ["broker", "balance", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R2 — positions, valid-but-missing account → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestBrokerPositionsValidAbsentAccount:
    def test_positions_acc9999_reports_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R2: positions --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND."""
        config_dir, token, key = initialized_config

        result = _run_broker_cli(
            config_dir,
            token,
            key,
            ["broker", "positions", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R3 — sanity: invalid `default` → VALIDATION_ERROR (기존 동작 보존)
# ────────────────────────────────────────────────────────────────────


class TestBrokerBalanceInvalidDefaultAccount:
    def test_balance_default_account_exits_with_validation_error(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R3: broker balance --account default → exit 1, code=VALIDATION_ERROR.

        ``reject_invalid_account_id`` 가 ``default`` 예약어를 거부하는 기존
        동작이 본 PR로 깨지지 않는지 확인한다 (#1635 Split B Layer 1 보존).
        typed except 추가가 ingress validation 이후 단계이므로 이 분기는
        영향 받지 않아야 한다.
        """
        config_dir, token, key = initialized_config

        result = _run_broker_cli(
            config_dir,
            token,
            key,
            ["broker", "balance", "--account", "default"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "VALIDATION_ERROR", payload
