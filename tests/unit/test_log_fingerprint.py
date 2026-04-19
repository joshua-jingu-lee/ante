"""`ante.core.log.fingerprint` 단위 테스트."""

from __future__ import annotations

import sys
import types

from ante.core.log.fingerprint import compute_fingerprint

# ---------------------------------------------------------------------------
# 테스트 헬퍼
# ---------------------------------------------------------------------------


def _make_tb_with_modules(
    frames: list[tuple[str, str]],
) -> types.TracebackType:
    """지정한 (module_name, func_name) 목록으로 traceback을 생성한다.

    각 프레임을 ``exec`` 로 실행하되, 전달하는 namespace에 ``__name__``을
    원하는 모듈명으로 설정한다. 이렇게 하면 ``frame.f_globals['__name__']``이
    지정한 값을 반환하므로, 파일 경로와 무관하게 모듈 식별을 테스트할 수 있다.

    Args:
        frames: ``(module_name, func_name)`` 튜플 리스트.
            첫 원소가 바깥쪽(오래된) 프레임, 마지막이 가장 안쪽(최근) 프레임이다.

    Returns:
        생성된 예외의 ``__traceback__``.
    """
    func_names = [fn for (_, fn) in frames]

    # 가장 안쪽 프레임: raise 만 수행
    inner_module, inner_name = frames[-1]
    inner_ns: dict = {"__name__": inner_module}
    exec(
        compile(
            f"def {inner_name}():\n    raise ValueError('boom')",
            f"<{inner_module}>",
            "exec",
        ),
        inner_ns,
    )

    # 바깥 프레임들을 안쪽 → 바깥 순서로 쌓는다
    chain_ns = [inner_ns]
    for i in range(len(frames) - 2, -1, -1):
        outer_module, outer_name = frames[i]
        inner_callable_name = func_names[i + 1]
        ns: dict = {
            "__name__": outer_module,
            inner_callable_name: chain_ns[-1][inner_callable_name],
        }
        exec(
            compile(
                f"def {outer_name}():\n    {inner_callable_name}()",
                f"<{outer_module}>",
                "exec",
            ),
            ns,
        )
        chain_ns.append(ns)

    outermost_ns = chain_ns[-1]
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
        tb = _make_tb_with_modules([("ante.broker.kis_stream", "handle_reconnect")])
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_multiple_ante_frames_picks_most_recent(self) -> None:
        """여러 ante 프레임이 있으면 가장 최근(깊은) 프레임 선택."""
        tb = _make_tb_with_modules(
            [
                ("ante.bot.manager", "start"),
                ("ante.broker.kis_stream", "handle_reconnect"),
            ]
        )
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_external_frame_between_ante_frames(self) -> None:
        """외부 프레임이 가장 안쪽이면 건너뛰고 최근 ante 프레임 선택."""
        tb = _make_tb_with_modules(
            [
                ("ante.bot.manager", "start"),
                ("ante.broker.kis_stream", "handle_reconnect"),
                ("asyncio.tasks", "run"),
            ]
        )
        result = compute_fingerprint(ConnectionError, tb, "ante.broker.kis_stream")
        assert result == "ConnectionError@ante.broker.kis_stream:handle_reconnect"

    def test_no_ante_frame_falls_back_to_logger_name(self) -> None:
        """ante 프레임이 전혀 없으면 logger_name으로 폴백한다."""
        tb = _make_tb_with_modules(
            [
                ("asyncio.tasks", "run"),
                ("httpx._client", "send"),
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

        tb = _make_tb_with_modules([("ante.bot.manager", "start")])
        result = compute_fingerprint(CustomError, tb, "ante.bot.manager")
        assert result == "CustomError@ante.bot.manager:start"

    def test_fingerprint_ignores_line_numbers(self) -> None:
        """같은 함수에서 라인이 달라도 동일한 fingerprint가 생성된다."""
        tb1 = _make_tb_with_modules([("ante.bot.manager", "start")])
        tb2 = _make_tb_with_modules([("ante.bot.manager", "start")])
        fp1 = compute_fingerprint(ValueError, tb1, "ante.bot.manager")
        fp2 = compute_fingerprint(ValueError, tb2, "ante.bot.manager")
        assert fp1 == fp2 == "ValueError@ante.bot.manager:start"

    def test_ante_root_module_is_matched(self) -> None:
        """모듈명이 'ante' 그 자체여도 매칭된다."""
        tb = _make_tb_with_modules([("ante", "some_func")])
        result = compute_fingerprint(ValueError, tb, "ante")
        assert result == "ValueError@ante:some_func"


# ---------------------------------------------------------------------------
# 실제 예외를 통한 end-to-end 검증
# ---------------------------------------------------------------------------


class TestComputeFingerprintEndToEnd:
    """실제 예외 발생 케이스 검증."""

    def test_real_exception_without_ante_frame_uses_fallback(self) -> None:
        """테스트 코드에서 직접 raise하면 ante 프레임이 없어 폴백한다.

        이 테스트 파일의 ``f_globals['__name__']``은 ``tests.unit.test_log_fingerprint``
        이므로 ``ante.`` 조건에 걸리지 않는다.
        """
        try:
            raise ConnectionError("simulated connection failure")
        except ConnectionError:
            exc_type, _, exc_tb = sys.exc_info()
            assert exc_type is ConnectionError
            result = compute_fingerprint(exc_type, exc_tb, "ante.broker.kis")

        assert result == "ConnectionError@ante.broker.kis"

    def test_checkout_path_does_not_confuse_module_detection(self) -> None:
        """프로젝트 체크아웃 경로에 'ante'가 포함되어도 모듈 탐지가 혼동되지 않는다.

        파일 경로 대신 ``f_globals['__name__']``을 사용하므로,
        '/Users/.../ante/src/ante/...' 같은 경로의 경우에도 테스트 모듈은
        ante.* 모듈로 오판되지 않는다.
        """
        try:
            raise ValueError("path confusion test")
        except ValueError:
            exc_type, _, exc_tb = sys.exc_info()
            result = compute_fingerprint(exc_type, exc_tb, "ante.test.logger")

        # 이 테스트 프레임은 ante.* 모듈이 아니므로 폴백
        assert result == "ValueError@ante.test.logger"
