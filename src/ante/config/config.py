"""Config 클래스 — 정적 설정(TOML) + 비밀값(.env) 통합 접근."""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from ante.config.defaults import DEFAULTS
from ante.config.exceptions import ConfigError

logger = logging.getLogger(__name__)


def _load_toml(path: Path) -> dict[str, Any]:
    """TOML 파일 로드. 파일 없으면 빈 dict 반환."""
    if not path.exists():
        logger.warning("TOML 설정 파일 없음: %s — 기본값 사용", path)
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _load_dotenv(path: Path) -> dict[str, str]:
    """간단한 .env 파일 파서. KEY=VALUE 형식."""
    if not path.exists():
        logger.warning(".env 파일 없음: %s", path)
        return {}
    result: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # 따옴표 제거
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    return result


def _nested_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """점(.) 구분자로 중첩 dict 접근.

    예: _nested_get({"db": {"path": "x"}}, "db.path") -> "x"
    """
    parts = key.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            return default
        current = current.get(part)
        if current is None:
            return default
    return current


def resolve_config_dir(override: Path | None = None) -> Path:
    """설정 디렉토리 탐색.

    우선순위: override 인자 > ANTE_CONFIG_DIR 환경변수
              > ~/.config/ante/ > ./config/
    """
    if override is not None:
        return override

    env_dir = os.environ.get("ANTE_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)

    user_dir = Path.home() / ".config" / "ante"
    if user_dir.exists():
        return user_dir

    return Path("config")


class Config:
    """Ante 통합 설정 접근 인터페이스.

    정적 설정(TOML)과 비밀값(.env)에 대한 일관된 접근을 제공한다.
    동적 설정은 DynamicConfigService가 별도 담당.
    """

    def __init__(self, static: dict[str, Any], secrets: dict[str, str]) -> None:
        self._static = static
        self._secrets = secrets

    @classmethod
    def load(cls, config_dir: Path | None = None) -> Config:
        """설정 파일 로드 및 Config 인스턴스 생성.

        config_dir이 None이면 resolve_config_dir()로 자동 탐색.
        """
        resolved = resolve_config_dir(config_dir)
        static = _load_toml(resolved / "system.toml")
        secrets = _load_dotenv(resolved / "secrets.env")
        return cls(static=static, secrets=secrets)

    def get(self, key: str, default: Any = None) -> Any:
        """정적 설정 조회. 점(.) 구분자로 중첩 접근.

        우선순위: TOML > DEFAULTS
        예: config.get("db.path") -> "db/ante.db"
        """
        value = _nested_get(self._static, key)
        if value is not None:
            return value
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def secret(self, key: str) -> str:
        """비밀값 조회. 환경변수 우선, 없으면 .env에서.

        예: config.secret("KIS_APP_KEY")
        Raises: ConfigError if not found
        """
        value = os.environ.get(key) or self._secrets.get(key)
        if value is None:
            raise ConfigError(f"Secret not found: {key}")
        return value

    def validate(self) -> None:
        """필수 설정 존재 여부 및 타입 검증. 시스템 시작 시 호출."""
        errors: list[str] = []

        required_static: list[tuple[str, type]] = [
            ("db.path", str),
            ("parquet.base_path", str),
            ("web.port", int),
        ]
        for key, expected_type in required_static:
            value = self.get(key)
            if value is None:
                errors.append(f"Missing required config: {key}")
            elif not isinstance(value, expected_type):
                errors.append(
                    f"Invalid type for {key}: expected {expected_type.__name__}"
                )

        if errors:
            raise ConfigError(
                "Configuration validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
