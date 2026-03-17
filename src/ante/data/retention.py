"""Data Pipeline — 데이터 보존 정책. 오래된 데이터 삭제로 용량 관리."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)


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

    async def enforce(self, now: datetime | None = None) -> dict[str, int]:
        """보존 정책 적용. 삭제된 파일 수를 timeframe별로 반환.

        Args:
            now: 기준 시간 (테스트용). None이면 현재 UTC.

        Returns:
            {"1m": 3, "5m": 1, ...} 형태의 삭제 건수
        """
        if now is None:
            now = datetime.now(UTC)

        deleted: dict[str, int] = {}

        for tf, max_days in self._retention.items():
            # -1이면 무기한 보존 → 스킵
            if max_days < 0:
                continue

            count = 0
            symbols = self._store.list_symbols(tf)

            for symbol in symbols:
                date_range = self._store.get_date_range(symbol, tf)
                if not date_range:
                    continue

                # Parquet 파일 순회
                path = self._store.base_path / "ohlcv" / tf / symbol
                if not path.exists():
                    continue

                for parquet_file in sorted(path.glob("*.parquet")):
                    month_str = parquet_file.stem  # "2024-01"
                    try:
                        # 월 파일의 마지막 날을 기준으로 판단
                        year, month = month_str.split("-")
                        # 해당 월의 말일 근사치 (다음달 1일 - 1일)
                        file_month_end = datetime(int(year), int(month), 28, tzinfo=UTC)
                        age_days = (now - file_month_end).days

                        if age_days > max_days:
                            if self._store.delete_file(symbol, tf, month_str):
                                count += 1
                    except (ValueError, IndexError):
                        logger.warning("Invalid parquet filename: %s", parquet_file)
                        continue

            if count > 0:
                deleted[tf] = count
                logger.info("Retention: deleted %d files for timeframe %s", count, tf)

        return deleted
