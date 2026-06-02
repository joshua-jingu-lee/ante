# Strategy 모듈 세부 설계 - 설계 결정 - AST 기반 정적 검증 (StrategyValidator)

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# AST 기반 정적 검증 (StrategyValidator)

구현: `src/ante/strategy/validator.py` 참조

전략 파일을 **실행하지 않고** AST 분석으로 안전성과 적합성을 검증한다.

#### ValidationResult 필드

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `valid` | `bool` | — | 검증 통과 여부 |
| `errors` | `list[str]` | `[]` | 에러 메시지 목록 |
| `warnings` | `list[str]` | `[]` | 경고 메시지 목록 |

검증 항목은 다음과 같다:

1. **파싱 가능 여부** — source-read + AST-parse 단계 (에러). 아래 매트릭스의 4클래스 중 하나라도 발생하면 `validate()` 수렴점에서 `ValidationResult(valid=False, errors=[content-free 안정 메시지], warnings=[])` 를 반환한다. 어떤 경우에도 `str(exception)`/예외 repr/codec명/byte/문자/토큰/소스 라인 텍스트를 `errors[]`에 포함하지 않는다 (#1675 input-reflection invariant).

    | 클래스 | 표면 | `errors[0]` 정규화 |
    |---|---|---|
    | `UnicodeDecodeError` (=`ValueError` 서브) | `filepath.read_text(encoding="utf-8")` 의 binary/non-UTF8 실패 | `"전략 파일을 텍스트 전략 소스로 읽을 수 없습니다."` (`_NOT_TEXT_SOURCE`, 고정 상수) |
    | `OSError` 계열 (`IsADirectoryError`, `PermissionError`, race-delete 후 `FileNotFoundError` 등) | `filepath.read_text(...)` 의 파일 접근 실패 | `"전략 파일에 접근할 수 없습니다."` (`_FILE_NOT_READABLE`, 고정 상수) |
    | `SyntaxError` | `ast.parse(...)` 문법 오류 | `f"Syntax error (line {e.lineno or 0}, offset {e.offset or 0})"` — **정수 line/offset 만** 노출 (`_syntax_msg(e)`). `str(e)`/`{e}` 금지 |
    | `ValueError` (`UnicodeDecodeError` 외, source-read/parse 단계의 드문 잔여) | `filepath.read_text(...)` 또는 `ast.parse(...)` | `_NOT_TEXT_SOURCE` |

    예외 순서는 `SyntaxError → OSError → (UnicodeDecodeError, ValueError)` 로 고정한다. `UnicodeDecodeError` 는 `ValueError` 서브이므로 마지막 묶음에서 잡히고, `IsADirectoryError`/`PermissionError`/`FileNotFoundError` 는 `OSError` 에서 잡힌다. 본 정규화는 `validate()` source-read + AST-parse 단계로 **한정**한다 — semantic 단계의 actionable 메시지(아래 2~9 항목)는 별도 계약이다.

2. **Strategy 상속 클래스 존재 여부** — 파일 내 정확히 1개의 Strategy 하위 클래스 필요 (에러). 메시지(`"No class inheriting from Strategy found"`, `"Multiple Strategy subclasses found: ..."`)는 사용자가 제출한 식별자(클래스명)를 의도적으로 노출하는 **actionable 계약**이다 (#1675 no-reflection 매트릭스 OUT-OF-SCOPE).
3. **필수 요소 검사** — `meta` 클래스 변수, `on_step()` 메서드 존재 확인 (에러). `accepts_external_signals=True`인데 `on_data()` 미구현 시 경고. 메시지의 멤버명·키워드는 actionable 계약이다.
4. **금지 모듈 import 검사** — 시스템 접근(`os`, `subprocess`), 네트워크(`requests`, `httpx`), DB 직접 접근(`sqlite3`), 파일시스템(`pathlib`) 등 차단 (에러). `"Forbidden import: {module}"` 의 module 식별자는 actionable 계약이다.
5. **금지된 내장 함수 호출** — `eval()`, `exec()`, `compile()`, `__import__()`, `open()`, `globals()`, `locals()` 호출 탐지 (에러). `"Forbidden built-in call: {name}() at line {lineno}"` 의 함수명·라인은 actionable 계약이다. `open()`은 builtin 파일시스템 게이트, `globals()`/`locals()`는 샌드박스 우회 경로이므로 경고가 아닌 에러로 차단한다 (전략은 파일시스템 접근 불가 — #4의 `pathlib` import 에러 차단과 정합). 이 목록의 SSOT는 `src/ante/strategy/validator.py`의 `FORBIDDEN_BUILTINS` 집합이며, 향후 항목 추가 시 코드와 본 스펙을 함께 동기한다. 탐지는 직접 호출(`open(...)`)뿐 아니라 `__builtins__["open"](...)` / `__builtins__.open(...)` 우회 형태도 포함한다.
6. **금지된 최상위 코드** — import, 클래스/함수 정의, 리터럴 상수 할당, docstring 외의 최상위 실행 코드 차단 (에러). `"Forbidden top-level code at line {lineno}: {NodeType}"` 의 AST 노드 타입명·라인은 actionable 계약이다.
7. **위험 패턴 경고** — 현재 경고로 분류되는 위험 패턴 없음. `open()` 파일 접근 호출은 보안 강화 결정에 따라 #5(금지된 내장 함수 호출)로 승격되어 **에러**로 차단한다. `_find_dangerous_patterns()`는 현재 빈 경고 목록을 반환하며, 향후 로드는 허용하되 알릴 위험 패턴이 생기면 이 항목에 추가한다.
8. **exchange 유효성 검증** — `meta.exchange` 값이 유효한 거래소 코드인지 검증 (에러). 유효 값: `VALID_EXCHANGES = {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"}`. `"Invalid exchange value: '{value}'. Valid values: ..."` 의 exchange 식별자는 actionable 계약이다.
9. **symbols와 exchange 일관성 경고** — `symbols`가 명시된 경우, 심볼 형식이 exchange와 맞는지 경고 표시. 예: KRX 전략에 `"AAPL"`은 KRX 종목코드 형식이 아님 (경고)

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> `VALID_EXCHANGES`는 canonical 5종 + `*`(StrategyMeta 전용 wildcard)다. 표면별 거부 계약·코드 SSOT 정렬은 #1576/#1578에서 다룬다(현재 코드/스펙 drift).

**설계 근거**:

1. **AST 기반 (실행 없이 분석)**
   - AI Agent가 생성한 코드를 실행 전에 안전성 확보
   - FreqTrade는 실행 후 검증(dry-run), Ante는 실행 전 정적 검증 추가
   - 금지 모듈 import가 있는 전략은 로드 자체를 차단

2. **블랙리스트 방식 (금지 모듈 목록)**
   - 화이트리스트(허용 모듈만 열거)는 Agent의 유연성을 과도하게 제한
   - numpy, polars, pandas-ta 등 데이터 분석 라이브러리는 자유롭게 사용 가능
   - 시스템 접근(os, sys, subprocess, shutil, ctypes), 네트워크(socket, http, urllib, requests, aiohttp, httpx), DB 직접 접근(sqlite3, sqlalchemy), 코드 로딩(importlib, pickle), 파일시스템(pathlib) 차단

3. **경고(warning)와 에러(error) 분리**
   - 에러: 로드 차단 사유 (금지 모듈, 필수 요소 미비, 금지된 내장 함수 호출)
   - 경고: 사용자에게 알리되 로드는 허용 (예: `accepts_external_signals=True`인데 `on_data()` 미구현, symbols/exchange 형식 불일치)
   - 파일시스템/샌드박스 우회 경로는 모두 에러로 차단한다: `open()`/`globals()`/`locals()` 호출(#5), `pathlib`/`os`/`subprocess` import(#4)
   - CLI에서 `ante strategy validate`로 확인 가능
