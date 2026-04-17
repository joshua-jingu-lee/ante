# Web API 모듈 세부 설계 - 시스템 엔드포인트

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 시스템 (`/api/system`)

> 각 엔드포인트의 요청/응답 스키마, 파라미터 상세, 에러 코드는 Swagger UI(`/docs`)를 참조한다. 아래 표는 전체 엔드포인트 목록과 용도를 요약한다.

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/system/status` | 시스템 상태 (status, version) |
| GET | `/api/system/health` | 헬스체크. 응답 스키마는 아래 [헬스체크 상세](#헬스체크-상세-get-apisystemhealth) 참조 |
| POST | `/api/system/kill-switch` | 킬 스위치 제어 (halt/activate). 파라미터: action, reason, account_id? (생략 시 전체 계좌) |

## 헬스체크 상세 (`GET /api/system/health`)

시스템 및 핵심 의존성의 현재 상태를 반환한다. 모니터링 도구(Docker `HEALTHCHECK`, 로드밸런서, 감시 에이전트 등)가 트래픽 수용 가능 여부를 판단하는 근거로 사용한다.

**요청**: 파라미터 없음.

**응답 스키마** (`HealthResponse`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `ok` | bool | 모든 의존성 체크 통과 여부. `all(checks.values())`로 계산 |
| `checks` | object (string → bool) | 개별 의존성 체크 결과. 키는 의존성 이름, 값은 통과 여부 |

**`checks` 항목 (1.0 기준)**:

| 키 | 통과 조건 | 체크 방법 |
|---|---|---|
| `db` | SQLite에 접근 가능 | `Database.fetch_one("SELECT 1")` 성공 |
| `broker` | 모든 계좌의 BrokerAdapter가 연결됨 | 계좌별 `broker.is_connected == True`의 AND 축약. 계좌가 0개이면 `True` |

**응답 예시**:

정상:
```json
{"ok": true, "checks": {"db": true, "broker": true}}
```

부분 실패 (브로커 끊김):
```json
{"ok": false, "checks": {"db": true, "broker": false}}
```

**설계 원칙**:
- 각 체크는 **독립적**이며 어느 하나의 실패가 다른 체크에 영향을 주지 않는다. 체크 중 발생한 예외는 내부에서 포착하고 해당 항목만 `false`로 기록한다. 엔드포인트 자체가 500을 반환하지 않는다.
- HTTP 상태 코드는 체크 결과와 무관하게 **항상 200**이다. 모니터링 도구는 `ok` 필드로 판정한다.
- 1.0 범위의 `checks`는 `db`, `broker`로 제한한다. `stream`, `treasury` 등은 운용 중 필요성이 실증되면 후속 이슈에서 확장한다 (YAGNI).
- 계좌 0개 상태에서 `broker=true`인 이유: 초기 설정 단계나 계좌가 일시적으로 비어있는 상태를 "브로커 불가"로 판정하지 않기 위함이다.
- `checks` 키 집합 확장은 기존 응답과 하위 호환이다 (소비자는 존재하는 키만 확인).
