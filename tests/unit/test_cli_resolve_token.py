"""_resolve_token 함수 단위 테스트 — 환경변수 및 토큰 파일 우선순위."""

from __future__ import annotations

import os
from unittest.mock import patch

from ante.cli.middleware import _resolve_token


class TestResolveToken:
    """토큰 해석 우선순위 테스트."""

    def test_env_var_takes_precedence(self, tmp_path):
        """ANTE_MEMBER_TOKEN 환경변수가 있으면 파일을 읽지 않는다."""
        token_file = tmp_path / "token"
        token_file.write_text("file_token")
        with patch.dict(
            os.environ,
            {"ANTE_MEMBER_TOKEN": "env_token", "ANTE_TOKEN_FILE": str(token_file)},
        ):
            assert _resolve_token() == "env_token"

    def test_token_file_via_env(self, tmp_path):
        """ANTE_TOKEN_FILE이 가리키는 파일에서 토큰을 읽는다."""
        token_file = tmp_path / "token"
        token_file.write_text("file_token_custom")
        with patch.dict(
            os.environ,
            {"ANTE_MEMBER_TOKEN": "", "ANTE_TOKEN_FILE": str(token_file)},
            clear=False,
        ):
            # 환경변수 제거
            env = os.environ.copy()
            env.pop("ANTE_MEMBER_TOKEN", None)
            with patch.dict(os.environ, env, clear=True):
                os.environ["ANTE_TOKEN_FILE"] = str(token_file)
                assert _resolve_token() == "file_token_custom"

    def test_default_token_file(self, tmp_path, monkeypatch):
        """ANTE_TOKEN_FILE도 없으면 /run/ante-token을 시도한다."""
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.delenv("ANTE_TOKEN_FILE", raising=False)
        # /run/ante-token은 테스트 환경에서 없으므로 빈 문자열 반환
        assert _resolve_token() == ""

    def test_token_file_strips_whitespace(self, tmp_path, monkeypatch):
        """토큰 파일의 앞뒤 공백/개행을 제거한다."""
        token_file = tmp_path / "token"
        token_file.write_text("  ante_token_abc123  \n")
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(token_file))
        assert _resolve_token() == "ante_token_abc123"

    def test_missing_token_file_returns_empty(self, tmp_path, monkeypatch):
        """토큰 파일이 없으면 빈 문자열을 반환한다."""
        monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
        monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "nonexistent"))
        assert _resolve_token() == ""
