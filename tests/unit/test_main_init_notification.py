"""``_init_notification`` 단위 테스트 (#1118).

``notification.telegram_enabled=false`` 일 때 Telegram 시크릿 조회 없이
즉시 반환되는지, 활성화 상태에서 시크릿이 없으면 ``ConfigError`` 를
흡수하고 건너뛰는지 검증한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ante.config import ConfigError
from ante.main import Services, _init_notification


class _StubConfig:
    """``Config.secret/get`` 계약만 만족하는 최소 더블."""

    def __init__(
        self,
        *,
        secrets: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        self._secrets = secrets or {}
        self._values = values or {}

    def secret(self, key: str) -> str:
        if key not in self._secrets:
            raise ConfigError(f"Secret not found: {key}")
        return self._secrets[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class _StubDynamicConfig:
    """``DynamicConfigService.get`` 계약만 만족하는 최소 더블."""

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = values or {}

    async def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class _StubEventBus:
    pass


def _make_services(
    *,
    telegram_enabled: str | None = "true",
    secrets: dict[str, str] | None = None,
) -> Services:
    values: dict[str, Any] = {}
    if telegram_enabled is not None:
        # 정적 config 는 사용되지 않지만 secret/get 계약 일관성을 위해 둔다.
        values["notification.min_level"] = "info"
    s = Services()
    s.config = _StubConfig(secrets=secrets, values=values)  # type: ignore[assignment]
    s.eventbus = _StubEventBus()  # type: ignore[assignment]
    dynamic_values: dict[str, Any] = {}
    if telegram_enabled is not None:
        dynamic_values["notification.telegram_enabled"] = telegram_enabled
    s.dynamic_config = _StubDynamicConfig(dynamic_values)  # type: ignore[assignment]
    return s


@pytest.mark.asyncio
async def test_disabled_skips_without_secrets() -> None:
    """telegram_enabled=false + 시크릿 없음 → ConfigError 없이 정상 return."""
    s = _make_services(telegram_enabled="false", secrets=None)

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_disabled_with_secrets_still_creates_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """telegram_enabled=false + 시크릿 존재 → 서비스는 생성한다.

    CRITICAL 알림 예외 경로와 ``ConfigChangedEvent`` 기반 동적 재활성화
    (notification 스펙 §_should_send) 를 보존하려면, disabled 상태에서도
    NotificationService 자체는 살아 있어야 한다. ``telegram_enabled=False``
    플래그만 필터로 전달한다. Receiver 는 토글 OFF 상태이므로 시작하지 않는다.
    """
    s = _make_services(
        telegram_enabled="false",
        secrets={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "42"},
    )
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    created_kwargs: list[dict[str, Any]] = []

    import ante.notification as notification_mod

    class _StubNotificationService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created_kwargs.append(kwargs)

        def subscribe(self) -> None:
            pass

    monkeypatch.setattr(
        notification_mod, "NotificationService", _StubNotificationService
    )

    await _init_notification(s)

    assert len(created_kwargs) == 1, "disabled 상태에서도 서비스는 생성되어야 한다"
    assert created_kwargs[0]["telegram_enabled"] is False
    assert s.notification_service is not None
    assert s.telegram_receiver is None, (
        "Receiver 는 telegram_enabled=false 일 때 시작되면 안 된다"
    )


@pytest.mark.asyncio
async def test_disabled_with_empty_secrets_skips() -> None:
    """telegram_enabled=false + 공란 시크릿 → skip (adapter 생성 불가)."""
    s = _make_services(
        telegram_enabled="false",
        secrets={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""},
    )

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_enabled_with_empty_secrets_skips() -> None:
    """telegram_enabled=true + 공란 시크릿 → broken adapter 방지 skip.

    ``Config.secret()`` 은 env 가 ``""`` 로 설정된 경우 빈 문자열을 반환하므로
    (raise 가 아님), 명시적 공란 가드가 필요하다. 스테이징 환경에서 시크릿을
    의도적으로 비워 두는 방식을 안전하게 지원한다.
    """
    s = _make_services(
        telegram_enabled="true",
        secrets={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""},
    )

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_enabled_without_secrets_skips_gracefully() -> None:
    """telegram_enabled=true 이지만 시크릿 누락 → ConfigError 흡수 후 skip."""
    s = _make_services(telegram_enabled="true", secrets=None)

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_enabled_with_only_token_skips_gracefully() -> None:
    """두 시크릿 중 하나라도 빠지면 부팅을 막지 않고 skip."""
    s = _make_services(
        telegram_enabled="true",
        secrets={"TELEGRAM_BOT_TOKEN": "t"},  # CHAT_ID 누락
    )

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_default_enabled_when_dynamic_config_empty() -> None:
    """dynamic_config 에 값이 없으면 기본값 "true" 로 해석되어 시크릿을 조회한다.

    시크릿 없음 → ConfigError 흡수 경로로 skip 되어야 한다 (부팅 안 막힘).
    """
    s = _make_services(telegram_enabled=None, secrets=None)

    await _init_notification(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None


@pytest.mark.asyncio
async def test_enabled_with_secrets_initializes_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """telegram_enabled=true + 시크릿 모두 존재 → NotificationService 생성."""
    s = _make_services(
        telegram_enabled="true",
        secrets={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "42"},
    )

    # TELEGRAM_CHAT_ID 환경변수가 parse 될 수 있도록 설정 (receiver 활성화 경로).
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    # NotificationService.subscribe 가 실제 EventBus 계약을 요구하므로,
    # 서비스 생성 후 subscribe 단계에서 실패해도 본 테스트의 목적(= 시크릿
    # 조회 순서 + 초기화 진입)에는 영향 없다. 생성 단계까지만 검증한다.
    created: list[Any] = []

    import ante.notification as notification_mod

    original_cls = notification_mod.NotificationService

    class _StubNotificationService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created.append(SimpleNamespace(args=args, kwargs=kwargs))

        def subscribe(self) -> None:
            pass

    monkeypatch.setattr(
        notification_mod, "NotificationService", _StubNotificationService
    )

    class _StubReceiver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(notification_mod, "TelegramCommandReceiver", _StubReceiver)

    try:
        await _init_notification(s)
    finally:
        monkeypatch.setattr(notification_mod, "NotificationService", original_cls)

    assert len(created) == 1, "NotificationService 생성자 호출 누락"
    assert s.notification_service is not None
    assert s.telegram_receiver is not None
