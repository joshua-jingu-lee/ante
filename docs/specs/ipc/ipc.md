# IPC 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/ipc/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) — "단일 asyncio 프로세스", D-002
> 참조: [cli.md](../cli/cli.md) — CLI 커맨드 분류

## 개요

IPC 모듈은 **CLI 프로세스가 서버 프로세스의 서비스 계층을 호출**할 수 있게 하는 프로세스 간 통신 인프라이다.

### 배경

Ante는 "이벤트 드리븐 모듈러 모놀리스"로, 모든 핵심 컴포넌트가 단일 asyncio 프로세스 안에서 동일한 EventBus를 공유한다. 웹 API는 이 프로세스 안에서 실행되므로 이벤트 체인이 정상 작동한다.

그러나 CLI는 별도 프로세스로 실행되며, 서비스를 독립적으로 생성한다. 이로 인해 CLI에서 발행한 이벤트가 서버의 구독자에 전달되지 않아, 런타임 부수효과(봇 중지, 예산 환수, 알림 등)가 누락된다.

IPC 모듈은 이 격차를 해소하여, **CLI와 웹 API가 동일한 서비스 인스턴스를 통해 동일한 검증·실행·이벤트 경로**를 타도록 한다.

```
웹 API (서버 프로세스 내부)       CLI (별도 프로세스)
┌─────────────────────┐        ┌──────────────────────┐
│ FastAPI 라우터       │        │ 1. ANTE_MEMBER_TOKEN  │
│                     │        │    → 인증 (DB 읽기)   │
│                     │        │ 2. @require_scope     │
│                     │        │ 3. IPCClient.send()   │
│                     │        └──────────┬───────────┘
│                     │                   │ Unix socket
│  ┌───────────────┐  │    ┌──────────────▼──────────┐
│  │               │  │    │ IPCServer               │
│  │  Service      │◄─┼────┤  → CommandRegistry      │
│  │  Registry     │  │    │  → _dispatch()          │
│  │               │  │    └─────────────────────────┘
│  └───────┬───────┘  │
│          │          │
│  ┌───────▼───────┐  │
│  │   EventBus    │  │
│  │  ├ BotManager │  │
│  │  ├ RuleEngine │  │
│  │  └ Treasury   │  │
│  └───────────────┘  │
└─────────────────────┘
```

### 설계 원칙

- **단일 실행 경로**: 비즈니스 로직과 이벤트 발행은 서버 프로세스에서만 수행된다
- **인증은 CLI에서, 실행은 서버에서**: CLI가 인증·권한 확인 후 커맨드를 서버에 위임한다
- **기존 서비스 재사용**: 새로운 서비스 계층을 만들지 않고, 서버의 기존 서비스 인스턴스를 그대로 호출한다
- **오프라인 커맨드 비간섭**: 읽기 전용·오프라인 커맨드(조회, 백테스트 등)는 기존 "직접 모듈 임포트" 방식을 유지한다

## CLI 커맨드 분류

구분 기준: **서버의 EventBus 구독자가 반응해야 하는 부수효과(이벤트 발행 또는 인메모리 상태 변경)가 있는가?**

- 있으면 → **런타임 커맨드** → IPC를 통해 서버에 위임
- 없으면 → **오프라인 커맨드** → 직접 모듈 임포트 (기존 유지)

### 런타임 커맨드 전수 목록 (IPC 대상)

#### System

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante system halt` | `system.halt` | `AccountService.suspend_all()` | `AccountSuspendedEvent` → BotManager 봇 중지 |
| `ante system activate` | `system.activate` | `AccountService.activate_all()` | `AccountActivatedEvent` → BotManager 봇 재시작 |

#### Account

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante account suspend` | `account.suspend` | `AccountService.suspend()` | `AccountSuspendedEvent` → BotManager 봇 중지 |
| `ante account activate` | `account.activate` | `AccountService.activate()` | `AccountActivatedEvent` → BotManager 봇 재시작 |
| `ante account delete` | `account.delete` | `AccountService.delete()` | `AccountSuspendedEvent` → BotManager 봇 중지 + `AccountDeletedEvent` 발행 |

#### Bot

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante bot create` | `bot.create` | `BotManager.create_bot()` | BotManager 인메모리 `_bots` 반영 필요 |
| `ante bot remove` | `bot.remove` | `BotManager.remove_bot()` | 실행 중 봇 중지 + 인메모리 제거 필요 |

#### Treasury

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante treasury allocate` | `treasury.allocate` | `Treasury.allocate()` | 인메모리 `_budgets`/`_unallocated` 캐시 동기화 |
| `ante treasury deallocate` | `treasury.deallocate` | `Treasury.deallocate()` | 동일 |

#### Config

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante config set` | `config.set` | `DynamicConfigService.set()` | `ConfigChangedEvent` → RuleEngine, NotificationService 반영 |

#### Approval

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante approval request` | `approval.request` | `ApprovalService.create()` | `NotificationEvent` 알림 + 전결 시 executor 실행 |
| `ante approval approve` | `approval.approve` | `ApprovalService.approve()` | `NotificationEvent` 알림 + executor 실행 |
| `ante approval reject` | `approval.reject` | `ApprovalService.reject()` | `NotificationEvent` 알림 |
| `ante approval cancel` | `approval.cancel` | `ApprovalService.cancel()` | `NotificationEvent` 알림 |
| `ante approval reopen` | `approval.reopen` | `ApprovalService.reopen()` | `NotificationEvent` 알림 |

#### Broker

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante broker reconcile --fix` | `broker.reconcile` | `PositionReconciler.reconcile()` | TradeService 인메모리 반영 + `NotificationEvent` 알림 |

### 오프라인 커맨드 (기존 유지)

`system start`, `system stop`, `system status`, 모든 조회(`list`, `show`, `status`) 커맨드, `backtest`, `data`, `strategy validate/submit`, `report`, `instrument`, `member` 조회, `audit`, `signal` 등.

> **참고**: `member register/suspend/revoke`는 이벤트를 발행하지만 현재 서버에 구독자가 없으므로 오프라인으로 분류한다. 향후 구독자가 추가되면 런타임으로 재분류한다.

## 통신 프로토콜

### 전송 계층

- **Unix domain socket**: `{data_dir}/ante.sock` (예: `db/ante.sock`)
- 서버 기동 시 소켓 생성, 종료 시 삭제
- 파일 시스템 권한으로 접근 제어 (소유자만 접근 가능, `0o600`)

### 메시지 형식

JSON 기반, 길이 접두사(length-prefixed) 프레이밍.

**요청**:
```json
{
  "id": "uuid-v4",
  "command": "system.halt",
  "args": {
    "reason": "긴급 중지"
  },
  "actor": "master"
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `string` (UUID v4) | 요청 식별자. 응답의 `id`와 매칭 |
| `command` | `string` | IPC 커맨드 (`CommandRegistry` 키) |
| `args` | `dict` | 커맨드 파라미터 |
| `actor` | `string` | CLI에서 인증된 멤버 ID (감사 추적용) |

**응답 (성공)**:
```json
{
  "id": "uuid-v4",
  "status": "ok",
  "result": {
    "suspended_count": 2
  }
}
```

**응답 (실패)**:
```json
{
  "id": "uuid-v4",
  "status": "error",
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "계좌를 찾을 수 없습니다: qa-acct-01"
  }
}
```

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `string` | 요청 `id`와 동일 |
| `status` | `"ok" \| "error"` | 성공/실패 |
| `result` | `dict` | 성공 시 반환 데이터 |
| `error.code` | `string` | 에러 코드 (서비스 예외 클래스명 등) |
| `error.message` | `string` | 에러 메시지 |

### 프레이밍

```
[4바이트 빅엔디안 길이][JSON 페이로드]
```

최대 메시지 크기: 1MB

## 컴포넌트 설계

### IPCServer

서버 프로세스에서 Unix socket을 열고, CLI 커맨드를 수신하여 서비스 계층으로 라우팅한다.

```
소스: src/ante/ipc/server.py
```

| 메서드 | 시그니처 | 설명 |
|--------|---------|------|
| `__init__` | `(self, socket_path: str, registry: ServiceRegistry)` | 소켓 경로와 서비스 레지스트리 |
| `start` | `async (self) -> None` | 소켓 서버 시작, `asyncio.start_unix_server` 사용 |
| `stop` | `async (self) -> None` | 소켓 서버 종료, 소켓 파일 삭제 |
| `_handle_connection` | `async (self, reader, writer) -> None` | 커넥션별 요청 처리 |
| `_dispatch` | `async (self, command: str, args: dict, actor: str) -> dict` | `CommandRegistry`에서 핸들러 조회 → 실행 → 결과 반환 |

### IPCClient

CLI 프로세스에서 서버의 Unix socket에 연결하여 커맨드를 전달하고 결과를 수신한다.

```
소스: src/ante/ipc/client.py
```

| 메서드 | 시그니처 | 설명 |
|--------|---------|------|
| `__init__` | `(self, socket_path: str, timeout: float = 30.0)` | 소켓 경로, 타임아웃 |
| `send` | `async (self, command: str, args: dict, actor: str) -> dict` | 커맨드 전송 + 결과 수신. 소켓 미존재 시 `ServerNotRunningError` |

### CommandRegistry

커맨드 문자열을 서비스 메서드에 매핑하는 라우팅 테이블.

```
소스: src/ante/ipc/registry.py
```

| 메서드 | 시그니처 | 설명 |
|--------|---------|------|
| `get` | `(self, command: str) -> CommandHandler \| None` | 커맨드에 대한 핸들러 반환 |
| `register` | `(self, command: str, handler: CommandHandler) -> None` | 커맨드 핸들러 등록 |

`CommandHandler` 시그니처: `async (registry: ServiceRegistry, args: dict, actor: str) -> dict`

### ServiceRegistry

서버의 서비스 인스턴스를 모아 놓은 컨테이너.

```
소스: src/ante/core/registry.py
```

```python
@dataclass
class ServiceRegistry:
    account: AccountService
    bot_manager: BotManager
    treasury_manager: TreasuryManager
    dynamic_config: DynamicConfigService
    approval: ApprovalService
    reconciler: PositionReconciler
    eventbus: EventBus
```

## 에러 처리

| 상황 | 동작 |
|------|------|
| 서버 미기동 (소켓 없음) | `IPCClient`가 `ServerNotRunningError` 발생. CLI는 `"서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."` 출력 후 종료 |
| 타임아웃 (기본 30초) | `IPCClient`가 `IPCTimeoutError` 발생. CLI는 `"서버 응답 시간 초과"` 출력 후 종료 |
| 서버 내부 에러 | 응답 `status: "error"` 반환. CLI는 `error.code` + `error.message` 출력 |
| 미등록 커맨드 | `_dispatch`에서 `UNKNOWN_COMMAND` 에러 응답 |

## 보안 고려

- **소켓 파일 권한**: 생성 시 `0o600` (소유자만 읽기/쓰기) — 로컬 머신의 다른 사용자 접근 차단
- **인증 이중화 불필요**: CLI에서 이미 `ANTE_MEMBER_TOKEN`으로 인증 + scope 확인을 수행하므로, IPC 계층에서 재인증하지 않는다. `actor` 필드로 감사 추적만 전달한다
- **요청 크기 제한**: 메시지 최대 크기 1MB — 과도한 페이로드 차단

## 파일 구조

```
src/ante/ipc/
├── __init__.py
├── server.py       # IPCServer — asyncio Unix socket 서버
├── client.py       # IPCClient — CLI용 클라이언트
├── registry.py     # CommandRegistry (커맨드 → 서비스 라우팅)
└── protocol.py     # 메시지 직렬화/역직렬화, 프레이밍

src/ante/core/
└── registry.py     # ServiceRegistry (서비스 컨테이너)
```
