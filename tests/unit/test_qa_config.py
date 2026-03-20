"""QA 서버 설정 및 엔트리포인트 파일 유효성 검증."""

from __future__ import annotations

import os
import stat
import subprocess
import tomllib
from pathlib import Path

# 프로젝트 루트 기준 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestSystemQaToml:
    """config/system.qa.toml 유효성 검증."""

    def setup_method(self) -> None:
        self.path = PROJECT_ROOT / "config" / "system.qa.toml"

    def test_file_exists(self) -> None:
        assert self.path.exists(), f"{self.path} 파일이 존재하지 않습니다"

    def test_valid_toml(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        assert isinstance(config, dict)

    def test_required_sections(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        required = [
            "system",
            "db",
            "web",
            "broker",
            "treasury",
            "reconcile",
            "audit",
            "approval",
        ]
        for section in required:
            assert section in config, f"[{section}] 섹션이 누락되었습니다"

    def test_debug_log_level(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        assert config["system"]["log_level"] == "DEBUG"

    def test_web_enabled_on_port_8000(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        assert config["web"]["enabled"] is True
        assert config["web"]["port"] == 8000

    def test_mock_broker_immediate_fill(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        assert config["broker"]["type"] == "mock"
        assert config["broker"]["fill_mode"] == "immediate"

    def test_db_path_absolute(self) -> None:
        with open(self.path, "rb") as f:
            config = tomllib.load(f)
        db_path = config["db"]["path"]
        assert db_path == "/app/db/ante.db", (
            f"Docker 환경에서의 DB 경로가 절대경로여야 합니다: {db_path}"
        )


class TestQaEntrypoint:
    """scripts/qa-entrypoint.sh 유효성 검증."""

    def setup_method(self) -> None:
        self.path = PROJECT_ROOT / "scripts" / "qa-entrypoint.sh"

    def test_file_exists(self) -> None:
        assert self.path.exists(), f"{self.path} 파일이 존재하지 않습니다"

    def test_executable_permission(self) -> None:
        mode = os.stat(self.path).st_mode
        assert mode & stat.S_IXUSR, "실행 권한(u+x)이 없습니다"

    def test_valid_bash_syntax(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(self.path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash 구문 오류: {result.stderr}"

    def test_shebang_line(self) -> None:
        with open(self.path) as f:
            first_line = f.readline().strip()
        assert first_line == "#!/bin/bash", f"shebang이 올바르지 않습니다: {first_line}"

    def test_contains_healthcheck_loop(self) -> None:
        content = self.path.read_text()
        assert "health" in content, "헬스체크 로직이 포함되어야 합니다"
        assert "seq 1 30" in content, "30초 헬스체크 대기 루프가 포함되어야 합니다"

    def test_contains_member_bootstrap(self) -> None:
        content = self.path.read_text()
        assert "member bootstrap" in content, "멤버 부트스트랩 명령이 포함되어야 합니다"

    def test_contains_server_background_start(self) -> None:
        content = self.path.read_text()
        assert "python -m ante.main &" in content, (
            "서버 백그라운드 기동 명령이 포함되어야 합니다"
        )

    def test_contains_wait_for_foreground(self) -> None:
        content = self.path.read_text()
        assert "wait $SERVER_PID" in content, (
            "서버 포그라운드 전환(wait)이 포함되어야 합니다"
        )

    def test_set_e_for_error_handling(self) -> None:
        content = self.path.read_text()
        assert "set -e" in content, "set -e로 에러 시 즉시 종료해야 합니다"
