"""에러 레지스트리 완전성 (#2664 「0에 도달하는 판정」 3).

``src/ante``의 모든 ``ante.*`` 예외 클래스의 인스턴스마다
``error_spec_for_exception(e).code``가 레지스트리의 ``ErrorSpec.code`` 집합에
있는지 본다. 지금 없는 클래스의 집합을 리터럴로 두고 정확히 같아야 통과한다.
이전 묶음마다 줄이고, 끝에 빈 집합이 된다.

클래스 열거와 인스턴스 생성은 #2641의 코드 보존 조사와 같다.
"""

from __future__ import annotations

import click

from ante.contracts import error_registry
from ante.contracts.errors import ErrorSpec
from ante.contracts.helpers import error_spec_for_exception
from tests.unit.contracts.test_error_code_preservation import (
    ante_exception_classes,
    make_instance,
)

OUTSIDE_REGISTRY = frozenset(
    {
        "ante.account.crypto.EncryptionKeyError",
        "ante.account.crypto.EncryptionKeyInvalidError",
        "ante.account.crypto.EncryptionKeyMissingError",
        "ante.broker.exceptions.ModifyOrgnoUnavailableError",
        "ante.contracts.ipc_client_errors.IPCRemoteError",
        "ante.gateway.stop_order.StopOrderManagerStoppedError",
    }
)

KNOWN_LIMIT_CODES = frozenset(
    {
        "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
        "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
        "ACCOUNT_DUPLICATE_CREDENTIAL_KEY",
        "ACCOUNT_INVALID_TIMEZONE",
        "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
        "INSTRUMENT_INVALID_EXCHANGE",
        "INSTRUMENT_INVALID_SYMBOL",
        "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED",
    }
)

KNOWN_LIMIT_CODES_NOT_YET_REGISTERED = frozenset(
    {
        "ACCOUNT_CREDENTIAL_ENV_NOT_SET",
        "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
        "ACCOUNT_DUPLICATE_CREDENTIAL_KEY",
        "ACCOUNT_INVALID_TIMEZONE",
        "ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
        "ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
    }
)


def registry_codes() -> frozenset[str]:
    codes = {spec.code for spec in error_registry.EXCEPTION_TO_SPEC.values()}
    codes |= {v.code for v in vars(error_registry).values() if isinstance(v, ErrorSpec)}
    return frozenset(codes)


def _resolved_code(cls: type[BaseException]) -> str:
    try:
        return error_spec_for_exception(make_instance(cls)).code
    except Exception as exc:
        return f"<raises {type(exc).__name__}>"


def test_classes_outside_registry_are_exactly_the_listed_set() -> None:
    classes = ante_exception_classes()
    assert len(classes) > len(OUTSIDE_REGISTRY)
    codes = registry_codes()
    outside = {
        f"{cls.__module__}.{cls.__qualname__}"
        for cls in classes
        if _resolved_code(cls) not in codes
    }
    assert outside == OUTSIDE_REGISTRY


def test_survey_sees_a_registered_class() -> None:
    names = {f"{c.__module__}.{c.__qualname__}" for c in ante_exception_classes()}
    assert "ante.bot.exceptions.BotNotFoundError" in names
    assert "BOT_NOT_FOUND" in registry_codes()


def test_known_limit_codes_not_yet_registered_are_exactly_the_listed_set() -> None:
    codes = registry_codes()
    assert {c for c in KNOWN_LIMIT_CODES if c not in codes} == (
        KNOWN_LIMIT_CODES_NOT_YET_REGISTERED
    )


def test_cli_error_classes_are_registered_under_their_own_code() -> None:
    from ante.contracts import cli_errors

    classes = [
        v
        for v in vars(cli_errors).values()
        if isinstance(v, type)
        and issubclass(v, BaseException)
        and v.__module__ == cli_errors.__name__
    ]
    assert len(classes) == len(cli_errors.__all__) > 0
    spec_of = error_registry.EXCEPTION_TO_SPEC
    registered = {
        c.__name__: spec_of[c].code if c in spec_of else None for c in classes
    }
    assert registered == {c.__name__: c.code for c in classes}


def test_cli_errors_tuple_is_exactly_the_module_exception_classes() -> None:
    from ante.contracts import cli_errors

    classes = {
        v
        for v in vars(cli_errors).values()
        if isinstance(v, type)
        and issubclass(v, BaseException)
        and v.__module__ == cli_errors.__name__
    }
    assert len(cli_errors.CLI_ERRORS) == len(set(cli_errors.CLI_ERRORS))
    assert set(cli_errors.CLI_ERRORS) == classes
    assert all(not issubclass(c, click.ClickException) for c in classes)
