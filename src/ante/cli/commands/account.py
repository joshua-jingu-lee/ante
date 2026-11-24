"""ante account -- 계좌 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from ante.account.errors import AccountStructuralChangeRequiresStoppedServerError
from ante.account.models import AccountStatus, is_blank_credential
from ante.cli import cold_path
from ante.cli._validators import (
    reject_invalid_account_id,
    reject_invalid_new_account_id,
    validate_nonnegative_finite_amount,
)
from ante.cli.cold_path import ACCOUNT_COLD_PATH_BLOCKED_CODE
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts.cli_errors import (
    AccountAlreadyDeletedError,
    AccountCredentialEnvNotSetError,
    AccountCredentialFileNotFoundError,
    AccountDuplicateCredentialKeyError,
    AccountInvalidStatusError,
    AccountInvalidTimezoneError,
    AccountMissingRequiredCredentialError,
    AccountUnknownCredentialKeyError,
    CliConfirmationRequiredError,
    CliMissingRequiredInputError,
)

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.service import AccountService
    from ante.cli.formatter import OutputFormatter

logger = logging.getLogger(__name__)


@click.group()
def account() -> None:
    """계좌 생성·조회·관리."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


_COLD_PATH_BLOCKED_CODE = ACCOUNT_COLD_PATH_BLOCKED_CODE


def _assert_no_active_runtime(fmt: OutputFormatter) -> None:
    """active Ante runtime이 있으면 cold-path 명령을 차단한다."""
    if cold_path.is_active_runtime(kill=os.kill):
        raise AccountStructuralChangeRequiresStoppedServerError(
            f"{_COLD_PATH_BLOCKED_CODE}: 서버가 실행 중입니다. "
            "cold-path 명령은 서버 정지 상태에서만 실행할 수 있습니다."
        )


@asynccontextmanager
async def _create_account_service(
    ctx: click.Context | None = None,
) -> AsyncIterator[AccountService]:
    """CLI에서 ``AccountService`` 를 생성하는 async context manager."""
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_account_service requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        eventbus = EventBus()
        account_service = AccountService(db=db, eventbus=eventbus)
        await account_service.initialize()
        yield account_service


def mask_value(key: str, value: str) -> str:
    """인증 정보 값을 마스킹한다.

    6자 이하: '****'
    초과: 앞 4자 + '****' + 뒤 2자
    """
    if len(value) <= 6:
        return "****"
    return value[:4] + "****" + value[-2:]


def _get_selectable_broker_types() -> list[str]:
    """BROKER_REGISTRY에 등록된 broker_type만 반환."""
    from ante.broker.registry import BROKER_REGISTRY

    return list(BROKER_REGISTRY.keys())


def _split_key_value(
    raw: str, *, fmt: OutputFormatter, option_label: str, position: int
) -> tuple[str, str]:
    """`key=value` 한 쌍을 파싱하고 형식 위반은 원문 없이 순번으로 알린다."""
    if "=" not in raw:
        raise CliMissingRequiredInputError(
            "CLI_MISSING_REQUIRED_INPUT: "
            f"{option_label} 옵션의 {position}번째 인자가 key=value 형식이 아닙니다."
        )
    key, _, value = raw.partition("=")
    key = key.strip()
    if not key:
        raise CliMissingRequiredInputError(
            "CLI_MISSING_REQUIRED_INPUT: "
            f"{option_label} 옵션의 {position}번째 인자의 key가 비어 있습니다."
        )
    return key, value


def _parse_broker_config_value(raw: str) -> Any:
    """`--broker-config key=value`의 value 부분을 안전하게 파싱한다."""
    lowered = raw.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"

    text = raw.strip()
    try:
        return int(text)
    except ValueError:
        pass

    try:
        Decimal(text)
    except InvalidOperation:
        return raw

    return float(text)


def _resolve_credentials(
    *,
    fmt: OutputFormatter,
    required_keys: list[str],
    direct_pairs: tuple[str, ...],
    env_pairs: tuple[str, ...],
    file_pairs: tuple[str, ...],
) -> dict[str, str]:
    """credential 입력 채널 3개를 합쳐 최종 credentials를 만든다."""
    required_set = set(required_keys)
    seen: dict[str, str] = {}

    def _allowed_key(raw: str, channel: str, position: int) -> tuple[str, str]:
        key, rest = _split_key_value(
            raw, fmt=fmt, option_label=channel, position=position
        )
        if key not in required_set:
            raise AccountUnknownCredentialKeyError(
                "ACCOUNT_UNKNOWN_CREDENTIAL_KEY: "
                f"알 수 없는 credential key입니다 ({channel} 옵션의 "
                f"{position}번째 인자). 허용되는 key: {sorted(required_set)}"
            )
        return key, rest

    def _set_or_dup(key: str, value: str) -> None:
        if key in seen:
            raise AccountDuplicateCredentialKeyError(
                "ACCOUNT_DUPLICATE_CREDENTIAL_KEY: "
                f"credential key {key!r}가 둘 이상 채널로 중복 입력되었습니다."
            )
        seen[key] = value

    for position, raw in enumerate(direct_pairs, start=1):
        key, value = _allowed_key(raw, "--credential", position)
        if is_blank_credential(value):
            raise AccountMissingRequiredCredentialError(
                "ACCOUNT_MISSING_REQUIRED_CREDENTIAL: "
                f"--credential {key}: 값이 비어 있습니다. "
                "credential 값은 비어 있을 수 없습니다."
            )
        _set_or_dup(key, value)

    for position, raw in enumerate(env_pairs, start=1):
        key, env_name = _allowed_key(raw, "--credential-env", position)
        env_name_clean = env_name.strip()
        if not env_name_clean:
            raise CliMissingRequiredInputError(
                "CLI_MISSING_REQUIRED_INPUT: "
                f"--credential-env {key}의 환경변수 이름이 비어 있습니다."
            )
        env_value = os.environ.get(env_name_clean)
        if is_blank_credential(env_value):
            raise AccountCredentialEnvNotSetError(
                "ACCOUNT_CREDENTIAL_ENV_NOT_SET: "
                f"--credential-env 옵션의 {position}번째 인자({key})가 가리키는 "
                "환경변수가 설정되지 않았거나 공란입니다."
            )
        _set_or_dup(key, env_value)

    for position, raw in enumerate(file_pairs, start=1):
        key, path_str = _allowed_key(raw, "--credential-file", position)
        path_clean = path_str.strip()
        if not path_clean:
            raise CliMissingRequiredInputError(
                "CLI_MISSING_REQUIRED_INPUT: "
                f"--credential-file {key}의 파일 경로가 비어 있습니다."
            )
        path = Path(path_clean)
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise AccountCredentialFileNotFoundError(
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: "
                f"--credential-file 옵션의 {position}번째 인자({key})가 가리키는 "
                "파일을 찾을 수 없습니다."
            )
        except (OSError, UnicodeDecodeError):
            raise AccountCredentialFileNotFoundError(
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: "
                f"--credential-file 옵션의 {position}번째 인자({key})가 가리키는 "
                "파일을 읽을 수 없습니다."
            )
        value = content.rstrip("\r\n")
        if is_blank_credential(value):
            raise AccountCredentialFileNotFoundError(
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND: "
                f"--credential-file 옵션의 {position}번째 인자({key})가 가리키는 "
                "파일이 비어 있습니다."
            )
        _set_or_dup(key, value)

    if required_set:
        missing = sorted(required_set - seen.keys())
        if missing:
            raise AccountMissingRequiredCredentialError(
                "ACCOUNT_MISSING_REQUIRED_CREDENTIAL: "
                f"필수 credential 누락: {missing}. "
                "--credential / --credential-env / --credential-file 중 "
                "하나로 모두 제공해야 합니다."
            )

    return seen


def _resolve_broker_config(
    *,
    fmt: OutputFormatter,
    pairs: tuple[str, ...],
) -> dict[str, Any]:
    """`--broker-config key=value` 반복 옵션을 dict로 파싱한다."""
    out: dict[str, Any] = {}
    first_position: dict[str, int] = {}
    for position, raw in enumerate(pairs, start=1):
        key, value_str = _split_key_value(
            raw, fmt=fmt, option_label="--broker-config", position=position
        )
        if key in out:
            raise CliMissingRequiredInputError(
                "CLI_MISSING_REQUIRED_INPUT: "
                f"--broker-config 옵션의 {position}번째 인자의 key가 "
                f"{first_position[key]}번째 인자와 중복됩니다."
            )
        out[key] = _parse_broker_config_value(value_str)
        first_position[key] = position
    return out


def _validate_broker_type(fmt: OutputFormatter, broker_type: str) -> None:
    """`--broker-type`이 BROKER_REGISTRY에 등록된 값인지 확인한다."""
    selectable = _get_selectable_broker_types()
    if broker_type not in selectable:
        raise CliMissingRequiredInputError(
            "CLI_MISSING_REQUIRED_INPUT: "
            f"등록되지 않은 broker_type: {broker_type!r}. "
            f"허용 값: {sorted(selectable)}"
        )


@account.command("create")
@click.option(
    "--broker-type",
    "broker_type",
    required=False,
    default=None,
    help="브로커 타입 (BROKER_REGISTRY 등록 값, 예: test, kis-domestic)",
)
@click.option(
    "--account-id",
    "account_id_opt",
    required=False,
    default=None,
    help="신규 계좌 식별자",
)
@click.option(
    "--name",
    "name_opt",
    required=False,
    default=None,
    help="계좌 표시 이름",
)
@click.option(
    "--trading-mode",
    "trading_mode_opt",
    required=False,
    default=None,
    type=click.Choice(["virtual", "live"], case_sensitive=False),
    help="거래 모드 (virtual 또는 live)",
)
@click.option(
    "--credential",
    "credentials_direct",
    multiple=True,
    metavar="KEY=VALUE",
    help="credential 직접 값 (테스트/로컬 편의용, 비권장 — shell history 노출)",
)
@click.option(
    "--credential-env",
    "credentials_env",
    multiple=True,
    metavar="KEY=ENV_NAME",
    help="credential을 환경변수에서 읽는다 (권장 채널)",
)
@click.option(
    "--credential-file",
    "credentials_file",
    multiple=True,
    metavar="KEY=PATH",
    help="credential을 파일에서 읽는다 (권장 채널)",
)
@click.option(
    "--broker-config",
    "broker_config_pairs",
    multiple=True,
    metavar="KEY=VALUE",
    help="broker-specific 설정 (free-form pass-through, 예: is_paper=true)",
)
@click.option(
    "--market-order-reserve-buffer-rate",
    "market_order_reserve_buffer_rate_opt",
    type=float,
    default=None,
    callback=validate_nonnegative_finite_amount,
    help=(
        "시장가 매수 reserve buffer 비율 (예: 0.005=0.5%). "
        "omit 시 BrokerPreset 기본값을 사용한다. "
        "NaN/Infinity/음수는 거부된다."
    ),
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_create(
    ctx: click.Context,
    broker_type: str | None,
    account_id_opt: str | None,
    name_opt: str | None,
    trading_mode_opt: str | None,
    credentials_direct: tuple[str, ...],
    credentials_env: tuple[str, ...],
    credentials_file: tuple[str, ...],
    broker_config_pairs: tuple[str, ...],
    market_order_reserve_buffer_rate_opt: float | None,
) -> CommandResult:
    """비대화형 계좌 생성 (cold-path 전용).

    필수 옵션: ``--broker-type``, ``--account-id``, ``--name``, ``--trading-mode``.
    credential은 ``BrokerPreset.required_credentials`` 키를 모두 충족해야 하며,
    ``--credential`` / ``--credential-env`` / ``--credential-file``로만 제공한다.
    """
    fmt = get_formatter(ctx)

    _assert_no_active_runtime(fmt)

    from ante.account.models import Account, TradingMode
    from ante.account.presets import BROKER_PRESETS

    required_inputs: dict[str, str | None] = {
        "--broker-type": broker_type,
        "--account-id": account_id_opt,
        "--name": name_opt,
        "--trading-mode": trading_mode_opt,
    }
    missing = [k for k, v in required_inputs.items() if v is None or v == ""]
    if missing:
        raise CliMissingRequiredInputError(
            f"CLI_MISSING_REQUIRED_INPUT: 필수 옵션 누락: {missing}"
        )

    assert broker_type is not None
    assert account_id_opt is not None
    assert name_opt is not None
    assert trading_mode_opt is not None

    account_id_opt = reject_invalid_new_account_id(
        account_id_opt, fmt, context="cli.account.create"
    )

    _validate_broker_type(fmt, broker_type)

    preset = BROKER_PRESETS.get(broker_type)
    if preset is None:
        raise CliMissingRequiredInputError(
            f"CLI_MISSING_REQUIRED_INPUT: broker preset 미정의: {broker_type!r}"
        )

    credentials = _resolve_credentials(
        fmt=fmt,
        required_keys=list(preset.required_credentials),
        direct_pairs=credentials_direct,
        env_pairs=credentials_env,
        file_pairs=credentials_file,
    )

    broker_config = _resolve_broker_config(fmt=fmt, pairs=broker_config_pairs)

    trading_mode = (
        TradingMode.VIRTUAL
        if trading_mode_opt.lower() == "virtual"
        else TradingMode.LIVE
    )

    if market_order_reserve_buffer_rate_opt is None:
        market_order_buffer = preset.market_order_reserve_buffer_rate
    else:
        market_order_buffer = Decimal(str(market_order_reserve_buffer_rate_opt))

    new_account = Account(
        account_id=account_id_opt,
        name=name_opt,
        exchange=preset.exchange,
        currency=preset.currency,
        timezone=preset.timezone,
        trading_hours_start=preset.trading_hours_start,
        trading_hours_end=preset.trading_hours_end,
        trading_mode=trading_mode,
        broker_type=broker_type,
        credentials=credentials,
        broker_config=broker_config,
        buy_commission_rate=preset.buy_commission_rate,
        sell_commission_rate=preset.sell_commission_rate,
        market_order_reserve_buffer_rate=market_order_buffer,
    )

    async def _do_create() -> Account:
        async with _create_account_service(ctx) as svc:
            return await svc.create(new_account)

    created = _run(_do_create())

    return CommandResult(
        message=f'계좌 "{created.account_id}" 생성 완료 '
        f"({created.exchange} / {created.currency} / {created.broker_type})",
        data={
            "account_id": created.account_id,
            "exchange": created.exchange,
            "currency": created.currency,
            "broker_type": created.broker_type,
        },
    )


@account.command("list")
@click.option(
    "--status",
    "status_filter",
    default=None,
    help="상태 필터 (active/suspended/deleted)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_list(ctx: click.Context, status_filter: str | None) -> CommandResult:
    """계좌 목록 조회."""
    if status_filter is not None and status_filter not in {
        s.value for s in AccountStatus
    }:
        raise AccountInvalidStatusError(
            f"잘못된 status 값: {status_filter!r}. "
            f"허용값: {sorted(s.value for s in AccountStatus)}"
        )

    async def _do_list() -> list[dict[str, Any]]:
        async with _create_account_service(ctx) as svc:
            status = AccountStatus(status_filter) if status_filter else None
            accounts = await svc.list(status=status)
            return [_account_to_row(a) for a in accounts]

    rows = _run(_do_list())

    if not rows:
        message = "등록된 계좌가 없습니다."
        empty = {"message": message, "accounts": []}
        return CommandResult(data=empty, text=(message,))

    columns = ["account_id", "name", "exchange", "currency", "broker_type", "status"]
    return CommandResult(
        data={"accounts": rows}, text=tuple(table_lines(rows, columns))
    )


@account.command("info")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_info(ctx: click.Context, account_id: str) -> CommandResult:
    """계좌 상세 정보 조회."""
    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.info"
    )

    async def _do_info() -> dict[str, Any]:
        async with _create_account_service(ctx) as svc:
            acct = await svc.get(validated_account_id)
            return _account_to_detail(acct)

    detail = _run(_do_info())

    return CommandResult(data=detail, text=_account_detail_lines(detail))


@account.command("suspend")
@click.argument("account_id")
@click.option("--reason", default="CLI 수동 정지", help="정지 사유")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_suspend(ctx: click.Context, account_id: str, reason: str) -> CommandResult:
    """계좌 거래 정지."""
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.suspend"
    )

    _run(
        ipc_send(
            "account.suspend",
            {"account_id": validated_account_id, "reason": reason},
            actor=member_id,
        )
    )

    return CommandResult(message=f'계좌 "{validated_account_id}" 정지 완료')


@account.command("activate")
@click.argument("account_id")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_activate(ctx: click.Context, account_id: str) -> CommandResult:
    """계좌 활성화."""
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.activate"
    )

    _run(
        ipc_send(
            "account.activate",
            {"account_id": validated_account_id},
            actor=member_id,
        )
    )

    return CommandResult(message=f'계좌 "{validated_account_id}" 활성화 완료')


@account.command("delete")
@click.argument("account_id")
@click.option(
    "--yes", "skip_confirm", is_flag=True, default=False, help="확인 없이 삭제"
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_delete(
    ctx: click.Context, account_id: str, skip_confirm: bool
) -> CommandResult:
    """계좌 삭제 (소프트 딜리트, cold-path 전용).

    1.0 정책: account.delete는 IPC runtime command가 아니다. active Ante
    runtime이 있으면 차단되며, 서버 정지 상태에서만 AccountService.delete를
    직접 호출한다. 소속 봇이 살아 있는 계좌는 AccountHasActiveBotsError로
    차단된다(orphan bot 무결성).

    SSOT: ``--yes`` 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED``로 실패
    (`docs/specs/cli/02-design-decisions.md` 위험 명령 확인 방식 표).
    """
    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    if not skip_confirm:
        raise CliConfirmationRequiredError(
            "CLI_CONFIRMATION_REQUIRED: "
            f'계좌 "{account_id}" 삭제는 확인이 필요합니다. --yes를 명시해 주세요.'
        )

    _assert_no_active_runtime(fmt)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.delete"
    )

    from ante.account.errors import AccountDeletedError

    async def _do_delete() -> None:
        async with _create_account_service(ctx) as svc:
            await svc.delete(validated_account_id, deleted_by=member_id)

    try:
        _run(_do_delete())
    except AccountDeletedError as e:
        raise AccountAlreadyDeletedError(str(e)) from e

    return CommandResult(message=f'계좌 "{validated_account_id}" 삭제 완료')


@account.command("credentials")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_credentials(ctx: click.Context, account_id: str) -> CommandResult:
    """인증 정보 조회 (마스킹)."""
    fmt = get_formatter(ctx)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.credentials"
    )

    async def _do_credentials() -> dict[str, str]:
        async with _create_account_service(ctx) as svc:
            acct = await svc.get(validated_account_id)
            return {k: mask_value(k, v) for k, v in acct.credentials.items()}

    masked = _run(_do_credentials())

    if not masked:
        message = "등록된 인증 정보가 없습니다."
        empty = {"message": message, "credentials": {}}
        return CommandResult(data=empty, text=(message,))

    return CommandResult(
        data={"account_id": account_id, "credentials": masked},
        text=(
            f"\n인증 정보 ({account_id})",
            "-" * 35,
            *(f"  {key.upper():14s}: {value}" for key, value in masked.items()),
        ),
    )


@account.command("set-credentials")
@click.argument("account_id")
@click.option(
    "--credential",
    "credentials_direct",
    multiple=True,
    metavar="KEY=VALUE",
    help="credential 직접 값 (테스트/로컬 편의용, 비권장 — shell history 노출)",
)
@click.option(
    "--credential-env",
    "credentials_env",
    multiple=True,
    metavar="KEY=ENV_NAME",
    help="credential을 환경변수에서 읽는다 (권장 채널)",
)
@click.option(
    "--credential-file",
    "credentials_file",
    multiple=True,
    metavar="KEY=PATH",
    help="credential을 파일에서 읽는다 (권장 채널)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_set_credentials(
    ctx: click.Context,
    account_id: str,
    credentials_direct: tuple[str, ...],
    credentials_env: tuple[str, ...],
    credentials_file: tuple[str, ...],
) -> CommandResult:
    """인증 정보 재설정 (비대화형, cold-path 전용).

    SSOT: ``BrokerPreset.required_credentials``를 **모두** 충족해야 하며,
    부분 갱신은 허용하지 않는다(`docs/specs/cli/03-commands.md`
    `account set-credentials` 입력 계약).
    BREAKING CHANGE: 이전 ``--app-key`` / ``--app-secret`` 옵션은 제거되었다.
    ``--credential`` / ``--credential-env`` / ``--credential-file``를 사용한다.
    """
    fmt = get_formatter(ctx)

    _assert_no_active_runtime(fmt)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.set-credentials"
    )

    from ante.account.presets import BROKER_PRESETS

    async def _do_set_credentials() -> CommandResult:
        async with _create_account_service(ctx) as svc:
            acct = await svc.get(validated_account_id)
            preset = BROKER_PRESETS.get(acct.broker_type)
            if not preset or not preset.required_credentials:
                any_input = bool(
                    credentials_direct or credentials_env or credentials_file
                )
                if any_input:
                    raise AccountUnknownCredentialKeyError(
                        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY: "
                        f"브로커 '{acct.broker_type}'은 "
                        "credentials를 요구하지 않습니다."
                    )
                msg = f"브로커 '{acct.broker_type}'에는 인증 정보가 필요하지 않습니다."
                payload = {"message": msg}
                return CommandResult(data=payload, text=(msg,))

            if not (credentials_direct or credentials_env or credentials_file):
                required = list(preset.required_credentials)
                raise AccountMissingRequiredCredentialError(
                    "ACCOUNT_MISSING_REQUIRED_CREDENTIAL: "
                    "credential 옵션이 누락되었습니다. "
                    "--credential / --credential-env / --credential-file "
                    f"중 하나로 required keys {required}를 모두 제공해야 합니다."
                )

            new_credentials = _resolve_credentials(
                fmt=fmt,
                required_keys=list(preset.required_credentials),
                direct_pairs=credentials_direct,
                env_pairs=credentials_env,
                file_pairs=credentials_file,
            )

            await svc.update(validated_account_id, credentials=new_credentials)
            done = f'계좌 "{validated_account_id}" 인증 정보 재설정 완료'
            return CommandResult(message=done, text=(done,))

    result: CommandResult = _run(_do_set_credentials())
    return result


@account.command("repair-timezone")
@click.argument("account_id")
@click.argument("new_timezone")
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_repair_timezone(
    ctx: click.Context, account_id: str, new_timezone: str
) -> CommandResult:
    """legacy invalid IANA timezone 계좌를 복구한다 (cold-path 전용).

    ``_row_to_account`` 가 stored invalid timezone 을 보존하면서
    ``Account.timezone_invalid`` marker 를 노출한 row 를 운영자가 명시한
    valid IANA timezone 으로 갱신한다. 내부적으로
    ``AccountService.repair_timezone`` → ``update(timezone=...)`` 으로
    위임하며, cold-path 의미론 (서버 정지 필요) 은 본 CLI 와 service
    boundary 양쪽에서 차단한다.

    실패 코드:

    - ``ACCOUNT_RUNTIME_ACTIVE`` 또는
      ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER``: 서버 실행 중
      차단 (cold-path).
    - ``ACCOUNT_INVALID_TIMEZONE``: ``new_timezone`` 이 IANA 등록 누락.
    - ``ACCOUNT_NOT_FOUND``: ``account_id`` 가 존재하지 않음.
    """
    fmt = get_formatter(ctx)

    _assert_no_active_runtime(fmt)

    validated_account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.account.repair-timezone"
    )

    from ante.account.errors import AccountDeletedError

    async def _do_repair() -> Account:
        async with _create_account_service(ctx) as svc:
            return await svc.repair_timezone(validated_account_id, new_timezone)

    try:
        repaired = _run(_do_repair())
    except ValueError as e:
        raise AccountInvalidTimezoneError(
            f"ACCOUNT_INVALID_TIMEZONE: invalid IANA timezone: {new_timezone!r} — {e}"
        )
    except AccountDeletedError as e:
        raise AccountAlreadyDeletedError(str(e)) from e

    return CommandResult(
        message=f'계좌 "{repaired.account_id}" timezone 복구 완료 '
        f"({repaired.timezone})",
        data={
            "code": "ACCOUNT_REPAIR_TIMEZONE_OK",
            "account_id": repaired.account_id,
            "timezone": repaired.timezone,
            "timezone_invalid": repaired.timezone_invalid,
        },
    )


def _account_to_row(acct: Account) -> dict[str, Any]:
    """Account를 테이블 행 dict로 변환."""
    return {
        "account_id": acct.account_id,
        "name": acct.name,
        "exchange": acct.exchange,
        "currency": acct.currency,
        "broker_type": acct.broker_type,
        "status": acct.status.value,
    }


def _account_to_detail(acct: Account) -> dict[str, Any]:
    """Account를 상세 dict로 변환."""
    return {
        "account_id": acct.account_id,
        "name": acct.name,
        "exchange": acct.exchange,
        "currency": acct.currency,
        "broker_type": acct.broker_type,
        "trading_mode": acct.trading_mode.value,
        "buy_commission_rate": str(acct.buy_commission_rate),
        "sell_commission_rate": str(acct.sell_commission_rate),
        "market_order_reserve_buffer_rate": str(acct.market_order_reserve_buffer_rate),
        "status": acct.status.value,
        "timezone": acct.timezone,
        "trading_hours": f"{acct.trading_hours_start}-{acct.trading_hours_end}",
        "created_at": str(acct.created_at) if acct.created_at else "",
    }


def _account_detail_lines(detail: dict[str, Any]) -> tuple[str, ...]:
    """텍스트 모드의 계좌 상세 줄."""
    lines = ["\n계좌 정보", "-" * 35]
    labels = {
        "account_id": "ID",
        "name": "이름",
        "exchange": "거래소",
        "currency": "통화",
        "broker_type": "브로커",
        "trading_mode": "거래 모드",
        "buy_commission_rate": "매수 수수료",
        "sell_commission_rate": "매도 수수료",
        "market_order_reserve_buffer_rate": "시장가 매수 버퍼",
        "status": "상태",
        "timezone": "시간대",
        "trading_hours": "거래 시간",
        "created_at": "생성일",
    }
    pct_keys = (
        "buy_commission_rate",
        "sell_commission_rate",
        "market_order_reserve_buffer_rate",
    )
    for key, label in labels.items():
        value = detail.get(key, "")
        if key in pct_keys and value not in ("", None):
            try:
                pct = float(value) * 100
                value = f"{pct:.3f}%"
            except (ValueError, TypeError):
                pass
        lines.append(f"  {label:14s}: {value}")
    return tuple(lines)
