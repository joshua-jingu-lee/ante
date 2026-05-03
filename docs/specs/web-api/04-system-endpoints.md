# Web API 모듈 세부 설계 - 시스템 엔드포인트

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 시스템 (`/api/system`)

> 각 엔드포인트의 요청/응답 스키마, 파라미터 상세, 에러 코드는 Swagger UI(`/docs`)를 참조한다. 아래 표는 전체 엔드포인트 목록과 용도를 요약한다.

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/system/status` | 시스템 상태 (status, version) |
| GET | `/api/system/health` | 헬스체크. 응답 스키마는 아래 [헬스체크 상세](#헬스체크-상세-get-apisystemhealth) 참조 |
| POST | `/api/system/halt` | 시스템 전역 정지. 모든 ACTIVE 계좌를 SUSPENDED로 전환. 파라미터: reason. 응답 shape은 아래 [Kill Switch 응답 SSOT](#kill-switch-응답-ssot-post-apisystemhalt--post-apisystemclear-halt) 참조 |
| POST | `/api/system/clear-halt` | 시스템 전역 정지 해제. 모든 SUSPENDED 계좌를 ACTIVE로 복구한다. 계좌 상태만 복구하며 봇을 자동 재시작하지 않는다. 응답 shape은 아래 [Kill Switch 응답 SSOT](#kill-switch-응답-ssot-post-apisystemhalt--post-apisystemclear-halt) 참조 |

> 단일 계좌 단위 정지/재개는 Account 모듈 엔드포인트(`POST /api/accounts/{id}/suspend` / `POST /api/accounts/{id}/activate`)를 사용한다. `/api/system/halt` / `/api/system/clear-halt`는 전역 편의 명령이며, 단일 계좌 파라미터를 받지 않는다.

## Kill Switch 응답 SSOT (`POST /api/system/halt` / `POST /api/system/clear-halt`)

`POST /api/system/halt`와 `POST /api/system/clear-halt`는 동일한 응답 shape을 사용한다 (HTTP 200, `application/json`).

```json
{
  "status": "halted | halt_cleared",
  "accounts_changed": 2,
  "changed_at": "2026-05-03T05:21:33Z",
  "accounts": [
    {
      "account_id": "domestic",
      "previous_status": "ACTIVE",
      "status": "SUSPENDED",
      "changed": true
    },
    {
      "account_id": "overseas",
      "previous_status": "ACTIVE",
      "status": "SUSPENDED",
      "changed": true
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `status` | string | `halt` 응답은 `"halted"`, `clear-halt` 응답은 `"halt_cleared"` |
| `accounts_changed` | int | 실제로 상태가 전환된 계좌 수 (`changed: true`인 항목 수와 동일) |
| `changed_at` | string (ISO 8601 UTC) | 상태 전환 처리 시각. `Z` suffix를 사용한다 |
| `accounts` | array | 처리 대상 계좌 목록. 각 항목은 아래 표를 따른다 |

`accounts[]` 항목 필드는 정확히 `account_id`, `previous_status`, `status`, `changed` 네 키만 포함한다 (설계 SSOT — `before_status` / `after_status`는 사용하지 않는다).

| 필드 | 타입 | 설명 |
|---|---|---|
| `account_id` | string | 계좌 식별자 |
| `previous_status` | string | 호출 직전 상태 (`ACTIVE` 또는 `SUSPENDED`) |
| `status` | string | 호출 직후 상태 (`ACTIVE` 또는 `SUSPENDED`) |
| `changed` | bool | 실제 전환 여부. 이미 목표 상태였던 계좌(예: `clear-halt` 호출 시 이미 ACTIVE인 계좌)는 `false` |

**의미 규칙**:
- `halt`는 모든 ACTIVE 계좌를 SUSPENDED로 전환한다. DELETED 계좌는 후보에서 제외되며 응답 `accounts[]`에 포함되지 않는다.
- `clear-halt`는 모든 SUSPENDED 계좌를 ACTIVE로 복구한다. DELETED 계좌는 후보에서 제외되며 응답 `accounts[]`에 포함되지 않는다. 계좌 상태만 복구하며 봇 자동 재시작은 수행하지 않는다(BotManager는 `AccountActivatedEvent`를 수신해도 로깅만 수행).
- `accounts[]`에는 처리 대상 후보 계좌(ACTIVE/SUSPENDED)만 포함되며, 상태 변화가 없는 항목(`changed: false` — 이미 목표 상태였던 계좌)도 응답에 노출되어 호출자가 멱등 동작을 검증할 수 있다. DELETED 계좌는 후보 자체에서 제외되므로 `accounts[]`에 등장하지 않는다.

**에러 envelope (4xx / 5xx)**:

4xx/5xx 응답은 기존 `ErrorResponse` (RFC 7807 — `type`, `title`, `detail`, `status`, `instance`)을 사용하며 `Content-Type: application/problem+json`으로 반환한다. 상세는 [07-error-format.md](07-error-format.md), [08-pydantic-schemas.md](08-pydantic-schemas.md)를 참조한다. `request_id`는 현재 `ErrorResponse` SSOT에 포함되지 않으므로 본 엔드포인트도 추가하지 않는다.

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
- 계좌 생성/삭제와 브로커 재초기화성 변경은 cold-path 전용이다. 따라서 `/health`는 서버 시작 시 로드된 계좌 topology만 평가하며, 런타임 `POST /api/accounts` 성공이나 hot-add broker `connect()`를 전제하지 않는다.
