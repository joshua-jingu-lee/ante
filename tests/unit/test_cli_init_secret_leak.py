"""이슈 #1721 R13: ANTE_DB_ENCRYPTION_KEY 7-채널 leak 검사.

7 채널 (init은 file logger 미셋업이므로 log file 채널 제외 — known-limitation):
1. stdout text mode
2. stdout JSON mode payload
3. stderr text mode error
4. stderr JSON mode recovery event
5. caplog records (level=DEBUG, propagation 강제 on)
6. Click ``result.exception`` chain message
7. ``test_account_failed`` 실패 메시지 본문

성공 경로 + 실패 경로(``_create_test_account`` 가 raise) 둘 다 검증한다.

Plan Preflight v4 narrow-scope 채택 — Codex v3 new-must-fix 3 흡수.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli


def _split_stderr_runner() -> CliRunner:
    """Click 8.1/8.3 양쪽에서 stderr 분리 캡처를 요청한다."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


def _read_key_line(secrets_env_path: Path) -> str | None:
    if not secrets_env_path.exists():
        return None
    last: str | None = None
    for raw in secrets_env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "ANTE_DB_ENCRYPTION_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        last = value
    return last


_MOCK_TEST_ACCOUNT = {
    "account_id": "test",
    "broker_type": "test",
    "exchange": "TEST",
}

_MOCK_MASTER_INFO = {
    "member_id": "owner",
    "name": "Owner",
    "role": "master",
    "emoji": "🦊",
}
_MOCK_TOKEN = "ante_hk_test_token_leak"
_MOCK_RECOVERY_KEY = "ANTE-RK-LEAK-TEST-XXXX-YYYY-ZZZZ"


def _mock_bootstrap(*args, **kwargs):
    return _MOCK_MASTER_INFO, _MOCK_TOKEN, _MOCK_RECOVERY_KEY


def _patch_init_success():
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(return_value=_MOCK_TEST_ACCOUNT),
        ),
        patch(
            "ante.cli.commands.init._master_exists_in_db",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "ante.cli.commands.init._test_account_state",
            new=AsyncMock(return_value="missing"),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


def _patch_init_failure():
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=RuntimeError("synthetic test_account failure")),
        ),
        patch(
            "ante.cli.commands.init._master_exists_in_db",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "ante.cli.commands.init._test_account_state",
            new=AsyncMock(return_value="missing"),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


def _assert_key_not_in(value: str, *, where: str, blob: str) -> None:
    """주어진 ``blob`` 텍스트에 ``value`` 부분 문자열이 없어야 한다."""
    assert value not in blob, (
        f"ANTE_DB_ENCRYPTION_KEY 누설 ({where})\n"
        f"key={value!r}\n"
        f"blob_excerpt={blob[:500]!r}"
    )


class TestInitR13EncryptionKeyNoLeak:
    """R13: 생성된 ANTE_DB_ENCRYPTION_KEY 가 7개 노출 채널에 나타나지 않는다."""

    @pytest.fixture(autouse=True)
    def _isolate_env_and_logs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """ANTE_DB_ENCRYPTION_KEY 환경변수 격리 + caplog propagation 강제.

        conftest.py 세션 fixture가 세션 시작 시 ANTE_DB_ENCRYPTION_KEY를 set하므로
        init이 자체적으로 키를 생성하는 경로를 검증하려면 명시적으로 delenv가 필요.
        monkeypatch는 테스트 종료 시 환경을 복원하므로 다른 테스트에 영향이 없다.
        """
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        ante_logger = logging.getLogger("ante")
        prev = ante_logger.propagate
        ante_logger.propagate = True
        caplog.set_level(logging.DEBUG)
        yield monkeypatch
        ante_logger.propagate = prev

    def test_success_path_no_leak_across_channels(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """성공 경로 — text+json 모드 모두 stdout/stderr/log/exception에 키 부재."""
        runner = _split_stderr_runner()

        # === text 모드 ===
        target_text = tmp_path / "text-mode"
        caplog.clear()
        patches = _patch_init_success()
        for p in patches:
            p.start()
        try:
            result_text = runner.invoke(cli, ["init", "--dir", str(target_text)])
        finally:
            for p in patches:
                p.stop()
        assert result_text.exit_code == 0, result_text.output

        text_key = _read_key_line(target_text / "secrets.env")
        assert text_key is not None
        _assert_key_not_in(text_key, where="text stdout", blob=result_text.stdout or "")
        stderr_text_blob = result_text.stderr if result_text.stderr_bytes else ""
        _assert_key_not_in(text_key, where="text stderr", blob=stderr_text_blob)
        log_blob_text = "\n".join(r.getMessage() for r in caplog.records)
        _assert_key_not_in(text_key, where="text caplog", blob=log_blob_text)
        exc_text = "" if result_text.exception is None else repr(result_text.exception)
        _assert_key_not_in(text_key, where="text exception", blob=exc_text)

        # === JSON 모드 ===
        # caplog 잔여 기록 제거 + 새 디렉토리에서 두 번째 실행.
        caplog.clear()
        target_json = tmp_path / "json-mode"
        # ANTE_DB_ENCRYPTION_KEY는 앞 실행에서 init이 set했을 수 있으므로 다시 제거.
        # monkeypatch를 통해 제거하면 테스트 종료 시 자동 복원된다.
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        patches = _patch_init_success()
        for p in patches:
            p.start()
        try:
            result_json = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target_json)]
            )
        finally:
            for p in patches:
                p.stop()
        assert result_json.exit_code == 0, (
            f"stdout={result_json.stdout}\nstderr={result_json.stderr}"
        )

        json_key = _read_key_line(target_json / "secrets.env")
        assert json_key is not None
        _assert_key_not_in(
            json_key, where="json stdout payload", blob=result_json.stdout or ""
        )
        stderr_json_blob = result_json.stderr if result_json.stderr_bytes else ""
        _assert_key_not_in(json_key, where="json stderr event", blob=stderr_json_blob)
        log_blob_json = "\n".join(r.getMessage() for r in caplog.records)
        _assert_key_not_in(json_key, where="json caplog", blob=log_blob_json)
        exc_json = "" if result_json.exception is None else repr(result_json.exception)
        _assert_key_not_in(json_key, where="json exception", blob=exc_json)

    def test_failure_path_no_leak_in_test_account_failed_message(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """실패 경로 — ``test_account_failed`` 에러 메시지 본문에 키 부재.

        7번째 채널 (실패 메시지 본문) 검증. ``_create_test_account``가 raise한
        ``RuntimeError`` 메시지가 ``OutputFormatter.error``로 직렬화될 때 키가
        절대 포함되면 안 된다.
        """
        runner = _split_stderr_runner()

        # === text 모드 실패 ===
        target_text = tmp_path / "fail-text"
        caplog.clear()
        patches = _patch_init_failure()
        for p in patches:
            p.start()
        try:
            result_text = runner.invoke(cli, ["init", "--dir", str(target_text)])
        finally:
            for p in patches:
                p.stop()
        assert result_text.exit_code == 1, result_text.output

        text_key = _read_key_line(target_text / "secrets.env")
        assert text_key is not None
        # text 모드 stdout / stderr / log / exception 모두 검사
        _assert_key_not_in(
            text_key, where="fail text stdout", blob=result_text.stdout or ""
        )
        stderr_blob = result_text.stderr if result_text.stderr_bytes else ""
        _assert_key_not_in(text_key, where="fail text stderr", blob=stderr_blob)
        # test_account_failed 메시지 본문 검증 (stdout 또는 stderr 어느 한 쪽에 있음)
        combined = (result_text.stdout or "") + stderr_blob
        assert "테스트 계좌 생성 실패" in combined
        _assert_key_not_in(
            text_key,
            where="fail text test_account_failed message",
            blob=combined,
        )
        log_blob = "\n".join(r.getMessage() for r in caplog.records)
        _assert_key_not_in(text_key, where="fail text caplog", blob=log_blob)
        exc_text = "" if result_text.exception is None else repr(result_text.exception)
        _assert_key_not_in(text_key, where="fail text exception", blob=exc_text)

        # === JSON 모드 실패 ===
        caplog.clear()
        target_json = tmp_path / "fail-json"
        # monkeypatch를 통해 제거하면 테스트 종료 시 자동 복원된다.
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        patches = _patch_init_failure()
        for p in patches:
            p.start()
        try:
            result_json = runner.invoke(
                cli, ["--format", "json", "init", "--dir", str(target_json)]
            )
        finally:
            for p in patches:
                p.stop()
        assert result_json.exit_code == 1
        json_key = _read_key_line(target_json / "secrets.env")
        assert json_key is not None
        _assert_key_not_in(
            json_key, where="fail json stdout", blob=result_json.stdout or ""
        )
        stderr_json = result_json.stderr if result_json.stderr_bytes else ""
        _assert_key_not_in(json_key, where="fail json stderr", blob=stderr_json)
        log_blob_j = "\n".join(r.getMessage() for r in caplog.records)
        _assert_key_not_in(json_key, where="fail json caplog", blob=log_blob_j)
        exc_json = "" if result_json.exception is None else repr(result_json.exception)
        _assert_key_not_in(json_key, where="fail json exception", blob=exc_json)
