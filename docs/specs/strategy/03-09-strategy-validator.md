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

1. **파싱 가능 여부** — 문법 오류 체크 (에러)
2. **Strategy 상속 클래스 존재 여부** — 파일 내 정확히 1개의 Strategy 하위 클래스 필요 (에러)
3. **필수 요소 검사** — `meta` 클래스 변수, `on_step()` 메서드 존재 확인 (에러). `accepts_external_signals=True`인데 `on_data()` 미구현 시 경고
4. **금지 모듈 import 검사** — 시스템 접근(`os`, `subprocess`), 네트워크(`requests`, `httpx`), DB 직접 접근(`sqlite3`), 파일시스템(`pathlib`) 등 차단 (에러)
5. **금지된 내장 함수 호출** — `eval()`, `exec()`, `compile()`, `__import__()` 호출 탐지 (에러)
6. **금지된 최상위 코드** — import, 클래스/함수 정의, 리터럴 상수 할당, docstring 외의 최상위 실행 코드 차단 (에러)
7. **위험 패턴 경고** — `open()` 파일 접근 호출 탐지 (경고)
8. **exchange 유효성 검증** — `meta.exchange` 값이 유효한 거래소 코드인지 검증 (에러). 유효 값: `VALID_EXCHANGES = {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"}`
9. **symbols와 exchange 일관성 경고** — `symbols`가 명시된 경우, 심볼 형식이 exchange와 맞는지 경고 표시. 예: KRX 전략에 `"AAPL"`은 KRX 종목코드 형식이 아님 (경고)

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
   - 에러: 로드 차단 사유 (금지 모듈, 필수 요소 미비)
   - 경고: 사용자에게 알리되 로드는 허용 (eval 호출, open 사용 등)
   - CLI에서 `ante strategy validate`로 확인 가능
