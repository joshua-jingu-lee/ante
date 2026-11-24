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


def _read_secrets_env_text(path: Path) -> str:
    """secrets.env를 UTF-8로 읽고, 디코딩 실패는 바이트 없는 ``ConfigError``로."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        raise ConfigError("secrets.env 파일을 UTF-8로 읽을 수 없습니다.") from None


def _load_dotenv(path: Path) -> dict[str, str]:
    """간단한 .env 파일 파서. KEY=VALUE 형식."""
    if not path.exists():
        logger.warning(".env 파일 없음: %s", path)
        return {}
    result: dict[str, str] = {}
    for line in _read_secrets_env_text(path).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def _nested_get(data: dict[str, Any], key: str, default: Any = None) -> Any:
    """점(.) 구분자로 중첩 dict 접근."""
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

    def __init__(
        self,
        static: dict[str, Any],
        secrets: dict[str, str],
        config_dir: Path | None = None,
    ) -> None:
        self._static = static
        self._secrets = secrets
        self._config_dir = config_dir

    @classmethod
    def load(cls, config_dir: Path | None = None) -> Config:
        """설정 파일 로드 및 Config 인스턴스 생성.

        부수효과: ``secrets.env`` 의 ``ANTE_DB_ENCRYPTION_KEY`` 값이
        Fernet canonical 형식을 만족하고, 현재 ``os.environ``에는 valid한
        ``ANTE_DB_ENCRYPTION_KEY`` 가 없으면(빈 문자열/invalid 포함),
        파일 값을 ``os.environ`` 으로 export한다. ``src/ante/account/crypto.py``
        가 ``os.environ`` 만 읽는 현재 contract를 깨지 않으면서 init이 만든
        키가 후속 CLI/서비스에 자동 전파되도록 한다.
        """
        from ante.account.crypto import _validate_fernet_key

        resolved = resolve_config_dir(config_dir)
        static = _load_toml(resolved / "system.toml")
        secrets = _load_dotenv(resolved / "secrets.env")

        file_key = secrets.get("ANTE_DB_ENCRYPTION_KEY")
        existing = os.environ.get("ANTE_DB_ENCRYPTION_KEY")
        if (
            file_key
            and _validate_fernet_key(file_key)
            and not _validate_fernet_key(existing or "")
        ):
            os.environ["ANTE_DB_ENCRYPTION_KEY"] = file_key

        return cls(static=static, secrets=secrets, config_dir=resolved)

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

    def resolve_path(self, key: str, default: str | None = None) -> Path:
        """path-like 정적 설정을 ``config_dir`` 기준의 절대 경로로 정규화한다.

        절대 경로로 설정된 값은 그대로, 상대 경로는 ``config_dir`` 기준으로 결합한다.

        직접 ``Config(...)`` 로 만들었거나 ``config_dir``이 ``None``이면
        ``Path.cwd()``를 폴백으로 사용한다.

        Raises:
            ConfigError: 키 값을 찾을 수 없고 ``default``도 ``None``인 경우.
        """
        raw = self.get(key, default)
        if raw is None:
            raise ConfigError(f"Path config missing: {key}")
        p = Path(str(raw))
        if p.is_absolute():
            return p
        base = self._config_dir if self._config_dir is not None else Path.cwd()
        return base / p

    def runtime_pid_path(self) -> Path:
        """``runtime.pid_path``를 ``config_dir`` 기준 절대 경로로 반환한다.

        Spec: ``docs/specs/config/03-design-decisions.md`` 200-202, 280-281.
        Default: ``<config_dir>/run/ante.pid``. ``[runtime] pid_path``를
        ``system.toml``에 두면 사용자 override가 우선한다.
        """
        return self.resolve_path("runtime.pid_path", "run/ante.pid")

    def runtime_socket_path(self) -> Path:
        """``runtime.socket_path``를 ``config_dir`` 기준 절대 경로로 반환한다.

        Spec: ``docs/specs/ipc/ipc.md`` 181-186,
        ``docs/specs/config/03-design-decisions.md`` 200-202.
        Default: ``<config_dir>/run/ante.sock``.
        """
        return self.resolve_path("runtime.socket_path", "run/ante.sock")

    def secret(self, key: str) -> str:
        """비밀값 조회. 환경변수 우선, 없으면 .env에서.

        환경변수가 존재하면(빈 문자열 포함) 그대로 반환하며, 빈 값 허용
        여부는 호출자가 판단한다.

        예: config.secret("KIS_APP_KEY")
        Raises: ConfigError if not found
        """
        if key in os.environ:
            return os.environ[key]
        value = self._secrets.get(key)
        if value is None:
            raise ConfigError(f"Secret not found: {key}")
        return value

    def validate(self) -> None:
        """필수 설정 존재 여부 및 타입 검증. 시스템 시작 시 호출."""
        errors: list[str] = []

        required_static: list[tuple[str, type]] = [
            ("db.path", str),
            ("parquet.base_path", str),
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
