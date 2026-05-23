"""account CLI crypto 에러 contract 회귀 (#1722).

다음 6개 회귀를 잠근다:

- R1 hang 회귀: ``ante account list`` (env clean + secrets.env 키 라인 삭제) →
  ``subprocess.run(timeout=5)`` 내 종료 + ``exit 1`` + JSON
  ``code="DB_ENCRYPTION_KEY_MISSING"``.
- R2 stable code 회귀: JSON ``code`` 필드 검증.
- R3 cleanup 회귀: in-process unit test로 ``AccountService.initialize`` 가
  raise할 때 ``Database.close`` 가 1회 await된다. 내부 필드 (``_writer`` /
  ``_reader``) 직접 접근 금지 — public lifecycle ``Database.close`` 호출 사실로
  검증 (Codex Plan v2 narrow-to 1).
- R4 7-command 일관성: ``account create/list/info/delete/credentials/
  set-credentials/repair-timezone`` 모두 동일 시나리오에서 같은 ``code`` +
  ``exit 1`` + ``timeout=5`` 내 종료.
- R5 invalid key 코드: env에 garbage value → ``code="DB_ENCRYPTION_KEY_INVALID"``.
- R6 wrong key decrypt 코드: legacy DB row가 키 A로 암호화 + 현재 env에 키 B →
  ``code="DB_ENCRYPTION_KEY_INVALID"``.

conftest fixture 격리: 모든 subprocess 호출에 명시 ``env={"PATH": ...,
"HOME": ..., "ANTE_CONFIG_DIR": ...}``만 전달한다. ``ANTE_DB_ENCRYPTION_KEY`` 는
의도적으로 제외 (R5/R6 한정으로 garbage/wrong value 명시 포함).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 5초 마진으로 차단한다. 정상 종료는 1-2초.
_SUBPROCESS_TIMEOUT_S = 5.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path, *, encryption_key: str | None = None, token: str | None = None
) -> dict[str, str]:
    """subprocess 환경 격리 헬퍼 (Codex Plan v2 must-fix 4).

    Conftest fixture 격리 원칙: 부모 프로세스의 ``ANTE_DB_ENCRYPTION_KEY`` /
    ``ANTE_MEMBER_TOKEN`` 등이 새는 것을 막기 위해 ``PATH`` / ``HOME`` /
    ``ANTE_CONFIG_DIR`` 만 명시적으로 전달한다. ``PYTHONPATH`` 는 src 트리에서
    ``-m ante`` 가 import 되도록 추가한다. ``ANTE_DB_ENCRYPTION_KEY`` 는
    의도적으로 제외 (R5/R6 한정으로 ``encryption_key`` 인자로 명시 주입).
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


def _strip_encryption_key_line(secrets_env_path: Path) -> None:
    """secrets.env에서 ANTE_DB_ENCRYPTION_KEY 라인을 제거한다 (R1 재현)."""
    if not secrets_env_path.exists():
        return
    lines = secrets_env_path.read_text().splitlines(keepends=True)
    prefix = "ANTE_DB_ENCRYPTION_KEY="
    kept = [line for line in lines if not line.lstrip().startswith(prefix)]
    secrets_env_path.write_text("".join(kept))


@pytest.fixture
def initialized_config(tmp_path: Path) -> tuple[Path, str]:
    """ante init을 완료한 config dir + member token 페어를 만든다.

    `ante init` 의 결과 JSON에서 ``token`` 을 추출해 R1~R6 회귀에 재사용한다.
    init 자체는 valid Fernet key로 정상 종료해야 하며, R1 재현은 호출자가
    ``_strip_encryption_key_line`` 으로 secrets.env 라인을 삭제한 뒤
    ``ANTE_DB_ENCRYPTION_KEY`` 를 env에서도 제외하여 키가 양쪽에 없는 상태를
    만든다.
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
    return config_dir, token


def _run_account_cli(
    config_dir: Path,
    token: str,
    args: list[str],
    *,
    encryption_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """account CLI를 subprocess로 실행한다. timeout=5로 hang 회귀를 차단한다."""
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _parse_json_error(stdout: str) -> dict:
    """JSON error payload 를 stdout 마지막 dict 라인에서 추출한다."""
    # OutputFormatter.error 는 JSON 모드에서 한 줄로 dump 한다. 부가 출력이
    # 있을 수 있으므로 마지막 JSON dict 라인을 찾는다.
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
# R1 / R2 — hang 회귀 + stable code (account list, missing key)
# ────────────────────────────────────────────────────────────────────


class TestAccountListMissingKeyNoHang:
    def test_account_list_missing_key_exits_with_stable_code(
        self, initialized_config: tuple[Path, str]
    ) -> None:
        """secrets.env 키 삭제 + env 미설정 → exit 1, code=MISSING, timeout 미발생."""
        config_dir, token = initialized_config
        _strip_encryption_key_line(config_dir / "secrets.env")

        result = _run_account_cli(config_dir, token, ["account", "list"])
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_error(result.stdout)
        assert payload.get("status") == "error"
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING"


# ────────────────────────────────────────────────────────────────────
# R3 — cleanup 회귀 (in-process, Database.close spy)
# ────────────────────────────────────────────────────────────────────


class TestCreateAccountServiceCleanup:
    @pytest.mark.asyncio
    async def test_initialize_failure_calls_db_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``AccountService.initialize`` 가 raise하면 ``Database.close`` 1회 await.

        내부 필드(``_writer`` / ``_reader``)는 들여다보지 않고 public lifecycle
        method ``Database.close`` 호출 사실로 검증한다 (Codex Plan v2 narrow-to 1).
        """
        from ante.account.crypto import EncryptionKeyMissingError
        from ante.cli.commands.account import _create_account_service
        from ante.core.database import Database

        # get_db_path는 ctx-less 경로에서 ANTE_CONFIG_DIR 기반으로 해석된다.
        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
        # valid Fernet key를 env에 두어 db.connect까지는 통과시킨다.
        # initialize 단계에서 명시 mock으로 raise.
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

        original_close = Database.close
        close_call_count = {"count": 0}

        async def spy_close(self: Database) -> None:
            close_call_count["count"] += 1
            await original_close(self)

        # AccountService.initialize를 raise하도록 monkeypatch
        from ante.account.service import AccountService

        async def raising_initialize(self: AccountService) -> None:
            raise EncryptionKeyMissingError(
                "테스트: initialize 도중 키 누락 시뮬레이션"
            )

        with patch.object(Database, "close", spy_close):
            monkeypatch.setattr(AccountService, "initialize", raising_initialize)

            with pytest.raises(EncryptionKeyMissingError):
                await _create_account_service()

        count = close_call_count["count"]
        assert count == 1, (
            f"Database.close 가 정확히 1회 await되어야 한다 (count={count})"
        )


# ────────────────────────────────────────────────────────────────────
# R4 — 7-command 일관성 회귀
# ────────────────────────────────────────────────────────────────────


# 7개 account 명령의 (args, code) 매트릭스. 모든 명령은 ``_create_account_service`` 를
# 통해 DB+initialize 진입하므로, 키가 없으면 동일하게 DB_ENCRYPTION_KEY_MISSING 으로
# 종료한다. 일부 명령은 ``_create_account_service`` 진입 전 별도 가드(예:
# cold-path runtime, --yes confirmation)를 먼저 실행한다. 가드를 만족시키지 못하면
# 다른 코드로 종료하므로, R4 매트릭스는 가드를 모두 통과하는 시나리오 인자를 쓴다.
_ACCOUNT_COMMANDS_FOR_R4: list[tuple[str, list[str]]] = [
    (
        "create",
        [
            "account",
            "create",
            "--broker-type",
            "test",
            "--account-id",
            "acc1",
            "--name",
            "A",
            "--trading-mode",
            "virtual",
            "--credential",
            "app_key=k",
            "--credential",
            "app_secret=s",
        ],
    ),
    ("list", ["account", "list"]),
    ("info", ["account", "info", "test"]),
    ("delete", ["account", "delete", "test", "--yes"]),
    ("credentials", ["account", "credentials", "test"]),
    (
        "set-credentials",
        [
            "account",
            "set-credentials",
            "test",
            "--credential",
            "app_key=k",
            "--credential",
            "app_secret=s",
        ],
    ),
    ("repair-timezone", ["account", "repair-timezone", "test", "Asia/Seoul"]),
]


class TestSevenCommandConsistency:
    @pytest.mark.parametrize(
        ("name", "args"),
        _ACCOUNT_COMMANDS_FOR_R4,
        ids=[name for name, _ in _ACCOUNT_COMMANDS_FOR_R4],
    )
    def test_missing_key_consistent_code_no_hang(
        self,
        initialized_config: tuple[Path, str],
        name: str,
        args: list[str],
    ) -> None:
        """7개 account 명령 모두 동일 missing-key 시나리오에서 같은 코드 + exit 1."""
        config_dir, token = initialized_config
        _strip_encryption_key_line(config_dir / "secrets.env")

        result = _run_account_cli(config_dir, token, args)
        assert result.returncode == 1, (
            f"[{name}] exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_error(result.stdout)
        assert payload.get("code") == "DB_ENCRYPTION_KEY_MISSING", (
            f"[{name}] 예상 code=DB_ENCRYPTION_KEY_MISSING, 실제 payload={payload}"
        )


# ────────────────────────────────────────────────────────────────────
# R5 — invalid key 형식 회귀
# ────────────────────────────────────────────────────────────────────


class TestInvalidKeyFormat:
    def test_invalid_key_format_returns_invalid_code(
        self, initialized_config: tuple[Path, str]
    ) -> None:
        """env에 garbage value → exit 1, code=DB_ENCRYPTION_KEY_INVALID."""
        config_dir, token = initialized_config
        _strip_encryption_key_line(config_dir / "secrets.env")

        result = _run_account_cli(
            config_dir, token, ["account", "list"], encryption_key="garbage"
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_error(result.stdout)
        assert payload.get("code") == "DB_ENCRYPTION_KEY_INVALID"


# ────────────────────────────────────────────────────────────────────
# R6 — wrong key decrypt 회귀
# ────────────────────────────────────────────────────────────────────


class TestWrongKeyDecrypt:
    def test_wrong_key_decrypt_returns_invalid_code(
        self, initialized_config: tuple[Path, str]
    ) -> None:
        """legacy DB는 키 A로 암호화 + 현재 env에 valid 키 B → exit 1, code=INVALID.

        init은 키 A로 ``test`` seed 계좌를 encrypt해 두었다. secrets.env 라인을
        삭제하고 env에 다른 valid Fernet key (B)를 주입하면 initialize 중
        ``_row_to_account`` 가 ``decrypt_credentials`` 를 호출해
        ``InvalidToken`` → ``EncryptionKeyInvalidError`` 로 매핑된다.
        """
        config_dir, token = initialized_config
        _strip_encryption_key_line(config_dir / "secrets.env")

        wrong_key = Fernet.generate_key().decode()
        result = _run_account_cli(
            config_dir, token, ["account", "list"], encryption_key=wrong_key
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_error(result.stdout)
        assert payload.get("code") == "DB_ENCRYPTION_KEY_INVALID"
