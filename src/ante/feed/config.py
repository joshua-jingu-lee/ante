"""DataFeed 설정 관리."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

FEED_DIR = ".feed"
ENV_FILE = ".env"
CONFIG_FILE = "config.toml"

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
            env_val = os.environ.get(key)
            if env_val:
                result[key] = env_val
            elif key in env_values:
                result[key] = env_values[key]
            else:
                result[key] = None
        return result

    def set_api_key(self, key: str, value: str) -> Path:
        """API 키를 .env 파일에 저장한다. 0600 임시 파일에 쓰고 원자 교체한다.

        Raises:
            ValueError: value에 개행 문자(`\\n` 또는 `\\r`)가 포함된 경우.
                _load_env_file은 quoting/escaping을 지원하지 않으므로
                개행이 포함된 value는 후속 라인을 별도 `KEY=VALUE`로
                재해석하게 만들어 다른 API 키를 주입할 수 있다.
                escaping 대신 reject하며, 파일은 변경하지 않는다.
        """
        if "\n" in value or "\r" in value:
            raise ValueError("API 키 값에 개행 문자를 포함할 수 없습니다")

        self._feed_dir.mkdir(parents=True, exist_ok=True)

        env_values = self._load_env_file()
        env_values[key] = value

        lines = [f"{k}={v}\n" for k, v in env_values.items()]
        try:
            data = "".join(lines).encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("API 키 값을 UTF-8로 인코딩할 수 없습니다") from None
        fd, tmp = tempfile.mkstemp(prefix=".env.", dir=self._feed_dir)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                os.fchmod(f.fileno(), 0o600)
            os.replace(tmp, self.env_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

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
        """API 키 존재 여부를 확인한다(동기, 네트워크 호출 없음).

        존재여부만 반환하는 경량 경로다. ``feed status`` 등 네트워크
        검증이 필요 없는 호출자가 사용한다. 유효성 검증이 필요하면
        :meth:`check_api_keys_with_validation` 을 사용한다.
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
                    "set": bool(val),
                    "source": source,
                }
            )
        return result

    async def check_api_keys_with_validation(
        self,
    ) -> list[dict[str, str | bool | None]]:
        """API 키 존재 여부 + 네트워크 유효성을 확인한다.

        각 항목은 ``{key, set, source, valid, detail}`` 형태다.
            * ``valid``  — ``True``(유효) / ``False``(인증 실패) /
              ``None``(검증 불가 또는 미설정 → 검증 생략).
            * ``detail`` — 인증 실패/검증 불가 시의 사유 문자열, 그 외 None.

        네트워크 예외/타임아웃(offline 포함)은 source 단에서 unknown으로
        흡수되어 예외가 전파되지 않는다.
        """
        keys = self.load_api_keys()
        result: list[dict[str, str | bool | None]] = []
        for key in API_KEYS:
            val = keys.get(key)
            source = ""
            valid: bool | None = None
            detail: str | None = None
            if val:
                env_val = os.environ.get(key)
                source = "env" if env_val else ".env"
                valid, detail = await self._validate_key(key, val)
            result.append(
                {
                    "key": key,
                    "set": bool(val),
                    "source": source,
                    "valid": valid,
                    "detail": detail,
                }
            )
        return result

    @staticmethod
    async def _validate_key(key: str, value: str) -> tuple[bool | None, str | None]:
        """단일 API 키를 해당 source의 경량 검증으로 평가한다."""
        if key == "ANTE_DART_API_KEY":
            from ante.feed.sources.dart import DARTSource

            return await DARTSource(api_key=value).validate_credentials()
        if key == "ANTE_DATAGOKR_API_KEY":
            from ante.feed.sources.data_go_kr import DataGoKrSource

            return await DataGoKrSource(api_key=value).validate_credentials()
        return None, None

    def _load_env_file(self) -> dict[str, str]:
        """.env 파일을 파싱하여 딕셔너리로 반환한다."""
        if not self.env_path.exists():
            return {}
        values: dict[str, str] = {}
        try:
            text = self.env_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise OSError("feed .env 파일을 UTF-8로 읽을 수 없습니다.") from None
        for line in text.splitlines():
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
