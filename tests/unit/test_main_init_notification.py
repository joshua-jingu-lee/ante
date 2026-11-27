"""알림 서비스 생성과 텔레그램 명령 수신기 시작 단위 테스트 (#1118, #3109).

``notification.telegram_enabled=false`` 일 때 Telegram 시크릿 조회 없이
즉시 반환되는지, 활성화 상태에서 시크릿이 없으면 ``ConfigError`` 를
흡수하고 건너뛰는지 검증한다. 기동 중에 쌓인 알림의 해제·종료 순서도 본다.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from ante.config import ConfigError
from ante.main import (
    Services,
    _init_notification_service,
    _init_telegram_receiver,
)


async def _init_notification(s: Services) -> None:
    """``main()`` 이 부르는 두 단계를 차례로 부른다."""
    await _init_notification_service(s)
    await _init_telegram_receiver(s)


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
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    created_kwargs: list[dict[str, Any]] = []

    import ante.notification as notification_mod

    class _StubNotificationService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created_kwargs.append(kwargs)
            self.adapter = kwargs["adapter"]

        def subscribe(self, *, defer: bool = False) -> None:
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

    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    # NotificationService.subscribe 가 실제 EventBus 계약을 요구하므로,
    # 서비스 생성 후 subscribe 단계에서 실패해도 본 테스트의 목적(= 시크릿
    # 조회 순서 + 초기화 진입)에는 영향 없다. 생성 단계까지만 검증한다.
    created: list[Any] = []

    import ante.notification as notification_mod

    original_cls = notification_mod.NotificationService

    class _StubNotificationService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            created.append(SimpleNamespace(args=args, kwargs=kwargs))
            self.adapter = kwargs["adapter"]

        def subscribe(self, *, defer: bool = False) -> None:
            pass

    monkeypatch.setattr(
        notification_mod, "NotificationService", _StubNotificationService
    )

    captured_kwargs: list[dict[str, Any]] = []

    class _StubReceiver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.started = False
            captured_kwargs.append(kwargs)

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(notification_mod, "TelegramCommandReceiver", _StubReceiver)

    # #2378: `_init_notification`이 TelegramCommandReceiver에 자금 조회
    # 의존성(TreasuryManager)을 주입하는지 회귀 가드. 주입 누락 시
    # `/balance`가 런타임에서 항상 fallback 문구를 반환하는 버그가 발생한다.
    sentinel_treasury_manager = object()
    s.treasury_manager = sentinel_treasury_manager  # type: ignore[assignment]

    # #2385: `_init_notification`이 TelegramCommandReceiver에 instrument_service를
    # 주입하는지 회귀 가드(#2378 동형). 주입 누락 시 `/stop` 보유종목이 런타임에서
    # 항상 종목코드만 표기하는 버그가 발생한다(format_label SSOT 미적용).
    sentinel_instrument_service = object()
    s.instrument_service = sentinel_instrument_service  # type: ignore[assignment]

    try:
        await _init_notification(s)
    finally:
        monkeypatch.setattr(notification_mod, "NotificationService", original_cls)

    assert len(created) == 1, "NotificationService 생성자 호출 누락"
    assert s.notification_service is not None
    assert s.telegram_receiver is not None
    assert len(captured_kwargs) == 1, "TelegramCommandReceiver 생성자 호출 누락"
    assert captured_kwargs[0]["treasury_manager"] is s.treasury_manager, (
        "TelegramCommandReceiver에 s.treasury_manager가 주입되어야 한다"
    )
    assert captured_kwargs[0]["instrument_service"] is s.instrument_service, (
        "TelegramCommandReceiver에 s.instrument_service가 주입되어야 한다 (#2385)"
    )


_FAKE_TOKEN = "fake-token"
_FAKE_CHAT_ID = "42"


def _real_config_services(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Services, list[dict[str, Any]]]:
    """실제 ``Config.secret`` 경로를 쓰고 수신기·서비스는 스텁한다 (#2625)."""
    import ante.notification as notification_mod
    from ante.config import Config

    class _StubNotificationService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.adapter = kwargs["adapter"]

        def subscribe(self, *, defer: bool = False) -> None:
            pass

    captured: list[dict[str, Any]] = []

    class _StubReceiver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.append(kwargs)

        def start(self) -> None:
            pass

    monkeypatch.setattr(
        notification_mod, "NotificationService", _StubNotificationService
    )
    monkeypatch.setattr(notification_mod, "TelegramCommandReceiver", _StubReceiver)

    s = Services()
    s.config = Config(
        static={},
        secrets={
            "TELEGRAM_BOT_TOKEN": _FAKE_TOKEN,
            "TELEGRAM_CHAT_ID": _FAKE_CHAT_ID,
        },
    )
    s.eventbus = _StubEventBus()  # type: ignore[assignment]
    s.dynamic_config = _StubDynamicConfig(  # type: ignore[assignment]
        {"notification.telegram_enabled": "true"}
    )
    return s, captured


@pytest.mark.asyncio
async def test_receiver_uses_chat_id_from_secrets_file_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2625: chat id가 secrets.env에만 있어도 수신기가 켜지고 발신과 같은 값을 쓴다."""
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    s, captured = _real_config_services(monkeypatch)

    await _init_notification(s)

    assert s.telegram_receiver is not None
    assert len(captured) == 1
    assert captured[0]["allowed_user_ids"] == [int(_FAKE_CHAT_ID)]
    assert captured[0]["adapter"]._chat_id == _FAKE_CHAT_ID


@pytest.mark.asyncio
async def test_receiver_and_sender_share_env_chat_id_over_secrets_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2625: 환경변수와 secrets.env가 다르면 발신·수신 모두 환경변수 값을 쓴다."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "7")
    s, captured = _real_config_services(monkeypatch)

    await _init_notification(s)

    assert s.telegram_receiver is not None
    assert len(captured) == 1
    assert captured[0]["allowed_user_ids"] == [7]
    assert captured[0]["adapter"]._chat_id == "7"


# ── #3109: 서비스·수신기 분리, 기동 중 쌓기, 종료 순서 ────────────────────────


class _RecordingAdapter:
    """보낸 제목을 기록하는 알림 어댑터 더블. ``delay`` 만큼 전송이 걸린다."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.titles: list[str] = []

    async def send(self, level: Any, message: str) -> bool:
        return True

    async def send_rich(
        self, level: Any, title: str, body: str, metadata: Any = None
    ) -> bool:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.titles.append(title)
        return True


def _receiver_stub(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    import ante.notification as notification_mod

    captured: list[dict[str, Any]] = []

    class _StubReceiver:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.append(kwargs)

        def start(self) -> None:
            pass

    monkeypatch.setattr(notification_mod, "TelegramCommandReceiver", _StubReceiver)
    return captured


def _real_service_services(
    *, chat_id: str = "42", telegram_enabled: str = "true"
) -> Services:
    from ante.eventbus import EventBus

    s = _make_services(
        telegram_enabled=telegram_enabled,
        secrets={"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": chat_id},
    )
    s.eventbus = EventBus()
    return s


@pytest.mark.asyncio
async def test_receiver_shares_adapter_instance_with_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수신기는 알림 서비스가 보내는 데 쓰는 바로 그 어댑터를 받는다."""
    captured = _receiver_stub(monkeypatch)
    s = _real_service_services()

    await _init_notification_service(s)
    assert s.telegram_receiver is None
    await _init_telegram_receiver(s)

    assert len(captured) == 1
    assert captured[0]["adapter"] is s.notification_service.adapter
    assert captured[0]["allowed_user_ids"] == [42]


@pytest.mark.asyncio
async def test_service_subscribes_in_deferring_mode() -> None:
    """서비스는 쌓기 모드로 구독해, 해제 전에는 어댑터를 부르지 않는다."""
    from ante.eventbus.events import NotificationEvent

    s = _real_service_services()
    await _init_notification_service(s)
    adapter = _RecordingAdapter()
    s.notification_service._adapter = adapter

    await s.eventbus.publish(NotificationEvent(level="error", title="기동 중"))
    assert adapter.titles == []

    s.notification_service.release()
    await s.notification_service.stop()
    assert adapter.titles == ["기동 중"]


@pytest.mark.asyncio
async def test_receiver_skips_when_service_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """서비스가 없으면(시크릿 없음·공란) 수신기도 만들지 않고 돌아온다."""
    captured = _receiver_stub(monkeypatch)
    s = _make_services(telegram_enabled="true", secrets=None)

    await _init_notification_service(s)
    await _init_telegram_receiver(s)

    assert s.notification_service is None
    assert s.telegram_receiver is None
    assert captured == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chat_id", "telegram_enabled", "level", "phrase"),
    [
        (
            "not-int",
            "true",
            logging.WARNING,
            "TELEGRAM_CHAT_ID 값이 올바른 정수가 아닙니다: 'not-int' — 무시합니다",
        ),
        (
            "42",
            "false",
            logging.INFO,
            "TelegramCommandReceiver 건너뜀 — telegram_enabled=false",
        ),
        (
            "not-int",
            "true",
            logging.INFO,
            "TelegramCommandReceiver 건너뜀 — TELEGRAM_CHAT_ID 미설정",
        ),
    ],
)
async def test_receiver_skip_branches_keep_log_phrases(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    chat_id: str,
    telegram_enabled: str,
    level: int,
    phrase: str,
) -> None:
    """수신기의 건너뜀 분기 셋은 나눈 뒤에도 같은 로그 문구로 건너뛴다."""
    captured = _receiver_stub(monkeypatch)
    s = _real_service_services(chat_id=chat_id, telegram_enabled=telegram_enabled)

    with caplog.at_level(logging.INFO, logger="ante.main"):
        await _init_notification_service(s)
        await _init_telegram_receiver(s)

    assert s.notification_service is not None
    assert s.telegram_receiver is None
    assert captured == []
    assert any(
        r.levelno == level and r.getMessage() == phrase for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_rules_unavailable_notice_is_sent_exactly_once() -> None:
    """뒤로 늦춘 규칙 차단 알림은 쌓였다가 해제 뒤 정확히 한 번 나간다."""
    from ante.main import _notify_rules_unavailable

    s = _real_service_services()
    await _init_notification_service(s)
    adapter = _RecordingAdapter()
    s.notification_service._adapter = adapter
    s.rule_engine_manager = SimpleNamespace(
        rules_unavailable_accounts=lambda: {"acc-1": "not_list"}
    )

    await _notify_rules_unavailable(s)
    s.notification_service.release()
    await s.notification_service.stop()

    assert adapter.titles == ["계좌 규칙을 읽지 못함 — 주문 차단"]


def _shutdown_services(adapter: _RecordingAdapter) -> tuple[Services, list[str]]:
    from ante.eventbus import EventBus
    from ante.notification.service import NotificationService

    s = Services()
    s.eventbus = EventBus()
    s.notification_service = NotificationService(
        adapter=adapter,  # type: ignore[arg-type]
        eventbus=s.eventbus,
    )
    s.notification_service.subscribe(defer=True)
    seen_at_receiver_stop: list[str] = []

    class _Receiver:
        async def stop(self) -> None:
            seen_at_receiver_stop.extend(adapter.titles)

    s.telegram_receiver = _Receiver()
    return s, seen_at_receiver_stop


@pytest.mark.asyncio
async def test_shutdown_with_empty_queue_sends_system_stop_right_away() -> None:
    """큐가 빈 평소 종료에서 「시스템 종료」는 정지 전에 바로 닿는다."""
    from ante.main import _shutdown

    adapter = _RecordingAdapter()
    s, seen = _shutdown_services(adapter)
    s.notification_service.release()
    await asyncio.sleep(0)

    await _shutdown(s)

    assert seen == ["시스템 종료"]
    assert adapter.titles == ["시스템 종료"]


@pytest.mark.asyncio
async def test_shutdown_during_drain_sends_system_stop_last() -> None:
    """큐를 비우는 중의 종료에서 「시스템 종료」는 버려지지 않고 마지막으로 닿는다."""
    from ante.eventbus.events import NotificationEvent
    from ante.main import _shutdown

    adapter = _RecordingAdapter(delay=0.1)
    s, _ = _shutdown_services(adapter)
    for title in ("A", "B", "C"):
        await s.eventbus.publish(NotificationEvent(level="error", title=title))
    s.notification_service.release()

    await asyncio.wait_for(_shutdown(s), timeout=10.0)

    assert adapter.titles == ["A", "B", "C", "시스템 종료"]
