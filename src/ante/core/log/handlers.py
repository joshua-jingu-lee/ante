"""커스텀 로그 핸들러."""

from __future__ import annotations

import datetime as _dt
import os
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

_KST: ZoneInfo | None = None


def _get_kst() -> ZoneInfo:
    global _KST
    if _KST is None:
        _KST = ZoneInfo("Asia/Seoul")
    return _KST


class DateNamedTimedRotatingFileHandler(TimedRotatingFileHandler):
    """활성 파일명에 날짜를 직접 포함하는 Asia/Seoul 자정 회전 핸들러.

    파일명 패턴: ``{prefix}-YYYY-MM-DD{file_suffix}`` (예: ``ante-2026-04-19.jsonl``).
    날짜는 **Asia/Seoul** 기준. 자정 회전 시 기존 파일은 그대로 두고(이미 날짜가
    파일명에 포함됨), 새 날짜를 사용해 ``baseFilename`` 을 갱신한 뒤 새 파일을
    연다. ``backupCount`` 를 초과하면 가장 오래된 날짜부터 삭제한다.
    """

    def __init__(
        self,
        log_dir: str | os.PathLike[str],
        *,
        prefix: str = "ante",
        file_suffix: str = ".jsonl",
        backup_count: int = 30,
        encoding: str | None = "utf-8",
        delay: bool = False,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._prefix = prefix
        self._file_suffix = file_suffix

        super().__init__(
            self._make_filename(),
            when="midnight",
            utc=False,
            backupCount=backup_count,
            encoding=encoding,
            delay=delay,
        )

    @staticmethod
    def _now_kst() -> _dt.datetime:
        """현재 시각을 Asia/Seoul tzinfo 로 반환한다."""
        return _dt.datetime.now(_get_kst())

    def _make_filename(self) -> str:
        """현재 날짜(Asia/Seoul) 기준 활성 파일 경로를 반환한다."""
        date_str = self._now_kst().strftime("%Y-%m-%d")
        return str(self._log_dir / f"{self._prefix}-{date_str}{self._file_suffix}")

    def computeRollover(self, currentTime: float) -> int:  # noqa: N802,N803
        """다음 Asia/Seoul 자정(Unix epoch 초) 을 반환한다.

        stdlib 구현은 ``utc`` 플래그에 따라 UTC 또는 local TZ 자정을 계산한다.
        배포 경로마다 TZ 가 달라질 수 있으므로 여기서 KST 를 명시적으로 고정해
        스펙 계약을 코드 레벨에서 보장한다.
        """
        now = _dt.datetime.fromtimestamp(currentTime, tz=_get_kst())
        next_midnight = (now + _dt.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return int(next_midnight.timestamp())

    def doRollover(self) -> None:  # noqa: N802
        """자정 회전: 기존 파일은 유지하고 새 날짜 파일을 연다.

        표준 구현과 달리 ``baseFilename`` 을 rename 하지 않는다. 파일명 자체에
        날짜가 포함되어 있어 현재 파일은 그대로 두고 새 날짜로 핸들을 전환하면
        된다.
        """
        if self.stream is not None:
            self.stream.close()
            self.stream = cast(Any, None)

        self.baseFilename = self._make_filename()
        if not self.delay:
            self.stream = self._open()

        current_time = int(time.time())
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at

        if self.backupCount > 0:
            for path in self._files_to_delete():
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _files_to_delete(self) -> list[str]:
        """``backupCount`` 초과분 중 가장 오래된 파일 경로를 반환한다."""
        pattern = f"{self._prefix}-*{self._file_suffix}"
        candidates = sorted(self._log_dir.glob(pattern))
        try:
            current = Path(self.baseFilename).resolve()
        except OSError:
            current = Path(self.baseFilename)
        filtered: list[Path] = []
        for p in candidates:
            try:
                if p.resolve() == current:
                    continue
            except OSError:
                if str(p) == str(current):
                    continue
            filtered.append(p)

        if len(filtered) <= self.backupCount:
            return []
        excess = len(filtered) - self.backupCount
        return [str(p) for p in filtered[:excess]]
