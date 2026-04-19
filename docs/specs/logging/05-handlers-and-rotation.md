# Logging 세부 설계 - 핸들러 구성과 회전 정책

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# 핸들러 구성과 회전 정책

## 핸들러 구성

| 항목 | 값 | 근거 |
|---|---|---|
| stdout 핸들러 | `logging.StreamHandler(sys.stdout)` | 콘솔 출력, Docker `docker logs`로 수집 |
| stdout 레벨 | `system.log_level` (기본 INFO) | [config/03-design-decisions.md](../config/03-design-decisions.md) §1 |
| stdout 포맷 | `%(asctime)s [%(levelname)s] %(name)s: %(message)s` | 기존 포맷 유지 — 사람 관찰용 |
| 파일 핸들러 | `logging.handlers.TimedRotatingFileHandler` | 일일 회전 |
| 파일 레벨 | `system.log_level` (동일) | 두 핸들러가 같은 레코드를 본다 |
| 파일 포맷 | `JsonFormatter` | [03-json-schema.md](03-json-schema.md) 참조 |
| 활성화 게이트 | `ANTE_LOG_JSONL=1` | 미설정 시 파일 핸들러 미생성 |

## 파일 경로와 회전

| 항목 | 값 |
|---|---|
| 파일명 | `logs/ante-YYYY-MM-DD.jsonl` (활성 파일명 자체가 날짜를 포함) |
| 회전 시점 | `when="midnight", utc=False` (Asia/Seoul 자정 기준) |
| 회전 방식 | 활성 파일은 날짜를 포함하므로 rename 불필요. 자정에 새 날짜로 `baseFilename` 을 교체하고 새 파일을 연다 |
| 보관 | 30일 (`backupCount=30`). 초과분은 가장 오래된 파일부터 삭제 |
| 디렉토리 | 컨테이너 `/app/logs` (named volume 또는 bind mount) |
| 퍼미션 | 0644 (기본) |

## 회전 동작 세부

1. 자정이 지나면 기존 `ante-2026-04-17.jsonl` 은 그대로 두고 (활성 파일명에 이미 날짜가 포함됨), 새 `ante-2026-04-18.jsonl` 을 연다. 이전 날 파일은 마지막 엔트리가 기록된 상태로 남아 감시 에이전트가 안전하게 수집할 수 있다.
2. `backupCount=30` 을 초과한 가장 오래된 파일부터 삭제된다 (예: 31일째 자정 회전 시 `ante-2026-03-18.jsonl` 이 제거됨).
3. 압축은 수행하지 않는다. 디스크 압박이 실측되면 후속 반복에서 `TimedRotatingFileHandler.rotator` 후킹으로 도입한다. 자세한 판단 이력은 [08-open-issues.md](08-open-issues.md) §스코프 제외 참조.

## 실패 처리

- **파일 핸들러 실패(디스크 가득, 권한 문제 등)**: 예외를 로깅 시스템 내부에서 무시하고 stdout 핸들러만 유지한다. `logging.Handler.handleError`의 기본 동작을 따른다.
- **stdout 핸들러 실패**: 드물지만 발생 시 프로세스 경고 출력 후 계속 진행한다.
- **둘 다 실패**: 로그가 유실되나 애플리케이션 종료를 유발하지 않는다. 로깅 실패는 비즈니스 로직에 영향을 주지 않는다.

## 동시성

`TimedRotatingFileHandler`는 멀티스레드/멀티프로세스 환경에서 회전 시점에 경합이 발생할 수 있다. 본 스펙은 **단일 프로세스**를 가정한다. 멀티 워커 구성이 필요해지면 별도 반복에서 `ConcurrentRotatingFileHandler` 또는 파일 분리 전략을 도입한다.

## 볼륨 마운트

| 환경 | 마운트 방식 | 경로 |
|---|---|---|
| Production | Docker named volume `ante_logs` → `/app/logs` | 재시작 시 보존 |
| Staging | bind mount `~/Projects/ante/logs` → `/app/logs` | 맥미니 파일시스템 직접 노출, 감시 에이전트 접근 용이 |
| QA | 마운트 불필요 | TC 실행 중 휘발, 자동 삭제 |
| 로컬 개발 | bind mount 또는 마운트 생략 | 개발자 선택 |

Staging이 bind mount인 이유: 감시 에이전트가 Docker 컨테이너 외부(맥미니 호스트)에서 직접 JSONL 파일을 읽어야 하기 때문이다.
