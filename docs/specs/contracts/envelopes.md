# CLI/IPC Envelope Shape SSOT

> Parent decision: [#1820 Contract SSOT 공통 인프라](https://github.com/joshua-jingu-lee/ante/issues/1820)
> Status: 1.0 normative — CLI와 IPC 외부 표면이 공유하는 envelope 형태의 단일 SSOT.
> Implementation references (non-normative): `src/ante/cli/formatter.py`, `src/ante/ipc/server.py`.

## 목적

본 문서는 Ante의 외부 표면(CLI `--format json`, IPC Unix domain socket)이
사용자/Agent에 노출하는 envelope 형태를 한 곳에 모은다. 기존 CLI/IPC 스펙과
구현이 이미 같은 4형태를 사용하고 있으므로, 본 문서는 새 계약을 발명하지 않고
기존 4형태를 상위 SSOT로 lock 한다.

후속 에픽(#1815/#1816/#1819/#1818)과 도메인 스펙은 envelope 형태를 별도로
재정의하지 않고 본 문서를 reference 한다.

## Envelope 4형태

Ante의 외부 표면 envelope은 다음 4형태만이 normative다.

```json
{"status": "ok",    "message": "...",  "data":   {...}}
{"status": "error", "code":    "...",  "message": "..."}
{"id": "uuid-v4",   "status":  "ok",   "result": {...}}
{"id": "uuid-v4",   "status":  "error","error":  {"code": "...", "message": "..."}}
```

순서대로 CLI success / CLI error / IPC success / IPC error 다.

## CLI success envelope

CLI 커맨드가 `--format json` 모드에서 성공한 경우 `stdout`으로 출력하는 형태다.

```json
{
  "status": "ok",
  "message": "<사람이 읽는 단문 메시지>",
  "data": { ... }
}
```

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `status` | `"ok"` | 필수 | 성공 응답 식별자. 항상 문자열 `"ok"`. |
| `message` | `string` | 필수 | 사람이 읽는 단문 결과 메시지. 빈 문자열도 허용한다. |
| `data` | `object` | 필수 | 커맨드별 payload. 페이로드가 없으면 빈 객체 `{}`를 직렬화한다. |

규칙:

- 세 필드는 항상 동시에 직렬화된다. `data`가 누락된 envelope은 본 SSOT를
  따르지 않는다. payload 없는 경우 `{}`로 명시한다.
- `data` 안의 키/값은 도메인별 페이로드 계약이며 본 SSOT 범위 밖이다.
- `--format text` 모드의 사람 친화 출력은 본 SSOT 범위가 아니다.
- 구현 reference: `OutputFormatter.success()` (`src/ante/cli/formatter.py`).

## CLI error envelope

CLI 커맨드가 `--format json` 모드에서 실패한 경우 출력하는 형태다.

```json
{
  "status": "error",
  "code":   "<STABLE_ERROR_CODE>",
  "message": "<사람이 읽는 에러 메시지>"
}
```

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `status` | `"error"` | 필수 | 에러 응답 식별자. 항상 문자열 `"error"`. |
| `code` | `string` | 필수 | 안정 에러 코드. 빈 문자열 `""`은 본 1.0 계약에서 허용되는 fallback(아직 typed code가 부여되지 않은 surface). |
| `message` | `string` | 필수 | 사람이 읽는 에러 메시지. 안내 문구는 도메인 스펙이 정한다. |

규칙:

- 세 필드는 항상 동시에 직렬화된다.
- exit code는 1 이상(non-zero)이어야 한다. exit 0 + error envelope는 본 SSOT 위반이다.
- `--format text` 모드는 `Error: <message>`를 `stderr`로 출력한다. JSON 모드는
  `stdout`으로 envelope 한 줄을 출력한다.
- `code` 값의 vocabulary(taxonomy, 도메인 prefix 등)는 본 SSOT 범위가 아니다 →
  [Non-Goals](#non-goals) 참조.
- 구현 reference: `OutputFormatter.error()` (`src/ante/cli/formatter.py`).

## IPC success envelope

IPC 서버가 요청을 성공적으로 처리한 경우 응답으로 직렬화하는 형태다.

```json
{
  "id": "uuid-v4",
  "status": "ok",
  "result": { ... }
}
```

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `id` | `string` | 필수 | 요청의 `id`와 1:1 매칭되는 식별자. 클라이언트가 응답을 요청과 짝짓는 데 사용한다. |
| `status` | `"ok"` | 필수 | 성공 응답 식별자. 항상 문자열 `"ok"`. |
| `result` | `object` | 필수 | 핸들러가 반환한 payload. payload 없으면 빈 객체 `{}`를 직렬화한다. |

규칙:

- 세 필드는 항상 동시에 직렬화된다.
- `result` 안의 키/값은 IPC 커맨드별 payload 계약이며 본 SSOT 범위 밖이다.
  도메인별 envelope 예시(예: `{"bot": ...}`, `{"suspended_count": N}`)는
  `result` payload의 일부이지 별도 envelope 형태가 아니다.
- 구현 reference: `IPCServer._dispatch()` 성공 분기 (`src/ante/ipc/server.py`).

## IPC error envelope

IPC 서버가 요청 처리 중 실패한 경우 응답으로 직렬화하는 형태다.

```json
{
  "id": "uuid-v4",
  "status": "error",
  "error": {
    "code":    "<STABLE_ERROR_CODE>",
    "message": "<사람이 읽는 에러 메시지>"
  }
}
```

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `id` | `string`\|`null` | 필수 | 요청의 `id`와 1:1 매칭. 요청 디코드 실패 등으로 `id`를 식별할 수 없는 경우 `null`을 직렬화한다. |
| `status` | `"error"` | 필수 | 에러 응답 식별자. 항상 문자열 `"error"`. |
| `error` | `object` | 필수 | `code`/`message` 두 필드를 갖는 중첩 객체. |
| `error.code` | `string` | 필수 | 안정 에러 코드(예: `BOT_NOT_FOUND`, `SERVICE_UNAVAILABLE`, `UNKNOWN_COMMAND`, `EXECUTION_ERROR`). |
| `error.message` | `string` | 필수 | 사람이 읽는 에러 메시지. |

규칙:

- 네 필드(`id`, `status`, `error.code`, `error.message`)는 항상 동시에 직렬화된다.
- `error`는 평탄화하지 않고 항상 중첩 객체로 직렬화한다. CLI error envelope과
  다른 점이다(아래 [Wrapping 경계](#wrapping-경계) 참조).
- 1.0에서 IPC error에 추가 메타데이터(`details`, `retryable` 등) 필드를 두지
  않는다. 도입은 #1819의 책임이며 본 SSOT 범위 밖이다 → [Non-Goals](#non-goals).
- 구현 reference: `IPCServer._dispatch()` 에러 분기와 `_service_unavailable()`
  (`src/ante/ipc/server.py`).

## Wrapping 경계

CLI envelope과 IPC envelope은 **표면별 1회만** wrapping 된다. 한 응답을 두 형태로
이중 wrapping 하지 않는다.

- **오프라인 CLI**: 직접 모듈 임포트로 실행되는 명령은 결과 dict을
  `OutputFormatter`로 한 번 wrapping 해 CLI envelope으로 출력한다.
- **IPC passthrough CLI**: 런타임 IPC 위임 명령은 IPC 응답의 `result`(또는
  `error`)를 그대로 사용해 CLI envelope을 1회 구성한다. IPC `result`를 다시
  IPC envelope으로 재감싸서 CLI에 넘기지 않는다.
- **CLI IPC 헬퍼 계약**: `src/ante/cli/commands/ipc_helpers.py`의 `ipc_send`는
  IPC 성공 응답의 `result`만 caller에 반환하고, IPC 에러 응답은
  `ClickException`에 안정 코드/메시지를 부착해 raise 한다. CLI leaf는 이를
  받아 `OutputFormatter.success(...)` 또는 `OutputFormatter.error(code, message)`로
  CLI envelope 1회 wrapping 한다. 이 동형은 `ante bot start/stop/status`의 IPC
  passthrough reference 패턴이다 (`src/ante/cli/commands/bot.py`).
- **결론**: 어느 표면이든 사용자/Agent에게 보이는 envelope은 CLI envelope 4형태
  중 하나(텍스트/JSON), IPC envelope 4형태 중 하나(서버 응답)다. CLI가 IPC
  envelope 그대로를 출력하거나, IPC가 CLI envelope을 반환하는 시나리오는 본
  SSOT가 정의하는 envelope 형태가 아니다.

## 도메인 payload 예시와의 관계

기존 CLI/IPC 도메인 스펙은 도메인 payload 예시를 풍부히 기록한다. 대표적으로:

- IPC `bot.status` → `{"bot": <BotDetail>}` payload (IPC envelope의 `result`)
- IPC `system.halt` → `{"suspended_count": N}` payload (IPC envelope의 `result`)
- CLI `bot list` → `{"bots": [...]}` payload (CLI envelope의 `data`)

위 `{...}` payload들은 본 SSOT가 정의하는 envelope이 **아니다**. envelope 4형태
**안쪽** 페이로드 슬롯(`data`/`result`)의 도메인 계약이다. payload schema의
계약 SSOT는 각 도메인 스펙(`docs/specs/<module>/...`)이며 본 SSOT 범위 밖이다.

## Non-Goals

본 SSOT가 정의하지 **않는** 항목은 다음과 같다.

- **에러 코드 taxonomy**: `code` 값의 도메인 prefix 규칙, 공통 코드 SSOT,
  exception → code 매핑은 #1816의 책임이다. CLI 일부 분야는
  `docs/specs/cli/02-design-decisions.md`의 입력 계약 에러 코드 표를 SSOT로
  유지한다.
- **CLI success payload migration**: 기존 raw-dict CLI 출력 명령을 standard
  CLI success envelope으로 옮기는 작업은 #1815의 책임이다. 본 SSOT는 standard
  envelope이 `{status, message, data}` 임만 lock 한다.
- **IPC CommandSpec metadata**: IPC 핸들러의 args/result schema, audit
  metadata, service 의존성 선언은 #1819의 책임이다. 본 SSOT는 IPC
  `result`/`error` 슬롯의 외형만 lock 한다.
- **도메인 payload schema**: `data`/`result` 안의 도메인별 필드 계약(예:
  `bot info`의 필드 목록)은 각 도메인 스펙이 SSOT다.
- **Envelope builder helper 도입 강제**: `build_cli_success(...)` /
  `build_ipc_error(...)` 같은 코드 helper의 도입은 본 SSOT가 강제하지 않는다.
  현재 `OutputFormatter`와 `IPCServer._dispatch()`가 envelope을 직접 직렬화하는
  방식이 normative behavior다. helper 도입이 필요하면 별도 이슈로 다룬다.
- **기존 formatter/server behavior 변경**: 본 SSOT는 문서화 변경만이며
  `OutputFormatter`/`IPCServer`의 런타임 동작을 바꾸지 않는다.
- **CLI `--format text` 출력 형태**: 사람 친화 텍스트 출력은 본 SSOT 범위 밖이다.
- **`docs/specs/contracts/README.md` 인덱스 작성**: contracts 디렉토리의 SSOT
  인덱스 작성은 #1824의 책임이다. 본 PR은 `docs/specs/README.md`에 contracts
  entry만 추가한다.

## 호출자/소비자 reference

본 envelope SSOT는 다음 표면이 직접 소비한다.

- **CLI 호출자**: 모든 `OutputFormatter.success/error` 호출자(현재 ante CLI
  명령 전반). 호출자별 payload 계약은 도메인 스펙을 따른다.
- **IPC 호출자**: `IPCClient.send()`를 통해 IPC 서버 응답을 받는 모든 CLI 명령
  및 향후 MCP/외부 클라이언트. `src/ante/cli/commands/ipc_helpers.py`의
  `ipc_send`가 1차 IPC envelope 디코더 reference다.
- **IPC 서버**: `IPCServer._dispatch()`가 본 envelope 4형태 중 IPC 2형태를
  직렬화하는 단일 chokepoint다. 핸들러는 평면 dict을 반환하며 envelope wrapping은
  `_dispatch()`가 일임한다.

## 변경 정책

- 본 SSOT는 1.0 normative이며 형태 변경은 contract change다. 새 필드 추가
  (예: `request_id`, `details`, `retryable`)는 본 문서 normative 절을 수정하지
  말고 **별도 SSOT 이슈**로 제안한 뒤 본 문서를 갱신한다.
- 도메인 payload 신설/변경은 본 SSOT를 건드리지 않는다. 해당 도메인 스펙에서
  처리한다.
- 본 문서가 lock 한 envelope 4형태와 충돌하는 normative 재정의가 다른 스펙에서
  발견되면 해당 스펙을 본 SSOT를 reference 하도록 정렬한다.
