"""ante.cli.commands._password — 랜덤 패스워드 생성 유틸 테스트."""

from __future__ import annotations

import re

from ante.cli.commands._password import generate_password

_ALPHABET_RE = re.compile(r"^[A-Za-z0-9\-_]+$")


class TestGeneratePassword:
    def test_default_length_is_24(self) -> None:
        """인자 없이 호출하면 기본 길이 24."""
        pwd = generate_password()
        assert len(pwd) == 24

    def test_custom_length(self) -> None:
        """length 인자를 명시하면 해당 길이로 생성한다."""
        for n in (8, 12, 32, 64):
            pwd = generate_password(n)
            assert len(pwd) == n, f"길이 {n} 생성 실패: 실제 {len(pwd)}"

    def test_alphabet_is_url_safe(self) -> None:
        """문자셋이 [A-Za-z0-9\\-_]로 제한된다 (shell-safe, URL-safe)."""
        # 여러 번 호출하여 문자셋 커버리지를 넓힘
        for _ in range(50):
            pwd = generate_password(24)
            assert _ALPHABET_RE.match(pwd), f"허용 외 문자 포함: {pwd!r}"

    def test_randomness(self) -> None:
        """매 호출 서로 다른 값을 생성한다 (충돌 확률 무시 가능)."""
        samples = {generate_password() for _ in range(20)}
        # 20번 중 중복 1~2개는 이론상 극히 낮지만, 최소한 대부분은 유일해야 함
        assert len(samples) >= 19
