# Ante Error Codes

에러 레지스트리(`src/ante/contracts/error_registry.py`)에 등록된 안정 에러 코드를 정리한 문서입니다. 레지스트리 모듈의 `ErrorSpec` 상수 전부와 `EXCEPTION_TO_SPEC`에서 생성합니다.

> 이 문서는 `scripts/generate_error_codes.py`로 자동 생성됩니다. 직접 편집하지 말고 레지스트리를 수정한 뒤 재생성하세요.

> 생성 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_error_codes.py`
> Check 명령: `PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_error_codes.py --check`

- 코드: **157**개 (예외 클래스 매핑 있음 **149** / 없음 **8**)

코드·분류·종료 코드·의미는 그 코드의 `ErrorSpec`의 `code`·`category`·`exit_code`·`description`에서, 예외 클래스는 `EXCEPTION_TO_SPEC`에서 그 코드를 가진 `ErrorSpec`에 연결된 클래스에서 얻습니다. 예외 클래스가 `—`인 코드는 `EXCEPTION_TO_SPEC`에 연결된 클래스가 없고, 의미가 `—`인 코드는 `description`이 비어 있습니다. 분류의 뜻과 명명 규칙은 [error-taxonomy.md](../../specs/contracts/error-taxonomy.md)에서 봅니다.

## 코드

| 코드 | 분류 | 종료 코드 | 예외 클래스 | 의미 |
|---|---|---|---|---|
| `ACCOUNT_ALREADY_DELETED` | `state_conflict` | 1 | `ante.contracts.cli_errors.AccountAlreadyDeletedError` | — |
| `ACCOUNT_ALREADY_EXISTS` | `state_conflict` | 1 | `ante.account.errors.AccountAlreadyExistsError` | — |
| `ACCOUNT_ALREADY_SUSPENDED` | `state_conflict` | 1 | `ante.account.errors.AccountAlreadySuspendedError` | — |
| `ACCOUNT_CREDENTIAL_ENV_NOT_SET` | `validation` | 1 | `ante.contracts.cli_errors.AccountCredentialEnvNotSetError` | `--credential-env`이 참조한 환경변수가 설정되지 않음 |
| `ACCOUNT_CREDENTIAL_FILE_NOT_FOUND` | `validation` | 1 | `ante.contracts.cli_errors.AccountCredentialFileNotFoundError` | `--credential-file`이 가리키는 파일이 존재하지 않음 |
| `ACCOUNT_DELETED` | `state_conflict` | 1 | `ante.account.errors.AccountDeletedError` | — |
| `ACCOUNT_DUPLICATE_CREDENTIAL_KEY` | `validation` | 1 | `ante.contracts.cli_errors.AccountDuplicateCredentialKeyError` | 같은 credential key를 `--credential`/`--credential-env`/`--credential-file` 중 둘 이상 채널로 중복 제공 |
| `ACCOUNT_HAS_ACTIVE_BOTS` | `state_conflict` | 1 | `ante.account.errors.AccountHasActiveBotsError` | — |
| `ACCOUNT_IMMUTABLE_FIELD` | `validation` | 1 | `ante.account.errors.AccountImmutableFieldError` | — |
| `ACCOUNT_INVALID_BROKER_TYPE` | `validation` | 1 | `ante.account.errors.InvalidBrokerTypeError` | — |
| `ACCOUNT_INVALID_STATUS` | `validation` | 1 | `ante.contracts.cli_errors.AccountInvalidStatusError` | — |
| `ACCOUNT_INVALID_TIMEZONE` | `validation` | 1 | `ante.contracts.cli_errors.AccountInvalidTimezoneError` | — |
| `ACCOUNT_MASTER_BOOTSTRAP_FAILED` | `state_conflict` | 1 | `ante.contracts.cli_errors.AccountMasterBootstrapFailedError` | — |
| `ACCOUNT_MISSING_CREDENTIALS` | `validation` | 1 | `ante.account.errors.MissingCredentialsError` | — |
| `ACCOUNT_MISSING_REQUIRED_CREDENTIAL` | `validation` | 1 | `ante.contracts.cli_errors.AccountMissingRequiredCredentialError` | `BrokerPreset.required_credentials`에 정의된 credential key 누락 |
| `ACCOUNT_NOT_FOUND` | `not_found` | 1 | `ante.account.errors.AccountNotFoundError` | — |
| `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER` | `state_conflict` | 1 | `ante.account.errors.AccountStructuralChangeRequiresStoppedServerError` | — |
| `ACCOUNT_SUSPENDED` | `state_conflict` | 1 | `ante.account.errors.AccountSuspendedError` | — |
| `ACCOUNT_TEST_CREATE_FAILED` | `internal` | 1 | `ante.contracts.cli_errors.AccountTestCreateFailedError` | — |
| `ACCOUNT_TEST_INACTIVE` | `state_conflict` | 1 | `ante.contracts.cli_errors.AccountTestInactiveError` | — |
| `ACCOUNT_UNKNOWN_CREDENTIAL_KEY` | `validation` | 1 | `ante.contracts.cli_errors.AccountUnknownCredentialKeyError` | broker preset의 `required_credentials`에 정의되지 않은 credential key 제공 |
| `ALREADY_RUNNING` | `state_conflict` | 1 | `ante.contracts.cli_errors.AlreadyRunningError` | — |
| `APPROVAL_INVALID_STATUS` | `validation` | 1 | `ante.contracts.cli_errors.ApprovalInvalidStatusError` | — |
| `APPROVAL_INVALID_TYPE` | `validation` | 1 | `ante.contracts.cli_errors.ApprovalInvalidTypeError` | — |
| `APPROVAL_NOT_FOUND` | `not_found` | 1 | `ante.approval.errors.ApprovalNotFoundError` | — |
| `APPROVAL_STATUS_CONFLICT` | `state_conflict` | 1 | `ante.approval.errors.ApprovalStatusConflictError` | — |
| `APPROVAL_VALIDATION_ERROR` | `validation` | 1 | `ante.approval.models.ApprovalValidationError` | `approval request --type` 값이 SSOT enum에 없음 |
| `BACKFILL_STOP_REQUESTED` | `state_conflict` | 1 | `ante.contracts.cli_errors.BackfillStopRequestedError` | — |
| `BACKTEST_DATA_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.BacktestDataNotFoundError` | — |
| `BACKTEST_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.BacktestError` | — |
| `BACKTEST_INVALID_EXCHANGE` | `validation` | 1 | `ante.contracts.cli_errors.BacktestInvalidExchangeError` | — |
| `BACKTEST_INVALID_SYMBOL` | `validation` | 1 | `ante.contracts.cli_errors.BacktestInvalidSymbolError` | — |
| `BACKTEST_INVALID_TIMEFRAME` | `validation` | 1 | `ante.contracts.cli_errors.BacktestInvalidTimeframeError` | — |
| `BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED` | `validation` | 1 | `ante.bot.exceptions.BotAccountCredentialsNotConfigured` | — |
| `BOT_ALREADY_EXISTS` | `state_conflict` | 1 | `ante.bot.exceptions.BotAlreadyExistsError` | — |
| `BOT_IMMUTABLE_FIELD` | `validation` | 1 | `ante.bot.exceptions.BotImmutableFieldError` | — |
| `BOT_INVALID_PARAM` | `validation` | 1 | `ante.contracts.cli_errors.BotInvalidParamError` | — |
| `BOT_MISSING_REQUIRED_ACCOUNT` | `validation` | 1 | `ante.contracts.cli_errors.BotMissingRequiredAccountError` | `--account` 생략 시 active 계좌가 0개 또는 2개 이상 |
| `BOT_NOT_ACCEPTING_SIGNALS` | `state_conflict` | 1 | `ante.bot.exceptions.BotNotAcceptingSignals` | — |
| `BOT_NOT_FOUND` | `not_found` | 1 | `ante.bot.exceptions.BotNotFoundError`<br>`ante.contracts.cli_errors.CliBotNotFoundError` | — |
| `BOT_NOT_RUNNING` | `state_conflict` | 1 | `ante.bot.exceptions.BotNotRunning` | 핸드셰이크 게이트 3 — 봇 존재하나 `status != RUNNING` |
| `BOT_SIGNAL_CHANNEL_BUSY` | `state_conflict` | 1 | `ante.bot.exceptions.BotSignalChannelBusy` | bot_id당 단일 active session 정책 — 2번째 `signal.connect` 핸드셰이크 거부 |
| `BOT_STATE_CONFLICT` | `state_conflict` | 1 | `ante.bot.exceptions.BotStateConflict` | — |
| `BOT_STRATEGY_ALREADY_RUNNING` | `state_conflict` | 1 | `ante.bot.exceptions.BotStrategyAlreadyRunningError` | — |
| `BROKER_API_ERROR` | `external` | 1 | `ante.broker.exceptions.APIError` | — |
| `BROKER_AUTH_FAILED` | `auth` | 1 | `ante.broker.exceptions.AuthenticationError` | — |
| `BROKER_CIRCUIT_OPEN` | `service_unavailable` | 1 | `ante.broker.exceptions.CircuitOpenError` | — |
| `BROKER_INVALID_TYPE` | `validation` | 1 | `ante.broker.registry.InvalidBrokerTypeError` | — |
| `BROKER_MODIFY_ORGNO_UNAVAILABLE` | `state_conflict` | 1 | `ante.broker.exceptions.ModifyOrgnoUnavailableError` | — |
| `BROKER_ORDER_NOT_FOUND` | `not_found` | 1 | `ante.broker.exceptions.OrderNotFoundError` | — |
| `BROKER_RATE_LIMITED` | `external` | 1 | `ante.broker.exceptions.RateLimitError` | — |
| `BROKER_RECONNECT_FAILED` | `external` | 1 | `ante.account.errors.BrokerReconnectFailedError` | — |
| `CLI_ALREADY_INITIALIZED` | `state_conflict` | 1 | `ante.contracts.cli_errors.CliAlreadyInitializedError` | — |
| `CLI_CONFIRMATION_REQUIRED` | `validation` | 1 | `ante.contracts.cli_errors.CliConfirmationRequiredError` | 위험 명령에 `--yes`/`--force` 누락 |
| `CLI_INVALID_DATE` | `validation` | 1 | `ante.contracts.cli_errors.CliInvalidDateError` | — |
| `CLI_INVALID_SCHEDULE_TIME` | `validation` | 1 | `ante.contracts.cli_errors.CliInvalidScheduleTimeError` | — |
| `CLI_MISSING_REQUIRED_INPUT` | `validation` | 1 | `ante.contracts.cli_errors.CliMissingRequiredInputError` | 필수 옵션·인자 누락 (도메인 명확 시 도메인 prefix specialize) |
| `CLI_OPTION_CONFLICT` | `validation` | 1 | `ante.contracts.cli_errors.CliOptionConflictError` | 상호 배타적인 옵션을 동시 사용 (period별 전용 옵션을 다른 period와 함께 사용 등) |
| `CLI_USAGE_ERROR` | `validation` | 1 | — | — |
| `CONFIG_INVALID_GENERAL` | `validation` | 1 | `ante.contracts.cli_errors.ConfigInvalidGeneralError` | — |
| `CONFIG_INVALID_GUARD` | `validation` | 1 | `ante.contracts.cli_errors.ConfigInvalidGuardError` | — |
| `CONFIG_INVALID_LOG_LEVEL` | `validation` | 1 | `ante.contracts.cli_errors.ConfigInvalidLogLevelError` | — |
| `CONFIG_INVALID_NICE_VALUE` | `validation` | 1 | `ante.contracts.cli_errors.ConfigInvalidNiceValueError` | — |
| `CONFIG_INVALID_VALUE` | `validation` | 1 | `ante.contracts.cli_errors.ConfigInvalidValueError` | — |
| `CONFIG_KEY_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.ConfigKeyNotFoundError` | — |
| `CONFIG_UNSUPPORTED_KEY` | `validation` | 1 | `ante.contracts.cli_errors.ConfigUnsupportedKeyError` | — |
| `CONFIG_VALIDATION_ERROR` | `validation` | 1 | `ante.config.exceptions.ConfigValidationError` | `config set <key> <value>` 의 key-invariant 위반 (enum SSOT가 정의된 키에 invalid 값, 예 `system.log_level` 이 `_VALID_LOG_LEVELS` 비멤버) |
| `DATASET_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.DatasetNotFoundError` | — |
| `DATA_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.DataError` | — |
| `DATA_INVALID_DATASET_ID` | `validation` | 1 | `ante.contracts.cli_errors.DataInvalidDatasetIdError` | — |
| `DATA_INVALID_FILTER` | `validation` | 1 | `ante.contracts.cli_errors.DataInvalidFilterError` | — |
| `DATA_VALIDATE_INVALID_SYMBOL` | `validation` | 1 | `ante.contracts.cli_errors.DataValidateInvalidSymbolError` | — |
| `DATA_VALIDATE_INVALID_TIMEFRAME` | `validation` | 1 | `ante.contracts.cli_errors.DataValidateInvalidTimeframeError` | — |
| `DB_ENCRYPTION_KEY_ERROR` | `internal` | 1 | `ante.account.crypto.EncryptionKeyError` | — |
| `DB_ENCRYPTION_KEY_INVALID` | `internal` | 1 | `ante.account.crypto.EncryptionKeyInvalidError` | — |
| `DB_ENCRYPTION_KEY_MISSING` | `internal` | 1 | `ante.account.crypto.EncryptionKeyMissingError` | — |
| `EXECUTION_ERROR` | `internal` | 1 | `ante.core.database.ReadOnlyDatabaseError` | — |
| `FEED_INJECT_INVALID_SYMBOL` | `validation` | 1 | `ante.contracts.cli_errors.FeedInjectInvalidSymbolError` | — |
| `FEED_INJECT_INVALID_TIMEFRAME` | `validation` | 1 | `ante.contracts.cli_errors.FeedInjectInvalidTimeframeError` | — |
| `FILE_NOT_FOUND` | `validation` | 1 | `ante.contracts.cli_errors.FeedFileNotFoundError` | — |
| `GUARD_PERMANENTLY_BLOCKED` | `validation` | 1 | `ante.contracts.cli_errors.GuardPermanentlyBlockedError` | — |
| `INSTRUMENT_EMPTY_FILE` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentEmptyFileError` | — |
| `INSTRUMENT_INVALID_EXCHANGE` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentInvalidExchangeError` | — |
| `INSTRUMENT_INVALID_FILE_FORMAT` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentInvalidFileFormatError` | — |
| `INSTRUMENT_INVALID_JSON_SHAPE` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentInvalidJsonShapeError` | — |
| `INSTRUMENT_INVALID_SYMBOL` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentInvalidSymbolError` | — |
| `INSTRUMENT_IO_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.InstrumentIoError` | — |
| `INSTRUMENT_MISSING_COLUMNS` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentMissingColumnsError` | — |
| `INSTRUMENT_SYNC_FAILED` | `external` | 1 | `ante.contracts.cli_errors.InstrumentSyncFailedError` | — |
| `INSTRUMENT_SYNC_SOURCE_UNSUPPORTED` | `validation` | 1 | `ante.contracts.cli_errors.InstrumentSyncSourceUnsupportedError` | — |
| `INVALID_DATE` | `validation` | 1 | `ante.contracts.cli_errors.InvalidDateError` | — |
| `INVALID_DATE_RANGE` | `validation` | 1 | `ante.contracts.cli_errors.InvalidDateRangeError` | 시작일 > 종료일 (inverted date range) 또는 effective 시작일이 미래(`feed run backfill --since` / `[schedule].backfill_since` > today) |
| `INVALID_JSON` | `validation` | 1 | `ante.contracts.cli_errors.InvalidJsonError` | — |
| `INVALID_SIGNAL_KEY` | `validation` | 1 | `ante.bot.exceptions.InvalidSignalKey` | 핸드셰이크 게이트 1 — signal key 검증 실패(`validate_signal_key` → None) |
| `IPC_ERROR` | `internal` | 1 | — | — |
| `IPC_SERVER_NOT_RUNNING` | `service_unavailable` | 1 | `ante.contracts.ipc_client_errors.IPCServerNotRunningError` | — |
| `IPC_TIMEOUT` | `service_unavailable` | 1 | `ante.contracts.ipc_client_errors.IPCClientTimeoutError` | — |
| `MALFORMED_REQUEST` | `validation` | 1 | — | 핸드셰이크 첫 프레임이 비-dict로 decode(`_handle_connection` 가드) |
| `MEMBER_ALREADY_EXISTS` | `state_conflict` | 1 | `ante.member.errors.MemberAlreadyExistsError` | — |
| `MEMBER_ID_RESERVED` | `validation` | 1 | `ante.member.errors.ReservedMemberIdError` | — |
| `MEMBER_INVALID_EMOJI` | `validation` | 1 | `ante.member.errors.MemberInvalidEmojiError` | — |
| `MEMBER_INVALID_RECOVERY_CREDENTIAL` | `auth` | 1 | `ante.member.errors.MemberInvalidRecoveryCredentialError` | — |
| `MEMBER_INVALID_SCOPE` | `permission` | 1 | `ante.member.scopes.InvalidScopeError` | — |
| `MEMBER_MASTER_PROTECTED` | `permission` | 1 | `ante.member.errors.MemberMasterProtectedError` | — |
| `MEMBER_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.CliMemberNotFoundError`<br>`ante.member.errors.MemberNotFoundError` | — |
| `MEMBER_PASSWORD_ENV_NOT_SET` | `validation` | 1 | `ante.contracts.cli_errors.MemberPasswordEnvNotSetError` | `--password-env`/`--new-password-env`이 참조한 환경변수가 설정되지 않음 |
| `MEMBER_PASSWORD_FILE_NOT_FOUND` | `validation` | 1 | `ante.contracts.cli_errors.MemberPasswordFileNotFoundError` | `--password-file`/`--new-password-file`이 가리키는 파일이 존재하지 않음 |
| `MEMBER_STATE_CONFLICT` | `state_conflict` | 1 | `ante.member.errors.MemberStateConflictError` | — |
| `MESSAGE_TOO_LARGE` | `validation` | 1 | — | — |
| `NOT_INITIALIZED` | `state_conflict` | 1 | `ante.contracts.cli_errors.FeedNotInitializedError` | — |
| `PERMISSION_DENIED` | `permission` | 1 | `ante.member.errors.PermissionDeniedError` | — |
| `PID_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.PidNotFoundError` | — |
| `PROCESS_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.ProcessNotFoundError` | — |
| `REPORT_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.ReportError` | — |
| `REPORT_INVALID_STATUS` | `validation` | 1 | `ante.contracts.cli_errors.ReportInvalidStatusError` | — |
| `REPORT_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.ReportNotFoundError` | — |
| `REPORT_VALIDATION_ERROR` | `validation` | 1 | `ante.contracts.cli_errors.ReportValidationError` | report 명령 입력 계약 위반 (제출 리포트 JSON/스키마 위반, `report performance --period monthly --year` 가 비양수 calendar year) |
| `RULE_CONFIG_ERROR` | `validation` | 1 | `ante.rule.exceptions.RuleConfigError` | — |
| `RULE_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.RuleNotFoundError` | — |
| `RULE_UPDATE_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.RuleUpdateError` | — |
| `SERVICE_NOT_CONFIGURED` | `service_unavailable` | 1 | `ante.bot.exceptions.SignalKeyManagerNotConfigured` | — |
| `SERVICE_UNAVAILABLE` | `service_unavailable` | 1 | — | — |
| `SIGNAL_KEY_NOT_SET` | `not_found` | 1 | `ante.contracts.cli_errors.SignalKeyNotSetError` | — |
| `SNAPSHOT_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.SnapshotNotFoundError` | — |
| `STOP_ORDER_MANAGER_STOPPED` | `service_unavailable` | 1 | — | — |
| `STRATEGY_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.CliStrategyError` | — |
| `STRATEGY_FILE_ACCESS_ERROR` | `external` | 1 | `ante.strategy.exceptions.StrategyFileAccessError` | — |
| `STRATEGY_INCOMPATIBLE_EXCHANGE` | `validation` | 1 | `ante.strategy.exceptions.IncompatibleExchangeError` | — |
| `STRATEGY_INVALID_STATUS_TRANSITION` | `state_conflict` | 1 | `ante.contracts.cli_errors.StrategyInvalidStatusTransitionError` | — |
| `STRATEGY_LOAD_ERROR` | `validation` | 1 | `ante.strategy.exceptions.StrategyLoadError` | — |
| `STRATEGY_MISSING_REQUIRED_ACCOUNT` | `validation` | 1 | `ante.contracts.cli_errors.StrategyMissingRequiredAccountError` | — |
| `STRATEGY_NOT_FOUND` | `not_found` | 1 | `ante.strategy.exceptions.StrategyNotFoundError` | — |
| `STRATEGY_VALIDATION_ERROR` | `validation` | 1 | `ante.strategy.exceptions.StrategyValidationError` | strategy 명령 인자(예: `--status`) 값이 SSOT enum에 없음 |
| `STRATEGY_VALIDATION_FAILED` | `validation` | 1 | `ante.contracts.cli_errors.StrategyValidationFailedError` | — |
| `TRADE_ERROR` | `internal` | 1 | `ante.contracts.cli_errors.TradeError` | — |
| `TRADE_NOT_FOUND` | `not_found` | 1 | `ante.contracts.cli_errors.TradeNotFoundError` | — |
| `TREASURY_ALLOCATE_FAILED` | `validation` | 1 | `ante.contracts.cli_errors.TreasuryAllocateFailedError` | — |
| `TREASURY_BOT_NOT_STOPPED` | `state_conflict` | 1 | `ante.treasury.exceptions.BotNotStoppedError` | — |
| `TREASURY_BUDGET_NOT_FOUND` | `not_found` | 1 | `ante.treasury.exceptions.TreasuryBudgetNotFoundError` | — |
| `TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE` | `validation` | 1 | `ante.treasury.exceptions.TreasuryDeallocateExceedsAvailableError` | — |
| `TREASURY_DEALLOCATE_FAILED` | `validation` | 1 | `ante.contracts.cli_errors.TreasuryDeallocateFailedError` | — |
| `TREASURY_INSUFFICIENT_BALANCE` | `validation` | 1 | `ante.treasury.exceptions.TreasuryInsufficientUnallocatedError` | — |
| `TREASURY_INSUFFICIENT_FUNDS` | `validation` | 1 | `ante.treasury.exceptions.InsufficientFundsError` | — |
| `TREASURY_INVALID_AMOUNT` | `validation` | 1 | `ante.treasury.exceptions.TreasuryInvalidAmountError` | — |
| `TREASURY_NOT_CONFIGURED` | `service_unavailable` | 1 | `ante.treasury.exceptions.TreasuryNotConfiguredError` | — |
| `UNKNOWN` | `internal` | 1 | — | — |
| `UNKNOWN_COMMAND` | `internal` | 1 | — | — |
| `UPDATE_CHECK_FAILED` | `external` | 1 | `ante.contracts.cli_errors.UpdateCheckFailedError` | — |
| `UPDATE_INSTALL_FAILED` | `external` | 1 | `ante.contracts.cli_errors.UpdateInstallFailedError` | — |
| `UPDATE_INSUFFICIENT_DISK_SPACE` | `state_conflict` | 1 | `ante.contracts.cli_errors.UpdateInsufficientDiskSpaceError` | — |
| `UPDATE_MIGRATION_FAILED` | `internal` | 1 | `ante.contracts.cli_errors.UpdateMigrationFailedError` | — |
| `UPDATE_ROLLBACK_FAILED` | `internal` | 1 | `ante.contracts.cli_errors.UpdateRollbackFailedError` | — |
| `UPDATE_SERVER_RUNNING` | `state_conflict` | 1 | `ante.contracts.cli_errors.UpdateServerRunningError` | `ante update --force` 없이 서버가 실행 중 |
| `VALIDATION_ERROR` | `validation` | 1 | `ante.account.errors.InvalidBrokerConfigError`<br>`ante.account.errors.InvalidExchangeError`<br>`ante.contracts.cli_errors.FeedInjectValidationError`<br>`ante.contracts.request_errors.RequestValidationError`<br>`ante.core.account_id.InvalidAccountIdError`<br>`ante.core.time.InvalidIsoDateError` | — |
| `auth_failed` | `auth` | 1 | `ante.contracts.cli_errors.CliAuthFailedError` | `ANTE_MEMBER_TOKEN`의 토큰 판정 거부와 DB `connect()` 실패 |
| `auth_required` | `auth` | 1 | `ante.contracts.cli_errors.CliAuthRequiredError` | `@require_auth` 미충족 (`ctx.obj["member"] is None`) |
| `permission_denied` | `permission` | 1 | `ante.contracts.cli_errors.CliPermissionDeniedError` | 인증 OK이나 scope 부족 |
