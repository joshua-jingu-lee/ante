"""StrategyValidator source-read + AST-parse 단계 4클래스 정규화 회귀 (#1675).

normative invariant (이슈 본문 v6 bounded B):

`StrategyValidator.validate(filepath)` 내부 source-read + AST-parse 단계에서
다음 4클래스 중 하나라도 발생하면 수렴점에서 `ValidationResult(valid=False,
errors=[content-free 안정 메시지], warnings=[])` 를 반환한다. 어떤 경우에도
`str(exception)`/예외 repr/codec명/byte/문자/토큰/소스 라인 텍스트를
`errors[]` 에 포함하지 않는다.

- `UnicodeDecodeError` (=`ValueError` 서브) — `read_text(utf-8)` binary
  실패 → `_NOT_TEXT_SOURCE`
- `OSError` (`IsADirectoryError`/`PermissionError`/race-delete 후
  `FileNotFoundError` 등) — 파일 접근 실패 → `_FILE_NOT_READABLE`
- `SyntaxError` — `ast.parse(...)` → `_syntax_msg(e)` (정수 line/offset)
- `ValueError` (UnicodeDecodeError 외) — source-read/parse 잔여
  → `_NOT_TEXT_SOURCE`

표면: web TestClient (`POST /api/strategies/validate`) + validator 직접 호출.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from unittest import mock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.strategy.validator import (  # noqa: E402
    _FILE_NOT_READABLE,
    _NOT_TEXT_SOURCE,
    StrategyValidator,
    _syntax_msg,
)
from ante.web.app import create_app  # noqa: E402

# ── 픽스처 (test_web_api.py 패턴 미러) ──────────────────────────


@dataclass
class _MasterMember:
    member_id: str = "master-test"
    type: str = "human"
    role: str = "master"
    org: str = "default"
    name: str = "Test Master"
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = dc_field(default_factory=list)


class _MasterOnlyMemberService:
    def __init__(self) -> None:
        self._master = _MasterMember()

    async def authenticate(self, token: str) -> _MasterMember:
        if token != "master-test-token":
            raise PermissionError("invalid token")
        return self._master

    async def get(self, member_id: str) -> _MasterMember | None:
        if member_id == self._master.member_id:
            return self._master
        return None

    async def update_last_active(self, member_id: str) -> None:
        return None


@pytest.fixture
def app():
    return create_app(member_service=_MasterOnlyMemberService())


@pytest.fixture
def client(app):
    test_client = TestClient(app)
    test_client.headers.update({"Authorization": "Bearer master-test-token"})
    return test_client


@pytest.fixture
def validator() -> StrategyValidator:
    return StrategyValidator()


# ── 보조 — no-reflection 단정 ─────────────────────────────────


# 어떤 경우에도 errors[0] 안에 다음 fragments 가 포함되어서는 안 된다 (대소문자
# 무관). 입력 byte/문자/codec/예외 repr/내부 토큰 모두 포함.
_FORBIDDEN_FRAGMENTS = (
    # codec / unicode 식별자
    "codec",
    "utf-8",
    "utf8",
    "can't decode",
    "cannot decode",
    "invalid start byte",
    "invalid continuation byte",
    "0x",
    "u+",
    "\\x",
    "null",
    "position",
    # OSError 식별자
    "isadirectoryerror",
    "permissionerror",
    "filenotfounderror",
    "permission denied",
    "no such file",
    "is a directory",
    "errno",
    # SyntaxError 원문 / 토큰
    "invalid character",
    "invalid syntax",
    "unexpected eof",
    "unterminated",
)


def _assert_no_reflection(
    errors: list[str], extra_forbidden: tuple[str, ...] = ()
) -> None:
    """errors[] 어디에도 입력 byte/codec/예외 repr/내부 토큰 noise 가 없는지 검증."""
    assert len(errors) == 1, f"expected single error, got {errors!r}"
    msg = errors[0]
    haystack = msg.lower()
    for frag in _FORBIDDEN_FRAGMENTS + tuple(f.lower() for f in extra_forbidden):
        assert frag not in haystack, (
            f"errors[0] reflected forbidden fragment {frag!r}: {msg!r}"
        )


def _post_validate(client: TestClient, path: str | os.PathLike[str]) -> dict:
    resp = client.post("/api/strategies/validate", json={"path": str(path)})
    return {"status": resp.status_code, "body": resp.json()}


# ── 4클래스 매트릭스 — validator 직접 호출 ─────────────────────


class TestUnicodeDecodeError:
    """UnicodeDecodeError (=ValueError 서브) — read_text(utf-8) binary 입력."""

    def test_invalid_utf8_bytes_direct(self, validator, tmp_path):
        """`b"\\xff\\xfe\\x00\\x01"` 같은 비 UTF-8 binary."""
        path = tmp_path / "bin.py"
        path.write_bytes(b"\xff\xfe\x00\x01\xff\xfe")

        result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert result.errors == [_NOT_TEXT_SOURCE]
        _assert_no_reflection(
            result.errors,
            extra_forbidden=("\\xff", "\\xfe", "ÿ", "þ"),
        )

    def test_invalid_utf8_bytes_web(self, client, tmp_path):
        path = tmp_path / "bin.py"
        path.write_bytes(b"\xff\xfe\x00\x01\xff\xfe")

        resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert resp["body"]["errors"] == [_NOT_TEXT_SOURCE]
        _assert_no_reflection(resp["body"]["errors"])

    def test_utf8_decodable_nul_byte_direct(self, validator, tmp_path):
        """`b"SQLite format 3\\x00rest"` — UTF-8 디코드는 되지만 SyntaxError(NUL).

        AST parser 가 NUL 을 만나면 `SyntaxError(source code cannot contain
        null bytes)` 를 발생시킨다. 본 매트릭스에서는 `SyntaxError → _syntax_msg`
        경로로 잡혀야 하고, 원문 `SQLite` 토큰은 절대 노출되어서는 안 된다.
        """
        path = tmp_path / "sqlite_hdr.py"
        path.write_bytes(b"SQLite format 3\x00rest")

        result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        # SyntaxError → _syntax_msg(line, offset) 형식
        assert len(result.errors) == 1
        assert re.fullmatch(
            r"Syntax error \(line \d+, offset \d+\)", result.errors[0]
        ), result.errors
        _assert_no_reflection(
            result.errors,
            extra_forbidden=("SQLite", "format 3", "rest", "\\x00"),
        )

    def test_utf8_decodable_nul_byte_web(self, client, tmp_path):
        path = tmp_path / "sqlite_hdr.py"
        path.write_bytes(b"SQLite format 3\x00rest")

        resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert len(resp["body"]["errors"]) == 1
        assert re.fullmatch(
            r"Syntax error \(line \d+, offset \d+\)", resp["body"]["errors"][0]
        )
        _assert_no_reflection(
            resp["body"]["errors"],
            extra_forbidden=("SQLite", "format 3", "rest"),
        )


class TestOSErrorClass:
    """OSError 계열 — IsADirectoryError / PermissionError / race FileNotFoundError."""

    def test_directory_path_direct(self, validator, tmp_path):
        """디렉터리 path — `IsADirectoryError` (OSError 서브)."""
        # tmp_path 자체가 디렉터리
        result = validator.validate(tmp_path)

        assert result.valid is False
        assert result.warnings == []
        assert result.errors == [_FILE_NOT_READABLE]
        _assert_no_reflection(result.errors, extra_forbidden=(str(tmp_path),))

    def test_directory_path_web(self, client, tmp_path):
        """web 경로 — 디렉터리는 `path.exists()` 를 통과하므로 validator 까지 도달."""
        resp = _post_validate(client, tmp_path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert resp["body"]["errors"] == [_FILE_NOT_READABLE]
        _assert_no_reflection(resp["body"]["errors"], extra_forbidden=(str(tmp_path),))

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="chmod 000 unreadable file path requires non-root POSIX",
    )
    def test_permission_denied_direct(self, validator, tmp_path):
        """`chmod 000` 권한 없는 파일 — `PermissionError` (OSError 서브)."""
        path = tmp_path / "locked.py"
        path.write_text("class Foo: pass\n")
        path.chmod(0o000)
        try:
            result = validator.validate(path)
        finally:
            # cleanup 을 위해 권한 복구
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        assert result.valid is False
        assert result.warnings == []
        assert result.errors == [_FILE_NOT_READABLE]
        _assert_no_reflection(result.errors, extra_forbidden=(str(path),))

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason="chmod 000 unreadable file path requires non-root POSIX",
    )
    def test_permission_denied_web(self, client, tmp_path):
        path = tmp_path / "locked.py"
        path.write_text("class Foo: pass\n")
        path.chmod(0o000)
        try:
            resp = _post_validate(client, path)
        finally:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert resp["body"]["errors"] == [_FILE_NOT_READABLE]
        _assert_no_reflection(resp["body"]["errors"])

    def test_race_delete_direct(self, validator, tmp_path):
        """race-delete after exists check — `Path.read_text` 가
        `FileNotFoundError` 를 던지는 시나리오 (OSError 서브) — mock 으로 재현.
        """
        path = tmp_path / "ghost.py"
        path.write_text("class Foo: pass\n")  # 일단 생성 (exists 통과용)

        with mock.patch.object(
            Path,
            "read_text",
            side_effect=FileNotFoundError(2, "No such file or directory"),
        ):
            result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert result.errors == [_FILE_NOT_READABLE]
        _assert_no_reflection(result.errors, extra_forbidden=(str(path),))

    def test_race_delete_web(self, client, tmp_path):
        """web 경로 — 라우트의 `path.exists()` 는 통과해야 validator 까지 도달.
        validator 내부 `read_text` 만 `FileNotFoundError` 로 mock 한다.
        """
        path = tmp_path / "ghost.py"
        path.write_text("class Foo: pass\n")

        with mock.patch.object(
            Path,
            "read_text",
            side_effect=FileNotFoundError(2, "No such file or directory"),
        ):
            resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert resp["body"]["errors"] == [_FILE_NOT_READABLE]
        _assert_no_reflection(resp["body"]["errors"])


class TestSyntaxErrorClass:
    """SyntaxError — `ast.parse` 실패. 정수 line/offset 만 노출."""

    def test_emoji_nul_free_direct(self, validator, tmp_path):
        """NUL-free emoji `"😀"` — invalid character syntax error.

        `_syntax_msg` 가 정수 line/offset 만 노출하고, 원문 `😀` 또는
        `U+1F600` codepoint 가 절대 노출되어서는 안 된다.
        """
        path = tmp_path / "emoji.py"
        path.write_text("😀")

        result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert len(result.errors) == 1
        assert re.fullmatch(r"Syntax error \(line \d+, offset \d+\)", result.errors[0])
        _assert_no_reflection(result.errors, extra_forbidden=("😀", "U+1F600", "1f600"))

    def test_emoji_nul_free_web(self, client, tmp_path):
        path = tmp_path / "emoji.py"
        path.write_text("😀")

        resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert len(resp["body"]["errors"]) == 1
        assert re.fullmatch(
            r"Syntax error \(line \d+, offset \d+\)", resp["body"]["errors"][0]
        )
        _assert_no_reflection(
            resp["body"]["errors"], extra_forbidden=("😀", "U+1F600", "1f600")
        )

    def test_garbage_tokens_direct(self, validator, tmp_path):
        """NUL-free garbage `"$$$ not python @@@"` — 토큰 부재."""
        path = tmp_path / "garbage.py"
        path.write_text("$$$ not python @@@")

        result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert len(result.errors) == 1
        assert re.fullmatch(r"Syntax error \(line \d+, offset \d+\)", result.errors[0])
        _assert_no_reflection(
            result.errors,
            extra_forbidden=("$$$", "@@@", "not python"),
        )

    def test_garbage_tokens_web(self, client, tmp_path):
        path = tmp_path / "garbage.py"
        path.write_text("$$$ not python @@@")

        resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert len(resp["body"]["errors"]) == 1
        assert re.fullmatch(
            r"Syntax error \(line \d+, offset \d+\)", resp["body"]["errors"][0]
        )
        _assert_no_reflection(
            resp["body"]["errors"],
            extra_forbidden=("$$$", "@@@", "not python"),
        )

    def test_typo_direct(self, validator, tmp_path):
        """사용자 typo `.py` `"def f(:"` — 위치 정수만."""
        path = tmp_path / "typo.py"
        path.write_text("def f(:")

        result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert len(result.errors) == 1
        assert re.fullmatch(r"Syntax error \(line \d+, offset \d+\)", result.errors[0])
        # 메시지 형식 자체에 `(`/`:` 가 들어있으므로 입력 원문 fragment 만 단정
        _assert_no_reflection(result.errors, extra_forbidden=("def f", "def "))

    def test_typo_web(self, client, tmp_path):
        path = tmp_path / "typo.py"
        path.write_text("def f(:")

        resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert len(resp["body"]["errors"]) == 1
        assert re.fullmatch(
            r"Syntax error \(line \d+, offset \d+\)", resp["body"]["errors"][0]
        )
        _assert_no_reflection(resp["body"]["errors"], extra_forbidden=("def f(:",))

    def test_syntax_msg_helper_none_lineno(self):
        """`SyntaxError.lineno`/`.offset` 가 `None` 이면 `0` 으로 fallback."""
        e = SyntaxError("anything")
        e.lineno = None
        e.offset = None
        assert _syntax_msg(e) == "Syntax error (line 0, offset 0)"

    def test_syntax_msg_helper_integer_only(self):
        """`_syntax_msg` 는 정수 line/offset 만 노출 — `str(e)`/text 없음."""
        e = SyntaxError("unexpected token 'foo'")
        e.lineno = 3
        e.offset = 7
        msg = _syntax_msg(e)
        assert msg == "Syntax error (line 3, offset 7)"
        # 원문 noise 부재
        assert "unexpected token" not in msg
        assert "foo" not in msg


class TestValueErrorResidual:
    """ValueError (UnicodeDecodeError 외) — read_text/parse 잔여."""

    def test_residual_value_error_direct(self, validator, tmp_path):
        """드문 잔여 ValueError 시나리오 — mock 으로 재현."""
        path = tmp_path / "ok.py"
        path.write_text("class Foo: pass\n")

        with mock.patch.object(
            Path, "read_text", side_effect=ValueError("some weird value error")
        ):
            result = validator.validate(path)

        assert result.valid is False
        assert result.warnings == []
        assert result.errors == [_NOT_TEXT_SOURCE]
        _assert_no_reflection(
            result.errors,
            extra_forbidden=("some weird value error", "valueerror"),
        )

    def test_residual_value_error_web(self, client, tmp_path):
        path = tmp_path / "ok.py"
        path.write_text("class Foo: pass\n")

        with mock.patch.object(
            Path, "read_text", side_effect=ValueError("some weird value error")
        ):
            resp = _post_validate(client, path)

        assert resp["status"] == 200
        assert resp["body"]["valid"] is False
        assert resp["body"]["warnings"] == []
        assert resp["body"]["errors"] == [_NOT_TEXT_SOURCE]
        _assert_no_reflection(
            resp["body"]["errors"],
            extra_forbidden=("some weird value error", "valueerror"),
        )


# ── OUT-OF-SCOPE — semantic 메시지는 actionable, no-reflection 미주장 ─


class TestSemanticActionable:
    """semantic 단계 메시지는 의도된 actionable 계약(클래스명/exchange/모듈 등).

    no-reflection invariant 매트릭스 OUT-OF-SCOPE — 본 테스트는 회귀 락이다
    (semantic 단계가 v6 교체로 깨지지 않는지).
    """

    def test_valid_python_non_strategy_direct(self, validator, tmp_path):
        """valid-Python 非전략 `'{"a":1}'` — 파싱 OK, semantic 단계에서 거부."""
        path = tmp_path / "nonstrategy.py"
        path.write_text('{"a":1}\n')

        result = validator.validate(path)

        assert result.valid is False
        # semantic 메시지는 식별자 명시 — actionable
        assert any("No class" in e for e in result.errors), result.errors

    def test_valid_strategy_regression_direct(self, validator, tmp_path):
        """정상 전략 회귀 — valid=true."""
        code = (
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class TestStrategy(Strategy):\n"
            "    meta = StrategyMeta(name='t', version='1.0.0', description='t')\n"
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        path = tmp_path / "ok.py"
        path.write_text(code)

        result = validator.validate(path)

        assert result.valid is True, result.errors
        assert result.errors == []

    def test_valid_strategy_regression_web(self, client, tmp_path):
        code = (
            "from ante.strategy import Strategy, StrategyMeta\n"
            "\n"
            "class TestStrategy(Strategy):\n"
            "    meta = StrategyMeta(name='t', version='1.0.0', description='t')\n"
            "\n"
            "    async def on_step(self, context):\n"
            "        return []\n"
        )
        path = tmp_path / "ok.py"
        path.write_text(code)

        resp = _post_validate(client, path)
        assert resp["status"] == 200
        assert resp["body"]["valid"] is True
        assert resp["body"]["errors"] == []


# ── route 분기 회귀 (route-level 무변경 확인) ─────────────────


class TestRouteUnchanged:
    """web 라우트 분기가 본 이슈로 흔들리지 않는지 확인 (Non-Goal 회귀 락)."""

    def test_nonexistent_path_web_returns_404(self, client):
        """미존재 path — route 의 `path.exists()` 가 404 로 거부 (validator 미도달)."""
        resp = client.post(
            "/api/strategies/validate",
            json={"path": "/definitely/does/not/exist.py"},
        )
        assert resp.status_code == 404


# ── self-check: constants are content-free fixed strings ────


def test_constants_are_content_free():
    """두 상수는 codec/byte/path/repr 자유 고정 상수임을 self-check."""
    for s in (_NOT_TEXT_SOURCE, _FILE_NOT_READABLE):
        low = s.lower()
        for frag in _FORBIDDEN_FRAGMENTS:
            assert frag not in low, (
                f"constant {s!r} contains forbidden fragment {frag!r}"
            )
        # 동적 포맷 마커 부재
        assert "{" not in s and "}" not in s, (
            f"constant {s!r} contains format placeholder"
        )
