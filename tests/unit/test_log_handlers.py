"""DateNamedTimedRotatingFileHandler 회귀 테스트.

주된 계약 (`docs/specs/logging/05-handlers-and-rotation.md` §회전 규칙):
- 파일명은 Asia/Seoul 날짜 기준 `ante-YYYY-MM-DD.jsonl`.
- `computeRollover` 는 호스트/컨테이너 TZ 와 무관하게 다음 KST 자정을
  Unix epoch 초로 돌려준다.
- 자정 회전 시 기존 파일은 rename 되지 않고 새 날짜로 핸들을 전환한다.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from zoneinfo import ZoneInfo

from ante.core.log.handlers import DateNamedTimedRotatingFileHandler


def test_filename_uses_kst_date_regardless_of_host_tz(tmp_path: Path) -> None:
    """호스트 TZ 가 UTC 등 다른 값이어도 파일명은 KST 날짜를 따른다."""
    handler = DateNamedTimedRotatingFileHandler(
        tmp_path, prefix="ante", file_suffix=".jsonl", backup_count=30
    )
    try:
        expected_date = _dt.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
        assert handler.baseFilename.endswith(f"ante-{expected_date}.jsonl")
    finally:
        handler.close()


def test_compute_rollover_returns_next_kst_midnight(tmp_path: Path) -> None:
    """임의의 현재 시각에 대해 다음 Asia/Seoul 자정을 Unix epoch 으로 반환한다.

    케이스: KST 기준 정오(12:00). 다음 자정까지 12 시간 남음.
    """
    handler = DateNamedTimedRotatingFileHandler(tmp_path)
    try:
        kst = ZoneInfo("Asia/Seoul")
        noon_kst = _dt.datetime(2026, 4, 17, 12, 0, 0, tzinfo=kst)
        next_midnight_kst = _dt.datetime(2026, 4, 18, 0, 0, 0, tzinfo=kst)

        actual = handler.computeRollover(noon_kst.timestamp())
        assert actual == int(next_midnight_kst.timestamp())
    finally:
        handler.close()


def test_compute_rollover_crosses_utc_day_boundary(tmp_path: Path) -> None:
    """UTC 자정과 KST 자정이 불일치하는 경계에서 올바르게 KST 기준으로 회전한다.

    UTC 23:00 (= KST 08:00) 에서 호출하면 다음 KST 자정(16 시간 후) 을 반환한다.
    """
    handler = DateNamedTimedRotatingFileHandler(tmp_path)
    try:
        utc = ZoneInfo("UTC")
        kst = ZoneInfo("Asia/Seoul")
        # 2026-04-17 23:00 UTC == 2026-04-18 08:00 KST
        probe_utc = _dt.datetime(2026, 4, 17, 23, 0, 0, tzinfo=utc)
        # 다음 KST 자정은 2026-04-19 00:00 KST == 2026-04-18 15:00 UTC
        next_midnight_kst = _dt.datetime(2026, 4, 19, 0, 0, 0, tzinfo=kst)

        actual = handler.computeRollover(probe_utc.timestamp())
        assert actual == int(next_midnight_kst.timestamp())
    finally:
        handler.close()


def test_rollover_does_not_rename_existing_file(tmp_path: Path) -> None:
    """자정 회전 시 기존 파일은 rename 되지 않고 새 날짜 파일이 생성된다."""
    handler = DateNamedTimedRotatingFileHandler(tmp_path, backup_count=30)
    try:
        original_path = Path(handler.baseFilename)
        # 핸들러가 파일에 한 줄 쓰도록 직접 스트림에 기록
        handler.stream.write('{"msg":"original"}\n')
        handler.stream.flush()
        assert original_path.exists()

        # 다음 날로 전환하도록 파일명 헬퍼를 가로챈다
        fake_next = tmp_path / "ante-9999-12-31.jsonl"
        handler._make_filename = lambda: str(fake_next)  # type: ignore[method-assign]

        handler.doRollover()

        # 기존 파일은 rename 되지 않고 그대로 남아 있어야 한다
        assert original_path.exists()
        assert original_path.read_text().strip() == '{"msg":"original"}'
        # 새 파일명이 활성 baseFilename 이 된다
        assert handler.baseFilename == str(fake_next)
    finally:
        handler.close()
