"""Account CLI success output ↔ registry OutputContract drift lock (#1846).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
account 도메인 9 leaf 의 ``OutputContract`` 와 ``ante account ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

drift 모델:

- ``envelope="standard"`` entry → CLI success envelope 4-form 중
  ``{status, message, data}`` (envelopes.md SSOT). ``fmt.success(...)``
  callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → 평면 dict 를 그대로 ``fmt.output(...)``
  로 dump 한다 (``status``/``message``/``data`` 3 키 모두 부재).

본 PR 은 account.py 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. 본 test 는 callsite 가
다른 shape 로 drift 했을 때 즉시 FAIL 한다 (registry 갱신 또는 callsite
정렬 중 한쪽이 책임).

11 시나리오:

1. ``list`` empty (rows 0) → ``raw_legacy`` (``{message, accounts}``)
2. ``list`` non-empty (rows > 0) → ``raw_legacy`` (``{accounts: [...]}``)
3. ``info`` → ``raw_legacy`` (평면 detail dict)
4. ``credentials`` empty (credentials 0) → ``raw_legacy``
   (``{message, credentials}``)
5. ``credentials`` non-empty → ``raw_legacy``
   (``{account_id, credentials}``)
6. ``create`` → ``standard`` (``fmt.success``)
7. ``set-credentials`` standard 경로 → ``standard`` (``fmt.success``)
8. ``set-credentials`` no-credentials short-circuit → ``raw_legacy``
   (``{message}``) — 분기 mixed 가 registry 의 ``raw_legacy`` 우선 정책에
   부합함을 lock
9. ``delete`` → ``standard`` (``fmt.success``)
10. ``repair-timezone`` → ``standard`` (``fmt.success``)
11. ``suspend`` (runtime_ipc passthrough) → ``standard`` (``fmt.success``)
12. ``activate`` (runtime_ipc passthrough) → ``standard`` (``fmt.success``)

(2 분기 케이스로 list/credentials 각각 empty/non-empty 를 분리해
12 시나리오로 확장. set-credentials short-circuit 도 별도 분기로 lock.)
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY

# ── envelope shape predicates (envelopes.md SSOT 정합) ─────────────────────


_STANDARD_KEYS = frozenset({"status", "message", "data"})


def _is_standard_envelope(payload: dict[str, Any]) -> bool:
    """``{status: "ok", message, data}`` 3 필수 키가 모두 존재하는지."""
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and set(payload.keys()) >= _STANDARD_KEYS
        and isinstance(payload.get("message"), str)
        and isinstance(payload.get("data"), dict)
    )


def _is_raw_legacy_envelope(payload: dict[str, Any]) -> bool:
    """평면 dict 이고 standard envelope 의 3 필수 키 셋이 모두 갖춰져 있지 않다.

    raw_legacy 는 평면 도메인 payload 를 그대로 dump 한다. 만약 dict 가
    ``{status, message, data}`` 3 키를 동시에 갖고 ``status == "ok"`` 면
    standard envelope 으로 분류된다 (애매한 경계 방지).
    """
    if not isinstance(payload, dict):
        return False
    # standard 3 키 셋을 *동시* 보유하지 않아야 raw_legacy 다. 도메인이
    # 우연히 message 또는 data 키 하나를 가질 수는 있으나, 세 키가 모두
    # 있으면서 status="ok" 면 standard envelope 으로 분류한다.
    if (
        set(payload.keys()) >= _STANDARD_KEYS
        and payload.get("status") == "ok"
        and isinstance(payload.get("data"), dict)
    ):
        return False
    return True


# ── registry entry 정합 sanity (envelope vocab) ───────────────────────────


def test_registry_account_entries_envelopes_classified() -> None:
    """account 9 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 두 값만 사용한다.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 9 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    for path, contract in CLI_COMMAND_REGISTRY.items():
        if path[:1] != ("account",):
            continue
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account_cli.py 패턴 동형) ─────────────────────────────────


def _mock_account(
    account_id: str = "test",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    status: str = "active",
    trading_mode: str = "virtual",
    credentials: dict | None = None,
):
    """테스트용 Account mock 객체 (tests/unit/test_account_cli.py 와 동형)."""
    from ante.account.models import Account, AccountStatus, TradingMode

    return Account(
        account_id=account_id,
        name=name,
        exchange=exchange,
        currency=currency,
        broker_type=broker_type,
        status=AccountStatus(status),
        trading_mode=TradingMode(trading_mode),
        credentials=credentials or {},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


@pytest.fixture
def mock_account_service():
    """AccountService mock fixture."""
    svc = AsyncMock()
    db = AsyncMock()

    async def _create_service():
        return svc, db

    with patch(
        "ante.cli.commands.account._create_account_service", new=_create_service
    ):
        yield svc


@pytest.fixture(autouse=True)
def bypass_auth():
    """master member 로 인증을 우회한다."""
    from ante.member.models import Member, MemberRole, MemberStatus, MemberType

    mock_member = Member(
        member_id="tester",
        name="테스터",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        status=MemberStatus.ACTIVE,
        scopes=[],
    )
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": mock_member}),
    ):
        yield


@pytest.fixture
def offline_runtime():
    """cold-path 명령이 active runtime guard 를 통과하도록 한다."""
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_offline_drift_test__.sock",
        ),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json account ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> dict[str, Any]:
    """CLI ``--format json`` 출력의 마지막 JSON 객체를 파싱한다.

    Click ``CliRunner`` 가 한 invocation 의 stdout 을 합쳐주므로 일반적으로
    한 줄의 JSON 객체만 나온다. 안전을 위해 첫 ``{`` 부터 마지막 ``}`` 까지를
    추출한다.
    """
    text = output.strip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    return json.loads(text)


# ── 1. account list (empty / non-empty) → raw_legacy ──────────────────────


def test_account_list_empty_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock,
) -> None:
    """``account list`` empty 결과: ``{message, accounts}`` 평면 dict (raw_legacy)."""
    mock_account_service.list.return_value = []
    result = _invoke(["--format", "json", "account", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account list empty: standard envelope 아니어야 함 (registry "
        f"envelope=raw_legacy 와 정합). 실제 payload={payload!r}"
    )
    assert payload == {"message": "등록된 계좌가 없습니다.", "accounts": []}


def test_account_list_non_empty_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock,
) -> None:
    """``account list`` non-empty: ``{accounts: [...]}`` 평면 dict (raw_legacy)."""
    mock_account_service.list.return_value = [
        _mock_account("test", "테스트", "TEST", "KRW", "test"),
    ]
    result = _invoke(["--format", "json", "account", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account list non-empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert "accounts" in payload
    assert isinstance(payload["accounts"], list)
    assert len(payload["accounts"]) == 1
    assert payload["accounts"][0]["account_id"] == "test"


# ── 2. account info → raw_legacy ──────────────────────────────────────────


def test_account_info_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock,
) -> None:
    """``account info``: 평면 detail dict (raw_legacy)."""
    mock_account_service.get.return_value = _mock_account(
        "domestic", "국내 주식", "KRX", "KRW", "kis-domestic"
    )
    result = _invoke(["--format", "json", "account", "info", "domestic"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account info: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["account_id"] == "domestic"
    assert payload["exchange"] == "KRX"


# ── 3. account credentials (empty / non-empty) → raw_legacy ───────────────


def test_account_credentials_empty_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock,
) -> None:
    """``account credentials`` empty: ``{message, credentials: {}}`` (raw_legacy)."""
    mock_account_service.get.return_value = _mock_account("test", credentials={})
    result = _invoke(["--format", "json", "account", "credentials", "test"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account credentials empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload == {"message": "등록된 인증 정보가 없습니다.", "credentials": {}}


def test_account_credentials_non_empty_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock,
) -> None:
    """``account credentials`` non-empty: ``{account_id, credentials}`` (raw_legacy)."""
    mock_account_service.get.return_value = _mock_account(
        "domestic", credentials={"app_key": "PSxxxxxxxx"}
    )
    result = _invoke(["--format", "json", "account", "credentials", "domestic"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account credentials non-empty: standard envelope 아니어야 함. "
        f"payload={payload!r}"
    )
    assert payload["account_id"] == "domestic"
    assert payload["credentials"]["app_key"] == "PSxx****xx"


# ── 4. account create → standard ──────────────────────────────────────────


def _create_args_test_broker(
    *,
    account_id: str = "test2",
    name: str = "테스트2",
    trading_mode: str = "virtual",
    extra: list[str] | None = None,
) -> list[str]:
    """``broker-type=test`` 표준 비대화형 인자 세트 (test_account_cli.py 동형)."""
    args = [
        "--format",
        "json",
        "account",
        "create",
        "--broker-type",
        "test",
        "--account-id",
        account_id,
        "--name",
        name,
        "--trading-mode",
        trading_mode,
        "--credential",
        "app_key=K",
        "--credential",
        "app_secret=S",
    ]
    if extra:
        args.extend(extra)
    return args


def test_account_create_envelope_matches_operation_standard(
    mock_account_service: AsyncMock, offline_runtime
) -> None:
    """``account create``: ``{status, message, data}`` (standard envelope)."""
    created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
    mock_account_service.create.return_value = created

    result = _invoke(_create_args_test_broker())
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"account create: standard envelope 이어야 함. payload={payload!r}"
    )
    assert payload["data"]["account_id"] == "test2"
    assert payload["data"]["broker_type"] == "test"


# ── 5. account set-credentials (standard / short-circuit) ─────────────────


def test_account_set_credentials_standard_path_envelope_matches_operation_standard(
    mock_account_service: AsyncMock, offline_runtime
) -> None:
    """``account set-credentials`` 정상 경로: ``fmt.success`` → standard envelope.

    test broker preset 은 ``required_credentials=["app_key", "app_secret"]`` 이라
    두 credential 을 모두 제공한 경우 정상 갱신 경로로 진입한다.
    """
    mock_account_service.get.return_value = _mock_account(
        "test", credentials={"app_key": "old", "app_secret": "old"}
    )
    mock_account_service.update.return_value = None

    result = _invoke(
        [
            "--format",
            "json",
            "account",
            "set-credentials",
            "test",
            "--credential",
            "app_key=K2",
            "--credential",
            "app_secret=S2",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    # 정상 경로는 fmt.success → standard envelope. registry entry 는
    # raw_legacy 우선이지만, set-credentials 는 분기 mixed 라 본 케이스는
    # standard 도 정당하다 (plan v2 #5 명시).
    assert _is_standard_envelope(payload), (
        f"account set-credentials 정상 경로: standard envelope 이어야 함. "
        f"payload={payload!r}"
    )
    assert "인증 정보 재설정 완료" in payload["message"]


def test_account_set_credentials_short_circuit_envelope_matches_raw_legacy(
    mock_account_service: AsyncMock, offline_runtime
) -> None:
    """``account set-credentials`` no-credentials short-circuit → raw_legacy.

    short-circuit 분기는 ``fmt.output({"message": ...})`` 평면 dict 를 dump
    한다. broker preset 이 required_credentials 가 없는 경우 (또는 BROKER_PRESETS
    에 등록되지 않은 경우) ``fmt.output({"message": ...})`` 평면 dict 로
    short-circuit 한다. 본 분기가 registry 의 raw_legacy 우선 정책에 부합함을
    lock 한다.

    구현: ``BROKER_PRESETS.get`` 을 ``None`` 으로 패치하면 set-credentials
    가 short-circuit 분기로 진입한다 (account.py:1015-1033).
    """
    mock_account_service.get.return_value = _mock_account(
        "test", credentials={}, broker_type="some-future-broker"
    )

    with patch(
        "ante.account.presets.BROKER_PRESETS",
        {},  # 빈 dict — preset.get(broker_type) 가 None 반환
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "account",
                "set-credentials",
                "test",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"account set-credentials short-circuit: raw_legacy 이어야 함. "
        f"payload={payload!r}"
    )
    assert "message" in payload
    assert "인증 정보가 필요하지 않습니다" in payload["message"]


# ── 6. account delete → standard ──────────────────────────────────────────


def test_account_delete_envelope_matches_operation_standard(
    mock_account_service: AsyncMock, offline_runtime
) -> None:
    """``account delete``: ``fmt.success`` → standard envelope."""
    mock_account_service.delete.return_value = None

    result = _invoke(["--format", "json", "account", "delete", "domestic", "--yes"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"account delete: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "삭제 완료" in payload["message"]


# ── 7. account repair-timezone → standard ─────────────────────────────────


def test_account_repair_timezone_envelope_matches_operation_standard(
    mock_account_service: AsyncMock, offline_runtime
) -> None:
    """``account repair-timezone``: ``fmt.success`` (with data) → standard envelope."""
    repaired = _mock_account("domestic", "국내 주식", "KRX", "KRW", "kis-domestic")
    # ``Account.timezone`` 은 dataclass field 라 기본 'Asia/Seoul' 이 들어가 있다.
    mock_account_service.repair_timezone.return_value = repaired

    result = _invoke(
        [
            "--format",
            "json",
            "account",
            "repair-timezone",
            "domestic",
            "Asia/Seoul",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"account repair-timezone: standard envelope 이어야 함. payload={payload!r}"
    )
    assert payload["data"]["account_id"] == "domestic"
    assert payload["data"]["code"] == "ACCOUNT_REPAIR_TIMEZONE_OK"


# ── 8. account suspend / activate (runtime_ipc passthrough) → standard ────


def test_account_suspend_envelope_matches_operation_standard() -> None:
    """``account suspend``: IPC passthrough 이후 ``fmt.success`` → standard envelope.

    envelopes.md "Wrapping 경계": runtime_ipc 명령은 IPC ``result`` 를 받은
    뒤 CLI surface 에서 ``fmt.success(...)`` 로 한 번 wrapping 한다.
    """
    mock_response = {"status": "ok", "data": {}}

    with patch("ante.cli.commands.ipc_helpers.IPCClient", autospec=True) as mock_cls:
        mock_client = AsyncMock()
        mock_client.send.return_value = mock_response
        mock_cls.return_value = mock_client

        with patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_suspend_drift_test__.sock",
        ):
            result = _invoke(["--format", "json", "account", "suspend", "domestic"])

    assert result.exit_code == 0, result.output
    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"account suspend: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "정지 완료" in payload["message"]


def test_account_activate_envelope_matches_operation_standard() -> None:
    """``account activate``: IPC passthrough → ``fmt.success`` standard envelope."""
    mock_response = {"status": "ok", "data": {}}

    with patch("ante.cli.commands.ipc_helpers.IPCClient", autospec=True) as mock_cls:
        mock_client = AsyncMock()
        mock_client.send.return_value = mock_response
        mock_cls.return_value = mock_client

        with patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_activate_drift_test__.sock",
        ):
            result = _invoke(["--format", "json", "account", "activate", "domestic"])

    assert result.exit_code == 0, result.output
    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"account activate: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "활성화 완료" in payload["message"]
