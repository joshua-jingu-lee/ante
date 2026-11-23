# Ante IPC Commands

`CommandRegistry`에 등록된 IPC 명령과 그 요청 모델을 정리한 문서입니다. `register_all_handlers`의 등록 값, `src/ante/ipc/requests.py`의 요청 모델, CLI 계약의 `ipc_command`에서 생성합니다.

> 이 문서는 `scripts/generate_ipc_commands.py`로 자동 생성됩니다. 직접 편집하지 말고 등록·요청 모델·CLI 계약을 수정한 뒤 재생성하세요.

> 생성 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_ipc_commands.py`
> Check 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_ipc_commands.py --check`

- 명령: **42**개 (mutating **32** / read-only **10**)

분류·`required_services`·`audit_action`·요청 모델은 등록에서, CLI 경로는 CLI 계약에서 그 명령을 `ipc_command`로 가진 경로에서 얻습니다. 그런 경로가 없는 등록 명령(`bot.signal_key.rotate`, `signal.connect`)을 어느 CLI 경로가 보내는지는 [ipc.md](../../specs/ipc/ipc.md)의 런타임 커맨드 전수 목록에서 봅니다.

## 명령

| IPC 명령 | 분류 | `required_services` | `audit_action` | 요청 모델 | 요청 필드 | CLI 경로(계약의 `ipc_command`) |
|---|---|---|---|---|---|---|
| `account.activate` | mutating | `account`, `audit_logger` | `account.activate` | `AccountActivateRequest` | `account_id: AccountId` (필수) | `ante account activate` |
| `account.suspend` | mutating | `account`, `audit_logger` | `account.suspend` | `AccountSuspendRequest` | `account_id: AccountId` (필수)<br>`reason: str = "IPC suspend"` | `ante account suspend` |
| `approval.approve` | mutating | `approval`, `audit_logger` | `approval.approve` | `ApprovalApproveRequest` | `id: str` (필수) | `ante approval approve` |
| `approval.cancel` | mutating | `approval`, `audit_logger` | `approval.cancel` | `ApprovalCancelRequest` | `id: str` (필수) | `ante approval cancel` |
| `approval.cancel_invalid` | mutating | `approval`, `audit_logger` | `approval.cancel_invalid` | `ApprovalCancelInvalidRequest` | `approval_id: str` (필수) | `ante approval cancel-invalid` |
| `approval.reject` | mutating | `approval`, `audit_logger` | `approval.reject` | `ApprovalRejectRequest` | `id: str` (필수)<br>`reason: str = ""` | `ante approval reject` |
| `approval.reopen` | mutating | `approval` | — | `ApprovalReopenRequest` | `id: str` (필수)<br>`body: str \| None = null`<br>`params: dict[str, Any] \| None = null` | `ante approval reopen` |
| `approval.request` | mutating | `approval` | — | `ApprovalRequestRequest` | `type: str` (필수)<br>`title: str` (필수)<br>`body: str = ""`<br>`params: dict[str, Any] \| None = null`<br>`reference_id: str = ""`<br>`expires_at: str = ""` | `ante approval request` |
| `bot.create` | mutating | `audit_logger`, `bot_manager`, `strategy_registry` | `bot.create` | `BotCreateRequest` | `strategy_id: str` (필수)<br>`account_id: AccountId` (필수)<br>`bot_id: str = ""`<br>`name: str = ""`<br>`interval_seconds: int = 60` | `ante bot create` |
| `bot.info` | read-only | `bot_manager` | — | `BotInfoRequest` | `bot_id: str` (필수) | `ante bot info` |
| `bot.list` | read-only | `bot_manager` | — | `BotListRequest` | `account_id: AccountId \| None = null` | `ante bot list` |
| `bot.positions` | read-only | `bot_manager` | — | `BotPositionsRequest` | `bot_id: str` (필수) | `ante bot positions` |
| `bot.remove` | mutating | `audit_logger`, `bot_manager` | `bot.delete` | `BotRemoveRequest` | `bot_id: str` (필수) | `ante bot remove` |
| `bot.signal_key` | read-only | `bot_manager` | — | `BotSignalKeyRequest` | `bot_id: str` (필수) | `ante bot signal-key` |
| `bot.signal_key.rotate` | mutating | `audit_logger`, `bot_manager` | `bot.signal_key.rotate` | `BotSignalKeyRotateRequest` | `bot_id: str` (필수) | — |
| `bot.start` | mutating | `account`, `audit_logger`, `bot_manager` | `bot.start` | `BotStartRequest` | `bot_id: str` (필수) | `ante bot start` |
| `bot.status` | read-only | `bot_manager` | — | `BotStatusRequest` | `bot_id: str` (필수) | `ante bot status` |
| `bot.stop` | mutating | `audit_logger`, `bot_manager` | `bot.stop` | `BotStopRequest` | `bot_id: str` (필수) | `ante bot stop` |
| `bot.update` | mutating | `audit_logger`, `bot_manager` | `bot.update` | `BotUpdateRequest` | `bot_id: str` (필수)<br>`updates: BotUpdateFields = BotUpdateFields()` | `ante bot update` |
| `broker.balance` | read-only | `account` | — | `BrokerBalanceRequest` | `account_id: AccountId` (필수) | `ante broker balance` |
| `broker.order_history` | read-only | `account` | — | `BrokerOrderHistoryRequest` | `account_id: AccountId` (필수)<br>`from_date: IsoDate \| None = null`<br>`to_date: IsoDate \| None = null` | `ante broker order-history` |
| `broker.positions` | read-only | `account` | — | `BrokerPositionsRequest` | `account_id: AccountId` (필수) | `ante broker positions` |
| `broker.reconcile` | mutating | `account`, `audit_logger`, `bot_manager`, `reconciler` | — | `BrokerReconcileRequest` | `account_id: AccountId` (필수)<br>`fix: bool = false` | `ante broker reconcile` |
| `broker.status` | read-only | `account` | — | `BrokerStatusRequest` | `account_id: AccountId` (필수) | `ante broker status` |
| `config.set` | mutating | `dynamic_config` | — | `ConfigSetRequest` | `key: str` (필수)<br>`value: str` (필수)<br>`category: str = "user"` | `ante config set` |
| `member.reactivate` | mutating | `audit_logger`, `member_service` | `member.reactivate` | `MemberReactivateRequest` | `member_id: str` (필수) | `ante member reactivate` |
| `member.regenerate_recovery_key` | mutating | `audit_logger`, `member_service` | `member.regenerate_recovery_key` | `MemberRegenerateRecoveryKeyRequest` | `password: SecretStr` (필수) | `ante member regenerate-recovery-key` |
| `member.register` | mutating | `audit_logger`, `member_service` | `member.register` | `MemberRegisterRequest` | `member_id: str` (필수)<br>`member_type: str` (필수)<br>`org: str = "default"`<br>`name: str = ""`<br>`scopes: list[str] = []` | `ante member register` |
| `member.reset_password` | mutating | `audit_logger`, `member_service` | `member.reset_password` | `MemberResetPasswordRequest` | `recovery_key: SecretStr` (필수)<br>`new_password: SecretStr` (필수) | `ante member reset-password` |
| `member.revoke` | mutating | `audit_logger`, `member_service` | `member.revoke` | `MemberRevokeRequest` | `member_id: str` (필수) | `ante member revoke` |
| `member.rotate_token` | mutating | `audit_logger`, `member_service` | `member.rotate_token` | `MemberRotateTokenRequest` | `member_id: str` (필수) | `ante member rotate-token` |
| `member.set_emoji` | mutating | `audit_logger`, `member_service` | `member.set_emoji` | `MemberSetEmojiRequest` | `member_id: str` (필수)<br>`emoji: str` (필수) | `ante member set-emoji` |
| `member.suspend` | mutating | `audit_logger`, `member_service` | `member.suspend` | `MemberSuspendRequest` | `member_id: str` (필수) | `ante member suspend` |
| `member.update_scopes` | mutating | `audit_logger`, `member_service` | `member.update_scopes` | `MemberUpdateScopesRequest` | `member_id: str` (필수)<br>`scopes: list[str]` (필수) | `ante member update-scopes` |
| `rule.update` | mutating | `account`, `audit_logger`, `dynamic_config` | `account.rule.update` | `RuleUpdateRequest` | `account_id: AccountId` (필수)<br>`rule_type: str` (필수)<br>`enabled: bool \| None = null`<br>`params: dict[str, Any] = {}` | `ante rule update` |
| `signal.connect` | read-only | `bot_manager` | — | `SignalConnectRequest` | `key: SecretStr` (필수) | — |
| `strategy.set_status` | mutating | `audit_logger`, `strategy_registry` | `strategy.set_status` | `StrategySetStatusRequest` | `strategy_id: str` (필수)<br>`status: Literal["registered", "adopted", "archived"]` (필수) | `ante strategy set-status` |
| `system.clear_halt` | mutating | `account`, `audit_logger` | `system.clear_halt` | `SystemClearHaltRequest` | — | `ante system clear-halt` |
| `system.halt` | mutating | `account`, `audit_logger` | `system.halt` | `SystemHaltRequest` | `reason: str = "IPC halt"` | `ante system halt` |
| `treasury.allocate` | mutating | `bot_manager`, `treasury_manager` | — | `TreasuryAllocateRequest` | `account_id: AccountId` (필수)<br>`bot_id: str` (필수)<br>`amount: float` (필수) | `ante treasury allocate` |
| `treasury.deallocate` | mutating | `bot_manager`, `treasury_manager` | — | `TreasuryDeallocateRequest` | `account_id: AccountId` (필수)<br>`bot_id: str` (필수)<br>`amount: float` (필수) | `ante treasury deallocate` |
| `treasury.set_balance` | mutating | `audit_logger`, `treasury_manager` | `treasury.set_balance` | `TreasurySetBalanceRequest` | `account_id: AccountId` (필수)<br>`balance: float` (필수) | `ante treasury set-balance` |

## 중첩 요청 모델

| 모델 | 요청 필드 |
|---|---|
| `BotUpdateFields` | `name: str \| None = null`<br>`strategy_id: str \| None = null`<br>`interval_seconds: int \| None = null`<br>`budget: float \| None = null` (`> 0`)<br>`auto_restart: bool \| None = null`<br>`max_restart_attempts: int \| None = null`<br>`restart_cooldown_seconds: int \| None = null`<br>`step_timeout_seconds: int \| None = null`<br>`max_signals_per_step: int \| None = null`<br>`account_id: str \| None = null` |
