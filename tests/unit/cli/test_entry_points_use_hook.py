"""운영 진입점 둘에서 관문의 예외가 진입점 훅을 지난다 (#2738 ⑧-3).

``pyproject.toml``의 ``ante`` 스크립트와 ``python -m ante``가 같은 루트
(``AuthenticatedGroup``)를 부르고, 토큰 없는 호출이 훅의 출력(text 줄
``Error: auth_required: …`` / JSON 봉투)으로 끝나는지 잠근다. ``python -m ante``의
stderr에는 설정 로더의 로그가 앞서므로 ``auth_required``가 든 줄만 비교한다.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.fernet import Fernet

from ante.cli.main import cli
from ante.cli.middleware import AuthenticatedGroup

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REQ = "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
_TEXT = f"Error: auth_required: {_REQ}\n"
_JSON = json.dumps({"status": "error", "code": "auth_required", "message": _REQ}) + "\n"


def _script_target() -> object:
    scripts = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())["project"][
        "scripts"
    ]
    module, _, attr = scripts["ante"].partition(":")
    return getattr(importlib.import_module(module), attr)


def test_script_entry_is_the_hooked_root() -> None:
    target = _script_target()
    assert target is cli
    assert isinstance(target, AuthenticatedGroup)
    assert type(target).main is AuthenticatedGroup.main


def test_module_entry_calls_the_same_root() -> None:
    source = (_REPO_ROOT / "src" / "ante" / "__main__.py").read_text()
    assert "from ante.cli.main import cli" in source
    assert source.rstrip().endswith("cli()")


@pytest.fixture()
def gate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "absent.token"))
    monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "PYTHONPATH": str(_REPO_ROOT / "src"),
        "ANTE_CONFIG_DIR": str(config_dir),
        "ANTE_TOKEN_FILE": str(tmp_path / "absent.token"),
        "ANTE_DB_ENCRYPTION_KEY": os.environ["ANTE_DB_ENCRYPTION_KEY"],
    }


@pytest.mark.parametrize(
    ("args", "stdout", "stderr"),
    [
        (["account", "list"], "", _TEXT),
        (["--format", "json", "account", "list"], _JSON, ""),
    ],
    ids=["text", "json"],
)
def test_script_entry_ends_gate_error_in_hook(
    args: list[str], stdout: str, stderr: str, gate_env: dict[str, str]
) -> None:
    target = _script_target()
    assert isinstance(target, AuthenticatedGroup)
    result = CliRunner(mix_stderr=False).invoke(target, args)
    assert (result.exit_code, result.stdout, result.stderr) == (1, stdout, stderr)


@pytest.mark.parametrize(
    ("args", "stdout", "stderr"),
    [
        (["account", "list"], "", _TEXT),
        (["--format", "json", "account", "list"], _JSON, ""),
    ],
    ids=["text", "json"],
)
def test_module_entry_ends_gate_error_in_hook(
    args: list[str], stdout: str, stderr: str, gate_env: dict[str, str]
) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "ante", *args],
        check=False,
        capture_output=True,
        text=True,
        env=gate_env,
        cwd=gate_env["HOME"],
    )
    assert (proc.returncode, proc.stdout) == (1, stdout)
    hook_lines = [line for line in proc.stderr.splitlines() if "auth_required" in line]
    assert hook_lines == stderr.splitlines()
