# IPC 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/ipc/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) — "단일 asyncio 프로세스", D-002
> 참조: [cli.md](../cli/cli.md) — CLI 커맨드 분류

## 개요

IPC 모듈은 **CLI 프로세스가 서버 프로세스의 서비스 계층을 호출**할 수 있게 하는 프로세스 간 통신 인프라이다.

### 배경

Ante는 "이벤트 드리븐 모듈러 모놀리스"로, 모든 핵심 컴포넌트가 단일 asyncio 프로세스 안에서 동일한 EventBus를 공유한다. 런타임 mutation은 이 프로세스 안에서 실행되어야 이벤트 체인이 정상 작동한다.

그러나 CLI는 별도 프로세스로 실행되며, 서비스를 독립적으로 생성한다. 이로 인해 CLI에서 발행한 이벤트가 서버의 구독자에 전달되지 않아, 런타임 부수효과(봇 중지, 예산 환수, 알림 등)가 누락된다.

IPC 모듈은 이 격차를 해소하여, **CLI가 서버 서비스 인스턴스를 통해 동일한 검증·실행·이벤트 경로**를 타도록 한다.

```
CLI (별도 프로세스)            서버 프로세스
┌──────────────────────┐       ┌─────────────────────────┐
│ 1. ANTE_MEMBER_TOKEN │       │ IPCServer               │
│    → 인증 (DB 읽기)  │       │  → CommandRegistry      │
│ 2. @require_scope    ├──────►│  → _dispatch()          │
│ 3. IPCClient.send()  │ Unix  │                         │
└──────────────────────┘ socket│  Service Registry       │
                               │  ├ EventBus             │
                               │  ├ BotManager           │
                               │  ├ RuleEngine           │
                               │  └ Treasury             │
                               └─────────────────────────┘
```

### 설계 원칙

- **단일 실행 경로**: 비즈니스 로직과 이벤트 발행은 서버 프로세스에서만 수행된다
- **권한 검증은 Member/CLI에서, 실행은 서버에서**: CLI가 Member SSOT 기반 인증·권한 확인 후 커맨드를 서버에 위임한다
- **기존 서비스 재사용**: 새로운 서비스 계층을 만들지 않고, 서버의 기존 서비스 인스턴스를 그대로 호출한다
- **오프라인 커맨드 비간섭**: 읽기 전용·오프라인 커맨드(조회, 백테스트 등)는 기존 "직접 모듈 임포트" 방식을 유지한다

## CLI 커맨드 분류

CLI 명령 시그니처와 전체 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md)다. 이 절은 그중 IPC 서버가 라우팅해야 하는
런타임 커맨드와 cold-path 예외만 설명한다.

구분 기준: **서버 프로세스가 보유한 EventBus 구독자, 인메모리 작업, 외부 연결,
인증·세션 상태가 관여하는가?**

- 있으면 → **런타임 커맨드** → IPC를 통해 서버에 위임
- 없으면 → **오프라인 커맨드** → 직접 모듈 임포트 (기존 유지)

### 런타임 커맨드 전수 목록 (IPC 대상)

#### System

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante system halt` | `system.halt` | `AccountService.suspend_all()` | `AccountSuspendedEvent` → BotManager 소속 봇 중지 |
| `ante system clear-halt` | `system.clear_halt` | `AccountService.activate_all()` | 계좌 상태만 ACTIVE로 복구; BotManager는 `AccountActivatedEvent` 수신 시 로깅만 수행 (자동 재시작은 수행하지 않음) |

#### Account

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante account suspend` | `account.suspend` | `AccountService.suspend()` | `AccountSuspendedEvent` → BotManager 소속 봇 중지 |
| `ante account activate` | `account.activate` | `AccountService.activate()` | 계좌 상태만 ACTIVE로 복구; BotManager는 `AccountActivatedEvent` 수신 시 로깅만 수행 (자동 재시작은 수행하지 않음) |

`ante account create`, `ante account delete`, `ante account set-credentials`는 IPC 대상이 아니다.
이 명령들은 cold-path structural 커맨드이며, active Ante runtime이 살아 있으면 CLI guard에서 차단된다.
특히 `account.delete`는 1.0 IPC 계약(`CommandRegistry`)에 등록되지 않으며, cold-path CLI에서
직접 `AccountService.delete()`를 호출한다. 활성 봇이 남아 있는 계좌는 service preflight
(`AccountHasActiveBotsError`)에서 차단된다.

#### Bot

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante bot create` | `bot.create` | `BotManager.create_bot()` | 등록된 `strategy_id`를 서버 StrategyRegistry에서 해석하고 BotManager 인메모리 `_bots` 반영 필요 |
| `ante bot start <bot_id>` | `bot.start` | `BotManager.get_bot()` + `account_service.get()` + `BotManager.start_bot()` | live 봇 존재 확인 + `app_key` credential preflight + asyncio task 생성 + `BotStartedEvent` 발행. 성공 시 audit `bot.start` 기록 |
| `ante bot stop <bot_id>` | `bot.stop` | `BotManager.get_bot()` + `BotManager.stop_bot()` | live 봇 존재 확인 + 실행 task 취소 + `BotStoppedEvent` 발행. 성공 시 audit `bot.stop` 기록 |
| `ante bot update <bot_id>` | `bot.update` | `BotManager.update_bot()` | 중지 상태 봇 설정을 서버 BotManager 기준으로 갱신 |
| `ante bot status <bot_id>` | `bot.status` | `BotManager.get_bot()` (read-only) | live 조회. 응답은 `{"bot": info}` envelope이며 `strategy_registry`/`treasury_manager`/`trade_service`가 있는 경우 strategy/budget/positions를 동적으로 보강 |
| `ante bot list [--account]` | `bot.list` | `BotManager.list_bots()` (read-only) | live 봇 목록 조회. `--account` 필터 후 CLI 6-key(`bot_id`/`name`/`strategy_id`/`account_id`/`status`/`created_at`) projection. 서버 정지 시 snapshot DB fallback |
| `ante bot info <bot_id>` | `bot.info` | `BotManager.get_bot()` (read-only) | live 봇 상세 조회. `{"bot": info}` envelope. 서버 정지 시 snapshot DB fallback |
| `ante bot positions <bot_id>` | `bot.positions` | `BotManager.get_bot()` + `TradeService.get_positions()` (read-only) | live 포지션 조회. 봇 계좌로 스코핑(#2137). `trade_service` 부재(legacy registry) 시 빈 collection graceful. 서버 정지 시 snapshot DB fallback |
| `ante bot signal-key <bot_id>` | `bot.signal_key` | `BotManager.get_signal_key()` (read-only) | live 시그널 키 조회. `{bot_id, signal_key}` (None 허용). `--rotate`(`bot.signal_key.rotate`, mutating)와 별개 read command. 서버 정지 시 snapshot DB fallback |
| `ante bot remove` | `bot.remove` (server running) / cold-path cleanup (server stopped) | `BotManager.remove_bot()` / `cold_path_remove_bot()` | 실행 중에는 봇 중지, EventBus 구독 해제, signal key 회수, 인메모리 제거 필요. 서버 정지 중에는 persisted cleanup만 수행 |
| `ante bot signal-key --rotate` | `bot.signal_key.rotate` | `BotManager.rotate_signal_key()` | 기존 signal channel 즉시 차단 + 새 key 발급 |

`bot.start`/`bot.stop`은 mutating, `bot.status`는 read-only다. 세 명령 모두 다음 stable
error code를 사용한다.

- `BOT_NOT_FOUND` (재사용 SSOT: `src/ante/bot/exceptions.py:BOT_NOT_FOUND_CODE`):
  `BotManager.get_bot()`이 `None`을 반환.
- `BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED` (신규): `bot.start`에서
  `account.credentials["app_key"]` 누락.
- `BOT_STATE_CONFLICT` (신규): `bot.start`/`bot.stop`의 `BotManager.start_bot()` /
  `stop_bot()` 호출 중 `BotError`.

서버 실행 중 `ante bot list/info/positions/signal-key`는 각각 `bot.list` /
`bot.info` / `bot.positions` / `bot.signal_key` IPC로 서버의 live 상태를 우선
조회한다(#2112, read-only). 서버가 정지된 상태(`IPC_SERVER_NOT_RUNNING`)에서는
DB에 저장된 persisted snapshot 조회로 fallback한다(runtime IPC + snapshot
fallback). `IPC_TIMEOUT`/server-error는 stale snapshot 은폐를 막기 위해
fallback 없이 surface한다. 단, `ante bot remove`는 #1161 cold-path 예외로 server stopped
상태에서 `signal_keys`, 전략 스냅샷, Treasury budget, `bots.status='deleted'`만 직접
정리할 수 있다. `handle_positions=liquidate`는 IPC runtime 경로에서만 의미가 있고,
cold-path 삭제는 항상 keep 의미다.

#### Treasury

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante treasury allocate` | `treasury.allocate` | `Treasury.allocate()` | 인메모리 `_budgets`/`_unallocated` 캐시 동기화 |
| `ante treasury deallocate` | `treasury.deallocate` | `Treasury.deallocate()` | 동일 |
| `ante treasury set-balance` | `treasury.set_balance` | `Treasury.set_account_balance()` | 계좌 총 잔고를 서버 TreasuryManager 캐시에 반영 |

#### Rule

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante rule update` | `rule.update` | `update_account_rule_config()` | DynamicConfig 갱신 + `ConfigChangedEvent` 발행 |

#### Strategy

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante strategy set-status` | `strategy.set_status` | `StrategyRegistry.update_status()` | 전략 채택/보관 상태를 서버 registry 기준으로 변경 |

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
| `ante approval cancel-invalid` | `approval.cancel_invalid` | `ApprovalService.cancel_invalid_type_request()` | scope `approval:admin`. legacy invalid-type row 의 administrative cleanup. 성공 후 `AuditLogger.log(action="approval.cancel_invalid", resource="approval:<id>")` 호출 (#1472) |
| `ante approval reopen` | `approval.reopen` | `ApprovalService.reopen()` | `NotificationEvent` 알림 |

#### Broker

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante broker status` | `broker.status` | `BrokerAdapter.health_check()` | 서버가 보유한 BrokerAdapter 연결 상태와 circuit breaker 상태 조회 |
| `ante broker balance` | `broker.balance` | `BrokerAdapter.get_account_balance()` | 서버 시작 시 생성된 adapter/credentials/rate limit 상태 재사용 |
| `ante broker positions` | `broker.positions` | `BrokerAdapter.get_positions()` | 서버 adapter 연결과 계좌 topology 기준으로 live 포지션 조회 |
| `ante broker reconcile --fix` | `broker.reconcile` | `PositionReconciler.reconcile()` | TradeService 인메모리 반영 + `NotificationEvent` 알림 |

일반 운영 CLI는 broker adapter를 직접 생성하지 않는다. 직접 생성 경로는 서버의
credentials 복호화, 연결 세션, rate limit, circuit breaker, audit 경로를 우회할 수
있다. `broker order`와 `broker stream prices`는 일반 운영 IPC 대상이 아니며 별도
maintenance/test 스펙 없이는 제공하지 않는다.

#### Member

| CLI 커맨드 | IPC 커맨드 | 서비스 메서드 | IPC 필요 사유 |
|-----------|-----------|-------------|-------------|
| `ante member register` | `member.register` | `MemberService.register()` | 토큰 발급 + 감사 로그 + member 알림 |
| `ante member set-emoji` | `member.set_emoji` | `MemberService.update_emoji()` | 런타임 member cache/API 응답 일관성 |
| `ante member suspend` | `member.suspend` | `MemberService.suspend()` | 기존 세션 무효화 + 보안 알림 |
| `ante member reactivate` | `member.reactivate` | `MemberService.reactivate()` | 인증 상태 변경을 런타임 API에 즉시 반영 |
| `ante member revoke` | `member.revoke` | `MemberService.revoke()` | 토큰 해시 삭제 + 세션 무효화 + 되돌릴 수 없는 감사 이벤트 |
| `ante member rotate-token` | `member.rotate_token` | `MemberService.rotate_token()` | 기존 토큰 즉시 무효화 + 새 토큰 1회 반환 |
| `ante member update-scopes` | `member.update_scopes` | `MemberService.update_scopes()` | master-only scope 변경을 서버 MemberService에서 처리 |
| `ante member reset-password` | `member.reset_password` | `MemberService.reset_password()` | recovery key 검증 + 세션 무효화 + 보안 알림 |
| `ante member regenerate-recovery-key` | `member.regenerate_recovery_key` | `MemberService.regenerate_recovery_key()` | 기존 recovery key 폐기 + 보안 알림 |

### 오프라인 커맨드 (기존 유지)

`system start`, `system stop`, `system status`, 서버 live 상태가 필요 없는 조회
커맨드, `backtest`, `data`, `strategy validate/submit`, `report`, `instrument`,
`member list/info`, `audit`, `signal` 등.

조회 커맨드라도 서버가 가진 live 상태를 읽어야 하면 런타임 IPC 대상이다. 대표적으로
`bot list/info/status/positions/signal-key`의 live 조회와
`broker status/balance/positions`가 여기에 속한다.

### Cold-path structural 커맨드

서버 topology를 바꾸는 명령은 IPC로 서버에 위임하지 않는다. active Ante runtime이
살아 있으면 실패하고, 서버 정지 상태에서만 직접 DB를 수정한다. 1.0 정책상 동일 OS
user/home server 기준으로 active runtime은 항상 단일이며, `config_dir`은 데이터/설정
프로필 경계지 동시 namespace가 아니다.

| CLI 커맨드 | active runtime 시 동작 | 이유 |
|-----------|------------------|------|
| `ante account create` | 차단 | Treasury/RuleEngine/Gateway/Bot hot wiring 비지원 |
| `ante account delete` | 차단 | 실행 중 consumer 제거와 partial failure 보상 비지원. 활성 봇이 남아 있으면 service preflight(`AccountHasActiveBotsError`)에서도 차단 |
| `ante account set-credentials` | 차단 | BrokerAdapter 재초기화와 장기 실행 consumer 전파 비지원 |

`account.delete`는 1.0 IPC 계약에서 제외된다. cold-path CLI는 `AccountService.delete()`를
직접 호출하며, IPC 라우팅 테이블(`CommandRegistry`)에 등록하지 않는다.

### 서버 정지 maintenance fallback

`member register/set-emoji/suspend/reactivate/revoke/rotate-token/reset-password/regenerate-recovery-key`는
서버 실행 중 런타임 IPC 대상이다. 같은 `config_dir`의 서버가 정지된 상태에서는
bootstrap, recovery, 비상 revoke 같은 운영 복구를 위해 CLI가 MemberService를 직접
생성할 수 있다. 이 fallback은 account cold-path처럼 서버 topology를 바꾸지는 않지만,
인증·세션 상태를 바꾸므로 서버 실행 중 직접 DB 수정은 금지한다.

## IPCServer lifecycle state

IPCServer는 shutdown 중 활성 IPC connection이 새 mutating 명령을 dispatch하는 race를
막기 위해 명시적인 lifecycle state를 가진다.

| 상태 | 진입 시점 | IPC dispatch 정책 |
|------|-----------|------------------|
| `RUNNING` | `start()`가 Unix socket listener와 파일 권한 설정을 완료한 직후 | 모든 등록 명령을 정상 dispatch |
| `SHUTTING_DOWN` | `stop_accepting()` 진입 직후, listener `close()` 호출 전 | mutating 명령은 `SERVICE_UNAVAILABLE`로 거부, read-only 명령은 통과 |
| `DRAINING` | `_shutdown()`이 BrokerAdapter disconnect/DB close 같은 리소스 종료에 들어가기 직전, 또는 `stop()` facade가 drain을 시작하기 직전 | mutating/read-only를 포함한 모든 명령을 `SERVICE_UNAVAILABLE`로 거부 |
| `STOPPED` | `unlink_socket()` 종료 시점 | mutating/read-only를 포함한 모든 명령을 `SERVICE_UNAVAILABLE`로 거부 |

`SHUTTING_DOWN`에서 read-only 명령을 통과시키는 이유는 BotManager와 DB가 아직 살아
있는 초기 shutdown 구간의 운영 가시성을 보존하기 위해서다. 반대로 `DRAINING` 이후는
BrokerAdapter disconnect와 DB close가 시작되는 구간이므로 read-only도 closed resource
접근 위험이 있어 거부한다.

`stop_accepting()`은 새 연결 수락만 중지하고 소켓 파일을 유지한다. cold-path guard는
`PID alive AND socket exists`를 active runtime으로 판정하므로, `unlink_socket()`은
BotManager/DB 종료 이후 lifecycle 마지막 단계에서만 호출된다.

## Handler taxonomy

`CommandRegistry`는 각 등록 명령을 `CommandSpec`으로 보관하며, `is_mutating` taxonomy를
명시한다. 이 taxonomy는 `SHUTTING_DOWN` 상태에서 mutating 명령만
`SERVICE_UNAVAILABLE`로 거부하기 위한 서버 측 계약이다.

- **mutating**: 서버 인메모리 상태, DB, 계좌/봇/예산/설정/결재/정산 상태를 변경하거나
  변경 이벤트를 발행하는 명령
- **read-only**: 서버가 보유한 live adapter를 통해 상태를 조회하지만 서버/DB 상태를
  변경하지 않는 명령

현재 `CommandRegistry.register_all_handlers()`에 등록된 IPC handler taxonomy는 아래 40개가
SSOT다. 새 handler를 추가할 때는 코드의 `is_mutating` 값과 이 표를 함께 갱신해야 한다.

| IPC 커맨드 | taxonomy | 근거 |
|-----------|----------|------|
| `system.halt` | mutating | `AccountService.suspend_all()` 호출 |
| `system.clear_halt` | mutating | `AccountService.activate_all()` 호출 |
| `account.suspend` | mutating | `AccountService.suspend()` 호출 |
| `account.activate` | mutating | `AccountService.activate()` 호출 |
| `bot.create` | mutating | `BotManager.create_bot()` 호출 |
| `bot.remove` | mutating | `BotManager.remove_bot()` 호출 |
| `bot.start` | mutating | `BotManager.start_bot()` 호출. `app_key` preflight + audit `bot.start` (#1712) |
| `bot.stop` | mutating | `BotManager.stop_bot()` 호출. audit `bot.stop` (#1712) |
| `bot.update` | mutating | `BotManager.update_bot()` 호출 |
| `bot.signal_key.rotate` | mutating | `BotManager.rotate_signal_key()` 호출. 기존 signal key 폐기 + 새 key 발급, audit `bot.signal_key.rotate` (#2111) |
| `treasury.allocate` | mutating | `Treasury.allocate()` 호출 |
| `treasury.deallocate` | mutating | `Treasury.deallocate()` 호출 |
| `treasury.set_balance` | mutating | `Treasury.set_account_balance()` 호출 |
| `rule.update` | mutating | DynamicConfig 기반 계좌 룰 수정 |
| `strategy.set_status` | mutating | `StrategyRegistry.update_status()` 호출 |
| `member.update_scopes` | mutating | `MemberService.update_scopes()` 호출 |
| `member.register` | mutating | `MemberService.register()` 호출. 토큰 발급 + 감사 로그. 발급 토큰은 result 에만 surface (#2113) |
| `member.set_emoji` | mutating | `MemberService.update_emoji()` 호출 (#2113) |
| `member.suspend` | mutating | `MemberService.suspend()` 호출. master 게이트 + 세션 무효화 (#2113) |
| `member.reactivate` | mutating | `MemberService.reactivate()` 호출 (#2113) |
| `member.revoke` | mutating | `MemberService.revoke()` 호출. 토큰 해시 삭제 (#2113) |
| `member.rotate_token` | mutating | `MemberService.rotate_token()` 호출. 새 토큰은 result 에만 surface (#2113) |
| `member.reset_password` | mutating | auth-exempt. master-lookup 을 handler 에서 수행, audit member_id 는 고정 sentinel. secret 은 result/audit/log 비노출 (#2113) |
| `member.regenerate_recovery_key` | mutating | auth-exempt. 새 recovery key 는 result 에만 surface (#2113) |
| `config.set` | mutating | `DynamicConfigService.set()` 호출 |
| `approval.request` | mutating | `ApprovalService.create()` 호출 |
| `approval.approve` | mutating | `ApprovalService.approve()` 호출 |
| `approval.reject` | mutating | `ApprovalService.reject()` 호출 |
| `approval.cancel` | mutating | `ApprovalService.cancel()` 호출 |
| `approval.cancel_invalid` | mutating | `ApprovalService.cancel_invalid_type_request()` 호출 + AuditLogger 기록 (#1472) |
| `approval.reopen` | mutating | `ApprovalService.reopen()` 호출 |
| `broker.reconcile` | mutating | `PositionReconciler.reconcile()`이 보정/이벤트 경로를 수행 |
| `broker.status` | read-only | `BrokerAdapter.health_check()` live 조회 |
| `broker.balance` | read-only | `BrokerAdapter.get_account_balance()` live 조회 |
| `broker.positions` | read-only | `BrokerAdapter.get_positions()` live 조회 |
| `bot.status` | read-only | `BotManager.get_bot()` live 조회. `{bot: ...}` envelope (#1712) |
| `bot.list` | read-only | `BotManager.list_bots()` live 조회. `--account` 필터 + CLI 6-key projection, `{bots: [...]}` envelope (#2112) |
| `bot.info` | read-only | `BotManager.get_bot()` live 조회. `{bot: info}` envelope (#2112) |
| `bot.positions` | read-only | `BotManager.get_bot()` 존재확인 + `TradeService.get_positions()` 봇 계좌 스코핑(#2137). `{positions: [...]}` envelope (#2112) |
| `bot.signal_key` | read-only | `BotManager.get_signal_key()` live 조회. `{bot_id, signal_key}` (None 허용). `bot.signal_key.rotate`(mutating)와 별개 read command (#2112) |

`broker.reconcile`은 CLI `--fix=False` 경로에서도 같은 IPC command를 사용하지만, 한 command
이름에 mutating/read-only 의미를 섞지 않고 일괄 mutating으로 분류한다. dry-run 전용
IPC command 분리는 별도 이슈 범위다.

`account.delete`처럼 1.0 IPC 계약에서 제외되어 `CommandRegistry`에 등록되지 않는 명령은
taxonomy 대상이 아니다. `member.*` 9개(`member.update_scopes` + admin mutation 8개)는 모두
`register_all_handlers()`에 wiring되어 있으며, CLI는 서버 실행 중 runtime IPC로 위임하고 서버
정지 시 maintenance fallback으로 `MemberService`를 직접 생성한다(IPC-first + 서버 정지 fallback,
#2113).

`member.register` / `member.rotate_token`의 발급 토큰과 `member.regenerate_recovery_key`의 새
recovery key는 사용자 표시용 result에만 담고 audit detail / audit_log / IPC error envelope /
server 로그 어디에도 노출하지 않는다. `member.reset_password` / `member.regenerate_recovery_key`는
auth-exempt이므로 대상 master member_id를 client가 아니라 서버 handler에서 master-lookup으로
해석하고, audit의 member_id는 client actor(스푸핑 가능)가 아니라 handler가 고정한 sentinel 상수로
기록한다.

## 통신 프로토콜

### 전송 계층

- **Unix domain socket**: Config resolver가 정규화한 `runtime.socket_path`
  - 기본값: `<config_dir>/run/ante.sock`
  - `system.toml`에는 `runtime.socket_path = "run/ante.sock"`처럼 `config_dir` 기준 상대 경로를 기록한다.
- 서버 기동 시 소켓 생성, 종료 시 삭제
- 파일 시스템 권한으로 접근 제어 (소유자만 접근 가능, `0o600`)

CLI와 서버는 같은 `--config-dir` 또는 `ANTE_CONFIG_DIR`을 사용할 때 같은 socket을 본다.
CWD나 `db.path` parent에서 socket 위치를 파생하지 않는다.

### 메시지 형식

JSON 기반, 길이 접두사(length-prefixed) 프레이밍.

IPC 응답 envelope(`status:"ok"` + `result` / `status:"error"` + `error`) 형태의
normative SSOT는 [contracts/envelopes.md](../contracts/envelopes.md)다. 본 절은
요청 envelope 형태와 응답 envelope 의 IPC 측 적용 예시만 기술한다. 새 필드
추가/변경은 본 절이 아닌 SSOT 문서를 우선 갱신한다.

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
| `actor` | `string` | CLI에서 인증된 멤버 ID (감사 추적용). 인증 면제 recovery 커맨드는 `"unknown"` 또는 recovery 대상 member_id |

**응답 (성공)** — IPC success envelope의 적용 예시. envelope 형태 SSOT는
[contracts/envelopes.md — IPC success envelope](../contracts/envelopes.md#ipc-success-envelope):

```json
{
  "id": "uuid-v4",
  "status": "ok",
  "result": {
    "suspended_count": 2
  }
}
```

`result` payload(`{"suspended_count": N}`, `{"bot": ...}` 등)는 도메인 IPC
커맨드별 계약이며 envelope 형태가 아니다.

**응답 (실패)** — IPC error envelope의 적용 예시. envelope 형태 SSOT는
[contracts/envelopes.md — IPC error envelope](../contracts/envelopes.md#ipc-error-envelope):

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

`error.code` 값의 vocabulary(taxonomy, 도메인 prefix 규칙, 공통 코드 SSOT)는
[`docs/specs/contracts/error-taxonomy.md`](../contracts/error-taxonomy.md) SSOT에
lock 되어 있다. 본 절은 envelope 형태만 다루며 vocabulary는 재정의하지 않는다.
현재 사용되는 공통 코드(`UNKNOWN_COMMAND`, `SERVICE_UNAVAILABLE`,
`SERVICE_NOT_CONFIGURED`, `EXECUTION_ERROR`) 의 의미는 위 SSOT를 따른다. 현재
사용되는 공통 코드 일부는 아래 [에러 처리](#에러-처리) 표에 예시로 기록한다.

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
| `__init__` | `(self, socket_path: str, service_registry: ServiceRegistry, command_registry: CommandRegistry)` | 소켓 경로와 서비스/커맨드 레지스트리 |
| `start` | `async (self) -> None` | 소켓 서버 시작, `asyncio.start_unix_server` 사용, state를 `RUNNING`으로 전환 |
| `stop_accepting` | `async (self) -> None` | state를 `SHUTTING_DOWN`으로 전환한 뒤 새 연결 수락 중지, 소켓 파일 유지 |
| `stop_dispatching` | `(self) -> None` | state를 `DRAINING`으로 전환하여 active connection의 추가 dispatch를 모두 거부 |
| `drain_connections` | `async (self, timeout: float = 5.0) -> None` | active 연결 drain 대기, timeout 시 경고 후 진행 |
| `unlink_socket` | `(self) -> None` | 소켓 파일 삭제, state를 `STOPPED`로 전환 |
| `stop` | `async (self) -> None` | 호환 facade: `stop_accepting()` → `stop_dispatching()` → `drain_connections()` → `unlink_socket()` |
| `_handle_connection` | `async (self, reader, writer) -> None` | 커넥션별 요청 처리 |
| `_dispatch` | `async (self, request: dict) -> dict` | lifecycle state/taxonomy 검사 → `CommandRegistry`에서 핸들러 조회 → 실행 → 결과 반환 |

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
| `get` | `(self, command: str) -> CommandSpec \| None` | 커맨드에 대한 핸들러와 taxonomy 반환 |
| `register` | `(self, command: str, handler: CommandHandler, *, is_mutating: bool) -> None` | 커맨드 핸들러와 mutating/read-only taxonomy 등록 |

`CommandHandler` 시그니처: `async (registry: ServiceRegistry, args: dict, actor: str) -> dict`

`CommandSpec` 필드: `name: str`, `handler: CommandHandler`, `is_mutating: bool`

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
    strategy_registry: StrategyRegistry | None = None
    audit_logger: AuditLogger | None = None  # #1472: approval.cancel_invalid audit
```

`audit_logger` 는 administrative mutation IPC (`approval.cancel_invalid`) 가
정상 환경에서 `audit_log` 테이블에 기록을 남기기 위한 optional 필드다.
테스트/legacy 환경에서는 `None` 이 허용되며, 핸들러는
`getattr(svc, "audit_logger", None)` 패턴으로 안전하게 분기한다 — `None` 일
때는 service 의 `history` append 가 fallback 추적 경로다.

## 에러 처리

`error.code` 값의 vocabulary와 분류(category, `EXECUTION_ERROR` 허용 범위,
`SERVICE_NOT_CONFIGURED` 의미, broker external code 분리, redaction)는
[`docs/specs/contracts/error-taxonomy.md`](../contracts/error-taxonomy.md) SSOT가
lock 한다. 본 절은 IPC server lifecycle/디스패치에서의 적용 예시만 기술한다.
특히 `_dispatch`의 `getattr(e, "code", "EXECUTION_ERROR")` fallback은 SSOT의
[`EXECUTION_ERROR` 허용 범위](../contracts/error-taxonomy.md#execution_error-허용-범위)를
따른다 — domain exception이 `code` 미부여로 `EXECUTION_ERROR`로 접히는 것은
drift다.

| 상황 | 동작 |
|------|------|
| 서버 미기동 (소켓 없음) | 런타임 전용 커맨드는 `IPCClient`가 `ServerNotRunningError` 발생. CLI는 `"서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."` 출력 후 종료. member maintenance fallback 대상은 IPC 실패 전/후 직접 MemberService 경로로 전환 가능 |
| 타임아웃 (기본 30초) | `IPCClient`가 `IPCTimeoutError` 발생. CLI는 `"서버 응답 시간 초과"` 출력 후 종료 |
| 서버 내부 에러 | 응답 `status: "error"` 반환. CLI는 `error.code` + `error.message` 출력 |
| 미등록 커맨드 | `_dispatch`에서 `UNKNOWN_COMMAND` 에러 응답 |
| shutdown 중 mutating 명령 | `SHUTTING_DOWN` 상태의 mutating 명령은 `SERVICE_UNAVAILABLE` 에러 응답 |
| 리소스 drain 중 dispatch | `DRAINING` 상태의 모든 명령은 `SERVICE_UNAVAILABLE` 에러 응답 |
| 서버 종료 후 dispatch | `STOPPED` 상태의 모든 명령은 `SERVICE_UNAVAILABLE` 에러 응답 |

## 보안 고려

- **소켓 파일 권한**: 생성 시 `0o600` (소유자만 읽기/쓰기) — 로컬 머신의 다른 사용자 접근 차단
- **인증 이중화 불필요**: 일반 CLI는 이미 `ANTE_MEMBER_TOKEN`으로 인증 + Member scope 확인을 수행하므로, IPC 계층에서 재인증하지 않는다. IPC는 별도 permission vocabulary를 소유하지 않고 `actor` 필드로 감사 추적만 전달한다. `member reset-password`처럼 인증 면제 recovery 커맨드는 토큰 대신 recovery key 또는 현재 패스워드를 서버 서비스가 검증한다
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
