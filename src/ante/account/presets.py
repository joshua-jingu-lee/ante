"""브로커 프리셋 정의."""

from decimal import Decimal

from ante.account.models import BrokerPreset

BROKER_PRESETS: dict[str, BrokerPreset] = {
    "test": BrokerPreset(
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        default_account_id="test",
        default_name="테스트",
        required_credentials=[],
    ),
    "kis-domestic": BrokerPreset(
        exchange="KRX",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="09:00",
        trading_hours_end="15:30",
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
        default_account_id="domestic",
        default_name="국내 주식",
        required_credentials=["app_key", "app_secret", "account_no"],
    ),
    # kis-overseas 프리셋은 정의만 해둔다.
    # KISOverseasAdapter 구현 및 BROKER_REGISTRY 등록은 1.1에서 지원.
    "kis-overseas": BrokerPreset(
        exchange="NYSE",
        currency="USD",
        timezone="America/New_York",
        trading_hours_start="09:30",
        trading_hours_end="16:00",
        buy_commission_rate=Decimal("0.001"),
        sell_commission_rate=Decimal("0.001"),
        default_account_id="us-stock",
        default_name="미국 주식",
        required_credentials=["app_key", "app_secret", "account_no"],
    ),
}
