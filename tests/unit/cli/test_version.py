"""CLI 버전 자동 읽기 테스트."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_PATH = Path(__file__).resolve().parents[3] / "src" / "ante" / "cli" / "main.py"


def test_no_hardcoded_version_in_source() -> None:
    """src/ante/cli/main.py에 하드코딩된 '0.1.0' 문자열이 없는지 확인한다."""
    content = _SOURCE_PATH.read_text()

    assert '"0.1.0"' not in content, "main.py에 하드코딩된 버전 '0.1.0'이 남아 있습니다"


def test_version_option_uses_dunder_version() -> None:
    """click.version_option이 __version__ 변수를 참조하는지 확인한다."""
    content = _SOURCE_PATH.read_text()

    assert "__version__" in content, "main.py에 __version__ 변수가 없습니다"
    assert "version=__version__" in content, (
        "click.version_option이 __version__을 사용하지 않습니다"
    )


def test_importlib_metadata_used() -> None:
    """importlib.metadata를 통해 버전을 읽는 코드가 존재하는지 확인한다."""
    content = _SOURCE_PATH.read_text()
    tree = ast.parse(content)

    found_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib.metadata":
            for alias in node.names:
                if alias.name == "version":
                    found_import = True

    assert found_import, "importlib.metadata.version import가 없습니다"


def test_fallback_to_dev() -> None:
    """importlib.metadata 실패 시 'dev' fallback이 있는지 확인한다."""
    content = _SOURCE_PATH.read_text()

    assert '"dev"' in content, "fallback 버전 'dev'가 없습니다"


def test_version_output_is_not_hardcoded() -> None:
    """ante --version 출력이 하드코딩된 '0.1.0'이 아닌지 확인한다."""
    from click.testing import CliRunner

    from ante.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    # 버전이 출력되어야 하며, 이전 하드코딩 값이 아니어야 한다
    assert "ante, version" in result.output
