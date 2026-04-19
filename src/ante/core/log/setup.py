"""시스템 로깅 핸들러 구성.

`docs/specs/logging/05-handlers-and-rotation.md` 및
`docs/specs/logging/07-implementation.md` 에 정의된 이중 핸들러(stdout 평문 +
환경변수 게이트 기반 JSONL 파일)를 구성한다.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from .formatter import JsonFormatter
from .handlers import DateNamedTimedRotatingFileHandler
from .safe_logger import install_safe_logger


def setup_logging(config: Any) -> None:
    """stdout 평문 + (게이트 시) 파일 JSONL 이중 핸들러 구성.

    - stdout: 사람 관찰용 기존 포맷 유지.
    - 파일 JSONL: ``ANTE_LOG_JSONL=1`` 이 설정된 경우에만 활성화,
      ``logs/ante-YYYY-MM-DD.jsonl`` 에 일일 자정 회전.
    - 파일 핸들러 초기화 실패(디스크 가득, 권한 문제 등) 시 예외를 삼키고
      stdout 핸들러만 유지한다 (스펙 §실패 처리).
    - 예약 키(``ts``, ``level``, ``logger``, ``msg``, ``env``, ``exc`` 및
      기타 LogRecord 속성)가 ``extra=`` 로 주입되어도 KeyError 없이 무시되도록
      ``AnteLogger`` 를 전역 Logger 클래스로 설치한다
      (스펙 ``03-json-schema.md`` §예약어 처리).
    """
    # 예약 키 KeyError 방지 — 반드시 핸들러 구성 이전에 수행.
    install_safe_logger()

    root = logging.getLogger()
    log_level = config.get("system.log_level", "INFO")
    root.setLevel(getattr(logging, log_level))

    # 기존 핸들러 제거 (재호출 시 중복 방지)
    for h in list(root.handlers):
        root.removeHandler(h)

    # stdout 핸들러 (기존 포맷 유지 — 사람 관찰용).
    # 파일 핸들러 초기화 이전에 등록해 이후 실패 시에도 stdout 로깅이 살아있다.
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(stdout_handler)

    # JSONL 파일 핸들러 (환경변수 게이트)
    if os.environ.get("ANTE_LOG_JSONL") == "1":
        try:
            log_dir = Path("logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = DateNamedTimedRotatingFileHandler(
                log_dir,
                prefix="ante",
                file_suffix=".jsonl",
                backup_count=30,
            )
            file_handler.setFormatter(JsonFormatter())
            root.addHandler(file_handler)
        except Exception as err:  # noqa: BLE001 — 로깅 실패는 전체 흡수
            # 부팅 차단을 막기 위해 예외를 흡수하고 stdout 핸들러만 유지한다.
            logging.getLogger(__name__).warning(
                "JSONL 파일 핸들러 초기화 실패 — stdout 전용으로 계속 진행: %s", err
            )
