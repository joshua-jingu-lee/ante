"""DynamicConfigService — 동적 설정 CRUD + 변경 알림.

Numeric invariant (#1412 oracle A7):
- write 경계(`validate_value`)에서 numeric 값(`int`/`float`, `bool` 제외)은
  반드시 finite 여야 한다. `NaN`/`Infinity`/`-Infinity` 는 ValueError 로 거부되며,
  호출자(web/IPC/CLI)가 422 로 변환한다.
- read 경계(`get`/`get_all`/`get_by_category`)에서 legacy non-finite numeric
  row 는 `_ensure_loaded_value_finite` 가 ConfigError 로 격리한다
  (defense-in-depth, JSON 직렬화 실패/silent corruption 방지).
"""

from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING, Any

from ante.config.exceptions import ConfigError

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def validate_value(key: str, value: Any) -> None:
    """키별 값 검증 (서비스 경계에서 호출).

    Generic numeric finite 가드 (#1412 oracle A7):
        모든 numeric 값(`int`/`float`, `bool` 제외)은 finite 여야 한다.
        `NaN`/`Infinity`/`-Infinity` 는 ValueError 로 거부된다. 이 가드는 키와
        무관하게 적용되어 IPC/CLI/web 모든 경로에서 동일하게 동작한다.
        `bool` 은 Python 에서 `int` 의 서브클래스(`isinstance(True, int) == True`)
        이므로 명시적으로 제외한다.

    `system.log_level` 처럼 enum SSOT가 정의된 키는 invalid 값을 즉시 거부한다.
    정의되지 않은 키는 numeric finite 가드 외에는 통과(generic CRUD 동작 유지).

    대소문자 정책: `system.log_level` 은 대소문자 구분으로 거부한다. 즉
    ``_VALID_LOG_LEVELS`` 멤버(전부 대문자)와 정확 일치해야 통과하고,
    ``"debug"`` 같은 소문자 입력은 ValueError 로 거부된다 (#1379 oracle A7).

    Raises:
        ValueError: 키별 invariant 또는 numeric finite invariant 를 위반한 경우.
            호출자(web/IPC/CLI)는 이를 422 등 도메인 응답으로 변환해야 한다.
    """
    # Generic numeric finite 가드 (#1412). bool 은 int 서브클래스이므로 명시 제외.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(
                "numeric config 값은 finite number 여야 합니다 "
                f"(NaN/Infinity 거부). key={key} value={value!r}"
            )

    if key == "system.log_level":
        if not isinstance(value, str) or value not in _VALID_LOG_LEVELS:
            raise ValueError(
                "system.log_level은 _VALID_LOG_LEVELS 멤버여야 합니다 (대소문자 구분)."
            )


def _ensure_loaded_value_finite(key: str, value: Any) -> Any:
    """DB 에서 읽은 dynamic config 값을 격리 검사한다 (#1412 oracle A7).

    legacy NaN/Infinity row 가 DB 에 남아있더라도 read 경계에서 ConfigError 로
    격리되어 downstream consumer(JSON 직렬화, rule engine 비교 등)로 silent
    하게 흘러가지 않도록 한다. write 경계(`validate_value`)의 finite 가드와
    짝을 이루는 defense-in-depth.

    `bool` 은 `int` 의 서브클래스이지만 `math.isfinite(True)` 는 True 이므로
    `validate_value` 와 동일하게 명시 제외하여 의도치 않은 경로를 차단한다.

    Raises:
        ConfigError: 저장된 값이 non-finite numeric 일 때. 호출자(web GET 라우트
            등)는 이를 422 등으로 변환할 수 있다.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ConfigError(
                "Dynamic config의 numeric 값이 non-finite 입니다. "
                f"key={key} value={value!r}"
            )
    return value


DYNAMIC_CONFIG_SCHEMA = """
CREATE TABLE IF NOT EXISTS dynamic_config (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    category  TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS dynamic_config_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    changed_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_config_history_key ON dynamic_config_history(key);
CREATE INDEX IF NOT EXISTS idx_config_history_changed_at
    ON dynamic_config_history(changed_at);
"""


class DynamicConfigService:
    """동적 설정 CRUD + 변경 알림.

    런타임 변경이 필요한 설정을 SQLite에 저장하고,
    변경 시 EventBus를 통해 ConfigChangedEvent를 발행한다.
    """

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(DYNAMIC_CONFIG_SCHEMA)

    _MISSING = object()

    async def get(self, key: str, default: Any = _MISSING) -> Any:
        """동적 설정 값 조회. JSON 역직렬화하여 반환.

        Read 경계에서 ``_ensure_loaded_value_finite`` 가 legacy non-finite
        numeric row 를 ConfigError 로 격리한다 (#1412 oracle A7).
        """
        row = await self._db.fetch_one(
            "SELECT value FROM dynamic_config WHERE key = ?", (key,)
        )
        if row is None:
            if default is not self._MISSING:
                return default
            raise ConfigError(f"Dynamic config not found: {key}")
        return _ensure_loaded_value_finite(key, json.loads(row["value"]))

    async def set(
        self, key: str, value: Any, category: str, changed_by: str = "system"
    ) -> None:
        """동적 설정 값 변경 + 이력 기록 + EventBus 알림.

        키별 invariant 가 정의된 경우 ``validate_value`` 가 ValueError 를
        발생시킨다(서비스 경계 검증, IPC/CLI 우회 차단 — #1379).

        legacy non-finite numeric row 가 저장돼 있는 키를 정상 값으로 덮어쓰는
        경로(self-healing)는 막지 않는다 — ``get`` 의 read defense 가
        ``ConfigError`` 를 raise 하면 ``old_value`` 를 ``None`` 으로 두고 새 값을
        그대로 저장한다 (#1412 oracle A7).
        """
        from ante.eventbus.events import ConfigChangedEvent

        validate_value(key, value)

        old_value = None
        if await self.exists(key):
            try:
                old_value = await self.get(key)
            except ConfigError:
                # legacy non-finite numeric row — self-healing 경로 허용. (#1412)
                old_value = None

        json_value = json.dumps(value)
        old_json = json.dumps(old_value) if old_value is not None else None
        await self._db.execute(
            """INSERT INTO dynamic_config (key, value, category, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at""",
            (key, json_value, category),
        )
        await self._db.execute(
            """INSERT INTO dynamic_config_history
               (key, old_value, new_value, changed_by, changed_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (key, old_json, json_value, changed_by),
        )
        await self._eventbus.publish(
            ConfigChangedEvent(
                category=category,
                key=key,
                old_value=old_json if old_json is not None else "",
                new_value=json_value,
            )
        )
        logger.info(
            "동적 설정 변경: %s = %s (category=%s, by=%s)",
            key,
            value,
            category,
            changed_by,
        )

    async def delete(self, key: str) -> bool:
        """동적 설정 삭제. 삭제 성공 시 True 반환."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM dynamic_config WHERE key = ?", (key,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM dynamic_config WHERE key = ?", (key,))
        return True

    async def get_all(self) -> list[dict[str, Any]]:
        """전체 동적 설정 조회.

        Read 경계에서 ``_ensure_loaded_value_finite`` 가 legacy non-finite
        numeric row 를 ConfigError 로 격리한다 (#1412 oracle A7).
        """
        rows = await self._db.fetch_all(
            "SELECT key, value, category, updated_at FROM dynamic_config ORDER BY key"
        )
        return [
            {
                "key": row["key"],
                "value": _ensure_loaded_value_finite(
                    row["key"], json.loads(row["value"])
                ),
                "category": row["category"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    async def get_by_category(self, category: str) -> dict[str, Any]:
        """카테고리별 모든 설정 조회.

        Read 경계에서 ``_ensure_loaded_value_finite`` 가 legacy non-finite
        numeric row 를 ConfigError 로 격리한다 (#1412 oracle A7).
        """
        rows = await self._db.fetch_all(
            "SELECT key, value FROM dynamic_config WHERE category = ?",
            (category,),
        )
        return {
            row["key"]: _ensure_loaded_value_finite(
                row["key"], json.loads(row["value"])
            )
            for row in rows
        }

    async def register_default(self, key: str, value: Any, category: str) -> None:
        """기본값 등록. 이미 값이 존재하면 무시한다."""
        if not await self.exists(key):
            json_value = json.dumps(value)
            await self._db.execute(
                "INSERT OR IGNORE INTO dynamic_config"
                " (key, value, category, updated_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (key, json_value, category),
            )
            logger.info("동적 설정 기본값 등록: %s = %s", key, value)

    async def exists(self, key: str) -> bool:
        """설정 존재 여부 확인."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM dynamic_config WHERE key = ?", (key,)
        )
        return row is not None

    async def get_history(self, key: str, limit: int = 50) -> list[dict[str, Any]]:
        """설정 변경 이력 조회. 최신순 반환."""
        rows = await self._db.fetch_all(
            """SELECT id, key, old_value, new_value, changed_by, changed_at
               FROM dynamic_config_history
               WHERE key = ?
               ORDER BY changed_at DESC, id DESC
               LIMIT ?""",
            (key, limit),
        )
        return list(rows)

    async def cleanup_history(self, retention_days: int = 90) -> int:
        """retention_days보다 오래된 이력 삭제. 삭제 건수 반환."""
        rows = await self._db.fetch_all(
            """SELECT id FROM dynamic_config_history
               WHERE changed_at < datetime('now', ?)""",
            (f"-{retention_days} days",),
        )
        count = len(rows)
        if count > 0:
            await self._db.execute(
                """DELETE FROM dynamic_config_history
                   WHERE changed_at < datetime('now', ?)""",
                (f"-{retention_days} days",),
            )
            logger.info(
                "설정 이력 정리: %d건 삭제 (retention=%d일)", count, retention_days
            )
        return count


def _on_log_level_changed(event: Any) -> None:
    """system.log_level 변경 시 루트 로거 레벨을 동적으로 갱신한다.

    서비스 경계에서 ``validate_value`` 가 invalid 값을 차단하므로 이 callback
    까지 invalid 값이 도달하는 일은 정상 경로에서는 발생하지 않는다(#1379).
    그래도 startup hook 이 historical persisted bad-value 를 publish 하거나
    구독자 순서가 바뀌는 경우를 대비해 silent-drop 을 defense-in-depth 로
    유지한다.
    """
    if event.key != "system.log_level":
        return

    new_level = json.loads(event.new_value).upper()
    if new_level not in _VALID_LOG_LEVELS:
        logger.warning("유효하지 않은 log_level: %s — 무시", new_level)
        return

    logging.getLogger().setLevel(getattr(logging, new_level))
    logger.info("루트 로거 레벨 변경: %s", new_level)
