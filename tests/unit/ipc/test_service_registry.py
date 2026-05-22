"""ServiceRegistry 테스트."""

from unittest.mock import MagicMock

from ante.core.registry import ServiceRegistry


def test_service_registry_creation() -> None:
    """ServiceRegistry 데이터클래스 생성 확인."""
    account = MagicMock()
    bot_manager = MagicMock()
    treasury_manager = MagicMock()
    dynamic_config = MagicMock()
    approval = MagicMock()
    reconciler = MagicMock()
    eventbus = MagicMock()

    reg = ServiceRegistry(
        account=account,
        bot_manager=bot_manager,
        treasury_manager=treasury_manager,
        dynamic_config=dynamic_config,
        approval=approval,
        reconciler=reconciler,
        eventbus=eventbus,
    )

    assert reg.account is account
    assert reg.bot_manager is bot_manager
    assert reg.treasury_manager is treasury_manager
    assert reg.dynamic_config is dynamic_config
    assert reg.approval is approval
    assert reg.reconciler is reconciler
    assert reg.eventbus is eventbus
    # Refs #1712: ``trade_service`` 는 optional default=None — 기존 호출
    # 호환성 (audit_logger 와 동형). legacy ServiceRegistry 호출자
    # (``trade_service`` 인자 미전달) 가 그대로 동작한다.
    assert reg.trade_service is None


def test_service_registry_accepts_trade_service() -> None:
    """Refs #1712: ``trade_service`` 를 명시 전달하면 그대로 보관된다.

    IPC ``bot.status`` handler 는 ``getattr(svc, "trade_service", None)`` 으로
    optional access 하며, 주입된 경우 ``enrich_bot_info`` 가 positions 보강에
    사용한다.
    """
    trade_service = MagicMock()
    reg = ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        trade_service=trade_service,
    )
    assert reg.trade_service is trade_service
