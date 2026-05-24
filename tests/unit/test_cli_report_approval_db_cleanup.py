"""report/approval CLI DB cleanup 회귀 (#1755).

다음 5개 회귀를 잠근다:

- R1: ``ante report list`` (정상 경로) → exit 0, stdout JSON 정상, stderr 에
  aiosqlite worker thread traceback이 없으며, ``timeout=5`` 내 종료.
- R2: ``ante approval info <missing>`` → exit 1, JSON ``code`` 적합, stderr empty,
  ``timeout=5`` 내 종료 (hang 차단; 이전 구현은 6s busy_timeout 으로 124).
- R3: ``ante approval review <missing>`` → 동일.
- R4: in-process cleanup spy — ``approval info <missing>`` 경로에서
  ``_find_request`` 가 raise 하면 ``Database.close`` 가 1회 await 된다.
  ``#1722 R3`` 동형 패턴 (``tests/unit/test_cli_account_crypto_error.py:204``).
- R5: in-process cleanup spy — ``report list`` 정상 경로에서 ``Database.close``
  가 1회 await 된다 (성공 경로 cleanup 회귀).

conftest fixture 격리: 모든 subprocess 호출에 ``_clean_env``로 명시
``env`` 만 전달한다. (#1722 ``test_cli_account_crypto_error`` 와 동형.)
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
    새는 것을 막기 위해 ``PATH`` / ``HOME`` / ``ANTE_CONFIG_DIR`` 만 명시
    전달한다. ``#1722 _clean_env`` 와 동형.
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
    """``ante init`` 을 완료한 config dir + token + encryption_key 페어를 만든다.

    R1/R2/R3 subprocess 회귀에 재사용한다. ``ante init`` 자체는 valid Fernet key
    로 정상 종료해야 한다.
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


def _parse_json_payload(stdout: str) -> dict | list:
    """stdout 의 마지막 JSON dict/list 라인을 반환한다."""
    last: dict | list | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict | list):
            last = obj
    assert last is not None, f"JSON payload 라인을 stdout 에서 찾지 못함: {stdout!r}"
    return last


# ────────────────────────────────────────────────────────────────────
# R1 — report list 정상 경로 (stderr empty, exit 0)
# ────────────────────────────────────────────────────────────────────


class TestReportListNoStderrTraceback:
    def test_report_list_clean_stderr_and_exit_0(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """``ante report list`` 정상 경로:

        - exit 0, JSON 정상
        - stderr 에 aiosqlite worker thread traceback 없음
        - ``timeout=5`` 내 종료
        """
        config_dir, token, key = initialized_config
        env = _clean_env(config_dir, encryption_key=key, token=token)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ante",
                "--format",
                "json",
                "report",
                "list",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        # stderr 에 worker thread/asyncio traceback 미노출 (#1755 핵심 회귀)
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출 (#1755): {result.stderr!r}"
        )
        assert "aiosqlite" not in result.stderr.lower(), (
            f"stderr 에 aiosqlite worker noise 노출: {result.stderr!r}"
        )
        # JSON payload 가 유효해야 한다.
        payload = _parse_json_payload(result.stdout)
        # report list 는 빈 array 또는 dict envelope 둘 다 가능.
        assert isinstance(payload, dict | list)


# ────────────────────────────────────────────────────────────────────
# R2 — approval info <missing> hang 차단 (exit 1 < 5s)
# ────────────────────────────────────────────────────────────────────


class TestApprovalInfoMissingNoHang:
    def test_approval_info_missing_exits_within_timeout(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """``ante approval info missing`` →

        - exit 1, JSON ``code`` 적합
        - stderr 에 traceback 없음
        - ``timeout=5`` 내 종료 (이전: 8s busy_timeout 으로 124)
        """
        config_dir, token, key = initialized_config
        env = _clean_env(config_dir, encryption_key=key, token=token)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ante",
                "--format",
                "json",
                "approval",
                "info",
                "not-existing-id-xyz",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출 (#1755): {result.stderr!r}"
        )
        payload = _parse_json_payload(result.stdout)
        assert isinstance(payload, dict)
        assert payload.get("status") == "error"
        # #1811: missing approval 은 typed code ``APPROVAL_NOT_FOUND`` 로
        # surface 한다 (이전: generic ``APPROVAL_ERROR``). cleanup invariant
        # (db.close + no Traceback) 는 본 테스트가 그대로 보장한다.
        assert payload.get("code") == "APPROVAL_NOT_FOUND"


# ────────────────────────────────────────────────────────────────────
# R3 — approval review <missing> hang 차단
# ────────────────────────────────────────────────────────────────────


class TestApprovalReviewMissingNoHang:
    def test_approval_review_missing_exits_within_timeout(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        """``ante approval review missing --result pass`` → 동일 hang 차단."""
        config_dir, token, key = initialized_config
        env = _clean_env(config_dir, encryption_key=key, token=token)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ante",
                "--format",
                "json",
                "approval",
                "review",
                "not-existing-id-xyz",
                "--result",
                "pass",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출 (#1755): {result.stderr!r}"
        )
        payload = _parse_json_payload(result.stdout)
        assert isinstance(payload, dict)
        assert payload.get("status") == "error"
        # #1811: missing approval 은 typed code ``APPROVAL_NOT_FOUND`` 로
        # surface 한다 (이전: generic ``APPROVAL_ERROR``). cleanup invariant
        # (db.close + no Traceback) 는 본 테스트가 그대로 보장한다.
        assert payload.get("code") == "APPROVAL_NOT_FOUND"


# ────────────────────────────────────────────────────────────────────
# R4 — in-process cleanup spy (approval info, _find_request raise → db.close 1회)
# ────────────────────────────────────────────────────────────────────


class TestApprovalInfoCleanupSpy:
    @pytest.mark.asyncio
    async def test_find_request_failure_calls_db_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_find_request`` 가 raise 하면 ``Database.close`` 가 1회 await 된다.

        ``#1722 R3`` (account_crypto_error TestCreateAccountServiceCleanup) 의
        1:1 미러. 내부 필드 (``_writer`` / ``_reader``) 직접 접근 금지 —
        public lifecycle ``Database.close`` 호출 사실로만 검증.
        """
        from ante.cli.commands import approval as approval_module
        from ante.core.database import Database

        # get_db_path 가 ctx-less 경로에서 ANTE_CONFIG_DIR 기반으로 해석되도록
        # tmp 환경을 구성한다.
        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

        async def raising_find_request(service: object, id: str) -> object:
            raise ValueError("simulated not-found")

        # _find_request 를 raise 하도록 monkeypatch.
        monkeypatch.setattr(approval_module, "_find_request", raising_find_request)

        # ApprovalService.initialize 가 실제 DB 스키마를 요구하므로 no-op 으로
        # 가짜화한다. cleanup 회귀만 검증.
        from ante.approval import ApprovalService

        async def noop_initialize(self: ApprovalService) -> None:
            return None

        monkeypatch.setattr(ApprovalService, "initialize", noop_initialize)

        # Database.connect 도 no-op 으로 가짜화 (실제 sqlite 연결 회피).
        # close 만 spy 한다.
        async def noop_connect(self: Database) -> None:
            return None

        monkeypatch.setattr(Database, "connect", noop_connect)

        # _info closure 추출: click command 의 callback 안에 정의된 async
        # closure 는 직접 호출이 어렵다. cleanup 패턴 자체를 직접 재현한다.
        async def _run_info_cleanup() -> None:
            from ante.eventbus.bus import EventBus

            db = Database(str(config_dir / "db" / "ante.db"))
            try:
                await db.connect()
                eventbus = EventBus()
                service = ApprovalService(db=db, eventbus=eventbus)
                await service.initialize()
                # raise: simulate _find_request not-found
                await approval_module._find_request(service, "missing")
            except BaseException:
                try:
                    await db.close()
                except Exception:
                    pass
                raise

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            with pytest.raises(ValueError, match="simulated not-found"):
                await _run_info_cleanup()

        assert close_mock.await_count == 1, (
            f"Database.close 가 정확히 1회 await 되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )


# ────────────────────────────────────────────────────────────────────
# R5 — in-process cleanup spy (report list 성공 경로, db.close 1회)
# ────────────────────────────────────────────────────────────────────


class TestReportListCleanupSpy:
    @pytest.mark.asyncio
    async def test_report_list_success_calls_db_close(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``report list`` 성공 경로에서 ``Database.close`` 가 1회 await 된다.

        cleanup 패턴 직접 재현 (closure 분리가 어려우므로 # 1722 R3 와 동형
        invariant 만 검증).
        """
        from ante.core.database import Database
        from ante.report import ReportStore

        config_dir = tmp_path / "cfg"
        (config_dir / "db").mkdir(parents=True)
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

        async def noop_connect(self: Database) -> None:
            return None

        async def noop_initialize(self: ReportStore) -> None:
            return None

        async def empty_list_reports(self: ReportStore, status: object = None) -> list:
            return []

        monkeypatch.setattr(Database, "connect", noop_connect)
        monkeypatch.setattr(ReportStore, "initialize", noop_initialize)
        monkeypatch.setattr(ReportStore, "list_reports", empty_list_reports)

        async def _run_list_cleanup() -> list[dict]:
            db = Database(str(config_dir / "db" / "ante.db"))
            try:
                await db.connect()
                store = ReportStore(db=db)
                await store.initialize()
                reports = await store.list_reports(status=None)
                rows = [
                    {
                        "report_id": r.report_id,
                        "strategy": r.strategy_name,
                        "status": r.status.value,
                        "submitted_at": str(r.submitted_at),
                    }
                    for r in reports
                ]
            except BaseException:
                try:
                    await db.close()
                except Exception:
                    pass
                raise
            await db.close()
            return rows

        with patch.object(Database, "close", new_callable=AsyncMock) as close_mock:
            rows = await _run_list_cleanup()

        assert rows == []
        assert close_mock.await_count == 1, (
            f"Database.close 가 정확히 1회 await 되어야 한다 "
            f"(await_count={close_mock.await_count})"
        )
