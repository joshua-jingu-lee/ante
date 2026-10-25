"""주문 생애주기 이벤트 ``exchange`` 전파 불변식 락 (#2487).

`docs/specs/eventbus/eventbus.md` 는 주문 생애주기 이벤트 페이로드가
``exchange`` 를 나른다고 정의한다. 그런데 생산자가 그 필드를 설정하지 않으면
``events.py`` 의 기본값 ``"KRX"`` 로 조용히 떨어지고, 그 값이
``trades.exchange`` / ``position_history.exchange`` 에 **영속 기록**된다.
읽는 코드가 아직 없어 사용자에게 보이지 않으므로 런타임 테스트로는 잡히지
않는다 — 그래서 정적 불변식으로 잠근다.

**도출 규칙 (고정)**: ``src/ante/eventbus/events.py`` 에 정의된 클래스 중

1. 이름이 ``Order`` 로 시작하고,
2. ``exchange`` :class:`ast.AnnAssign` 필드를 가진 것

의 **교집합**. 규칙을 집합의 정의로 닫으므로 「손으로 센 목록이 부분집합이
된다」는 실패 모드가 원천 차단된다. 신규 생애주기 이벤트가 같은 규칙을 만족
하면 별도 갱신 없이 자동 편입된다.

규칙 설계 근거:

* ``Order`` 접두 **단독**으로 도출하면 ``OrderView`` / ``OrderRegistry`` /
  ``OrderAction`` / ``OrderTrackerRecord`` / ``OrderNotFoundError`` 생성자와
  충돌한다 → ``events.py`` 정의 + ``exchange`` 필드의 교집합이어야 한다.
* ``ExternalSignalEvent`` 는 ``exchange`` 필드가 있으나 ``Order`` 접두가 아니라
  배제된다. 배제가 정당한 근거: 유일 생산자
  ``signal/channel.py`` 가 exchange 를 넘기지 않지만 ``bot.py`` 가
  ``exchange=self.exchange`` 로 재구성하므로 결함이 아니다.
* ``exchange`` 필드가 **없는** 이벤트(``OrderCancelEvent`` /
  ``OrderModifyEvent`` / ``OrderModifyRejectedEvent`` /
  ``OrderCancelFailedEvent``)는 스펙(``eventbus.md``)이 그렇게 정의했으므로
  대상이 아니다. 규칙이 자동으로 배제한다.

**``**`` 언패킹 면제 규칙 (고정)**: AST 는 ``OrderFilledEvent(**payload)`` 에서
리터럴 kwarg 를 볼 수 없다. 이름 지정 allowlist 로만 면제하되, **면제는 무조건이
아니라 payload 출처가 ``exchange`` 키를 실제로 만든다는 조건부**다
(:data:`_STAR_UNPACK_EXEMPTIONS` 의 ``payload_*`` 앵커). 짝이 없는 면제는
「신규 생산자가 ``**payload`` 로 우회」라는 구멍이 되어 본 락의 존재 이유를
무효화한다.

allowlist 키는 ``(repo-relative 경로, 감싸는 함수명)`` 이다 — **줄 번호를 쓰지
않는다**. line-keyed allowlist(``factory_drift_allowlist.yaml``)는 무관한 코드
삽입만으로도 갱신을 요구하는 드리프트 부담을 지므로 승계하지 않는다.

Known limitation (유계 수용): 본 락은 **이벤트** 생산자만 잠근다.
``Order`` 명명 규약을 따르지 않는 신규 생애주기 이벤트, 그리고 신규
``TradeRecord`` 생산자는 도출 규칙 밖이다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from tests.unit.contracts.helpers import _iter_python_files, _parse_module

# tests/unit/contracts/test_order_event_exchange_propagation.py
# → parents[3] == repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "ante"
_EVENTS_MODULE = _SRC_ROOT / "eventbus" / "events.py"

# 도출 규칙이 잡아야 하는 것으로 실측 확인된 생애주기 이벤트 (#2487 census).
# 상한이 아니라 **하한**이다 — 규칙이 이 중 하나라도 놓치면(예: 누가 필드를
# 지웠거나 클래스를 옮겼으면) loud 하게 실패시킨다. 신규 이벤트 추가는
# 규칙이 자동 편입하므로 본 상수를 갱신할 필요가 없다.
_KNOWN_EXCHANGE_BEARING_EVENTS = frozenset(
    {
        "OrderRequestEvent",
        "OrderValidatedEvent",
        "OrderRejectedEvent",
        "OrderApprovedEvent",
        "OrderSubmittedEvent",
        "OrderFilledEvent",
        "OrderCancelledEvent",
        "OrderModifyExecutedEvent",
        "OrderFailedEvent",
        "OrderUpdateEvent",
    }
)

# 도출 규칙이 배제해야 하는 것 — 배제 근거는 모듈 docstring 참조.
_KNOWN_EXCLUDED_EVENTS = frozenset(
    {
        "ExternalSignalEvent",
        "OrderCancelEvent",
        "OrderModifyEvent",
        "OrderModifyRejectedEvent",
        "OrderCancelFailedEvent",
    }
)


@dataclass(frozen=True)
class StarUnpackExemption:
    """``**`` 언패킹 생산자의 조건부 면제 선언.

    면제는 **무조건이 아니다**. ``payload_*`` 앵커가 가리키는 함수가 반환하는
    dict 리터럴의 키 집합에 ``"exchange"`` 가 실제로 있을 때에만 성립한다.

    Attributes:
        call_module: ``**`` 언패킹 호출이 있는 파일 (repo-relative POSIX).
        call_function: 그 호출을 감싸는 함수명. **줄 번호를 쓰지 않는다.**
        payload_module: payload 를 만드는 파일 (repo-relative POSIX).
        payload_class: payload 생성 메서드가 속한 클래스명.
        payload_function: payload 를 ``return {...}`` 하는 메서드명.
        reason: 면제 사유.
    """

    call_module: str
    call_function: str
    payload_module: str
    payload_function: str
    payload_class: str | None = None
    reason: str = ""

    @property
    def call_key(self) -> tuple[str, str]:
        return (self.call_module, self.call_function)


# 항목이 1건뿐이라 별도 YAML 을 만들지 않고 모듈 상수로 둔다.
_STAR_UNPACK_EXEMPTIONS: tuple[StarUnpackExemption, ...] = (
    StarUnpackExemption(
        call_module="src/ante/trade/fill_outbox.py",
        call_function="_publish_row",
        payload_module="src/ante/trade/fill_applier.py",
        payload_class="FillApplier",
        payload_function="_build_payload",
        reason=(
            "durable fill outbox 재발행 경로. payload 는 DB 에 저장된 dict 를 "
            "그대로 OrderFilledEvent(**payload) 로 되살린다 — 생성 책임은 "
            "FillApplier._build_payload 에 있다 (#1949, #2487)."
        ),
    ),
)


@dataclass(frozen=True)
class ProducerCallSite:
    """생애주기 이벤트 생성자 호출부의 정적 메타데이터.

    Attributes:
        module: repo-relative POSIX 경로.
        event: 이벤트 클래스명.
        lineno: 호출 줄 (1-based, 진단 메시지 전용 — 락 키가 아니다).
        function: 호출을 감싸는 함수명. 없으면 ``""``.
        has_literal_exchange: ``exchange=`` 리터럴 kwarg 존재 여부.
        has_star_unpack: ``**mapping`` 언패킹 존재 여부.
    """

    module: str
    event: str
    lineno: int
    function: str
    has_literal_exchange: bool
    has_star_unpack: bool

    @property
    def call_key(self) -> tuple[str, str]:
        return (self.module, self.function)

    def describe(self) -> str:
        where = self.function or "<module>"
        return f"{self.module}:{self.lineno} {self.event}() in {where}"


def _rel(path: Path) -> str:
    """repo-relative POSIX 문자열 (allowlist 키와 비교 가능한 형태)."""
    return path.resolve().relative_to(_REPO_ROOT).as_posix()


def _has_exchange_field(node: ast.ClassDef) -> bool:
    """class body 에 ``exchange`` :class:`ast.AnnAssign` 이 있는지."""
    return any(
        isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and stmt.target.id == "exchange"
        for stmt in node.body
    )


def collect_exchange_bearing_order_events() -> frozenset[str]:
    """도출 규칙을 적용해 대상 이벤트 클래스명 집합을 반환한다.

    ``events.py`` 를 :func:`ast.parse` 로 읽는다 — import side effect 를 피하는
    ``helpers`` 의 AST 선례를 따른다.
    """
    module = _parse_module(_EVENTS_MODULE)
    assert module is not None, f"{_rel(_EVENTS_MODULE)} 파싱 실패"
    return frozenset(
        node.name
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name.startswith("Order")
        and _has_exchange_field(node)
    )


class _ProducerCollector(ast.NodeVisitor):
    """감싸는 함수명을 추적하며 대상 이벤트 생성자 호출을 수집한다."""

    def __init__(self, module_rel: str, targets: frozenset[str]) -> None:
        self._module = module_rel
        self._targets = targets
        self._func_stack: list[str] = []
        self.sites: list[ProducerCallSite] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name) and func.id in self._targets:
            self.sites.append(
                ProducerCallSite(
                    module=self._module,
                    event=func.id,
                    lineno=node.lineno,
                    function=self._func_stack[-1] if self._func_stack else "",
                    has_literal_exchange=any(
                        kw.arg == "exchange" for kw in node.keywords
                    ),
                    has_star_unpack=any(kw.arg is None for kw in node.keywords),
                )
            )
        self.generic_visit(node)


def collect_producer_call_sites() -> list[ProducerCallSite]:
    """``src/ante`` 전체에서 대상 이벤트 생성자 호출부를 수집한다."""
    targets = collect_exchange_bearing_order_events()
    sites: list[ProducerCallSite] = []
    for path in _iter_python_files(_SRC_ROOT):
        module = _parse_module(path)
        if module is None:
            continue
        collector = _ProducerCollector(_rel(path), targets)
        collector.visit(module)
        sites.extend(collector.sites)
    return sites


def _returned_dict_literal_keys(
    module_rel: str,
    function_name: str,
    class_name: str | None,
) -> frozenset[str] | None:
    """지정 함수가 ``return {...}`` 하는 dict 리터럴의 문자열 키 집합.

    함수를 찾지 못하면 ``None`` (앵커 staleness 신호). 여러 ``return`` 이 있으면
    모든 dict 리터럴 키의 합집합을 반환한다.
    """
    path = _REPO_ROOT / module_rel
    module = _parse_module(path)
    if module is None:
        return None

    scope: ast.AST | None = None
    if class_name is None:
        scope = module
    else:
        for node in ast.walk(module):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                scope = node
                break
    if scope is None:
        return None

    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(scope):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == function_name
        ):
            target = node
            break
    if target is None:
        return None

    keys: set[str] = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            for key in node.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    keys.add(key.value)
    return frozenset(keys)


def _exemption_is_satisfied(exemption: StarUnpackExemption) -> bool:
    """면제의 payload 출처가 실제로 ``exchange`` 키를 만드는지."""
    keys = _returned_dict_literal_keys(
        exemption.payload_module,
        exemption.payload_function,
        exemption.payload_class,
    )
    return keys is not None and "exchange" in keys


# ── 도출 규칙 자체의 건전성 ────────────────────────────────────────────────


def test_derivation_rule_covers_known_lifecycle_events() -> None:
    """도출 규칙이 실측 확인된 생애주기 이벤트를 전부 포함해야 한다.

    :data:`_KNOWN_EXCHANGE_BEARING_EVENTS` 는 상한이 아니라 하한이다 — 신규
    이벤트는 규칙이 자동 편입하므로 상수 갱신이 불필요하고, 기존 이벤트에서
    ``exchange`` 필드가 사라지면(스펙 변경 없는 조용한 축소) 여기서 잡힌다.
    """
    derived = collect_exchange_bearing_order_events()
    missing = sorted(_KNOWN_EXCHANGE_BEARING_EVENTS - derived)
    assert not missing, (
        "도출 규칙이 알려진 생애주기 이벤트를 놓쳤다 "
        f"(events.py 에서 exchange 필드가 사라졌거나 클래스가 이동): {missing}"
    )


def test_derivation_rule_excludes_non_lifecycle_classes() -> None:
    """exchange 필드가 없는 이벤트와 ``Order`` 접두 아닌 클래스는 배제된다.

    배제 근거는 모듈 docstring 참조. 특히 ``OrderCancelFailedEvent`` 는
    ``gateway._on_order_cancel`` 안에서 ``OrderCancelledEvent`` 바로 옆에
    생성되므로 우발적 범위 침범 확률이 가장 높다 — 배제를 명시 락한다.
    """
    derived = collect_exchange_bearing_order_events()
    leaked = sorted(_KNOWN_EXCLUDED_EVENTS & derived)
    assert not leaked, (
        "도출 규칙이 배제 대상을 포함했다 — 스펙(eventbus.md)이 exchange 를 "
        f"정의하지 않은 이벤트에 필드가 추가됐는지 확인하라: {leaked}"
    )


def test_producer_sweep_finds_call_sites() -> None:
    """스윕이 호출부를 하나도 못 찾으면 락이 vacuous 하게 통과한다.

    경로/규칙이 깨져 0건이 되는 실패 모드를 명시적으로 차단한다.
    """
    sites = collect_producer_call_sites()
    assert sites, (
        f"{_rel(_SRC_ROOT)} 에서 생애주기 이벤트 생성자 호출을 하나도 찾지 못했다 "
        "— 경로 앵커 또는 도출 규칙이 깨졌다"
    )


# ── 핵심 불변식 ────────────────────────────────────────────────────────────


def test_all_lifecycle_producers_propagate_exchange() -> None:
    """모든 생산자가 ``exchange`` 를 설정해야 한다 (#2487).

    면제는 :data:`_STAR_UNPACK_EXEMPTIONS` 에 선언된 ``**`` 언패킹 호출부에
    한하며, **payload 출처가 ``exchange`` 키를 실제로 만들 때에만** 성립한다.

    실패 시 후속 작업 가이드:

    * 호출부에 ``exchange=`` 를 추가하라. 값 소스는 보통 핸들러의
      ``event.exchange`` 이며, 그 이벤트에 exchange 필드가 없으면
      ``OrderTracker`` record(``record.exchange or "KRX"``)가 유일한 정당
      소스다.
    * ``**payload`` 로 재구성하는 신규 경로라면
      :data:`_STAR_UNPACK_EXEMPTIONS` 에 payload 출처 앵커와 함께 등록하라.
      앵커 없는 면제는 허용되지 않는다.
    """
    satisfied_keys = {
        exemption.call_key
        for exemption in _STAR_UNPACK_EXEMPTIONS
        if _exemption_is_satisfied(exemption)
    }
    violations = [
        site
        for site in collect_producer_call_sites()
        if not site.has_literal_exchange
        and not (site.has_star_unpack and site.call_key in satisfied_keys)
    ]
    assert not violations, (
        f"exchange 를 전파하지 않는 주문 생애주기 이벤트 생산자 {len(violations)}건:\n"
        + "\n".join(f"  - {site.describe()}" for site in sorted(violations, key=str))
    )


def test_star_unpack_exemptions_have_live_payload_sources() -> None:
    """면제마다 짝지어진 payload 출처가 ``exchange`` 키를 만들어야 한다.

    짝이 없으면 면제 자체가 「신규 생산자가 ``**payload`` 로 우회」라는 구멍이
    된다. 본 테스트는 그 짝을 독립적으로 검증해 진단 메시지를 분리한다.
    """
    broken: list[str] = []
    for exemption in _STAR_UNPACK_EXEMPTIONS:
        keys = _returned_dict_literal_keys(
            exemption.payload_module,
            exemption.payload_function,
            exemption.payload_class,
        )
        if keys is None:
            broken.append(
                f"{exemption.payload_module}::{exemption.payload_class}."
                f"{exemption.payload_function} 를 찾을 수 없다 (앵커 stale)"
            )
        elif "exchange" not in keys:
            broken.append(
                f"{exemption.payload_module}::{exemption.payload_class}."
                f"{exemption.payload_function} 반환 dict 에 'exchange' 키가 없다 "
                f"(현재 키: {sorted(keys)})"
            )
    assert not broken, "면제의 payload 출처 검증 실패:\n" + "\n".join(
        f"  - {item}" for item in broken
    )


def test_star_unpack_exemptions_are_not_stale() -> None:
    """선언된 면제 항목은 실제 ``**`` 언패킹 호출부와 일치해야 한다.

    호출부가 사라졌거나 리터럴 kwarg 로 바뀌었으면 면제를 걷어내야 한다 —
    죽은 면제가 남으면 이후 같은 위치의 신규 우회를 조용히 통과시킨다.
    """
    star_keys = {
        site.call_key for site in collect_producer_call_sites() if site.has_star_unpack
    }
    stale = [
        f"{exemption.call_module}::{exemption.call_function}"
        for exemption in _STAR_UNPACK_EXEMPTIONS
        if exemption.call_key not in star_keys
    ]
    assert not stale, (
        "더 이상 존재하지 않는 ``**`` 언패킹 호출부를 면제하고 있다 "
        f"(면제를 제거하라): {stale}"
    )
