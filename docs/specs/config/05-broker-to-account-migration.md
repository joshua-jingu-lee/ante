# Config 모듈 세부 설계 - Broker → Account 마이그레이션

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# Broker → Account 마이그레이션

기존 `[broker]` 섹션의 일부 설정은 Account 모델로 이관된다.
이관 후 Account 필드명과 산정 규칙의 SSOT는
[Account config migration](../account/08-config-migration.md)이다. 이 문서는 Config
관점에서 legacy source의 위치와 실행 주체만 요약한다.

**호환 요약:**

| Legacy source | Canonical Account output |
|---------------|--------------------------|
| `broker.type` | `broker_type` |
| `broker.commission_rate` | `buy_commission_rate` |
| `broker.commission_rate` + `broker.sell_tax_rate` | `sell_commission_rate` |
| `secrets.env`의 `KIS_*` | encrypted `credentials` JSON |

`credentials_ref`, `commission_rate`, `sell_tax_rate`는 이관 후 Account API/DB 필드가
아니다. Config 문서에서 이 이름이 등장한다면 legacy 설정 입력을 설명하는 용도로만
사용한다.

**실행 주체:**

`ante init`은 이 마이그레이션을 수행하지 않는다 (재설계 2026-04, #1125). 현행 `ante init`은 비대화형 최소 bootstrap(파일 골격 + master + default test account)만 수행하며, 기존 `[broker]` 섹션을 감지하거나 변환하지 않는다.

기존 broker 설정이 남아 있는 환경의 이관은 별도 명령으로 처리한다 (구체 명령은 마이그레이션 도구가 도입될 때 본 문서에 갱신).

**기대 변환 흐름 (마이그레이션 도구 기준):**

```
마이그레이션 도구 실행
  → 기존 [broker] 섹션 감지
  → Account(id="default", broker_type=broker.type, ...) 생성
  → secrets.env의 KIS_* 키를 Account.credentials JSON으로 암호화 저장
  → [broker] 섹션에서 이관된 키 제거 (인프라 설정만 유지)
```
