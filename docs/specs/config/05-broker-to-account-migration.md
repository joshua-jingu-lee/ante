# Config 모듈 세부 설계 - Broker → Account 마이그레이션

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# Broker → Account 마이그레이션

기존 `[broker]` 섹션의 일부 설정은 Account 모델로 이관된다.

**이관 대상:**

| 기존 설정 | 이관 후 |
|-----------|---------|
| `broker.type` | `Account.broker_type` |
| `broker.commission_rate` | `Account.commission_rate` |
| `broker.sell_tax_rate` | `Account.sell_tax_rate` |
| `secrets.env`의 `KIS_APP_KEY` 등 | `Account.credentials_ref` → `secrets.env`의 `KIS_{ACCOUNT_ID}_*` |

**실행 주체:**

`ante init`은 이 마이그레이션을 수행하지 않는다 (재설계 2026-04, #1125). 현행 `ante init`은 비대화형 최소 bootstrap(파일 골격 + master + default test account)만 수행하며, 기존 `[broker]` 섹션을 감지하거나 변환하지 않는다.

기존 broker 설정이 남아 있는 환경의 이관은 별도 명령으로 처리한다 (구체 명령은 마이그레이션 도구가 도입될 때 본 문서에 갱신).

**기대 변환 흐름 (마이그레이션 도구 기준):**

```
마이그레이션 도구 실행
  → 기존 [broker] 섹션 감지
  → Account(id="default", broker_type=broker.type, ...) 생성
  → secrets.env의 KIS_* 키를 KIS_DEFAULT_* 접두사로 매핑
  → [broker] 섹션에서 이관된 키 제거 (인프라 설정만 유지)
```
