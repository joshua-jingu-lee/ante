"""DataFeed 설정 관리."""

from __future__ import annotations

import os
import stat
from pathlib import Path

FEED_DIR = ".feed"
ENV_FILE = ".env"
CONFIG_FILE = "config.toml"

# Supported API keys
API_KEYS = [
    "ANTE_DATAGOKR_API_KEY",
    "ANTE_DART_API_KEY",
]

DEFAULT_CONFIG_TOML = """[general]
log_level = "INFO"
nice_value = 10

[schedule]
daily_at = "16:00"
backfill_at = "01:00"
backfill_since = "2015-01-01"

[guard]
blocked_days = []
blocked_hours = ["09:00-15:30"]
pause_during_trading = true

[routing]
data_go_kr = ["krx"]
dart = ["krx"]

[ohlcv.krx]
timeframes = ["1d"]
symbols = "all"

[fundamental.krx]
symbols = "all"
"""


class FeedConfig:
    """DataFeed 설정 관리.

    API 키 우선순위: 환경변수 > .feed/.env 파일
    """

    def __init__(self, data_path: str | Path) -> None:
        self._data_path = Path(data_path)
        self._feed_dir = self._data_path / FEED_DIR

    @property
    def feed_dir(self) -> Path:
        return self._feed_dir

    @property
    def env_path(self) -> Path:
        return self._feed_dir / ENV_FILE

    @property
    def config_path(self) -> Path:
        return self._feed_dir / CONFIG_FILE

    def is_initialized(self) -> bool:
        """DataFeed가 초기화되어 있는지 확인한다."""
        return self.config_path.exists()

    def load_config(self) -> dict[str, object]:
        """config.toml을 읽어 딕셔너리로 반환한다.

        Returns:
            설정 딕셔너리. 파일이 없으면 빈 딕셔너리.
        """
        import tomllib

        if not self.config_path.exists():
            return {}
        with self.config_path.open("rb") as f:
            return tomllib.load(f)

    def init(self) -> list[str]:
        """피드 디렉토리를 초기화한다. 생성된 경로 목록을 반환한다."""
        created = []

        self._feed_dir.mkdir(parents=True, exist_ok=True)

        if not self.config_path.exists():
            self.config_path.write_text(DEFAULT_CONFIG_TOML)
            created.append(str(self.config_path))

        checkpoints_dir = self._feed_dir / "checkpoints"
        checkpoints_dir.mkdir(exist_ok=True)
        created.append(str(checkpoints_dir) + "/")

        reports_dir = self._feed_dir / "reports"
        reports_dir.mkdir(exist_ok=True)
        created.append(str(reports_dir) + "/")

        return created

    def load_api_keys(self) -> dict[str, str | None]:
        """API 키를 로드한다. 우선순위: 환경변수 > .env 파일."""
        env_values = self._load_env_file()
        result: dict[str, str | None] = {}
        for key in API_KEYS:
            # 환경변수 우선
            env_val = os.environ.get(key)
            if env_val:
                result[key] = env_val
            elif key in env_values:
                result[key] = env_values[key]
            else:
                result[key] = None
        return result

    def set_api_key(self, key: str, value: str) -> Path:
        """API 키를 .env 파일에 저장한다. 파일 퍼미션을 0600으로 설정한다."""
        self._feed_dir.mkdir(parents=True, exist_ok=True)

        env_values = self._load_env_file()
        env_values[key] = value

        lines = [f"{k}={v}\n" for k, v in env_values.items()]
        self.env_path.write_text("".join(lines))
        self.env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600

        return self.env_path

    def list_api_keys(self) -> list[dict[str, str]]:
        """API 키 목록을 마스킹하여 반환한다."""
        env_file_values = self._load_env_file()
        result = []
        for key in API_KEYS:
            env_val = os.environ.get(key)
            if env_val:
                result.append(
                    {
                        "key": key,
                        "value": _mask_value(env_val),
                        "source": "env",
                    }
                )
            elif key in env_file_values:
                result.append(
                    {
                        "key": key,
                        "value": _mask_value(env_file_values[key]),
                        "source": ".env",
                    }
                )
            else:
                result.append(
                    {
                        "key": key,
                        "value": "(미설정)",
                        "source": "",
                    }
                )
        return result

    def check_api_keys(self) -> list[dict[str, str | bool]]:
        """API 키 존재 여부를 확인한다.

        유효성 검증은 네트워크 호출이 필요하므로 스텁.
        """
        keys = self.load_api_keys()
        result: list[dict[str, str | bool]] = []
        for key in API_KEYS:
            val = keys.get(key)
            source = ""
            if val:
                env_val = os.environ.get(key)
                source = "env" if env_val else ".env"
            result.append(
                {
                    "key": key,
                    "set": val is not None,
                    "source": source,
                }
            )
        return result

    def _load_env_file(self) -> dict[str, str]:
        """.env 파일을 파싱하여 딕셔너리로 반환한다."""
        if not self.env_path.exists():
            return {}
        values: dict[str, str] = {}
        for line in self.env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
        return values


def _mask_value(value: str) -> str:
    """API 키 값을 마스킹한다: 앞 3자 + *** + 뒤 3자."""
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-3:]
