"""ante account -- 계좌 관리 커맨드.

비대화형 입력 계약(`docs/specs/cli/02-design-decisions.md` — 비대화형 입력 계약)을
구현한다. `account create`, `account set-credentials`, `account delete`는
stdin prompt/confirm을 사용하지 않고, 옵션/환경변수/파일/명시적 `--yes`로만
입력을 받는다. 누락 입력은 prompt 없이 구조화된 에러로 종료한다.

에러 코드 SSOT는 `docs/specs/cli/02-design-decisions.md`의 표준 에러 코드 표를
따른다(`ACCOUNT_MISSING_REQUIRED_CREDENTIAL`, `ACCOUNT_UNKNOWN_CREDENTIAL_KEY`,
`ACCOUNT_DUPLICATE_CREDENTIAL_KEY`, `ACCOUNT_CREDENTIAL_ENV_NOT_SET`,
`ACCOUNT_CREDENTIAL_FILE_NOT_FOUND`, `CLI_MISSING_REQUIRED_INPUT`,
`CLI_CONFIRMATION_REQUIRED`).
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import click

from ante.cli.cold_path import (
    ACCOUNT_COLD_PATH_BLOCKED_CODE,
    assert_no_active_runtime,
)
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

if TYPE_CHECKING:
    from ante.account.models import Account
    from ante.account.service import AccountService
    from ante.cli.formatter import OutputFormatter
    from ante.core.database import Database

logger = logging.getLogger(__name__)


@click.group()
def account() -> None:
    """계좌 생성·조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


# ── cold-path active runtime guard ──────────────────────────────


# Cold-path 차단 응답 코드. SSOT는 docs/specs/cli/03-commands.md 117-118줄,
# docs/specs/account/09-cli.md 49-54줄.
_COLD_PATH_BLOCKED_CODE = ACCOUNT_COLD_PATH_BLOCKED_CODE


def _assert_no_active_runtime(fmt: OutputFormatter) -> None:
    """active Ante runtime이 있으면 cold-path 명령을 차단한다.

    공유 헬퍼는 Refs #1157/#1160의 canonical config-dir, PID/socket, startup
    marker 규칙을 사용한다. 이 래퍼는 기존 account 테스트와 import 경로를
    유지하기 위한 호환 계층이다.
    """
    # ``kill=os.kill``은 기존 테스트가 ``ante.cli.commands.account.os.kill``을
    # monkeypatch하던 계약을 유지하기 위한 호환 주입점이다.
    assert_no_active_runtime(
        fmt,
        code=_COLD_PATH_BLOCKED_CODE,
        message=(
            "서버가 실행 중입니다. "
            "cold-path 명령은 서버 정지 상태에서만 실행할 수 있습니다."
        ),
        kill=os.kill,
    )


async def _create_account_service() -> tuple[AccountService, Database]:
    """CLI에서 AccountService를 생성하는 헬퍼."""
    from ante.account.service import AccountService
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    return account_service, db


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


# ── 비대화형 입력 helper ─────────────────────────────────────────


def _exit_with_error(fmt: OutputFormatter, code: str, message: str) -> NoReturn:
    """구조화된 에러를 출력하고 SystemExit(1)으로 종료한다.

    text/json 양쪽 표면에 에러 코드가 일관되게 노출되도록 한다.
    JSON 모드(`OutputFormatter.is_json`)에서는 `OutputFormatter.error`가
    `{"status": "error", "code": ..., "message": ...}` 형식으로 dump한다.
    text 모드에서는 `OutputFormatter.error`가 message만 출력하므로,
    사람/Agent가 같은 표면에서 코드를 읽을 수 있도록 message 본문에
    `CODE: ` prefix를 덧붙인다(cold-path 헬퍼
    ``cold_path.assert_no_active_runtime``과 동일 contract).

    반환 타입은 ``NoReturn``이므로, 호출 후 후속 코드는 mypy 관점에서
    unreachable하다(env/file 분기에서 None narrowing 등).
    """
    fmt.error(f"{code}: {message}", code=code)
    raise SystemExit(1)


def _split_key_value(
    raw: str, *, fmt: OutputFormatter, option_label: str
) -> tuple[str, str]:
    """`key=value` 한 쌍을 파싱한다. 형식 위반 시 즉시 종료.

    `=`가 한 번도 등장하지 않거나, key가 공란이면 `CLI_MISSING_REQUIRED_INPUT`
    으로 종료한다. 값에는 `=`가 추가로 들어와도 그대로 유지한다(쉘 인자
    이스케이프와의 호환을 위해 첫 `=`만 분리자로 본다).
    """
    if "=" not in raw:
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            f"{option_label} 옵션은 key=value 형식이어야 합니다: {raw!r}",
        )
    key, _, value = raw.partition("=")
    key = key.strip()
    if not key:
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            f"{option_label} 옵션의 key가 비어 있습니다: {raw!r}",
        )
    return key, value


def _parse_broker_config_value(raw: str) -> Any:
    """`--broker-config key=value`의 value 부분을 안전하게 파싱한다.

    1.0 free-form pass-through 정책(`docs/specs/cli/03-commands.md`
    `--broker-config` 정책 절)을 따른다. 알 수 없는 key는 검증하지 않으며,
    값만 bool/int/float/str 순서로 변환한다. broker adapter는 자기에게
    필요한 known key만 읽고 나머지는 silent ignore할 수 있다.

    소수 값(`"1.5"`, `"0.00015"` 등)은 `float`로 변환한다. KIS adapter는
    `config.get("retry.backoff_base_seconds", ...)`처럼 numeric 값을 직접
    소비하므로(`src/ante/broker/kis.py`), 문자열로 저장하면 후속 산술
    연산에서 `TypeError`가 발생한다. 또한 `Account.broker_config`는
    `service.create()`에서 `json.dumps(...)`로 직렬화되므로(`Decimal`은
    JSON serializable이 아님) `float`이 안전한 native JSON 타입이다.
    """
    lowered = raw.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"

    text = raw.strip()
    # int 우선 시도 (음수 포함). bool 다음 순서로 평가하여
    # "0"/"1" 같은 값이 bool로 잘못 변환되는 회귀를 막는다.
    try:
        return int(text)
    except ValueError:
        pass

    # Decimal로 파싱 가능하면 float 반환. Decimal로 일단 검증한 뒤
    # ``float(text)``로 변환하여 KIS adapter의 `float` 소비 계약과
    # `json.dumps`의 native JSON 타입 요구를 동시에 만족시킨다.
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
    """credential 입력 채널 3개를 합쳐 최종 credentials를 만든다.

    SSOT(`docs/specs/cli/02-design-decisions.md` 표):
    - 알 수 없는 key → ``ACCOUNT_UNKNOWN_CREDENTIAL_KEY``
    - 동일 key 중복 채널 → ``ACCOUNT_DUPLICATE_CREDENTIAL_KEY``
    - env 미설정/공란 → ``ACCOUNT_CREDENTIAL_ENV_NOT_SET``
    - file 부재/읽기 실패/공란 → ``ACCOUNT_CREDENTIAL_FILE_NOT_FOUND``
    - 누락된 required key → ``ACCOUNT_MISSING_REQUIRED_CREDENTIAL``

    required_keys가 빈 리스트(예: 향후 broker preset)면 모든 입력이 unknown
    이 되므로, 이 경우 credentials는 비어 있어야 한다(빈 dict 반환).
    """
    required_set = set(required_keys)
    seen: dict[str, str] = {}

    def _set_or_dup(key: str, value: str, channel: str) -> None:
        if required_set and key not in required_set:
            _exit_with_error(
                fmt,
                "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
                f"알 수 없는 credential key: {key!r} ({channel}). "
                f"허용되는 key: {sorted(required_set)}",
            )
        if key in seen:
            _exit_with_error(
                fmt,
                "ACCOUNT_DUPLICATE_CREDENTIAL_KEY",
                f"credential key {key!r}가 둘 이상 채널로 중복 입력되었습니다.",
            )
        seen[key] = value

    for raw in direct_pairs:
        key, value = _split_key_value(raw, fmt=fmt, option_label="--credential")
        # 직접 채널도 env/file과 일관되게 빈 값(공란)을 거부한다.
        # 빈 credential은 broker adapter 인증에 사용할 수 없는 unusable 값이며,
        # `--credential app_key=` 같은 입력은 사용자 실수일 가능성이 매우 높다.
        # SSOT: docs/specs/cli/02-design-decisions.md 표준 에러 코드 표 —
        # ``ACCOUNT_MISSING_REQUIRED_CREDENTIAL``.
        if value == "":
            _exit_with_error(
                fmt,
                "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
                (
                    f"--credential {key}: 값이 비어 있습니다. "
                    "credential 값은 비어 있을 수 없습니다."
                ),
            )
        _set_or_dup(key, value, "--credential")

    for raw in env_pairs:
        key, env_name = _split_key_value(raw, fmt=fmt, option_label="--credential-env")
        env_name_clean = env_name.strip()
        if not env_name_clean:
            _exit_with_error(
                fmt,
                "CLI_MISSING_REQUIRED_INPUT",
                f"--credential-env {key}의 환경변수 이름이 비어 있습니다.",
            )
        env_value = os.environ.get(env_name_clean)
        if env_value is None or env_value == "":
            _exit_with_error(
                fmt,
                "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
                (
                    f"--credential-env {key}={env_name_clean}: "
                    "환경변수가 설정되지 않았거나 공란입니다."
                ),
            )
        _set_or_dup(key, env_value, "--credential-env")

    for raw in file_pairs:
        key, path_str = _split_key_value(raw, fmt=fmt, option_label="--credential-file")
        path_clean = path_str.strip()
        if not path_clean:
            _exit_with_error(
                fmt,
                "CLI_MISSING_REQUIRED_INPUT",
                f"--credential-file {key}의 파일 경로가 비어 있습니다.",
            )
        path = Path(path_clean)
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            _exit_with_error(
                fmt,
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
                f"--credential-file {key}={path_clean}: 파일을 찾을 수 없습니다.",
            )
        except OSError as exc:
            _exit_with_error(
                fmt,
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
                (
                    f"--credential-file {key}={path_clean}: "
                    f"파일을 읽을 수 없습니다 ({exc})."
                ),
            )
        # 파일 끝의 단일 개행은 제거하되, 그 외 공백·내용은 보존한다.
        # (PEM/JSON 등 의미 있는 줄바꿈이 포함될 수 있음을 가정하지 않는다 —
        # credential value는 단일 토큰이라는 1.0 가정.)
        value = content.rstrip("\r\n")
        if value == "":
            _exit_with_error(
                fmt,
                "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
                f"--credential-file {key}={path_clean}: 파일이 비어 있습니다.",
            )
        _set_or_dup(key, value, "--credential-file")

    if required_set:
        missing = sorted(required_set - seen.keys())
        if missing:
            _exit_with_error(
                fmt,
                "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
                (
                    f"필수 credential 누락: {missing}. "
                    "--credential / --credential-env / --credential-file 중 "
                    "하나로 모두 제공해야 합니다."
                ),
            )

    return seen


def _resolve_broker_config(
    *,
    fmt: OutputFormatter,
    pairs: tuple[str, ...],
) -> dict[str, Any]:
    """`--broker-config key=value` 반복 옵션을 dict로 파싱한다.

    1.0 free-form pass-through 정책: known key 검증 없이 그대로 통과시킨다.
    같은 key가 두 번 들어오면 명시적으로 거부한다(silent overwrite는 입력
    오류의 흔적을 가리므로). 값은 bool/int/str 순으로 안전하게 파싱한다.
    """
    out: dict[str, Any] = {}
    for raw in pairs:
        key, value_str = _split_key_value(raw, fmt=fmt, option_label="--broker-config")
        if key in out:
            _exit_with_error(
                fmt,
                "CLI_MISSING_REQUIRED_INPUT",
                f"--broker-config key {key!r}가 중복 입력되었습니다.",
            )
        out[key] = _parse_broker_config_value(value_str)
    return out


def _validate_broker_type(fmt: OutputFormatter, broker_type: str) -> None:
    """`--broker-type`이 BROKER_REGISTRY에 등록된 값인지 확인한다.

    SSOT: `docs/specs/cli/03-commands.md` Broker 책임 경계 — `BROKER_REGISTRY`가
    `broker_type` 문자열 → 어댑터 매핑의 SSOT.
    """
    selectable = _get_selectable_broker_types()
    if broker_type not in selectable:
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            (
                f"등록되지 않은 broker_type: {broker_type!r}. "
                f"허용 값: {sorted(selectable)}"
            ),
        )


# ── create ──────────────────────────────────────


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
    help=(
        "시장가 매수 reserve buffer 비율 (예: 0.005=0.5%). "
        "omit 시 BrokerPreset 기본값을 사용한다 (#1333)."
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
) -> None:
    """비대화형 계좌 생성 (cold-path 전용).

    필수 옵션: ``--broker-type``, ``--account-id``, ``--name``, ``--trading-mode``.
    credential은 ``BrokerPreset.required_credentials`` 키를 모두 충족해야 하며,
    ``--credential`` / ``--credential-env`` / ``--credential-file``로만 제공한다.
    """
    fmt = get_formatter(ctx)

    # cold-path: active runtime이 있으면 진입 직후 차단
    _assert_no_active_runtime(fmt)

    from ante.account.models import Account, TradingMode
    from ante.account.presets import BROKER_PRESETS

    # 1) 필수 옵션 검증
    required_inputs: dict[str, str | None] = {
        "--broker-type": broker_type,
        "--account-id": account_id_opt,
        "--name": name_opt,
        "--trading-mode": trading_mode_opt,
    }
    missing = [k for k, v in required_inputs.items() if v is None or v == ""]
    if missing:
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            f"필수 옵션 누락: {missing}",
        )

    # mypy: 위 검증으로 모두 not None
    assert broker_type is not None
    assert account_id_opt is not None
    assert name_opt is not None
    assert trading_mode_opt is not None

    # 2) broker_type enum 검증 (BROKER_REGISTRY SSOT)
    _validate_broker_type(fmt, broker_type)

    # 3) BrokerPreset 조회 — required_credentials의 SSOT
    preset = BROKER_PRESETS.get(broker_type)
    if preset is None:
        # BROKER_REGISTRY에는 있지만 BROKER_PRESETS에 없는 경우 — 계약 불일치.
        # 1.0 범위에서는 두 dict 모두 동일 keys를 가지지만, 방어적으로 가드한다.
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            f"broker preset 미정의: {broker_type!r}",
        )

    # 4) credential 해석
    credentials = _resolve_credentials(
        fmt=fmt,
        required_keys=list(preset.required_credentials),
        direct_pairs=credentials_direct,
        env_pairs=credentials_env,
        file_pairs=credentials_file,
    )

    # 5) broker_config 해석 (free-form pass-through)
    broker_config = _resolve_broker_config(fmt=fmt, pairs=broker_config_pairs)

    # 6) trading_mode 매핑
    trading_mode = (
        TradingMode.VIRTUAL
        if trading_mode_opt.lower() == "virtual"
        else TradingMode.LIVE
    )

    # market_order_reserve_buffer_rate: 옵션 omit 시 preset 기본값을 그대로
    # 사용하고, 명시된 경우 ``Decimal(str(...))``로 정밀도를 보존한다 (#1333).
    if market_order_reserve_buffer_rate_opt is None:
        market_order_buffer = preset.market_order_reserve_buffer_rate
    else:
        market_order_buffer = Decimal(str(market_order_reserve_buffer_rate_opt))

    # 7) Account 생성
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
        svc, db = await _create_account_service()
        try:
            return await svc.create(new_account)
        finally:
            await db.close()

    try:
        created = _run(_do_create())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(
        f'계좌 "{created.account_id}" 생성 완료 '
        f"({created.exchange} / {created.currency} / {created.broker_type})",
        data={
            "account_id": created.account_id,
            "exchange": created.exchange,
            "currency": created.currency,
            "broker_type": created.broker_type,
        },
    )


# ── list ──────────────────────────────────────


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
def account_list(ctx: click.Context, status_filter: str | None) -> None:
    """계좌 목록 조회."""
    fmt = get_formatter(ctx)

    from ante.account.models import AccountStatus

    async def _do_list() -> list[dict]:
        svc, db = await _create_account_service()
        try:
            status = AccountStatus(status_filter) if status_filter else None
            accounts = await svc.list(status=status)
            return [_account_to_row(a) for a in accounts]
        finally:
            await db.close()

    try:
        rows = _run(_do_list())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if not rows:
        fmt.output({"message": "등록된 계좌가 없습니다.", "accounts": []})
        return

    if fmt.is_json:
        fmt.output({"accounts": rows})
    else:
        fmt.table(
            rows,
            ["account_id", "name", "exchange", "currency", "broker_type", "status"],
        )


# ── info ──────────────────────────────────────


@account.command("info")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_info(ctx: click.Context, account_id: str) -> None:
    """계좌 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _do_info() -> dict:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            return _account_to_detail(acct)
        finally:
            await db.close()

    try:
        detail = _run(_do_info())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(detail)
    else:
        _print_account_detail(detail)


# ── suspend ──────────────────────────────────────


@account.command("suspend")
@click.argument("account_id")
@click.option("--reason", default="CLI 수동 정지", help="정지 사유")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_suspend(ctx: click.Context, account_id: str, reason: str) -> None:
    """계좌 거래 정지."""
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    try:
        _run(
            ipc_send(
                "account.suspend",
                {"account_id": account_id, "reason": reason},
                actor=member_id,
            )
        )
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 정지 완료')


# ── activate ──────────────────────────────────────


@account.command("activate")
@click.argument("account_id")
@click.pass_context
@require_auth
@require_scope("account:write")
def account_activate(ctx: click.Context, account_id: str) -> None:
    """계좌 활성화."""
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    member_id = get_member_id(ctx)

    try:
        _run(
            ipc_send(
                "account.activate",
                {"account_id": account_id},
                actor=member_id,
            )
        )
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 활성화 완료')


# ── delete ──────────────────────────────────────


@account.command("delete")
@click.argument("account_id")
@click.option(
    "--yes", "skip_confirm", is_flag=True, default=False, help="확인 없이 삭제"
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_delete(ctx: click.Context, account_id: str, skip_confirm: bool) -> None:
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
        _exit_with_error(
            fmt,
            "CLI_CONFIRMATION_REQUIRED",
            f'계좌 "{account_id}" 삭제는 확인이 필요합니다. --yes를 명시해 주세요.',
        )

    # cold-path: confirm 통과 직후 active runtime 차단
    _assert_no_active_runtime(fmt)

    from ante.account.errors import (
        AccountDeletedError,
        AccountHasActiveBotsError,
        AccountNotFoundError,
    )

    async def _do_delete() -> None:
        svc, db = await _create_account_service()
        try:
            await svc.delete(account_id, deleted_by=member_id)
        finally:
            await db.close()

    try:
        _run(_do_delete())
    except AccountHasActiveBotsError as e:
        # 메시지 본문은 errors.py에서 multi-step 복구 절차까지 포함해 빌드한다.
        # (#1139 R-A) 별도 wording을 만들지 말고 그대로 출력한다.
        fmt.error(str(e), code="ACCOUNT_HAS_ACTIVE_BOTS")
        raise SystemExit(1) from e
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except AccountDeletedError as e:
        fmt.error(str(e), code="ACCOUNT_ALREADY_DELETED")
        raise SystemExit(1) from e
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(f'계좌 "{account_id}" 삭제 완료')


# ── credentials ──────────────────────────────────────


@account.command("credentials")
@click.argument("account_id")
@format_option
@click.pass_context
@require_auth
@require_scope("account:read")
def account_credentials(ctx: click.Context, account_id: str) -> None:
    """인증 정보 조회 (마스킹)."""
    fmt = get_formatter(ctx)

    async def _do_credentials() -> dict[str, str]:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            return {k: mask_value(k, v) for k, v in acct.credentials.items()}
        finally:
            await db.close()

    try:
        masked = _run(_do_credentials())
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    if not masked:
        fmt.output({"message": "등록된 인증 정보가 없습니다.", "credentials": {}})
        return

    if fmt.is_json:
        fmt.output({"account_id": account_id, "credentials": masked})
    else:
        click.echo(f"\n인증 정보 ({account_id})")
        click.echo("-" * 35)
        for key, value in masked.items():
            click.echo(f"  {key.upper():14s}: {value}")


# ── set-credentials ──────────────────────────────────────


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
) -> None:
    """인증 정보 재설정 (비대화형, cold-path 전용).

    SSOT: ``BrokerPreset.required_credentials``를 **모두** 충족해야 하며,
    부분 갱신은 허용하지 않는다(`docs/specs/cli/03-commands.md`
    `account set-credentials` 입력 계약).
    BREAKING CHANGE: 이전 ``--app-key`` / ``--app-secret`` 옵션은 제거되었다.
    ``--credential`` / ``--credential-env`` / ``--credential-file``를 사용한다.
    """
    fmt = get_formatter(ctx)

    # cold-path: active runtime이 있으면 진입 직후 차단
    _assert_no_active_runtime(fmt)

    from ante.account.presets import BROKER_PRESETS

    async def _do_set_credentials() -> None:
        svc, db = await _create_account_service()
        try:
            acct = await svc.get(account_id)
            preset = BROKER_PRESETS.get(acct.broker_type)
            if not preset or not preset.required_credentials:
                # broker preset이 credentials를 요구하지 않는 경우(예: 향후 broker)
                # 입력이 있으면 unknown으로 거부하고, 없으면 no-op으로 안내한다.
                any_input = bool(
                    credentials_direct or credentials_env or credentials_file
                )
                if any_input:
                    _exit_with_error(
                        fmt,
                        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
                        (
                            f"브로커 '{acct.broker_type}'은 "
                            "credentials를 요구하지 않습니다."
                        ),
                    )
                msg = f"브로커 '{acct.broker_type}'에는 인증 정보가 필요하지 않습니다."
                fmt.output({"message": msg})
                return

            # credential 옵션 누락 검증: 채널 셋이 모두 비어 있으면 실패
            if not (credentials_direct or credentials_env or credentials_file):
                required = list(preset.required_credentials)
                _exit_with_error(
                    fmt,
                    "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
                    (
                        "credential 옵션이 누락되었습니다. "
                        "--credential / --credential-env / --credential-file "
                        f"중 하나로 required keys {required}를 모두 제공해야 합니다."
                    ),
                )

            new_credentials = _resolve_credentials(
                fmt=fmt,
                required_keys=list(preset.required_credentials),
                direct_pairs=credentials_direct,
                env_pairs=credentials_env,
                file_pairs=credentials_file,
            )

            await svc.update(account_id, credentials=new_credentials)
            fmt.success(f'계좌 "{account_id}" 인증 정보 재설정 완료')
        finally:
            await db.close()

    try:
        _run(_do_set_credentials())
    except SystemExit:
        raise
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e


# ── repair-timezone ──────────────────────────────────────


@account.command("repair-timezone")
@click.option(
    "--account-id",
    "account_id_opt",
    required=False,
    default=None,
    help="복구 대상 계좌 식별자",
)
@click.option(
    "--timezone",
    "timezone_opt",
    required=False,
    default=None,
    help="새 valid IANA timezone (예: Asia/Seoul, US/Eastern)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("account:write")
def account_repair_timezone(
    ctx: click.Context,
    account_id_opt: str | None,
    timezone_opt: str | None,
) -> None:
    """legacy invalid timezone row 를 valid IANA 값으로 교정한다 (cold-path 전용).

    #1473 이전에 저장되어 ``GET /api/accounts`` 응답에 ``timezone_invalid: true`` 로
    보고된 row 를 복구하는 운영 명령. service 는 ``_row_to_account`` 단계에서
    invalid timezone 을 fallback (``Asia/Seoul``) 으로 대체해 load 자체는
    성공시키지만, 원본 DB row 는 그대로 invalid 다 — 본 명령으로만 명시적으로
    rewrite 한다 (silent rewrite 금지).

    필수 옵션: ``--account-id``, ``--timezone``.

    실패 코드:

    - ``CLI_MISSING_REQUIRED_INPUT``: 옵션 누락.
    - ``ACCOUNT_INVALID_TIMEZONE``: ``--timezone`` 이 invalid IANA key.
    - ``ACCOUNT_NOT_FOUND``: 계좌 없음.
    - ``ACCOUNT_ALREADY_DELETED``: DELETED 계좌 (복구 불가).

    SSOT: docs/specs/account/09-cli.md (repair-timezone 절).
    """
    fmt = get_formatter(ctx)

    # cold-path: active runtime 차단
    _assert_no_active_runtime(fmt)

    required_inputs: dict[str, str | None] = {
        "--account-id": account_id_opt,
        "--timezone": timezone_opt,
    }
    missing = [k for k, v in required_inputs.items() if v is None or v == ""]
    if missing:
        _exit_with_error(
            fmt,
            "CLI_MISSING_REQUIRED_INPUT",
            f"필수 옵션 누락: {missing}",
        )

    assert account_id_opt is not None
    assert timezone_opt is not None

    from ante.account.errors import (
        AccountDeletedError,
        AccountNotFoundError,
    )

    async def _do_repair() -> Account:
        svc, db = await _create_account_service()
        try:
            return await svc.repair_timezone(account_id_opt, timezone_opt)
        finally:
            await db.close()

    try:
        repaired = _run(_do_repair())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except AccountDeletedError as e:
        fmt.error(str(e), code="ACCOUNT_ALREADY_DELETED")
        raise SystemExit(1) from e
    except ValueError as e:
        # validate_iana_timezone 의 invalid IANA 메시지를 그대로 노출.
        fmt.error(str(e), code="ACCOUNT_INVALID_TIMEZONE")
        raise SystemExit(1) from e
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        raise SystemExit(1) from e

    fmt.success(
        f'계좌 "{repaired.account_id}" timezone 복구 완료 ({repaired.timezone})',
        data={
            "account_id": repaired.account_id,
            "timezone": repaired.timezone,
            "timezone_invalid": repaired.timezone_invalid,
        },
    )


# ── 유틸리티 ──────────────────────────────────────


def _account_to_row(acct: Account) -> dict:
    """Account를 테이블 행 dict로 변환."""
    return {
        "account_id": acct.account_id,
        "name": acct.name,
        "exchange": acct.exchange,
        "currency": acct.currency,
        "broker_type": acct.broker_type,
        "status": acct.status.value,
    }


def _account_to_detail(acct: Account) -> dict:
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


def _print_account_detail(detail: dict) -> None:
    """텍스트 모드로 계좌 상세 출력."""
    click.echo("\n계좌 정보")
    click.echo("-" * 35)
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
        click.echo(f"  {label:14s}: {value}")
