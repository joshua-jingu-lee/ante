"""CLI 에러코드 명명 규칙 sweep (#1773-#1782).

10 개 oracle A7 이슈 동일 패턴 (CLI 에러코드 명명 위반) sweep을 잠근다.

- 3 lower-case → SCREAMING_SNAKE (#1773 / #1774 / #1775)
- 7 missing → 도메인 prefix SCREAMING_SNAKE 추가 (#1776-#1782)

각 R-case는 subprocess로 ante CLI를 실행하고 ``--format json`` 출력에서
``code`` 필드가 expected SCREAMING_SNAKE 값과 정확히 일치하는지 확인한다.

R-case 매핑:
  R1 #1773 ``ante init`` 2회 → ``CLI_ALREADY_INITIALIZED``
  R2 #1774 ``ante report view <missing>`` → ``REPORT_NOT_FOUND``
  R3 #1775 ``ante treasury snapshot --account test --date 1999-01-01``
         → ``SNAPSHOT_NOT_FOUND``
  R4 #1776 ``ante config get <missing-key>`` → ``CONFIG_KEY_NOT_FOUND``
  R5 #1777 ``ante rule info <missing-rule> --account test``
         → ``RULE_NOT_FOUND``
  R6 #1778 ``ante member info <missing-member>`` → ``MEMBER_NOT_FOUND``
  R7 #1779 ``ante bot logs <missing-bot>`` → ``BOT_NOT_FOUND``
  R8 #1780 ``ante instrument import <file>.txt``
         → ``INSTRUMENT_INVALID_FILE_FORMAT``
  R9 #1781 ``ante instrument import <empty>.csv``
         → ``INSTRUMENT_EMPTY_FILE``
  R10 #1782 ``ante instrument import <object>.json``
         → ``INSTRUMENT_INVALID_JSON_SHAPE``

conftest 격리: ``_clean_env`` 헬퍼로 부모 프로세스의 환경변수가 새지 않도록
``PATH`` / ``HOME`` / ``ANTE_CONFIG_DIR`` / ``PYTHONPATH`` 만 명시 전달한다
(#1725 ``test_cli_treasury_account_not_found.py`` 동형).
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
    config_dir: Path,
    *,
    encryption_key: str | None = None,
    token: str | None = None,
) -> dict[str, str]:
    """subprocess 환경 격리 헬퍼.

    부모 프로세스의 ``ANTE_DB_ENCRYPTION_KEY`` / ``ANTE_MEMBER_TOKEN`` 등이
    새는 것을 막기 위해 ``PATH`` / ``HOME`` / ``ANTE_CONFIG_DIR`` /
    ``PYTHONPATH`` 만 명시 전달한다 (#1725 동형).
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


def _parse_json_last(stdout: str) -> dict:
    """JSON dict payload를 stdout에서 추출한다.

    ``OutputFormatter.error`` 는 single-line JSON 한 줄로 dump하지만
    ``OutputFormatter.output`` 은 indent=2로 multi-line dump한다.
    우선 stdout 전체를 한 번에 ``json.loads`` 로 시도하고(success path),
    실패하면 라인별 스캔으로 마지막 dict 라인을 찾는다 (error path).
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


def _run_cli(
    config_dir: Path,
    args: list[str],
    *,
    token: str | None = None,
    encryption_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """``ante --format json <args>`` 를 subprocess로 실행한다.

    timeout=5로 hang 회귀를 차단한다.
    """
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _run_init(config_dir: Path, encryption_key: str) -> tuple[str, str]:
    """초기 ``ante init`` 을 호출하고 (token, encryption_key)를 반환한다.

    init은 ``create_default_test_account()`` 경로로 ``account_id='test'``
    시드 계좌를 자동 생성한다. token은 후속 subprocess 호출의
    ``ANTE_MEMBER_TOKEN`` 으로 쓰인다.
    """
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
            "Sweep",
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
# R1 #1773 — ante init 2회 → CLI_ALREADY_INITIALIZED
# ────────────────────────────────────────────────────────────────────


class TestInitAlreadyInitializedCodeNaming:
    def test_init_twice_emits_uppercase_already_initialized(
        self, tmp_path: Path
    ) -> None:
        """R1: init 2번째 실행 → exit 1, code=CLI_ALREADY_INITIALIZED."""
        config_dir = tmp_path / "config"
        key = Fernet.generate_key().decode()
        _run_init(config_dir, key)  # 1차 init (성공)

        # 2차 init — already-initialized 상태에서 exit 1 + JSON 에러.
        init_env = _clean_env(config_dir, encryption_key=key)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ante",
                "--format",
                "json",
                "init",
                "--name",
                "Sweep",
            ],
            env=init_env,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "CLI_ALREADY_INITIALIZED", payload


# ────────────────────────────────────────────────────────────────────
# R2 #1774 — ante report view <missing> → REPORT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestReportViewNotFoundCodeNaming:
    def test_report_view_missing_id_emits_uppercase_report_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R2: report view <missing> → exit 1, code=REPORT_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["report", "view", "rpt-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "REPORT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R3 #1775 — treasury snapshot --account test --date 1999-01-01
#           → SNAPSHOT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestTreasurySnapshotNotFoundCodeNaming:
    def test_snapshot_missing_date_emits_uppercase_snapshot_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R3: snapshot --account test --date 1999-01-01 → SNAPSHOT_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            [
                "treasury",
                "snapshot",
                "--account",
                "test",
                "--date",
                "1999-01-01",
            ],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "SNAPSHOT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R4 #1776 — config get <missing-key> → CONFIG_KEY_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestConfigGetMissingKeyCodeNaming:
    def test_config_get_missing_key_emits_config_key_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R4: config get <missing> → exit 1, code=CONFIG_KEY_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["config", "get", "does.not.exist.key"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "CONFIG_KEY_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R5 #1777 — rule info <missing> --account test → RULE_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestRuleInfoNotFoundCodeNaming:
    def test_rule_info_missing_rule_emits_rule_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R5: rule info <missing> --account test → RULE_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["rule", "info", "rule-does-not-exist", "--account", "test"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "RULE_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R6 #1778 — member info <missing> → MEMBER_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestMemberInfoNotFoundCodeNaming:
    def test_member_info_missing_id_emits_member_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R6: member info <missing> → exit 1, code=MEMBER_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["member", "info", "mbr-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R7 #1779 — bot logs <missing> → BOT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestBotLogsNotFoundCodeNaming:
    def test_bot_logs_missing_bot_emits_bot_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R7: bot logs <missing> → exit 1, code=BOT_NOT_FOUND."""
        config_dir, token, key = initialized_config
        result = _run_cli(
            config_dir,
            ["bot", "logs", "bot-does-not-exist"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "BOT_NOT_FOUND", payload


# ────────────────────────────────────────────────────────────────────
# R8 #1780 — instrument import <file>.txt → INSTRUMENT_INVALID_FILE_FORMAT
# ────────────────────────────────────────────────────────────────────


class TestInstrumentImportInvalidFormatCodeNaming:
    def test_invalid_extension_emits_invalid_file_format(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        """R8: import <file>.txt → exit 1, code=INSTRUMENT_INVALID_FILE_FORMAT."""
        config_dir, token, key = initialized_config
        bogus = tmp_path / "bogus.txt"
        bogus.write_text("not a csv or json\n", encoding="utf-8")
        result = _run_cli(
            config_dir,
            ["instrument", "import", str(bogus)],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "INSTRUMENT_INVALID_FILE_FORMAT", payload


# ────────────────────────────────────────────────────────────────────
# R9 #1781 — instrument import <empty>.csv → INSTRUMENT_EMPTY_FILE
# ────────────────────────────────────────────────────────────────────


class TestInstrumentImportEmptyFileCodeNaming:
    def test_empty_json_emits_empty_file(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        """R9: import <empty>.json (빈 array) → code=INSTRUMENT_EMPTY_FILE.

        JSON 경로를 쓰면 ``ext == ".json"`` 분기를 통과해 ``records`` 가
        빈 list가 되고, ``if not records`` 분기에서 INSTRUMENT_EMPTY_FILE
        로 종료된다.
        """
        config_dir, token, key = initialized_config
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        result = _run_cli(
            config_dir,
            ["instrument", "import", str(empty)],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "INSTRUMENT_EMPTY_FILE", payload


# ────────────────────────────────────────────────────────────────────
# R10 #1782 — instrument import <object>.json → INSTRUMENT_INVALID_JSON_SHAPE
# ────────────────────────────────────────────────────────────────────


class TestInstrumentImportInvalidJsonShapeCodeNaming:
    def test_json_object_root_emits_invalid_json_shape(
        self,
        initialized_config: tuple[Path, str, str],
        tmp_path: Path,
    ) -> None:
        """R10: import <object>.json (object root) → INSTRUMENT_INVALID_JSON_SHAPE."""
        config_dir, token, key = initialized_config
        obj_json = tmp_path / "object.json"
        obj_json.write_text('{"symbol": "AAPL"}', encoding="utf-8")
        result = _run_cli(
            config_dir,
            ["instrument", "import", str(obj_json)],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "INSTRUMENT_INVALID_JSON_SHAPE", payload
