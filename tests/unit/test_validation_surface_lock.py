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
    owner: type | None, field_path: tuple[str, ...], validating_site: str
) -> tuple[str, str, str]:
    """비-``dict[str,Any]`` dict 노드를 **(owner qualname,
    caller-visible static schema full field-path, validating-site)**
    키로 정규화(INV-1 — site 포함 + full-path).

    ``field_path`` = 루트 요청 모델부터 그 dict 노드까지의 **부모
    필드명 경로 전체**(``("a", "creds")`` — Annotated unwrap·Union·
    container 인덱스는 필드가 아니므로 미포함; 해석 B). 매칭 키의
    path 성분은 ``".".join(field_path)`` 전체다 — **마지막-owner
    suffix 정규화 폐기**([P2] nested full-path key).

    이전 구현은 path 문자열에서 마지막 owner qualname 이후 suffix
    만 남겼다. 동일 nested ``BaseModel`` 타입이 한 요청 모델의 **두
    필드에 재사용**되고 그 nested 에 unsafe dict 필드가 있으면
    (``Parent.a: Inner`` / ``Parent.b: Inner``, ``Inner.creds:
    dict[str,str]``), 두 경로의 최종 owner(``Inner``)·필드(``creds``)
    가 같아 ``(Inner, creds, site)`` 단일 키로 **병합**됐다. 그러면
    ``Parent.a`` 경로의 pre-reject proof 가 무가드 ``Parent.b``
    경로까지 덮어 fail-open. full static schema path 를 보존하면
    ``(Inner, a.creds, site)`` ≠ ``(Inner, b.creds, site)`` 로
    distinct → 각 부모 경로가 자기 pre-reject proof 필요(무가드
    경로 UNPROVEN→FAIL). 같은 owner 라도 **다른** ``dict[str,T]``
    필드가 추가되면 별 키, **같은 (owner,field-path) 라도 다른
    검증-site**(S1 callee / S2 route+entrypoint)면 site 별 키가 별도
    (per-(owner,full-path,site) — fail-open 차단).

    flat top-level dict 필드(``AccountUpdateRequest.credentials``)는
    부모 필드 경로가 단일 필드뿐이라 ``field_path == ("credentials",)``
    → path 성분 ``"credentials"``(기존 registry 키 불변 — 회귀 없음).
    """
    oq = owner.__qualname__ if owner is not None else "<root>"
    field = ".".join(field_path) if field_path else ""
    return (oq, field, validating_site)


def _discover(  # noqa: C901 - enumeration 은 단일 책임이나 타입 분기多
    tp: Any,
    path: str,
    disc: Discovered,
    *,
    validating_site: str,
    seen: frozenset[int] = frozenset(),
    owner: type | None = None,
    field_path: tuple[str, ...] = (),
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

    ``field_path`` = 루트 요청 모델부터 현재 노드까지의 **부모 필드명
    경로**([P2] nested full-path key). BaseModel 필드 진입 시에만
    그 필드명을 append 하며(Annotated unwrap·Union·container 인덱스
    재귀는 필드가 아니므로 그대로 전달 — 해석 B 인덱스 면제), dict
    노드 키의 path 성분으로 그 full-path 전체를 쓴다(마지막-owner
    suffix 정규화 폐기 — 동일 nested 타입 2필드 재사용 시 부모 경로가
    달라 distinct 키).
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
            inner,
            path,
            disc,
            validating_site=validating_site,
            seen=seen,
            owner=owner,
            field_path=field_path,
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
                field_path=field_path,
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
        # 비-dict[str,Any] dict 노드 — (owner, full field-path, site)
        # 키로 기록(마지막-owner suffix 아님 — [P2] nested full-path).
        disc.dict_nodes.add(_owner_field_key(owner, field_path, validating_site))
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
                field_path=field_path,
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
            # owner = 이 BaseModel — 자식 dict 노드 (owner,field,site)
            # 귀속. field_path 에 이 필드명 append([P2] full-path —
            # 같은 nested 타입이 2필드 재사용돼도 부모 경로가 달라
            # distinct 키; root 모델 자신의 필드부터 기록되므로 flat
            # 필드는 단일 성분 ``(fname,)`` = 기존 registry 키 불변).
            _discover(
                fi.annotation,
                fpath,
                disc,
                validating_site=validating_site,
                seen=child_seen,
                owner=tp,
                field_path=(*field_path, fname),
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
    # INV-1 정밀화(Codex attempt-5 [P2] — site granularity 과병합
    # 회귀 락): 이 검증 호출을 감싸는 **가장 가까운 enclosing
    # FunctionDef/AsyncFunctionDef 의 dotted qualname**(route
    # handler/endpoint 함수; 중첩 시 ``outer.inner``, 메서드는
    # ``Class.method``). lineno-agnostic 하면서도 같은 모듈·같은
    # 모델의 검증 호출이 **다른 handler** 면 distinct site-id 가
    # 되도록 하는 안정·distinct 식별자. 모듈 스코프(어떤 함수에도
    # 안 감싸인) 호출은 ``"<module>"``. enclosing 함수 qualname 이
    # pre-reject 가드 적용 경계(자연 floor) — 같은 함수 내 동일
    # 모델 2회 호출은 동일 가드 context 라 더 미세 단위 불요.
    enclosing: str


def _enclosing_callable_qualname(tree: ast.AST, call_node: ast.Call) -> str:
    """``call_node`` 를 감싸는 가장 가까운 FunctionDef/AsyncFunctionDef
    의 **dotted qualname** 을 AST 로 도출(INV-1 정밀화 — site-id
    enclosing-qualname 성분).

    부모 체인을 따라 ClassDef/FunctionDef/AsyncFunctionDef 이름을
    바깥→안 순서로 모아 ``.`` 으로 잇는다(중첩 함수 ``outer.inner``,
    메서드 ``Class.method``, route handler/endpoint 함수). 어떤
    함수에도 감싸이지 않은 모듈 스코프 호출은 ``"<module>"``.
    lineno 는 포함하지 않는다(fragile-by-design 회피) — enclosing
    함수 qualname 만으로 같은 모듈·같은 모델의 distinct handler 가
    distinct site-id 가 된다(과병합 회귀 영구 락).
    """
    parent: dict[int, ast.AST] = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[id(child)] = p
    chain: list[str] = []
    cur: ast.AST | None = parent.get(id(call_node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            chain.append(cur.name)
        cur = parent.get(id(cur))
    if not chain:
        return "<module>"
    return ".".join(reversed(chain))


# BaseModel 생성자-경로 검증 site 의 합성 ``method`` 마커 —
# ``model_validate`` 군과 동형으로 S1 source walk 하되, 정적
# resolve 불가 생성자-스타일 검증은 INV-3 single-sink 로
# unresolvable 충전(default-deny). 실제 Pydantic API 이름과
# 충돌하지 않는 sentinel(``_PYDANTIC_ENTRYPOINT_METHODS`` 와
# 교집합 ∅).
_CONSTRUCTOR_VALIDATION_METHOD = "<ctor>"

# raw-body **parsed-object** source 를 만드는 호출(말단 식별자
# 기준 — ``request.json()`` / ``json.loads(...)``). 이 호출 결과를
# 담은 변수(및 Name→Name 단순 alias 전이)가 생성자 인자로 **그
# 자체** 전달되면(``Req(**payload)`` / ``Req(payload)``) 그
# 생성자는 raw-body 검증 문맥이다. ``request.body()``(raw bytes)는
# 그 자체로 모델 검증 입력이 아니므로(``json.loads`` 의 인자로만
# 쓰임) seed 에서 제외 — over-taint(``body.x`` 파생 등) 로 무관한
# 일반 객체 생성을 false-positive 로 잡지 않도록 좁힌다.
_RAW_BODY_PARSED_CALL_NAMES: frozenset[str] = frozenset({"json", "loads"})


def _enclosing_funcdef(
    tree: ast.AST, call_node: ast.Call
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """``call_node`` 를 감싸는 가장 가까운 (Async)FunctionDef. 없으면
    None(모듈 스코프).
    """
    parent: dict[int, ast.AST] = {}
    for p in ast.walk(tree):
        for child in ast.iter_child_nodes(p):
            parent[id(child)] = p
    cur: ast.AST | None = parent.get(id(call_node))
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur
        cur = parent.get(id(cur))
    return None


def _raw_body_tainted_names(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """``fn`` 본문에서 raw-body **parsed-object** 입력을 담은 변수
    이름 집합(Name→Name 단순 alias 전이 폐포).

    seed = ``request.json()`` / ``json.loads(...)`` 호출 결과를
    **직접** 담은 대입 target Name(``payload = json.loads(raw)`` ·
    ``data: dict = await request.json()`` — assignment 형태 무관,
    ``_assignment_bindings`` 정규화). 이후 ``y = x`` **Name→Name
    단순 alias**(RHS 가 정확히 tainted Name)만 고정점 전파한다.

    **attribute/subscript 파생은 전파하지 않는다**:
    ``body = json.loads(raw)`` 의 ``body`` 는 seed 지만
    ``cfg = body.bot_id`` 의 ``cfg`` 는 raw-body 검증 입력이 아닌
    이미 추출된 필드값이므로 tainted 아님(over-taint 로 무관한
    일반 객체 생성 ``BotConfig(bot_id=body.bot_id)`` 을
    false-positive 로 잡는 것을 차단 — 검증-source 자체만 추적).
    """
    tainted: set[str] = set()

    def _is_parsed_call(rhs: ast.expr) -> bool:
        for sub in ast.walk(rhs):
            if isinstance(sub, ast.Call) and isinstance(
                sub.func, (ast.Name, ast.Attribute)
            ):
                if _ref_terminal_name(sub.func) in _RAW_BODY_PARSED_CALL_NAMES:
                    return True
        return False

    def _strip(e: ast.expr) -> ast.expr:
        # ``await x`` 의 await 를 벗겨 내부 표현으로(직접 source 판정).
        return e.value if isinstance(e, ast.Await) else e

    changed = True
    while changed:
        changed = False
        for stmt in fn.body:
            for node in ast.walk(stmt):
                for tgt_names, rhs in _assignment_bindings(node):
                    core = _strip(rhs)
                    is_seed = _is_parsed_call(rhs)
                    is_alias = isinstance(core, ast.Name) and core.id in tainted
                    if not (is_seed or is_alias):
                        continue
                    for nm in tgt_names:
                        if nm not in tainted:
                            tainted.add(nm)
                            changed = True
    return tainted


def _is_raw_body_parsed_call(e: ast.expr) -> bool:
    """``e`` 가 ``request.json()`` / ``json.loads(...)`` (또는 그
    ``await``) 직접 호출인가 — 중간 변수 없는 raw-body parsed-object
    source.
    """
    if isinstance(e, ast.Await):
        e = e.value
    return (
        isinstance(e, ast.Call)
        and isinstance(e.func, (ast.Name, ast.Attribute))
        and _ref_terminal_name(e.func) in _RAW_BODY_PARSED_CALL_NAMES
    )


def _is_body_derived_value(v: ast.expr, raw_body_names: set[str]) -> bool:
    """``v`` 가 caller-controlled parsed-body 에서 **파생된** 값인가
    (S1a [P2] body-kwarg 생성자-경로 탐지용 — 파생 폐포).

    body-derived = (a) raw-body parsed-object **그 자체**
    (``payload`` tainted Name · ``await request.json()`` /
    ``json.loads(raw)`` 직접 호출), 또는 (b) 그 parsed-object 의
    임의 **subscript/attribute 파생 체인**(``payload["credentials"]``
    · ``payload.credentials`` · ``body["a"]["b"]`` · ``await
    request.json()["x"]``). subscript key/attr 체인을 끝까지 벗겨
    말단 base 가 tainted Name 또는 raw-body parsed call 이면 True.

    이 술어는 ``Req(credentials=payload["credentials"], ...)`` 처럼
    parsed body 의 **필드값을 BaseModel 생성자 인자**(kwarg 포함)로
    넘기는 경로를 잡기 위한 것이다 — Pydantic 이 그 dict 필드의
    caller-controlled key/value 를 검증해 422 ``loc`` 에 반사할 수
    있어 lock 우회 벡터다. ``_raw_body_tainted_names`` 의 exact-value
    closure(unpack/positional 형태가 쓰는 attribute/subscript
    **비**전파)는 그대로 두고, 본 술어만 파생 체인을 추적한다
    (over-taint 로 무관한 일반 객체 생성을 잡지 않도록 호출측에서
    callee BaseModel-positive-resolve 게이트와 결합 — 모호성은
    positive 증명으로만 해소).
    """
    cur: ast.expr = v
    # subscript/attribute 파생 체인을 말단 base 까지 벗긴다.
    while isinstance(cur, (ast.Subscript, ast.Attribute)):
        cur = cur.value
    if isinstance(cur, ast.Name) and cur.id in raw_body_names:
        return True
    return _is_raw_body_parsed_call(cur)


def _ctor_raw_body_form(call: ast.Call, raw_body_names: set[str]) -> str | None:
    """생성자 호출 인자가 caller-controlled raw-body 입력을 검증 입력
    으로 받는 형태인가, 그렇다면 어떤 형태인가.

    반환:
    - ``"unpack"`` — ``Req(**payload)`` / ``Req(**await
      request.json())``: raw-body parsed dict 를 ``**``-unpack 하는
      형태. Pydantic 생성자 검증의 **정의 형태**이며 builtin/helper
      는 절대 raw-body 를 이렇게 unpack 하지 않는다 → callee 의
      BaseModel resolve 여부와 무관하게 항상 생성자-경로 검증 site
      (resolve 안 되면 _resolve_s1 에서 default-deny unresolvable).
    - ``"positional"`` — ``Req(payload)`` / ``Req(json.loads(raw))``:
      raw-body parsed dict 를 단일 positional 인자로 넘기는 형태.
      ``len(payload)``/``set(payload)``/``list(payload)`` 같은
      builtin 가드와 형태가 동일해 **모호**하므로, 호출측에서
      callee 가 정적 BaseModel 서브클래스로 resolve 될 때만 검증
      site 로 채택한다(그 외엔 무관한 builtin/helper — false-positive
      0). 모호성은 BaseModel-resolve 라는 positive 증명으로만 해소.
    - ``"kwarg"`` — ``Req(credentials=payload["credentials"], ...)``
      (S1a [P2] 완결): parsed body 에서 **파생된 값**(subscript/attr
      체인 ``payload["x"]``/``body.x``/raw-body call 파생)이
      BaseModel 생성자의 **임의 인자**(keyword/positional/``**``)로
      흘러가는 형태. Pydantic 이 그 인자로 받은 dict 필드의
      caller-controlled key/value 를 검증해 422 ``loc`` 에 반사할 수
      있어 unpack/positional 만 보던 attempt-8 탐지의 우회 벡터다.
      ``len(payload)``/``BotConfig(bot_id=body.bot_id)`` 같은 builtin/
      무관 객체 생성과 형태가 모호하므로 positional 과 동일하게
      callee BaseModel-positive-resolve 시에만 site(호출측 게이트 —
      false-positive 0). unpack/positional 보다 **약한** 형태이므로
      그 둘에 매칭되지 않은 경우에만 평가한다.
    - ``None`` — body-파생값이 어떤 인자로도 안 감(상수/literal/
      raw-body 무관 인자만, 또는 raw-body 자체가 함수 안에 없음).
      검증-source 파생 없음 → 생성자-경로 검증 아님
      (``HTTPException``/``isinstance``/``Path(p)``/``_Helper(a=1)``
      false-positive 차단).
    """

    def _is_raw_body_value(v: ast.expr) -> bool:
        if isinstance(v, ast.Name) and v.id in raw_body_names:
            return True
        return _is_raw_body_parsed_call(v)

    # ``**``-unpack 검증 형태 — builtin/helper 는 raw-body 를 이렇게
    # unpack 하지 않으므로 callee resolve 무관 항상 생성자-경로 site.
    for kw in call.keywords:
        if kw.arg is None and _is_raw_body_value(kw.value):
            return "unpack"
    # 단일 positional 검증 입력 — builtin 가드(len/set/list)와 형태
    # 동일·모호. callee BaseModel positive resolve 시에만 site.
    if len(call.args) == 1 and not call.keywords:
        only = call.args[0]
        if not isinstance(only, ast.Starred) and _is_raw_body_value(only):
            return "positional"
    # body-파생값(subscript/attr 체인)이 **임의 생성자 인자**(kwarg
    # 포함)로 흘러가는 형태 — parsed body 의 필드값을 BaseModel
    # 생성자 인자로 넘기는 우회(``Req(credentials=payload["x"])``).
    # positional 과 동형으로 모호 → callee BaseModel-positive-resolve
    # 게이트(호출측)에서만 site 채택(false-positive 0). positional
    # 인자·keyword 인자·``**``-인자 어디든 1개라도 body-파생이면 True.
    arg_exprs: list[ast.expr] = []
    for a in call.args:
        arg_exprs.append(a.value if isinstance(a, ast.Starred) else a)
    arg_exprs.extend(kw.value for kw in call.keywords)
    for a in arg_exprs:
        if _is_body_derived_value(a, raw_body_names):
            return "kwarg"
    return None


def _scan_s1_entrypoints() -> list[_EntrypointSite]:
    """routes/**/*.py AST 에서 Pydantic 검증 entrypoint 호출 전수.

    ``<Recv>.<method>(...)`` 형태의 call 중 method ∈ entrypoint API
    (model_validate 군). 추가로 raw-body 검증 문맥의 **BaseModel
    생성자 호출**(``<Name>(**payload)`` / ``<Name>(payload)`` —
    caller-controlled raw-body 입력이 생성자 인자) 도 S1 검증 site
    로 수집한다(model_validate 와 동형 — S1a/INV-3 [P2]; 새 raw-body
    handler 가 일반 Pydantic 생성자 ``Req(**payload)`` 로 검증해도
    discovery lock 이 우회되지 않게). 손-열거 census 금지 — AST
    self-derive. 각 site 는 그 호출을 감싸는 enclosing callable
    qualname 도 보존한다(INV-1 정밀화 — 같은 모듈·같은 모델이라도
    다른 handler 면 distinct site-id; 과병합 fail-open 차단).
    """
    sites: list[_EntrypointSite] = []
    for modname, path in _route_modules():
        tree = ast.parse(path.read_text(), filename=str(path))
        # 함수별 raw-body tainted-name 캐시(생성자-경로 문맥 판정용).
        raw_body_cache: dict[int, set[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
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
                        enclosing=_enclosing_callable_qualname(tree, node),
                    )
                )
                continue
            # BaseModel 생성자-경로 검증 탐지 (S1a/INV-3 [P2]).
            # callee 가 단순 이름(``Req``) 또는 점 접근(``m.Req``)인
            # 생성자 호출만 후보. 생성자 인자가 caller-controlled
            # raw-body parsed-object **그 자체**(``Req(**payload)``/
            # ``Req(**await request.json())``/``Req(payload)``)이거나,
            # parsed body 에서 **파생된 값**(``Req(creds=payload["x"])``
            # — subscript/attr 체인)이 임의 생성자 인자(kwarg 포함)로
            # 흘러갈 때 S1 site (S1a [P2] body-kwarg 완결). raw-body
            # 와 무관한 일반 객체 생성·상수/literal 인자만의 생성은
            # 제외(false-positive 0). 모호 형태(positional/kwarg)는
            # callee BaseModel-positive-resolve 시에만 site 채택, 동적
            # 클래스 ``**``-unpack 은 _resolve_s1 에서 INV-3
            # single-sink unresolvable(default-deny).
            if not isinstance(func, (ast.Name, ast.Attribute)):
                continue
            fn = _enclosing_funcdef(tree, node)
            if fn is None:
                # 모듈 스코프 객체 생성 — raw-body handler 문맥 아님.
                continue
            key = id(fn)
            if key not in raw_body_cache:
                raw_body_cache[key] = _raw_body_tainted_names(fn)
            raw_body_names = raw_body_cache[key]
            form = _ctor_raw_body_form(node, raw_body_names)
            if form is None:
                # 생성자 인자가 raw-body parsed-object 자체가 아님 —
                # 무관한 일반 객체 생성(검증-source 동일성 없음). skip.
                continue
            if isinstance(func, ast.Name):
                recv_name = func.id
            else:
                recv_name = ast.unparse(func)
            if form in ("positional", "kwarg"):
                # ``Req(payload)``/``Req(creds=payload["x"])`` 는
                # ``len(payload)``/``BotConfig(bot_id=body.bot_id)``
                # builtin·무관 객체 생성과 형태 동일·모호 — callee 가
                # 정적 BaseModel 서브클래스로 resolve 될 때만 검증
                # site (positive 증명으로만 모호성 해소; 그 외 builtin/
                # helper/무관 객체 false-positive 0). ``**``-unpack
                # 형태는 builtin 이 안 쓰므로 resolve 무관 항상 site
                # (아래; 동적 클래스면 _resolve_s1 default-deny).
                resolved = _resolve_name_in_module(modname, recv_name)
                if not (isinstance(resolved, type) and issubclass(resolved, BaseModel)):
                    continue
            sites.append(
                _EntrypointSite(
                    module=modname,
                    lineno=node.lineno,
                    callee_src=f"{recv_name}.{_CONSTRUCTOR_VALIDATION_METHOD}",
                    receiver=recv_name,
                    method=_CONSTRUCTOR_VALIDATION_METHOD,
                    enclosing=_enclosing_callable_qualname(tree, node),
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
) -> tuple[list[tuple[str, type[BaseModel]]], bool]:
    """제네릭 helper(``model.model_validate``)의 model 인자 추적.

    helper 의 ``model`` 파라미터로 전달되는 **모든** 호출 인자를
    검사한다. 반환: ((caller-site, literal-BaseModel) 리스트,
    all_resolved). ``caller-site`` = 그 helper 호출을 감싸는 **가장
    가까운 enclosing callable 의 dotted qualname**(즉 helper 를
    invoke 한 endpoint/handler 함수; 모듈 스코프면 ``"<module>"``).

    INV-1 정밀화(Codex attempt-6 [P2] — attempt-5 enclosing-qualname
    원칙을 helper-trace 경로에 동일 확장): 이전 구현은 helper 본문
    내부 단일 ``model.model_validate`` call site 의 sid 와 model 만
    보존하고 helper 를 **호출한 endpoint** 정보를 버린 채
    **model-only dedupe** 했다. 같은 BaseModel 을 2개 endpoint 가
    같은 helper 로 검증하고 그중 **한** handler 만 unsafe dict 필드를
    pre-reject 하면, model-only dedupe 가 그 dict 노드를 단일
    site-id 로 만들어 한 endpoint 의 pre-reject proof 가 가드 없는
    다른 endpoint 에도 재사용된다(attempt-5 와 동일 fail-open class
    의 helper-trace 변종). 따라서 helper 호출 site 별로 **(caller
    enclosing-callable-qualname, model)** 단위로 보존한다(model-only
    dedupe 폐기). 같은 helper·같은 모델이라도 호출 endpoint(enclosing
    handler)가 다르면 distinct caller-site → distinct site-id →
    DISCOVERED dict-node 키·``_REGISTERED_DICT_PROOFS`` 키 양쪽 그
    caller-site 포함(INV-1 set-difference 정합; 가드 없는 caller-site
    는 자기 proof 없어 UNPROVEN→FAIL).

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
    # (caller-site, model) 쌍 — model-only dedupe 폐기(INV-1 정밀화).
    # caller-site = helper 호출 노드를 감싸는 enclosing callable
    # qualname(helper 를 invoke 한 endpoint/handler). 같은
    # (caller-site, model) 만 dedupe(같은 endpoint 안 동일 helper·
    # 동일 모델 2회 호출은 동일 가드 context — 자연 floor).
    pairs: list[tuple[str, type[BaseModel]]] = []
    seen_pairs: set[tuple[str, int]] = set()
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
        # 이 helper 호출을 감싸는 enclosing callable(=helper 를 invoke
        # 한 endpoint/handler) qualname — attempt-5 site-id 원칙을
        # helper-trace caller 경로에 동일 적용.
        caller_site = _enclosing_callable_qualname(tree, node)
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
                pk = (caller_site, id(resolved))
                if pk not in seen_pairs:
                    seen_pairs.add(pk)
                    pairs.append((caller_site, resolved))
                continue
        # 변수/표현식/비-BaseModel literal → 정적 resolve 불가.
        all_resolved = False
    if not saw_call:
        return [], False
    return pairs, all_resolved


def _resolve_s1() -> _S1Resolve:
    """S1a∪S1b: entrypoint site 전수 → 검증 모델 정적 resolve.

    - ``<Model>.model_validate`` : 모듈 namespace 에서 literal Model.
    - ``<Model>(**payload)`` 생성자-경로 검증 : 모듈 namespace 에서
      literal BaseModel 이면 model_validate 와 동형 S1 source.
      정적 resolve 불가(동적 클래스·미해결 qualified name) 면
      INV-3 single-sink unresolvable(default-deny — 우회 차단).
    - ``TypeAdapter(...).validate_*`` : 동적 → 단일 unresolvable.
    - 제네릭 ``model.model_validate`` : helper model 인자 전수 추적.
      **하나라도** literal-BaseModel resolve 안 되면 site 전체
      unresolvable(any-match → all-must-resolve, INV-3).
    """
    res = _S1Resolve()
    for site in _scan_s1_entrypoints():
        # sid 형식: ``module:lineno:enclosing-qualname:callee_src``.
        # lineno 는 helper-trace(_trace_generic_helper_model_args)
        # 가 site.lineno 로 호출을 특정하는 데만 쓰이고 안정
        # site-id(``_stable_s1_site``)에서는 제거된다(fragile
        # 회피). enclosing-qualname 은 안정·distinct call-site
        # 식별자로 보존된다(INV-1 정밀화 — 과병합 차단). module·
        # lineno 는 단일 세그먼트이고 enclosing/callee_src 에는
        # ``:`` 가 없으므로 4-세그먼트 split 이 모호하지 않다.
        sid = f"{site.module}:{site.lineno}:{site.enclosing}:{site.callee_src}"
        recv = site.receiver
        cls = _resolve_name_in_module(site.module, recv)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            res.models.append((sid, cls))
            continue
        if site.method == _CONSTRUCTOR_VALIDATION_METHOD:
            # raw-body 검증 문맥의 BaseModel 생성자 호출인데 callee
            # 가 정적으로 BaseModel 서브클래스로 resolve 안 됨(동적
            # 클래스·미해결 qualified name 등) → INV-3 single-sink
            # unresolvable (default-deny — 생성자-경로로 lock 우회
            # 차단). 정적 BaseModel 이면 위 분기에서 이미 model_validate
            # 와 동형 S1 source 로 충전됐다.
            res.unresolvable.append(
                f"{sid} → BaseModel 생성자-경로 검증인데 callee 가 정적 "
                "literal-BaseModel 로 resolve 불가 (동적 클래스/미해결 "
                "qualified name — INV-3 single-sink, default-deny)"
            )
            continue
        if "TypeAdapter(" in recv:
            res.unresolvable.append(
                f"{sid} → TypeAdapter 동적 검증 (정적 resolve 불가 — "
                "lock-walkable 아님)"
            )
            continue
        if recv.isidentifier():
            pairs, all_resolved = _trace_generic_helper_model_args(site)
            if not all_resolved or not pairs:
                # any-match → all-must-resolve: literal+dynamic 혼재
                # 또는 추적 불가 → site 전체 단일 unresolvable.
                res.unresolvable.append(
                    f"{sid} → 제네릭 helper model 인자 전수 정적 "
                    "literal-BaseModel resolve 실패 (any-match → "
                    "all-must-resolve; literal+dynamic 혼재/추적불가)"
                )
                continue
            # INV-1 정밀화(attempt-6 [P2]): helper-trace site-id 의
            # **enclosing 세그먼트를 helper 내부(site.enclosing)가
            # 아니라 helper 를 invoke 한 caller endpoint qualname**
            # 으로 둔다. 같은 helper·같은 모델이라도 caller endpoint
            # 가 다르면 distinct enclosing 세그먼트 → ``_stable_s1_site``
            # 정규화 후에도 distinct stable site-id 가 되어 한 endpoint
            # 의 pre-reject proof 가 가드 없는 다른 endpoint dict 노드로
            # 재사용되지 않는다(attempt-5 와 동형의 helper-trace 변종
            # fail-open 차단). sid 형식(``module:lineno:enclosing:
            # callee_src``)·4-세그먼트 split 불변 — enclosing 세그먼트만
            # caller_site 로 치환하고 ``#Model`` 은 callee_src 마지막
            # 세그먼트에 부착(``:`` 무포함 유지).
            for caller_site, m in pairs:
                helper_sid = (
                    f"{site.module}:{site.lineno}:{caller_site}:"
                    f"{site.callee_src}#{m.__name__}"
                )
                res.models.append((helper_sid, m))
            continue
        res.unresolvable.append(f"{sid} → receiver 정적 resolve 불가")
    return res


def _ref_terminal_name(node: ast.expr) -> str | None:
    """``Name``/``Attribute`` 참조의 **말단 식별자**(점 접근의 마지막
    attr; ``pydantic.ValidationError`` → ``ValidationError``,
    ``ValidationError`` → ``ValidationError``). 그 외 None.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _except_handles_validation_error(handler: ast.ExceptHandler) -> bool:
    """``except`` handler 타입 표현이 ``ValidationError`` 를 잡는가.

    ``except ValidationError``, ``except pydantic.ValidationError``,
    ``except (X, ValidationError)``, ``except (A | ValidationError)``
    형태를 모두 인식한다(말단 식별자 == ``ValidationError`` 인
    Name/Attribute 가 타입 표현 트리 어디에든 있으면 True). bare
    ``except:``/타입 미지정은 False(본 게이트는 ValidationError 전용).
    """
    t = handler.type
    if t is None:
        return False
    for n in ast.walk(t):
        if isinstance(n, (ast.Name, ast.Attribute)):
            if _ref_terminal_name(n) == "ValidationError":
                return True
    return False


def _target_names(target: ast.expr) -> list[str]:
    """대입 target 표현에서 바인딩되는 **단순 Name** 들을 도출.

    ``x`` (Name) → ``[x]``; ``a, b`` / ``[a, b]`` / ``a, *rest``
    (Tuple/List/Starred unpack) → 각 element 의 Name; attribute/
    subscript target(``self.x``/``d[k]``) 은 단순 변수 바인딩이
    아니므로 무시(taint 전파 대상 아님). 중첩 unpack 도 재귀.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for el in target.elts:
            out.extend(_target_names(el))
        return out
    return []


def _assignment_bindings(
    node: ast.AST,
) -> list[tuple[list[str], ast.expr]]:
    """예외-파생 alias/taint 전이를 위한 **대입 형태 정규화**.

    assignment 형태와 무관하게 동일 taint 가 되도록(behavioral),
    ``(bound Name 들, RHS 표현식)`` 쌍 리스트를 반환한다:

    - ``ast.Assign`` (``x = v`` / ``a, b = v`` / 다중 target
      ``a = b = v``): 각 target 의 Name 들, RHS = ``node.value``.
    - ``ast.AnnAssign`` (``errs: list = exc.errors(...)``): target
      이 Name 이고 ``value`` 가 있으면 그 Name, RHS = ``node.value``
      (annotation-only ``x: T`` 는 RHS 없음 → 제외).
    - ``ast.AugAssign`` (``x += exc.json()``): target 이 Name 이면
      그 Name, RHS = ``node.value`` (누적도 예외-파생이면 taint).
    - ``ast.NamedExpr`` (walrus ``(errs := exc.errors())``): target
      Name, RHS = ``node.value``.

    tuple/starred unpack(``a, b = exc, ...``)은 element-level 로
    Name 을 모두 바인딩에 넣어 RHS 가 taint 면 전부 taint 처리한다
    (보수적 — unpack 으로 예외-파생 alias 가 새는 것을 누락 없이).
    attribute/subscript target 은 단순 변수 바인딩이 아니라 제외.
    """
    if isinstance(node, ast.Assign):
        names: list[str] = []
        for tgt in node.targets:
            names.extend(_target_names(tgt))
        return [(names, node.value)] if names else []
    if isinstance(node, ast.AnnAssign):
        if node.value is None:
            return []
        names = _target_names(node.target)
        return [(names, node.value)] if names else []
    if isinstance(node, ast.AugAssign):
        names = _target_names(node.target)
        return [(names, node.value)] if names else []
    if isinstance(node, ast.NamedExpr):
        names = _target_names(node.target)
        return [(names, node.value)] if names else []
    return []


def _exception_alias_names(handler: ast.ExceptHandler) -> set[str]:
    """handler 본문에서 ``as <name>`` 예외 객체 **및 그 단순 별칭**
    변수 이름 집합을 도출(``v = <alias>`` 단순 대입 전이 폐포).

    ``except ... as e:`` 의 ``e`` 에서 시작해, handler 본문의
    ``x = e`` / ``y = x`` 같은 **Name→Name 단순 대입**을 고정점까지
    전파한다. assignment 형태(``ast.Assign``/``ast.AnnAssign``
    ``y: T = e``/``ast.AugAssign``/walrus ``(y := e)``/tuple·
    starred unpack ``a, b = e, _``)와 무관하게 동일 alias 전이
    (behavioral — ``_assignment_bindings`` 정규화). 이로써
    ``errs = e; errs.errors(...)`` · ``errs: list = e`` 같은 변수
    경유 직접 호출도 그 receiver(``errs``)가 별칭 집합에 들어가
    위반으로 잡힌다(substring/Assign-only 로는 못 잡던 변수·
    annotation 경유 우회 차단). ``as`` 이름이 없으면
    (``except ValidationError:``) 빈 집합.
    """
    if handler.name is None:
        return set()
    aliases: set[str] = {handler.name}
    # 고정점 — 새 별칭이 더 생기지 않을 때까지 본문 대입 재스캔
    # (assignment 형태 무관 — _assignment_bindings 정규화).
    changed = True
    while changed:
        changed = False
        for stmt in handler.body:
            for node in ast.walk(stmt):
                for tgt_names, val in _assignment_bindings(node):
                    if not (isinstance(val, ast.Name) and val.id in aliases):
                        continue
                    for nm in tgt_names:
                        if nm not in aliases:
                            aliases.add(nm)
                            changed = True
    return aliases


def _is_chokepoint_call_of(node: ast.expr, aliases: set[str]) -> bool:
    """``node`` 가 ``sanitize_validation_errors(<exc|alias>)`` chokepoint
    호출인가 — ``func`` == ``Name(<chokepoint>)`` 이고 인자
    (positional/keyword) 중 예외 별칭 Name 이 1개 이상(kwarg/줄바꿈
    무관). #1650 SSOT 의 **유일한** sanctioned launder 형태.
    """
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if not (isinstance(f, ast.Name) and f.id == _CHOKEPOINT_NAME):
        return False
    arg_exprs = list(node.args) + [kw.value for kw in node.keywords]
    return any(isinstance(a, ast.Name) and a.id in aliases for a in arg_exprs)


def _expr_taints_from_exc(node: ast.expr, aliases: set[str]) -> bool:
    """``node`` 가 예외 객체(별칭 집합 ``aliases``)에서 **파생된**
    값을 만드는 표현인가 — 단, 단일 chokepoint
    ``sanitize_validation_errors(<alias>)`` 호출**의 인자 위치**에
    들어간 alias 만 launder 된 것으로 보아 그 위치의 ref 는 sink 가
    아니다.

    fail-closed: chokepoint **인자 위치 밖**에서 예외 별칭 Name 이
    그 표현의 서브트리에 **하나라도** 등장하면 taint 로 판정한다 —
    ``str(e)`` · ``e.json()`` · ``e.errors(...)`` · ``repr(e)`` ·
    ``e.__str__()`` · ``f"{e}"`` · ``"x" % e`` · ``"x" + str(e)`` ·
    ``[e]`` · ``{"k": e}`` · 그 외 예외 객체에서 임의로 파생한
    detail 전부(열거 화이트리스트가 아니라 "예외 alias 가 새는
    비-chokepoint 위치 = taint" behavioral 매트릭스 — 새 우회 형태도
    자동 포착).

    mixed-expr 보강 ([P2] — attempt-9 fail-open 봉인): 같은 응답
    표현에 chokepoint 와 raw 예외 참조가 섞이면
    (``{"safe": sanitize_validation_errors(e), "raw": str(e)}``),
    이전 구현은 ``ast.walk`` 중 chokepoint child 인 첫 alias 를
    만나 거기서 조기 ``return False``(clean) 하고 뒤의 sibling
    raw ``str(e)`` 를 못 봐 fail-open 했다. 본 함수는 **표현 전체를
    끝까지 스캔**해, chokepoint 호출 인자 위치에 들어간 alias ref 는
    launder 로 건너뛰되, **그 외 위치의 alias ref 가 하나라도 있으면
    taint** 로 집계한다(launder 범위 = chokepoint 호출 인자 서브트리
    위치에 한정 — chokepoint child 방문이 sibling raw ref 검출을
    단축시키지 않음). chokepoint 호출 노드 자체(``node`` 가 그
    호출)도 taint 아님(인자 alias 는 launder).
    """
    if _is_chokepoint_call_of(node, aliases):
        return False
    for sub in ast.walk(node):
        if not (isinstance(sub, ast.Name) and sub.id in aliases):
            continue
        # 이 alias 참조가 ``node`` 서브트리 어떤 chokepoint 호출의
        # 인자 위치에 들어 있으면 launder — 그 ref 는 sink 아님.
        # **단축 금지**: launder 된 ref 라도 조기 종료하지 않고
        # 다음 alias ref 를 계속 검사한다(sibling raw 누락 차단).
        if _ref_inside_chokepoint(node, sub, aliases):
            continue
        # chokepoint 인자 밖 alias ref — taint(나머지 ref 무관하게
        # 이미 새는 것이 확정).
        return True
    return False


def _ref_inside_chokepoint(root: ast.expr, ref: ast.Name, aliases: set[str]) -> bool:
    """``root`` 서브트리에서 ``ref`` (예외 alias Name 노드)가
    chokepoint 호출 ``sanitize_validation_errors(...)`` 의 인자
    서브트리 안에 포함되면 True(그 alias 는 launder 됨).
    """
    for sub in ast.walk(root):
        if isinstance(sub, ast.Call) and _is_chokepoint_call_of(sub, aliases):
            arg_exprs = list(sub.args) + [kw.value for kw in sub.keywords]
            for a in arg_exprs:
                for inner in ast.walk(a):
                    if inner is ref:
                        return True
    return False


# detail 을 응답 body 로 방출하는 sink 생성자(라우트 전수 실측 =
# ``HTTPException`` 만 사용; ``*Response`` 군은 방어적으로 함께
# 커버해 향후 raw error-response 우회도 fail-closed). substring
# 화이트리스트가 아니라 "이름이 HTTPException 또는 *Response 로
# 끝나는 호출 = 응답 sink" behavioral 규칙.
def _is_response_sink_call(call: ast.Call) -> bool:
    f = call.func
    name = _ref_terminal_name(f) if isinstance(f, (ast.Name, ast.Attribute)) else None
    if name is None:
        return False
    return name == "HTTPException" or name.endswith("Response")


def _handler_emits_unsanitized_exc_detail(
    handler: ast.ExceptHandler, aliases: set[str]
) -> bool:
    """이 ValidationError handler block 이 예외 객체에서 파생된
    detail 을 **chokepoint 미경유**로 응답에 방출하는가(handler-level
    판정 — 전역 count 아님).

    sink 인식(fail-closed):
    - 응답 sink 생성자 호출(``HTTPException(...)``/``*Response(...)``)
      의 임의 인자가 ``_expr_taints_from_exc`` → True 이면 그 handler
      는 미경유 detail 방출.
    - ``raise <expr>`` / ``return <expr>`` 의 ``<expr>`` 가
      exc-taint 이면(예외 객체를 그대로/파생해 raise·return) 미경유
      방출 — ``raise HTTPException(...)`` 는 위 sink 규칙으로 이미
      커버, 추가로 ``return e`` / ``return str(e)`` 같은 raw 방출도
      포착.
    - tainted 값을 변수에 담아 우회(``msg = str(e); detail=msg`` ·
      ``errs: list = e.errors(...); detail=errs`` · ``buf += e.json()``
      · walrus·tuple unpack)는 ``_exception_alias_names`` 의
      Name→Name 전이폐포로 alias 가 확장되고, 또한
      ``<assignment> = <exc-taint expr>`` 대입의 RHS 가 taint 이면
      그 target Name 도 taint-name 으로 전파해 downstream sink 에서
      잡는다(assignment 형태 무관 — ``_assignment_bindings`` 정규화;
      ``ast.Assign``/``ast.AnnAssign``/``ast.AugAssign``/walrus/
      tuple·starred unpack 동등 처리).

    handler 가 ValidationError 를 잡되 detail 을 그 예외에서 안
    만들고 re-raise / 무관 응답이면(예: ``raise HTTPException(...,
    detail="고정 문자열")``) taint 가 없으므로 대상 아님 — 본 함수
    False.
    """
    if not aliases:
        # ``except ValidationError:`` (별칭 없음) — 예외 객체를
        # 직접 detail 로 만들 수 없으므로 미경유 방출 불가.
        return False

    # tainted 변수 이름 전파: ``<assignment> = <exc-taint RHS>`` 면
    # 그 bound Name 도 taint(assignment 형태 무관 —
    # ``_assignment_bindings`` 가 ``ast.Assign``/``ast.AnnAssign``
    # ``errs: list = exc.errors(...)``/``ast.AugAssign``/walrus/
    # tuple·starred unpack 을 동등 정규화. Assign-only 추적이면
    # annotated-assignment 로 예외-파생값을 중간변수에 담아
    # ``HTTPException(detail=errs)`` 로 우회 시 taint 미전파 →
    # fail-open; 형태 무관 동일 taint 로 봉인).
    tainted_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for stmt in handler.body:
            for n in ast.walk(stmt):
                for tgt_names, rhs in _assignment_bindings(n):
                    rhs_aliases = aliases | tainted_names
                    if _expr_taints_from_exc(rhs, rhs_aliases):
                        for nm in tgt_names:
                            if nm not in tainted_names:
                                tainted_names.add(nm)
                                changed = True

    sink_aliases = aliases | tainted_names

    for n in ast.walk(handler):
        # 응답 sink 생성자 — 인자 중 exc-taint 가 하나라도 있으면 위반.
        if isinstance(n, ast.Call) and _is_response_sink_call(n):
            arg_exprs = list(n.args) + [kw.value for kw in n.keywords]
            for a in arg_exprs:
                if _expr_taints_from_exc(a, sink_aliases):
                    return True
        # ``raise <expr>`` — 예외 객체/파생을 그대로 raise.
        if isinstance(n, ast.Raise) and n.exc is not None:
            if _expr_taints_from_exc(n.exc, sink_aliases):
                # ``raise sanitize_validation_errors(e)`` 같은 건
                # 의미상 안 나오지만, 위 _expr_taints_from_exc 가
                # chokepoint launder 를 이미 제외하므로 안전.
                # 단 ``raise HTTPException(...)`` 는 sink-call 규칙이
                # 정밀 — 여기서는 raw ``raise e`` / ``raise X(str(e))``
                # 중 sink-call 아닌 형태를 보강 포착.
                if not (isinstance(n.exc, ast.Call) and _is_response_sink_call(n.exc)):
                    return True
        # ``return <exc-taint>`` — raw 예외 파생을 응답으로 반환.
        if isinstance(n, ast.Return) and n.value is not None:
            if _expr_taints_from_exc(n.value, sink_aliases):
                if not (
                    isinstance(n.value, ast.Call) and _is_response_sink_call(n.value)
                ):
                    return True
    return False


def _scan_validationerror_handler_chokepoint(
    route_modules: list[tuple[str, Path]] | None = None,
) -> tuple[int, list[str]]:
    """**per-handler** chokepoint 강제 (#1650 SSOT, INV-3): 각 raw-body
    ``except (...ValidationError...) as <name>:`` handler 가 예외
    객체에서 파생한 422/HTTP detail 을 방출할 때 **반드시 그 handler
    자신의 ``sanitize_validation_errors(<name|alias>)`` 단일
    chokepoint** 만 거쳐야 한다.

    반환: ``(conforming_choke, nonconforming)``.
    - ``conforming_choke`` = chokepoint 를 실제 사용하는(launder 하는)
      ValidationError handler 수 — #1650 SSOT 가 살아 있다는 positive
      증거(0 이면 SSOT 회귀).
    - ``nonconforming`` = chokepoint 미경유로 예외-파생 detail 을
      방출하는 handler 식별자 리스트. **이 집합이 비어 있어야 PASS.**

    attempt-7 fail-open 봉인: 이전 구현은 **전역** ``choke`` 합과
    ``direct`` 합만 봤다(``direct==0 ∧ 전역 choke>0`` ⟹ PASS). 새
    raw-body handler 가 ``except ValidationError as e:`` 후
    ``detail=str(e)`` / ``e.json()`` / ``repr(e)`` / f-string 보간
    등 ``.errors()`` 가 **아닌** 형태로 우회하면 그 handler 는
    ``.errors()`` 를 안 부르니 ``direct==0`` 이고
    ``sanitize_validation_errors`` 도 안 거치지만, **다른 기존
    handler 들** 때문에 전역 ``choke>0`` 이 유지돼 lock 이
    통과(fail-open)했다. #1650 SSOT 는 *각* ValidationError handler
    가 chokepoint 를 거쳐야 한다 — 전역 합이 아니라 **handler 별**
    강제. 전역 ``direct``/``choke`` 합산 게이트를 폐기하고
    "ValidationError handler 집합 중 chokepoint-미경유 detail 방출
    handler 수 == 0" 단일 단언으로 재집약한다.

    하드코딩 카운트 없음 — routes/**/*.py AST self-derive. handler
    block 단위가 자연 floor(각 ``except ValidationError`` block 이
    #1650 chokepoint SSOT 적용 경계).
    """
    mods = route_modules if route_modules is not None else _route_modules()
    conforming_choke = 0
    nonconforming: list[str] = []
    for modname, path in mods:
        tree = ast.parse(path.read_text(), filename=str(path))
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            if not _except_handles_validation_error(handler):
                continue
            aliases = _exception_alias_names(handler)
            uses_chokepoint = any(
                _is_chokepoint_call_of(c, aliases)
                for c in ast.walk(handler)
                if isinstance(c, ast.Call)
            )
            if uses_chokepoint:
                conforming_choke += 1
            if _handler_emits_unsanitized_exc_detail(handler, aliases):
                nonconforming.append(f"{modname}:L{handler.lineno}")
    return conforming_choke, nonconforming


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
            # INV-1 정밀화(Codex attempt-5 [P2] — S2 site granularity
            # 동형 보장): S2 validating-site 도 distinct call-site 가
            # 되도록 route path 에 더해 **HTTP method 집합 + endpoint
            # 함수 qualname**(route handler/endpoint 함수)을 보존한다.
            # 같은 path 에 다른 method(GET/PUT)·다른 endpoint 함수가
            # 매핑되면(또는 동일 path/다른 handler) S1 의 enclosing
            # -qualname 보존과 동형으로 distinct site-id 가 되어 한
            # site 의 pre-reject 증명이 가드 없는 다른 S2 site 로
            # 재사용되지 않는다. lineno 는 포함하지 않는다(S1 과 동형
            # — fragile 회피; path+method+endpoint qualname 이 안정·
            # distinct call-site 식별자, 자연 floor).
            ep = getattr(r, "endpoint", None)
            ep_qn = getattr(ep, "__qualname__", None) or repr(ep)
            ep_mod = getattr(ep, "__module__", None) or "<?>"
            methods = ",".join(sorted(getattr(r, "methods", None) or []))
            s2_site = f"{full}[{methods}]@{ep_mod}.{ep_qn}"
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
                    out.body_models.append((f"{s2_site}#body_field", ann))
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
                    out.body_models.append((f"{s2_site}#dep_body", ann))
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
    """S1 site_id(``module:lineno:enclosing-qualname:callee_src``
    [+``#Model``])를 **lineno 무관·enclosing-qualname 보존 안정
    site**(``module:enclosing-qualname:callee_src``)로 정규화 —
    INV-1 정밀화(Codex attempt-5 [P2] — site granularity 과병합 락).

    volatile 한 lineno 는 키에서 제거한다(가드 유무는 줄 번호의
    사실이 아니라 그 검증 호출을 감싸는 enclosing handler/endpoint
    함수의 사실이다 — 줄 번호를 키에 넣으면 routes 파일의 무관한
    윗쪽 편집만으로 키가 흔들려 fragile-by-design). 그러나 **enclosing
    callable qualname 은 보존**한다: lineno-agnostic 하게 callee 만
    으로 site 를 정규화하면 같은 route 모듈 내 동일 모델의 검증
    호출이 2개(서로 다른 handler)면 하나의 site-id 로 과병합돼, 한
    handler 의 pre-reject 가드 proof 가 가드 없는 다른 handler 에
    재사용되어 discovery lock 이 fail-open 으로 PASS 한다(attempt-5
    FAIL class). enclosing 함수 qualname 을 site-id 에 두면 같은
    모듈·같은 모델이라도 distinct handler 면 distinct site-id 가
    되어 가드 없는 site 는 자기 proof 가 없어 UNPROVEN→FAIL.
    enclosing 함수가 pre-reject 가드 적용 경계(자연 floor) — 같은
    함수 내 동일 모델 2회 호출은 동일 가드 context 라 더 미세 단위
    불요. sid 는 정확히 4-세그먼트(``module:lineno:enclosing:
    callee_src``)이며 module·lineno 는 단일 세그먼트, enclosing·
    callee_src 에는 ``:`` 가 없다(enclosing 은 식별자+``.``,
    제네릭 helper 의 ``#Model`` suffix 는 callee_src 마지막
    세그먼트에 포함). lineno 만 떼고 ``module:enclosing:callee_src``
    재조립.
    """
    parts = s1_site_id.split(":")
    if len(parts) >= 4:
        module = parts[0]
        # parts[1] = lineno(제거). parts[2] = enclosing-qualname.
        # parts[3:] = callee_src(``:`` 없음 — join 은 안전 복원).
        enclosing = parts[2]
        callee_src = ":".join(parts[3:])
        return f"{module}:{enclosing}:{callee_src}"
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
    가 그 검증 site(``ante.web.routes.accounts:update_account:
    AccountUpdateRequest.model_validate`` — ``update_account`` handler,
    ``PUT /api/accounts/{id}``)에서 ``model_validate`` 이전 STRUCTURAL
    409 로 거부됨을 behavioral 증명. model_validate 스파이가 invoke
    되면 (가드 회귀) 단언 실패. 이 증명은 그 **특정 site**(특정
    enclosing handler ``update_account``) 한정이며, 동일 모델/필드를
    검증하는 다른 handler/site 가 생기면 그 site 는 별도 키(enclosing
    qualname 이 다름)라 본 증명으로 통과되지 않는다(INV-1 정밀화 —
    같은 모듈·같은 모델 다중-handler 과병합 fail-open 차단).
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
# ``module:enclosing-qualname:callee_src`` 리터럴(lineno 무관·enclosing
# handler qualname 보존 — Codex attempt-5 [P2] 과병합 락; 같은 모듈·
# 같은 모델이라도 distinct handler 면 distinct site-id).
_REGISTERED_DICT_PROOFS: list[_DictPreRejectProof] = [
    _DictPreRejectProof(
        owner_qualname="AccountUpdateRequest",
        field_name="credentials",
        validating_site=(
            "ante.web.routes.accounts:update_account:"
            "AccountUpdateRequest.model_validate"
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
    all-must-resolve). raw-body chokepoint 우회 **per-handler** 검사:
    각 ValidationError handler 가 예외-파생 detail 을 chokepoint
    미경유로 방출하면 그 handler 가 FAIL 로 집계(#1650 SSOT;
    전역 count 아님 — attempt-7 fail-open 봉인).
    """
    s1 = _resolve_s1()
    assert not s1.unresolvable, (
        "S1b origin-complete FAIL-CLOSED — 정적 resolve 불가 검증 "
        f"origin/entrypoint(단일 sink): {s1.unresolvable}"
    )
    assert s1.models, "S1 검증 entrypoint 0건 — AST 스캔 회귀 의심"

    choke, nonconforming = _scan_validationerror_handler_chokepoint()
    assert not nonconforming, (
        "ValidationError handler 집합 중 chokepoint-미경유 예외-파생 "
        "detail 방출 handler 발견 — #1650 SSOT 는 *각* handler 가 "
        "``sanitize_validation_errors(<exc>)`` 단일 chokepoint 만 "
        "거쳐야 한다(``detail=str(e)``/``e.json()``/``e.errors(...)``/"
        "``repr(e)``/f-string 보간 등 임의 예외-파생 detail 금지; "
        "전역 합 아니라 handler 별 강제 — attempt-7 fail-open 봉인): "
        f"{nonconforming}"
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


def test_attempt5_same_module_same_model_multi_handler_no_overmerge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-5 회귀 canary(Codex [P2] — site-id 과병합 영구 락):
    같은 route 모듈·같은 모델을 검증하는 handler 가 2개이고 그중
    **하나만** pre-reject 가드가 있을 때, 가드 없는 handler 의 dict
    노드가 가드 있는 handler 의 proof 로 재사용되지 않고
    UNPROVEN→FAIL 함을 행위로 단언한다.

    이전 ``_stable_s1_site`` 는 site-id 를 ``module:callee_src`` 로
    lineno-agnostic 정규화하면서 enclosing handler 를 버려, 같은
    모듈·같은 모델의 2개 handler(``handler_a`` 가드 有 /
    ``handler_b`` 가드 無) 검증 호출이 단일 site-id 로 **과병합**
    됐다. 그러면 ``handler_a`` 의 pre-reject proof 키가 가드 없는
    ``handler_b`` 의 dict 노드에도 매칭돼 discovery lock 이
    fail-open 으로 PASS 했다(attempt-5 FAIL class).

    본 canary 는 합성 routes 모듈을 두고 (a) 두 handler 가
    **distinct** stable site-id(enclosing qualname 이 다름)를
    가짐을 단언하고, (b) ``handler_a`` site 만 proof 등록한 상태로
    ``compute_verdict`` 가 ``handler_b`` 의 dict 노드를 UNPROVEN
    으로 FAIL 시킴을 단언한다. **old 코드(module:callee_src
    과병합)에서는 (a)/(b) 모두 red** — 영구 회귀 락.
    """
    # 패키지 디렉토리명 = ``_ROUTES_PKG`` 와 동일해야
    # ``import_module`` 으로 정적 resolve(_resolve_s1) 가능.
    syn_routes = tmp_path / "syn_routes_1651_a5"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # 같은 모듈·같은 모델(비-dict[str,Any] dict 필드 보유 → dict
    # 노드 발생)을 검증하는 handler 2개. handler_a=가드 有(개념),
    # handler_b=가드 無. lock 관점에서 둘은 distinct site 여야 한다.
    (syn_routes / "multi.py").write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class MultiReq(BaseModel):\n"
        "    creds: dict[str, str] = {}\n"
        "\n"
        "def handler_a(payload):\n"
        "    return MultiReq.model_validate(payload)\n"
        "\n"
        "def handler_b(payload):\n"
        "    return MultiReq.model_validate(payload)\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a5")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651_a5" or m.startswith("syn_routes_1651_a5."):
                del sys.modules[m]
        s1 = _resolve_s1()
    finally:
        for m in list(sys.modules):
            if m == "syn_routes_1651_a5" or m.startswith("syn_routes_1651_a5."):
                del sys.modules[m]
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    # (a) 두 handler 가 distinct stable site-id 를 가져야 한다.
    stable_sites = {_stable_s1_site(sid) for sid, _m in s1.models}
    site_a = "syn_routes_1651_a5.multi:handler_a:MultiReq.model_validate"
    site_b = "syn_routes_1651_a5.multi:handler_b:MultiReq.model_validate"
    assert site_a in stable_sites and site_b in stable_sites, (
        "attempt-5 과병합 회귀 — 같은 모듈·같은 모델의 2개 handler "
        "가 enclosing-qualname 보존 distinct site-id 로 분리되지 "
        f"않음(old module:callee_src 과병합 재발): {sorted(stable_sites)}"
    )
    assert site_a != site_b, "site_a/site_b 가 동일 — 과병합(canary 무효)"

    # DISCOVERED dict 노드: 두 site 각각에 (MultiReq, creds, site) 가
    # 별도로 발견돼야 한다(과병합이면 1개로 합쳐짐).
    surf = _SurfaceModels(
        site_models=[(_stable_s1_site(sid), m) for sid, m in s1.models],
        site_roots=[],
        unresolvable=list(s1.unresolvable),
    )
    disc = _discover_all(surf)
    node_a = ("MultiReq", "creds", site_a)
    node_b = ("MultiReq", "creds", site_b)
    assert node_a in disc.dict_nodes and node_b in disc.dict_nodes, (
        "attempt-5 과병합 회귀 — handler 별 distinct dict 노드 "
        f"(owner,field,site) 미생성: {sorted(disc.dict_nodes)}"
    )

    # (b) handler_a site 만 proof 등록 → handler_b dict 노드는
    # UNPROVEN 으로 FAIL 해야 한다(과병합이면 site_a proof 가
    # 가드 없는 site_b 노드까지 덮어 fail-open PASS).
    registered_a_only = frozenset({node_a})
    verdict = compute_verdict(
        disc,
        surf.unresolvable,
        registered_dict_keys=registered_a_only,
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "attempt-5 과병합 fail-open 재발 — handler_a site proof 만 "
        "등록했는데 lock PASS(가드 없는 handler_b dict 노드가 "
        "handler_a proof 로 재사용됨): "
        f"unproven_dict={verdict.unproven_dict}"
    )
    assert node_b in set(verdict.unproven_dict), (
        "attempt-5 — 가드 없는 handler_b 의 dict 노드가 UNPROVEN "
        f"으로 떨어지지 않음: unproven={verdict.unproven_dict}"
    )
    assert node_a not in set(verdict.unproven_dict), (
        "handler_a dict 노드는 proof 등록됐으므로 PROVEN 이어야 함 "
        f"(per-site 1:1 결합 회귀): unproven={verdict.unproven_dict}"
    )


def test_attempt6_same_helper_same_model_multi_endpoint_caller_site_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-6 회귀 canary ① (Codex [P2] — helper-trace caller-site
    과병합 영구 락; attempt-5 enclosing-qualname 원칙을 helper-trace
    경로에 확장):

    **같은 제네릭 helper**(``model.model_validate``)를 **같은 모델**
    (비-``dict[str,Any]`` dict 필드 보유)로 검증하는 endpoint 가 2개
    이고 그중 **하나만** pre-reject 가드가 있을 때, 가드 없는
    endpoint 의 dict 노드가 가드 있는 endpoint 의 proof 로
    재사용되지 않고 UNPROVEN→FAIL 함을 단언한다.

    이전 ``_trace_generic_helper_model_args`` 는 helper 본문 내부
    단일 ``model.model_validate`` call site 의 sid·model 만 보존하고
    **model-only dedupe** 했다(같은 모델이면 1개로 합침). 그러면
    같은 helper 를 ``endpoint_a``(가드 有 개념)/``endpoint_b``(가드
    無)가 **같은 모델**로 호출해도 단일 site-id 로 과병합돼,
    ``endpoint_a`` 의 pre-reject proof 키가 가드 없는 ``endpoint_b``
    dict 노드에도 매칭돼 discovery lock 이 fail-open PASS 했다
    (attempt-5 와 동형의 helper-trace 변종 fail-open class).

    본 canary 는 (a) 두 caller endpoint 가 **distinct** stable
    site-id(caller enclosing-qualname 이 다름)를 가짐을 단언하고,
    (b) ``endpoint_a`` site dict 노드만 proof 등록한 상태로
    ``compute_verdict`` 가 ``endpoint_b`` dict 노드를 UNPROVEN 으로
    FAIL 시킴을 단언한다. **old 코드(model-only dedupe — helper
    내부 site 단일화)에서는 (a)/(b) 모두 red** — 영구 회귀 락.
    """
    syn_routes = tmp_path / "syn_routes_1651_a6"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # 제네릭 helper 가 같은 모델(SameReq — 비-dict[str,Any] dict 필드
    # 보유 → dict 노드 발생)을 2개 endpoint(endpoint_a/endpoint_b)
    # 에서 검증. lock 관점 둘은 distinct caller-site 여야 한다.
    (syn_routes / "shared.py").write_text(
        "from pydantic import BaseModel\n"
        "\n"
        "class SameReq(BaseModel):\n"
        "    creds: dict[str, str] = {}\n"
        "\n"
        "def _parse(payload, model):\n"
        "    return model.model_validate(payload)\n"
        "\n"
        "def endpoint_a(payload):\n"
        "    return _parse(payload, SameReq)\n"
        "\n"
        "def endpoint_b(payload):\n"
        "    return _parse(payload, SameReq)\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a6")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651_a6" or m.startswith("syn_routes_1651_a6."):
                del sys.modules[m]
        s1 = _resolve_s1()
    finally:
        for m in list(sys.modules):
            if m == "syn_routes_1651_a6" or m.startswith("syn_routes_1651_a6."):
                del sys.modules[m]
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    # (a) 두 caller endpoint 가 distinct stable site-id 를 가져야
    # 한다(helper 내부가 아니라 caller endpoint qualname 이 enclosing
    # 세그먼트). 같은 helper·같은 모델이라도 caller 가 다르면 분리.
    stable_sites = {_stable_s1_site(sid) for sid, _m in s1.models}
    site_a = "syn_routes_1651_a6.shared:endpoint_a:model.model_validate#SameReq"
    site_b = "syn_routes_1651_a6.shared:endpoint_b:model.model_validate#SameReq"
    assert site_a in stable_sites and site_b in stable_sites, (
        "attempt-6 helper-trace 과병합 회귀 — 같은 helper·같은 "
        "모델을 검증하는 2개 caller endpoint 가 caller "
        "enclosing-qualname 보존 distinct site-id 로 분리되지 "
        f"않음(old model-only dedupe 재발): {sorted(stable_sites)}"
    )
    assert site_a != site_b, "site_a/site_b 동일 — 과병합(canary 무효)"
    assert not s1.unresolvable, (
        "synthetic helper 가 all-must-resolve 인데 unresolvable "
        f"(canary 무효 — INV-3 회귀): {s1.unresolvable}"
    )

    # DISCOVERED dict 노드: 두 caller site 각각에 (SameReq, creds,
    # site) 가 별도로 발견돼야 한다(과병합이면 1개로 합쳐짐).
    surf = _SurfaceModels(
        site_models=[(_stable_s1_site(sid), m) for sid, m in s1.models],
        site_roots=[],
        unresolvable=list(s1.unresolvable),
    )
    disc = _discover_all(surf)
    node_a = ("SameReq", "creds", site_a)
    node_b = ("SameReq", "creds", site_b)
    assert node_a in disc.dict_nodes and node_b in disc.dict_nodes, (
        "attempt-6 helper-trace 과병합 회귀 — caller endpoint 별 "
        f"distinct dict 노드 (owner,field,site) 미생성: "
        f"{sorted(disc.dict_nodes)}"
    )

    # (b) endpoint_a site dict 노드만 proof 등록 → endpoint_b dict
    # 노드는 UNPROVEN 으로 FAIL 해야 한다(과병합이면 site_a proof 가
    # 가드 없는 site_b 노드까지 덮어 fail-open PASS).
    registered_a_only = frozenset({node_a})
    verdict = compute_verdict(
        disc,
        surf.unresolvable,
        registered_dict_keys=registered_a_only,
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "attempt-6 helper-trace 과병합 fail-open 재발 — endpoint_a "
        "site proof 만 등록했는데 lock PASS(가드 없는 endpoint_b "
        "dict 노드가 endpoint_a proof 로 재사용됨): "
        f"unproven_dict={verdict.unproven_dict}"
    )
    assert node_b in set(verdict.unproven_dict), (
        "attempt-6 — 가드 없는 endpoint_b 의 dict 노드가 UNPROVEN "
        f"으로 떨어지지 않음: unproven={verdict.unproven_dict}"
    )
    assert node_a not in set(verdict.unproven_dict), (
        "endpoint_a dict 노드는 proof 등록됐으므로 PROVEN 이어야 함 "
        f"(per-caller-site 1:1 결합 회귀): unproven={verdict.unproven_dict}"
    )


def test_attempt6_variant_validationerror_handler_ast_semantic_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-6 회귀 canary ② (Codex [P2] — ValidationError-handler
    AST 의미 게이트 영구 락; substring count 폐기):

    chokepoint(``sanitize_validation_errors``)를 우회해 raw-body
    handler 가 **직접 ``<exc>.errors(...)``** 로 422 detail 을
    만드는데, substring 매칭이 못 잡는 **variant** 형태(다른 변수명
    ``exc`` · 중간 변수 ``errs = exc.errors(...)`` · kwarg 순서
    뒤바꿈 · 줄바꿈 차이)일 때 per-handler AST 의미 검사가 그
    handler 를 **nonconforming** 으로 잡아 FAIL 함을 단언한다.

    **old 코드(정확 substring
    ``detail=e.errors(include_context=False, include_input=False)``
    카운트)에서는 이 variant 가 매칭 실패해 ``direct == 0`` 으로
    통과(fail-open)** — 영구 회귀 락. 동시에 정상 chokepoint
    handler 는 nonconforming 에 안 들고 ``choke > 0`` 으로 통과함을
    확인한다(강화가 정상 패턴을 false-positive 로 깨지 않음).
    """
    syn_routes = tmp_path / "syn_routes_1651_a6e"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # variant bypass handler: 다른 변수명(exc)·중간 변수(errs)·
    # kwarg 순서 뒤바꿈(include_input 먼저)·줄바꿈 — substring
    # ``detail=e.errors(include_context=False, include_input=False)``
    # 와 한 글자도 안 맞지만 의미상 직접 e.errors() detail 우회.
    (syn_routes / "bypass.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class Req(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def handler(payload):\n"
        "    try:\n"
        "        return Req.model_validate(payload)\n"
        "    except ValidationError as exc:\n"
        "        errs = exc.errors(\n"
        "            include_input=False,\n"
        "            include_context=False,\n"
        "        )\n"
        "        raise HTTPException(status_code=422, detail=errs) from None\n"
    )
    # 정상 chokepoint handler — 강화가 이걸 false-positive 로 깨지
    # 않아야 한다(direct 0 · choke 1).
    (syn_routes / "ok.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "from ante.web.errors import sanitize_validation_errors\n"
        "\n"
        "class OkReq(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def ok_handler(payload):\n"
        "    try:\n"
        "        return OkReq.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail=sanitize_validation_errors(e),\n"
        "        ) from None\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a6e")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        choke, nonconforming = _scan_validationerror_handler_chokepoint()
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    assert any("bypass" in s for s in nonconforming), (
        "attempt-6 ValidationError-handler AST 게이트 회귀 — variant "
        "직접 ``exc.errors(...)`` (다른 변수명·중간 변수·kwarg 순서·"
        "줄바꿈) handler 가 nonconforming 으로 안 잡힘(old substring "
        f"count fail-open 재발): nonconforming={nonconforming}"
    )
    assert not any("ok" in s for s in nonconforming), (
        "정상 chokepoint handler 가 nonconforming 으로 잘못 잡힘 — "
        f"AST 의미 검사가 정상 패턴을 false-positive: {nonconforming}"
    )
    assert choke >= 1, (
        "정상 chokepoint handler 가 choke 로 안 잡힘 — AST 의미 "
        f"검사가 정상 패턴을 false-negative: choke={choke}"
    )


def test_attempt7_per_handler_chokepoint_global_count_fail_open_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-7 회귀 canary ③ (Codex [P2] — per-handler chokepoint
    강제; **전역 count fail-open** 영구 락):

    raw-body handler 가 ``except ValidationError as e:`` 후
    ``detail=str(e)`` (또는 ``e.json()``)로 우회한다 — ``.errors()``
    를 **안** 부르므로 old 전역-count 로직에선 그 handler 의
    ``direct == 0``, 그리고 ``sanitize_validation_errors`` 도 안
    거치지만 **같은 스캔 대상의 다른 정상 chokepoint handler** 때문에
    전역 ``choke > 0`` 이 유지돼 lock 이 PASS(fail-open) 했다.

    신 per-handler 로직: 그 우회 handler 가 chokepoint 미경유로
    예외-파생 detail (``str(e)``/``e.json()``)을 방출하므로 그
    handler 단위로 **nonconforming** 에 집계돼 FAIL. 정상 chokepoint
    handler 는 nonconforming 에 안 들고 ``choke > 0`` 에 기여한다 —
    즉 **old 전역-count 로직이라면 green(=red 누락) 일 시나리오가 신
    로직에선 정상 FAIL**. 영구 락: 이 canary 가 red 면 per-handler
    강제가 전역 합산으로 회귀한 것.

    ``str(e)`` 우회와 ``e.json()`` 우회를 별 모듈로 두 형태 모두
    포착함을 단언(``.errors()`` AST 만 보던 attempt-6 보강 — 임의
    예외-파생 detail 방출 behavioral 매트릭스).
    """
    syn_routes = tmp_path / "syn_routes_1651_a7p"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # 우회 ①: ``detail=str(e)`` — 예외 객체를 문자열화해 그대로
    # 방출(``.errors()`` 미호출 → old 전역 direct==0).
    (syn_routes / "bypass_str.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqStr(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def handler_str(payload):\n"
        "    try:\n"
        "        return ReqStr.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(status_code=422, detail=str(e)) "
        "from None\n"
    )
    # 우회 ②: 중간 변수 + ``e.json()`` — f-string 보간으로 detail
    # 합성(``.errors()`` 미호출 → old 전역 direct==0).
    (syn_routes / "bypass_json.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqJson(BaseModel):\n"
        "    y: int\n"
        "\n"
        "def handler_json(payload):\n"
        "    try:\n"
        "        return ReqJson.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        msg = e.json()\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        '            detail=f"invalid: {msg}",\n'
        "        ) from None\n"
    )
    # 같은 스캔 대상에 정상 chokepoint handler 동거 — old 전역
    # count 라면 이 handler 때문에 ``choke > 0`` 이 유지돼 위
    # 우회들이 fail-open 으로 통과했다.
    (syn_routes / "ok.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "from ante.web.errors import sanitize_validation_errors\n"
        "\n"
        "class OkReq(BaseModel):\n"
        "    z: int\n"
        "\n"
        "def ok_handler(payload):\n"
        "    try:\n"
        "        return OkReq.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail=sanitize_validation_errors(e),\n"
        "        ) from None\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a7p")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        choke, nonconforming = _scan_validationerror_handler_chokepoint()
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    # ``str(e)`` 우회 handler 가 per-handler nonconforming 에 집계.
    assert any("bypass_str" in s for s in nonconforming), (
        "attempt-7 per-handler 회귀 — ``detail=str(e)`` 우회 handler "
        "가 nonconforming 으로 안 잡힘(전역 count fail-open 재발: "
        "다른 정상 handler 의 choke>0 이 이 handler 의 미경유를 "
        f"가림): nonconforming={nonconforming}"
    )
    # ``e.json()`` f-string 보간 우회 handler 도 집계.
    assert any("bypass_json" in s for s in nonconforming), (
        "attempt-7 per-handler 회귀 — ``e.json()`` f-string 보간 "
        "우회 handler 가 nonconforming 으로 안 잡힘(임의 예외-파생 "
        f"detail behavioral 매트릭스 회귀): nonconforming={nonconforming}"
    )
    # 정상 chokepoint handler 는 nonconforming 에 안 든다(강화가
    # 정상 패턴을 false-positive 로 깨지 않음 — old 전역 count
    # 라면 이 handler 가 우회들을 fail-open 으로 가렸을 바로 그
    # handler).
    assert not any("ok" in s for s in nonconforming), (
        "정상 chokepoint handler 가 nonconforming 으로 잘못 잡힘 — "
        f"per-handler 의미 검사가 정상 패턴을 false-positive: "
        f"{nonconforming}"
    )
    assert choke >= 1, (
        "정상 chokepoint handler 가 choke 로 안 잡힘 — per-handler "
        f"검사가 정상 패턴을 false-negative: choke={choke}"
    )


def test_attempt8_annassign_exc_derived_detail_bypass_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-8 회귀 canary ① (Codex [P2] — AnnAssign taint 전파
    영구 락):

    raw-body handler 가 ``except ValidationError as exc:`` 후
    **annotated assignment** ``errs: list = exc.errors(...)`` 로
    예외-파생값을 중간변수에 담아 ``HTTPException(detail=errs)`` 로
    방출한다. ``ast.Assign`` 만 전파하던 old 구현은 ``ast.AnnAssign``
    을 보지 못해 ``errs`` 가 tainted-name 으로 전파되지 않아 그
    handler 가 nonconforming 으로 안 잡혔다(fail-open). 신
    ``_assignment_bindings`` 정규화는 assignment 형태 무관하게 동일
    taint 처리하므로 그 handler 가 per-handler nonconforming 에
    집계돼 FAIL. ``AugAssign`` 누적·walrus·tuple unpack 우회 변종도
    같은 정규화로 함께 포착됨을 단언(behavioral — 형태 무관).
    정상 chokepoint handler 는 false-positive 로 안 깨진다.
    """
    syn_routes = tmp_path / "syn_routes_1651_a8a"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # 우회 ①: annotated assignment ``errs: list = exc.errors(...)``.
    (syn_routes / "bypass_ann.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqAnn(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def handler_ann(payload):\n"
        "    try:\n"
        "        return ReqAnn.model_validate(payload)\n"
        "    except ValidationError as exc:\n"
        "        errs: list = exc.errors(\n"
        "            include_input=False,\n"
        "            include_context=False,\n"
        "        )\n"
        "        raise HTTPException(status_code=422, detail=errs) "
        "from None\n"
    )
    # 우회 ②: AugAssign 누적 ``buf += exc.json()``.
    (syn_routes / "bypass_aug.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqAug(BaseModel):\n"
        "    y: int\n"
        "\n"
        "def handler_aug(payload):\n"
        "    try:\n"
        "        return ReqAug.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        '        buf = "invalid: "\n'
        "        buf += e.json()\n"
        "        raise HTTPException(status_code=422, detail=buf) "
        "from None\n"
    )
    # 우회 ③: walrus ``(w := exc.errors())`` 직접 sink 인자.
    (syn_routes / "bypass_walrus.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqW(BaseModel):\n"
        "    z: int\n"
        "\n"
        "def handler_walrus(payload):\n"
        "    try:\n"
        "        return ReqW.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail=(w := e.errors()),\n"
        "        ) from None\n"
    )
    # 우회 ④: tuple unpack ``a, b = exc.errors(), None`` 후 detail=a.
    (syn_routes / "bypass_tuple.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "\n"
        "class ReqT(BaseModel):\n"
        "    t: int\n"
        "\n"
        "def handler_tuple(payload):\n"
        "    try:\n"
        "        return ReqT.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        a, b = e.errors(), None\n"
        "        raise HTTPException(status_code=422, detail=a) "
        "from None\n"
    )
    # 정상 chokepoint handler — 강화가 false-positive 로 깨면 안 됨.
    (syn_routes / "ok.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "from ante.web.errors import sanitize_validation_errors\n"
        "\n"
        "class OkReq(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def ok_handler(payload):\n"
        "    try:\n"
        "        return OkReq.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail=sanitize_validation_errors(e),\n"
        "        ) from None\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a8a")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        choke, nonconforming = _scan_validationerror_handler_chokepoint()
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    for variant in ("bypass_ann", "bypass_aug", "bypass_walrus", "bypass_tuple"):
        assert any(variant in s for s in nonconforming), (
            f"attempt-8 AnnAssign taint 회귀 — ``{variant}`` 우회 "
            "handler 가 nonconforming 으로 안 잡힘(assignment 형태 "
            "무관 taint 정규화 회귀 = fail-open: AnnAssign/AugAssign/"
            f"walrus/tuple unpack 미전파): nonconforming={nonconforming}"
        )
    assert not any("ok" in s for s in nonconforming), (
        "정상 chokepoint handler 가 nonconforming 으로 잘못 잡힘 — "
        f"taint 정규화가 정상 패턴을 false-positive: {nonconforming}"
    )
    assert choke >= 1, (
        "정상 chokepoint handler 가 choke 로 안 잡힘 — taint "
        f"정규화가 정상 패턴을 false-negative: choke={choke}"
    )


def test_attempt8_basemodel_constructor_path_validation_s1_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-8 회귀 canary ② (Codex [P2] — BaseModel 생성자-경로
    검증 S1 탐지 영구 락):

    새 raw-body handler 가 Pydantic 일반 생성자
    ``Req(**payload)`` / ``Req(payload)`` 로 검증한다(``model_validate``
    가 아님). old S1 scanner 는 ``model_validate`` attribute call
    패턴만 보고 ``ast.Call.func`` 가 ``Name`` 인 생성자 호출을 전부
    skip → unsafe dict 필드를 가진 요청 모델을 그렇게 검증해도
    discovery lock 이 green(fail-open) 이었다.

    신 S1a 탐지(생성자-경로 포함): (a) callee 가 정적 BaseModel
    서브클래스로 resolve 되면 ``model_validate`` 와 동형 S1 source
    로 walk → unsafe ``dict[str, str]`` 필드가 DISCOVERED dict
    노드가 되어 미등록이면 UNPROVEN→FAIL. (b) 정적 resolve 불가한
    생성자-스타일 검증(동적 클래스)은 INV-3 single-sink
    ``unresolvable`` 충전(default-deny). raw-body 검증 문맥
    한정(caller-controlled ``payload`` 가 생성자 인자) — 무관한
    일반 객체 생성은 S1 site 아님(false-positive 0).

    **old 코드(생성자-경로 미탐지)에서는 (a)/(b) 모두 red(누락)**
    — 영구 회귀 락.
    """
    syn_routes = tmp_path / "syn_routes_1651_a8b"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # (a) 정적 BaseModel 생성자-경로 검증(``Req(**payload)``) — unsafe
    #     ``dict[str, str]`` 필드 보유 → DISCOVERED dict 노드.
    #     인접 무관 객체 생성(``_Helper(a=1)``)은 S1 site 아님.
    (syn_routes / "ctor_static.py").write_text(
        "import json\n"
        "from pydantic import BaseModel\n"
        "from fastapi import Request\n"
        "\n"
        "class _Helper:\n"
        "    def __init__(self, a=0):\n"
        "        self.a = a\n"
        "\n"
        "class CtorReq(BaseModel):\n"
        "    creds: dict[str, str] = {}\n"
        "\n"
        "async def ctor_handler(request: Request):\n"
        "    raw = await request.body()\n"
        "    payload = json.loads(raw)\n"
        "    _local = _Helper(a=1)\n"
        "    return CtorReq(**payload)\n"
    )
    # (b) 동적 클래스 생성자-경로 검증 — 정적 resolve 불가 →
    #     INV-3 single-sink unresolvable(default-deny).
    (syn_routes / "ctor_dynamic.py").write_text(
        "import json\n"
        "from fastapi import Request\n"
        "\n"
        "def _pick():\n"
        "    import pydantic\n"
        "    return pydantic.BaseModel\n"
        "\n"
        "async def dyn_handler(request: Request):\n"
        "    payload = json.loads(await request.body())\n"
        "    Model = _pick()\n"
        "    return Model(**payload)\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a8b")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651_a8b" or m.startswith("syn_routes_1651_a8b."):
                del sys.modules[m]
        sites = _scan_s1_entrypoints()
        s1 = _resolve_s1()
    finally:
        for m in list(sys.modules):
            if m == "syn_routes_1651_a8b" or m.startswith("syn_routes_1651_a8b."):
                del sys.modules[m]
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    # 실제 scanner 가 두 생성자-경로 검증 site 를 발견.
    ctor_sites = [s for s in sites if s.method == _CONSTRUCTOR_VALIDATION_METHOD]
    static_site = [
        s
        for s in ctor_sites
        if s.module == "syn_routes_1651_a8b.ctor_static" and s.receiver == "CtorReq"
    ]
    dyn_site = [
        s
        for s in ctor_sites
        if s.module == "syn_routes_1651_a8b.ctor_dynamic" and s.receiver == "Model"
    ]
    assert static_site, (
        "attempt-8 생성자-경로 회귀 — 정적 BaseModel ``CtorReq(**payload)`` "
        f"검증 site 가 S1 scanner 에서 미발견(fail-open): {sites}"
    )
    assert dyn_site, (
        "attempt-8 생성자-경로 회귀 — 동적 ``Model(**payload)`` 검증 "
        f"site 가 S1 scanner 에서 미발견(fail-open): {sites}"
    )
    # 무관한 일반 객체 생성(``_Helper(a=1)``)은 S1 site 아님
    # (false-positive 0 — raw-body 인자 무관).
    assert not any(s.receiver == "_Helper" for s in ctor_sites), (
        "무관한 일반 객체 생성(``_Helper(a=1)``)이 S1 생성자-경로 "
        f"site 로 잘못 잡힘(false-positive): {ctor_sites}"
    )

    # (a) 정적 BaseModel → model_validate 와 동형 S1 source(models).
    static_models = [
        (sid, m)
        for sid, m in s1.models
        if sid.startswith("syn_routes_1651_a8b.ctor_static:")
    ]
    assert static_models and all(
        m.__name__ == "CtorReq" for _sid, m in static_models
    ), (
        "attempt-8 생성자-경로 회귀 — 정적 ``CtorReq(**payload)`` 가 "
        f"S1 source(models)로 충전되지 않음(fail-open): {s1.models}"
    )
    # 그 모델이 DISCOVERED dict 노드를 만들고 미등록이면 FAIL.
    surf = _SurfaceModels(
        site_models=[(_stable_s1_site(sid), m) for sid, m in static_models],
        site_roots=[],
        unresolvable=[],
    )
    disc = _discover_all(surf)
    assert any(
        owner == "CtorReq" and field == "creds" for owner, field, _s in disc.dict_nodes
    ), (
        "attempt-8 생성자-경로 회귀 — 정적 BaseModel 의 unsafe "
        f"``creds: dict[str,str]`` 가 DISCOVERED dict 노드로 안 잡힘: "
        f"{sorted(disc.dict_nodes)}"
    )
    verdict = compute_verdict(
        disc,
        surf.unresolvable,
        registered_dict_keys=frozenset(),
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "attempt-8 생성자-경로 fail-open 재발 — 생성자-경로 검증 "
        "모델의 unsafe dict 필드가 미등록인데 discovery lock PASS: "
        f"unproven_dict={verdict.unproven_dict}"
    )

    # (b) 동적 클래스 생성자-경로 → INV-3 single-sink unresolvable.
    assert any(
        "syn_routes_1651_a8b.ctor_dynamic" in u and "생성자-경로" in u
        for u in s1.unresolvable
    ), (
        "attempt-8 생성자-경로 회귀 — 동적 클래스 ``Model(**payload)`` "
        "생성자-경로 검증이 INV-3 single-sink unresolvable 로 충전되지 "
        f"않음(default-deny 회귀 = fail-open): {s1.unresolvable}"
    )


def test_attempt9_body_kwarg_constructor_path_validation_s1_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-9 회귀 canary ① (Codex [P2] — body-파생 keyword 생성자
    S1 site 영구 락; attempt-8 생성자-경로 탐지의 완결):

    raw-body handler 가 parsed body 의 **필드값**을 BaseModel 생성자
    **keyword 인자**로 넘겨 검증한다
    (``Req(credentials=payload["credentials"], name=payload["name"])``).
    attempt-8 탐지는 ``Req(**payload)``(unpack)·``Req(payload)``
    (single positional raw object)만 S1 site 로 잡고, parsed body 의
    subscript/attr 파생값이 생성자 keyword 인자로 흘러가는 경로는
    미탐지였다 — 그런데 Pydantic 은 그 인자로 받은 ``credentials``
    dict 필드의 caller-controlled key/value 를 검증해 422 ``loc`` 에
    반사할 수 있어 lock 우회 벡터다.

    신 S1a 탐지(``"kwarg"`` 형태): parsed-body alias 의 subscript/attr
    파생 체인이 BaseModel-positive-resolve 생성자의 **임의 인자**
    (kwarg 포함)로 전달되면 그 모델을 ``model_validate`` 와 동형 S1
    source 로 walk → unsafe ``dict[str,str]`` 필드가 DISCOVERED dict
    노드가 되어 미등록이면 UNPROVEN→FAIL. 무관한 일반 객체 생성
    (``_Helper(a=payload["a"])`` — callee 비-BaseModel)은 BaseModel-
    positive-resolve 게이트로 S1 site 아님(false-positive 0).

    **old 코드(body-파생 kwarg 생성자 미탐지)에서는 red(누락)
    = fail-open** — 영구 회귀 락.
    """
    syn_routes = tmp_path / "syn_routes_1651_a9k"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # body-파생 필드값을 BaseModel 생성자 keyword 인자로 — unsafe
    # ``dict[str,str]`` 필드 보유 → DISCOVERED dict 노드. 인접 무관
    # 객체 생성(``_Helper(a=payload["a"])``)은 callee 비-BaseModel
    # 이므로 S1 site 아님(false-positive 0).
    (syn_routes / "kw_static.py").write_text(
        "import json\n"
        "from pydantic import BaseModel\n"
        "from fastapi import Request\n"
        "\n"
        "class _Helper:\n"
        "    def __init__(self, a=0):\n"
        "        self.a = a\n"
        "\n"
        "class KwReq(BaseModel):\n"
        "    credentials: dict[str, str] = {}\n"
        "    name: str = ''\n"
        "\n"
        "async def kw_handler(request: Request):\n"
        "    raw = await request.body()\n"
        "    payload = json.loads(raw)\n"
        "    _local = _Helper(a=payload['a'])\n"
        "    return KwReq(\n"
        "        credentials=payload['credentials'],\n"
        "        name=payload['name'],\n"
        "    )\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a9k")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651_a9k" or m.startswith("syn_routes_1651_a9k."):
                del sys.modules[m]
        sites = _scan_s1_entrypoints()
        s1 = _resolve_s1()
    finally:
        for m in list(sys.modules):
            if m == "syn_routes_1651_a9k" or m.startswith("syn_routes_1651_a9k."):
                del sys.modules[m]
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    ctor_sites = [s for s in sites if s.method == _CONSTRUCTOR_VALIDATION_METHOD]
    kw_site = [
        s
        for s in ctor_sites
        if s.module == "syn_routes_1651_a9k.kw_static" and s.receiver == "KwReq"
    ]
    assert kw_site, (
        "attempt-9 body-kwarg 회귀 — body-파생 필드값을 keyword "
        "인자로 넘기는 ``KwReq(credentials=payload['credentials'])`` "
        f"생성자-경로 검증 site 가 S1 scanner 에서 미발견(fail-open): "
        f"{sites}"
    )
    # 무관한 일반 객체 생성(``_Helper(a=payload['a'])``)은 callee
    # 비-BaseModel 이므로 S1 site 아님(false-positive 0).
    assert not any(s.receiver == "_Helper" for s in ctor_sites), (
        "무관한 일반 객체 생성(``_Helper(a=payload['a'])``)이 S1 "
        f"body-kwarg site 로 잘못 잡힘(false-positive): {ctor_sites}"
    )
    # 정적 BaseModel → model_validate 와 동형 S1 source(models).
    kw_models = [
        (sid, m)
        for sid, m in s1.models
        if sid.startswith("syn_routes_1651_a9k.kw_static:")
    ]
    assert kw_models and all(m.__name__ == "KwReq" for _sid, m in kw_models), (
        "attempt-9 body-kwarg 회귀 — ``KwReq(credentials=payload['x'])`` "
        f"가 S1 source(models)로 충전되지 않음(fail-open): {s1.models}"
    )
    # 그 모델의 unsafe dict 필드가 DISCOVERED → 미등록이면 FAIL.
    surf = _SurfaceModels(
        site_models=[(_stable_s1_site(sid), m) for sid, m in kw_models],
        site_roots=[],
        unresolvable=[],
    )
    disc = _discover_all(surf)
    assert any(
        owner == "KwReq" and field == "credentials"
        for owner, field, _s in disc.dict_nodes
    ), (
        "attempt-9 body-kwarg 회귀 — body-kwarg 검증 모델의 unsafe "
        f"``credentials: dict[str,str]`` 가 DISCOVERED dict 노드로 안 "
        f"잡힘: {sorted(disc.dict_nodes)}"
    )
    verdict = compute_verdict(
        disc,
        surf.unresolvable,
        registered_dict_keys=frozenset(),
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "attempt-9 body-kwarg fail-open 재발 — body-kwarg 생성자-경로 "
        "검증 모델의 unsafe dict 필드가 미등록인데 discovery lock "
        f"PASS: unproven_dict={verdict.unproven_dict}"
    )


def test_attempt9_mixed_expr_chokepoint_sibling_raw_ref_scanned_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """attempt-9 회귀 canary ② (Codex [P2] — mixed-expr chokepoint+raw
    sibling 전체 스캔 영구 락):

    같은 response detail 표현에 chokepoint 와 raw 예외 참조가 섞이면
    (``detail={"safe": sanitize_validation_errors(e), "raw": str(e)}``),
    이전 ``_expr_taints_from_exc`` 는 ``ast.walk`` 중 chokepoint
    호출의 child alias ``e`` 를 먼저 만나 거기서 조기 ``return``
    (clean)하고 뒤의 sibling raw ``str(e)`` 를 못 봐 그 handler 가
    ``nonconforming`` 에서 누락(fail-open)됐다.

    신 로직: 표현 전체를 끝까지 스캔해 chokepoint 인자 위치의 alias
    ref 는 launder 로 건너뛰되, **그 외 위치(sibling raw ``str(e)``)
    의 alias ref 가 하나라도 있으면 taint** → 그 handler 가
    per-handler ``nonconforming`` 에 집계돼 FAIL. 정상 chokepoint-only
    handler 는 nonconforming 에 안 들고 ``choke > 0`` 에 기여한다 —
    즉 강화가 정상 패턴을 false-positive 로 깨지 않는다.

    **old 코드(chokepoint child 조기 종료)에서는 red(누락)
    = fail-open** — 영구 회귀 락.
    """
    syn_routes = tmp_path / "syn_routes_1651_a9m"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    # mixed-expr 우회: detail dict 에 chokepoint(safe)와 raw str(e)
    # 가 sibling — chokepoint child 를 먼저 walk 하면 raw 누락.
    (syn_routes / "mixed.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "from ante.web.errors import sanitize_validation_errors\n"
        "\n"
        "class MixedReq(BaseModel):\n"
        "    x: int\n"
        "\n"
        "def mixed_handler(payload):\n"
        "    try:\n"
        "        return MixedReq.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail={\n"
        '                "safe": sanitize_validation_errors(e),\n'
        '                "raw": str(e),\n'
        "            },\n"
        "        ) from None\n"
    )
    # 정상 chokepoint-only handler — 강화가 false-positive 로 깨면 안 됨.
    (syn_routes / "ok.py").write_text(
        "from pydantic import BaseModel, ValidationError\n"
        "from fastapi import HTTPException\n"
        "from ante.web.errors import sanitize_validation_errors\n"
        "\n"
        "class OkReq(BaseModel):\n"
        "    z: int\n"
        "\n"
        "def ok_handler(payload):\n"
        "    try:\n"
        "        return OkReq.model_validate(payload)\n"
        "    except ValidationError as e:\n"
        "        raise HTTPException(\n"
        "            status_code=422,\n"
        "            detail=sanitize_validation_errors(e),\n"
        "        ) from None\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_a9m")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        choke, nonconforming = _scan_validationerror_handler_chokepoint()
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    assert any("mixed" in s for s in nonconforming), (
        "attempt-9 mixed-expr 회귀 — chokepoint 와 sibling raw "
        "``str(e)`` 가 섞인 detail 표현의 handler 가 nonconforming "
        "으로 안 잡힘(chokepoint child 조기 종료 fail-open 재발): "
        f"nonconforming={nonconforming}"
    )
    assert not any("ok" in s for s in nonconforming), (
        "정상 chokepoint-only handler 가 nonconforming 으로 잘못 "
        f"잡힘 — mixed-expr 전체 스캔이 정상 패턴을 false-positive: "
        f"{nonconforming}"
    )
    assert choke >= 1, (
        "정상 chokepoint handler 가 choke 로 안 잡힘 — 전체 스캔이 "
        f"정상 패턴을 false-negative: choke={choke}"
    )


# attempt-9 canary ③ 전용 모듈-레벨 모델(qualname 이 dotted-suffix
# 없는 안정 식별자여야 owner 키가 ``_NestedReuseInner`` 로 고정 —
# 함수-로컬 클래스는 ``<locals>`` 가 붙음).
class _NestedReuseInner(BaseModel):
    creds: dict[str, str] = {}


class _NestedReuseParent(BaseModel):
    a: _NestedReuseInner
    b: _NestedReuseInner


def test_attempt9_nested_same_type_two_field_reuse_full_path_key_locked() -> None:
    """attempt-9 회귀 canary ③ (Codex [P2] — nested 동일 타입 2필드
    재사용 full static schema path 키 영구 락):

    동일 nested ``BaseModel`` 타입(``_Inner`` — unsafe ``dict[str,str]``
    필드 보유)이 한 요청 모델의 **두 필드**(``a``/``b``)에 재사용되면,
    이전 ``_owner_field_key`` 의 마지막-owner suffix 정규화가 두 경로
    (``a.creds``·``b.creds``)를 같은 ``(_Inner, creds, site)`` 단일
    키로 **병합**했다. 그러면 한 부모 경로(``a``)의 pre-reject proof
    가 무가드 다른 부모 경로(``b``)까지 덮어 fail-open PASS.

    신 로직: dict 노드 키의 path 성분을 **루트 요청모델부터 그 dict
    노드까지의 full static schema field-path** 로 보존
    (``a.creds`` ≠ ``b.creds``) → 두 경로가 distinct 키. ``a`` 경로만
    proof 등록하면 ``b`` 경로는 자기 proof 가 없어 UNPROVEN→FAIL.

    **old 코드(마지막-owner suffix 병합)에서는 red(병합돼 한
    proof 가 무가드 경로까지 덮음) = fail-open** — 영구 회귀 락.
    site-id(enclosing-qualname) 성분은 그대로 결합됨도 확인.
    """
    site = "syn:lock_a9n:nested_reuse:_NestedReuseParent.model_validate"
    disc = discover_annotation(
        _NestedReuseParent,
        _NestedReuseParent.__qualname__,
        validating_site=site,
    )

    node_a = ("_NestedReuseInner", "a.creds", site)
    node_b = ("_NestedReuseInner", "b.creds", site)
    # 두 부모 경로가 **distinct** full-path 키로 분리돼야 한다(병합
    # 이면 ``(_Inner, creds, site)`` 단일 노드만 남음).
    assert node_a in disc.dict_nodes and node_b in disc.dict_nodes, (
        "attempt-9 nested full-path 회귀 — 동일 nested 타입 2필드 "
        "재사용이 부모 경로별 distinct (owner, full-path, site) 키로 "
        f"분리되지 않음(마지막-owner suffix 병합 재발): "
        f"{sorted(disc.dict_nodes)}"
    )
    merged = ("_NestedReuseInner", "creds", site)
    assert merged not in disc.dict_nodes, (
        "attempt-9 nested full-path 회귀 — 마지막-owner suffix "
        f"병합 키 ``{merged}`` 가 생성됨(full-path 보존 실패)"
    )

    # ``a`` 경로만 proof 등록 → ``b`` 경로는 UNPROVEN→FAIL 해야 한다
    # (병합이면 ``a`` proof 가 무가드 ``b`` 경로까지 덮어 PASS).
    registered_a_only = frozenset({node_a})
    verdict = compute_verdict(
        disc,
        [],
        registered_dict_keys=registered_a_only,
        registered_validator_ids=frozenset(),
    )
    assert not verdict.ok, (
        "attempt-9 nested full-path fail-open 재발 — ``a`` 경로 "
        "proof 만 등록했는데 lock PASS(무가드 ``b`` 경로가 ``a`` "
        f"proof 로 재사용됨): unproven_dict={verdict.unproven_dict}"
    )
    assert node_b in set(verdict.unproven_dict), (
        "attempt-9 — 무가드 ``b.creds`` 경로가 UNPROVEN 으로 안 "
        f"떨어짐: unproven={verdict.unproven_dict}"
    )
    assert node_a not in set(verdict.unproven_dict), (
        "``a.creds`` 경로는 proof 등록됐으므로 PROVEN 이어야 함 "
        f"(per-full-path 1:1 결합 회귀): unproven={verdict.unproven_dict}"
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
    # S2 site-id 형식(INV-1 정밀화 — Codex attempt-5 [P2]):
    # ``{route_path}[{methods}]@{mod}.{endpoint_qn}#{kind}``. route
    # path 는 첫 ``[`` 앞 토큰이다(method/endpoint qualname 보존으로
    # site-id 가 distinct — 같은 path 다른 method/handler 면 별 site).
    by_path: dict[str, set[Any]] = {}
    for path, ann in collected.body_models:
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            # 예: "/s1[POST]@mod._s1#body_field" → route="/s1".
            route = path.split("[", 1)[0]
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CV1 S1b canary ①: synthetic unsafe entrypoint(미walkable
    TypeAdapter) → **실제 S1 scanner/resolver** 가 단일
    ``unresolvable`` 로 충전(우회 불가, 비공허 회귀 락).

    이전 구현은 synthetic 파일 생성 후 **테스트 내부 별도 AST
    루프**만 돌고 ``_scan_s1_entrypoints()``/``_resolve_s1()`` 를
    호출하지 않아, 실제 S1 scanner/resolver 가 TypeAdapter 검증을
    더 이상 unresolvable 로 충전 안 하게 회귀해도 canary 가
    green(공허 단언)이었다. 본 canary 는 ``_ROUTES_DIR``/
    ``_ROUTES_PKG`` 를 synthetic routes 디렉터리로 monkeypatch 한
    뒤 **실제 ``_scan_s1_entrypoints()``/``_resolve_s1()`` 를
    호출**해 unsafe TypeAdapter 검증 site 가 INV-3 single-sink
    ``unresolvable`` 에 들어가는지(그리고 models 로 잘못 충전되지
    않는지) 단언한다 — 실-resolver 경유(공허 일소).
    """
    syn_routes = tmp_path / "syn_routes_1651_c1"
    syn_routes.mkdir()
    (syn_routes / "__init__.py").write_text('"""syn routes pkg."""\n')
    (syn_routes / "ta.py").write_text(
        "from pydantic import TypeAdapter\n"
        "def h(payload):\n"
        "    return TypeAdapter(dict[str, int]).validate_python(payload)\n"
    )

    import sys

    lock_mod = sys.modules[__name__]
    monkeypatch.setattr(lock_mod, "_ROUTES_DIR", syn_routes)
    monkeypatch.setattr(lock_mod, "_ROUTES_PKG", "syn_routes_1651_c1")

    sys.path.insert(0, str(tmp_path))
    try:
        importlib.invalidate_caches()
        for m in list(sys.modules):
            if m == "syn_routes_1651_c1" or m.startswith("syn_routes_1651_c1."):
                del sys.modules[m]
        sites = _scan_s1_entrypoints()
        s1 = _resolve_s1()
    finally:
        for m in list(sys.modules):
            if m == "syn_routes_1651_c1" or m.startswith("syn_routes_1651_c1."):
                del sys.modules[m]
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    # 실제 scanner 가 TypeAdapter entrypoint 를 발견했는가.
    assert any(
        s.module == "syn_routes_1651_c1.ta" and "TypeAdapter(" in s.receiver
        for s in sites
    ), (
        "S1b canary ① — 실제 ``_scan_s1_entrypoints()`` 가 synthetic "
        f"unsafe TypeAdapter entrypoint 를 발견 못 함(우회 가능): {sites}"
    )
    # 실제 resolver 가 그것을 단일 unresolvable sink 로 충전.
    assert any("TypeAdapter" in u for u in s1.unresolvable), (
        "S1b canary ① 비공허 회귀 락 위반 — 실제 ``_resolve_s1()`` 가 "
        "unsafe TypeAdapter 검증을 INV-3 single-sink unresolvable 로 "
        f"충전하지 않음(공허/회귀 = fail-open): {s1.unresolvable}"
    )
    # 잘못 models(정적 BaseModel resolve 성공)로 충전되면 안 된다.
    assert not any(sid.startswith("syn_routes_1651_c1.ta:") for sid, _m in s1.models), (
        "S1b canary ① — unsafe TypeAdapter 검증이 정적 BaseModel "
        f"models 로 잘못 충전됨(극성 위반): {s1.models}"
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
            enclosing="helper",
        )
        pairs, all_resolved = _trace_generic_helper_model_args(site)
    finally:
        sys.modules.pop(modname, None)
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()

    assert not all_resolved, (
        "S1b canary ② 위반 — literal+dynamic 혼재 helper 가 "
        "all-must-resolve 로 unresolvable 판정되지 않음(any-match "
        f"fail-open): pairs={[(cs, m.__name__) for cs, m in pairs]}"
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
