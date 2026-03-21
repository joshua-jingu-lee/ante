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
