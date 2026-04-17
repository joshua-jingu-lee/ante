# Logging 세부 설계 - 컨텍스트 필드 주입 패턴

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# 컨텍스트 필드 주입 패턴

호출 지점에서 도메인 맥락을 로그에 담기 위한 규약이다. 기존 호출부를 모두 바꾸지 않고, **새로 작성하거나 중요한 경로에만 선택적으로 적용**한다.

## 기본 패턴

```python
# Before (기존, 그대로 동작)
logger.error("주문 전송 실패: code=%d", code)

# After (선택적 보강)
logger.error(
    "주문 전송 실패",
    extra={"account_id": account_id, "order_id": order_id, "code": code},
)
```

JSON 출력 예:

```json
{"ts":"2026-04-17T20:15:32.145Z","level":"ERROR","logger":"ante.broker.kis","msg":"주문 전송 실패","env":"staging","account_id":"paper01","order_id":"ord-123","extra":{"code":403}}
```

## 승격 규칙

`extra={}` 에 전달된 키는 다음 규칙에 따라 처리된다.

1. **표준 컨텍스트 키**([03-json-schema.md](03-json-schema.md) §선택 컨텍스트 필드)는 최상위 필드로 승격된다.
2. **비표준 키**는 `extra` 하위 객체에 중첩된다.
3. **예약 키**(`ts`, `level`, `logger`, `msg`, `env`, `exc`)는 무시된다.

**혼합 예시**:

```python
logger.info(
    "봇 시작",
    extra={
        "bot_id": "pingpong-1",       # 표준 → 최상위
        "strategy_id": "ping_pong",   # 표준 → 최상위
        "start_mode": "restored",     # 비표준 → extra 중첩
        "level": "IGNORED",           # 예약 → 무시
    },
)
```

출력:

```json
{"ts":"...","level":"INFO","logger":"ante.bot.manager","msg":"봇 시작","env":"staging","bot_id":"pingpong-1","strategy_id":"ping_pong","extra":{"start_mode":"restored"}}
```

## 권장 주입 경로

다음 경로는 Fingerprint 분석·이슈 추적에 가치가 크므로 우선 주입한다.

| 경로 | 권장 필드 |
|---|---|
| `ante.broker.*` (KIS 어댑터, 주문) | `account_id`, `order_id`, `symbol` |
| `ante.bot.*` (봇 수명주기) | `bot_id`, `strategy_id` |
| `ante.trade.*` (체결·포지션) | `account_id`, `order_id`, `symbol` |
| `ante.web.*` (API 핸들러) | `request_id`, `account_id` (인증된 경우) |
| `ante.rule.*` (룰 평가) | `account_id`, `bot_id` |

다른 모듈은 기존 호출부 유지로 충분하다. 전체 모듈에 일괄 주입하는 작업은 우선순위가 낮다.

## 민감값 취급

**절대 주입하지 말아야 할 값**:
- 토큰 원본 (`ante_hk_*`, `ante_ak_*`, KIS APP_SECRET 등)
- 비밀번호·해시 원본
- KIS 계좌번호 원본 (마스킹 후 주입 또는 생략)
- 세션 쿠키

호출자 책임으로 마스킹 후 주입한다. 로깅 인프라는 주입된 값을 그대로 직렬화하므로, 필터링이나 redaction을 수행하지 않는다.

**마스킹 예시**:

```python
masked_account = account_number[:4] + "****" + account_number[-2:]
logger.error("계좌 조회 실패", extra={"account_number_masked": masked_account})
```

## 주입 실패에 대한 내성

`extra=` 주입은 로깅 인프라의 "선택적" 기능이다. 누락되어도 필수 필드만으로 엔트리가 유효하다. 미래에 감시 에이전트가 고도화되면 주입 빈도가 자연스럽게 늘어난다. 지금 모든 경로를 강제하지 않는다.
