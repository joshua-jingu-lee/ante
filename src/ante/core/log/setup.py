"""시스템 로깅 핸들러 구성.

`docs/specs/logging/05-handlers-and-rotation.md` 및
`docs/specs/logging/07-implementation.md` 에 정의된 이중 핸들러(stdout 평문 +
환경변수 게이트 기반 JSONL 파일)를 구성한다.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from .formatter import JsonFormatter


def setup_logging(config: Any) -> None:
    """stdout 평문 + (게이트 시) 파일 JSONL 이중 핸들러 구성.

    - stdout: 사람 관찰용 기존 포맷 유지.
    - 파일 JSONL: ``ANTE_LOG_JSONL=1`` 이 설정된 경우에만 활성화,
      ``logs/ante.jsonl`` 에 ``TimedRotatingFileHandler`` 로 일일 회전.
    """
    root = logging.getLogger()
    log_level = config.get("system.log_level", "INFO")
    root.setLevel(getattr(logging, log_level))

    # 기존 핸들러 제거 (재호출 시 중복 방지)
    for h in list(root.handlers):
        root.removeHandler(h)

    # stdout 핸들러 (기존 포맷 유지 — 사람 관찰용)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(stdout_handler)

    # JSONL 파일 핸들러 (환경변수 게이트)
    if os.environ.get("ANTE_LOG_JSONL") == "1":
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "ante.jsonl",
            when="midnight",
            utc=False,
            backupCount=30,
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
