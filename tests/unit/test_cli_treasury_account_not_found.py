"""treasury CLI valid-but-missing account_id contract 회귀 (#1725).

다음 5개 회귀를 잠근다 (이슈 본문 v2 Implementation Plan):

- R1 hang 회귀 (status): ``ante treasury status --account acc-9999`` →
  ``subprocess.run(timeout=5)`` 내 종료 + ``exit 1`` + JSON
  ``code="ACCOUNT_NOT_FOUND"``.
- R2 hang 회귀 (snapshot): ``ante treasury snapshot --account acc-9999`` →
  동일.
- R3 cleanup 회귀: in-process unit test로 ``account_service.get`` 이
  raise할 때 ``Database.close`` 가 1회 await된다. 내부 필드 (``_writer`` /
  ``_reader``) 직접 접근 금지 — public lifecycle ``Database.close`` 호출 사실로
  검증 (#1722 R3 동형).
- R4 sanity (status, valid existing): ``--account test`` → exit 0, status
  payload. ``test`` 계좌는 ``ante init``이 ``create_default_test_account()``
  로 자동 생성한다 (``scoping.py:36`` "test는 ante init 경로 전용 예약어").
- R5 sanity (status, invalid `default`): ``--account default`` → exit 1,
  ``code="VALIDATION_ERROR"`` (기존 ``reject_invalid_account_id`` 동작 보존).

conftest fixture 격리: 모든 subprocess 호출에 명시 ``env={"PATH": ...,
"HOME": ..., "ANTE_CONFIG_DIR": ..., "PYTHONPATH": ...}`` 만 전달한다.
``ANTE_DB_ENCRYPTION_KEY`` 와 ``ANTE_MEMBER_TOKEN`` 은 명시 인자로만 주입한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
    ``PYTHONPATH`` 만 명시적으로 전달한다 (#1722 ``test_cli_account_crypto_error``
    동형).
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
    계좌를 자동 생성한다 (``scoping.py:36`` 참조). R4 sanity가 이 시드 계좌를
    재사용한다. token/key는 후속 subprocess 호출에서 인증/암복호화에 쓰인다.
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
    ``OutputFormatter.output`` 은 indent=2로 multi-line dump한다. 우선 전체
    stdout을 한 번에 ``json.loads`` 로 시도하고(success path), 실패하면 라인별
    스캔으로 마지막 dict 라인을 찾는다 (error path: single-line).
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
# R1 / R2 — hang 회귀 + stable ACCOUNT_NOT_FOUND code (status/snapshot)
# ────────────────────────────────────────────────────────────────────


class TestTreasuryStatusValidAbsentAccount:
    def test_status_acc9999_exits_with_account_not_found_no_hang(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R1: status --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND, no hang."""
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "status", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


class TestTreasurySnapshotValidAbsentAccount:
    def test_snapshot_acc9999_exits_with_account_not_found_no_hang(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R2: snapshot --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND, no hang."""
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "snapshot", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R3 — cleanup 회귀 (in-process, Database.close spy)
# ────────────────────────────────────────────────────────────────────


class TestCreateTreasuryCleanup:
    @pytest.mark.asyncio
    async def test_account_not_found_calls_db_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``account_service.get`` 가 raise하면 ``Database.close`` 1회 await.

        내부 필드(``_writer`` / ``_reader``)는 들여다보지 않고 public lifecycle
        method ``Database.close`` 호출 사실로 검증한다 (#1722 R3 동형,
        ``test_cli_account_crypto_error.py:204`` 참조).
        """
        from ante.account.errors import AccountNotFoundError
        from ante.account.service import AccountService
        from ante.cli.commands.treasury import _create_treasury
        from ante.core.database import Database

        # get_db_path는 ctx-less 경로에서 ANTE_CONFIG_DIR 기반으로 해석된다.
        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
        # valid Fernet key를 env에 두어 db.connect까지는 통과시킨다.
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

        # AccountService.initialize는 통과시키고, AccountService.get에서
        # AccountNotFoundError를 raise해 _create_treasury의 cleanup 경로를 친다.
        async def passing_initialize(self: AccountService) -> None:
            return None

        async def raising_get(self: AccountService, account_id: str) -> object:
            raise AccountNotFoundError(f"계좌를 찾을 수 없습니다: {account_id}")

        # Database.close 를 AsyncMock으로 주입하고 await_count == 1로 검증한다.
        # cleanup 호출 사실만 검증하면 충분하므로 실제 close 본체는 위임하지
        # 않는다 (process 종료 시 임시 자원은 OS가 회수).
        #
        # #1857: ``_create_treasury`` 는 async context manager 로 변환됨.
        # ``async with`` 진입 시점에 ``AccountService.get`` raise 가 발생해야
        # ``open_cli_db`` 의 ``except BaseException`` cleanup 이 ``db.close()``
        # 를 호출한다. ctx 없이 호출하기 위해 click context 를 만든다.
        import click

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            monkeypatch.setattr(AccountService, "initialize", passing_initialize)
            monkeypatch.setattr(AccountService, "get", raising_get)

            with pytest.raises(AccountNotFoundError):
                ctx = click.Context(click.Command("dummy"))
                async with _create_treasury("acc-9999", ctx=ctx):
                    pass

        assert close_mock.await_count == 1, (
            f"Database.close 가 정확히 1회 await되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# R4 — sanity: valid existing `test` 계좌는 exit 0 + status payload
# ────────────────────────────────────────────────────────────────────


class TestTreasuryStatusValidExistingAccount:
    def test_status_test_account_exits_with_status_payload(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R4: status --account test → exit 0, status payload.

        ``test`` 계좌는 ``ante init`` 이 ``create_default_test_account()`` 경로로
        자동 생성한다 (``scoping.py:36`` "test는 ante init 경로 전용 예약어").
        """
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "status", "--account", "test"],
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        # status payload는 fmt.output(dict)으로 dump되므로 envelope 없이 핵심
        # 필드가 노출된다 (`account_balance` 등). 회귀의 sanity 보장만 하면
        # 충분하므로 dict 키 존재만 확인한다.
        assert "account_balance" in payload, payload


# ────────────────────────────────────────────────────────────────────
# R5 — sanity: invalid `default` → VALIDATION_ERROR (기존 동작 보존)
# ────────────────────────────────────────────────────────────────────


class TestTreasuryStatusInvalidDefaultAccount:
    def test_status_default_account_exits_with_validation_error(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R5: status --account default → exit 1, code=VALIDATION_ERROR.

        ``reject_invalid_account_id`` 가 ``default`` 예약어를 거부하는 기존 동작이
        본 PR로 깨지지 않는지 확인한다 (#1635 Split B Layer 1).
        """
        config_dir, token, key = initialized_config

        result = _run_treasury_cli(
            config_dir,
            token,
            key,
            ["treasury", "status", "--account", "default"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "VALIDATION_ERROR", payload
