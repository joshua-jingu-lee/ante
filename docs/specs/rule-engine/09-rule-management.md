# Rule Engine 모듈 세부 설계 - 룰 정의 및 관리

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 룰 정의 및 관리

룰은 계좌별 설정 파일로 정의되며, 동적으로 추가/수정 가능.

```toml
[accounts.domestic.rules]
daily_loss_limit = { max_daily_loss_rate = 0.05, action = "halt" }
total_exposure_limit = { max_exposure_rate = 0.8 }
# trading_hours는 Account의 trading_hours_start/end, timezone에서 자동 주입

[accounts.us-stock.rules]
daily_loss_limit = { max_daily_loss_rate = 0.03, action = "halt" }
total_exposure_limit = { max_exposure_rate = 0.7 }
# trading_hours는 Account의 trading_hours_start/end, timezone에서 자동 주입
```

> `trading_hours` 룰의 시간대와 거래 시간은 Account 모델에서 자동 주입되므로, 룰 설정에서 별도로 지정하지 않는다. Account의 `trading_hours_start`, `trading_hours_end`, `timezone` 필드가 곧 TradingHoursRule의 설정이 된다.

전략별 룰은 계좌 설정 하위에 정의한다:

```json
{
  "accounts": {
    "domestic": {
      "strategy": {
        "my_strategy": {
          "position_size": {
            "id": "position_size",
            "name": "Position Size Limit",
            "type": "position_size",
            "enabled": true,
            "priority": 10,
            "config": {
              "max_position_percent": 0.10,
              "max_position_amount": 1000.0
            }
          }
        }
      }
    }
  }
}
```
