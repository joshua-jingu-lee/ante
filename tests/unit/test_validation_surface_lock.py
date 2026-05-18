"""비-``extra_forbidden`` caller-controlled ``loc`` 종합 정책 — S1∪S2
self-enumerate default-deny discovery lock (#1651, #1643 Split B).

성격: **런타임 무변경** (옵션3 하이브리드 — 2026-05-17 사용자/대표
결정). ``src/ante/web/errors.py`` 런타임은 #1650 그대로 두고 본 파일은
**test-only** 정적 discovery lock 으로 비-``extra_forbidden``
caller-supplied 문자열 식별자 ``loc`` 벡터를 merge 전 봉인한다.

## PASS-computation 구조 (이슈 #1651 INV-1..5 봉인 — 단일 형태)

@code-reviewer 메타리뷰가 Codex 2연속 fail-open FAIL 의 근본원인을
``proven=f(discovered)`` self-defeat / walker 내부 노드별
plausibility-OR 로 진단했다. 본 모듈은 PASS 판정을 **단일 함수**로
재집약한다(스팟 수정 금지):

- **INV-1 (물리 분리)**: ``DISCOVERED`` (introspection self-derive —
  ``_discover`` enumeration walk 만 채움) 와 ``REGISTERED_STATIC``
  (정적 리터럴 선언: dict 축 ``_REGISTERED_DICT_PROOFS`` · validator
  축 ``_REGISTERED_VALIDATOR_SURFACE_IDS``) 는 **서로 다른 코드
  경로**. ``REGISTERED_STATIC`` 을 만드는 코드는 introspection 함수
  (``_iter_model_validators``/``_validator_markers``/enumeration walk)
  를 **절대 호출하지 않는다** — 명시 리터럴 surface-id/필드-키
  집합이다(재도출 시 ``proven=f(discovered)`` self-defeating).
- **INV-2 (enumeration·verdict 분리)**: ``_discover`` walk 는
  **verdict 없이** 트리 전 노드를 끝까지 방문해 ``DISCOVERED`` 만
  채운다(미증명 unsafe 노드에서 short-circuit/``return`` 금지 — 기록
  하고 계속). PASS 는 walk 종료 후 단 한 곳(``compute_verdict``)에서
  ``UNPROVEN = DISCOVERED − REGISTERED_STATIC``,
  ``PASS ⟺ (UNPROVEN == ∅ ∧ unresolvable == ∅)`` 로만 계산한다.
- **INV-3 (single fail-closed sink)**: 정적 resolve 불가(dynamic
  helper 인자·미해결 receiver·미지 mount/route·unwalkable origin)
  전부 단일 ``unresolvable`` 집합에 모이고 ``unresolvable ≠ ∅ ⟹
  무조건 FAIL``. helper-trace 는 site 의 model 인자 중 정적
  literal-BaseModel resolve 안 되는 게 하나라도 있으면 site 전체
  unresolvable(any-match → all-must-resolve).
- **INV-4 (per-identifier 1:1 behavioral)**: 각 ``REGISTERED_STATIC``
  항목(dict (owner,field) 키 / validator surface-id)은 그 식별자
  **단위로** behavioral 증명과 1:1. validator canary 는 모델-단위
  'ValidationError 한 번' 이 아니라 등록 surface-id **각각**이
  sentinel 주입 시 loc=static·sentinel∉detail 임을 개별 증명.
- **INV-5 (self-defeat 회귀 canary)**: ``REGISTERED_STATIC`` 공집합
  치환 시 현 S1∪S2 의 모든 validator-bearing·비-``dict[str,Any]``
  surface 가 전수 FAIL 함을 단언(RC-1 영구 락 — red 면
  ``proven=f(discovered)`` 재발).

본 lock 은 #1643 v11 default-deny 락 계약을 1:1 재사용한다(재유도
금지). 검사 surface 의 개수도 고정 모델/필드 멤버명도 lock 입력으로
하드코딩하지 않는다 — ``DISCOVERED`` introspection self-derive 가 유일
SSOT 이며 미등록·미증명 항목은 fail-closed 다. (``REGISTERED_STATIC``
리터럴은 lock 입력이 아니라 INV-1 정적 proof 축이다 — 등록
behavioral 증명 1:1 식별자.)

해석 B(2026-05-18 사용자/대표 결정): bounded 정수 수열 인덱스
(``list``/``tuple``/``set`` element 위치)는 invariant 대상이 아니므로
container 를 인덱스 사유로 unsafe 기록하지 않는다(element TYPE 이
unsafe 면 그 element 노드를 기록 — 인덱스 면제 ≠ element-TYPE 면제).

I-flat 은 #1651 lock invariant 가 아니다(#1650 extra_forbidden 런타임
소유 — safe forbid/nested BaseModel 은 PASS).

현 실측 (비-normative · 검증용 · lock 입력 아님 · impl/meta 가 lock 에
복사 금지 — 본 주석과 lock 결과가 어긋나면 lock 이 정답):
- S2(FastAPI body introspection) = 요청모델 1건(flat, dict/nested 0)
- S1∪S2 self-enumerate validator surface 는 전부 plain ``ValueError`` →
  static field-path loc · sentinel∉detail(live leak 0)
- 비-``dict[str,Any]`` dict 노드는 STRUCTURAL-rejection 4xx 가 소유
  모델 ``model_validate`` 이전 발화하는 1개 경로뿐(나머지 0)
- cold-path-409·openapi_extra-only 모델은 S1∪S2 정의상 자동 비포함
"""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import enum
import importlib
import re
import types
import typing
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple, Union, get_args, get_origin

import pydantic
import pytest
import typing_extensions

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi import Body, Depends, FastAPI  # noqa: E402
from fastapi.dependencies.utils import get_flat_dependant  # noqa: E402
from fastapi.routing import APIRoute, APIRouter  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import (  # noqa: E402
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainValidator,
    RootModel,
    TypeAdapter,
    WrapValidator,
    field_validator,
)
from starlette.applications import Starlette  # noqa: E402
from starlette.routing import (  # noqa: E402
    Mount,
    Route,
    Router,
    WebSocketRoute,
)

from ante.web.app import create_app  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTES_DIR = _REPO_ROOT / "src" / "ante" / "web" / "routes"
_ROUTES_PKG = "ante.web.routes"

# #1651 검증판 명문(스펙 SSOT 일치) — introspection 의미 게이트는
# CV1/CV3 canary 이고 본 핀은 회귀 진단 보조.
_VERIFIED_FASTAPI_VERSION = "0.135.1"

# caller-controlled sentinel — 422 detail/loc 어디에도 등장하면 안 된다.
SENTINEL = "SNTNL_1651_lockf00dbeef"


# ════════════════════════════════════════════════════════════════════
# 공유 introspection primitive (DISCOVERED 전용 — INV-1)
# ════════════════════════════════════════════════════════════════════
#
# 아래 primitive 는 **introspection self-derive** 다. INV-1 에 따라
# DISCOVERED 산출 경로(``_discover``/``_enumerate_*``)에서만 호출하며
# REGISTERED_STATIC 산출 경로는 이 함수들을 절대 호출하지 않는다.


_LEAF_SAFE_TYPES: tuple[type, ...] = (
    str,
    int,
    float,
    bool,
    bytes,
    Decimal,
)

# 인식 container origin — 모든 type 인자가 재귀 safe 여야 PASS.
_CONTAINER_ORIGINS: tuple[Any, ...] = (
    list,
    tuple,
    set,
    frozenset,
)

_VALIDATOR_MARKER_TYPES: tuple[type, ...] = (
    AfterValidator,
    BeforeValidator,
    WrapValidator,
    PlainValidator,
)


def _is_leaf_safe(tp: Any) -> bool:
    if tp is None or tp is type(None) or tp is Any:
        return True
    try:
        import datetime as _dt
        import uuid as _uuid

        if tp in (_dt.datetime, _dt.date, _dt.time, _uuid.UUID):
            return True
    except Exception:  # pragma: no cover - 방어
        pass
    if isinstance(tp, type):
        if issubclass(tp, _LEAF_SAFE_TYPES):
            return True
        if issubclass(tp, enum.Enum):
            return True
    return False


def _validator_markers(metadata: typing.Iterable[Any]) -> list[Any]:
    """field metadata 에서 validator/custom core-schema provider 추출.

    pydantic 은 ``Annotated[X, *Validator]`` 의 X 만 ``fi.annotation`` 에
    남기고 validator 는 ``fi.metadata`` 로 분리하므로, enumeration 은
    metadata 를 검사해 opaque validator surface 를 self-enumerate 한다.
    """
    out: list[Any] = []
    for meta in metadata:
        if isinstance(meta, _VALIDATOR_MARKER_TYPES):
            out.append(meta)
        elif hasattr(meta, "__get_pydantic_core_schema__"):
            out.append(meta)
    return out


def _iter_model_validators(model: type[BaseModel]) -> list[str]:
    """모델의 field/model validator + v1 호환 validator surface 식별자.

    하드코딩 금지 — ``__pydantic_decorators__`` 전 맵에서 self-derive.
    """
    dec = getattr(model, "__pydantic_decorators__", None)
    if dec is None:
        return []
    names: list[str] = []
    _decorator_attrs = (
        "field_validators",
        "model_validators",
        "validators",
        "root_validators",
    )
    for attr in _decorator_attrs:
        bag = getattr(dec, attr, None) or {}
        for key in bag:
            names.append(f"{model.__module__}.{model.__qualname__}::{attr}::{key}")
    return names


def _field_annotated_validator_sid(model: type[BaseModel], fname: str) -> str:
    return (
        f"{model.__module__}.{model.__qualname__}::field_annotated_validator::{fname}"
    )


# ════════════════════════════════════════════════════════════════════
# DISCOVERED: verdict-free enumeration walk (INV-2)
# ════════════════════════════════════════════════════════════════════
#
# ``_discover`` 는 annotation 트리를 끝까지 enumeration 한다. PASS/FAIL
# verdict 를 내지 않고(short-circuit/``return False`` 없음) 발견한
# 모든 사실을 ``Discovered`` 에 축적한다. verdict 는 ``compute_verdict``
# 단일 지점에서 set-difference 로만 계산된다(INV-2).


@dataclasses.dataclass
class Discovered:
    """enumeration 결과 — verdict 없음. introspection self-derive 사실."""

    # 비-``dict[str,Any]`` dict 노드 키 (owner qualname, owner-relative
    # field/annotation-path, **validating-site**). validating-site =
    # 그 dict 노드가 검증되는 S1 callee(module:callee_src) 또는 S2
    # route+entrypoint(route_path#entrypoint) 식별자. INV-1 정밀화
    # (Codex `review-mpagchqw` [P2]): pre-validation-reject 가드는
    # **특정 검증-site 의 속성**이므로 (owner,field) 만으로 키하면 동일
    # 모델/필드를 검증하는 **다른** S1 callee/S2 route+entrypoint 에
    # 증명이 재사용돼 가드 없는 site 가 통과(fail-open). site 를 키에
    # 포함해 set-difference 가 (owner,path,site) 단위로 계산되어야
    # 가드 있는 site 만 PASS, 가드 없는 다른 site 는 UNPROVEN→FAIL.
    # site 는 자연 floor(가드 유무는 검증-site 별 사실 — 더 미세 단위
    # 불요).
    dict_nodes: set[tuple[str, str, str]] = dataclasses.field(default_factory=set)
    # validator/Annotated[*Validator]/custom-core-schema surface-id 전수.
    validator_surfaces: set[str] = dataclasses.field(default_factory=set)
    # safe-allowlist 에 **양성 매칭되지 않은** 비-dict·비-validator
    # 노드(extra='allow'/RootModel/dataclass/TypedDict/NamedTuple/
    # unknown/opaque generic 등). 이 집합은 ``REGISTERED_STATIC`` 으로
    # 절대 해제되지 않는다 — 비어 있어야 PASS(default-deny).
    unsafe_nodes: list[str] = dataclasses.field(default_factory=list)

    def merge(self, other: Discovered) -> None:
        self.dict_nodes |= other.dict_nodes
        self.validator_surfaces |= other.validator_surfaces
        self.unsafe_nodes.extend(other.unsafe_nodes)


def _owner_field_key(
    owner: type | None, path: str, validating_site: str
) -> tuple[str, str, str]:
    """비-``dict[str,Any]`` dict 노드를 **(owner qualname,
    owner-relative field/annotation-path, validating-site)** 키로
    정규화(INV-1 정밀화 — site 포함).

    walker path 형식: ``<root>...<Owner>.<field>`` + container/Union
    위치 표식(``|N``/``[N]``). 매칭 키는 owner qualname + container
    인덱스 표식을 제거한 owner-relative field-path + **그 노드가
    검증되는 site** 다. 같은 owner 라도 **다른** ``dict[str,T]``
    필드가 추가되면 그 (owner,field,site) 가 별도 키가 되고, **같은
    (owner,field) 라도 다른 검증-site**(S1 callee / S2
    route+entrypoint)에서 발견되면 그 site 별 키가 별도가 되어 한
    site 의 pre-reject 증명이 가드 없는 다른 site 로 재사용되지
    않는다(per-(owner,field,site) — fail-open 차단).
    """
    oq = owner.__qualname__ if owner is not None else "<root>"
    cleaned = re.sub(r"[|\[][0-9]+\]?", "", path)
    segs = [s for s in cleaned.split(".") if s]
    field = segs[-1] if segs else cleaned
    last_idx = -1
    for i, s in enumerate(segs):
        if s == oq:
            last_idx = i
    if last_idx != -1 and last_idx + 1 < len(segs):
        field = ".".join(segs[last_idx + 1 :])
    return (oq, field, validating_site)


def _discover(  # noqa: C901 - enumeration 은 단일 책임이나 타입 분기多
    tp: Any,
    path: str,
    disc: Discovered,
    *,
    validating_site: str,
    seen: frozenset[int] = frozenset(),
    owner: type | None = None,
) -> None:
    """annotation 타입 트리 **verdict-free** enumeration (INV-2).

    트리 전 노드를 끝까지 방문하며(short-circuit 금지) 발견 사실만
    ``disc`` 에 축적한다. 어느 노드도 verdict(PASS/FAIL)를 내지
    않는다 — PASS 는 ``compute_verdict`` 단일 지점에서만.

    safe-allowlist 양성 매칭 노드는 아무것도 기록하지 않는다(자식
    재귀만). 비-``dict[str,Any]`` dict 노드 → ``dict_nodes``.
    validator/Annotated[*Validator] surface → ``validator_surfaces``.
    그 외 일체(extra='allow'/RootModel/dataclass/TypedDict/NamedTuple/
    unknown)는 ``unsafe_nodes`` (REGISTERED_STATIC 으로 해제 불가).
    해석 B: bounded 정수 element 인덱스 자체는 위반 아님 — container
    를 인덱스 사유로 unsafe 기록하지 않는다(element TYPE 만 재귀).
    """
    # leaf-safe — 안전. 아무것도 기록하지 않고 종료(자식 없음).
    if _is_leaf_safe(tp):
        return

    origin = get_origin(tp)

    # Annotated[X, *meta]: 구조 메타 unwrap. validator/custom
    # core-schema 제공자 → surface-id 기록(opaque) 후 inner 계속 walk.
    if origin is Annotated or (
        origin is None and getattr(tp, "__metadata__", None) is not None
    ):
        args = get_args(tp)
        inner = args[0]
        if _validator_markers(args[1:]):
            disc.validator_surfaces.add(f"{path}::Annotated[*Validator]")
        _discover(
            inner, path, disc, validating_site=validating_site, seen=seen, owner=owner
        )
        return

    # Literal[...] — leaf-safe (값은 caller dict 키 생성 불가).
    if origin is Literal:
        return

    # Optional/Union 계열 — 모든 인자 재귀(verdict 없음).
    if origin is Union or origin is getattr(types, "UnionType", None):
        for i, arg in enumerate(get_args(tp)):
            _discover(
                arg,
                f"{path}|{i}",
                disc,
                validating_site=validating_site,
                seen=seen,
                owner=owner,
            )
        return

    # dict/Mapping 계열 — 정확히 dict[str,Any] 만 safe(기록 안 함).
    if origin in (dict, collections.abc.Mapping, collections.abc.MutableMapping) or (
        isinstance(origin, type) and issubclass(origin, collections.abc.Mapping)
    ):
        args = get_args(tp)
        is_exact_str_any = (
            origin is dict and len(args) == 2 and args[0] is str and args[1] is Any
        )
        if is_exact_str_any:
            return
        # 비-dict[str,Any] dict 노드 — (owner,field,site) 키로 기록.
        disc.dict_nodes.add(_owner_field_key(owner, path, validating_site))
        return

    # 인식 container — element TYPE 만 재귀(해석 B: 인덱스 자체는
    # 위반 아님 → container 를 인덱스 사유로 unsafe 기록하지 않음).
    if origin in _CONTAINER_ORIGINS or (
        isinstance(origin, type)
        and origin is not dict
        and issubclass(origin, (list, tuple, set, frozenset))
    ):
        args = get_args(tp)
        type_args = [a for a in args if a is not Ellipsis]
        for i, arg in enumerate(type_args):
            _discover(
                arg,
                f"{path}[{i}]",
                disc,
                validating_site=validating_site,
                seen=seen,
                owner=owner,
            )
        return

    # pydantic RootModel — opaque structured body → unsafe 기록.
    if isinstance(tp, type) and issubclass(tp, RootModel):
        disc.unsafe_nodes.append(
            f"RootModel structured body at {path}:{tp.__qualname__}"
        )
        return

    # pydantic BaseModel — extra/typed __pydantic_extra__/validator
    # surface 를 기록하고 필드를 **전수** 재귀(verdict 없음 —
    # short-circuit 으로 가려질 자식까지 끝까지 enumeration).
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        if id(tp) in seen:
            return  # 재귀 모델 사이클 방지(이미 walk 중).
        child_seen = seen | {id(tp)}

        extra = tp.model_config.get("extra")
        if extra not in (None, "forbid", "ignore"):
            # pydantic 기본(None) == ignore. 'allow' 는 unsafe.
            disc.unsafe_nodes.append(
                f"BaseModel extra='{extra}' at {path}:{tp.__qualname__}"
            )

        ann = getattr(tp, "__annotations__", {})
        if "__pydantic_extra__" in ann:
            disc.unsafe_nodes.append(
                f"typed __pydantic_extra__ at {path}:{tp.__qualname__}"
            )

        # validator surface 전수 self-enumerate(model decorators ∪
        # field Annotated[*Validator] marker). 기록만 — verdict 없음.
        for v in _iter_model_validators(tp):
            disc.validator_surfaces.add(v)

        for fname, fi in tp.model_fields.items():
            fpath = f"{path}.{tp.__qualname__}.{fname}"
            if _validator_markers(getattr(fi, "metadata", []) or []):
                disc.validator_surfaces.add(_field_annotated_validator_sid(tp, fname))
            # owner = 이 BaseModel — 자식 dict 노드 (owner,field,site) 귀속.
            _discover(
                fi.annotation,
                fpath,
                disc,
                validating_site=validating_site,
                seen=child_seen,
                owner=tp,
            )
        return

    # dataclass / pydantic dataclass
    if dataclasses.is_dataclass(tp):
        disc.unsafe_nodes.append(f"dataclass structured body at {path}")
        return

    # TypedDict
    if typing_extensions.is_typeddict(tp) or (
        hasattr(typing, "is_typeddict") and typing.is_typeddict(tp)
    ):
        disc.unsafe_nodes.append(f"TypedDict structured body at {path}")
        return

    # NamedTuple
    if isinstance(tp, type) and issubclass(tp, tuple) and hasattr(tp, "_fields"):
        disc.unsafe_nodes.append(f"NamedTuple structured body at {path}")
        return

    # 그 외 일체(임의 class/Generic/ForwardRef/미해결 string/unknown)
    # → 증명가능 안전 아님 → unsafe 기록(default-deny 핵심).
    disc.unsafe_nodes.append(
        f"증명가능 안전 아님 (unknown/opaque shape): {tp!r} at {path}"
    )


def discover_annotation(
    tp: Any, path: str = "root", *, validating_site: str = "<canary>"
) -> Discovered:
    """annotation 트리를 verdict-free enumeration 하고 ``Discovered``
    반환. PASS/FAIL 판정은 호출측 ``compute_verdict`` 단일 지점에서만.

    ``validating_site`` = 이 annotation 트리가 검증되는 S1 callee
    (module:callee_src) 또는 S2 route+entrypoint(route_path#entrypoint)
    식별자. 발견되는 비-``dict[str,Any]`` dict 노드 키에 포함되어
    pre-reject 증명이 가드 있는 site 에만 1:1 결합된다(INV-1 정밀화).
    shape canary 는 site-무관이므로 기본 ``<canary>`` 를 쓴다(REGISTERED
    공집합으로 default-deny 극성만 검증 — site granularity 불요).
    """
    disc = Discovered()
    _discover(tp, path, disc, validating_site=validating_site)
    return disc


# ════════════════════════════════════════════════════════════════════
# S1 (a+b origin-complete fail-closed) — raw-body Pydantic 검증 surface
# ════════════════════════════════════════════════════════════════════
#
# S1a: routes/**/*.py 의 raw-body Pydantic 검증 callee 모델 resolve.
# S1b: 모든 Pydantic 검증 entrypoint 가 lock-walked 검증 source 에 1:1
#      (정적 literal-BaseModel resolve) 또는 #1650 chokepoint 경유.
#      정적 resolve 불가 origin/entrypoint 1개라도 → 단일
#      ``unresolvable`` 집합(INV-3, all-must-resolve).


# Pydantic 검증 entrypoint API 표면(self-derive 대상; 손-열거 아님 —
# AST 가 attribute call name 으로 탐지).
_PYDANTIC_ENTRYPOINT_METHODS: frozenset[str] = frozenset(
    {
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
        "validate_python",
        "validate_json",
        "validate_strings",
        "parse_obj",
        "parse_raw",
    }
)

# #1650 chokepoint — raw-body site sanitization SSOT.
_CHOKEPOINT_NAME = "sanitize_validation_errors"


def _route_modules() -> list[tuple[str, Path]]:
    """``ante.web.routes`` 패키지의 **모든 하위 모듈** (dotted name,
    소스 경로) 전수 — 재귀 self-enumerate(손-열거 금지).

    top-level ``routes/*.py`` 만이 아니라 ``routes/**/*.py`` 하위
    패키지 전체를 ``Path.rglob`` 으로 빠짐없이 수집한다. 향후
    ``src/ante/web/routes/foo/bar.py`` 같은 하위 패키지 모듈에
    raw-body Pydantic 검증 callee/entrypoint 가 추가돼도 S1
    discovery 가 그 validation surface 를 놓치지 않도록 한다(top-level
    한정 glob 은 fail-open). ``__init__.py`` 도 포함한다 — 패키지
    초기화 모듈도 핸들러를 호스팅할 수 있으므로 일괄 skip 은 그
    자체로 fail-open 갭이다(``routes/__init__.py`` →
    ``ante.web.routes``, ``routes/foo/__init__.py`` →
    ``ante.web.routes.foo``, ``routes/foo/bar.py`` →
    ``ante.web.routes.foo.bar``).

    dotted module name 은 ``__file__`` 기반 가정 없이 relative path
    에서 직접 도출하므로 하위 패키지 모듈도 ``importlib`` 으로 정확히
    import·AST 추적된다(flat ``rsplit`` 경로 재구성 금지 — INV-3).
    """
    out: list[tuple[str, Path]] = []
    for p in sorted(_ROUTES_DIR.rglob("*.py")):
        rel = p.relative_to(_ROUTES_DIR).with_suffix("")
        parts = list(rel.parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        modname = ".".join([_ROUTES_PKG, *parts]) if parts else _ROUTES_PKG
        out.append((modname, p))
    return out


def _resolve_name_in_module(modname: str, name: str) -> Any:
    """모듈 namespace 에서 이름(클래스)을 resolve. 미발견 None."""
    mod = importlib.import_module(modname)
    return getattr(mod, name, None)


def _module_source_path(modname: str) -> Path | None:
    """모듈의 실제 소스 파일 경로(``__file__``) — routes-dir 가정 금지.

    실 S1 site 는 전부 ``ante.web.routes.*`` 라 결과 동일하지만,
    모듈 객체의 ``__file__`` 로 resolve 하면 routes 밖 helper canary
    (synthetic 모듈)도 동일 코드로 정확히 추적된다.
    """
    try:
        mod = importlib.import_module(modname)
    except Exception:  # pragma: no cover - 방어
        return None
    f = getattr(mod, "__file__", None)
    if not f:
        return None
    p = Path(f)
    return p if p.exists() else None


@dataclasses.dataclass
class _EntrypointSite:
    module: str
    lineno: int
    callee_src: str  # 예: "BotCreateRequest.model_validate"
    receiver: str  # 예: "BotCreateRequest" / "model"
    method: str


def _scan_s1_entrypoints() -> list[_EntrypointSite]:
    """routes/**/*.py AST 에서 Pydantic 검증 entrypoint 호출 전수.

    ``<Recv>.<method>(...)`` 형태의 call 중 method ∈ entrypoint API.
    손-열거 census 금지 — AST self-derive.
    """
    sites: list[_EntrypointSite] = []
    for modname, path in _route_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in _PYDANTIC_ENTRYPOINT_METHODS:
                continue
            recv = func.value
            if isinstance(recv, ast.Name):
                recv_name = recv.id
            else:
                recv_name = ast.unparse(recv)
            sites.append(
                _EntrypointSite(
                    module=modname,
                    lineno=node.lineno,
                    callee_src=f"{recv_name}.{func.attr}",
                    receiver=recv_name,
                    method=func.attr,
                )
            )
    return sites


@dataclasses.dataclass
class _S1Resolve:
    """S1a∪S1b resolve 결과.

    ``models`` = 정적 literal-BaseModel 로 resolve 된 (site_id, model).
    ``unresolvable`` = 정적 resolve 불가 origin/entrypoint(단일 sink —
    INV-3; ≠∅ ⟹ 무조건 FAIL, all-must-resolve).
    """

    models: list[tuple[str, type[BaseModel]]] = dataclasses.field(default_factory=list)
    unresolvable: list[str] = dataclasses.field(default_factory=list)


def _trace_generic_helper_model_args(
    site: _EntrypointSite,
) -> tuple[list[type[BaseModel]], bool]:
    """제네릭 helper(``model.model_validate``)의 model 인자 추적.

    helper 의 ``model`` 파라미터로 전달되는 **모든** 호출 인자를
    검사한다. 반환: (literal-BaseModel 리스트, all_resolved).
    ``all_resolved`` 는 helper 호출 site 의 model 인자가 **하나도
    빠짐없이** 정적 literal-BaseModel 로 resolve 됐을 때만 True
    (any-match → all-must-resolve, INV-3). literal+dynamic 혼재면
    False → 호출측이 단일 ``unresolvable`` 로 보낸다(우회 차단).
    """
    modname = site.module
    src_path = _module_source_path(modname)
    if src_path is None:
        # 소스 파일 식별 불가 → 추적 불가(전부 미해결, INV-3).
        return [], False
    tree = ast.parse(src_path.read_text(), filename=str(src_path))

    enclosing: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if fn.lineno <= site.lineno and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == site.method
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == site.receiver
                and n.lineno == site.lineno
                for n in ast.walk(fn)
            ):
                enclosing = fn
    if enclosing is None:
        # helper 함수 식별 불가 → 추적 불가(전부 미해결).
        return [], False
    param_names = {a.arg for a in enclosing.args.args}
    if site.receiver not in param_names:
        # receiver 가 helper 파라미터 아님(지역 변수 등) → 추적 불가.
        return [], False

    # site.receiver 가 helper 의 몇 번째 파라미터인지(positional index).
    pos_params = [a.arg for a in enclosing.args.args]
    try:
        recv_pos = pos_params.index(site.receiver)
    except ValueError:  # pragma: no cover - 위 param_names 검사로 도달 불가
        return [], False

    helper_name = enclosing.name
    models: list[type[BaseModel]] = []
    all_resolved = True
    saw_call = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        called = (
            f.id
            if isinstance(f, ast.Name)
            else (f.attr if isinstance(f, ast.Attribute) else None)
        )
        if called != helper_name:
            continue
        saw_call = True
        # 이 helper 호출에서 receiver 파라미터로 전달되는 인자를 찾는다
        # (positional index 우선, 없으면 keyword).
        arg_node: ast.expr | None = None
        if recv_pos < len(node.args):
            arg_node = node.args[recv_pos]
        else:
            for kw in node.keywords:
                if kw.arg == site.receiver:
                    arg_node = kw.value
                    break
        if arg_node is None:
            # 이 호출에서 model 인자 전달 형태 불명 → 미해결(전체 FAIL).
            all_resolved = False
            continue
        if isinstance(arg_node, ast.Name):
            resolved = _resolve_name_in_module(modname, arg_node.id)
            if isinstance(resolved, type) and issubclass(resolved, BaseModel):
                if resolved not in models:
                    models.append(resolved)
                continue
        # 변수/표현식/비-BaseModel literal → 정적 resolve 불가.
        all_resolved = False
    if not saw_call:
        return [], False
    return models, all_resolved


def _resolve_s1() -> _S1Resolve:
    """S1a∪S1b: entrypoint site 전수 → 검증 모델 정적 resolve.

    - ``<Model>.model_validate`` : 모듈 namespace 에서 literal Model.
    - ``TypeAdapter(...).validate_*`` : 동적 → 단일 unresolvable.
    - 제네릭 ``model.model_validate`` : helper model 인자 전수 추적.
      **하나라도** literal-BaseModel resolve 안 되면 site 전체
      unresolvable(any-match → all-must-resolve, INV-3).
    """
    res = _S1Resolve()
    for site in _scan_s1_entrypoints():
        sid = f"{site.module}:{site.lineno}:{site.callee_src}"
        recv = site.receiver
        cls = _resolve_name_in_module(site.module, recv)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            res.models.append((sid, cls))
            continue
        if "TypeAdapter(" in recv:
            res.unresolvable.append(
                f"{sid} → TypeAdapter 동적 검증 (정적 resolve 불가 — "
                "lock-walkable 아님)"
            )
            continue
        if recv.isidentifier():
            models, all_resolved = _trace_generic_helper_model_args(site)
            if not all_resolved or not models:
                # any-match → all-must-resolve: literal+dynamic 혼재
                # 또는 추적 불가 → site 전체 단일 unresolvable.
                res.unresolvable.append(
                    f"{sid} → 제네릭 helper model 인자 전수 정적 "
                    "literal-BaseModel resolve 실패 (any-match → "
                    "all-must-resolve; literal+dynamic 혼재/추적불가)"
                )
                continue
            for m in models:
                res.models.append((f"{sid}#{m.__name__}", m))
            continue
        res.unresolvable.append(f"{sid} → receiver 정적 resolve 불가")
    return res


def _scan_chokepoint_and_error_sites() -> tuple[int, int]:
    """raw-body ValidationError 처리 site 와 chokepoint 호출 수.

    origin-complete: 모든 raw-body ``except ValidationError`` site 가
    chokepoint ``sanitize_validation_errors`` 를 detail 로 사용해야
    한다(직접 ``e.errors(...)`` detail 잔존 0 — #1650 SSOT). 본 스캔은
    AST/텍스트로 self-derive(하드코딩 카운트 없음).
    """
    choke = 0
    direct = 0
    for _modname, path in _route_modules():
        text = path.read_text()
        choke += text.count(f"detail={_CHOKEPOINT_NAME}(e),")
        if "detail=e.errors(include_context=False, include_input=False)" in text:
            direct += text.count(
                "detail=e.errors(include_context=False, include_input=False)"
            )
    return choke, direct


# ════════════════════════════════════════════════════════════════════
# S2 (mounted-app 재귀 + positive-type mount 면제)
# ════════════════════════════════════════════════════════════════════


@dataclasses.dataclass
class _S2Collect:
    body_models: list[tuple[str, Any]]  # (route_path, annotation)
    # positive 미증명 mount/route — 단일 unresolvable sink(INV-3).
    unresolvable: list[str]


# positive-type non-validation mount allowlist — 검증불가가 타입으로
# 증명되는 명시 allowlist(파일 서빙 전용, Pydantic 422 loc 생성 구조적
# 불가). "routes 속성 부재 ⇒ PASS" absence 추론 금지(fail-open).
_NON_VALIDATION_MOUNT_TYPES: tuple[type, ...] = (StaticFiles,)

# positive-type **route-container** allowlist — lock 이 ``routes`` 의
# Starlette route 의미(``APIRoute``/``Mount``/``Route``/
# ``WebSocketRoute`` 자식 트리)를 **아는** known 타입에 한해서만 재귀
# 한다. ``Starlette`` 는 ``FastAPI`` sub-app 을 MRO 로 포함하고,
# ``Router`` 는 ``Mount(routes=[...])`` 가 wrapping 하는 컨테이너,
# ``APIRouter`` 는 FastAPI 라우터 컨테이너다. **``routes`` 속성 존재
# 만으로 재귀·통과 금지** — 빈 ``routes=[]`` known 컨테이너는 재귀가
# positive-type 으로 완결(자식 0 = 검증 surface 0; 컨테이너 타입
# 자체는 request body 검증 불가, ``APIRoute`` 자식만 가능)되지만,
# 타입 미지(unknown ASGI)·``routes`` duck-typing 만 가진 mount 는
# positive 증명 불가이므로 단일 ``unresolvable`` 로 fail-closed
# (absence/duck-typing 추론 금지 — INV-3 single-sink, positive-type).
_KNOWN_ROUTE_CONTAINER_TYPES: tuple[type, ...] = (Starlette, Router, APIRouter)


def _collect_s2(app: Any, prefix: str = "") -> _S2Collect:  # noqa: C901
    """``create_app()`` route 재귀 순회(Mount/sub-app 내부 포함).

    각 ``APIRoute`` 의 ``route.body_field`` ∪
    ``get_flat_dependant(route.dependant).body_params`` 의 annotation
    수집. Mount 는 (INV-3 single-sink + positive-type):
      - positive-type 증명 non-validation mount(``StaticFiles`` 등
        allowlist 타입 ``isinstance``) → 면제 PASS.
      - **known route-container 타입**(``_KNOWN_ROUTE_CONTAINER_TYPES``
        — ``Starlette``/``Router``/``APIRouter``; lock 이 ``routes`` 의
        route 의미를 아는 타입) → 재귀(빈 ``routes=[]`` 도 positive
        타입으로 재귀 완결 = surface 0). ``routes`` 속성 존재만으로
        재귀하지 않는다.
      - 그 외 일체(unknown ASGI · empty-route custom mount ·
        ``routes`` duck-typing 만; positive 증명 불가) → 그 mount id
        를 단일 ``unresolvable`` 에 충전(fail-closed; absence/
        duck-typing 을 safe 로 추론하지 않음).
    """
    out = _S2Collect(body_models=[], unresolvable=[])
    routes = getattr(app, "routes", None)
    if routes is None:
        out.unresolvable.append(
            f"{prefix or '<root>'}: routes 속성 없는 app (positive 미증명)"
        )
        return out
    for r in routes:
        if isinstance(r, APIRoute):
            full = prefix + r.path
            # INV-3 정밀화(Codex `review-mpagchqw` [P2]): introspection
            # 예외를 try/except 로 삼켜 route body params 를 조용히
            # 누락하면 default-deny 가 green 으로 새는 fail-open 이다.
            # body_field 접근·get_flat_dependant·annotation resolve 의
            # **모든** 예외를 그 surface id(route 식별자)와 함께 단일
            # ``out.unresolvable`` 에 추가하고 계속한다(삼키고 skip 0).
            # ``unresolvable ≠ ∅ ⟹ 무조건 FAIL`` 단일 sink 가 누락을
            # 잡는다.
            try:
                bf = getattr(r, "body_field", None)
            except Exception as exc:  # pragma: no cover - 방어(fail-closed)
                out.unresolvable.append(
                    f"{full}#body_field: body_field 접근 예외 "
                    f"{type(exc).__name__}: {exc} (introspection 실패 "
                    "→ single fail-closed sink, INV-3)"
                )
                bf = None
            if bf is not None:
                try:
                    ann = getattr(bf.field_info, "annotation", None)
                except Exception as exc:  # pragma: no cover - 방어
                    out.unresolvable.append(
                        f"{full}#body_field: annotation resolve 예외 "
                        f"{type(exc).__name__}: {exc} (INV-3 sink)"
                    )
                else:
                    out.body_models.append((f"{full}#body_field", ann))
            try:
                fd = get_flat_dependant(r.dependant)
                body_params = list(fd.body_params)
            except Exception as exc:
                # get_flat_dependant/dependant graph 예외 → 그 route 의
                # body params 가 미지(누락=fail-open)이므로 route id 를
                # 단일 sink 에 충전(삼키고 skip 금지 — INV-3).
                out.unresolvable.append(
                    f"{full}#dep_body: get_flat_dependant 예외 "
                    f"{type(exc).__name__}: {exc} (route body params "
                    "미지 → single fail-closed sink, INV-3)"
                )
            else:
                for bp in body_params:
                    try:
                        ann = getattr(bp.field_info, "annotation", None)
                    except Exception as exc:  # pragma: no cover - 방어
                        out.unresolvable.append(
                            f"{full}#dep_body: dep body annotation "
                            f"resolve 예외 {type(exc).__name__}: {exc} "
                            "(INV-3 sink)"
                        )
                        continue
                    out.body_models.append((f"{full}#dep_body", ann))
        elif isinstance(r, Mount):
            sub = r.app
            mount_path = prefix + r.path
            if isinstance(sub, _NON_VALIDATION_MOUNT_TYPES):
                continue
            # positive-type 증명만 재귀(INV-3 single-sink): lock 이
            # ``routes`` 의 route 의미를 **아는** known 컨테이너 타입
            # 일 때만. ``routes`` 속성 존재(duck-typing)·빈 ``routes=[]``
            # custom ASGI mount 만으로 재귀·통과하면 그 mount 가
            # ``__call__`` 에서 request body/Pydantic 검증 시 S2
            # default-deny 가 우회된다(fail-open).
            if isinstance(sub, _KNOWN_ROUTE_CONTAINER_TYPES):
                child = _collect_s2(sub, mount_path)
                out.body_models.extend(child.body_models)
                out.unresolvable.extend(child.unresolvable)
                continue
            out.unresolvable.append(
                f"{mount_path}: positive-type 미증명 mount "
                f"({type(sub).__module__}.{type(sub).__name__} — "
                "known route-container 타입 아님 ∧ known-safe "
                "non-validation 타입 아님; routes 속성/empty-route/"
                "duck-typing absence 추론 금지 → single fail-closed "
                "sink, INV-3)"
            )
        elif isinstance(r, (Route, WebSocketRoute)):
            # positive 구조 증명(absence 추론 아님): FastAPI 의
            # request-body Pydantic 검증·422 loc 생성은 구조적으로
            # ``APIRoute`` 에만 존재(``body_field``/
            # ``dependant.body_params`` 는 ``APIRoute`` 전용). Starlette
            # ``Route``/``WebSocketRoute`` (FastAPI 내부 openapi/docs/
            # redoc GET·websocket)은 body_field 를 가질 수 없는 타입
            # 이므로 Pydantic 422 loc 표면이 아니다 — out-of-S2.
            continue
        else:
            out.unresolvable.append(
                f"{prefix + getattr(r, 'path', '?')}: 미지 route 타입 "
                f"{type(r).__module__}.{type(r).__name__} (positive 미증명)"
            )
    return out


def _build_app() -> Any:
    """검증용 app 인스턴스(서비스 미주입 — route graph 만 필요)."""
    return create_app()


# ════════════════════════════════════════════════════════════════════
# S1∪S2 self-enumerate → DISCOVERED (introspection, INV-1 DISCOVERED 축)
# ════════════════════════════════════════════════════════════════════


def _stable_s1_site(s1_site_id: str) -> str:
    """S1 site_id(``module:lineno:callee_src`` [+``#Model``])를 **lineno
    무관 안정 site**(``module:callee_src``)로 정규화 — INV-1 정밀화.

    issue 본문이 validating-site = "S1 callee 위치(파일:심볼)" 로 정의
    하므로 volatile 한 lineno 는 키에서 제거한다(가드 유무는 그 callee
    심볼=route+entrypoint 의 사실이지 줄 번호의 사실이 아니다). 줄
    번호를 키에 넣으면 routes 파일의 무관한 윗쪽 편집만으로 키가
    흔들려 등록 proof 가 stale 가 되는 fragile-by-design 결함이 된다
    (site 는 자연 floor — 더 미세 단위 불요).
    """
    parts = s1_site_id.split(":")
    if len(parts) >= 3:
        module = parts[0]
        callee_src = ":".join(parts[2:])  # callee_src 자체엔 ':' 없음
        # 제네릭 helper 의 ``#Model`` suffix 도 callee_src 에 포함돼
        # site 식별자로 보존(같은 helper 라도 다른 검증 모델은 별 site).
        return f"{module}:{callee_src}"
    return s1_site_id  # 형식 예외 — 원본 유지(set-difference 가 잡음)


@dataclasses.dataclass
class _SurfaceModels:
    """S1∪S2 self-enumerate 결과.

    INV-1 정밀화: 모델/root 를 **검증 site 와 함께** 보존한다(모델
    dedup 으로 site 를 버리지 않는다 — 같은 모델이 여러 site 에서
    검증되면 각 site 별로 dict 노드 키가 갈려야 가드 없는 site 가
    재사용 통과되지 않는다).
    """

    # (validating_site, model) — 같은 모델이 여러 site 면 각각 보존.
    site_models: list[tuple[str, type[BaseModel]]]
    # (validating_site, root_path, annotation) — root-container body.
    site_roots: list[tuple[str, str, Any]]
    # S1b/S2 단일 unresolvable sink(INV-3).
    unresolvable: list[str]


def _s1s2_surface_models() -> _SurfaceModels:
    """S1∪S2 self-enumerate BaseModel + root-container annotation +
    단일 unresolvable sink(S1b helper/TypeAdapter + S2 mount/route).

    각 모델/root 는 그 검증 site(S1 안정 callee / S2 route+entrypoint)
    와 쌍으로 보존된다 — dict 노드 키의 validating-site 성분(INV-1).
    """
    s1 = _resolve_s1()
    app = _build_app()
    s2 = _collect_s2(app)

    site_models: list[tuple[str, type[BaseModel]]] = []
    site_roots: list[tuple[str, str, Any]] = []
    seen_pairs: set[tuple[str, int]] = set()
    for s1_sid, m in s1.models:
        site = _stable_s1_site(s1_sid)
        pk = (site, id(m))
        if pk in seen_pairs:
            continue
        seen_pairs.add(pk)
        site_models.append((site, m))
    for path, ann in s2.body_models:
        # S2 site = route_path#entrypoint (이미 안정 — lineno 무관).
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            pk = (path, id(ann))
            if pk in seen_pairs:
                continue
            seen_pairs.add(pk)
            site_models.append((path, ann))
        else:
            site_roots.append((path, path, ann))
    return _SurfaceModels(
        site_models=site_models,
        site_roots=site_roots,
        unresolvable=list(s1.unresolvable) + list(s2.unresolvable),
    )


def _discover_all(surface: _SurfaceModels) -> Discovered:
    """S1∪S2 전 surface 의 annotation 트리를 verdict-free enumeration
    해 단일 ``Discovered`` 로 병합(INV-2 — verdict 없음).

    각 surface 의 검증 site 를 ``discover_annotation`` 에 전달해 발견
    dict 노드 키에 validating-site 가 박힌다(INV-1 정밀화 — 가드
    있는 site 만 등록 proof 와 set-difference 로 1:1).
    """
    disc = Discovered()
    for site, rpath, ann in surface.site_roots:
        disc.merge(discover_annotation(ann, f"s2-root:{rpath}", validating_site=site))
    for site, m in surface.site_models:
        disc.merge(discover_annotation(m, m.__qualname__, validating_site=site))
    return disc


# ════════════════════════════════════════════════════════════════════
# REGISTERED_STATIC (INV-1 — 정적 리터럴, introspection 절대 미호출)
# ════════════════════════════════════════════════════════════════════
#
# 아래 두 집합은 **명시 리터럴**이다. INV-1: 이 집합을 만드는 코드는
# introspection 함수(``_iter_model_validators``/``_validator_markers``/
# ``_discover``)를 절대 호출하지 않는다. ``proven=f(discovered)``
# self-defeat 영구 차단(INV-5 canary 가 락). 등록 식별자 각각은
# behavioral 증명과 1:1(INV-4).


# ── dict 축 REGISTERED_STATIC ──────────────────────────────────────
#
# 비-``dict[str,Any]`` dict 노드의 justified-unreachable PASS 는, 소유
# 모델 ``model_validate`` 가 호출되기 *이전에* 그 필드를 포함한 요청이
# 거부(예 4xx)됨을 행위로 증명한 등록 entry 로만 허용. (owner_qualname,
# field_name, **validating_site**) 리터럴 키 + behavioral prove fn 의
# 1:1(INV-4). validating_site 는 그 dict 노드가 검증되는 S1 안정 callee
# (``module:callee_src``) 또는 S2 route+entrypoint(``route_path#ep``)
# 식별자다(INV-1 정밀화 — pre-reject 가드는 검증-site 의 속성이므로
# (owner,field) 단독 키면 가드 없는 다른 site 로 증명 재사용=fail-open).


@dataclasses.dataclass
class _DictPreRejectProof:
    """(owner qualname, field/annotation-path, validating-site)
    **리터럴** 키 + behavioral 증명. lock self-derive 한 dict 노드와
    (owner,path,site) 단위 1:1(owner 단독도, owner+field 단독도 아님 —
    INV-1 정밀화). ``prove`` 는 owner 모델 ``model_validate`` 스파이를
    걸고 그 필드를 포함한 요청이 그 **특정 site** 에서 model_validate
    **미호출** 상태로 거부됨을 단언(strip 후처리 단언 불충분 — 스파이
    invoke 시 fail). 이 키는 introspection 으로 만들지 않는다(리터럴).
    """

    owner_qualname: str
    field_name: str
    validating_site: str
    prove: typing.Callable[[], None]

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.owner_qualname, self.field_name, self.validating_site)


def _prove_account_update_credentials_pre_reject() -> None:
    """``AccountUpdateRequest.credentials`` (비-dict[str,Any] dict 노드)
    가 그 검증 site(``ante.web.routes.accounts:AccountUpdateRequest.
    model_validate`` — ``PUT /api/accounts/{id}``)에서 ``model_validate``
    이전 STRUCTURAL 409 로 거부됨을 behavioral 증명. model_validate
    스파이가 invoke 되면 (가드 회귀) 단언 실패. 이 증명은 그 **특정
    site** 한정이며, 동일 모델/필드를 검증하는 다른 site 가 생기면
    그 site 는 별도 키라 본 증명으로 통과되지 않는다(INV-1 정밀화).
    """
    from ante.web.routes import accounts as accounts_mod
    from ante.web.schemas import AccountUpdateRequest

    invoked: list[bool] = []
    orig = AccountUpdateRequest.model_validate
    had_own = "model_validate" in AccountUpdateRequest.__dict__

    def _spy(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - 미호출 단언
        invoked.append(True)
        return orig(*args, **kwargs)

    from tests.unit.conftest import (
        MASTER_AUTH_HEADERS,
        make_master_member_service,
    )

    app = create_app(member_service=make_master_member_service())
    c = TestClient(app)
    c.headers.update(MASTER_AUTH_HEADERS)

    AccountUpdateRequest.model_validate = classmethod(  # type: ignore[method-assign]
        lambda cls, *a, **k: _spy(*a, **k)
    )
    try:
        resp = c.put(
            "/api/accounts/acc-1",
            json={"credentials": {SENTINEL: "leak"}},
        )
    finally:
        if had_own:
            AccountUpdateRequest.model_validate = orig  # type: ignore[method-assign]
        else:
            try:
                del AccountUpdateRequest.model_validate
            except AttributeError:  # pragma: no cover - 방어
                AccountUpdateRequest.model_validate = orig  # type: ignore[method-assign]

    assert resp.status_code == 409, (
        f"credentials → STRUCTURAL 409 pre-reject 회귀: status="
        f"{resp.status_code} body={resp.text}"
    )
    assert not invoked, (
        "AccountUpdateRequest.model_validate 가 credentials 거부 "
        "이전 가드를 우회해 호출됨 — pre-validation-reject precedence "
        "guard 붕괴 (strip 후처리 단언으로는 증명 불충분)"
    )
    assert hasattr(accounts_mod, "STRUCTURAL_FIELDS")
    detail = str(resp.json().get("detail", ""))
    assert SENTINEL not in detail, f"409 detail 에 caller sentinel 반사: {detail}"


# INV-1: 리터럴 (owner,field,validating-site) 키 집합. introspection
# 미호출 — validating_site 는 그 dict 노드가 검증되는 S1 안정 callee
# ``module:callee_src`` 리터럴(lineno 무관 — issue 본문 "파일:심볼").
_REGISTERED_DICT_PROOFS: list[_DictPreRejectProof] = [
    _DictPreRejectProof(
        owner_qualname="AccountUpdateRequest",
        field_name="credentials",
        validating_site=(
            "ante.web.routes.accounts:AccountUpdateRequest.model_validate"
        ),
        prove=_prove_account_update_credentials_pre_reject,
    ),
]

# INV-1: dict 축 REGISTERED_STATIC = 리터럴 (owner,field,site) 키 frozenset.
_REGISTERED_DICT_KEYS: frozenset[tuple[str, str, str]] = frozenset(
    p.key for p in _REGISTERED_DICT_PROOFS
)


# ── validator 축 REGISTERED_STATIC ─────────────────────────────────
#
# INV-1 핵심 정정(RC-1): validator 축 REGISTERED_STATIC 은 **명시
# 리터럴 surface-id 문자열 집합**이다. dict 축 ``_REGISTERED_DICT_KEYS``
# 와 **동형의 정적 proof**. 이 집합을 만드는 코드는 ``model_ref`` 모델을
# introspection(``_iter_model_validators``/``_validator_markers``)으로
# 재도출하지 않는다 — 재도출하면 ``proven=f(discovered)`` 라
# DISCOVERED 가 늘면 REGISTERED 도 같이 늘어 set-difference 가 영구
# 공집합(self-defeating). 신규 validator 가 모델에 추가되면 그
# surface-id 가 DISCOVERED 에는 들어가지만 본 리터럴 집합에는 없으므로
# UNPROVEN ≠ ∅ → FAIL(default-deny). INV-5 canary 가 이를 영구 락.
#
# surface-id 문자열 형식(introspection 산출물과 동일 규칙이되 여기서는
# 리터럴 선언):
#   "<module>.<Model>::field_validators::<name>"
#   "<module>.<Model>::model_validators::<name>"
#   "<module>.<Model>::validators::<name>"        (v1 호환)
#   "<module>.<Model>::root_validators::<name>"    (v1 호환)
#   "<module>.<Model>::field_annotated_validator::<field>"
#   "<path>::Annotated[*Validator]"

_REGISTERED_VALIDATOR_SURFACE_IDS: frozenset[str] = frozenset(
    {
        "ante.web.routes.bots.BotCreateRequest::model_validators::"
        "_require_strategy_identifier",
        "ante.web.routes.members.MemberCreateRequest::field_validators::"
        "_validate_scopes",
        "ante.web.routes.members.ScopesUpdateRequest::field_validators::"
        "_validate_scopes",
        "ante.web.schemas.AccountUpdateRequest::field_validators::"
        "_validate_timezone_update",
        "ante.web.schemas.AccountUpdateRequest::field_validators::"
        "_validate_trading_hours_update",
        "ante.web.schemas.RuleUpdateRequest::field_validators::_validate_params_finite",
    }
)


# ── validator 축 behavioral canary (INV-4 — surface-id 1:1) ─────────
#
# 각 등록 surface-id 는 caller sentinel 주입 시 422 loc=static
# field-path · sentinel∉detail 임을 **개별** 증명한다(모델-단위
# 'ValidationError 한 번' 금지). canary 는 ``surface_ids`` 를
# **리터럴**로 선언하고(INV-1) payload 가 그 surface 를 실제 트리거
# 함을 behavioral 로 단언한다.


@dataclasses.dataclass
class _ValidatorBehavioralCanary:
    """validator surface-id 1:1 behavioral canary.

    ``surface_ids`` = 이 canary 가 behavioral 로 커버하는 **리터럴**
    surface-id 집합(introspection 재도출 아님 — INV-1). ``model_ref``
    + ``payloads`` 로 그 surface 가 실제 트리거돼 loc=static·
    sentinel∉detail 임을 단언(INV-4). #1629 L1 de-interpolation 회귀
    겸함.
    """

    surface_ids: frozenset[str]
    model_ref: typing.Callable[[], type[BaseModel]]
    payloads: list[dict]
    # INV-4 (b) 정밀화(Codex `review-mpagchqw` [P2]): set 이면
    # behavioral payload 가 트리거한 **모든** ValidationError 의
    # ``loc[0]`` 가 이 allowlist 안이어야 한다 — 무관 필드의 collateral
    # 오류(예 enum/type)가 섞이면 ``triggered`` 가 공허 충족되므로
    # FAIL. None 이면 미부과(단일-필드 payload 는 자명히 격리).
    isolated_loc_roots: frozenset[str] | None = None


def _m(modname: str, clsname: str) -> typing.Callable[[], type[BaseModel]]:
    def _get() -> type[BaseModel]:
        m = importlib.import_module(modname)
        cls = getattr(m, clsname)
        assert isinstance(cls, type) and issubclass(cls, BaseModel)
        return cls

    return _get


_VALIDATOR_BEHAVIORAL_CANARIES: list[_ValidatorBehavioralCanary] = [
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.routes.bots.BotCreateRequest::model_validators::"
                "_require_strategy_identifier"
            }
        ),
        model_ref=_m("ante.web.routes.bots", "BotCreateRequest"),
        payloads=[{"bot_id": "b1", "name": SENTINEL}],
    ),
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.routes.members.MemberCreateRequest::field_validators::"
                "_validate_scopes"
            }
        ),
        model_ref=_m("ante.web.routes.members", "MemberCreateRequest"),
        # INV-4 정밀화(Codex `review-mpagchqw` [P2]): per-surface
        # behavioral payload 는 **대상 validator(_validate_scopes)만**
        # 격리 실패시켜야 한다. 이전 payload 는 ``member_type='AGENT'``
        # (MemberType StrEnum SSOT=``human``/``agent`` — 대문자
        # ``AGENT`` 는 invalid)라 ``_validate_scopes`` 와 **무관한**
        # enum ``ValidationError`` 만으로도 ``triggered`` 가 공허
        # 충족됐다(scopes validator 가 실제 sentinel 을 거부 안 해도
        # per-surface proof 가 공허 통과). 무관 필드는 전부 유효값
        # (``member_type='agent'`` 유효)으로 두고 **invalid scope
        # (sentinel)만** 실패하게 해 trigger 가 ``_validate_scopes``
        # 그 surface 때문임을 보장한다.
        payloads=[
            {
                "member_id": "m1",
                "member_type": "agent",
                "scopes": [SENTINEL],
            }
        ],
        # 트리거 오류는 ``scopes`` (=_validate_scopes) 한정이어야
        # 한다 — ``member_type``/``member_id`` 등 무관 필드의 collateral
        # 오류가 섞이면 FAIL(공허 trigger 차단). 'agent' 가 valid 라
        # 현재 단 1건(loc=('scopes',))뿐임이 행위로 보장된다.
        isolated_loc_roots=frozenset({"scopes"}),
    ),
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.routes.members.ScopesUpdateRequest::field_validators::"
                "_validate_scopes"
            }
        ),
        model_ref=_m("ante.web.routes.members", "ScopesUpdateRequest"),
        payloads=[{"scopes": [SENTINEL]}],
    ),
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.schemas.AccountUpdateRequest::field_validators::"
                "_validate_trading_hours_update"
            }
        ),
        model_ref=_m("ante.web.schemas", "AccountUpdateRequest"),
        payloads=[{"trading_hours_start": SENTINEL}],
    ),
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.schemas.AccountUpdateRequest::field_validators::"
                "_validate_timezone_update"
            }
        ),
        model_ref=_m("ante.web.schemas", "AccountUpdateRequest"),
        payloads=[{"timezone": SENTINEL}],
    ),
    _ValidatorBehavioralCanary(
        surface_ids=frozenset(
            {
                "ante.web.schemas.RuleUpdateRequest::field_validators::"
                "_validate_params_finite"
            }
        ),
        model_ref=_m("ante.web.schemas", "RuleUpdateRequest"),
        # caller-controlled **key**=SENTINEL 이고 value 가 finite 위반
        # (NaN) → ``_validate_params_finite`` 실제 실패. 이렇게 해야
        # "SENTINEL∉detail ∧ loc=static field-path" 단언이 공허하지
        # 않고 실효(de-interpolation 회귀 게이트).
        payloads=[{"params": {SENTINEL: float("nan")}}],
    ),
]

# INV-4: 전 canary 의 리터럴 surface_ids union 이 등록 behavioral 커버
# 집합이어야 한다(REGISTERED_VALIDATOR_SURFACE_IDS 와 정확히 일치 —
# 등록은 했으나 behavioral 미증명 = 공허 단언 금지).
_BEHAVIORAL_COVERED_SURFACE_IDS: frozenset[str] = frozenset().union(
    *(c.surface_ids for c in _VALIDATOR_BEHAVIORAL_CANARIES)
)


def _behavioral_validator_check(
    model: type[BaseModel],
    payloads: list[dict],
    *,
    isolated_loc_roots: frozenset[str] | None = None,
) -> None:
    """validator surface 행위 단언: caller sentinel → loc=static
    field-path · sentinel∉detail (#1629 L1 de-interpolation 회귀 겸함).

    ``isolated_loc_roots`` 가 set 이면 트리거된 **모든**
    ValidationError 의 ``loc[0]`` 가 그 allowlist 안이어야 한다 —
    무관 필드의 collateral 오류가 섞이면 ``triggered`` 가 공허
    충족되므로 FAIL(INV-4 (b) per-surface 비-collateral 격리,
    Codex `review-mpagchqw` [P2]).
    """
    triggered = False
    for payload in payloads:
        try:
            model.model_validate(payload)
        except pydantic.ValidationError as e:
            triggered = True
            errs = e.errors(include_context=False, include_input=False)
            for err in errs:
                loc = err.get("loc", ())
                for seg in loc:
                    assert seg != SENTINEL, (
                        f"{model.__qualname__} validator loc 에 caller "
                        f"sentinel 노출: {loc}"
                    )
                detail = str(err)
                assert SENTINEL not in detail, (
                    f"{model.__qualname__} validator detail 에 caller "
                    f"sentinel 반사: {detail}"
                )
                if isolated_loc_roots is not None:
                    root = loc[0] if loc else None
                    assert root in isolated_loc_roots, (
                        f"{model.__qualname__} per-surface behavioral "
                        f"payload 에 collateral 오류 혼입 — loc root "
                        f"{root!r} ∉ {sorted(isolated_loc_roots)} "
                        f"(무관 필드 오류로 triggered 공허 충족, INV-4 "
                        f"(b) 위반): err={err}"
                    )
    assert triggered, (
        f"{model.__qualname__} validator canary self-검증 실패 — "
        f"payload 가 검증 실패 경로를 타지 않음"
    )


# ════════════════════════════════════════════════════════════════════
# compute_verdict: 단일 PASS-computation (INV-2 — verdict 단일 지점)
# ════════════════════════════════════════════════════════════════════
#
# PASS ⟺ (UNPROVEN == ∅ ∧ unresolvable == ∅)
# UNPROVEN = (dict_nodes − REGISTERED_DICT_KEYS)
#          ∪ (validator_surfaces − REGISTERED_VALIDATOR_SURFACE_IDS)
#          ∪ {unsafe_nodes}            # REGISTERED 으로 해제 불가
#
# walker 내부 노드별 plausibility-OR PASS 구조는 전면 폐기됐다 —
# verdict 는 오직 여기서만 set-difference 로 계산된다(INV-2).


@dataclasses.dataclass
class Verdict:
    ok: bool
    unproven_dict: list[tuple[str, str, str]] = dataclasses.field(default_factory=list)
    unproven_validators: list[str] = dataclasses.field(default_factory=list)
    unsafe: list[str] = dataclasses.field(default_factory=list)
    unresolvable: list[str] = dataclasses.field(default_factory=list)


def compute_verdict(
    disc: Discovered,
    unresolvable: typing.Sequence[str],
    *,
    registered_dict_keys: frozenset[tuple[str, str, str]],
    registered_validator_ids: frozenset[str],
) -> Verdict:
    """단일 PASS-computation (INV-2). DISCOVERED − REGISTERED_STATIC.

    ``registered_*`` 는 호출측이 명시 리터럴(INV-1)을 주입한다 —
    introspection 으로 만들지 않는다. INV-5 canary 는 빈
    REGISTERED 를 주입해 전수 FAIL 을 단언한다.
    """
    unproven_dict = sorted(disc.dict_nodes - registered_dict_keys)
    unproven_vs = sorted(disc.validator_surfaces - registered_validator_ids)
    unsafe = list(disc.unsafe_nodes)
    unres = list(unresolvable)
    ok = not unproven_dict and not unproven_vs and not unsafe and not unres
    return Verdict(
        ok=ok,
        unproven_dict=unproven_dict,
        unproven_validators=unproven_vs,
        unsafe=unsafe,
        unresolvable=unres,
    )


# ════════════════════════════════════════════════════════════════════
# 테스트: S1∪S2 self-enumerate default-deny discovery lock — 현 코드 green
# ════════════════════════════════════════════════════════════════════


def test_fastapi_verified_version_pin_advisory() -> None:
    """검증판 진단(비-게이트 — CV1/CV3 canary 가 의미 게이트).

    스펙 SSOT(07-error-format.md)는 ``fastapi==0.135.1`` 검증판을
    명문한다. 본 단언은 회귀 진단 보조이며 introspection 의미 게이트는
    CV1/CV3 canary 다(version-agnostic — pin 미일치라도 canary 가 1차).
    """
    import fastapi

    if fastapi.__version__ != _VERIFIED_FASTAPI_VERSION:  # pragma: no cover
        pytest.skip(
            f"fastapi {fastapi.__version__} != 검증판 "
            f"{_VERIFIED_FASTAPI_VERSION} — CV1/CV3 canary 가 의미 게이트"
        )


def test_s1b_origin_complete_single_unresolvable_sink_empty() -> None:
    """S1b origin-complete(INV-3): 단일 unresolvable sink == ∅.

    모든 Pydantic 검증 entrypoint 가 lock-walkable(정적 literal
    BaseModel resolve) 또는 #1650 chokepoint 경유여야 한다. 제네릭
    helper 는 model 인자 중 **하나라도** 정적 literal-BaseModel resolve
    안 되면 그 site 전체가 단일 unresolvable(any-match →
    all-must-resolve). raw-body chokepoint 우회 직접 ``e.errors(...)``
    detail 잔존 0(#1650 SSOT).
    """
    s1 = _resolve_s1()
    assert not s1.unresolvable, (
        "S1b origin-complete FAIL-CLOSED — 정적 resolve 불가 검증 "
        f"origin/entrypoint(단일 sink): {s1.unresolvable}"
    )
    assert s1.models, "S1 검증 entrypoint 0건 — AST 스캔 회귀 의심"

    choke, direct = _scan_chokepoint_and_error_sites()
    assert direct == 0, (
        f"chokepoint 우회 직접 e.errors(...) detail 잔존: {direct} "
        "(raw-body site 는 sanitize_validation_errors chokepoint 만 호출)"
    )
    assert choke > 0, "chokepoint 호출 site 0 — #1650 SSOT 회귀 의심"


def test_s2_mounted_recursive_single_unresolvable_sink_empty() -> None:
    """S2 mounted 재귀(INV-3): positive-type 미증명 mount/route 단일
    unresolvable sink == ∅.

    ``create_app()`` route 재귀 순회(Mount/sub-app 내부 포함). mount
    면제는 positive-type 증명(allowlist 타입 isinstance)으로만 PASS —
    "routes/body_field 속성 부재 ⇒ PASS" absence 추론 금지(fail-open).
    """
    app = _build_app()
    s2 = _collect_s2(app)
    assert not s2.unresolvable, (
        "S2 FAIL-CLOSED — positive-type 미증명 mount/route(route-bearing "
        f"아님 ∧ known-safe non-validation 타입 아님): {s2.unresolvable}"
    )
    assert s2.body_models, "S2 body 수집 0건 — introspection 회귀 의심"


def test_discovery_lock_current_surface_pass_false_positive_zero() -> None:
    """현 코드 락 green: 단일 PASS-computation 전수 PASS.

    INV-2: ``_discover`` 가 S1∪S2 전 surface 의 트리를 verdict-free
    enumeration → 단일 ``Discovered``. ``compute_verdict`` 한 곳에서
    ``UNPROVEN = DISCOVERED − REGISTERED_STATIC`` 단일 set-difference.
    ``PASS ⟺ (UNPROVEN == ∅ ∧ unresolvable == ∅)``.

    REGISTERED_STATIC 은 명시 리터럴(INV-1) — introspection 재도출
    아님. 발견된 비-``dict[str,Any]`` dict 노드/validator surface 중
    리터럴 등록집합에 없는 것이 하나라도 있으면 FAIL. 미증명/unknown
    unsafe shape(unsafe_nodes)는 REGISTERED 으로 해제 불가.

    현 가정 = caller-supplied 키/이름 벡터 live 0건. 강화 후에도 현
    S1∪S2 전수 PASS 여야 하며, 새 FAIL = 실 live 노출 표면 발견 →
    Stop Condition(중단·재보고).
    """
    surface = _s1s2_surface_models()
    disc = _discover_all(surface)
    verdict = compute_verdict(
        disc,
        surface.unresolvable,
        registered_dict_keys=_REGISTERED_DICT_KEYS,
        registered_validator_ids=_REGISTERED_VALIDATOR_SURFACE_IDS,
    )
    assert verdict.ok, (
        "discovery lock default-deny FAIL — 미증명/unknown unsafe "
        "surface 또는 unresolvable origin 발견 (현 가정=0건 — Stop "
        "Condition: live 노출 표면 또는 미증명 surface 면 즉시 중단·"
        f"재보고): unproven_dict={verdict.unproven_dict} "
        f"unproven_validators={verdict.unproven_validators} "
        f"unsafe={verdict.unsafe} unresolvable={verdict.unresolvable}"
    )


def test_inv5_self_defeat_regression_canary_empty_registered_all_fail() -> None:
    """INV-5 self-defeat 회귀 canary: ``REGISTERED_STATIC`` 공집합
    치환 시 현 S1∪S2 의 모든 validator-bearing·비-``dict[str,Any]``
    surface 가 **전수 FAIL** 해야 한다.

    이 canary 가 red 면 ``proven=f(discovered)`` 가 재발한 것이다
    (RC-1 영구 락 — REGISTERED 가 introspection 으로 재도출되면 빈
    REGISTERED 를 줘도 set-difference 가 공집합이 되어 FAIL 하지
    못한다). 현 코드는 validator-bearing 모델·비-``dict[str,Any]``
    dict 노드를 실제로 가지므로(검증용 실측), 빈 REGISTERED 면
    UNPROVEN ≠ ∅ 이어야 한다.
    """
    surface = _s1s2_surface_models()
    disc = _discover_all(surface)

    # DISCOVERED 자체는 비어 있지 않아야 한다(현 코드는 validator
    # surface·dict 노드 보유 — 이게 비면 enumeration 회귀라 canary 무효).
    assert disc.validator_surfaces, (
        "INV-5 canary self-검증 실패 — DISCOVERED validator surface 0건"
        " (enumeration 회귀; canary 가 공허해짐)"
    )
    assert disc.dict_nodes, (
        "INV-5 canary self-검증 실패 — DISCOVERED dict 노드 0건 "
        "(enumeration 회귀; canary 가 공허해짐)"
    )

    # REGISTERED_STATIC 공집합 주입 → 전수 FAIL 단언.
    verdict = compute_verdict(
        disc,
        surface.unresolvable,
        registered_dict_keys=frozenset(),
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "INV-5 위반 — REGISTERED_STATIC 공집합인데 lock PASS "
        "(proven=f(discovered) self-defeat 재발)"
    )
    # 모든 validator surface 가 UNPROVEN 으로 떨어져야 한다.
    assert set(verdict.unproven_validators) == disc.validator_surfaces, (
        "INV-5 위반 — 빈 REGISTERED 인데 일부 validator surface 가 "
        f"UNPROVEN 으로 안 떨어짐: discovered={sorted(disc.validator_surfaces)} "
        f"unproven={sorted(verdict.unproven_validators)}"
    )
    # 모든 비-dict[str,Any] dict 노드가 UNPROVEN 으로 떨어져야 한다.
    assert set(verdict.unproven_dict) == disc.dict_nodes, (
        "INV-5 위반 — 빈 REGISTERED 인데 일부 dict 노드가 UNPROVEN "
        f"으로 안 떨어짐: discovered={sorted(disc.dict_nodes)} "
        f"unproven={sorted(verdict.unproven_dict)}"
    )


def test_registered_static_does_not_invoke_introspection() -> None:
    """INV-1 구조 단언: ``REGISTERED_STATIC`` 두 축이 명시 리터럴이고
    introspection 산출이 아님을 정적으로 확인.

    - validator 축: ``_REGISTERED_VALIDATOR_SURFACE_IDS`` 의 모든
      원소가 ``str`` 리터럴(introspection 객체 아님). 모듈 소스 AST
      에서 그 frozenset literal 이 함수 호출(``_iter_model_validators``
      등) 없이 문자열 set 으로만 구성됨을 단언.
    - dict 축: ``_REGISTERED_DICT_KEYS`` 가 ``_REGISTERED_DICT_PROOFS``
      의 리터럴 ``(owner_qualname, field_name)`` 튜플로만 구성.

    이 단언이 깨지면 ``proven=f(discovered)`` 재유입 — INV-5 와 함께
    RC-1 이중 락.
    """
    assert all(isinstance(s, str) for s in _REGISTERED_VALIDATOR_SURFACE_IDS), (
        "validator 축 REGISTERED_STATIC 에 비-str(introspection 객체) 혼입"
    )
    assert all(
        isinstance(p.owner_qualname, str)
        and isinstance(p.field_name, str)
        and isinstance(p.validating_site, str)
        for p in _REGISTERED_DICT_PROOFS
    ), "dict 축 REGISTERED_STATIC 키(owner,field,site)가 리터럴 str 아님"

    # 모듈 소스 AST: _REGISTERED_VALIDATOR_SURFACE_IDS 대입 RHS 가
    # frozenset({<str literal>...}) 형태(함수 호출 노드 부재)인지 확인.
    src = Path(__file__).read_text()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        # ``NAME: ann = rhs`` 는 AnnAssign, ``NAME = rhs`` 는 Assign.
        if isinstance(node, ast.AnnAssign):
            target = node.target
            targets = [target.id] if isinstance(target, ast.Name) else []
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        else:
            continue
        if "_REGISTERED_VALIDATOR_SURFACE_IDS" not in targets:
            continue
        assert value is not None
        found = True
        # RHS = frozenset({...}) — frozenset 호출 인자는 set literal,
        # 그 원소는 전부 str Constant(또는 implicit-concat str). 내부에
        # introspection 함수 호출 노드가 없어야 한다.
        bad_calls = [
            n
            for n in ast.walk(value)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id != "frozenset"
        ]
        assert not bad_calls, (
            "INV-1 위반 — _REGISTERED_VALIDATOR_SURFACE_IDS 리터럴 RHS "
            f"에 함수 호출(introspection 재도출 의심): "
            f"{[ast.dump(b) for b in bad_calls]}"
        )
        for n in ast.walk(value):
            assert not isinstance(n, ast.Attribute), (
                "INV-1 위반 — REGISTERED_STATIC RHS 에 attribute 접근 "
                "(introspection/모델 참조 의심)"
            )
    assert found, "_REGISTERED_VALIDATOR_SURFACE_IDS 대입을 AST 에서 미발견"


def test_lock_validator_surfaces_subset_of_registered_static() -> None:
    """CV3 subset(INV-1): lock self-derive(DISCOVERED) validator
    surface 집합 ⊆ ``_REGISTERED_VALIDATOR_SURFACE_IDS`` (리터럴).

    DISCOVERED 는 introspection self-derive, REGISTERED 는 명시
    리터럴 — 물리 분리(INV-1). 둘이 다른 코드 경로라, 등록 모델에 새
    ``field_validator``/``model_validator`` 가 추가되면 그 신규
    surface-id 가 DISCOVERED 에는 들어가지만 리터럴 REGISTERED 에는
    없어 subset 위반 → FAIL(default-deny). 개수·고정 멤버명 lock 입력
    하드코딩 아님 — DISCOVERED self-derive 가 SSOT, REGISTERED 는
    INV-1 정적 proof 축.
    """
    surface = _s1s2_surface_models()
    disc = _discover_all(surface)
    assert disc.validator_surfaces, "validator surface self-enumerate 0건 — 회귀 의심"
    missing = sorted(disc.validator_surfaces - _REGISTERED_VALIDATOR_SURFACE_IDS)
    assert not missing, (
        "lock self-enumerate validator surface 가 REGISTERED_STATIC "
        f"미등록(surface-id 단위 — 신규 validator 추가 차단): {missing}. "
        f"등록 리터럴 집합={sorted(_REGISTERED_VALIDATOR_SURFACE_IDS)}"
    )


def test_registered_validators_have_per_surface_id_behavioral_canary() -> None:
    """INV-4: ``_REGISTERED_VALIDATOR_SURFACE_IDS`` 의 **각** surface-id
    가 behavioral canary 로 1:1 커버됨(공허 단언 금지).

    등록만 하고 behavioral 미증명이면(모델-단위 'ValidationError 한
    번' 으로 약화) FAIL. 등록 리터럴 집합 == behavioral 커버 집합
    이어야 한다(over-register/under-cover 양방향 차단).
    """
    only_reg = sorted(
        _REGISTERED_VALIDATOR_SURFACE_IDS - _BEHAVIORAL_COVERED_SURFACE_IDS
    )
    only_cov = sorted(
        _BEHAVIORAL_COVERED_SURFACE_IDS - _REGISTERED_VALIDATOR_SURFACE_IDS
    )
    assert _BEHAVIORAL_COVERED_SURFACE_IDS == _REGISTERED_VALIDATOR_SURFACE_IDS, (
        "INV-4 위반 — 등록 surface-id 집합 ≠ behavioral 커버 집합. "
        f"등록만={only_reg} 커버만={only_cov}"
    )


@pytest.mark.parametrize(
    "canary",
    [
        pytest.param(c, id="+".join(sorted(c.surface_ids)))
        for c in _VALIDATOR_BEHAVIORAL_CANARIES
    ],
)
def test_cv3_validator_behavioral_per_surface_no_sentinel(
    canary: _ValidatorBehavioralCanary,
) -> None:
    """CV3 behavioral(INV-4): 등록 surface-id 각각이 caller sentinel
    주입 시 422 loc=static field-path 뿐 · sentinel∉detail.

    surface-id 단위 1:1(모델-단위 'ValidationError 한 번' 금지) —
    canary 의 리터럴 ``surface_ids`` 가 ``model_ref`` 모델이 실제
    self-enumerate 하는 surface 부분집합인지도 확인(공허 canary 차단).
    #1629 L1 de-interpolation 회귀 겸함.
    """
    model = canary.model_ref()
    # canary 의 리터럴 surface_ids 가 실제 모델 introspection 의
    # 부분집합인지(존재하지 않는 surface 를 등록한 공허 canary 차단).
    actual: set[str] = set(_iter_model_validators(model))
    for fname, fi in model.model_fields.items():
        if _validator_markers(getattr(fi, "metadata", []) or []):
            actual.add(_field_annotated_validator_sid(model, fname))
    stale = canary.surface_ids - actual
    assert not stale, (
        f"INV-4 — canary 리터럴 surface_ids 가 모델 introspection 에 "
        f"부재(stale/오타 canary): {sorted(stale)} (실제={sorted(actual)})"
    )
    _behavioral_validator_check(
        model, canary.payloads, isolated_loc_roots=canary.isolated_loc_roots
    )


def test_pre_validation_reject_precedence_guards_all_proven() -> None:
    """INV-4: self-derived 비-dict[str,Any] dict 노드 전부 등록
    pre-reject behavioral 증명 green (미증명 노드 0).

    각 등록 entry 는 owner 모델 ``model_validate`` 스파이를 걸고 그
    필드를 포함한 요청이 그 **특정 site** 에서 model_validate
    **미호출** 상태로 거부됨을 단언(strip 후처리 단언 불충분). 추가로
    DISCOVERED dict 노드(owner,field,**site**) 집합이 등록 리터럴 키
    집합과 정확히 일치(stale/over-broad 차단 — INV-1 정밀화).
    """
    for proof in _REGISTERED_DICT_PROOFS:
        proof.prove()

    # DISCOVERED (owner,field,site) dict 노드 ⊆ 등록 리터럴 키(미증명
    # 노드 0). 동시에 등록 키가 실제 발견되는지(stale 등록 차단)도
    # 단언. site 가 키에 있어 가드 없는 다른 site 가 별 키→미증명.
    surface = _s1s2_surface_models()
    disc = _discover_all(surface)
    missing = sorted(disc.dict_nodes - _REGISTERED_DICT_KEYS)
    assert not missing, (
        f"발견 dict 노드 (owner,field,site) {missing} 가 등록 리터럴 "
        f"pre-validation-reject 키 집합 {sorted(_REGISTERED_DICT_KEYS)} 에 "
        "없음 (per-(owner,field,site) 증명 필요 — 가드 없는 site 면 "
        "여기서 FAIL)"
    )
    stale = sorted(_REGISTERED_DICT_KEYS - disc.dict_nodes)
    assert not stale, (
        f"등록 dict 키 {stale} 가 현 S1∪S2 에서 미발견 (stale 등록 — "
        "registry 가 introspection 과 괴리)"
    )


# ════════════════════════════════════════════════════════════════════
# CV1: fail-closed FastAPI introspection canary
# ════════════════════════════════════════════════════════════════════


class _SafeForbidModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class _SafeIgnoreModel(BaseModel):
    name: str


class _ExtraAllowModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str


class _TypedPydanticExtraModel(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, int]
    name: str


class _ValidatorBearingModel(BaseModel):
    x: int

    @field_validator("x")
    @classmethod
    def _v(cls, v: int) -> int:  # pragma: no cover - canary 구조용
        return v


@dataclasses.dataclass
class _PlainDataclass:
    a: int


@pydantic.dataclasses.dataclass
class _PydanticDataclass:
    a: int


class _TD(typing_extensions.TypedDict):
    a: int


class _NT(NamedTuple):
    a: int


class _RootDictModel(RootModel[dict[str, int]]):
    pass


class _OpaqueArbitrary:  # 임의 class — known-safe 아님.
    pass


class _CanaryEnum(enum.Enum):
    A = "a"
    B = "b"


def _opt(tp: Any) -> Any:
    """legacy ``typing.Union[tp, None]`` origin 동적 생성(canary 전용).

    PEP604 ``tp | None`` 은 ``types.UnionType`` origin, ``typing.Union``
    은 ``typing.Union`` origin — enumeration 이 둘을 동일 Union 분기로
    처리함을 양쪽 canary 로 고정한다.
    """
    return Union[tp, None]  # noqa: UP007 — legacy Union origin canary 의도


def _make_dict_field_model() -> type[BaseModel]:
    class _DictFieldModel(BaseModel):
        m: dict[str, int]

    return _DictFieldModel


def _shape_pass(tp: Any) -> bool:
    """단일 PASS-computation 으로 shape 판정(REGISTERED 공집합 —
    순수 default-deny canary 극성)."""
    disc = discover_annotation(tp, "canary")
    v = compute_verdict(
        disc,
        [],
        registered_dict_keys=frozenset(),
        registered_validator_ids=frozenset(),
    )
    return v.ok


class _ShapeModelS1(BaseModel):
    name: str


class _ShapeModelS2(BaseModel):
    name: str


class _ShapeModelS3(BaseModel):
    name: str


class _ShapeModelS4(BaseModel):
    name: str


def test_cv1_introspection_shapes_1_to_4_detect_model() -> None:
    """CV1 ①~④(INV-4 정밀화 — per-path positive, Codex
    `review-mpagchqw` [P2]): FastAPI introspection shape **각 path 별**
    기대 annotation 이 S2 수집에 개별 등장하는지 positive 단언.

    ① implicit ``body: M`` ② ``Annotated[M, Body()]`` ③ embedded
    ``Body(embed=True)`` ④ dependency-nested body param. 이전엔
    ``M in found`` any-match 라 한 shape 만 발견돼도 green 이었다 —
    ``Depends`` body param·``Body(embed=True)`` 수집이 깨져 implicit
    하나만 수집돼도 통과하는 fail-open. 본 canary 는 path 별로
    **서로 다른 모델**을 두고 각 path 가 그 모델을 개별 수집했는지
    단언(한 shape 라도 누락이면 FAIL — any-match 폐기). 검증판
    fastapi==0.135.1.
    """

    def _dep(d: _ShapeModelS4) -> _ShapeModelS4:  # pragma: no cover
        return d

    mini = FastAPI()

    @mini.post("/s1")
    def _s1(body: _ShapeModelS1) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s2")
    def _s2(body: Annotated[_ShapeModelS2, Body()]) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s3")
    def _s3(
        body: Annotated[_ShapeModelS3, Body(embed=True)],
    ) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s4")
    def _s4(d: _ShapeModelS4 = Depends(_dep)) -> dict:  # pragma: no cover
        return {}

    collected = _collect_s2(mini)
    assert not collected.unresolvable, (
        f"CV1 ①~④ S2 introspection 예외 → unresolvable(INV-3): {collected.unresolvable}"
    )

    # path 별 수집 annotation 인덱스(route_path → 발견 BaseModel 집합).
    by_path: dict[str, set[Any]] = {}
    for path, ann in collected.body_models:
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            # path 형식 예: "/s1#body_field" / "/s4#dep_body".
            route = path.split("#", 1)[0]
            by_path.setdefault(route, set()).add(ann)

    # INV-4: **각** path 가 자기 기대 모델을 개별 수집했는지 positive
    # 단언(any-match 금지 — 한 shape 라도 누락이면 FAIL).
    expected = [
        ("/s1", _ShapeModelS1, "implicit body: M"),
        ("/s2", _ShapeModelS2, "Annotated[M, Body()]"),
        ("/s3", _ShapeModelS3, "Annotated[M, Body(embed=True)]"),
        ("/s4", _ShapeModelS4, "Depends(_dep) body param"),
    ]
    missing = [
        f"{route}({desc})→{model.__name__}"
        for route, model, desc in expected
        if model not in by_path.get(route, set())
    ]
    collected_map = {k: sorted(m.__name__ for m in v) for k, v in by_path.items()}
    assert not missing, (
        "CV1 ①~④ INV-4 per-path positive 위반 — shape 별 기대 "
        f"annotation 이 그 path 에서 미수집(any-match fail-open): "
        f"{missing}; 수집맵={collected_map}"
    )


def test_cv1_known_bad_shapes_all_fail_closed() -> None:
    """CV1 ⑤~⑳: element-TYPE/구조 known-bad shape 전부 fail-closed.

    단일 PASS-computation(REGISTERED 공집합)이 통과(PASS)하면 canary
    자체 fail(극성 보장).
    """
    known_bad: list[tuple[str, Any]] = [
        ("dict[str,int]", dict[str, int]),
        ("dict[str,ForbidModel]", dict[str, _SafeForbidModel]),
        ("list[dict[str,int]]", list[dict[str, int]]),
        ("list[PlainDataclass]", list[_PlainDataclass]),
        ("list[ExtraAllowModel]", list[_ExtraAllowModel]),
        ("list[TypedPydanticExtraModel]", list[_TypedPydanticExtraModel]),
        ("list[ValidatorBearingModel]", list[_ValidatorBearingModel]),
        ("Optional[dict[str,int]] (typing.Union origin)", _opt(dict[str, int])),
        ("dict[str,int]|None (UnionType origin)", dict[str, int] | None),
        ("PlainDataclass", _PlainDataclass),
        ("PydanticDataclass", _PydanticDataclass),
        ("TypedDict", _TD),
        ("NamedTuple", _NT),
        ("dict[int,Any]", dict[int, Any]),
        ("dict[int,int]", dict[int, int]),
        ("dict[Any,int]", dict[Any, int]),
        ("dict[Literal,int]", dict[Literal["a", "b"], int]),
        ("ExtraAllowModel", _ExtraAllowModel),
        ("TypedPydanticExtraModel", _TypedPydanticExtraModel),
        ("ValidatorBearingModel", _ValidatorBearingModel),
        ("RootModel[dict[str,int]]", _RootDictModel),
        (
            "Annotated[dict[str,Any],AfterValidator]",
            Annotated[dict[str, Any], AfterValidator(lambda v: v)],
        ),
        ("OpaqueArbitrary", _OpaqueArbitrary),
        ("dict[str,T≠Any] nested in BaseModel field", _make_dict_field_model()),
    ]
    leaked = [name for name, tp in known_bad if _shape_pass(tp)]
    assert not leaked, (
        f"CV1 known-bad shape 가 PASS-computation 을 통과(fail-open) — "
        f"극성 위반: {leaked}"
    )


def test_cv1_interpretation_b_positive_element_safe_containers_pass() -> None:
    """CV1 해석 B 양성: element-safe 컨테이너 PASS.

    bounded 정수 인덱스 자체는 위반 아님 — ``list[str]``/``tuple``/
    ``set[<safe>]``/``list[<safe forbid|ignore validator-clean
    BaseModel>]`` PASS. ``extra='forbid'`` safe BaseModel element 는
    PASS(known-bad 는 element TYPE 이 FAIL-CLOSED 집합일 때지 forbid
    여부/인덱스가 아님 — ``list[ForbidModel]`` 더 이상 known-bad 아님).
    """
    positive: list[tuple[str, Any]] = [
        ("list[str]", list[str]),
        ("tuple[int,str]", tuple[int, str]),
        ("tuple[int,...]", tuple[int, ...]),
        ("set[str]", set[str]),
        ("frozenset[int]", frozenset[int]),
        ("list[SafeForbidModel]", list[_SafeForbidModel]),
        ("list[SafeIgnoreModel]", list[_SafeIgnoreModel]),
        ("dict[str,Any]", dict[str, Any]),
        ("str|None (UnionType origin)", str | None),
        ("Optional[str] (typing.Union origin)", _opt(str)),
        ("list[int|None]", list[int | None]),
        ("SafeForbidModel", _SafeForbidModel),
        ("SafeIgnoreModel", _SafeIgnoreModel),
        ("Literal", Literal["a", "b"]),
        ("Enum", _CanaryEnum),
    ]
    failed = [name for name, tp in positive if not _shape_pass(tp)]
    assert not failed, (
        f"CV1 해석 B 양성 element-safe 컨테이너가 false-positive FAIL "
        f"(인덱스/forbid 사유 오FAIL — 극성 위반): {failed}"
    )


def test_cv1_polarity_meta_assertion_unknown_is_fail() -> None:
    """CV1 극성-반전 메타-단언: opaque/미지 annotation 도 unknown=FAIL.

    PASS-computation 이 shape 를 미리 알지 못해도 default-deny 로 FAIL
    하는지를 검증("shape 열거"가 아니라 "unknown=FAIL" 폴리시 자체).
    """

    class _NeverSeenBefore:
        pass

    T = typing.TypeVar("T")

    class _UnknownGeneric(typing.Generic[T]):
        pass

    for tp in (
        _NeverSeenBefore,
        _UnknownGeneric[int],
        "UnresolvedForwardRef",
        object,
    ):
        assert not _shape_pass(tp), (
            f"극성 메타-단언 위반 — unknown annotation 이 PASS: {tp!r}"
        )


def test_cv1_origin_complete_canary_unsafe_entrypoint_fail_closed(
    tmp_path: Path,
) -> None:
    """CV1 S1b canary ①: synthetic unsafe entrypoint(미walkable
    TypeAdapter) → entrypoint API 매칭에 잡힘(우회 불가).
    """
    syn = tmp_path / "syn_route.py"
    syn.write_text(
        "from pydantic import TypeAdapter\n"
        "def h(payload):\n"
        "    return TypeAdapter(dict[str, int]).validate_python(payload)\n"
    )
    tree = ast.parse(syn.read_text(), filename=str(syn))
    found_unsafe = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _PYDANTIC_ENTRYPOINT_METHODS:
                recv = ast.unparse(node.func.value)
                if "TypeAdapter(" in recv:
                    found_unsafe = True
    assert found_unsafe, (
        "S1b canary ① self-검증 실패 — synthetic unsafe TypeAdapter "
        "entrypoint 가 entrypoint API 매칭에서 누락(미탐지 시 우회 가능)"
    )


def test_cv1_s1_route_discovery_recursive_subpackage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CV1 S1 보강(Codex attempt4 [P2] — S1 하위 route 모듈 재귀
    스캔): ``_route_modules()`` 가 top-level ``routes/*.py`` 만이
    아니라 ``routes/**/*.py`` 하위 패키지 전체를 빠짐없이 self-
    enumerate 함을 행위로 고정한다(``__init__.py`` 포함, dotted
    module name 정확).

    이전 구현은 top-level glob 한정이라 향후
    ``src/ante/web/routes/foo/bar.py`` 같은 하위 패키지 모듈에
    raw-body Pydantic 검증 callee/entrypoint 가 추가되면 S1
    discovery 가 그 validation surface 를 전혀 발견 못 했다
    (fail-open). 본 canary 는 합성 routes 트리(top-level + 하위
    패키지 + 패키지 ``__init__``)를 두고 모든 모듈이 (정확한 dotted
    name, 실제 소스 경로)로 수집되는지, 그리고 하위 패키지 모듈의
    Pydantic entrypoint 가 ``_scan_s1_entrypoints`` 에 등장하는지
    단언한다.
    """
    syn_routes = tmp_path / "routes"
    (syn_routes / "deep" / "nested").mkdir(parents=True)
    # top-level 모듈.
    (syn_routes / "top.py").write_text(
        "from pydantic import BaseModel\n"
        "class TopReq(BaseModel):\n"
        "    a: int\n"
        "def h(p):\n"
        "    return TopReq.model_validate(p)\n"
    )
    # 패키지 __init__.py (포함돼야 함 — 일괄 skip 은 fail-open 갭).
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    (syn_routes / "deep" / "__init__.py").write_text("")
    (syn_routes / "deep" / "nested" / "__init__.py").write_text("")
    # 하위 패키지 모듈의 raw-body Pydantic 검증 entrypoint.
    (syn_routes / "deep" / "nested" / "bar.py").write_text(
        "from pydantic import BaseModel\n"
        "class BarReq(BaseModel):\n"
        "    b: int\n"
        "def handler(payload):\n"
        "    return BarReq.model_validate(payload)\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651")

    mods = dict(_route_modules())
    names = set(mods)
    # 정확한 dotted module name 도출(__init__ → 패키지명; 중첩 .구분).
    assert "syn_routes_1651" in names, (
        f"패키지 __init__.py(routes/__init__.py)가 수집 누락 — 일괄 "
        f"skip 은 fail-open 갭(핸들러 호스팅 가능): {sorted(names)}"
    )
    assert "syn_routes_1651.top" in names, f"top-level 모듈 누락: {sorted(names)}"
    assert "syn_routes_1651.deep" in names, (
        f"하위 패키지 __init__.py 누락: {sorted(names)}"
    )
    assert "syn_routes_1651.deep.nested.bar" in names, (
        f"하위 패키지 모듈(routes/**/*.py) 재귀 미발견 — top-level "
        f"한정 glob fail-open: {sorted(names)}"
    )
    # (modname, path) 쌍의 path 가 실제 소스(flat 재구성 아님)여야 함.
    assert mods["syn_routes_1651.deep.nested.bar"] == (
        syn_routes / "deep" / "nested" / "bar.py"
    ), "하위 패키지 모듈 경로가 실제 소스가 아님(flat rsplit 재구성 잔존)"

    # 하위 패키지 모듈의 Pydantic 검증 entrypoint 가 S1 스캔에 등장.
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651" or m.startswith("syn_routes_1651."):
                del sys.modules[m]
        sites = _scan_s1_entrypoints()
    finally:
        sys.path.remove(str(tmp_path))
    scanned_mods = {s.module for s in sites}
    assert "syn_routes_1651.deep.nested.bar" in scanned_mods, (
        f"하위 패키지 모듈의 raw-body model_validate entrypoint 가 S1 "
        f"스캔에서 누락(재귀 self-enumerate 미작동 = fail-open): "
        f"{scanned_mods}"
    )


def test_cv1_origin_complete_canary_helper_literal_dynamic_mix_unresolvable(
    tmp_path: Path,
) -> None:
    """CV1 S1b canary ②: 제네릭 helper 가 literal+dynamic 모델 호출
    혼재 시 추적기가 **all-must-resolve** 로 site 전체 unresolvable
    판정(any-match 우회 차단 — Codex attempt2 finding).

    합성 모듈: helper 가 한 호출에서는 literal 모델, 다른 호출에서는
    변수(dynamic)로 검증 → ``_trace_generic_helper_model_args`` 가
    ``all_resolved=False`` 를 반환해야 한다(literal 하나 있다고
    models 비-empty 만으로 통과시키면 안 됨 — RC-3 any-match 차단).
    """
    import sys

    src = (
        "import sys\n"
        "from pydantic import BaseModel\n"
        "class LiteralModel(BaseModel):\n"
        "    x: int\n"
        "def helper(payload, model):\n"
        "    return model.model_validate(payload)\n"
        "def route_a():\n"
        "    return helper({}, LiteralModel)\n"
        "def route_b():\n"
        "    chosen = sys.modules\n"
        "    return helper({}, chosen)\n"
    )
    modname = "_syn_helper_mix_1651"
    syn = tmp_path / f"{modname}.py"
    syn.write_text(src)
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        sys.modules.pop(modname, None)
        importlib.import_module(modname)
        # helper 본문 ``model.model_validate`` 의 lineno.
        lineno = src.splitlines().index("    return model.model_validate(payload)") + 1
        site = _EntrypointSite(
            module=modname,
            lineno=lineno,
            callee_src="model.model_validate",
            receiver="model",
            method="model_validate",
        )
        models, all_resolved = _trace_generic_helper_model_args(site)
    finally:
        sys.modules.pop(modname, None)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    assert not all_resolved, (
        "S1b canary ② 위반 — literal+dynamic 혼재 helper 가 "
        "all-must-resolve 로 unresolvable 판정되지 않음(any-match "
        f"fail-open): models={[m.__name__ for m in models]}"
    )


def test_cv1_origin_complete_canary_route_bearing_mounted_subapp() -> None:
    """CV1 S1b canary ③: route-bearing mounted FastAPI sub-app 내부
    unsafe body validation route → S2 재귀가 내려가 enumeration 이
    unsafe 기록 → 단일 verdict 에서 FAIL.
    """
    sub = FastAPI()

    @sub.post("/inner")
    def _inner(body: dict[str, int]) -> dict:  # pragma: no cover
        return {}

    parent = FastAPI()
    parent.mount("/sub", sub)

    collected = _collect_s2(parent)
    assert not collected.unresolvable, (
        f"route-bearing sub-app 이 positive 미증명 mount 로 오분류: "
        f"{collected.unresolvable}"
    )
    inner_anns = [ann for path, ann in collected.body_models if "/sub/inner" in path]
    assert inner_anns, "S2 재귀가 mounted sub-app 내부 route 에 미도달 — 우회 가능"
    for ann in inner_anns:
        assert not _shape_pass(ann), (
            f"mounted sub-app 내부 unsafe body(dict[str,int]) 가 "
            f"PASS-computation 통과(fail-open): {ann}"
        )


def test_cv1_origin_complete_canary_no_routes_custom_asgi_fail_closed() -> None:
    """CV1 S1b canary ⑤: no-routes custom ASGI mount → 단일
    unresolvable sink(absence-of-routes 를 safe 추론 = fail-open).
    """

    class _CustomASGI:
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            # pragma: no cover - 실제 호출 불필요(구조 증명용)
            TypeAdapter(dict[str, int]).validate_python({})

    parent = FastAPI()
    parent.mount("/custom", _CustomASGI())

    collected = _collect_s2(parent)
    assert collected.unresolvable, (
        "no-routes custom ASGI mount 가 unresolvable 되지 않음 "
        "(absence-of-routes 를 safe 로 추론 = fail-open)"
    )
    assert any("/custom" in fm for fm in collected.unresolvable), (
        f"custom ASGI mount 진단 부재: {collected.unresolvable}"
    )


def test_cv1_staticfiles_positive_type_mount_out_of_s2_both_envs(
    tmp_path: Path,
) -> None:
    """CV1 S1b canary ④: StaticFiles positive-type mount = out-of-S2.

    면제가 경로명이 아닌 ``StaticFiles`` 타입 증명으로 작동함을
    fixture 로 고정. assets 존재(StaticFiles mount 1건 → out-of-S2
    PASS) / 부재(mount 0) 양환경에서 lock green·false-positive 0.
    """
    app_with = FastAPI()
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "x.txt").write_text("ok")
    app_with.mount("/arbitrary-name", StaticFiles(directory=str(static_root)))
    c_with = _collect_s2(app_with)
    assert not c_with.unresolvable, (
        f"StaticFiles mount 가 positive-type 면제되지 않음(경로명 무관 "
        f"타입 증명): {c_with.unresolvable}"
    )

    app_without = FastAPI()
    c_without = _collect_s2(app_without)
    assert not c_without.unresolvable, (
        f"mount 0 환경에서 false-positive: {c_without.unresolvable}"
    )

    real = create_app()
    rc = _collect_s2(real)
    assert not rc.unresolvable, (
        f"create_app() S2 mount FAIL(현 dist/assets 환경): {rc.unresolvable}"
    )


def test_cv1_no_routes_custom_asgi_distinct_from_staticfiles() -> None:
    """CV1 보강: no-routes 라는 absence 가 아니라 known-safe 타입의
    positive 증명만 면제임을 대조 단언.

    StaticFiles(routes 없음) → out-of-S2, custom ASGI(routes 없음) →
    unresolvable. 두 mount 모두 ``routes`` 부재이나 결과가 갈리는
    것은 absence 추론이 아닌 positive-type 증명임을 고정한다.
    """
    import tempfile

    class _CustomASGI:
        async def __call__(
            self, scope: Any, receive: Any, send: Any
        ) -> None: ...  # pragma: no cover

    with tempfile.TemporaryDirectory() as d:
        app = FastAPI()
        app.mount("/sf", StaticFiles(directory=d))
        app.mount("/cu", _CustomASGI())
        c = _collect_s2(app)
    assert len(c.unresolvable) == 1, (
        f"positive-type 대조 실패 — StaticFiles 와 custom ASGI 가 "
        f"동일 처리(absence 추론 의심): {c.unresolvable}"
    )


def test_cv1_routes_duck_typed_custom_asgi_fail_closed() -> None:
    """CV1 보강(Codex attempt4 [P2] — unknown/empty-route mount
    fail-closed): ``routes`` 속성을 가졌지만(``routes=[]`` 포함)
    **known route-container 타입이 아닌** custom ASGI mount 는
    positive-type 미증명이므로 단일 ``unresolvable`` 에 충전돼야
    한다(fail-closed).

    이전 게이트는 ``getattr(sub, "routes", None) is not None`` 라
    ``routes`` duck-typing 만 있어도(빈 ``routes=[]`` 포함) 재귀 후
    조용히 통과 → 그런 custom ASGI 가 ``__call__`` 에서 request body/
    Pydantic 검증을 수행하면 S2 default-deny 가 우회됐다(fail-open).
    본 canary 는 ``routes`` 속성 존재만으로 통과되지 않고 positive-type
    증명(known route-container ∨ known-safe non-validation 타입)만이
    PASS 임을 행위로 고정한다.
    """

    class _DuckRoutesEmpty:
        """``routes=[]`` 를 가지나 알려진 route-container 가 아닌
        custom ASGI(``__call__`` 에서 body 검증 가능)."""

        routes: list[Any] = []

        async def __call__(
            self, scope: Any, receive: Any, send: Any
        ) -> None:  # pragma: no cover - 구조 증명용
            TypeAdapter(dict[str, int]).validate_python({})

    class _DuckRoutesNonEmpty:
        """``routes`` 가 비어있지 않은 임의 객체 리스트(Starlette route
        타입 아님) — duck-typing 만으로 재귀하면 오탐."""

        def __init__(self) -> None:
            self.routes = [object()]

        async def __call__(
            self, scope: Any, receive: Any, send: Any
        ) -> None: ...  # pragma: no cover

    parent = FastAPI()
    parent.mount("/duck-empty", _DuckRoutesEmpty())
    parent.mount("/duck-nonempty", _DuckRoutesNonEmpty())
    collected = _collect_s2(parent)

    for tag in ("/duck-empty", "/duck-nonempty"):
        assert any(tag in u for u in collected.unresolvable), (
            f"routes duck-typed custom ASGI mount({tag}) 가 단일 "
            f"unresolvable 에 미충전 — routes 속성/empty-route 만으로 "
            f"재귀·통과(fail-open): {collected.unresolvable}"
        )
    assert not collected.body_models, (
        "duck-typed custom ASGI mount 로 재귀해 body_models 가 수집됨 "
        f"(known route-container 가 아닌데 재귀): {collected.body_models}"
    )


def test_cv1_known_empty_route_container_recurses_positive_type() -> None:
    """CV1 보강(대조): 알려진 route-container 타입은 ``routes=[]`` 로
    비어 있어도 positive-type 으로 재귀가 완결(검증 surface 0)되어
    ``unresolvable`` 에 충전되지 않는다.

    fail-closed 가 빈 known 컨테이너까지 잘못 거부하면 false-positive
    이다. ``Mount(routes=[...])`` 는 Starlette 가 ``Router`` 로
    wrapping 하므로 known route-container positive-type 면제 경로를
    탄다(empty known container = surface 0, ≠ unknown ASGI).
    """
    parent = FastAPI()
    parent.routes.append(Mount("/empty-router", routes=[]))
    parent.mount("/empty-fastapi", FastAPI())
    collected = _collect_s2(parent)
    assert not collected.unresolvable, (
        "known route-container(빈 Router/FastAPI sub-app)가 fail-closed "
        f"오거부됨(false-positive — empty ≠ unknown): {collected.unresolvable}"
    )


def test_inv3_s2_introspection_exception_charges_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INV-3 정밀화(Codex `review-mpagchqw` [P2]): S2 introspection
    예외(``get_flat_dependant``)가 **삼켜져 route 가 조용히 누락**되지
    않고 **단일 ``unresolvable`` sink 에 충전**됨을 행위로 증명한다.

    이전 구현은 ``except Exception: pass`` 로 예외를 삼켜 그 route 의
    body params 가 default-deny 에서 green 으로 새는 fail-open 이었다
    (예외 route 가 unresolvable 미충전 → ``unresolvable == ∅`` 인양
    PASS). 본 canary 는 ``get_flat_dependant`` 가 raise 하도록
    monkeypatch 한 뒤, ``_collect_s2`` 가 그 route 식별자를
    ``unresolvable`` 에 추가하는지 단언한다. 누락(=fail-open)이면 red.
    """
    import sys

    lock_mod = sys.modules[__name__]

    sub = FastAPI()

    @sub.post("/boom")
    def _boom(body: dict[str, int]) -> dict:  # pragma: no cover - 구조용
        return {}

    def _raising_get_flat_dependant(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic introspection failure")

    # 본 모듈이 import 한 심볼을 patch(호출부가 모듈-로컬 이름 사용).
    monkeypatch.setattr(lock_mod, "get_flat_dependant", _raising_get_flat_dependant)

    collected = _collect_s2(sub)

    # 예외가 삼켜졌다면 unresolvable 가 비어 fail-open. INV-3 single
    # fail-closed sink 가 그 route 식별자를 충전해야 한다.
    assert collected.unresolvable, (
        "INV-3 위반 — get_flat_dependant 예외가 삼켜져 route 가 "
        "조용히 누락(unresolvable 미충전 = default-deny fail-open). "
        "모든 introspection 예외는 single fail-closed sink 에 충전돼야 "
        "한다(삼키고 skip 0)"
    )
    assert any(
        "/boom#dep_body" in u and "get_flat_dependant 예외" in u
        for u in collected.unresolvable
    ), (
        f"INV-3 — 예외가 route 식별자와 함께 충전되지 않음(진단 부재): "
        f"{collected.unresolvable}"
    )

    # 단일 sink 가 ≠∅ 이면 무조건 FAIL(verdict 합류 확인).
    disc = _discover_all(_SurfaceModels(site_models=[], site_roots=[], unresolvable=[]))
    verdict = compute_verdict(
        disc,
        collected.unresolvable,
        registered_dict_keys=_REGISTERED_DICT_KEYS,
        registered_validator_ids=_REGISTERED_VALIDATOR_SURFACE_IDS,
    )
    assert not verdict.ok, (
        "INV-3 — unresolvable ≠ ∅ 인데 compute_verdict 가 PASS "
        "(single fail-closed sink 미작동)"
    )
