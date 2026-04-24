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

    def test_contains_ante_init(self) -> None:
        """issue #1125: member bootstrap은 제거되고 ante init이 master 생성을 담당."""
        content = self.path.read_text()
        assert "ante --format json init" in content or "ante init" in content, (
            "ante init (비대화형) 명령이 포함되어야 합니다"
        )
        assert "member bootstrap" not in content, (
            "제거된 ante member bootstrap 명령이 남아있습니다"
        )

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

    def test_qa_entrypoint_runs_init_before_server_start(self) -> None:
        """qa-entrypoint.sh는 서버 백그라운드 기동 전에 ante init을 호출해야 한다.

        서버가 먼저 기동되면 DB 파일이 생성되어 init이
        master bootstrap을 skip하는 회귀를 막는다.
        관련 이슈: #1125 (Codex branch review finding)
        """
        script = self.path.read_text()
        # ante init은 python -m ante.main (서버 기동) 앞에 와야 한다
        init_pos = script.find("ante --format json init")
        # 백그라운드 기동 패턴: "python -m ante.main &" (ampersand 포함)
        server_pos = script.find("python -m ante.main &")
        assert init_pos != -1, "ante init 호출이 없습니다"
        assert server_pos != -1, "서버 백그라운드 기동 라인이 없습니다"
        assert init_pos < server_pos, (
            f"qa-entrypoint.sh: ante init(pos={init_pos})이 "
            f"서버 기동(pos={server_pos}) 앞에 와야 합니다"
        )

    def test_qa_entrypoint_uses_login_rotate_after_reset_password(self) -> None:
        """reset-password 이후엔 login+rotate-token으로 새 토큰을 발급해야 한다.

        init이 발급한 초기 토큰은 reset-password 내부의
        `RecoveryKeyManager._invalidate_token`이 `token_hash=NULL`로 업데이트하여
        무효화한다. 따라서 init의 JSON 출력에서 token 필드를 QA_TOKEN에 직접
        저장하면 /run/ante-token에 무효 토큰이 쓰여 CLI 인증이 깨진다.
        유효 토큰은 서버 기동 후 login + rotate-token 경로로만 발급해야 한다.

        관련 이슈: #1125 (Codex branch review 3차 finding)
        """
        import re

        script = self.path.read_text()

        # 1) reset-password가 호출되는지 (QA 패스워드 동기화)
        assert "reset-password" in script, "reset-password 호출이 없습니다"

        # 2) init이 낸 token을 QA_TOKEN에 직접 대입하지 않는지
        #    금지 패턴: QA_TOKEN=$(echo "$INIT_JSON" ... .token ...)
        forbidden = re.search(
            r"QA_TOKEN=\$\(echo\s+\"\$INIT_JSON\".*?token",
            script,
            re.DOTALL,
        )
        assert forbidden is None, (
            "init 토큰을 QA_TOKEN에 직접 대입하고 있습니다 (reset-password로 무효화됨)"
        )

        # 3) login + rotate-token 흐름이 존재하는지
        assert "/api/auth/login" in script, "login 엔드포인트 호출이 없습니다"
        assert "/api/members" in script and "rotate-token" in script, (
            "rotate-token 엔드포인트 호출이 없습니다"
        )

        # 4) login이 조건부(예: `if [ -z "$QA_TOKEN" ]`)가 아니라 서버 기동 후
        #    항상 실행되어야 한다. login 위치가 reset-password 이후이고,
        #    이전의 조건부 `if [ -z "$QA_TOKEN" ]` 블록 안이 아닌지 확인한다.
        #    (실제 HTTP 호출 URL 기준으로 위치를 찾는다 — 주석/설명문 포함 금지)
        reset_pos = script.find("reset-password")
        login_pos = script.find("/api/auth/login")
        rotate_http_pos = script.find("/api/members/qa-admin/rotate-token")
        assert reset_pos < login_pos, "login은 reset-password 이후에 위치해야 합니다"
        assert login_pos < rotate_http_pos, (
            "rotate-token HTTP 호출은 login 이후에 위치해야 합니다"
        )

        # 5) 기존의 조건부 재발급 블록(`if [ -z "$QA_TOKEN" ]`)이 제거됐는지
        #    검증 — 이 가드가 남아 있으면 첫 기동에서 rotate가 skip된다.
        assert 'if [ -z "$QA_TOKEN" ]' not in script, (
            "조건부 rotate-token 분기가 남아 있습니다. "
            "reset-password 후에는 항상 login+rotate로 토큰을 재발급해야 합니다."
        )

    def test_qa_entrypoint_preserves_init_stderr_for_recovery(self) -> None:
        """Finding 2 (Codex 6차 review) — init stderr를 버리면 partial-failure
        recovery_key 이벤트가 영구 소실된다.

        `ante init`이 master bootstrap은 성공했지만 test account 생성에서 실패하면
        stdout은 에러 payload로 대체되고 stderr 1줄 JSON 이벤트
        (`master_bootstrap_complete`)에 recovery_key가 실린다. 과거 구현은
        `ante ... init ... 2>/dev/null || true`로 stderr를 버려 재기동 시 복구
        불가능한 상태를 만들었다. 이제는 stdout/stderr를 각각 mktemp 파일로
        캡처하고 exit code 분기로 partial-failure를 복구해야 한다.
        """
        import re

        script = self.path.read_text()

        # 1) init 호출 부근에서 `2>/dev/null` 으로 stderr를 버리면 안 된다.
        #    허용되는 패턴: stderr를 파일(또는 FD)에 리다이렉트.
        init_block_match = re.search(r"ante\s+--format\s+json\s+init[^\n]*", script)
        assert init_block_match is not None, "ante init 호출 라인이 없습니다"
        init_line = init_block_match.group(0)
        assert "2>/dev/null" not in init_line, (
            "ante init 호출에서 stderr를 버리고 있습니다 "
            f"(partial-failure 복구 이벤트 소실): {init_line!r}"
        )

        # 2) stderr를 파일/stream에 캡처하는 리다이렉션이 있어야 한다.
        assert re.search(r"2>\s*\"?\$?INIT_STDERR", script) or "2> " in script, (
            "init stderr를 파일에 캡처하는 리다이렉션이 보이지 않습니다"
        )

        # 3) partial-failure 이벤트(master_bootstrap_complete)를 처리하는
        #    분기가 있어야 한다.
        assert "master_bootstrap_complete" in script, (
            "init의 partial-failure stderr 이벤트(master_bootstrap_complete)를 "
            "처리하는 분기가 없습니다"
        )

        # 4) exit code를 || true 로 삼켜버리면 partial-failure와
        #    already_initialized 구분이 불가능하다. init 호출 직후 exit code를
        #    변수에 보관해 분기로 처리해야 한다.
        assert "INIT_EXIT" in script, (
            "init exit code를 변수에 보관해 분기 처리해야 합니다"
        )

    def test_qa_entrypoint_fails_fast_on_non_recoverable_init_error(self) -> None:
        """Finding (Codex 7차 review) — 복구 불가능한 init 실패에서 즉시 종료.

        `ante init`은 여러 exit 1 경로를 가진다:
        - test_account_inactive: default test account가 suspended/deleted 상태
        - bootstrap_failed: master bootstrap 중 예외
        - test_account_failed: partial-failure (stderr 이벤트로 처리됨)
        - already_initialized: 모든 상태 완료 (재기동)

        과거 구현(Codex 6차 fix)은 `master_bootstrap_complete` stderr 이벤트가
        없는 모든 non-zero exit을 "기존 상태 = 재기동"으로 오인해 suspended
        test account 같은 치명적 실패 시에도 서버를 그대로 기동했다.

        이제는 stdout JSON의 `code` 필드로 실패 유형을 구분해
        `already_initialized`만 재기동 경로로 허용하고 그 외는 exit 1 한다.
        """
        script = self.path.read_text()

        # 1) stdout JSON의 code 필드를 파싱하는 분기가 있어야 한다.
        assert "INIT_CODE" in script, (
            "init stdout JSON의 code 필드를 파싱해 분기 처리해야 합니다"
        )

        # 2) already_initialized가 재기동 허용 토큰으로 쓰여야 한다.
        assert "already_initialized" in script, (
            "already_initialized code를 재기동 경로로 허용해야 합니다"
        )

        # 3) 복구 불가능 분기가 exit 1로 종료해야 한다. 분기 블록 안에 FATAL
        #    메시지가 있고 exit 1이 존재해야 한다.
        assert "FATAL" in script, "복구 불가능한 init 실패에 FATAL 로그가 필요합니다"
        assert "exit 1" in script, "복구 불가능한 init 실패에서 즉시 exit 1 해야 합니다"

    def test_qa_entrypoint_only_already_initialized_allows_restart(self) -> None:
        """Codex 7차 review — already_initialized 외의 code는 재기동 금지.

        이 테스트는 분기 순서/구조를 문자열 기반으로 확인한다:
        - INIT_CODE 추출 블록이 있어야 하고
        - `already_initialized`와 같은 비교 조건이 분기 트루 쪽에 있어야 하며
        - 그 반대 (else) 분기에서 exit 1 해야 한다.
        """
        script = self.path.read_text()

        # INIT_CODE 분기 블록 — `if [ "$INIT_CODE" = "already_initialized" ]`
        # 형태가 존재해야 한다.
        assert '"$INIT_CODE" = "already_initialized"' in script, (
            "already_initialized code를 명시적으로 비교하는 분기가 필요합니다"
        )

        # else 분기(복구 불가능)에 exit 1이 있어야 한다. 간단 검증: 분기 블록 안에
        # `else` 및 `exit 1`이 함께 있는지 전체 스크립트에서 확인.
        # 블록 대략적 위치: INIT_CODE 변수 선언 이후 처음 나오는 `exit 1`
        idx_init_code = script.find("INIT_CODE")
        assert idx_init_code != -1
        tail = script[idx_init_code:]
        # else ... exit 1 패턴
        assert "else" in tail and "exit 1" in tail, (
            "INIT_CODE 분기의 else 경로에서 exit 1 해야 합니다"
        )
