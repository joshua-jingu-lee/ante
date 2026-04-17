# Logging 세부 설계 - Fingerprint 규칙

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# Fingerprint 규칙

같은 근본 원인으로 반복 발생하는 예외를 묶기 위한 안정 식별자다. 감시 에이전트가 GitHub 이슈의 dedup 키로 사용한다.

## 생성 방식

```
{exception class}@{스택에서 가장 최근의 ante.* 프레임 module:function}
```

## 매칭 규칙

1. 스택 프레임을 **최근 호출 → 먼 호출** 순으로 순회한다.
2. 프레임의 모듈 경로가 `ante.` 접두어로 시작하는 첫 프레임을 선택한다.
3. 선택된 프레임의 `module:function` 값을 조합한다.
4. 해당하는 프레임이 없으면 폴백 규칙을 적용한다.

### 예시

| 조건 | Fingerprint |
|---|---|
| `ante.broker.kis_stream.handle_reconnect` 내부에서 `ConnectionError` | `ConnectionError@ante.broker.kis_stream:handle_reconnect` |
| `ante.bot.manager.start` 내부에서 `ValueError` | `ValueError@ante.bot.manager:start` |
| 스택에 `ante.*` 프레임이 없음 (로거만 호출) | `{exception class}@{logger 이름}` (폴백) |

## 제외 규칙

다음 프레임은 `ante.*` 탐색 대상에서 제외한다.

- 표준 라이브러리 (`asyncio.*`, `threading.*`, `logging.*` 등)
- 외부 라이브러리 (`httpx.*`, `fastapi.*`, `aiosqlite.*`, `websockets.*` 등)
- 테스트 프레임워크 (`pytest.*`, `_pytest.*`)

모듈 이름이 `ante.`로 시작하지 않으면 자동으로 제외된다.

## 안정성 요구사항

Fingerprint는 **코드 변경에 둔감**해야 한다. 같은 근본 원인이 여러 리팩터링을 거쳐도 동일한 키를 유지한다.

- **라인번호 포함 안 함**: 코드 이동·주석 추가에 영향받지 않는다.
- **함수명 레벨의 해상도**: 파일 내부에서 여러 예외 호출이 있어도 함수 단위로 묶인다.
- **모듈 경로 포함**: 같은 함수명이 다른 모듈에 있어도 구분된다.

## 폴백 전략

스택에 `ante.*` 프레임이 없는 케이스는 드물지만, 예를 들어 외부 라이브러리 내부에서 `logger.error("...")`만 호출되는 경우가 발생할 수 있다. 이때는 `logger` 이름으로 대체한다.

```
ConnectionError@ante.broker.kis  # (logger=ante.broker.kis, ante.* 프레임 없음)
```

## 감시 에이전트 계약

Fingerprint는 GitHub 이슈의 dedup 키로 사용된다. 이 계약은 `docs/specs/` 외부(감시 에이전트 커맨드 정의)에서 관리되며, 본 스펙은 **Fingerprint의 생성 규칙과 안정성**만 정의한다.

- 이슈 검색 시 타이틀 매칭 + body 내 `<!-- fingerprint: ... -->` HTML 코멘트 매칭을 병행한다 (감시 에이전트 구현 세부).
- Fingerprint 규칙이 변경되면 기존 이슈와의 매칭이 어긋날 수 있다. 변경 시 마이그레이션 계획을 동반한다.
