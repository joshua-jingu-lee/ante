# Logging 세부 설계 - JSON 로그 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# JSON 로그 스키마

JSONL 파일에 기록되는 한 줄의 구조를 정의한다. stdout 평문 핸들러는 본 스키마와 무관하게 기존 포맷(`%(asctime)s [%(levelname)s] %(name)s: %(message)s`)을 사용한다.

## 필수 필드 (모든 엔트리)

| 필드 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `ts` | string (ISO 8601 UTC) | `"2026-04-17T20:15:32.145Z"` | 타임존 독립 정렬·비교 |
| `level` | string | `"ERROR"` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `logger` | string | `"ante.broker.kis.adapter"` | Python logger 이름 (모듈 경로) |
| `msg` | string | `"주문 전송 실패"` | 주 메시지 (`logger.error(...)`의 첫 인자 치환 결과) |
| `env` | string | `"staging"` | `ANTE_ENV` 환경변수 값 |

**최소 엔트리 예시**:

```json
{"ts":"2026-04-17T20:15:34.002Z","level":"INFO","logger":"ante.bot.manager","msg":"봇 pingpong-1 상태 OK","env":"staging"}
```

## 선택 컨텍스트 필드

호출자가 `logger.error(msg, extra={...})` 형태로 주입한 값이 최상위 필드로 승격된다. 권장 키 목록:

| 필드 | 타입 | 사용 맥락 |
|---|---|---|
| `account_id` | string | Broker/Trade 경로 |
| `bot_id` | string | 봇 수명주기 |
| `strategy_id` | string | 전략 실행 |
| `order_id` | string | 주문 흐름 추적 |
| `symbol` | string | 종목 관련 |
| `request_id` | string | Web API 요청 |
| `extra` | object | 모듈 특수 정보 (표준 필드에 들지 않는 자유 객체) |

**예시**:

```json
{"ts":"2026-04-17T20:15:32.145Z","level":"ERROR","logger":"ante.broker.kis","msg":"주문 전송 실패","env":"staging","account_id":"paper01","order_id":"ord-123","extra":{"code":403}}
```

## 예약어 처리

표준 필드와 중복되는 키(`ts`, `level`, `logger`, `msg`, `env`, `exc`)는 `extra=`로 주입해도 무시된다. Formatter가 표준 값으로 덮어쓰며, 호출자의 실수로 로그 구조가 깨지지 않도록 보호한다.

## Exception 필드 (예외 포함 시)

`logger.exception()` 또는 `logger.error(..., exc_info=True)` 호출 시 Formatter가 자동 생성한다.

```json
{
  "exc": {
    "type": "ConnectionError",
    "message": "WebSocket closed unexpectedly",
    "traceback": "Traceback (most recent call last):\n  ...",
    "fingerprint": "ConnectionError@ante.broker.kis_stream:handle_reconnect"
  }
}
```

| 필드 | 설명 |
|---|---|
| `exc.type` | 예외 클래스명 |
| `exc.message` | `str(exception)` |
| `exc.traceback` | `traceback.format_exception()` 결과 (단일 문자열, JSON 이스케이프) |
| `exc.fingerprint` | 같은 에러를 식별하는 안정 키 ([04-fingerprint.md](04-fingerprint.md) 참조) |

## 직렬화 규칙

- JSON 출력은 `ensure_ascii=False`로 한글·비ASCII 문자를 유지한다.
- 키 순서는 필수 필드 → 컨텍스트 필드 → `exc` 순서를 권장한다 (가독성).
- 한 레코드는 반드시 단일 라인으로 직렬화되며 내부에 개행 문자가 포함되지 않는다 (`exc.traceback`의 개행은 `\n`으로 이스케이프).
- 출력은 **strict JSON**이어야 한다. `NaN`, `Infinity`, `-Infinity` 같은 non-finite float는 `null`로 정규화한다 (중첩 dict/list 내부도 재귀적으로 적용). 지표·시세 경로에서 non-finite 값이 `extra=`로 유입되더라도 로그 파이프가 깨지지 않도록 Formatter가 방어한다.
