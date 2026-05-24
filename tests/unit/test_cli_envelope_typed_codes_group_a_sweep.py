"""CLI/IPC envelope typed-code Group A sweep (#1784, #1789, #1795-#1798, #1800).

7 oracle A7 이슈 sweep — typed exception code 보존 + CLI ``fmt.error`` code
명시 + strategy submit envelope 정합. CLI 표면이 다음 카테고리로 갈린다:

- **cold-path subprocess 검증 가능**: bot info / bot signal-key (cold-path),
  instrument import (no DB), strategy submit (no DB) — ``ante`` CLI 를
  실제 subprocess 로 실행해 ``--format json`` 출력의 ``code`` 필드를
  검증한다.
- **IPC 전용 (server 필요)**: account suspend/activate, bot create,
  approval cancel-invalid, strategy set-status (active runtime branch),
  member update-scopes (active runtime branch) — server fixture 없이는
  ``IPC_SERVER_NOT_RUNNING`` 만 받기 때문에, 본 sweep 은 typed exception
  class 의 ``code`` 속성을 직접 verify 하고 IPC server.py 의
  ``getattr(e, "code", "EXECUTION_ERROR")`` envelope 매핑 invariant 가
  보존되는지 확인한다 (registry handler 가 typed exception 을 raise
  하면 envelope 코드가 자동으로 surface 된다).

R-case 매핑:
  R1 #1795 ``AccountNotFoundError.code = "ACCOUNT_NOT_FOUND"`` 보존
  R2 #1796 ``StrategyNotFoundError.code = "STRATEGY_NOT_FOUND"`` +
         ``StrategyRegistry.update_status`` 가 typed exception raise
  R3 #1797 ``InvalidScopeError.code = "MEMBER_INVALID_SCOPE"`` 보존
  R4 #1798 ``ApprovalNotFoundError.code = "APPROVAL_NOT_FOUND"`` +
         ``ApprovalService.cancel_invalid_type_request`` typed raise
  R5 #1800 ``BotAlreadyExistsError.code = "BOT_ALREADY_EXISTS"`` +
         ``BotManager.create_bot`` 가 duplicate id 시 typed raise
  R6 #1784 ``bot info <missing>`` → ``code="BOT_NOT_FOUND"`` (subprocess)
  R7 #1784 ``bot signal-key <missing>`` → ``code="BOT_NOT_FOUND"`` (subprocess)
  R8 #1784 ``bot create --param invalid`` → ``code="BOT_INVALID_PARAM"``
         (subprocess, param 파싱은 IPC 이전 단계)
  R9 #1784 ``instrument import <csv_missing_cols>`` →
         ``code="INSTRUMENT_MISSING_COLUMNS"`` (subprocess)
  R10 #1784 ``instrument import <directory>`` →
         ``code="INSTRUMENT_IO_ERROR"`` (subprocess)
  R11 #1789 ``strategy submit <invalid>`` envelope 에 ``code`` 필드 추가
         (subprocess)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_SUBPROCESS_TIMEOUT_S = 10.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path,
    *,
    encryption_key: str | None = None,
    token: str | None = None,
) -> dict[str, str]:
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


def _run_cli(
    config_dir: Path,
    args: list[str],
    *,
    token: str | None = None,
    encryption_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _run_init(config_dir: Path, encryption_key: str) -> tuple[str, str]:
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
            "GroupASweep",
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
    """``ante init`` 완료 (config_dir, token, encryption_key)."""
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()
    token, _ = _run_init(config_dir, key)
    return config_dir, token, key


# ════════════════════════════════════════════════════════════════════
# 카테고리 1 — typed exception class ``code`` 속성 보존 (IPC envelope
# 매핑 invariant). IPC 전용 표면은 server fixture 없이 envelope 을
# subprocess 로 재현할 수 없으므로 typed exception 의 class-level
# ``code`` 가 SCREAMING_SNAKE_CASE 안정 값을 갖는지 직접 verify 한다.
# IPC ``server.py:_dispatch`` 가 ``getattr(e, "code", "EXECUTION_ERROR")``
# 로 envelope 코드를 매핑하므로 (registry handler 가 해당 typed
# exception 을 raise 하기만 하면) envelope 에 자동 surface 된다.
# ════════════════════════════════════════════════════════════════════


class TestTypedExceptionCodeAttributes:
    """R1-R5: typed exception class ``code`` 속성 매핑 lock."""

    def test_r1_account_not_found_error_code_is_account_not_found(self) -> None:
        """#1795: ``AccountNotFoundError.code = "ACCOUNT_NOT_FOUND"``."""
        from ante.account.errors import AccountNotFoundError

        assert AccountNotFoundError.code == "ACCOUNT_NOT_FOUND"
        # 인스턴스에서도 동일 코드가 surface 되어 IPC envelope 의
        # ``getattr(e, "code", ...)`` 가 안정적으로 작동한다.
        exc = AccountNotFoundError("계좌 없음: foo")
        assert getattr(exc, "code", None) == "ACCOUNT_NOT_FOUND"

    def test_r2_strategy_not_found_error_code_is_strategy_not_found(self) -> None:
        """#1796: ``StrategyNotFoundError.code = "STRATEGY_NOT_FOUND"``."""
        from ante.strategy.exceptions import StrategyError, StrategyNotFoundError

        assert StrategyNotFoundError.code == "STRATEGY_NOT_FOUND"
        # StrategyError 상속 보존 — 기존 ``except StrategyError`` 핸들러
        # 회귀 없음.
        assert issubclass(StrategyNotFoundError, StrategyError)
        exc = StrategyNotFoundError("Strategy not found: foo")
        assert getattr(exc, "code", None) == "STRATEGY_NOT_FOUND"

    def test_r3_invalid_scope_error_code_is_member_invalid_scope(self) -> None:
        """#1797: ``InvalidScopeError.code = "MEMBER_INVALID_SCOPE"``."""
        from ante.member.scopes import InvalidScopeError

        assert InvalidScopeError.code == "MEMBER_INVALID_SCOPE"
        # ``ValueError`` 상속 보존 — 기존 ``except ValueError`` 핸들러 회귀
        # 없음.
        assert issubclass(InvalidScopeError, ValueError)
        exc = InvalidScopeError("invalid:scope")
        assert getattr(exc, "code", None) == "MEMBER_INVALID_SCOPE"

    def test_r4_approval_not_found_error_code_is_approval_not_found(self) -> None:
        """#1798: ``ApprovalNotFoundError.code = "APPROVAL_NOT_FOUND"``."""
        from ante.approval.errors import ApprovalError, ApprovalNotFoundError

        assert ApprovalNotFoundError.code == "APPROVAL_NOT_FOUND"
        assert issubclass(ApprovalNotFoundError, ApprovalError)
        exc = ApprovalNotFoundError("appr-missing")
        assert getattr(exc, "code", None) == "APPROVAL_NOT_FOUND"

    def test_r5a_bot_already_exists_error_code(self) -> None:
        """#1800: ``BotAlreadyExistsError.code = "BOT_ALREADY_EXISTS"``."""
        from ante.bot.exceptions import (
            BOT_ALREADY_EXISTS_CODE,
            BotAlreadyExistsError,
            BotError,
        )

        assert BOT_ALREADY_EXISTS_CODE == "BOT_ALREADY_EXISTS"
        assert BotAlreadyExistsError.code == "BOT_ALREADY_EXISTS"
        assert issubclass(BotAlreadyExistsError, BotError)
        exc = BotAlreadyExistsError("Bot already exists: foo")
        assert getattr(exc, "code", None) == "BOT_ALREADY_EXISTS"

    def test_r5b_bot_strategy_already_running_error_code(self) -> None:
        """#1800: ``BotStrategyAlreadyRunningError`` code ==
        ``"BOT_STRATEGY_ALREADY_RUNNING"``.
        """
        from ante.bot.exceptions import (
            BOT_STRATEGY_ALREADY_RUNNING_CODE,
            BotError,
            BotStrategyAlreadyRunningError,
        )

        assert BOT_STRATEGY_ALREADY_RUNNING_CODE == "BOT_STRATEGY_ALREADY_RUNNING"
        assert BotStrategyAlreadyRunningError.code == "BOT_STRATEGY_ALREADY_RUNNING"
        assert issubclass(BotStrategyAlreadyRunningError, BotError)


# ════════════════════════════════════════════════════════════════════
# 카테고리 2 — service-layer typed raise 검증. CLI/IPC 표면이 typed
# 코드를 surface 하려면 service 가 typed exception 을 raise 해야 한다.
# 본 fixture-light 단위 테스트는 직접 service 를 호출해 raise type
# 회귀를 막는다.
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestServiceLayerTypedRaise:
    """service-layer 가 missing resource 를 typed exception 으로 raise."""

    async def test_r2_strategy_registry_update_status_raises_typed_not_found(
        self, tmp_path: Path
    ) -> None:
        """#1796: ``StrategyRegistry.update_status(missing)`` →
        ``StrategyNotFoundError`` (code ``"STRATEGY_NOT_FOUND"``).
        """
        from ante.core.database import Database
        from ante.strategy.exceptions import StrategyNotFoundError
        from ante.strategy.registry import StrategyRegistry, StrategyStatus

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        await db.connect()
        try:
            registry = StrategyRegistry(db)
            await registry.initialize()

            with pytest.raises(StrategyNotFoundError) as excinfo:
                await registry.update_status(
                    "missing-strategy-id", StrategyStatus.ADOPTED
                )
            assert getattr(excinfo.value, "code", None) == "STRATEGY_NOT_FOUND"
        finally:
            await db.close()

    async def test_r4_approval_service_cancel_invalid_raises_typed_not_found(
        self, tmp_path: Path
    ) -> None:
        """#1798: ``ApprovalService.cancel_invalid_type_request(missing)`` →
        ``ApprovalNotFoundError`` (code ``"APPROVAL_NOT_FOUND"``).
        """
        from ante.approval.errors import ApprovalNotFoundError
        from ante.approval.service import ApprovalService
        from ante.core.database import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        await db.connect()
        try:
            service = ApprovalService(db, eventbus=None)
            await service.initialize()

            with pytest.raises(ApprovalNotFoundError) as excinfo:
                await service.cancel_invalid_type_request(
                    "appr-missing",
                    resolved_by="admin",
                )
            assert getattr(excinfo.value, "code", None) == "APPROVAL_NOT_FOUND"
        finally:
            await db.close()


# ════════════════════════════════════════════════════════════════════
# 카테고리 3 — subprocess CLI envelope 검증 (#1784 + #1789).
# ════════════════════════════════════════════════════════════════════


class TestBotInfoMissingCodeContract:
    """R6 #1784: ``bot info <missing>`` → exit 1, code=BOT_NOT_FOUND."""

    def test_bot_info_missing_emits_bot_not_found_code(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["bot", "info", "oracle-missing-bot"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "BOT_NOT_FOUND", payload


class TestBotSignalKeyMissingCodeContract:
    """R7 #1784: ``bot signal-key <missing>`` → exit 1, code=BOT_NOT_FOUND."""

    def test_bot_signal_key_missing_emits_bot_not_found_code(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["bot", "signal-key", "oracle-missing-bot"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "BOT_NOT_FOUND", payload


class TestBotCreateInvalidParamCodeContract:
    """R8 #1784: ``bot create --param invalid`` → exit 1, code=BOT_INVALID_PARAM.

    param 파싱은 IPC 이전 단계라 server 없이도 reproducer 가 된다.
    """

    def test_bot_create_invalid_param_emits_bot_invalid_param_code(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            [
                "bot",
                "create",
                "--strategy",
                "any-strategy",
                "--name",
                "oracle-test",
                "--param",
                "not_key_value",  # = 미포함 → BadParameter
            ],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "BOT_INVALID_PARAM", payload


class TestInstrumentImportMissingColumnsCodeContract:
    """R9 #1784: ``instrument import <csv_missing_symbol_exchange>`` →
    exit 1, code=INSTRUMENT_MISSING_COLUMNS.
    """

    def test_instrument_import_missing_columns_emits_missing_columns_code(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        config_dir, token, key = initialized_config
        bad_csv = tmp_path / "missing-cols.csv"
        bad_csv.write_text(
            "ticker,price\nFOO,100\nBAR,200\n",
            encoding="utf-8",
        )
        result = _run_cli(
            config_dir,
            ["instrument", "import", str(bad_csv), "--dry-run"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "INSTRUMENT_MISSING_COLUMNS", payload


class TestInstrumentImportDirectoryCodeContract:
    """R10 #1784: ``instrument import <directory_with_csv_suffix>`` →
    exit 1, code=INSTRUMENT_IO_ERROR.
    """

    def test_instrument_import_directory_emits_io_error_code(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        config_dir, token, key = initialized_config
        # ``.csv`` suffix 를 가진 디렉토리: 파일 형식 분기는 통과하지만
        # ``open(...)`` 에서 IsADirectoryError raise → ``INSTRUMENT_IO_ERROR``.
        bad_dir = tmp_path / "instrument-dir.csv"
        bad_dir.mkdir()
        result = _run_cli(
            config_dir,
            ["instrument", "import", str(bad_dir), "--dry-run"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "INSTRUMENT_IO_ERROR", payload


class TestStrategySubmitEnvelopeCodeField:
    """R11 #1789: ``strategy submit`` validation/load failure envelope 에
    ``code`` 필드가 추가되어 자동화가 분류할 수 있다.
    """

    def test_strategy_submit_validation_failure_envelope_has_code(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        config_dir, token, key = initialized_config
        # 정적 검증 실패: 전략 파일이 ``Strategy`` 클래스를 정의하지 않음.
        bad_py = tmp_path / "invalid_strategy.py"
        bad_py.write_text(
            "# 전략 클래스가 없는 빈 파이썬 파일\n",
            encoding="utf-8",
        )
        result = _run_cli(
            config_dir,
            ["strategy", "submit", str(bad_py)],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        # validate 또는 load 단계에서 실패할 수 있으므로 둘 다 허용.
        assert payload.get("submitted") is False, payload
        stage = payload.get("stage")
        assert stage in {"validate", "load"}, payload
        # #1789 invariant: envelope 에 typed ``code`` 가 존재해야 함.
        code = payload.get("code")
        assert code in {
            "STRATEGY_VALIDATION_ERROR",
            "STRATEGY_LOAD_ERROR",
        }, payload
