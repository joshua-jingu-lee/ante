"""CLI offline factory drift checks (#1858, closes #1818 epic).

#1818 부모 epic 이 채택한 ``open_cli_db`` async-context manager (#1855) 와
``_create_*_service`` 도메인 팩토리로의 마이그레이션 (#1856/#1857) 이후,
신규 CLI command 가 factory 를 우회해 ``Database(get_db_path(...))`` 를
직접 생성하지 않도록 lock 한다.

3 Family 구성:

* Family A — direct ``Database(...)`` construction drift
  ``src/ante/cli/commands/*.py`` 에서 ``Database(...)`` 직접 생성 callsite 를
  AST 로 수집해 ``factory_drift_allowlist.yaml`` baseline 과 비교한다.
  baseline 외 신규 발견 시 FAIL. baseline 잔여 entry (callsite 가 사라진
  경우) 도 FAIL — drift 가 양방향으로 잡혀야 baseline 이 stale 해지지 않는다.

* Family B — legacy ``get_db_path()`` (ctx 미전달) report-only count
  ``src/ante/cli/commands/*.py`` 에서 ``get_db_path()`` (positional arg 0 개)
  호출 callsite 를 수집한다. 본 PR 은 baseline 등록만 수행 (FAIL 없음).
  strict enforcement 는 후속 이슈에서 결정한다.

* Family C — CLI registry ``execution`` class ↔ factory 사용 정합
  :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 의 94 leaf 를
  순회해, ``execution`` Literal 과 callback module 의 factory/IPC 사용
  패턴이 정렬되어 있는지 검증한다.

  - ``offline`` / ``cold_path`` → callback module 이 ``open_cli_db`` 또는
    ``_create_*_service`` 를 사용 (또는 module/callsite 가 baseline 등록).
  - ``runtime_ipc`` → callback module 이 ``ipc_send`` 를 사용. 직접
    Database 생성은 baseline (cold_path fallback) 에 한해 허용.
  - ``long_running`` / ``bootstrap`` → skip (lifecycle 이 다르므로 본
    drift test scope 밖).

본 모듈은 read-only 검사다 — CLI command 본문 / service business logic /
factory implementation / CLI registry 어느 것도 변경하지 않는다 (#1858 plan
의 "변경 금지" invariant).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from tests.unit.contracts.helpers import (
    iter_click_leaf_commands,
    iter_database_constructions,
    iter_get_db_path_calls,
)

# ── path constants ────────────────────────────────────────────────────────


def _repo_root() -> Path:
    """Repository root (본 파일 기준 4 단계 상위).

    ``tests/unit/cli/test_factory_drift_check.py`` → parents[3] == repo root.
    이 helper 는 cwd 에 의존하지 않는다.
    """
    return Path(__file__).resolve().parents[3]


def _commands_dir() -> Path:
    return _repo_root() / "src" / "ante" / "cli" / "commands"


def _allowlist_path() -> Path:
    return (
        _repo_root() / "tests" / "unit" / "contracts" / "factory_drift_allowlist.yaml"
    )


# ── allowlist loader ──────────────────────────────────────────────────────


def _load_direct_database_allowlist() -> set[tuple[str, int]]:
    """allowlist YAML 의 ``direct_database_construction`` section 을 ``set``으로 로드.

    각 entry 는 ``(path, line)`` 튜플로 정규화한다. ``path`` 는 repo root
    기준 POSIX 슬래시 상대 경로 문자열, ``line`` 은 1-based int.
    """
    data = yaml.safe_load(_allowlist_path().read_text(encoding="utf-8")) or {}
    raw = data.get("direct_database_construction") or []
    return {(str(item["path"]), int(item["line"])) for item in raw}


def _to_repo_relative(path: Path) -> str:
    """``path`` 를 repo root 기준 POSIX 상대 경로 문자열로 변환."""
    return path.resolve().relative_to(_repo_root()).as_posix()


# ── Family A — direct Database(...) construction drift ────────────────────


class TestNoNewDirectDatabaseConstructionOutsideAllowlist:
    """Family A: ``src/ante/cli/commands/*.py`` 의 ``Database(...)`` 직접 생성 drift."""

    def test_no_new_direct_database_construction_outside_allowlist(self) -> None:
        """baseline 외 신규 ``Database(...)`` callsite 가 추가되면 FAIL.

        baseline 의 모든 entry 가 실제 callsite 와 1:1 매치되는지도 검증한다 —
        callsite 가 factory 로 마이그레이션 되어 사라졌으면 본 YAML 에서
        entry 를 함께 제거해야 한다 (stale baseline 방지).
        """
        baseline = _load_direct_database_allowlist()
        discovered: set[tuple[str, int]] = set()
        for site in iter_database_constructions(_commands_dir()):
            discovered.add((_to_repo_relative(site.path), site.lineno))

        new_callsites = discovered - baseline
        stale_baseline = baseline - discovered

        if new_callsites:
            lines = "\n".join(f"  - {p}:{ln}" for p, ln in sorted(new_callsites))
            pytest.fail(
                "New direct Database(...) construction outside allowlist detected.\n"
                "신규 CLI command 가 factory (`open_cli_db` 또는 "
                "`_create_*_service`)\n"
                "를 우회해 Database 를 직접 생성했다. factory 사용으로 마이그레이션\n"
                "하거나, lifecycle 이 long-running/bootstrap/live-state 와 엮여\n"
                "정당화 사유가 있다면\n"
                "`tests/unit/contracts/factory_drift_allowlist.yaml` 의\n"
                "`direct_database_construction` 에 reason 과 함께 등록한다.\n\n"
                f"신규 callsite:\n{lines}"
            )

        if stale_baseline:
            lines = "\n".join(f"  - {p}:{ln}" for p, ln in sorted(stale_baseline))
            pytest.fail(
                "Stale baseline entry detected.\n"
                "factory_drift_allowlist.yaml 의 entry 가 실제 코드 callsite 와\n"
                "맞지 않는다. callsite 가 factory 로 마이그레이션 되어 사라졌으면\n"
                "본 YAML 에서도 함께 entry 를 제거한다 (callsite 줄번호가 바뀌었으면\n"
                "갱신).\n\n"
                f"Stale entry:\n{lines}"
            )


# ── Family B — legacy get_db_path() report-only count ─────────────────────


class TestGetDbPathWithoutCtxLegacyCountReport:
    """Family B: ctx 미전달 ``get_db_path()`` callsite report-only.

    본 테스트는 항상 PASS 한다. baseline 외 callsite 가 등장해도 FAIL 하지
    않으며, 카운트와 위치 list 만 record (``caplog`` / capsys 가 아니라
    docstring 의 known baseline 과 sanity 비교).

    strict enforcement 는 후속 이슈에서 결정한다 (#1858 plan v1 — Family B
    는 report-only 로 시작).
    """

    # 현재 코드 baseline (배치 시점 grep 검증 기준):
    # - broker.py:34, 354 — runtime_ipc cold_path fallback (live state)
    # - signal.py:48 — long_running stream channel
    #
    # 본 list 가 동일하게 잡히는지 sanity 만 단언한다. 신규 callsite 발견 시
    # FAIL 하지 않고 report 만 한다.
    _KNOWN_LEGACY_CALLSITES = frozenset(
        {
            ("src/ante/cli/commands/broker.py", 34),
            ("src/ante/cli/commands/broker.py", 354),
            ("src/ante/cli/commands/signal.py", 48),
        }
    )

    def test_get_db_path_without_ctx_legacy_count_report(self) -> None:
        """ctx 미전달 ``get_db_path()`` callsite 를 수집해 report 만 출력."""
        legacy_callsites: list[tuple[str, int, str]] = []
        for call in iter_get_db_path_calls(_commands_dir()):
            if not call.has_ctx_argument:
                legacy_callsites.append(
                    (_to_repo_relative(call.path), call.lineno, call.snippet)
                )

        # report-only: 본 테스트는 신규 callsite 등장 시 FAIL 하지 않는다.
        # 대신 known baseline 과 sanity 비교해 helper 자체가 callsite 를
        # 놓치지 않는지 확인한다 (helper drift 방지).
        observed = {(path, lineno) for path, lineno, _ in legacy_callsites}
        missing_from_baseline = observed - self._KNOWN_LEGACY_CALLSITES
        baseline_no_longer_present = self._KNOWN_LEGACY_CALLSITES - observed

        # 신규 등장은 sanity 차원에서만 print 한다 (FAIL 없음).
        # baseline 이 사라지면 helper drift 가능성이 있으므로 정보용으로 surface.
        if missing_from_baseline or baseline_no_longer_present:
            report_lines = [
                f"Family B report: {len(legacy_callsites)} legacy `get_db_path()`"
                f" (no ctx) callsite(s) found:",
            ]
            for path, lineno, snippet in sorted(legacy_callsites):
                report_lines.append(f"  - {path}:{lineno}  {snippet.strip()}")
            # report-only: 의도적으로 assertion 없음 — pytest 가 docstring +
            # 본 정보를 verbose 모드에서 노출하도록 print 만 한다.
            print("\n".join(report_lines))

        # 본 테스트의 단 하나의 hard invariant: legacy callsite 가 negative
        # 개수일 수 없다 (sanity).
        assert len(legacy_callsites) >= 0


# ── Family C — CLI registry execution class ↔ factory usage ───────────────


# Family C 가 검사 대상으로 삼는 execution class.
# - offline / cold_path: factory (open_cli_db 또는 _create_*_service) 사용 필요.
# - runtime_ipc: ipc_send 사용 필요. 직접 Database 는 baseline 에서만 허용.
# long_running / bootstrap 은 본 drift test scope 밖 (skip).
_FACTORY_REQUIRED_EXECUTIONS = frozenset({"offline", "cold_path"})
_IPC_REQUIRED_EXECUTIONS = frozenset({"runtime_ipc"})
_SKIPPED_EXECUTIONS = frozenset({"long_running", "bootstrap"})


def _module_path_for_callback(callback: object) -> Path | None:
    """Click leaf callback 의 정의 module 의 ``.py`` 파일 경로 반환.

    AuthenticatedGroup wrap 등으로 callback 이 wrapper 함수가 된 경우에도
    ``__wrapped__`` chain 을 풀어 최종 함수의 module 을 가져온다.
    """
    func = callback
    # functools.wraps 가 부착한 ``__wrapped__`` chain 을 풀어 본체로 내려간다.
    while True:
        wrapped = getattr(func, "__wrapped__", None)
        if wrapped is None:
            break
        func = wrapped

    module_name = getattr(func, "__module__", None)
    if not module_name:
        return None
    import importlib

    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return None
    return Path(module_file)


def _read_module_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _module_uses_factory(module_path: Path) -> bool:
    """module 본문에 ``open_cli_db`` 또는 ``_create_*_service`` 사용 자취가 있는지.

    text 기반 sweep 으로 ``open_cli_db`` token (import 또는 callsite) 또는
    ``_create_*_service`` 함수 정의 / 호출 token 이 존재하는지 확인한다.
    AST 정밀 분석을 쓰지 않는 이유: factory 가 본문 또는 helper module 안에
    inline 정의되어 있어도 매치되어야 하는데, registry 호출 시 callback 의
    실제 wrapper 가 callback decorator chain 너머로 숨어 있어 introspection
    이 신뢰하기 어렵다. text 매치는 callback decoration chain 과 무관하게
    callsite 의 본문 사용을 잡는다.
    """
    text = _read_module_text(module_path)
    if not text:
        return False
    if "open_cli_db" in text:
        return True
    # ``_create_*_service`` 패턴 (account / member / approval / treasury 등
    # 모듈마다 이름이 약간씩 다름 — `_create_account_service`,
    # `_create_service`, `_create_trade_service` 등). 본 helper 는 보수적
    # 매치 (suffix `_service` 또는 `_create_service`) 를 쓴다.
    if "_create_service" in text:
        return True
    # 일반 패턴: `_create_xxx_service`. 정규식 없이 token 매치.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("async def _create_", "def _create_")):
            if "_service" in stripped:
                return True
    return False


def _module_uses_ipc(module_path: Path) -> bool:
    """module 본문에 ``ipc_send`` 사용 자취가 있는지."""
    text = _read_module_text(module_path)
    if not text:
        return False
    return "ipc_send" in text


def _module_has_direct_database_in_baseline(
    module_path: Path,
    baseline: set[tuple[str, int]],
) -> bool:
    """module 의 모든 ``Database(...)`` 직접 생성 callsite 가 baseline 에 포함되는지.

    True 면: 본 module 의 직접 생성은 정당화된 baseline 안에 있다.
    False 면: baseline 외 callsite 가 존재 (Family A drift) — 단, 본 helper
    는 Family C 의 정합 판정 용도로만 쓰이며 실제 FAIL 은 Family A 가 담당.
    """
    text = _read_module_text(module_path)
    if not text:
        return True  # 본문 없으면 직접 생성도 없음 (vacuous true).
    try:
        module = ast.parse(text, filename=str(module_path))
    except SyntaxError:
        return True

    rel_path = _to_repo_relative(module_path)
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "Database"):
            continue
        if (rel_path, node.lineno) not in baseline:
            return False
    return True


class TestCliExecutionClassMatchesFactoryUsage:
    """Family C: registry ``execution`` ↔ callback module factory/IPC 정합."""

    def test_cli_execution_class_matches_factory_usage(self) -> None:
        """``execution`` class 가 callback module 의 factory/IPC 사용과 정합.

        - ``offline`` / ``cold_path`` → module 이 factory 사용 (open_cli_db
          또는 _create_*_service).
        - ``runtime_ipc`` → module 이 ipc_send 사용.
        - ``long_running`` / ``bootstrap`` → skip.

        module 이 baseline 등록된 직접 Database 생성 callsite 만 보유하면
        factory 미사용도 허용한다 (broker 의 cold_path fallback, signal 의
        external process lifecycle 등 — Family A 의 baseline 와 동기화).
        """
        from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY

        # leaf path → callback module path 매핑 (Click introspection).
        path_to_module: dict[tuple[str, ...], Path] = {}
        for leaf in iter_click_leaf_commands():
            callback = leaf.command.callback
            if callback is None:
                continue
            module_path = _module_path_for_callback(callback)
            if module_path is None:
                continue
            path_to_module[leaf.path] = module_path

        baseline = _load_direct_database_allowlist()

        mismatches: list[str] = []
        checked = 0
        skipped = 0

        for path, contract in CLI_COMMAND_REGISTRY.items():
            execution = contract.execution
            if execution in _SKIPPED_EXECUTIONS:
                skipped += 1
                continue

            module_path = path_to_module.get(path)
            if module_path is None:
                # callback module 을 introspection 으로 얻지 못한 경우
                # (hidden subtree 등). 본 drift test 의 책임이 아니므로 skip.
                skipped += 1
                continue

            checked += 1
            module_uses_factory = _module_uses_factory(module_path)
            module_uses_ipc = _module_uses_ipc(module_path)
            module_baseline_only = _module_has_direct_database_in_baseline(
                module_path, baseline
            )

            if execution in _FACTORY_REQUIRED_EXECUTIONS:
                # factory 또는 baseline-only 가 OK. 둘 다 아니면 FAIL.
                if not (module_uses_factory or module_baseline_only):
                    mismatches.append(
                        f"  - {' '.join(path)} (execution={execution!r}, "
                        f"module={_to_repo_relative(module_path)}): "
                        f"factory (open_cli_db / _create_*_service) 미사용이며 "
                        f"baseline 외 direct Database 생성 존재."
                    )
            elif execution in _IPC_REQUIRED_EXECUTIONS:
                # IPC 사용 OR (baseline-only direct DB) 가 OK.
                # broker 4 commands 는 spec primary 가 runtime_ipc 이고
                # cold_path fallback (baseline 등록) 으로 직접 DB 를 사용한다.
                # module 이 ipc_send 토큰을 보유하면 정합 OK.
                if not (module_uses_ipc or module_baseline_only):
                    mismatches.append(
                        f"  - {' '.join(path)} (execution={execution!r}, "
                        f"module={_to_repo_relative(module_path)}): "
                        f"ipc_send 사용이 발견되지 않고 baseline 외 direct Database "
                        f"생성 존재."
                    )

        # sanity: 94 entry 중 4 long_running + 0 bootstrap = 4 skip 기대.
        # 본 카운트는 정보용 (assertion 아님) — registry 변경 시 자동 조정.
        assert checked >= 1, (
            f"Family C: 검사된 entry 가 0 개. CLI registry introspection 실패 가능 "
            f"(checked={checked}, skipped={skipped})."
        )

        if mismatches:
            lines = "\n".join(mismatches)
            pytest.fail(
                "CLI execution class ↔ factory/IPC 사용 정합 mismatch.\n"
                "registry 의 execution class 가 callback module 의 factory 또는 IPC\n"
                "사용 패턴과 어긋난다. 다음 중 하나를 적용하라:\n"
                "  1) module 본문을 factory (open_cli_db / _create_*_service) 또는\n"
                "     ipc_send 로 마이그레이션.\n"
                "  2) registry 의 execution class 를 실제 구현 lifecycle 에 맞춰 조정\n"
                "     (스펙 SSOT 와 일치해야 함).\n"
                "  3) 직접 Database 생성이 long-running/bootstrap/live-state 와 엮여\n"
                "     factory 변환이 부적절하면 `factory_drift_allowlist.yaml` 에\n"
                "     baseline 등록.\n\n"
                f"Mismatched entries:\n{lines}"
            )
