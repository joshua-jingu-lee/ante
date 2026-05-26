"""CLI registry auth-scope-master drift tests (#1845).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 의
:class:`~ante.contracts.cli_registry.AuthContract` 와 다음 3 source-of-truth
사이의 drift 를 잠근다:

1. :data:`ante.cli.middleware._AUTH_EXEMPT_COMMAND_PATHS` allowlist (public).
2. ``@require_scope(*scopes)`` 데코레이터 (`_required_scopes` marker, scoped).
3. ``@require_master`` 데코레이터 (`_require_master_applied` marker, master).
4. ``@require_auth`` 데코레이터 / :class:`AuthenticatedGroup` 자동 wrap
   (`_require_auth_applied` 또는 `_wrapped_by_authenticated_group` marker,
   authenticated fallback).

본 PR 시점 :data:`CLI_COMMAND_REGISTRY` 는 빈 dict (`#1844` baseline) 이므로
모든 4 drift test 는 **vacuous pass** 한다 — registered entry 가 없으면
검증 대상이 없다. 후속 PR (`#1846` account / `#1847` remaining) 이 entry 를
등록하기 시작하면 본 4 test 가 registered entry vs decorator/allowlist 의
정합을 검증한다 (의도된 deferred lock pattern).

**Day-0 cascade** (`#1846` / `#1847` 가 entry 등록 시):

- 본 PR 4 drift test 는 registered entry 의 auth mode/scope 가 marker 와
  일치하는지 검증.
- :mod:`tests.unit.contracts.test_cli_registry_shell` 의
  ``test_registry_baseline_is_empty`` / ``test_all_contracts_baseline_is_empty``
  는 entry 추가 즉시 FAIL 한다 — `#1846` / `#1847` 의 책임으로 본 baseline
  단언을 갱신 (등록 entry > 0) 또는 제거한다.
- :mod:`tests.unit.contracts.test_cli_registry_leaf_coverage` 의
  ``test_cli_registry_leaf_coverage_report`` 의 baseline 단언도 동일 cascade.

본 test 가 **하지 않는 것** (다른 PR 의 책임):

- 누락 leaf 의 enforcement (`#1848` final coverage).
- registry 실제 entry 등록 (`#1846` / `#1847`).
- output payload migration (`#1846` / `#1847`).
- auth middleware enforcement rewrite (스펙 `#1815` 본문 변경 금지).

본 4 test 는 모두 미등록 leaf 에 대해서는 skip-equivalent (vacuous pass) 한다
— 검증 대상이 없으면 false negative 없이 그냥 통과한다. registered entry 가
등장하면 그 entry 만 검증한다.
"""

from __future__ import annotations

from ante.cli.middleware import _AUTH_EXEMPT_COMMAND_PATHS
from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from tests.unit.contracts.helpers import iter_command_auth_metadata

# ── Family A — registry ↔ _AUTH_EXEMPT_COMMAND_PATHS (public) ─────────────


def test_family_a_public_allowlist_drift() -> None:
    """Family A: registered entry 의 ``public`` 모드는 allowlist 와 일치해야 한다.

    Drift 조건 (FAIL):

    - registry 에 ``auth.mode == "public"`` 으로 등록된 path 가
      ``_AUTH_EXEMPT_COMMAND_PATHS`` 에 없음.
    - registry 에 등록된 path 가 ``_AUTH_EXEMPT_COMMAND_PATHS`` 에 있는데
      ``auth.mode`` 가 ``"public"`` 이 아님.

    미등록 leaf 는 검증하지 않는다 (`#1845` 의 책임 한계, deferred lock).
    """
    allowlist = set(_AUTH_EXEMPT_COMMAND_PATHS)

    for path, contract in CLI_COMMAND_REGISTRY.items():
        if contract.auth.mode == "public":
            assert path in allowlist, (
                f"{path}: registry auth.mode='public' 이지만 "
                f"_AUTH_EXEMPT_COMMAND_PATHS 에 없음. middleware 의 allowlist "
                f"또는 registry entry 중 한 쪽이 drift."
            )
        elif path in allowlist:
            raise AssertionError(
                f"{path}: _AUTH_EXEMPT_COMMAND_PATHS 에 등재되어 있지만 "
                f"registry auth.mode='{contract.auth.mode}' (public 기대). "
                f"allowlist 또는 registry entry 중 한 쪽이 drift."
            )


# ── Family B — registry ↔ @require_scope (scoped) ─────────────────────────


def test_family_b_require_scope_decorator_drift() -> None:
    """Family B: registered scoped entry 의 scope 가 decorator marker 와 일치.

    Drift 조건 (FAIL):

    - registry ``auth.mode == "scoped"`` 인 path 의 ``auth.scopes`` 가
      callback 의 ``_required_scopes`` marker 와 다름.
    - decorator marker (``_required_scopes`` non-empty) 가 있는데 registry
      ``auth.mode`` 가 ``"scoped"`` 가 아님.

    미등록 leaf 는 검증하지 않는다. ``@require_master`` 가 부착된 leaf 는
    Family C 가 책임지므로 ``is_master`` 인 metadata 는 본 test 가 scope
    drift 로 잡지 않는다 (master 가 scope decorator 보다 우선).
    """
    meta_by_path = {m.path: m for m in iter_command_auth_metadata()}

    for path, contract in CLI_COMMAND_REGISTRY.items():
        meta = meta_by_path.get(path)
        if meta is None:
            # Click tree 에 없는 path 가 등록된 경우 — leaf_coverage test 가
            # 별도로 잡는다. 본 test 는 auth-shape 정합만 본다.
            continue

        if contract.auth.mode == "scoped":
            assert contract.auth.scopes == meta.scopes, (
                f"{path}: registry auth.scopes={sorted(contract.auth.scopes)} "
                f"이지만 @require_scope marker={sorted(meta.scopes)}. "
                f"decorator 또는 registry entry 중 한 쪽이 drift."
            )
        elif meta.scopes and not meta.is_master:
            # master 가 부착된 경우는 Family C 가 책임. master 가 아닌데
            # decorator scope marker 가 있는데 registry mode 가 scoped 가
            # 아니면 drift.
            raise AssertionError(
                f"{path}: callback 에 @require_scope marker="
                f"{sorted(meta.scopes)} 가 있지만 registry "
                f"auth.mode='{contract.auth.mode}' (scoped 기대). "
                f"decorator 또는 registry entry 중 한 쪽이 drift."
            )


# ── Family C — registry ↔ @require_master (master) ────────────────────────


def test_family_c_require_master_decorator_drift() -> None:
    """Family C: registered master entry 와 decorator marker 일치.

    Drift 조건 (FAIL):

    - registry ``auth.mode == "master"`` 인 path 의 callback 에
      ``_require_master_applied`` marker 가 없음.
    - decorator marker (``_require_master_applied``) 가 있는데 registry
      ``auth.mode`` 가 ``"master"`` 가 아님.

    미등록 leaf 는 검증하지 않는다.
    """
    meta_by_path = {m.path: m for m in iter_command_auth_metadata()}

    for path, contract in CLI_COMMAND_REGISTRY.items():
        meta = meta_by_path.get(path)
        if meta is None:
            continue

        if contract.auth.mode == "master":
            assert meta.is_master, (
                f"{path}: registry auth.mode='master' 이지만 callback 에 "
                f"@require_master marker 가 없다. decorator 누락 또는 "
                f"registry entry 가 drift."
            )
        elif meta.is_master:
            raise AssertionError(
                f"{path}: callback 에 @require_master marker 가 있지만 "
                f"registry auth.mode='{contract.auth.mode}' (master 기대). "
                f"decorator 또는 registry entry 중 한 쪽이 drift."
            )


# ── Family D — registry ↔ @require_auth (authenticated fallback) ──────────


def test_family_d_authenticated_fallback_drift() -> None:
    """Family D: requires_auth 만 부착된 leaf 는 ``auth.mode == "authenticated"``.

    Drift 조건 (FAIL):

    - registry ``auth.mode == "authenticated"`` 인데 callback 의
      ``_require_auth_applied`` / ``_wrapped_by_authenticated_group`` marker
      가 없거나, 또는 master/scoped 가 함께 표시되어 있음 (fallback 의미
      충돌).
    - callback 이 public/master/scoped 가 아니지만 인증은 요구되는
      (requires_auth=True, is_master=False, scopes=empty, is_public=False)
      leaf 가 registry 에 등록되었는데 ``auth.mode`` 가 ``"authenticated"``
      가 아님.

    분류 우선순위 (`AuthMetadata` docstring 참조):
    public → master → scoped → authenticated. 본 test 는 마지막 fallback
    인 authenticated 만 책임진다.

    미등록 leaf 는 검증하지 않는다.
    """
    meta_by_path = {m.path: m for m in iter_command_auth_metadata()}

    for path, contract in CLI_COMMAND_REGISTRY.items():
        meta = meta_by_path.get(path)
        if meta is None:
            continue

        # authenticated 분류 조건: requires_auth=True 이고 public/master/
        # scoped 어느 family 에도 매치하지 않음.
        is_authenticated_only = (
            meta.requires_auth
            and not meta.is_public
            and not meta.is_master
            and not meta.scopes
        )

        if contract.auth.mode == "authenticated":
            assert meta.requires_auth, (
                f"{path}: registry auth.mode='authenticated' 이지만 callback "
                f"에 인증 marker (@require_auth 또는 AuthenticatedGroup) 가 "
                f"없다. decorator 누락 또는 registry entry 가 drift."
            )
            assert is_authenticated_only, (
                f"{path}: registry auth.mode='authenticated' 인데 callback "
                f"이 다른 family marker 도 가짐 (is_public={meta.is_public}, "
                f"is_master={meta.is_master}, scopes={sorted(meta.scopes)}). "
                f"Family 우선순위(public → master → scoped → authenticated) "
                f"위반."
            )
        elif is_authenticated_only:
            raise AssertionError(
                f"{path}: callback 이 authenticated-only fallback (인증만 "
                f"요구, scope/master 없음) 인데 registry "
                f"auth.mode='{contract.auth.mode}' (authenticated 기대). "
                f"decorator 또는 registry entry 중 한 쪽이 drift."
            )


# ── activation lock (#1846 — vacuous baseline 종료) ───────────────────────


def test_registry_auth_drift_is_active() -> None:
    """#1846 가 account 9 entries 를 등록하면서 deferred lock 이 활성화되었다.

    #1845 시점에는 ``CLI_COMMAND_REGISTRY`` 가 빈 dict 라 4 drift test 가
    모두 vacuous pass 였다 (``test_registry_auth_drift_baseline_is_vacuous``
    가 빈 dict 를 단언). #1846 가 account entries 를 등록하면서 본 단언은
    "registry 에 entry 가 1 개 이상 존재한다" 로 갱신되었다 — 4 drift test
    가 이제 실제 검증을 수행한다. 미등록 leaf FAIL enforcement 는 `#1848`
    의 책임이다.
    """
    assert len(CLI_COMMAND_REGISTRY) > 0, (
        "본 PR (#1846) 시점 CLI_COMMAND_REGISTRY 는 account 9 entries 가 "
        "등록되어 있어야 한다. account migration 회귀가 의심된다."
    )
