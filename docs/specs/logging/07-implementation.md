# Logging 세부 설계 - 구현 위치와 설계 근거

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# 구현 위치

| 자산 | 경로 | 역할 |
|---|---|---|
| `JsonFormatter` | `src/ante/core/log/formatter.py` (신설) | `logging.Formatter` 상속, `format()`이 [03-json-schema.md](03-json-schema.md)의 스키마에 따라 JSON 직렬화 |
| `compute_fingerprint` | `src/ante/core/log/fingerprint.py` (신설) | Exception과 traceback 객체에서 [04-fingerprint.md](04-fingerprint.md) 규칙에 따라 키 생성 |
| `setup_logging` | `src/ante/core/log/setup.py` (신설) | 핸들러 구성 함수. `config`, 환경변수, 로그 디렉토리를 입력으로 받아 `logging` 루트 로거에 핸들러 부착 |
| `AnteLogger` / `install_safe_logger` | `src/ante/core/log/safe_logger.py` (신설) | 예약 키가 `extra=` 로 주입되어도 `makeRecord` KeyError 없이 무시되도록 Logger 서브클래스 등록 |
| `DateNamedTimedRotatingFileHandler` | `src/ante/core/log/handlers.py` (신설) | 활성 파일명에 `YYYY-MM-DD` 를 포함시켜 자정 경계에서 **파일명 교체**로 회전 (이름 바꾸기 없음) |
| 예약 키 단일 소스 | `src/ante/core/log/_record_keys.py` (신설) | `LOGRECORD_ATTRS` 는 런타임 프로브로 추출, `ANTE_RESERVED` 는 JSONL 스펙 필드. formatter/safe_logger 가 공유 |
| 통합 지점 | `src/ante/main.py` `_init_core` | 기존 `logging.basicConfig(...)`을 `setup_logging(config)`으로 교체 |
| 테스트 | `tests/unit/test_log_formatter.py`, `tests/unit/test_log_setup.py`, `tests/unit/test_log_safe_logger.py` | 스키마·fingerprint·이중 핸들러·예약 키 방어 회귀 검증 |

## 스펙 § → 코드 → 회귀 테스트 매트릭스

같은 리스크 클래스의 반복 회귀를 막기 위한 고정 매핑이다. 스펙 문단을 바꿀 때
는 대응 코드·테스트를 함께 갱신한다. PR 설명에는 해당 행을 인용한다.

| 스펙 | 코드 | 회귀 테스트 | 차단 대상 |
|---|---|---|---|
| [03-json-schema.md](03-json-schema.md) §예약어 처리 | `src/ante/core/log/safe_logger.py::AnteLogger.makeRecord`, `_record_keys.LOGRECORD_ATTRS`, `formatter._LOGRECORD_BUILTIN` (같은 소스) | `tests/unit/test_log_safe_logger.py`, `tests/unit/test_log_formatter.py::test_reserved_keys_ignored_from_extra` | `extra={"msg": ...}` 류 KeyError, Python 버전별 `taskName` 누락 |
| [03-json-schema.md](03-json-schema.md) §직렬화 규칙 (non-finite float) | `src/ante/core/log/formatter.py::_sanitize_for_json`, `json.dumps(..., allow_nan=False)` | `tests/unit/test_log_formatter.py` NaN/Infinity 케이스 | `NaN`/`Infinity` 토큰이 JSONL 로 누출되어 strict 파서가 깨짐 |
| [04-fingerprint.md](04-fingerprint.md) | `src/ante/core/log/fingerprint.py::compute_fingerprint` | `tests/unit/test_log_fingerprint.py` | 라인번호 의존·설치 경로 의존으로 같은 근본 원인이 다른 키로 기록됨 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) §회전 규칙 (no-rename) | `src/ante/core/log/handlers.py::DateNamedTimedRotatingFileHandler.doRollover` | `tests/unit/test_log_setup.py` 회전 동작 | 자정에 파일이 rename 되어 외부 파일 감시기(감시 에이전트)가 inode 를 잃음 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) §회전 규칙 (Asia/Seoul 자정) | `src/ante/core/log/handlers.py` `_KST = ZoneInfo("Asia/Seoul")`, `computeRollover`, `_make_filename` | `tests/unit/test_log_handlers.py` KST 경계 회귀 | 호스트/컨테이너 TZ (Docker, systemd, launchd) 불일치로 자정 경계가 밀림 |
| [05-handlers-and-rotation.md](05-handlers-and-rotation.md) §볼륨 마운트 | `docker-compose.yml` `ante-logs`, `docker-compose.staging.yml` bind mount | 수동 검증 (`docker compose config`) | 컨테이너 종료 시 로그 유실, staging 감시 에이전트가 파일을 못 읽음 |
| [06-failure-handling.md](06-failure-handling.md) §파일 핸들러 실패 격리 | `src/ante/core/log/setup.py` try/except + stdout 선등록 | `tests/unit/test_log_setup.py` 디스크/권한 실패 케이스 | 파일 핸들러 초기화 실패가 부팅을 차단 |

## 네임스페이스 선택

`src/ante/logging/`이 아닌 `src/ante/core/log/`에 두는 이유:

1. **표준 라이브러리 `logging`과 이름 충돌 회피**: `ante.logging.*` 네임스페이스는 패키지 내에서 `import logging`이 의도와 다르게 해석될 여지를 남긴다. `ante.core.log.*`는 안전하다.
2. **공통 인프라 자산의 물리적 위치**: 스펙은 독립 모듈이지만 구현 코드는 Database·시스템 초기화와 같이 전역에서 호출되는 기반 자산이므로 기존 `core/` 하위에 둔다. 스펙(독립 `docs/specs/logging/`)과 구현 경로(`src/ante/core/log/`)는 일대일 매칭될 필요가 없으며, 독자는 본 문서의 매핑 표로 경로를 확인한다.

# 설계 근거

## 1. 표준 라이브러리 기반

`logging.Handler`·`Formatter` 계약을 그대로 사용하여 외부 의존성(`structlog`, `python-json-logger` 등) 없이 구현한다.

- 현재 30+ 모듈이 이미 `logging.getLogger(__name__)` 패턴으로 통일되어 있어 호출부 수정이 불필요하다.
- JSON 직렬화 로직은 80라인 내외로 직접 작성 가능하다.
- 외부 의존성 최소화는 "얇은 인프라"라는 설계 철학에 부합한다.

## 2. 점진 도입 가능

`ANTE_LOG_JSONL` 게이트로 전역 영향 없이 개별 환경에서 검증 후 확산한다.

- 기존 프로덕션은 미설정 상태로 회귀 위험이 0이다.
- 스테이징에서 먼저 켜서 며칠~몇 주 운용한 뒤 QA·프로덕션으로 확장한다.
- 파일 핸들러의 실패가 stdout 핸들러에 영향을 주지 않는다.

## 3. 관심사 분리

시스템 로그가 이벤트·감사 로그와 완전히 독립된 파이프라인을 갖는다.

- 이벤트 로그(`event_log`)·감사 로그(`audit_log`)는 DB에 있고, 시스템 로그는 파일에 있다.
- 각 종류의 스키마·보관·회전 정책이 서로 영향을 주지 않는다.
- 감시 에이전트는 시스템 로그만 읽으면 되며, DB 접근 권한이 필요 없다.

## 4. Fingerprint 안정성

라인번호 배제·최상위 앱 프레임 선택으로 리팩터링 저항성을 확보한다.

- 같은 근본 원인이 여러 위치에서 기록되어도 동일 키로 묶인다.
- 코드 이동·주석 추가에 영향받지 않는다.
- 감시 에이전트의 dedup이 장기간에 걸쳐 일관되게 동작한다.

## 5. 호출부 변경 최소화

기존 `logger.error(...)` 호출을 수정하지 않는다.

- 중앙 설정(`main.py` 내 `basicConfig` 블록 20줄)만 `setup_logging(config)` 호출로 교체한다.
- 컨텍스트 필드(`extra={}`)는 선택적으로 중요한 경로에만 주입한다.
- 전체 모듈을 수정하는 대규모 커밋을 유발하지 않는다.
