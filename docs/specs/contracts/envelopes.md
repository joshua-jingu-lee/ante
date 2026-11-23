# CLI/IPC Envelope Shape SSOT

> Parent decision: [#1820 Contract SSOT 공통 인프라](https://github.com/joshua-jingu-lee/ante/issues/1820)
> Status: 1.0 normative — CLI와 IPC 외부 표면이 공유하는 envelope 형태의 단일 SSOT.
> Implementation references (non-normative): `src/ante/cli/formatter.py`, `src/ante/cli/middleware.py`, `src/ante/contracts/cli_registry.py`, `src/ante/ipc/server.py`.

## 목적

본 문서는 Ante의 외부 표면(CLI `--format json`, IPC Unix domain socket)이
사용자/Agent에 노출하는 envelope 형태를 한 곳에 모은다. CLI 명령의 JSON 성공
출력이 CLI success envelope인지는 그 명령의 CLI 계약이 정한다
([CLI 성공 출력과 계약](#cli-성공-출력과-계약)).

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

CLI 계약의 `envelope`이 `standard`인 커맨드가 `--format json` 모드에서 성공한 경우
`stdout`으로 출력하는 형태다.

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

## CLI 성공 출력과 계약

- CLI 명령의 `--format json` 성공 출력 형태는 CLI 계약
  (`src/ante/contracts/cli_registry.py`)의 `OutputContract.envelope`이 정한다. 값은
  `standard`와 `raw_legacy` 둘이고(`EnvelopeForm`), 명령별 값의 정본은 계약이다.
- 계약의 `envelope`이 `standard`인 명령의 성공 출력은 CLI success envelope이다. 명령이
  결과 값(`CommandResult`)을 돌려주면 진입점 훅이 그 값으로 envelope을 한 번
  직렬화한다. 결과 값의 `text`(text 모드의 줄)는 줄의 tuple이거나 그것을 돌려주는
  callable이며, envelope은 `text`를 쓰지 않고 callable은 text 모드에서만 불린다. 결과 값을 돌려주는데 계약이 없거나 `envelope`이 `standard`가 아니면 훅은
  envelope을 내지 않고 `TypeError`를 낸다.
- `data` 배치: 결과 값의 payload가 객체면 그대로 `data`다. 배열이면
  `{<계약의 data_key>: 배열}`이다. 계약의 `data_key`가 없는데 payload가 배열이면 훅은
  envelope을 내지 않고 `TypeError`를 낸다. `data_key`의 이름은 배열의 행이 나타내는
  자원의 복수형 snake_case 명사다(예: 결재 요청 행의 배열은 `approvals`).
- 계약의 `envelope`이 `raw_legacy`인 명령의 성공 출력은 CLI success envelope이 아니다.
  명령이 직접 만든 payload(평면 객체나 배열 등)가 그대로 나가며, 본 SSOT의 4형태 밖이다.
  `raw_legacy`는 계약에서 사라져 가는 값이다. 새 계약은 이 값을 쓰지 않으며,
  `raw_legacy_contracts` 래칫(`scripts/check_entry_ratchet.py`)이 이 값을 가진 계약
  집합이 기준선보다 늘어나는 것을 막는다.
- 계약의 `envelope`을 `raw_legacy`에서 `standard`로 바꾸는 명령은 payload의 키와 값을
  바꾸지 않는다. 옛 payload가 객체면 그대로 `data`에 들어가고 `message`는 빈 문자열이며,
  payload 안의 `message` 키는 `data`에 남는다. 옛 payload가 배열이면 계약에 `data_key`를
  채운다.
- 이 전환의 버전 정책은 [D-021](../../decisions/D-021-trust-pyramid-governance.md)을
  따른다.

## CLI error envelope

CLI 커맨드가 `--format json` 모드에서 실패한 경우 출력하는 형태다.

```json
{
  "status": "error",
  "code":   "<STABLE_ERROR_CODE>",
  "message": "<사람이 읽는 에러 메시지>",
  "details": {"stage": "load"}
}
```

`details`는 선택 키다(상세가 있는 에러만 — 예시는 `strategy submit`의 로드 실패).

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `status` | `"error"` | 필수 | 에러 응답 식별자. 항상 문자열 `"error"`. |
| `code` | `string` | 필수 | 안정 에러 코드. 빈 문자열 `""`은 본 1.0 계약에서 허용되는 fallback(아직 typed code가 부여되지 않은 surface). |
| `message` | `string` | 필수 | 사람이 읽는 에러 메시지. 안내 문구는 도메인 스펙이 정한다. |
| `details` | `object` | 선택 | 상세가 있는 에러만 싣는다. 키는 아래 표의 코드마다 정해져 있다. |

규칙:

- `status`·`code`·`message`는 항상 동시에 직렬화되고, `details`는 상세가 있을 때만
  네 번째 키로 더한다(`null`로 직렬화하지 않는다). `details`를 연 근거는 [#2762](https://github.com/joshua-jingu-lee/ante/issues/2762)(유지관리자 결정)다.
- exit code는 1 이상(non-zero)이어야 한다. exit 0 + error envelope는 본 SSOT 위반이다.
- `--format text` 모드는 `Error: <code>: <message>`를 `stderr`로 출력한다. 메시지가
  이미 `<code>: `로 시작하면 접두를 다시 붙이지 않는다. Click 자신의 사용법 오류는
  Click 기본 형식을 따른다. 상세가 있는 에러는 오류 줄 뒤에 상세 줄이 `stderr`로
  이어진다. JSON 모드는 `stdout`으로 envelope 한 줄을 출력한다.
- `details`에도 `message`의 redaction 규칙(민감정보 금지,
  [error-taxonomy.md](error-taxonomy.md#redaction-정책-normative))이 적용된다.
- 지금 `details`를 싣는 출구(IPC error envelope에는 `details`가 없다):

  | 명령 | `code` | `details` |
  |------|--------|-----------|
  | `strategy validate`의 검증 실패 | `STRATEGY_VALIDATION_FAILED` | `{errors, warnings}` |
  | `strategy submit`의 검증 실패 | `STRATEGY_VALIDATION_ERROR` | `{stage: "validate", errors}` |
  | `strategy submit`의 `StrategyError` 계열 로드·meta·등록 실패 | 그 예외의 코드 | `{stage}` (`load`·`meta_validation`·`register`) |
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

- **오프라인 CLI**: 직접 모듈 임포트로 실행되는 명령 가운데 계약의 `envelope`이
  `standard`인 명령은 결과를 한 번 wrapping 해 CLI success envelope으로 출력한다.
- **IPC passthrough CLI**: 런타임 IPC 위임 명령 가운데 계약의 `envelope`이 `standard`인
  명령은 IPC `result`를 다시 IPC envelope으로 감싸지 않고 CLI success envelope을 1회
  구성한다.
- **CLI IPC 헬퍼 계약**: `src/ante/cli/commands/ipc_helpers.py`의 `ipc_send`는
  IPC 성공 응답의 `result`만 호출자에 돌려주고, 실패는 타입 예외로 올린다:
  `IPCServerNotRunningError`·`IPCClientTimeoutError`, 그리고 서버의
  `error.code`/`error.message`를 그대로 가진 `IPCRemoteError`(없으면 `UNKNOWN`/
  `알 수 없는 오류`). CLI leaf는 이 예외를 잡지 않고, 진입점 훅이 CLI error
  envelope을 1회 만든다(text 모드는 `Error: <code>: <message>` 한 줄). 다만 서버
  미기동에서 직접 실행으로 넘어가는 명령은 `IPCServerNotRunningError`만 잡고,
  `bot signal-key`(조회)는 코드가 `BOT_NOT_FOUND`인 `IPCRemoteError`만 잡으며,
  `rule update`·`strategy set-status`는 포괄 `except` 앞에서 셋을 그대로 다시 올린다.
- **streaming 핸드셰이크 passthrough(`signal connect`)**: `signal connect`의 핸드셰이크
  단계는 데몬이 생성한 IPC error envelope의 `error.code`/`error.message`를 CLI error
  envelope으로 **1회만** 옮긴다. 이때 JSON 모드의 `message`는 **verbatim
  passthrough**한다 — CLI가 번역·재작성하지 않는다. 다만 데몬이 빈 `message`를
  내면 `<code>: `가 되고 SCREAMING_SNAKE가 아닌 `code`는 `EXECUTION_ERROR`가 된다(지금
  데몬이 내는 코드·메시지에서는 일어나지 않는다). 데몬이 낸 거부는
  `IPCRemoteError`로, 연결 실패(소켓 없음·연결 거부·응답 끊김·시간 초과)는 위 헬퍼와
  같은 `IPCServerNotRunningError`·`IPCClientTimeoutError`로 진입점 훅에 올린다.
  따라서 JSON 모드의 데몬 핸드셰이크 검증 에러는 `{status:error, code, message}`
  형태로 #1705 회귀 lock과 byte-identical하게 유지되고, text 모드는 위 text 규칙대로
  `stderr`에 `Error: <code>: <message>` 한 줄을 낸다(#2762). 이는 위 **CLI IPC 헬퍼
  계약**의 동형(streaming 표면) 적용이며, `code` vocabulary와 streaming 프로토콜
  자체는 본 SSOT 범위 밖이다(각각 `docs/specs/contracts/error-taxonomy.md`,
  `docs/specs/ipc/ipc.md`). 계약 정의는
  [#2334](https://github.com/joshua-jingu-lee/ante/issues/2334)이며 **구현 PR 머지
  후 동작**한다(동기 버그 #2333 unblock; spec 단계에서는 미동작).
- **결론**: 어느 표면이든 사용자/Agent에게 보이는 envelope은 CLI envelope 2형태
  중 하나(JSON. 계약이 `raw_legacy`인 명령의 성공 출력은 envelope이 아니다), IPC
  envelope 2형태 중 하나(서버 응답)다. CLI가 IPC
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
- **명령군별 전환**: 계약이 `raw_legacy`인 명령을 `standard`로 옮기는 일은 명령군마다
  별도 이슈로 한다. 본 SSOT는 그 전환의 규칙만 정한다
  ([CLI 성공 출력과 계약](#cli-성공-출력과-계약)).
- **IPC CommandSpec metadata**: IPC 핸들러의 args/result schema, audit
  metadata, service 의존성 선언은 #1819의 책임이다. 본 SSOT는 IPC
  `result`/`error` 슬롯의 외형만 lock 한다.
- **도메인 payload schema**: `data`/`result` 안의 도메인별 필드 계약(예:
  `bot info`의 필드 목록)은 각 도메인 스펙이 SSOT다.
- **직렬화 코드의 모양**: CLI success envelope은 `OutputFormatter.success()`가
  직렬화하고(진입점 훅도 이 함수를 부른다), IPC envelope은 `IPCServer._dispatch()`가
  직렬화한다. 본 SSOT는 형태만 정하고 직렬화하는 코드의 모양은 정하지 않는다.
- **CLI `--format text` 출력 형태**: 사람 친화 텍스트 출력은 본 SSOT 범위 밖이다.
- **`docs/specs/contracts/README.md` 인덱스 작성**: contracts 디렉토리의 SSOT
  인덱스 작성은 #1824의 책임이다. 본 PR은 `docs/specs/README.md`에 contracts
  entry만 추가한다.

## 호출자/소비자 reference

본 envelope SSOT는 다음 표면이 직접 소비한다.

- **CLI 호출자**: `OutputFormatter.success/error` 호출자 — CLI 진입점 훅
  (`src/ante/cli/middleware.py`)과 그 함수를 직접 부르는 명령. 호출자별 payload
  계약은 도메인 스펙을 따른다.
- **IPC 호출자**: `IPCClient.send()`를 통해 IPC 서버 응답을 받는 모든 CLI 명령
  및 향후 MCP/외부 클라이언트. `src/ante/cli/commands/ipc_helpers.py`의
  `ipc_send`가 1차 IPC envelope 디코더 reference다.
- **IPC 서버**: `IPCServer._dispatch()`가 본 envelope 4형태 중 IPC 2형태를
  직렬화하는 단일 chokepoint다. 핸들러는 평면 dict을 반환하며 envelope wrapping은
  `_dispatch()`가 일임한다.

## 변경 정책

- 본 SSOT는 1.0 normative이며 형태 변경은 contract change다. 새 필드 추가
  (예: `request_id`, `retryable`)는 본 문서 normative 절을 수정하지
  말고 **별도 SSOT 이슈**로 제안한 뒤 본 문서를 갱신한다. CLI error envelope의
  `details`는 [#2762](https://github.com/joshua-jingu-lee/ante/issues/2762)로 열었다.
- 도메인 payload 신설/변경은 본 SSOT를 건드리지 않는다. 해당 도메인 스펙에서
  처리한다.
- 본 문서가 lock 한 envelope 4형태와 충돌하는 normative 재정의가 다른 스펙에서
  발견되면 해당 스펙을 본 SSOT를 reference 하도록 정렬한다.
