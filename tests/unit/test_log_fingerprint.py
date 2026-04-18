"""`ante.core.log.fingerprint` 단위 테스트."""

from __future__ import annotations

import sys
import traceback
import types
from pathlib import Path
from unittest.mock import patch

from ante.core.log.fingerprint import _module_path, compute_fingerprint

# ---------------------------------------------------------------------------
# _module_path 단위 테스트
# ---------------------------------------------------------------------------


class TestModulePath:
    """경로 → ante 모듈 표기 변환 규칙 검증."""

    def test_ante_bot_manager_path(self) -> None:
        """/app/src/ante/bot/manager.py -> ante.bot.manager."""
        assert _module_path("/app/src/ante/bot/manager.py") == "ante.bot.manager"

    def test_ante_broker_kis_stream_path(self) -> None:
        """중첩된 서브모듈 경로도 올바르게 변환된다."""
        assert (
            _module_path("/app/src/ante/broker/kis_stream.py")
            == "ante.broker.kis_stream"
        )

    def test_external_stdlib_path_returns_none(self) -> None:
        """표준 라이브러리 경로는 None."""
        assert _module_path("/usr/lib/python3.12/asyncio/tasks.py") is None

    def test_external_third_party_path_returns_none(self) -> None:
        """외부 라이브러리 경로는 None."""
        assert (
            _module_path("/usr/lib/python3.12/site-packages/httpx/_client.py") is None
        )

    def test_non_python_file_returns_none(self) -> None:
        """확장자가 .py가 아니면 None."""
        assert _module_path("/app/src/ante/broker/kis_stream.txt") is None

    def test_path_without_ante_returns_none(self) -> None:
        """ante 세그먼트가 없으면 None."""
        assert _module_path("/app/src/other/module.py") is None


# ---------------------------------------------------------------------------
# compute_fingerprint 테스트 헬퍼
# ---------------------------------------------------------------------------


def _make_tb_from_frames(frames: list[tuple[str, int, str]]) -> types.TracebackType:
    """지정한 (filename, lineno, funcname) 목록으로 실제 ``TracebackType``을 생성한다.

    각 프레임을 ``exec`` 로 실제 실행하여 중첩된 호출 스택을 만들고,
    가장 안쪽에서 예외를 발생시켜 traceback 체인을 얻는다.

    Args:
        frames: ``(filename, lineno, funcname)`` 튜플 리스트.
            첫 원소가 바깥쪽(오래된) 프레임, 마지막 원소가 가장 안쪽(최근) 프레임이다.

    Returns:
        생성된 예외의 ``__traceback__``.
    """
    # 각 프레임을 함수로 정의하고 연쇄 호출한 뒤, 가장 안쪽에서 raise 한다.
    # exec에 전용 code object를 전달해 각 프레임의 filename을 원하는 값으로 지정한다.
    func_names = [fn for (_, _, fn) in frames]

    # 안쪽부터 바깥쪽 순으로 함수 정의를 쌓는다 (호출은 바깥 → 안쪽).
    def make_code(
        filename: str,
        lineno: int,
        funcname: str,
        body: str,
    ) -> types.CodeType:
        # body 앞에 빈 줄을 넣어 lineno 위치에 실제 코드가 오도록 보정한다.
        padding = "\n" * max(lineno - 1, 0)
        source = f"{padding}def {funcname}():\n    {body}\n"
        return compile(source, filename, "exec")

    # 안쪽 함수부터 역순으로 생성하면서 outer가 inner를 호출하도록 구성한다.
    # 가장 안쪽 프레임은 raise 만 수행.
    namespaces: list[dict] = []

    # innermost
    inner_file, inner_line, inner_name = frames[-1]
    inner_ns: dict = {}
    exec(
        make_code(inner_file, inner_line, inner_name, "raise ValueError('boom')"),
        inner_ns,
    )
    namespaces.append(inner_ns)

    # 바깥 프레임들을 역순(안쪽 직전 → 가장 바깥)으로 쌓는다.
    for i in range(len(frames) - 2, -1, -1):
        outer_file, outer_line, outer_name = frames[i]
        inner_callable_name = func_names[i + 1]
        ns: dict = {inner_callable_name: namespaces[-1][inner_callable_name]}
        exec(
            make_code(outer_file, outer_line, outer_name, f"{inner_callable_name}()"),
            ns,
        )
        namespaces.append(ns)

    outermost_ns = namespaces[-1]
    outermost_name = func_names[0]
    try:
        outermost_ns[outermost_name]()
    except ValueError:
        _, _, tb = sys.exc_info()
        assert tb is not None
        return tb

    raise RuntimeError("expected exception was not raised")  # pragma: no cover


# ---------------------------------------------------------------------------
# compute_fingerprint 테스트
# ---------------------------------------------------------------------------


class TestComputeFingerprint:
    """fingerprint 생성 규칙 검증."""

    def test_single_ante_frame(self) -> None:
        """단일 ante 모듈 프레임 → 정상 fingerprint."""
        tb = _make_tb_from_frames(
            [
                ("/app/src/ante/broker/kis_stream.py", 10, "handle_reconnect"),
            ]
        )
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_multiple_ante_frames_picks_most_recent(self) -> None:
        """여러 ante 프레임이 있으면 reversed 첫 번째(가장 안쪽) 선택."""
        tb = _make_tb_from_frames(
            [
                ("/app/src/ante/bot/manager.py", 5, "start"),
                ("/app/src/ante/broker/kis_stream.py", 12, "handle_reconnect"),
            ]
        )
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_external_frame_between_ante_frames(self) -> None:
        """외부 라이브러리 프레임이 가장 안쪽이면 건너뛰고 최근 ante 프레임 선택."""
        tb = _make_tb_from_frames(
            [
                ("/app/src/ante/bot/manager.py", 3, "start"),
                ("/app/src/ante/broker/kis_stream.py", 8, "handle_reconnect"),
                ("/usr/lib/python3.12/asyncio/tasks.py", 20, "run"),
            ]
        )
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_no_ante_frame_falls_back_to_logger_name(self) -> None:
        """ante 프레임이 전혀 없으면 logger_name으로 폴백한다."""
        tb = _make_tb_from_frames(
            [
                ("/usr/lib/python3.12/asyncio/tasks.py", 15, "run"),
                ("/usr/lib/python3.12/site-packages/httpx/_client.py", 42, "send"),
            ]
        )
        result = compute_fingerprint(ValueError, tb, "ante.broker.kis")
        assert result == "ValueError@ante.broker.kis"

    def test_none_traceback_falls_back_to_logger_name(self) -> None:
        """exc_tb가 None이면 logger_name으로 폴백한다."""
        result = compute_fingerprint(RuntimeError, None, "ante.core.log")
        assert result == "RuntimeError@ante.core.log"

    def test_uses_exception_class_name(self) -> None:
        """exception class 이름이 fingerprint 앞에 들어간다 (네임스페이스 제외)."""

        class CustomError(Exception):
            pass

        tb = _make_tb_from_frames(
            [
                ("/app/src/ante/bot/manager.py", 7, "start"),
            ]
        )
        result = compute_fingerprint(CustomError, tb, "ante.bot.manager")
        assert result == "CustomError@ante.bot.manager:start"


# ---------------------------------------------------------------------------
# 실제 예외를 통한 end-to-end 검증
# ---------------------------------------------------------------------------


class TestComputeFingerprintEndToEnd:
    """실제 예외 발생 케이스 검증."""

    def test_real_exception_without_ante_frame_uses_fallback(self) -> None:
        """테스트 코드에서 직접 raise하면 ante 프레임이 없어 폴백한다.

        테스트 파일 경로는 ``tests/unit/test_log_fingerprint.py`` 이므로
        ``ante/`` 접두어 매칭에 걸리지 않는다.
        """
        try:
            raise ConnectionError("simulated connection failure")
        except ConnectionError:
            exc_type, _, exc_tb = sys.exc_info()
            assert exc_type is ConnectionError
            result = compute_fingerprint(exc_type, exc_tb, "ante.broker.kis")

        assert result == "ConnectionError@ante.broker.kis"

    def test_fingerprint_ignores_line_numbers(self) -> None:
        """같은 함수에서 라인 번호가 달라도 동일한 fingerprint를 생성한다."""
        tb1 = _make_tb_from_frames(
            [("/app/src/ante/bot/manager.py", 5, "start")],
        )
        tb2 = _make_tb_from_frames(
            [("/app/src/ante/bot/manager.py", 42, "start")],
        )
        fp1 = compute_fingerprint(ValueError, tb1, "ante.bot.manager")
        fp2 = compute_fingerprint(ValueError, tb2, "ante.bot.manager")
        assert fp1 == fp2 == "ValueError@ante.bot.manager:start"


# ---------------------------------------------------------------------------
# mock 기반 unit test (traceback.extract_tb를 직접 대체)
# ---------------------------------------------------------------------------


class TestComputeFingerprintWithMockedExtract:
    """traceback.extract_tb를 모킹하여 스택 구성을 직접 제어한다.

    실제 TracebackType 생성 경로와 별개로, extract_tb 결과에 따른
    reversed 순회 로직을 독립적으로 검증한다.
    """

    def _make_frame_summary(self, filename: str, name: str) -> traceback.FrameSummary:
        return traceback.FrameSummary(filename, 1, name)

    def test_reversed_iteration_selects_innermost_ante_frame(self) -> None:
        """reversed 순회 시 마지막(=가장 안쪽) ante 프레임이 선택된다."""
        frames = [
            self._make_frame_summary("/app/src/ante/bot/manager.py", "start"),
            self._make_frame_summary(
                "/app/src/ante/broker/kis_stream.py", "handle_reconnect"
            ),
        ]

        # compute_fingerprint 내부의 exc_tb is None 체크를 우회하기 위해
        # 임의의 traceback 객체 + extract_tb patch 조합을 사용한다.
        try:
            raise RuntimeError("sentinel")
        except RuntimeError:
            _, _, fake_tb = sys.exc_info()

        with patch(
            "ante.core.log.fingerprint.traceback.extract_tb",
            return_value=frames,
        ):
            result = compute_fingerprint(ConnectionError, fake_tb, "logger")

        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_skips_external_innermost_frame(self) -> None:
        """가장 안쪽이 외부 프레임이면 건너뛰고 이전 ante 프레임을 선택한다."""
        frames = [
            self._make_frame_summary("/app/src/ante/bot/manager.py", "start"),
            self._make_frame_summary(
                "/usr/lib/python3.12/site-packages/httpx/_client.py", "send"
            ),
        ]

        try:
            raise RuntimeError("sentinel")
        except RuntimeError:
            _, _, fake_tb = sys.exc_info()

        with patch(
            "ante.core.log.fingerprint.traceback.extract_tb",
            return_value=frames,
        ):
            result = compute_fingerprint(ValueError, fake_tb, "logger")

        assert result == "ValueError@ante.bot.manager:start"

    def test_all_external_frames_falls_back(self) -> None:
        """모든 프레임이 외부면 logger_name 폴백."""
        frames = [
            self._make_frame_summary("/usr/lib/python3.12/asyncio/tasks.py", "run"),
            self._make_frame_summary(
                "/usr/lib/python3.12/site-packages/httpx/_client.py", "send"
            ),
        ]

        try:
            raise RuntimeError("sentinel")
        except RuntimeError:
            _, _, fake_tb = sys.exc_info()

        with patch(
            "ante.core.log.fingerprint.traceback.extract_tb",
            return_value=frames,
        ):
            result = compute_fingerprint(ValueError, fake_tb, "ante.broker.kis")

        assert result == "ValueError@ante.broker.kis"


# ---------------------------------------------------------------------------
# Regex 규칙 정상성 - test file 자체 경로로 negative sanity
# ---------------------------------------------------------------------------


def test_tests_unit_path_is_not_matched_as_ante_module() -> None:
    """tests/unit/ 경로는 ante.* 매칭에 걸리지 않아야 한다."""
    here = str(Path(__file__).resolve())
    assert _module_path(here) is None
