# Config 모듈 세부 설계 - Broker → Account 마이그레이션

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# Broker → Account 마이그레이션

기존 `[broker]` 섹션의 일부 설정은 Account 모델로 이관된다. `ante init` 실행 시 기존 broker 설정이 자동으로 "default" Account로 변환된다.

**이관 대상:**

| 기존 설정 | 이관 후 |
|-----------|---------|
| `broker.type` | `Account.broker_type` |
| `broker.commission_rate` | `Account.commission_rate` |
| `broker.sell_tax_rate` | `Account.sell_tax_rate` |
| `secrets.env`의 `KIS_APP_KEY` 등 | `Account.credentials_ref` → `secrets.env`의 `KIS_{ACCOUNT_ID}_*` |

**자동 변환 흐름:**

```
ante init 실행
  → 기존 [broker] 섹션 감지
  → Account(id="default", broker_type=broker.type, ...) 자동 생성
  → secrets.env의 KIS_* 키를 KIS_DEFAULT_* 접두사로 매핑
  → [broker] 섹션에서 이관된 키 제거 (인프라 설정만 유지)
```
