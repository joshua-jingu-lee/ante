"""Config 기본값 시드 등록 테스트."""

import pytest

from ante.config import DynamicConfigService
from ante.config.defaults import DEFAULTS
from ante.core import Database


class FakeEventBus:
    """테스트용 EventBus 대역."""

    def __init__(self):
        self.published: list = []

    async def publish(self, event):
        self.published.append(event)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return FakeEventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = DynamicConfigService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


CATEGORY_MAP = {
    "rule": "trading",
    "risk": "trading",
    "bot": "trading",
    "broker": "trading",
    "notification": "notification",
    "display": "display",
    "system": "system",
}


async def _seed_defaults(service: DynamicConfigService) -> None:
    """DEFAULTS를 register_default로 시드하는 헬퍼."""
    for key, value in DEFAULTS.items():
        prefix = key.split(".")[0]
        category = CATEGORY_MAP.get(prefix, "system")
        await service.register_default(key, str(value), category=category)


async def test_defaults_seeded(service):
    """초기화 후 DEFAULTS의 모든 키가 등록되어 있는지 확인한다."""
    await _seed_defaults(service)

    all_configs = await service.get_all()
    registered_keys = {row["key"] for row in all_configs}

    for key in DEFAULTS:
        assert key in registered_keys, f"기본값 키 '{key}'가 등록되지 않았다"


async def test_existing_value_not_overwritten(service):
    """이미 수정된 값이 register_default로 덮어써지지 않는다."""
    # 사용자가 먼저 값을 설정
    await service.set("rule.daily_loss_limit", 0.03, category="trading")

    # 기본값 시드 실행
    await _seed_defaults(service)

    # 사용자가 설정한 값이 보존되어야 함
    value = await service.get("rule.daily_loss_limit")
    assert value == 0.03, f"사용자 설정값 0.03이 기본값으로 덮어써졌다: {value}"


async def test_new_defaults_contain_risk_keys(service):
    """리스크 관리 관련 기본값 키가 DEFAULTS에 포함되어 있다."""
    expected_risk_keys = [
        "rule.daily_loss_limit",
        "rule.max_exposure_percent",
        "rule.max_unrealized_loss",
        "rule.max_trades_per_hour",
        "rule.allowed_hours",
        "risk.max_mdd_pct",
        "risk.max_position_pct",
    ]
    for key in expected_risk_keys:
        assert key in DEFAULTS, f"리스크 키 '{key}'가 DEFAULTS에 없다"


async def test_new_defaults_contain_trading_keys(service):
    """봇, 거래비용, 알림 관련 기본값 키가 DEFAULTS에 포함되어 있다."""
    expected_keys = [
        "bot.default_interval_sec",
        "broker.commission_rate",
        "broker.sell_tax_rate",
        "notification.telegram_enabled",
        "notification.telegram_level",
        "notification.fill_alert",
        "notification.daily_report",
    ]
    for key in expected_keys:
        assert key in DEFAULTS, f"키 '{key}'가 DEFAULTS에 없다"


async def test_telegram_enabled_default_is_true():
    """notification.telegram_enabled 기본값이 'true'이다 (Refs #997)."""
    assert DEFAULTS["notification.telegram_enabled"] == "true"


async def test_removed_telegram_command_keys():
    """telegram.command.* 키가 DEFAULTS에서 제거되었다 (Refs #997)."""
    assert "telegram.command.polling_interval" not in DEFAULTS
    assert "telegram.command.confirm_timeout" not in DEFAULTS
