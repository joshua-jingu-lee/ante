"""JsonFormatter 단위 테스트.

`docs/specs/logging/03-json-schema.md` 의 JSON 스키마 계약을 검증한다.
"""

from __future__ import annotations

import json
import logging

import pytest

from ante.core.log import JsonFormatter


@pytest.fixture
def formatter() -> JsonFormatter:
    return JsonFormatter()


def _make_record(
    *,
    name: str = "ante.test",
    level: int = logging.INFO,
    msg: str = "hello",
    args: tuple = (),
    exc_info=None,
    extra: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=10,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def _format(formatter: JsonFormatter, record: logging.LogRecord) -> dict:
    line = formatter.format(record)
    # 단일 라인 검증: 내부에 raw 개행 없음
    assert "\n" not in line
    return json.loads(line)


# ── 1. 필수 필드 5종 ───────────────────────────────────────────


def test_required_fields_present(formatter, monkeypatch):
    monkeypatch.delenv("ANTE_ENV", raising=False)
    record = _make_record(name="ante.bot.manager", msg="봇 기동")

    payload = _format(formatter, record)

    assert set(payload.keys()) >= {"ts", "level", "logger", "msg", "env"}
    assert payload["level"] == "INFO"
    assert payload["logger"] == "ante.bot.manager"
    assert payload["msg"] == "봇 기동"
    # ISO 8601 UTC, Z-suffix
    assert payload["ts"].endswith("Z")


# ── 2. ANTE_ENV 기본값 ─────────────────────────────────────────


def test_env_default_production_when_unset(formatter, monkeypatch):
    monkeypatch.delenv("ANTE_ENV", raising=False)
    record = _make_record()

    payload = _format(formatter, record)

    assert payload["env"] == "production"


# ── 3. ANTE_ENV=staging ────────────────────────────────────────


def test_env_reads_ante_env(formatter, monkeypatch):
    monkeypatch.setenv("ANTE_ENV", "staging")
    record = _make_record()

    payload = _format(formatter, record)

    assert payload["env"] == "staging"


# ── 4. 표준 컨텍스트 필드는 최상위로 승격 ──────────────────────


def test_standard_extra_promoted_to_top_level(formatter):
    record = _make_record(extra={"account_id": "abc", "order_id": "ord-1"})

    payload = _format(formatter, record)

    assert payload["account_id"] == "abc"
    assert payload["order_id"] == "ord-1"
    # 표준 키는 extra 하위로 중첩되지 않는다
    assert "extra" not in payload or "account_id" not in payload.get("extra", {})


# ── 5. 비표준 키는 extra 하위로 중첩 ───────────────────────────


def test_nonstandard_extra_nested_in_extra(formatter):
    record = _make_record(extra={"custom_field": "x", "code": 403})

    payload = _format(formatter, record)

    assert "extra" in payload
    assert payload["extra"] == {"custom_field": "x", "code": 403}


# ── 6. 예약 키 (level, logger 등) 은 무시되어 표준 값 유지 ─────


def test_reserved_keys_ignored_from_extra(formatter, monkeypatch):
    """예약 키가 extra 경로로 새어들어와도 표준 값이 유지된다."""
    monkeypatch.setenv("ANTE_ENV", "staging")

    # 실제 호출부는 `logger.error(msg, extra={...})` 경로이므로 setattr로 시뮬레이션.
    # LogRecord 생성 후 예약 키가 속성으로 존재하더라도 payload 최상위는 표준 값을
    # 유지해야 하고, extra 하위로도 새어나가면 안 된다.
    record = _make_record(level=logging.ERROR, msg="hello")
    # msg 제외 예약 키들을 LogRecord 속성으로 주입 시도 (비정상 경로 시뮬레이션)
    record.ts = "0"
    record.env = "fake"
    record.exc = "fake"

    payload = _format(formatter, record)

    # 표준 필드가 유지된다
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "ante.test"
    assert payload["msg"] == "hello"
    assert payload["env"] == "staging"
    assert payload["ts"].endswith("Z")
    # 예약 키는 extra 하위로 새어나가지 않는다
    assert "extra" not in payload


# ── 7. Exception 포함 시 exc 블록 생성 ─────────────────────────


def test_exception_block_populated(formatter):
    try:
        raise ValueError("bad input")
    except ValueError:
        import sys

        exc_info = sys.exc_info()

    record = _make_record(
        name="ante.bot.manager",
        level=logging.ERROR,
        msg="오류 발생",
        exc_info=exc_info,
    )

    payload = _format(formatter, record)

    assert "exc" in payload
    exc = payload["exc"]
    assert exc["type"] == "ValueError"
    assert exc["message"] == "bad input"
    assert "Traceback" in exc["traceback"]
    assert "ValueError" in exc["traceback"]
    # stub fingerprint 형식: {type}@{logger}
    assert exc["fingerprint"] == "ValueError@ante.bot.manager"


# ── 8. 한글 메시지는 비이스케이프로 유지 ───────────────────────


def test_korean_message_not_escaped(formatter):
    record = _make_record(msg="한글 메시지")

    line = formatter.format(record)

    # 원문 한글이 그대로 포함되어야 하며 \uXXXX 이스케이프가 아니어야 한다
    assert "한글 메시지" in line
    assert "\\u" not in line


# ── 9. 단일 라인 보장 (개행 없음) ──────────────────────────────


def test_single_line_output(formatter):
    try:
        raise RuntimeError("line1\nline2")
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()

    record = _make_record(
        msg="멀티라인\n포함",
        exc_info=exc_info,
    )

    line = formatter.format(record)

    # 결과 문자열 내부에 raw 개행이 없어야 한다 (traceback의 개행은 \n으로 이스케이프)
    assert "\n" not in line
    # JSON 파싱이 성공해야 한다
    payload = json.loads(line)
    # 원본 메시지의 개행은 payload["msg"] 내부에서 복원된다
    assert payload["msg"] == "멀티라인\n포함"
