# Contracts SSOT 인덱스

> Parent decision: [#1820 Contract SSOT 공통 인프라](https://github.com/joshua-jingu-lee/ante/issues/1820)
> Status: 1.0 normative index — CLI/IPC 외부 표면 계약을 정렬하는 공통 SSOT의 단일 진입점.
> Scope: 본 인덱스는 vocabulary / envelope / drift helper / migration order를 한 곳에서
> 인덱싱한다. 후속 에픽(#1815/#1816/#1818/#1819)이 같은 단어와 같은 helper를 반복
> 정의하지 않도록 한다.

## 목적

`docs/specs/contracts/`는 Ante 외부 표면(CLI `--format json`, IPC Unix domain
socket)이 사용자/Agent에게 노출하는 **wire-level 계약의 SSOT**를 모은다.

- 본 인덱스는 4개의 SSOT 산출물(envelope shape, vocabulary code module, drift
  helper skeleton, migration domain order)을 한 곳에서 가리키고, 4 후속 에픽이
  같은 SSOT를 참조하는지 cross-check 결과를 기록한다.
- 본 인덱스는 SSOT 본문을 재정의하지 않는다. 본문은 각 산출물 문서/모듈을
  따른다.
- 본 인덱스는 후속 에픽(#1815/#1816/#1818/#1819)의 normative 책임(actual
  registry/taxonomy/factory/metadata 구현)을 정의하지 않는다. 그 책임은 각
  에픽의 본문에 있다.

## SSOT 산출물 인덱스

| 축 | SSOT 위치 | 소유 이슈 | 비고 |
|---|---|---|---|
| Envelope shape | [docs/specs/contracts/envelopes.md](envelopes.md) | #1821 | CLI success/error, IPC success/error 4형태 lock |
| Vocabulary code | [src/ante/contracts/vocab.py](../../../src/ante/contracts/vocab.py) | #1822 | `ContractKind`, `EnvelopeForm`, `AuthMode` Literal SSOT |
| Drift helper skeleton | [tests/unit/contracts/helpers.py](../../../tests/unit/contracts/helpers.py) | #1823 | Click/IPC iterator, `*Error` class / `fmt.error` callsite helper |
| Error taxonomy | [docs/specs/contracts/error-taxonomy.md](error-taxonomy.md) | #1816 / #1839 | `code` vocabulary + 8 category + auth legacy alias + 대표 fault lock |
| Offline service factory contract | [docs/specs/contracts/offline-factory.md](offline-factory.md) | #1818 / #1854 | CLI `offline`/`cold-path` factory 책임·비책임 + `read_only` skip 정책 + ctx path resolution + read-only 예외 |
| Migration domain order | 본 문서 [Migration Domain Order](#migration-domain-order) | #1820 | `account → member → approval → bot → treasury → broker → strategy → 기타` |

### Envelope shape (#1821)

[`docs/specs/contracts/envelopes.md`](envelopes.md)가 CLI/IPC envelope 4형태의
단일 SSOT다. 본 인덱스는 그 본문을 재정의하지 않는다. 후속 에픽이 새 envelope
shape을 추가하거나 기존 4형태를 변경하려면 envelopes.md 자체를 갱신한다.

핵심 lock:

- CLI success: `{status:"ok", message, data}`
- CLI error: `{status:"error", code, message}`
- IPC success: `{id, status:"ok", result}`
- IPC error: `{id, status:"error", error:{code, message}}`

### Vocabulary code (#1822)

[`src/ante/contracts/vocab.py`](../../../src/ante/contracts/vocab.py)가 3개
Literal type alias의 단일 코드 SSOT다.

- `ContractKind = Literal["entity", "operation", "collection", "raw", "stream"]`
- `EnvelopeForm = Literal["standard", "raw_legacy"]`
- `AuthMode = Literal["public", "authenticated", "scoped", "master"]`

본 모듈은 runtime behavior를 가지지 않고 Literal type alias만 export한다.
enum/dataclass/helper/validator는 의도적으로 제외되어 있다 — 후속 에픽이
필요해지면 별도 이슈로 분리한다.

#### `raw_legacy` 표현

`raw_legacy`는 `ContractKind`가 **아니다**. `raw_legacy`는 `EnvelopeForm`에만
존재한다. 기존 raw JSON 출력 예외는 다음처럼 표현한다.

```python
OutputContract(kind="raw", envelope="raw_legacy")
```

즉, `kind`(result shape 종류) 축과 `envelope`(응답 envelope 형태) 축은 독립이며,
legacy raw JSON 출력은 `ContractKind="raw"` + `EnvelopeForm="raw_legacy"`
조합이다. 본 정렬은 #1820/#1822에서 결정되었고 후속 #1815가 reference한다.

### Drift helper skeleton (#1823)

[`tests/unit/contracts/helpers.py`](../../../tests/unit/contracts/helpers.py)가
4 후속 에픽이 반복해서 작성할 drift-test 유틸의 공통 skeleton이다. 본 SSOT는
helper API skeleton만 제공하고 실제 drift policy/assertion은 각 후속 에픽의
책임이다.

Helper 분류:

- **import 기반** — Click root group, IPC `CommandRegistry`는 module import만으로
  leaf 식별이 가능하므로 introspection으로 다룬다.
  - `iter_click_leaf_commands(root=None)` — Click root group의 public leaf
    command를 yield. hidden subtree는 제외한다. 기본 root는 `ante.cli.main.cli`.
  - `iter_ipc_command_specs(registry=None)` — `CommandRegistry`에서 등록된
    `CommandSpec`을 yield. registry 미지정 시 새 빈 registry에
    `register_all_handlers`를 적용한 default를 사용한다.
- **AST/텍스트 기반** — exception class와 `fmt.error(...)` callsite sweep은
  import side effect를 피하기 위해 file text를 `ast.parse`한다.
  - `iter_exception_classes(root=Path("src/ante"))` — `*Error` class와 class-level
    `code` 속성을 식별한다.
  - `iter_fmt_error_calls(root=Path("src/ante/cli"))` — `fmt.error(...)`
    callsite와 code argument classification 정보를 yield한다.

helper 자체 unit test는 [`tests/unit/contracts/test_helpers.py`](../../../tests/unit/contracts/test_helpers.py)에
있다.

### Error taxonomy (#1816 / #1839)

[`docs/specs/contracts/error-taxonomy.md`](error-taxonomy.md)가 CLI/IPC envelope
`code`/`error.code` 슬롯의 안정 vocabulary와 분류 규칙의 단일 SSOT다. 본 인덱스는
그 본문을 재정의하지 않으며 후속 에픽이 새 code/카테고리를 추가하려면
error-taxonomy.md 자체를 갱신한다.

핵심 lock:

- `ErrorSpec(code, category, exit_code=1, retryable=False reserved)` shape
- 8 category Literal: `validation | auth | permission | not_found | state_conflict | service_unavailable | external | internal`
- `EXECUTION_ERROR` 허용 범위(코드 버그/외부 미분류) + domain exception drift 금지
- auth middleware lowercase code(`auth_required`/`auth_failed`/`permission_denied`)
  는 `AUTH_REQUIRED`/`AUTH_FAILED`/`PERMISSION_DENIED`의 legacy alias로 정렬 (#1815 migration 책임)
- `SERVICE_NOT_CONFIGURED`를 `service_unavailable` category 안정 코드로 등록 (#1819 소비)
- 대표 fault lock: `InvalidAccountIdError → VALIDATION_ERROR`, `BotNotFoundError → BOT_NOT_FOUND`,
  `ApprovalNotFoundError → APPROVAL_NOT_FOUND`, `MemberInvalidScopeError → MEMBER_INVALID_SCOPE`
- broker 원천 code는 envelope 최상위 `code` 슬롯에 노출 금지 (ante public taxonomy만 노출)
- `details` 필드는 reserved (envelope shape 변경은 envelopes.md SSOT 선행)
- redaction: envelope `message`에 token/password/recovery_key 등 민감정보 포함 금지

### Offline service factory contract (#1818 / #1854)

[`docs/specs/contracts/offline-factory.md`](offline-factory.md)가 CLI
`offline`/`cold-path` execution class가 사용하는 service composition factory의
책임/비책임 경계, `read_only` 초기화 정책, ctx 기반 path resolution 정책의
단일 SSOT다. 본 인덱스는 그 본문을 재정의하지 않는다.

핵심 lock:

- factory 책임: DB lifecycle (`Database(get_db_path(ctx))` + `connect()`/`close()`),
  EventBus 생성, service lifecycle, `initialize()` 호출 정책, cleanup
  (`except BaseException` + close 보장; #1722/#1755), config-dir/path resolution.
- factory 비책임: IPC 호출, IPC fallback, runtime vs offline 분기, active
  runtime guard 호출, audit logging, auth/scope 검증, envelope 직렬화, error
  code 매핑.
- `read_only` 정책: 옵션 B (factory-level skip) — `Database` API는 변경하지
  않고, read-only 명령에서 factory가 `service.initialize()` 호출을 skip해 schema
  /DDL trigger를 차단한다.
- ctx 정책: 신규 factory 내부에서 `get_db_path(ctx)` 명시 전달이 권장. ctx 없는
  암시 fallback은 deprecated.
- read-only 예외: `AccountService`/`MemberService`/`ApprovalService`/
  `AuditLogger`/`DynamicConfigService`의 `initialize()`는 schema/migration DDL을
  발화하므로 read-only 명령에서도 호출된다. 본 예외 목록은 후속 #1855 schema
  분리 결정에 따라 축소될 수 있다.

본 SSOT는 [`envelopes.md`](envelopes.md), [`error-taxonomy.md`](error-taxonomy.md)
본문을 재정의하지 않는다. migration order는 [Migration Domain Order](#migration-domain-order)
SSOT를 reference만 한다.

### Migration domain order

후속 4 에픽(#1815/#1816/#1818/#1819)의 **1차 migration 순서는 다음으로 고정**된다.

```text
account → member → approval → bot → treasury → broker → strategy → 기타
```

규칙:

- 각 후속 에픽의 첫 구현 PR은 가능한 한 `account` domain부터 시작한다.
- 독립성이 큰 #1818도 본 순서를 기본값으로 삼되, cleanup 회귀 차단 가치
  때문에 `member`/`approval`까지 같은 1차 PR에 포함할 수 있다. 본 예외는
  #1818 본문에 lock되어 있다.
- 4 에픽 본문, 본 인덱스, 후속 PR에서 본 순서를 다르게 표현하면 drift다.
  drift를 발견하면 본 인덱스를 SSOT로 정렬한다.

본 순서는 [#1820](https://github.com/joshua-jingu-lee/ante/issues/1820)에서
결정되었다.

## 후속 에픽 reference matrix

후속 4 에픽이 본 인덱스의 어느 SSOT 축을 참조해야 하는지 정렬한 표다. 4 에픽
본문 prelude가 본 인덱스와 일치함을 [4-epic cross-check](#4-epic-cross-check)
절에서 확인한다.

| 에픽 | Envelope (#1821) | Vocabulary (#1822) | Drift helper (#1823) | Migration order (#1820) | 추가 reference |
|---|---|---|---|---|---|
| #1815 CLI command contract | CLI success/error | `ContractKind`, `EnvelopeForm`, `AuthMode` | `iter_click_leaf_commands` | 1차: `account` | #1819 IPC registry (server-side SSOT 분리), #1816 error taxonomy |
| #1816 Stable error contract | CLI error, IPC error | (선택) | `iter_exception_classes`, `iter_fmt_error_calls` | 1차: `account` | #1815 auth registry, #1819 `SERVICE_NOT_CONFIGURED` 소비 |
| #1818 Offline service factory | (에러 발화 시) CLI error | (독립) | (해당 없음) | 1차: `account` + `member`/`approval` 예외 허용 | #1816 error taxonomy(에러 발화 시), [offline-factory.md](offline-factory.md) (#1854), generated artifact policy |
| #1819 IPC CommandSpec metadata | IPC success/error | `ContractKind` | `iter_ipc_command_specs` | 1차: `account` | #1816 `SERVICE_NOT_CONFIGURED`, #1815 CLI ↔ IPC drift test |

규칙:

- 본 표는 4 에픽이 같은 SSOT를 가리키는지 추적한다. 4 에픽 본문 자체를
  reference 표로 대체하지 않는다. 본 인덱스는 reference matrix를 제공하고, 4
  에픽 본문은 각자의 normative 책임을 별도로 기술한다.
- 4 에픽 본문이 본 표와 어긋나는 새 vocabulary/envelope/helper를 도입하려고
  하면, 그 변경은 본 인덱스와 #1820 결정에 영향을 주므로 별도 SSOT 이슈로
  분리한다.
- "(선택)"/"(독립)"/"(해당 없음)"은 해당 축이 그 에픽의 1차 책임이 아님을
  뜻한다. 향후 PR에서 필요해지면 본 표를 갱신한다.

## 4-epic cross-check

본 인덱스 작성 시점(#1824 구현 PR, 2026-05-25 KST) 기준으로, 4 에픽 본문이
본 인덱스의 SSOT를 이미 참조하는지 cross-check한 결과다. 본 절은 4 에픽 본문을
재작성하지 않는다 — 본 인덱스 등록 후의 reference 상태를 기록한다.

| 검사 항목 | #1815 | #1816 | #1818 | #1819 |
|---|---|---|---|---|
| `#1820` parent reference (선행 의존) | OK | OK | OK | OK |
| `ContractKind`/`EnvelopeForm`/`AuthMode` vocabulary reference | OK | (선택) | (독립) | OK (`ContractKind`) |
| Envelope shape SSOT reference (`docs/specs/contracts/envelopes.md`) | OK | OK (CLI/IPC error) | OK (에러 발화 시) | OK (IPC success/error) |
| Drift test 공통 helper reference (#1823) | OK | OK | (해당 없음) | OK |
| Migration domain 순서 (`account → … → 기타`) lock | OK | OK | OK (cleanup 예외 명시) | OK |
| `raw_legacy`를 `EnvelopeForm`으로 표현 | OK | (해당 없음) | (해당 없음) | (해당 없음) |
| Generated artifact policy 명시 | OK | OK | OK | OK |

해석:

- 4 에픽 prelude는 본 인덱스가 등록되기 전부터 `#1820`/`ContractKind`/`EnvelopeForm`/`AuthMode`/envelope shape SSOT/drift
  helper/migration order를 일관되게 reference한다. #1824 인덱스 등록 후 본
  인덱스(`docs/specs/contracts/README.md`)를 별도 entry로 가리키도록 4 에픽
  본문을 추가 수정할 필요는 없다.
- 본 인덱스는 4 에픽 본문에 새 normative reference를 강제 삽입하지 않는다.
  4 에픽의 Plan Preflight나 실제 구현 PR에서 본 인덱스를 reference하는 것은
  허용/권장이며, 본 인덱스에서 강제하지 않는다.
- `raw_legacy` 표현은 #1815 prelude와 본 인덱스에서 모두 `EnvelopeForm`으로
  정렬되어 있다. #1816/#1818/#1819는 `raw_legacy`를 직접 다루지 않으므로 해당
  축은 표에서 "(해당 없음)"이다.
- generated artifact policy(`docs/architecture/generated/project-structure.md`
  영향 여부, `guide/cli.md` 재생성 조건)는 4 에픽 본문에 각자 명시되어 있다.
  본 인덱스 추가에 따른 project-structure 재생성은 본 PR이 수행한다.

## 변경 정책

- 본 인덱스가 가리키는 SSOT(envelopes.md, vocab.py, helpers.py)의 본문 변경은
  각 산출물의 변경 정책을 따른다. 본 인덱스는 본문을 재정의하지 않는다.
- 본 인덱스 자체의 변경(새 SSOT 축 추가, migration order 변경, reference matrix
  열 추가)은 #1820 결정을 갱신하는 contract change다. 별도 SSOT 이슈로 다룬다.
- 4 에픽 본문이 본 인덱스와 어긋나면 본 인덱스를 SSOT로 정렬한다. 4 에픽 본문
  대규모 재작성은 본 PR의 범위 밖이며, 후속 별도 이슈로 분리한다.

## Non-Goals

본 인덱스가 다루지 **않는** 항목:

- 4 에픽 본문의 대규모 재작성 — 본 PR은 prelude에 이미 있는 reference 상태를
  cross-check 표로 기록할 뿐이다.
- 실제 CLI command registry / error taxonomy / offline service factory / IPC
  CommandSpec metadata 구현 — 각각 #1815/#1816/#1818/#1819의 책임이다.
- vocabulary/envelope/helper 본문 변경 — 각 산출물 SSOT의 책임이다.
- envelope builder helper(`build_cli_success(...)` 등) 도입 강제 — 본 인덱스
  범위 밖이다.
- production code 변경 — 본 PR은 docs index 전용이다.

## 후속 진행

본 인덱스가 등록된 시점 기준 후속 진행 순서:

1. #1820 meta-epic close (본 #1824 close가 마지막 sub-issue다).
2. #1816 → #1819/#1815 → #1818 순으로 후속 에픽 착수.
   - #1819는 #1816 taxonomy의 `SERVICE_NOT_CONFIGURED`를 소비하므로 #1816 이후.
   - #1818은 #1816 error 발화만 reference하므로 #1815/#1819와 병행 가능.
3. 각 후속 에픽의 Plan Preflight는 본 인덱스를 reference하고, 필요 시 본 인덱스
   reference matrix를 갱신할 후속 patch 이슈를 발행한다.
