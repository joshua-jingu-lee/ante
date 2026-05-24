"""treasury read 계열 CLI valid-but-missing account_id 회귀 (#1758).

#1725 follow-up sweep. status/snapshot이 #1725로 typed
``except AccountNotFoundError → code="ACCOUNT_NOT_FOUND"`` 매핑을 받은 것과
동형으로, 나머지 4개 명령(`budgets`, `portfolio value`, `portfolio history`,
`set-balance`)에도 같은 매핑을 적용한다.

ante-oracle host probe ``cli_treasury_valid_absent_read_followup_contract`` 가
signature ``treasury_budgets_valid_absent`` /
``treasury_portfolio_value_valid_absent`` /
``treasury_portfolio_history_valid_absent`` 로 잡은 contract-drift를 잠근다.

회귀:

- R1 (budgets): ``ante treasury budgets --account acc-9999`` →
  ``exit 1`` + JSON ``code="ACCOUNT_NOT_FOUND"``.
- R2 (portfolio value): ``ante treasury portfolio value --account acc-9999`` →
  동일.
- R3 (portfolio history): ``ante treasury portfolio history --account acc-9999``
  → 동일.
- R4 (set-balance): ``ante treasury set-balance acc-9999 100`` → 동일.
  (요청 본문 작업 #2, ``treasury.py:337-356`` 호출 표면이 이미 generic except
  를 가지고 있어 typed ``AccountNotFoundError`` 를 분기에 추가했다.)
- R5 sanity (valid existing `test` 계좌): 위 4개 명령 모두 ``exit 0`` +
  정상 payload (#1725 와 동형 sanity 회귀 보존).

conftest fixture 격리는 ``test_cli_treasury_account_not_found.py`` (#1725) 와
동형이다 (명시 ``env`` allowlist, ``ANTE_DB_ENCRYPTION_KEY`` /
``ANTE_MEMBER_TOKEN`` 누출 차단).
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
    ``PYTHONPATH`` 만 명시적으로 전달한다 (#1722 / #1725 동형).
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
    계좌를 자동 생성한다 (``scoping.py:36`` 참조). R5 sanity가 이 시드 계좌를
    재사용한다.
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


def _run_treasury_cli(
    config_dir: Path,
    token: str,
    encryption_key: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """treasury CLI를 subprocess로 실행한다. timeout=5로 hang 회귀를 차단한다."""
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
    ``OutputFormatter.output`` 은 indent=2로 multi-line dump한다. 전체 stdout을
    먼저 한 번에 ``json.loads`` 로 시도하고, 실패하면 라인별로 마지막 dict
    라인을 찾는다 (#1725 동형).
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
# R1 — budgets valid-but-missing → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestTreasuryBudgetsValidAbsentAccount:
    def test_budgets_acc9999_exits_with_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R1: budgets --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND."""
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "budgets", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R2 — portfolio value valid-but-missing → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestTreasuryPortfolioValueValidAbsentAccount:
    def test_portfolio_value_acc9999_exits_with_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R2: portfolio value --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND."""
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "portfolio", "value", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R3 — portfolio history valid-but-missing → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestTreasuryPortfolioHistoryValidAbsentAccount:
    def test_portfolio_history_acc9999_exits_with_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R3: portfolio history --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND."""
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "portfolio", "history", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R4 — set-balance valid-but-missing → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestTreasurySetBalanceValidAbsentAccount:
    def test_set_balance_acc9999_exits_with_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R4: set-balance acc-9999 100 → exit 1, code=ACCOUNT_NOT_FOUND.

        cold-path (``is_active_runtime() == False``) 분기에서
        ``_create_treasury`` 가 ``AccountNotFoundError`` 를 raise한다. typed
        매핑이 없으면 generic ``Exception`` fallback이 ``TREASURY_ERROR`` 로
        새 contract-drift가 발생하므로 typed 분기를 친다.
        """
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "set-balance", "100", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R5 — sanity: valid existing `test` 계좌는 모든 4개 명령에서 정상 동작
# ────────────────────────────────────────────────────────────────────


class TestTreasuryReadValidExistingAccountSanity:
    """valid 계좌(`test`) 회귀 보존 — 본 PR이 정상 경로를 깨지 않는지 확인.

    ``test`` 계좌는 ``ante init`` 이 ``create_default_test_account()`` 로
    자동 생성한다 (#1725 R4 동형).
    """

    def test_budgets_test_account_exits_ok(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "budgets", "--account", "test"],
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert "budgets" in payload, payload

    def test_portfolio_value_test_account_exits_ok(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "portfolio", "value", "--account", "test"],
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert "total_value" in payload, payload

    def test_portfolio_history_test_account_exits_ok(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "portfolio", "history", "--account", "test"],
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert "data" in payload, payload

    def test_set_balance_test_account_exits_ok(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "set-balance", "100000", "--account", "test"],
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("account_id") == "test", payload
