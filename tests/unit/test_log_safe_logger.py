"""AnteLogger / install_safe_logger() 단위 테스트.

stdlib ``Logger.makeRecord()`` 는 ``extra`` 의 키가 ``LogRecord`` 속성과
충돌하면 ``KeyError`` 를 던진다. ``docs/specs/logging/03-json-schema.md``
§예약어 처리 는 표준 필드가 ``extra=`` 로 주입되어도 무시되어야 한다고
규정하므로, 이를 makeRecord 단계에서 선제 정규화하는 동작을 검증한다.
"""

from __future__ import annotations

import io
import json
import logging

import pytest

from ante.core.log import (
    AnteLogger,
    JsonFormatter,
    install_safe_logger,
    setup_logging,
)


class _StubConfig:
    def __init__(self, values: dict | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default=None):
        return self._values.get(key, default)


@pytest.fixture(autouse=True)
def _restore_logging_state():
    """테스트 간 logging 전역 상태 격리.

    ``install_safe_logger()`` 는 기존 Logger 인스턴스의 ``makeRecord`` 를
    bound-method 로 직접 교체한다. 테스트 격리를 위해 각 테스트 종료 시:
    1. 테스트가 만든 개별 Logger 인스턴스들의 ``makeRecord`` 오버라이드 제거
    2. ``loggerDict`` 를 이전 스냅샷으로 복원
    3. root logger 의 ``makeRecord`` 를 stdlib 구현으로 복원
    4. Logger 클래스를 stdlib ``logging.Logger`` 로 복원
    """
    saved_logger_class = logging.getLoggerClass()
    saved_root_dict = logging.root.__dict__.copy()
    saved_root_level = logging.root.level
    saved_root_handlers = list(logging.root.handlers)
    saved_logger_dict = dict(logging.Logger.manager.loggerDict)

    # 시작 시 순수 stdlib 상태를 보장 — 다른 테스트 스위트가 남긴 오염을 제거
    logging.setLoggerClass(logging.Logger)
    if "makeRecord" in logging.root.__dict__:
        del logging.root.__dict__["makeRecord"]
    for existing in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(existing, logging.Logger) and "makeRecord" in existing.__dict__:
            del existing.__dict__["makeRecord"]

    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)

    try:
        yield
    finally:
        # 개별 Logger 인스턴스의 makeRecord 오버라이드 제거
        for existing in list(logging.Logger.manager.loggerDict.values()):
            if (
                isinstance(existing, logging.Logger)
                and "makeRecord" in existing.__dict__
            ):
                del existing.__dict__["makeRecord"]
        # root logger 복원
        for h in list(logging.root.handlers):
            logging.root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        if "makeRecord" in logging.root.__dict__:
            del logging.root.__dict__["makeRecord"]
        logging.root.__dict__.update(saved_root_dict)
        for h in saved_root_handlers:
            logging.root.addHandler(h)
        logging.root.setLevel(saved_root_level)
        # Logger 클래스 복원
        logging.setLoggerClass(saved_logger_class)
        # loggerDict 복원
        logging.Logger.manager.loggerDict = saved_logger_dict  # type: ignore[assignment]


def _attach_stream(logger: logging.Logger, formatter=None) -> io.StringIO:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter or logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return stream


# ── 0. 사전 조건: stdlib 은 extra={"msg": ...} 에서 KeyError 를 낸다 ──


def test_stdlib_raises_keyerror_on_extra_msg_without_install():
    """설치 전에는 stdlib 이 실제로 KeyError 를 던진다는 베이스라인 확인."""
    logger = logging.getLogger("ante.test.stdlib_baseline")
    _attach_stream(logger)

    with pytest.raises(KeyError, match="msg"):
        logger.info("hi", extra={"msg": "fake"})


# ── 1. install_safe_logger 후 msg 키가 KeyError 없이 처리됨 ─────


def test_install_prevents_keyerror_on_reserved_msg():
    install_safe_logger()
    logger = logging.getLogger("ante.test.install_msg")
    stream = _attach_stream(logger)

    # stdlib 이라면 여기서 KeyError — 설치 후에는 무시되고 정상 로깅
    logger.info("hi", extra={"msg": "fake"})

    assert stream.getvalue().strip() == "hi"


def test_install_prevents_keyerror_on_multiple_logrecord_attrs():
    """msg, args, name, levelname, exc_info, pathname 모두 안전."""
    install_safe_logger()
    logger = logging.getLogger("ante.test.install_many")
    stream = _attach_stream(logger)

    logger.info(
        "hi",
        extra={
            "msg": "fake",
            "args": (1, 2),
            "name": "fake_name",
            "levelname": "FAKE",
            "exc_info": None,
            "pathname": "/fake/path",
            "created": 0,
            "filename": "x",
            "lineno": 99,
        },
    )

    assert stream.getvalue().strip() == "hi"


def test_install_prevents_keyerror_on_ante_reserved_keys():
    """Ante JSONL 예약 키 (ts, level, logger, env, exc) 도 무시된다."""
    install_safe_logger()
    logger = logging.getLogger("ante.test.install_ante_reserved")
    stream = _attach_stream(logger)

    logger.info(
        "hi",
        extra={
            "ts": "fake",
            "level": "FAKE",
            "logger": "fake",
            "env": "fake-env",
            "exc": "fake-exc",
        },
    )

    assert stream.getvalue().strip() == "hi"


# ── 2. 루트 로거도 안전 ────────────────────────────────────────


def test_root_logger_safe_after_install():
    install_safe_logger()
    root = logging.getLogger()
    stream = _attach_stream(root)

    root.info("root-hi", extra={"msg": "fake", "ts": "fake"})

    assert stream.getvalue().strip() == "root-hi"


# ── 3. 이미 캐시된 logger 도 install 후 patch 된다 ─────────────


def test_preexisting_cached_logger_is_patched():
    """install 이전에 만들어진 logger 도 안전해야 한다."""
    logger = logging.getLogger("ante.preexisting.child")
    _attach_stream(logger)

    # 설치 전에는 KeyError
    with pytest.raises(KeyError):
        logger.info("hi", extra={"msg": "fake"})

    install_safe_logger()

    # 설치 후 같은 logger 인스턴스가 안전해야 한다
    logger.info("hi", extra={"msg": "fake", "ts": "fake"})


# ── 4. 정상 extra 필드는 보존된다 ──────────────────────────────


def test_custom_extra_preserved():
    install_safe_logger()
    logger = logging.getLogger("ante.test.custom_extra")
    stream = _attach_stream(logger, formatter=JsonFormatter())

    logger.info(
        "hello",
        extra={
            "account_id": "abc",
            "custom_field": 123,
            "msg": "should_be_ignored",
        },
    )

    payload = json.loads(stream.getvalue().strip())
    assert payload["msg"] == "hello"  # 표준 msg 유지
    assert payload["account_id"] == "abc"  # 표준 컨텍스트 필드 승격
    assert payload.get("extra") == {"custom_field": 123}  # 비표준 키는 extra 하위


# ── 5. setup_logging() 이 install 을 수행 ──────────────────────


def test_setup_logging_installs_safe_logger(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTE_LOG_JSONL", raising=False)
    monkeypatch.chdir(tmp_path)

    # 사전 상태: 순수 Logger 클래스
    logging.setLoggerClass(logging.Logger)

    setup_logging(_StubConfig())

    # setup_logging 후 새 logger 는 AnteLogger
    new_logger = logging.getLogger("ante.test.setup_makes_ante")
    assert isinstance(new_logger, AnteLogger)

    # 실제 호출도 안전
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    new_logger.addHandler(handler)
    new_logger.setLevel(logging.DEBUG)
    new_logger.propagate = False
    new_logger.info("ok", extra={"msg": "fake"})


# ── 6. 재호출 멱등성 ───────────────────────────────────────────


def test_install_is_idempotent():
    install_safe_logger()
    install_safe_logger()
    install_safe_logger()

    logger = logging.getLogger("ante.test.idempotent")
    _attach_stream(logger)
    logger.info("hi", extra={"msg": "fake"})  # 여전히 안전
