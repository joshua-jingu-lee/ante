"""CSV 파일에서 데이터를 수동 주입하는 모듈 (ante feed inject)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FeedInjector:
    """외부 CSV 파일에서 과거 데이터를 DataStore에 주입한다.

    동작 순서:
      1. CSV 파일 로드
      2. Normalizer로 스키마 정규화 (source에 따라 선택)
      3. 4계층 검증 (transform/validate.py)
      4. ParquetStore.write()로 저장
    """

    def inject_csv(
        self,
        path: Path,
        symbol: str,
        timeframe: str = "1d",
        source: str = "external",
        data_path: str = "data/",
    ) -> int:
        """CSV 파일을 읽어 DataStore에 주입한다.

        Args:
            path: CSV 파일 경로.
            symbol: 종목 코드 (6자리).
            timeframe: 타임프레임 (기본값: '1d').
            source: 데이터 소스 식별자 (normalizer 선택에 사용).
            data_path: 데이터 저장 디렉토리 경로.

        Returns:
            주입된 행 수.
        """
        ...
