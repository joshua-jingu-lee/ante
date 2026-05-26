"""rule CLI valid-but-missing account_id contract 회귀 (#1726).

다음 R-case들을 잠근다 (이슈 본문 v2 Implementation Plan):

- R1 우선순위 회귀 (info): ``ante rule info missing-rule --account acc-9999``
  → ``subprocess.run(timeout=5)`` 내 종료 + ``exit 1`` + JSON
  ``code="ACCOUNT_NOT_FOUND"``. account existence가 rule lookup보다
  먼저 보고됨을 검증한다 (이전 동작: 빈 code의 "룰을 찾을 수 없습니다").
- R2 cleanup 회귀: in-process unit test로 ``db.fetch_one`` 이 raise할 때
  ``Database.close`` 가 1회 await된다. 내부 필드 (``_writer`` /
  ``_reader``) 직접 접근 금지 — public lifecycle ``Database.close`` 호출
  사실로 검증 (#1722/#1725 R3 동형).
- R3 sanity (info, valid existing): ``rule info global-rule --account test``
  → 룰이 없으면 exit 1 + "룰을 찾을 수 없습니다" (account 자체는 존재
  하므로 ACCOUNT_NOT_FOUND이 아님). ``test`` 계좌는 ``ante init`` 이
  ``create_default_test_account()`` 로 자동 생성한다.
- R4 sanity (info, account 존재 + 룰 없음): ``rule info missing-rule
  --account test`` → exit 1, "룰을 찾을 수 없습니다" 메시지 보존
  (account는 존재, rule만 없음 — code는 빈 값 또는 기존 동작 보존).
- R5 sanity (info, invalid `default`): ``rule info missing-rule --account
  default`` → exit 1, ``code="VALIDATION_ERROR"`` (기존
  ``reject_invalid_account_id`` 동작 보존).
- R_LIST 회귀 (list, valid-absent): ``rule list --account acc-9999`` →
  exit 1, ``code="ACCOUNT_NOT_FOUND"`` (SSOT consolidation 후에도 동일
  동작 보존).

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
    계좌를 자동 생성한다 (``scoping.py:36`` 참조). R3/R4 sanity가 이 시드
    계좌를 재사용한다. token/key는 후속 subprocess 호출에서 인증/암복호화에
    쓰인다.
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


def _run_rule_cli(
    config_dir: Path,
    token: str,
    encryption_key: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """rule CLI를 subprocess로 실행한다. timeout=5로 hang 회귀를 차단한다."""
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
# R1 — 우선순위 회귀: rule info valid-but-missing account → ACCOUNT_NOT_FOUND
# ────────────────────────────────────────────────────────────────────


class TestRuleInfoValidAbsentAccount:
    def test_info_acc9999_reports_account_not_found_before_rule_lookup(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R1: info acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND.

        우선순위: account existence가 rule lookup보다 먼저 보고된다.
        이전 동작은 빈 ``code`` + "룰을 찾을 수 없습니다" 메시지였다.
        """
        config_dir, token, key = initialized_config

        result = _run_rule_cli(
            config_dir,
            token,
            key,
            ["rule", "info", "missing-rule", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload
        # rule lookup 메시지가 우선되지 않는지 확인 (우선순위 역전 회귀).
        assert "룰을 찾을 수 없습니다" not in (payload.get("message") or ""), payload


# ────────────────────────────────────────────────────────────────────
# R2 — cleanup 회귀 (in-process, Database.close spy)
# ────────────────────────────────────────────────────────────────────


class TestCreateRuleEngineCleanup:
    @pytest.mark.asyncio
    async def test_existence_check_raise_calls_db_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``db.fetch_one`` 가 raise하면 ``Database.close`` 1회 await.

        ``_create_rule_engine`` 의 ``except BaseException`` cleanup 블록이
        실제로 ``db.close()`` 를 호출하는지 검증한다 (#1722/#1725 R3 동형).
        내부 필드(``_writer`` / ``_reader``)는 들여다보지 않고 public
        lifecycle method ``Database.close`` 호출 사실로 검증한다.
        """
        from ante.account.errors import AccountNotFoundError
        from ante.cli.commands.rule import _create_rule_engine
        from ante.core.database import Database

        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

        async def passing_connect(self: Database) -> None:
            return None

        async def raising_fetch_one(
            self: Database, sql: str, params: tuple = ()
        ) -> object:
            raise AccountNotFoundError("계좌 'acc-9999'를 찾을 수 없습니다.")

        # #1857: ``_create_rule_engine`` 는 async context manager 로 변환됨.
        import click

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            monkeypatch.setattr(Database, "connect", passing_connect)
            monkeypatch.setattr(Database, "fetch_one", raising_fetch_one)

            with pytest.raises(AccountNotFoundError):
                ctx = click.Context(click.Command("dummy"))
                async with _create_rule_engine("acc-9999", ctx=ctx):
                    pass

        assert close_mock.await_count == 1, (
            f"Database.close 가 정확히 1회 await되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# R3 — sanity: rule info global-rule --account test (account 존재, rule 미존재)
# ────────────────────────────────────────────────────────────────────


class TestRuleInfoValidExistingAccountMissingRule:
    def test_info_missing_rule_with_existing_account_returns_rule_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R3 sanity: rule info global-rule --account test → exit 1, rule lookup 메시지.

        ``test`` 계좌는 존재(``ante init`` 시드)하므로 ``ACCOUNT_NOT_FOUND``
        가 아닌 기존 rule lookup 분기로 흘러야 한다. global-rule 등록이
        config-driven이라 환경에 따라 결과가 다를 수 있는데, 어느 경우든
        ``ACCOUNT_NOT_FOUND`` 가 아닌지를 검증한다.
        """
        config_dir, token, key = initialized_config

        result = _run_rule_cli(
            config_dir,
            token,
            key,
            ["rule", "info", "global-rule", "--account", "test"],
        )
        # exit code는 환경 의존(시드 룰 존재 여부)이므로 ACCOUNT_NOT_FOUND
        # 분기로 떨어지지 않았는지만 확인한다.
        if result.returncode != 0:
            payload = _parse_json_last(result.stdout)
            assert payload.get("code") != "ACCOUNT_NOT_FOUND", (
                f"존재하는 account 'test'에 ACCOUNT_NOT_FOUND 분기 오인: {payload}"
            )


# ────────────────────────────────────────────────────────────────────
# R4 — sanity: account 존재 + rule 미존재 → "룰을 찾을 수 없습니다" 보존
# ────────────────────────────────────────────────────────────────────


class TestRuleInfoMissingRuleWithExistingAccount:
    def test_info_missing_rule_with_existing_account_preserves_rule_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R4 sanity: info missing-rule --account test → exit 1, rule not-found.

        account ``test`` 는 존재하지만 ``missing-rule`` 은 등록되어 있지
        않다. 기존 "룰을 찾을 수 없습니다" 메시지가 그대로 노출되는지
        확인한다 (account 존재 시 rule lookup 분기 보존).
        """
        config_dir, token, key = initialized_config

        result = _run_rule_cli(
            config_dir,
            token,
            key,
            ["rule", "info", "missing-rule", "--account", "test"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        # account가 존재하므로 ACCOUNT_NOT_FOUND가 아니어야 한다.
        assert payload.get("code") != "ACCOUNT_NOT_FOUND", payload
        # 기존 rule lookup 메시지 보존.
        assert "룰을 찾을 수 없습니다" in (payload.get("message") or ""), payload


# ────────────────────────────────────────────────────────────────────
# R5 — sanity: invalid `default` → VALIDATION_ERROR (기존 동작 보존)
# ────────────────────────────────────────────────────────────────────


class TestRuleInfoInvalidDefaultAccount:
    def test_info_default_account_exits_with_validation_error(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R5: rule info missing-rule --account default → exit 1, code=VALIDATION_ERROR.

        ``reject_invalid_account_id`` 가 ``default`` 예약어를 거부하는 기존
        동작이 본 PR로 깨지지 않는지 확인한다 (#1635 Split B Layer 1).
        """
        config_dir, token, key = initialized_config

        result = _run_rule_cli(
            config_dir,
            token,
            key,
            ["rule", "info", "missing-rule", "--account", "default"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "VALIDATION_ERROR", payload


# ────────────────────────────────────────────────────────────────────
# R_LIST — rule list SSOT consolidation 회귀 (helper 이동 후 동일 동작 보존)
# ────────────────────────────────────────────────────────────────────


class TestRuleListValidAbsentAccount:
    def test_list_acc9999_still_reports_account_not_found(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """R_LIST: rule list --account acc-9999 → exit 1, code=ACCOUNT_NOT_FOUND.

        ``rule_list`` 의 inline existence check 블록을 ``_create_rule_engine``
        helper로 이동한 후에도 동일한 envelope/code를 반환하는지 확인한다.
        """
        config_dir, token, key = initialized_config

        result = _run_rule_cli(
            config_dir,
            token,
            key,
            ["rule", "list", "--account", "acc-9999"],
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload
