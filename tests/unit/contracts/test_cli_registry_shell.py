"""CLI contract registry shell signature lock test (#1844).

본 모듈은 :mod:`ante.contracts.cli_registry` 의 dataclass / accessor / 빈
registry 시그니처를 **lock** 한다. 후속 PR (`#1846` account / `#1847`
remaining / `#1845`/`#1848` drift guard) 가 contract entry 를 등록하기
시작했을 때 dataclass 시그니처가 임의로 흔들리면 광범위 재작업이
필요하기 때문에, 본 PR 시점에서 시그니처를 명시 단언으로 박아둔다.

본 test 가 lock 하는 것:

* :class:`AuthContract` / :class:`OutputContract` /
  :class:`CliCommandContract` 의 필드 이름 집합과 순서.
* default 값 (``scopes`` 는 빈 frozenset, ``data_key`` 는 ``None``,
  ``envelope`` 는 ``"standard"``, ``ipc_command`` 는 ``None``).
* ``frozen=True`` dataclass 인지 (불변 instance 보장).
* :data:`ante.contracts.vocab.AuthMode` / :data:`ContractKind` /
  :data:`EnvelopeForm` Literal 의 모든 값이 dataclass 에 받아들여진다.
* ``raw_legacy`` 가 :data:`EnvelopeForm` 자리이지 :data:`ContractKind`
  자리가 아니다 (#1820 결정).
* :data:`CLI_COMMAND_REGISTRY` 는 본 PR 시점 빈 dict, 두 accessor 가
  비어있다.
* :mod:`ante.contracts.cli_registry` 또는 :mod:`ante.contracts` import 가
  CLI command 실행 side effect 를 만들지 않는다.

scope 외 (deliberately not asserted): 실제 command entry 등록 여부는
`#1846` / `#1847` 의 책임이며, 본 test 는 빈 registry baseline 만 확인한다.
"""

from __future__ import annotations

import dataclasses
import sys
import typing

import pytest

from ante.contracts.cli_registry import (
    CLI_COMMAND_REGISTRY,
    AuthContract,
    CliCommandContract,
    ExecutionClass,
    OutputContract,
    all_contracts,
    get_contract,
)
from ante.contracts.vocab import AuthMode, ContractKind, EnvelopeForm

# ── dataclass field signature lock ─────────────────────────────────────────


def _field_map(cls: type) -> dict[str, dataclasses.Field]:
    return {f.name: f for f in dataclasses.fields(cls)}


def test_auth_contract_field_names_and_order() -> None:
    fields = dataclasses.fields(AuthContract)
    assert [f.name for f in fields] == ["mode", "scopes"]


def test_auth_contract_is_frozen() -> None:
    assert AuthContract.__dataclass_params__.frozen is True


def test_auth_contract_scopes_default_is_empty_frozenset() -> None:
    # default 가 mutable factory 면 default_factory 호출 결과를 확인한다.
    instance = AuthContract(mode="public")
    assert instance.scopes == frozenset()
    assert isinstance(instance.scopes, frozenset)


def test_auth_contract_scope_set_is_immutable() -> None:
    instance = AuthContract(mode="scoped", scopes=frozenset({"a", "b"}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.mode = "public"  # type: ignore[misc]


def test_output_contract_field_names_and_order() -> None:
    fields = dataclasses.fields(OutputContract)
    assert [f.name for f in fields] == ["kind", "data_key", "envelope"]


def test_output_contract_is_frozen() -> None:
    assert OutputContract.__dataclass_params__.frozen is True


def test_output_contract_defaults() -> None:
    instance = OutputContract(kind="entity")
    assert instance.data_key is None
    assert instance.envelope == "standard"


def test_cli_command_contract_field_names_and_order() -> None:
    fields = dataclasses.fields(CliCommandContract)
    assert [f.name for f in fields] == [
        "path",
        "auth",
        "output",
        "execution",
        "ipc_command",
    ]


def test_cli_command_contract_is_frozen() -> None:
    assert CliCommandContract.__dataclass_params__.frozen is True


def test_cli_command_contract_defaults() -> None:
    instance = CliCommandContract(
        path=("example",),
        auth=AuthContract(mode="public"),
        output=OutputContract(kind="entity"),
        execution="offline",
    )
    assert instance.ipc_command is None


def test_cli_command_contract_execution_is_required() -> None:
    # ``execution`` 은 default 없음 (#1815 normative).
    field = _field_map(CliCommandContract)["execution"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING


# ── vocab alignment ────────────────────────────────────────────────────────


def _literal_values(literal_alias: object) -> tuple[object, ...]:
    """Literal alias 의 값들을 튜플로 반환한다."""
    return typing.get_args(literal_alias)


def test_auth_mode_literal_values_accepted_by_auth_contract() -> None:
    for value in _literal_values(AuthMode):
        instance = AuthContract(mode=value)  # type: ignore[arg-type]
        assert instance.mode == value


def test_contract_kind_literal_values_accepted_by_output_contract() -> None:
    for value in _literal_values(ContractKind):
        instance = OutputContract(kind=value)  # type: ignore[arg-type]
        assert instance.kind == value


def test_envelope_form_literal_values_accepted_by_output_contract() -> None:
    for value in _literal_values(EnvelopeForm):
        instance = OutputContract(kind="raw", envelope=value)  # type: ignore[arg-type]
        assert instance.envelope == value


def test_execution_class_literal_values_match_spec() -> None:
    # docs/specs/cli/03-commands.md 의 5 모드와 1:1 정합 (external process 흡수).
    assert set(_literal_values(ExecutionClass)) == {
        "bootstrap",
        "offline",
        "runtime_ipc",
        "cold_path",
        "long_running",
    }


def test_raw_legacy_is_envelope_form_not_contract_kind() -> None:
    """``raw_legacy`` 는 EnvelopeForm 값이지 ContractKind 값이 아니다 (#1820)."""
    assert "raw_legacy" in _literal_values(EnvelopeForm)
    assert "raw_legacy" not in _literal_values(ContractKind)
    # 표현 lock: kind="raw" + envelope="raw_legacy" 조합으로 표현된다.
    instance = OutputContract(kind="raw", envelope="raw_legacy")
    assert instance.kind == "raw"
    assert instance.envelope == "raw_legacy"


# ── registry baseline (account migration, #1846) ──────────────────────────
#
# #1844 시점에는 ``CLI_COMMAND_REGISTRY`` 가 빈 dict 라는 baseline 단언이
# 박혀 있었다 (``test_empty_registry_baseline`` / ``test_all_contracts_
# baseline_is_empty``). #1846 가 account 9 entries 를 등록하면서 그
# deferred lock 은 자연스럽게 종료되었다 — 본 PR 가 두 baseline 단언을
# 제거했다. 이후의 invariant 는 "registry 가 plain mutable dict 이고
# accessor 가 일관 동작한다" 만 lock 한다. 미등록 leaf FAIL 은 `#1848`
# 의 책임이다.


def test_get_contract_returns_none_when_missing() -> None:
    """미등록 path 는 ``None`` 을 반환한다 (account 9 entry 외)."""
    # nonexistent path 는 항상 ``None``.
    assert get_contract(("nonexistent",)) is None
    # bot 도메인 entry 등록은 #1847 의 책임이므로 본 PR 시점에는 ``None``.
    assert get_contract(("bot", "start")) is None


def test_registry_is_mutable_dict() -> None:
    """후속 PR (`#1847`) 가 in-place 등록할 수 있도록 plain dict 다."""
    assert isinstance(CLI_COMMAND_REGISTRY, dict)


def test_account_entries_registered_after_1846() -> None:
    """#1846 가 account 9 leaf entry 를 등록했음을 lock 한다.

    본 단언은 #1846 가 account migration 을 완료한 시점부터 lock 된다.
    9 entry 의 정확한 ``OutputContract`` / ``AuthContract`` 정합 검증은
    :mod:`tests.unit.contracts.test_cli_registry_auth_drift` (Family B) 와
    :mod:`tests.unit.test_account_success_output_drift` 가 책임진다.
    """
    expected_account_paths = {
        ("account", "list"),
        ("account", "info"),
        ("account", "credentials"),
        ("account", "create"),
        ("account", "set-credentials"),
        ("account", "delete"),
        ("account", "repair-timezone"),
        ("account", "suspend"),
        ("account", "activate"),
    }
    registered = set(CLI_COMMAND_REGISTRY.keys())
    assert expected_account_paths.issubset(registered), (
        f"account 9 entry 가 모두 등록되어야 한다 (#1846). "
        f"누락: {sorted(expected_account_paths - registered)}"
    )


def test_member_entries_registered_after_1847_sub_pr_1() -> None:
    """#1847 sub-PR 1 가 member 12 leaf entry 를 등록했음을 lock 한다.

    본 단언은 #1847 sub-PR 1 가 member migration 을 완료한 시점부터
    lock 된다. 12 entry 의 정확한 ``OutputContract`` / ``AuthContract``
    정합 검증은 :mod:`tests.unit.contracts.test_cli_registry_auth_drift`
    (Family A/B/C) 와 :mod:`tests.unit.test_member_success_output_drift`
    가 책임진다.
    """
    expected_member_paths = {
        ("member", "list"),
        ("member", "info"),
        ("member", "list-invalid-roles"),
        ("member", "register"),
        ("member", "set-emoji"),
        ("member", "update-scopes"),
        ("member", "suspend"),
        ("member", "reactivate"),
        ("member", "revoke"),
        ("member", "rotate-token"),
        ("member", "reset-password"),
        ("member", "regenerate-recovery-key"),
    }
    registered = set(CLI_COMMAND_REGISTRY.keys())
    assert expected_member_paths.issubset(registered), (
        f"member 12 entry 가 모두 등록되어야 한다 (#1847 sub-PR 1). "
        f"누락: {sorted(expected_member_paths - registered)}"
    )


# ── alias re-export from package __init__ ─────────────────────────────────


def test_package_reexports_registry_symbols() -> None:
    from ante import contracts

    assert contracts.AuthContract is AuthContract
    assert contracts.OutputContract is OutputContract
    assert contracts.CliCommandContract is CliCommandContract
    assert contracts.CLI_COMMAND_REGISTRY is CLI_COMMAND_REGISTRY
    assert contracts.get_contract is get_contract
    assert contracts.all_contracts is all_contracts


# ── import side effect lock ───────────────────────────────────────────────


def test_cli_registry_import_does_not_load_cli_main() -> None:
    """registry import 만으로 ``ante.cli.main`` (Click root) 이 import 되지 않는다.

    Click root import 는 모든 command module 의 ``import`` 및 그에 따른 IO /
    env access / configuration 로딩을 트리거할 수 있다. registry shell 은
    순수 dataclass + 빈 dict 이므로 어떤 CLI 모듈도 끌어오면 안 된다.
    """
    # 본 test 실행 시점에 이전 test 가 ``ante.cli.main`` 을 import 했을 수
    # 있으므로 sys.modules 를 정리한 뒤 isolated import 한다.
    cli_modules = [
        name
        for name in list(sys.modules)
        if name == "ante.cli" or name.startswith("ante.cli.")
    ]
    for name in cli_modules:
        del sys.modules[name]
    # cli_registry / contracts package 도 다시 import 해서 import 그래프를
    # 재현한다.
    for name in ("ante.contracts.cli_registry", "ante.contracts"):
        if name in sys.modules:
            del sys.modules[name]

    import ante.contracts.cli_registry  # noqa: F401  -- side effect probe

    loaded_cli = [
        name
        for name in sys.modules
        if name == "ante.cli" or name.startswith("ante.cli.")
    ]
    assert loaded_cli == [], (
        "ante.contracts.cli_registry import 가 ante.cli 트리를 끌어왔다: "
        f"{sorted(loaded_cli)}"
    )


def test_contracts_package_import_does_not_load_cli_main() -> None:
    """``from ante import contracts`` 만으로 ``ante.cli.main`` 이 import 되지 않는다."""
    cli_modules = [
        name
        for name in list(sys.modules)
        if name == "ante.cli" or name.startswith("ante.cli.")
    ]
    for name in cli_modules:
        del sys.modules[name]
    for name in ("ante.contracts", "ante.contracts.cli_registry"):
        if name in sys.modules:
            del sys.modules[name]

    import ante.contracts  # noqa: F401

    loaded_cli = [
        name
        for name in sys.modules
        if name == "ante.cli" or name.startswith("ante.cli.")
    ]
    assert loaded_cli == [], (
        f"ante.contracts import 가 ante.cli 트리를 끌어왔다: {sorted(loaded_cli)}"
    )
