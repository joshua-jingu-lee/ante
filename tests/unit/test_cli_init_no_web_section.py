"""D-018 회귀: ante init 산출물 system.toml에 ``[web]`` 섹션 부재 검증.

D-018(`docs/decisions/D-018-core-interface-cli-ipc.md`)은 Ante 1.0의 활성
운영 인터페이스를 CLI와 Unix socket IPC로 제한하고 HTTP REST/Web UI를 코어
런타임에서 제거한다. PR #1718/#1720이 코드 surface를 제거한 뒤에도
``SYSTEM_TOML_TEMPLATE``에 ``[web] host/port = 3982`` 라인이 stale로 남아
``ante init`` 산출물이 제거된 surface를 활성 설정처럼 노출했다(#1730).

본 테스트는 ``ante init``으로 생성되는 ``system.toml``에 ``[web]`` 섹션과
``port = 3982`` 라인이 다시 들어가지 않도록 회귀 락으로 고정한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.init import SYSTEM_TOML_TEMPLATE
from ante.cli.main import cli

_MOCK_MASTER_INFO = {
    "member_id": "owner",
    "name": "Owner",
    "role": "master",
    "emoji": "🦊",
}
_MOCK_TOKEN = "ante_hk_test_token_d018"
_MOCK_RECOVERY_KEY = "ANTE-RK-XXXX-YYYY-ZZZZ-AAAA-BBBB-CCCC"
_MOCK_TEST_ACCOUNT = {
    "account_id": "test",
    "broker_type": "test",
    "exchange": "TEST",
}


def _mock_bootstrap(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    return _MOCK_MASTER_INFO, _MOCK_TOKEN, _MOCK_RECOVERY_KEY


def _mock_create_test_account(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    return _MOCK_TEST_ACCOUNT


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_system_toml_template_omits_web_section() -> None:
    """SYSTEM_TOML_TEMPLATE 자체에 ``[web]`` / ``port = 3982`` 부재."""
    assert "[web]" not in SYSTEM_TOML_TEMPLATE
    assert "port = 3982" not in SYSTEM_TOML_TEMPLATE
    # D-018 active surface 섹션은 그대로 보존되어야 한다.
    assert "[system]" in SYSTEM_TOML_TEMPLATE
    assert "[db]" in SYSTEM_TOML_TEMPLATE
    assert "[runtime]" in SYSTEM_TOML_TEMPLATE


def test_init_creates_system_toml_without_web_section(
    runner: CliRunner, tmp_path
) -> None:
    """``ante init`` 산출물 ``system.toml``에 ``[web]`` 섹션 부재."""
    target = tmp_path / "config"

    with (
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=_mock_create_test_account),
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
    ):
        result = runner.invoke(cli, ["init", "--dir", str(target)])

    assert result.exit_code == 0, result.output
    system_toml_path = target / "system.toml"
    assert system_toml_path.exists()

    content = system_toml_path.read_text()
    assert "[web]" not in content
    assert "port = 3982" not in content
    # active surface 섹션 보존 확인.
    assert "[system]" in content
    assert "[db]" in content
    assert "[runtime]" in content
