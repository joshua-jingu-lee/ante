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
        # 결정적 테스트를 위해 buffer는 0으로 둔다 (#1333).
        market_order_reserve_buffer_rate=Decimal("0"),
        default_account_id="test",
        default_name="테스트",
        required_credentials=["app_key", "app_secret"],
    ),
    "kis-domestic": BrokerPreset(
        exchange="KRX",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="09:00",
        trading_hours_end="15:30",
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
        # 시장가 매수의 가격 변동 흡수를 위한 0.5% 보수 버퍼 (#1333).
        market_order_reserve_buffer_rate=Decimal("0.005"),
        default_account_id="domestic",
        default_name="국내 주식",
        required_credentials=["app_key", "app_secret", "account_no"],
    ),
}
