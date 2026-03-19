"""Data Pipeline — 데이터 보존 정책. 오래된 데이터 삭제로 용량 관리."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)

# OHLCV 타임프레임 집합 — retention key가 여기 속하면 data_type="ohlcv"
_OHLCV_TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "15m", "1h", "1d"})


def _resolve_data_type(key: str) -> tuple[str, str]:
    """retention key를 (data_type, timeframe) 튜플로 변환.

    Args:
        key: retention 딕셔너리의 키 (예: "1m", "fundamental")

    Returns:
        (data_type, timeframe) — 예: ("ohlcv", "1m"), ("fundamental", "")
    """
    if key in _OHLCV_TIMEFRAMES:
        return ("ohlcv", key)
    return (key, "")


class RetentionPolicy:
    """데이터 보존 정책 — 오래된 데이터 삭제로 용량 관리.

    타임프레임별로 보존 기간을 설정하고, 초과된 데이터를 자동 삭제한다.
    -1은 무기한 보존을 의미한다.
    """

    DEFAULT_RETENTION: dict[str, int] = {
        "1m": 365,  # 1분봉: 365일
        "5m": 365,  # 5분봉: 365일
        "15m": 365,  # 15분봉: 365일
        "1h": 365,  # 1시간봉: 365일
        "1d": 3650,  # 일봉: 10년
        "fundamental": -1,  # 재무데이터: 무기한
    }

    def __init__(
        self,
        store: ParquetStore,
        retention_days: dict[str, int] | None = None,
    ) -> None:
        self._store = store
        self._retention = retention_days or self.DEFAULT_RETENTION.copy()

    @property
    def retention_days(self) -> dict[str, int]:
        return self._retention

    def enforce(self, now: datetime | None = None) -> dict[str, int]:
        """보존 정책 적용. 삭제된 파일 수를 timeframe별로 반환.

        Args:
            now: 기준 시간 (테스트용). None이면 현재 UTC.

        Returns:
            {"1m": 3, "5m": 1, ...} 형태의 삭제 건수
        """
        if now is None:
            now = datetime.now(UTC)

        deleted: dict[str, int] = {}

        for key, max_days in self._retention.items():
            # -1이면 무기한 보존 → 스킵
            if max_days < 0:
                continue

            count = self._enforce_age(key, max_days, now)
            if count > 0:
                deleted[key] = count
                logger.info("Retention: deleted %d files for %s", count, key)

        return deleted

    def _enforce_age(self, key: str, max_days: int, now: datetime) -> int:
        """기간 기반 보존 정책: max_days 초과 파일 삭제.

        Args:
            key: retention 딕셔너리 키 (예: "1m", "fundamental")
            max_days: 보존 일수
            now: 기준 시간

        Returns:
            삭제된 파일 수
        """
        data_type, timeframe = _resolve_data_type(key)
        count = 0
        symbols = self._store.list_symbols(timeframe, data_type=data_type)

        for symbol in symbols:
            count += self._delete_expired_files(
                symbol, timeframe, data_type, max_days, now
            )

        return count

    def _delete_expired_files(
        self,
        symbol: str,
        timeframe: str,
        data_type: str,
        max_days: int,
        now: datetime,
    ) -> int:
        """심볼 하나의 만료 파일 삭제.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임 (예: "1m", "")
            data_type: 데이터 타입 (예: "ohlcv", "fundamental")
            max_days: 보존 일수
            now: 기준 시간

        Returns:
            삭제된 파일 수
        """
        date_range = self._store.get_date_range(symbol, timeframe, data_type=data_type)
        if not date_range:
            return 0

        path = self._store._resolve_path(symbol, timeframe, data_type)
        if not path.exists():
            return 0

        count = 0
        for parquet_file in sorted(path.glob("*.parquet")):
            if self._is_expired(parquet_file.stem, max_days, now):
                if self._store.delete_file(
                    symbol, timeframe, parquet_file.stem, data_type=data_type
                ):
                    count += 1
        return count

    @staticmethod
    def _is_expired(month_str: str, max_days: int, now: datetime) -> bool:
        """월별 parquet 파일이 보존 기간을 초과했는지 판단.

        Args:
            month_str: 파일명 stem (예: "2024-01")
            max_days: 보존 일수
            now: 기준 시간

        Returns:
            보존 기간 초과 여부
        """
        try:
            year, month = month_str.split("-")
            file_month_end = datetime(int(year), int(month), 28, tzinfo=UTC)
            age_days = (now - file_month_end).days
            return age_days > max_days
        except (ValueError, IndexError):
            logger.warning("Invalid parquet filename: %s.parquet", month_str)
            return False
