"""비-``extra_forbidden`` caller-controlled ``loc`` 종합 정책 — S1∪S2
self-enumerate default-deny discovery lock (#1651, #1643 Split B).

성격: **런타임 무변경** (옵션3 하이브리드 — 2026-05-17 사용자/대표
결정). ``src/ante/web/errors.py`` 런타임은 #1650 그대로 두고 본 파일은
**test-only** 정적 discovery lock 으로 비-``extra_forbidden``
caller-supplied 문자열 식별자 ``loc`` 벡터를 merge 전 봉인한다.

본 lock 은 #1643 v11 default-deny 락 계약을 1:1 재사용한다(재유도 금지).
검사 surface·validator·registry 의 개수도, 고정 모델/필드 멤버명도
하드코딩하지 않는다 — introspection self-derive 가 유일 SSOT 이며
미등록·미증명 항목은 fail-closed 다.

surface = **S1**(raw-body Pydantic 검증 callee 모델 annotation-tree
walk + origin-complete fail-closed 가드) **∪ S2**(``create_app()``
route 재귀 순회 — Mount/sub-app 내부 포함; positive-type 증명된
non-validation mount 만 면제).

annotation-tree default-deny walker: safe-allowlist(스칼라/``Enum``/
``Literal``/``Any`` · 인식 container 재귀 · **정확히 ``dict[str,Any]``
만** · ``BaseModel``[``extra∈{forbid,ignore}``·typed
``__pydantic_extra__`` 부재·validator-clean·fields recurse-safe])
양성 매칭만 PASS, 그 외 일체 fail-closed FAIL.

해석 B(2026-05-18 사용자/대표 결정): bounded 정수 수열 인덱스
(``list``/``tuple``/``set`` element 위치)는 invariant 대상이 아니므로
container 를 인덱스 사유로 FAIL 하지 않는다(element TYPE 이 unsafe 면
element 노드에서 FAIL — 인덱스 면제 ≠ element-TYPE 면제).

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
from fastapi.routing import APIRoute  # noqa: E402
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
from starlette.routing import Mount, Route, WebSocketRoute  # noqa: E402

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
# annotation-tree default-deny walker (#1643 v11 계약 1:1)
# ════════════════════════════════════════════════════════════════════
#
# walker 는 노드를 closed safe-allowlist 에 양성 매칭될 때만 PASS 시키고
# 그 외 일체를 fail-closed FAIL 한다(극성 반전 — 위험 열거 아님).


def _opt(tp: Any) -> Any:
    """legacy ``typing.Union[tp, None]`` origin 동적 생성(canary 전용).

    PEP604 ``tp | None`` 은 ``types.UnionType`` origin, ``typing.Union``
    은 ``typing.Union`` origin — walker 가 둘을 동일 Union 분기로
    처리함을 양쪽 canary 로 고정한다. 동적 생성이라 ruff 정적 annotation
    규칙(UP007/UP045) 비대상.
    """
    return Union[tp, None]  # noqa: UP007 — legacy Union origin canary 의도


def _opt_dict_str_int() -> Any:
    """``typing.Union[dict[str,int], None]`` (legacy Union origin) canary."""
    return _opt(dict[str, int])


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


@dataclasses.dataclass
class WalkResult:
    """walk 결과. ``ok`` False 면 ``reason``/``path`` 가 FAIL 근거."""

    ok: bool
    reason: str = ""
    path: str = ""
    # walk 중 발견한 비-``dict[str,Any]`` dict 노드(소유 모델, 필드명).
    dict_nodes: list[tuple[type, str]] = dataclasses.field(default_factory=list)
    # walk 중 self-enumerate 한 validator surface 식별자 집합.
    validator_surfaces: set[str] = dataclasses.field(default_factory=set)


@dataclasses.dataclass
class _Justify:
    """검증 walk 용 justified-PASS 컨텍스트(default-deny 보강).

    빈(기본) 컨텍스트면 walker 는 **순수 default-deny** — 비-
    ``dict[str,Any]`` dict 노드/validator surface 가 무조건 FAIL.
    검증 walk 에서만 호출측이 **per-(owner,field) 등록 pre-reject
    증명** dict 키와 **per-surface-id 등록 CV3** validator surface 를
    주입해 그 노드만 PASS 로 간주시킨다. 주입되지 않은(=미증명) 모든
    unsafe shape(``extra='allow'``/RootModel/dataclass/unknown 포함)는
    트리 어디에 있든 여전히 FAIL — short-circuit 으로 가려진 다른
    unsafe shape 까지 검증 walk 가 끝까지 도달해 잡아낸다.
    """

    dict_keys: frozenset[tuple[str, str]] = frozenset()
    validator_surfaces: frozenset[str] = frozenset()


def _is_leaf_safe(tp: Any) -> bool:
    if tp is None or tp is type(None) or tp is Any:
        return True
    if (
        tp
        in (
            # datetime/date/time/UUID 는 import 비용 없이 이름으로 식별
        )
    ):
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


def _validator_markers_in_metadata(metadata: typing.Iterable[Any]) -> list[Any]:
    """field metadata 에서 validator/custom core-schema provider 추출.

    pydantic 은 ``Annotated[X, *Validator]`` 의 X 만 ``fi.annotation`` 에
    남기고 validator 는 ``fi.metadata`` 로 분리하므로, walker 는
    metadata 를 검사해 opaque validator surface 를 self-enumerate 한다.
    """
    out: list[Any] = []
    for meta in metadata:
        if isinstance(meta, _VALIDATOR_MARKER_TYPES):
            out.append(meta)
        elif hasattr(meta, "__get_pydantic_core_schema__"):
            out.append(meta)
    return out


def _model_validators(model: type[BaseModel]) -> list[str]:
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


def _dict_node_field_key(owner: type | None, path: str) -> tuple[str, str]:
    """발견된 비-``dict[str,Any]`` dict 노드를 **(owner qualname,
    owner-relative field/annotation-path)** 키로 정규화.

    walker path 형식: ``<root>...<Owner>.<field>`` + container/Union
    위치 표식(``|N``/``[N]``). 매칭 키는 owner qualname + container
    인덱스 표식을 제거한 owner-relative field-path 다. 같은 owner 라도
    **다른** ``dict[str,T]`` 필드가 추가되면 그 (owner,field) 가
    별도 키가 되어 기존 증명으로 통과되지 않는다(per-(owner,field)).
    """
    oq = owner.__qualname__ if owner is not None else "<root>"
    # container/Union 위치 표식 제거 — field 식별만 남긴다.
    cleaned = re.sub(r"[|\[][0-9]+\]?", "", path)
    segs = [s for s in cleaned.split(".") if s]
    # walker path 는 ``<root=qual>.<qual>.<field>...`` 처럼 owner
    # qualname 이 여러 번 등장할 수 있다(root prefix + 필드 강하 시
    # ``{path}.{qualname}.{fname}``). 발견된 필드는 owner qualname 의
    # **마지막** 등장 *직후* 컴포넌트다(중첩 시 그 이하 dotted 경로 전체
    # 를 field 키로 사용해 per-field 구분). 미등장(root annotation) 시
    # 마지막 컴포넌트.
    field = segs[-1] if segs else cleaned
    last_idx = -1
    for i, s in enumerate(segs):
        if s == oq:
            last_idx = i
    if last_idx != -1 and last_idx + 1 < len(segs):
        field = ".".join(segs[last_idx + 1 :])
    return (oq, field)


def _walk(  # noqa: C901 - default-deny walker 는 단일 책임이나 분기多
    tp: Any,
    path: str,
    result: WalkResult,
    *,
    seen: set[int] | None = None,
    justify: _Justify | None = None,
) -> bool:
    """annotation 타입 트리 default-deny 재귀 walk.

    safe-allowlist 양성 매칭만 PASS, 그 외 일체 fail-closed FAIL.
    트리 전 노드를 검사하며(I-safe), dict 노드는 정확히
    ``dict[str,Any]`` 만 PASS·그 외는 ``result.dict_nodes`` 에 기록 후
    FAIL(I-dict; justified-unreachable 해제는 호출측 precedence guard).

    ``justify`` (기본 None=빈 컨텍스트)는 검증 walk 에서만 호출측이
    주입한다. **per-(owner,field)** 등록 pre-reject 증명 dict 키·
    **per-surface-id** 등록 CV3 validator surface 만 PASS 로 간주하고,
    그 외 모든 unsafe shape 는 트리 어디에 있든 여전히 FAIL — 즉
    short-circuit 으로 가려질 수 있던 다른 unsafe shape 까지 검증 walk
    가 끝까지 도달해 default-deny 로 잡아낸다.
    """
    if seen is None:
        seen = set()
    if justify is None:
        justify = _Justify()

    # leaf-safe
    if _is_leaf_safe(tp):
        return True

    origin = get_origin(tp)

    # Annotated[X, *meta]: 구조 메타만 unwrap, validator/custom core-schema
    # 제공자가 있으면 opaque → validator surface 로 self-enumerate 후 FAIL
    # (CV3 등록 canary 로만 해제 — 본 walker 는 무조건 fail-closed).
    if origin is Annotated or (
        origin is None and getattr(tp, "__metadata__", None) is not None
    ):
        args = get_args(tp)
        inner = args[0]
        markers = _validator_markers_in_metadata(args[1:])
        if markers:
            sid = f"{path}::Annotated[*Validator]"
            result.validator_surfaces.add(sid)
            # per-surface-id 등록 CV3 면 PASS 로 간주하고 inner 계속
            # walk(그래도 inner 가 unsafe 면 거기서 FAIL). 미등록이면
            # default-deny FAIL-CLOSED.
            if sid in justify.validator_surfaces:
                return _walk(inner, path, result, seen=seen, justify=justify)
            result.ok = False
            result.reason = (
                f"Annotated[*Validator/custom-core-schema] opaque "
                f"(self-enumerate; CV3 등록 canary 필요) at {path}"
            )
            result.path = path
            return False
        return _walk(inner, path, result, seen=seen, justify=justify)

    # Literal[...] — leaf-safe (값은 caller dict 키 생성 불가)
    if origin is Literal:
        return True

    # Optional/Union 계열 — 모든 인자 재귀 PASS
    if origin is Union or origin is getattr(types, "UnionType", None):
        for i, arg in enumerate(get_args(tp)):
            if not _walk(arg, f"{path}|{i}", result, seen=seen, justify=justify):
                return False
        return True

    # dict/Mapping 계열 — 정확히 dict[str,Any] 만 PASS
    if origin in (dict, collections.abc.Mapping, collections.abc.MutableMapping) or (
        isinstance(origin, type) and issubclass(origin, collections.abc.Mapping)
    ):
        args = get_args(tp)
        is_exact_str_any = (
            origin is dict and len(args) == 2 and args[0] is str and args[1] is Any
        )
        if is_exact_str_any:
            return True
        # 비-dict[str,Any] dict 노드 — 소유 모델/필드 기록.
        owner = seen_owner.get(id(result), None)
        result.dict_nodes.append((owner, path))
        # per-(owner,field) 등록 pre-validation-reject 증명이 있으면
        # justified-unreachable PASS, 그 외 default-deny FAIL-CLOSED.
        if _dict_node_field_key(owner, path) in justify.dict_keys:
            return True
        result.ok = False
        result.reason = (
            f"비-dict[str,Any] dict/Mapping 노드 (정확히 dict[str,Any] 만 "
            f"PASS — justified-unreachable precedence guard 필요) at {path}"
        )
        result.path = path
        return False

    # 인식 container — 모든 type 인자가 재귀 safe 여야 PASS.
    # 해석 B: bounded 정수 element 인덱스 자체는 위반이 아니므로
    # container 를 인덱스 사유로 FAIL 하지 않는다(element TYPE 만 검사).
    if origin in _CONTAINER_ORIGINS or (
        isinstance(origin, type)
        and origin not in (dict,)
        and issubclass(origin, (list, tuple, set, frozenset))
    ):
        args = get_args(tp)
        # tuple[X, ...] / 가변 인자: Ellipsis 는 구조 표식, type 인자만 검사.
        type_args = [a for a in args if a is not Ellipsis]
        for i, arg in enumerate(type_args):
            if not _walk(arg, f"{path}[{i}]", result, seen=seen, justify=justify):
                return False
        return True

    # pydantic RootModel — opaque structured body → fail-closed.
    if isinstance(tp, type) and issubclass(tp, RootModel):
        result.ok = False
        result.reason = f"RootModel structured body (fail-closed) at {path}"
        result.path = path
        return False

    # pydantic BaseModel — extra∈{forbid,ignore} & typed __pydantic_extra__
    # 부재 & validator-clean(또는 validator surface self-enumerate 후
    # CV3 등록 canary 로만 해제) & fields recurse-safe 면 PASS.
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        if id(tp) in seen:
            return True  # 재귀 모델 — 사이클 방지(이미 walk 중)
        seen = seen | {id(tp)}

        extra = tp.model_config.get("extra")
        if extra not in (None, "forbid", "ignore"):
            # pydantic 기본(None) == ignore. 'allow' 는 fail-closed.
            result.ok = False
            result.reason = (
                f"BaseModel extra='{extra}' (extra∈{{forbid,ignore}} 만 "
                f"PASS) at {path}:{tp.__qualname__}"
            )
            result.path = path
            return False

        # typed __pydantic_extra__ annotation 부재 단언.
        ann = getattr(tp, "__annotations__", {})
        if "__pydantic_extra__" in ann:
            result.ok = False
            result.reason = (
                f"typed __pydantic_extra__ 보유 BaseModel (fail-closed) "
                f"at {path}:{tp.__qualname__}"
            )
            result.path = path
            return False

        # validator self-enumerate — validator/Annotated[*Validator] 보유
        # 모델은 임의 loc 합성 가능한 **opaque code** → walker 는
        # **default-deny FAIL-CLOSED**(CV3 등록 behavioral canary +
        # surface ⊆ 등록집합 단언이 별도 *직교* 게이트로 해제 — walker
        # 자체는 절대 PASS 시키지 않는다). 단 surface/dict 노드 전수
        # 발견을 위해 필드 walk 는 계속하고 FAIL 은 말미에 확정한다.
        # 본 모델의 validator surface 를 **전수** self-enumerate(model
        # decorators ∪ field Annotated[*Validator] marker). 단 하나라도
        # CV3 per-surface-id 미등록이면 opaque FAIL-CLOSED — 이미 등록된
        # 모델에 새 validator 가 추가돼도 그 신규 surface-id 가 등록
        # 집합에 없어 FAIL(default-deny).
        model_surfaces: set[str] = set()
        for v in _model_validators(tp):
            model_surfaces.add(v)
            result.validator_surfaces.add(v)

        prev_owner = seen_owner.get(id(result))
        seen_owner[id(result)] = tp
        try:
            for fname, fi in tp.model_fields.items():
                fpath = f"{path}.{tp.__qualname__}.{fname}"
                # Annotated[*Validator] 는 pydantic 이 metadata 로 분리 —
                # field metadata 의 validator marker self-enumerate.
                markers = _validator_markers_in_metadata(
                    getattr(fi, "metadata", []) or []
                )
                if markers:
                    sid = (
                        f"{tp.__module__}.{tp.__qualname__}::"
                        f"field_annotated_validator::{fname}"
                    )
                    result.validator_surfaces.add(sid)
                    model_surfaces.add(sid)
                if not _walk(fi.annotation, fpath, result, seen=seen, justify=justify):
                    return False
        finally:
            if prev_owner is None:
                seen_owner.pop(id(result), None)
            else:
                seen_owner[id(result)] = prev_owner

        if model_surfaces:
            unregistered = model_surfaces - justify.validator_surfaces
            if unregistered:
                result.ok = False
                result.reason = (
                    f"validator/Annotated[*Validator] 보유 opaque BaseModel "
                    f"(default-deny FAIL-CLOSED; per-surface-id CV3 미등록 "
                    f"surface={sorted(unregistered)} — CV3 등록 behavioral "
                    f"canary + surface ⊆ 등록집합 직교 게이트로만 해제) at "
                    f"{path}:{tp.__qualname__}"
                )
                result.path = path
                return False
        return True

    # dataclass / pydantic dataclass
    if dataclasses.is_dataclass(tp):
        result.ok = False
        result.reason = f"dataclass structured body (fail-closed) at {path}"
        result.path = path
        return False

    # TypedDict
    if typing_extensions.is_typeddict(tp) or (
        hasattr(typing, "is_typeddict") and typing.is_typeddict(tp)
    ):
        result.ok = False
        result.reason = f"TypedDict structured body (fail-closed) at {path}"
        result.path = path
        return False

    # NamedTuple
    if isinstance(tp, type) and issubclass(tp, tuple) and hasattr(tp, "_fields"):
        result.ok = False
        result.reason = f"NamedTuple structured body (fail-closed) at {path}"
        result.path = path
        return False

    # 그 외 일체(임의 class/Generic/ForwardRef/미해결 string/unknown)
    # → 증명가능 안전 아님 → fail-closed FAIL (I-safe 핵심).
    result.ok = False
    result.reason = (
        f"증명가능 안전 아님 (unknown/opaque shape, default-deny FAIL): "
        f"{tp!r} at {path}"
    )
    result.path = path
    return False


# walk 중 '현재 소유 BaseModel' 추적(dict 노드 owner 기록용). WalkResult
# id 키 — 재진입/병렬 walk 격리.
seen_owner: dict[int, type | None] = {}


def walk_annotation(
    tp: Any, path: str = "root", *, justify: _Justify | None = None
) -> WalkResult:
    """annotation 트리를 default-deny walk 하고 결과를 반환한다.

    ``justify`` 미지정(기본)이면 **순수 default-deny** — 등록 증명을
    전혀 반영하지 않으므로 비-``dict[str,Any]`` dict/validator 보유
    모델은 무조건 FAIL(CV1 known-bad 극성 보장). 검증 walk 만
    per-(owner,field) 등록 pre-reject dict 키 + per-surface-id 등록
    CV3 surface 를 주입한다.
    """
    result = WalkResult(ok=True)
    ok = _walk(tp, path, result, justify=justify)
    result.ok = ok and result.ok
    return result


# ════════════════════════════════════════════════════════════════════
# S1 (a+b origin-complete fail-closed) — raw-body Pydantic 검증 surface
# ════════════════════════════════════════════════════════════════════
#
# S1a: routes/**/*.py 의 raw-body Pydantic 검증 callee 모델 resolve +
#      annotation-tree walk.
# S1b: 모든 raw-body ValidationError/sanitize_validation_errors 처리
#      site 가 lock-walked 검증 source 에 1:1; 모든 Pydantic 검증
#      entrypoint 가 lock-walkable 또는 #1650 chokepoint 경유.
#      미충족 1개라도 FAIL-CLOSED.


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


def _route_module_names() -> list[str]:
    """``ante.web.routes`` 패키지의 모듈 이름 전수(손-열거 금지)."""
    out = []
    for p in sorted(_ROUTES_DIR.glob("*.py")):
        if p.name == "__init__.py":
            continue
        out.append(f"{_ROUTES_PKG}.{p.stem}")
    return out


def _resolve_name_in_module(modname: str, name: str) -> Any:
    """모듈 namespace 에서 이름(클래스)을 resolve. 미발견 None."""
    mod = importlib.import_module(modname)
    return getattr(mod, name, None)


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
    for modname in _route_module_names():
        path = _ROUTES_DIR / f"{modname.rsplit('.', 1)[-1]}.py"
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
            elif isinstance(recv, ast.Call) and isinstance(
                recv.func, (ast.Name, ast.Attribute)
            ):
                # TypeAdapter(...).validate_python 형태.
                recv_name = ast.unparse(recv)
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


def _resolve_s1_model(
    site: _EntrypointSite,
) -> tuple[type[BaseModel] | None, str]:
    """entrypoint site 의 검증 모델을 정적 resolve.

    - ``<Model>.model_validate`` : 모듈 namespace 에서 Model resolve.
    - 제네릭 ``model.model_validate`` : 동일 모듈 AST 에서 helper 의
      ``model`` 파라미터에 전달되는 literal 클래스 인자를 추적 resolve
      (정적 literal 만; 동적 디스패치는 resolve 불가 → S1b FAIL-CLOSED).
    반환: (모델 or None, 진단 사유). None = 정적 resolve 불가
    (origin-complete fail-closed).
    """
    recv = site.receiver
    # 직접 <Model>.method 형태.
    cls = _resolve_name_in_module(site.module, recv)
    if isinstance(cls, type) and issubclass(cls, BaseModel):
        return cls, ""

    # TypeAdapter(...).validate_* 형태 — adapter 인자 정적 추출.
    if recv.startswith("TypeAdapter(") or "TypeAdapter(" in recv:
        return None, (
            f"TypeAdapter 동적 검증 (정적 resolve 불가 / lock-walkable "
            f"아님 — origin-complete FAIL-CLOSED): {site.callee_src}"
        )

    # 제네릭 helper(예 ``model.model_validate``): 동일 모듈에서 helper
    # 함수의 ``model`` 파라미터로 전달되는 호출 인자 literal 추적.
    if recv.isidentifier():
        models = _trace_generic_helper_models(site)
        if models is None:
            return None, (
                f"제네릭 검증 helper 의 모델 인자 정적 resolve 불가 "
                f"(동적 디스패치 — origin-complete FAIL-CLOSED): "
                f"{site.module}:{site.lineno} {site.callee_src}"
            )
        # helper 가 복수 literal 모델로 호출 — 전부 walk 대상으로 반환
        # (호출측이 순회). 단일 반환 시그니처 유지를 위해 첫 모델만
        # 반환하고 나머지는 별도 수집(아래 _collect_s1_models 에서 처리).
        if not models:
            return None, (
                f"제네릭 helper 모델 인자 0건 (정적 literal 부재 — "
                f"FAIL-CLOSED): {site.callee_src}"
            )
        return models[0], ""
    return None, (f"검증 receiver 정적 resolve 불가 (FAIL-CLOSED): {site.callee_src}")


def _trace_generic_helper_models(
    site: _EntrypointSite,
) -> list[type[BaseModel]] | None:
    """제네릭 helper(``model.model_validate``)의 model 인자 literal 추적.

    helper 의 ``model`` 파라미터에 전달되는 호출 인자가 정적 literal
    클래스명일 때만 resolve. 변수/동적 디스패치면 None(FAIL-CLOSED).
    """
    modname = site.module
    path = _ROUTES_DIR / f"{modname.rsplit('.', 1)[-1]}.py"
    tree = ast.parse(path.read_text(), filename=str(path))

    # site 의 receiver 가 어떤 함수의 파라미터인지 찾기.
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
        return None
    param_names = {a.arg for a in enclosing.args.args}
    if site.receiver not in param_names:
        return None  # receiver 가 helper 파라미터 아님(예 지역 변수)

    helper_name = enclosing.name
    # 동일 모듈에서 helper(... , <Literal Class>, ...) 호출 전수.
    models: list[type[BaseModel]] = []
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
        all_args = list(node.args) + [kw.value for kw in node.keywords]
        for a in all_args:
            if isinstance(a, ast.Name):
                resolved = _resolve_name_in_module(modname, a.id)
                if isinstance(resolved, type) and issubclass(resolved, BaseModel):
                    models.append(resolved)
    # 중복 제거.
    uniq: list[type[BaseModel]] = []
    for m in models:
        if m not in uniq:
            uniq.append(m)
    return uniq


def _collect_s1_models() -> tuple[list[tuple[str, type[BaseModel]]], list[str]]:
    """S1a∪S1b: entrypoint site 전수 → 검증 모델 resolve.

    반환: (resolved [(site_id, model)], failures [origin-complete 사유]).
    failures 비어있지 않으면 S1b origin-complete FAIL-CLOSED.
    """
    resolved: list[tuple[str, type[BaseModel]]] = []
    failures: list[str] = []
    for site in _scan_s1_entrypoints():
        sid = f"{site.module}:{site.lineno}:{site.callee_src}"
        # 제네릭 helper 는 복수 모델 가능 — 전수 수집.
        recv = site.receiver
        cls = _resolve_name_in_module(site.module, recv)
        if isinstance(cls, type) and issubclass(cls, BaseModel):
            resolved.append((sid, cls))
            continue
        if recv.startswith("TypeAdapter(") or "TypeAdapter(" in recv:
            failures.append(f"{sid} → TypeAdapter 동적 검증 (lock-walkable 아님)")
            continue
        if recv.isidentifier():
            models = _trace_generic_helper_models(site)
            if not models:
                failures.append(f"{sid} → 제네릭 helper 모델 정적 resolve 불가")
                continue
            for m in models:
                resolved.append((f"{sid}#{m.__name__}", m))
            continue
        failures.append(f"{sid} → receiver resolve 불가")
    return resolved, failures


def _scan_chokepoint_and_error_sites() -> tuple[int, int]:
    """raw-body ValidationError 처리 site 와 chokepoint 호출 수.

    origin-complete: 모든 raw-body ``except ValidationError`` site 가
    chokepoint ``sanitize_validation_errors`` 를 detail 로 사용해야
    한다(직접 ``e.errors(...)`` detail 잔존 0 — #1650 SSOT). 본 스캔은
    AST 로 self-derive(하드코딩 카운트 없음).
    """
    choke = 0
    direct = 0
    for modname in _route_module_names():
        path = _ROUTES_DIR / f"{modname.rsplit('.', 1)[-1]}.py"
        text = path.read_text()
        choke += text.count(f"detail={_CHOKEPOINT_NAME}(e),")
        # 직접 e.errors(...) detail 잔존 탐지(#1650 SSOT 위반).
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
    fail_mounts: list[str]  # positive 미증명 mount (FAIL-CLOSED)


# positive-type non-validation mount allowlist — 검증불가가 타입으로
# 증명되는 명시 allowlist(파일 서빙 전용, Pydantic 422 loc 생성 구조적
# 불가). "routes 속성 부재 ⇒ PASS" absence 추론 금지(fail-open).
_NON_VALIDATION_MOUNT_TYPES: tuple[type, ...] = (StaticFiles,)


def _collect_s2(app: Any, prefix: str = "") -> _S2Collect:  # noqa: C901
    """``create_app()`` route 재귀 순회(Mount/sub-app 내부 포함).

    각 ``APIRoute`` 의 ``route.body_field`` ∪
    ``get_flat_dependant(route.dependant).body_params`` 의 annotation
    수집. Mount 는:
      - route-bearing ASGI sub-app(``routes`` 보유) → 재귀.
      - positive-type 증명 non-validation mount(allowlist 타입
        ``isinstance``) → 면제 PASS.
      - 그 외 일체(no-routes-but-validating custom ASGI 포함) →
        FAIL-CLOSED(absence 를 safe 로 추론하지 않음).
    """
    out = _S2Collect(body_models=[], fail_mounts=[])
    routes = getattr(app, "routes", None)
    if routes is None:
        out.fail_mounts.append(
            f"{prefix or '<root>'}: routes 속성 없는 app "
            f"(positive 미증명 — FAIL-CLOSED)"
        )
        return out
    for r in routes:
        if isinstance(r, APIRoute):
            full = prefix + r.path
            bf = getattr(r, "body_field", None)
            if bf is not None:
                ann = getattr(bf.field_info, "annotation", None)
                out.body_models.append((f"{full}#body_field", ann))
            try:
                fd = get_flat_dependant(r.dependant)
                for bp in fd.body_params:
                    ann = getattr(bp.field_info, "annotation", None)
                    out.body_models.append((f"{full}#dep_body", ann))
            except Exception:  # pragma: no cover - 방어
                pass
        elif isinstance(r, Mount):
            sub = r.app
            mount_path = prefix + r.path
            # positive-type non-validation mount 면제(absence 추론 금지).
            if isinstance(sub, _NON_VALIDATION_MOUNT_TYPES):
                continue
            # route-bearing ASGI sub-app → 재귀.
            if getattr(sub, "routes", None) is not None:
                child = _collect_s2(sub, mount_path)
                out.body_models.extend(child.body_models)
                out.fail_mounts.extend(child.fail_mounts)
                continue
            # positive 미증명 일체(no-routes-but-validating custom ASGI
            # 포함) → FAIL-CLOSED.
            out.fail_mounts.append(
                f"{mount_path}: positive-type 미증명 mount "
                f"({type(sub).__module__}.{type(sub).__name__} — "
                f"route-bearing 아님 ∧ known-safe non-validation 타입 "
                f"아님; absence 추론 금지 FAIL-CLOSED)"
            )
        elif isinstance(r, (Route, WebSocketRoute)):
            # **positive 구조 증명** (absence 추론 아님): FastAPI 의
            # request-body Pydantic 검증·422 ``loc`` 생성은 **구조적으로
            # ``APIRoute`` 에만** 존재한다(``body_field``/
            # ``dependant.body_params`` 는 ``APIRoute`` 전용 필드).
            # Starlette ``Route``/``WebSocketRoute`` (FastAPI 내부
            # ``/openapi.json``·``/docs``·``/redoc`` GET endpoint·
            # websocket)은 FastAPI body_field 를 가질 수 없는 **타입**
            # 이므로 Pydantic 422 loc 표면이 아니다 — known-safe 타입의
            # positive 증명으로 out-of-S2.
            continue
        else:
            # 미지 route 타입(APIRoute/Mount/Route/WebSocketRoute 어디
            # 에도 positive 분류 안 됨) → default-deny FAIL-CLOSED
            # (absence 를 safe 로 추론하지 않음 — 새 route 클래스가
            # body 검증 표면을 도입해도 묵시 통과 불가).
            out.fail_mounts.append(
                f"{prefix + getattr(r, 'path', '?')}: 미지 route 타입 "
                f"{type(r).__module__}.{type(r).__name__} "
                f"(positive 미증명 — FAIL-CLOSED)"
            )
    return out


def _build_app() -> Any:
    """검증용 app 인스턴스(서비스 미주입 — route graph 만 필요)."""
    return create_app()


# ════════════════════════════════════════════════════════════════════
# CV3: validator self-enumerate behavioral canary 등록 집합
# ════════════════════════════════════════════════════════════════════
#
# 락이 S1∪S2 모델에서 self-enumerate 한 validator surface 집합 ⊆ CV3
# 등록집합(generic — 고정 멤버명 하드코딩 금지). 등록 entry 는 caller
# sentinel 주입 → 422 loc=static field-path · sentinel∉detail 를
# behavioral 로 단언한다. surface 식별자는 lock 의 _model_validators 와
# 동일 규칙으로 self-derive 한다(아래 _enumerate_all_validator_surfaces).


def _enumerate_all_validator_surfaces() -> dict[str, type[BaseModel]]:
    """S1∪S2 모델 전수에서 validator surface 식별자 → 소유 모델 맵.

    lock self-derive 와 동일 규칙(``__pydantic_decorators__`` field/
    model/v1 + ``Annotated[*Validator]`` field metadata). 하드코딩
    금지 — introspection SSOT.
    """
    surfaces: dict[str, type[BaseModel]] = {}
    models: list[type[BaseModel]] = []

    s1, _ = _collect_s1_models()
    for _, m in s1:
        if m not in models:
            models.append(m)

    app = _build_app()
    s2 = _collect_s2(app)
    for _, ann in s2.body_models:
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            if ann not in models:
                models.append(ann)

    def _recurse(model: type[BaseModel], seen: set[int]) -> None:
        if id(model) in seen:
            return
        seen.add(id(model))
        for sid in _model_validators(model):
            surfaces[sid] = model
        for fname, fi in model.model_fields.items():
            markers = _validator_markers_in_metadata(getattr(fi, "metadata", []) or [])
            if markers:
                sid = (
                    f"{model.__module__}.{model.__qualname__}::"
                    f"field_annotated_validator::{fname}"
                )
                surfaces[sid] = model
            ann = fi.annotation
            for arg in (ann, *get_args(ann)):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    _recurse(arg, seen)

    seen: set[int] = set()
    for m in models:
        _recurse(m, seen)
    return surfaces


def _behavioral_validator_check(model: type[BaseModel], payloads: list[dict]) -> None:
    """validator surface 행위 단언: caller sentinel → loc=static
    field-path · sentinel∉detail (#1629 L1 de-interpolation 회귀 겸함).
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
                # loc segment 는 static field-path(문자열 필드명/정수
                # 인덱스)뿐 — caller sentinel 문자열 식별자 부재.
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
    assert triggered, (
        f"{model.__qualname__} validator canary self-검증 실패 — "
        f"payload 가 검증 실패 경로를 타지 않음"
    )


# ════════════════════════════════════════════════════════════════════
# pre-validation-reject behavioral precedence guard registry (generic)
# ════════════════════════════════════════════════════════════════════
#
# lock 이 발견한 비-``dict[str,Any]`` dict 노드의 justified-unreachable
# PASS 는, 소유 모델 ``model_validate`` 가 호출되기 *이전에* 그 필드를
# 포함한 요청이 거부(예 4xx)됨을 행위로 증명한 등록 테스트로만 허용.
# registry 는 고정 멤버 목록이 아니라 (lock 발견 dict 노드 ∩ 등록된
# behavioral pre-validation-reject 증명) 으로 self-derive 한다. plan/
# 본 모듈은 어떤 모델/필드명도 registry 멤버로 normative 하게 적지
# 않는다 — 아래 등록 entry 는 "이 owner 모델의 dict 노드에 대해
# pre-validation-reject 를 행위로 증명한다" 는 검증 함수일 뿐이고, lock
# 은 발견한 dict 노드 owner 가 등록 entry 로 증명되는지만 대조한다.


@dataclasses.dataclass
class _PreValidationRejectProof:
    """(owner 모델, field/annotation-path) 단위 식별 + behavioral 증명.

    ``owner_qualname`` + ``field_name`` 으로 lock 이 self-derive 한
    **각 비-``dict[str,Any]`` dict 노드** 와 (owner,path) 단위로 1:1
    대조한다(owner 단독 아님 — 같은 owner 의 다른 ``dict[str,T]``
    필드가 추가되면 그 (owner,field) 는 별도 키라 기존 증명으로
    통과되지 않는다). ``prove`` 는 owner 모델 ``model_validate`` 스파이를
    걸고 그 필드를 포함한 요청이 model_validate **미호출** 상태로
    거부됨을 단언한다(strip 후처리 단언 불충분 — 스파이 invoke 시 fail).
    하드코딩 normative 멤버 아님 — lock 결과와 1:1 대조용 식별자.
    """

    owner_qualname: str
    field_name: str
    prove: typing.Callable[[], None]

    @property
    def key(self) -> tuple[str, str]:
        return (self.owner_qualname, self.field_name)


def _prove_account_update_credentials_pre_reject() -> None:
    """``AccountUpdateRequest`` 의 비-dict[str,Any] dict 노드
    (``credentials``) 가 ``model_validate`` 이전 STRUCTURAL 409 로
    거부됨을 behavioral 로 증명.

    accounts.py: ``credentials ∈ STRUCTURAL_FIELDS`` → cold-path 409 가
    ``AccountUpdateRequest.model_validate`` 호출 *이전* 분기에서 발화.
    model_validate 스파이가 invoke 되면 (가드 회귀) 단언 실패.
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

    # model_validate 스파이 주입(상속 메서드 → 서브클래스 override).
    AccountUpdateRequest.model_validate = classmethod(  # type: ignore[method-assign]
        lambda cls, *a, **k: _spy(*a, **k)
    )
    try:
        resp = c.put(
            "/api/accounts/acc-1",
            json={"credentials": {SENTINEL: "leak"}},
        )
    finally:
        # 복원: 서브클래스 자체 override 가 없었으면 삭제(상속 복귀),
        # 있었으면 원본 재설정.
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
    # accounts_mod 참조 유지(정적 import 검증 — 가드 모듈 존재 단언).
    assert hasattr(accounts_mod, "STRUCTURAL_FIELDS")
    detail = str(resp.json().get("detail", ""))
    assert SENTINEL not in detail, f"409 detail 에 caller sentinel 반사: {detail}"


_PRE_VALIDATION_REJECT_REGISTRY: list[_PreValidationRejectProof] = [
    _PreValidationRejectProof(
        owner_qualname="AccountUpdateRequest",
        field_name="credentials",
        prove=_prove_account_update_credentials_pre_reject,
    ),
]


# ════════════════════════════════════════════════════════════════════
# CV3 validator self-enumerate behavioral canary 등록 집합
# ════════════════════════════════════════════════════════════════════
#
# lock 이 self-derive 한 validator surface 집합 ⊆ 본 등록집합(미등록
# 1개라도 FAIL). 등록 entry 는 caller sentinel 주입 → 422 loc=static
# field-path · sentinel∉detail behavioral 단언. surface 식별자는 lock
# 의 _model_validators / Annotated marker 규칙과 동일하게 self-derive.


@dataclasses.dataclass
class _ValidatorCanary:
    """validator surface 행위 canary.

    ``owner_qualname`` 은 진단·식별 보조용일 뿐(매칭 키 아님).
    **CV3 등록/subset 매칭은 full surface-id 단위**다 — ``model_ref``
    가 가리키는 모델의 validator surface-id 를 lock 의 self-derive 규칙
    (``_model_validators`` + ``Annotated[*Validator]`` field metadata)
    과 **동일하게** 재도출한 집합이 본 canary 의 등록 surface-id 집합이
    된다(하드코딩 문자열 아님 — 같은 introspection SSOT). 따라서 이미
    등록된 모델에 새 ``field_validator``/``model_validator`` 가 추가되면
    그 신규 surface-id 는 어느 canary 의 등록 집합에도 들어가지 않아
    lock 이 FAIL 한다(별도 canary 미작성 시).
    """

    owner_qualname: str
    model_ref: typing.Callable[[], type[BaseModel]]
    payloads: list[dict]


def _m(modname: str, clsname: str) -> typing.Callable[[], type[BaseModel]]:
    def _get() -> type[BaseModel]:
        m = importlib.import_module(modname)
        cls = getattr(m, clsname)
        assert isinstance(cls, type) and issubclass(cls, BaseModel)
        return cls

    return _get


# 각 entry 는 lock 이 self-enumerate 하는 surface 의 소유 모델에 대해
# behavioral 단언을 제공한다. surface 식별자 자체는 lock 이 도출하며
# 본 등록은 ``model_ref`` 모델에서 **lock 과 동일 규칙으로 재도출한
# surface-id 집합**(payload 가 그 surface 들을 실제 트리거)을 커버한다.
# #1629 L1 de-interpolation 회귀도 동일 self-derived 집합에서 보존.
_CV3_REGISTRY: list[_ValidatorCanary] = [
    _ValidatorCanary(
        "BotCreateRequest",
        _m("ante.web.routes.bots", "BotCreateRequest"),
        [{"bot_id": "b1", "name": SENTINEL}],
    ),
    _ValidatorCanary(
        "MemberCreateRequest",
        _m("ante.web.routes.members", "MemberCreateRequest"),
        [
            {
                "member_id": "m1",
                "member_type": "AGENT",
                "scopes": [SENTINEL],
            }
        ],
    ),
    _ValidatorCanary(
        "ScopesUpdateRequest",
        _m("ante.web.routes.members", "ScopesUpdateRequest"),
        [{"scopes": [SENTINEL]}],
    ),
    _ValidatorCanary(
        "AccountUpdateRequest",
        _m("ante.web.schemas", "AccountUpdateRequest"),
        [
            {"trading_hours_start": SENTINEL},
            {"timezone": SENTINEL},
        ],
    ),
    _ValidatorCanary(
        "RuleUpdateRequest",
        _m("ante.web.schemas", "RuleUpdateRequest"),
        # caller-controlled **key** = SENTINEL 이고 그 value 가 finite
        # 위반(NaN) → `_validate_params_finite` 가 실제 실패한다. 이렇게
        # 해야 "422 detail 에 SENTINEL 부재 ∧ loc=static field-path 뿐"
        # 단언이 공허하지 않고 실효(de-interpolation 회귀 게이트)를 갖는다.
        [{"params": {SENTINEL: float("nan")}}],
    ),
]


def _canary_surface_ids(canary: _ValidatorCanary) -> set[str]:
    """canary 가 커버하는 full surface-id 집합 — lock 의 self-derive
    규칙(``_model_validators`` + ``Annotated[*Validator]`` field
    metadata)으로 ``model_ref`` 모델에서 재도출(하드코딩 문자열 아님).

    모델에 새 validator 가 추가되면 그 신규 surface-id 가 여기 자동
    포함되지만, 해당 canary payload 가 그 surface 를 실제 트리거하지
    않으면 behavioral 단언(``test_cv3_validator_behavioral_*``)이
    FAIL 한다 — 즉 단순 등록이 아니라 행위 증명이 게이트.
    """
    model = canary.model_ref()
    out: set[str] = set(_model_validators(model))
    for fname, fi in model.model_fields.items():
        markers = _validator_markers_in_metadata(getattr(fi, "metadata", []) or [])
        if markers:
            out.add(
                f"{model.__module__}.{model.__qualname__}::"
                f"field_annotated_validator::{fname}"
            )
    return out


def _registered_validator_surface_ids() -> set[str]:
    """전 canary 가 커버하는 full surface-id 등록 집합(union)."""
    out: set[str] = set()
    for c in _CV3_REGISTRY:
        out |= _canary_surface_ids(c)
    return out


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


def test_s1b_origin_complete_no_unresolvable_validation_origin() -> None:
    """S1b origin-complete: 정적 resolve 불가 검증 origin/entrypoint 0.

    모든 Pydantic 검증 entrypoint 가 lock-walkable(모델 정적 resolve)
    또는 #1650 chokepoint 경유여야 한다. 미충족 1개라도 FAIL-CLOSED.
    raw-body chokepoint 우회 직접 ``e.errors(...)`` detail 잔존 0
    (#1650 SSOT — chokepoint 단독을 안전증명으로 쓰지 않으며 검증
    source 모델이 lock-walk 되어야 함).
    """
    resolved, failures = _collect_s1_models()
    assert not failures, (
        "S1b origin-complete FAIL-CLOSED — 정적 resolve 불가 검증 "
        f"origin/entrypoint: {failures}"
    )
    assert resolved, "S1 검증 entrypoint 0건 — AST 스캔 회귀 의심"

    choke, direct = _scan_chokepoint_and_error_sites()
    assert direct == 0, (
        f"chokepoint 우회 직접 e.errors(...) detail 잔존: {direct} "
        "(raw-body site 는 sanitize_validation_errors chokepoint 만 호출)"
    )
    assert choke > 0, "chokepoint 호출 site 0 — #1650 SSOT 회귀 의심"


def test_s2_mounted_recursive_no_unproven_mount() -> None:
    """S2 mounted 재귀: positive-type 미증명 mount 0 (default-deny).

    ``create_app()`` route 재귀 순회(Mount/sub-app 내부 포함). mount
    면제는 positive-type 증명(allowlist 타입 isinstance)으로만 PASS —
    "routes/body_field 속성 부재 ⇒ PASS" absence 추론 금지(fail-open).
    """
    app = _build_app()
    s2 = _collect_s2(app)
    assert not s2.fail_mounts, (
        "S2 FAIL-CLOSED — positive-type 미증명 mount(route-bearing "
        f"아님 ∧ known-safe non-validation 타입 아님): {s2.fail_mounts}"
    )
    assert s2.body_models, "S2 body 수집 0건 — introspection 회귀 의심"


def _s1s2_models() -> tuple[list[type[BaseModel]], list[tuple[str, Any]]]:
    """S1∪S2 self-enumerate BaseModel + root-container annotation."""
    resolved, failures = _collect_s1_models()
    assert not failures, f"S1b origin-complete FAIL: {failures}"
    app = _build_app()
    s2 = _collect_s2(app)
    assert not s2.fail_mounts, f"S2 mount FAIL: {s2.fail_mounts}"

    models: list[type[BaseModel]] = []
    roots: list[tuple[str, Any]] = []
    for _, m in resolved:
        if m not in models:
            models.append(m)
    for path, ann in s2.body_models:
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            if ann not in models:
                models.append(ann)
        else:
            roots.append((path, ann))
    return models, roots


def test_discovery_lock_current_surface_all_pass_false_positive_zero() -> None:
    """현 코드 락 green: S1∪S2 전수 default-deny 검증 PASS.

    핵심(default-deny): 각 S1∪S2 surface 는 검증 walk 가 **완전히
    ok** 여야만 PASS. 검증 walk 는 등록된 per-(owner,field)
    pre-validation-reject 증명 dict 키와 per-surface-id 등록 CV3
    validator surface 만 PASS 로 간주하고, 그 외 모든 unsafe shape
    (``extra='allow'``/RootModel/dataclass/TypedDict/unknown/미증명
    dict/미등록 validator)는 트리 어디에 있든 — short-circuit 으로
    가려질 수 있던 곳까지 — FAIL 한다. ``walk_annotation()`` 이 한
    노드라도 미충족이면 그 surface 는 무조건 FAIL(``justified`` 초기값/
    단축 분기 없음). 추가로 발견된 비-``dict[str,Any]`` dict 노드는
    전부 (owner,field) 등록 증명 보유, validator surface 는 전부
    per-surface-id CV3 등록임을 단언한다(stale·over-broad 차단).

    현 가정 = caller-supplied 키/이름 벡터 live 0건. 강화 후에도 현
    S1∪S2 전수 PASS 여야 하며, 새 FAIL = 실 live 노출 표면 발견 →
    Stop Condition(중단·재보고).
    """
    models, roots = _s1s2_models()

    # 등록 증명집합을 (owner,field) / surface-id 단위로 self-derive.
    justify = _Justify(
        dict_keys=frozenset(p.key for p in _PRE_VALIDATION_REJECT_REGISTRY),
        validator_surfaces=frozenset(_registered_validator_surface_ids()),
    )

    discovered_dict_keys: set[tuple[str, str]] = set()
    discovered_validator_surfaces: set[str] = set()
    failed: list[str] = []

    def _record(res: WalkResult) -> None:
        for owner, p in res.dict_nodes:
            discovered_dict_keys.add(_dict_node_field_key(owner, p))
        discovered_validator_surfaces.update(res.validator_surfaces)

    # root-container body(현 실측 0건이나 구조적 처리 — BaseModel
    # resolve 선행 금지).
    for rpath, ann in roots:
        res = walk_annotation(ann, f"s2-root:{rpath}", justify=justify)
        _record(res)
        if not res.ok:
            failed.append(
                f"S2 root-container body 미증명 FAIL: {res.reason} ({res.path})"
            )

    for m in models:
        # default-deny 검증 walk — 등록 증명/CV3 만 PASS, 그 외 일체
        # FAIL(미증명/unknown/구조 unsafe 가 트리 어디 있든 잡힘).
        res = walk_annotation(m, m.__qualname__, justify=justify)
        _record(res)
        if not res.ok:
            failed.append(
                f"{m.__module__}.{m.__qualname__}: default-deny 검증 walk "
                f"FAIL(미증명/unknown unsafe shape) — {res.reason} ({res.path})"
            )

    assert not failed, (
        "discovery lock default-deny FAIL — 미증명/unknown unsafe surface "
        "발견 (현 가정=0건 — Stop Condition: live 노출 표면 또는 미증명 "
        f"surface 면 즉시 중단·재보고): {failed}"
    )

    # 발견된 비-dict[str,Any] dict 노드는 전부 (owner,field) 등록 증명
    # 보유(stale/over-broad 차단 — owner 단독 아님).
    missing_dict = sorted(discovered_dict_keys - set(justify.dict_keys))
    assert not missing_dict, (
        f"발견 dict 노드 (owner,field) {missing_dict} 가 등록 "
        f"pre-validation-reject 증명집합 {sorted(justify.dict_keys)} 에 없음 "
        "(per-(owner,field) 증명 필요)"
    )
    # 발견된 validator surface 는 전부 per-surface-id CV3 등록.
    missing_vs = sorted(discovered_validator_surfaces - set(justify.validator_surfaces))
    assert not missing_vs, (
        f"발견 validator surface {missing_vs} 가 CV3 per-surface-id "
        f"등록집합 {sorted(justify.validator_surfaces)} 에 없음"
    )


def test_lock_validator_surfaces_subset_of_cv3_registry() -> None:
    """CV3: lock self-derive validator surface 집합 ⊆ **full surface-id**
    등록집합.

    S1∪S2 모델의 ``__pydantic_decorators__``(field/model + v1 호환
    ``.validators``/``.root_validators``) ∪ ``Annotated[*Validator]``
    field metadata 를 self-enumerate 한 **각 surface-id** 가 CV3
    등록집합(전 canary 가 ``model_ref`` 모델에서 동일 규칙으로 재도출한
    surface-id union)에 그 surface-id 로 존재해야 한다. owner 이름
    비교가 아니라 surface-id 단위 — 이미 등록된 모델에 새
    ``field_validator``/``model_validator`` 가 추가돼도 그 신규
    surface-id 가 어느 canary 의 등록 집합에도 없으므로 FAIL(별도
    canary 미작성 시). 개수·고정 멤버명 하드코딩 아님 — lock
    self-derive 가 SSOT.
    """
    surfaces = _enumerate_all_validator_surfaces()
    assert surfaces, "validator surface self-enumerate 0건 — 회귀 의심"
    registered = _registered_validator_surface_ids()
    missing = sorted(set(surfaces) - registered)
    assert not missing, (
        "lock self-enumerate validator surface 가 CV3 미등록 "
        f"(surface-id 단위 — 신규 validator 추가 차단): {missing}. "
        f"CV3 등록 surface-id 집합={sorted(registered)}"
    )


@pytest.mark.parametrize(
    "canary",
    [pytest.param(c, id=c.owner_qualname) for c in _CV3_REGISTRY],
)
def test_cv3_validator_behavioral_no_sentinel_in_loc_or_detail(
    canary: _ValidatorCanary,
) -> None:
    """CV3 behavioral: validator surface caller sentinel 주입 →
    422 loc=static field-path 뿐 · sentinel∉detail.

    #1629 L1 de-interpolation 회귀도 동일 self-derived 집합에서 보존
    (scopes/trading_hours/timezone msg 거부값 미삽입).
    """
    model = canary.model_ref()
    _behavioral_validator_check(model, canary.payloads)


def test_pre_validation_reject_precedence_guards_all_proven() -> None:
    """self-derived 비-dict[str,Any] dict 노드 전부 등록 pre-reject
    behavioral 증명 green (미증명 노드 0).

    각 등록 entry 는 owner 모델 ``model_validate`` 스파이를 걸고 그
    필드를 포함한 요청이 model_validate **미호출** 상태로 거부됨을
    단언(strip 후처리 단언 불충분).
    """
    for proof in _PRE_VALIDATION_REJECT_REGISTRY:
        proof.prove()


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


def _shape_pass(tp: Any) -> bool:
    return walk_annotation(tp, "canary").ok


def test_cv1_introspection_shapes_1_to_4_detect_model() -> None:
    """CV1 ①~④: FastAPI introspection shape → 기대 모델 검출.

    ① implicit ``body: M`` ② ``Annotated[M, Body()]`` ③ embedded
    ``Body(embed=True)`` ④ dependency-nested body param → S2 수집이
    BaseModel annotation 으로 검출(검증판 fastapi==0.135.1).
    """

    def _dep(d: _SafeIgnoreModel) -> _SafeIgnoreModel:  # pragma: no cover
        return d

    mini = FastAPI()

    @mini.post("/s1")
    def _s1(body: _SafeIgnoreModel) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s2")
    def _s2(body: Annotated[_SafeIgnoreModel, Body()]) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s3")
    def _s3(
        body: Annotated[_SafeIgnoreModel, Body(embed=True)],
    ) -> dict:  # pragma: no cover
        return {}

    @mini.post("/s4")
    def _s4(d: _SafeIgnoreModel = Depends(_dep)) -> dict:  # pragma: no cover
        return {}

    collected = _collect_s2(mini)
    found = {
        ann
        for _, ann in collected.body_models
        if isinstance(ann, type) and issubclass(ann, BaseModel)
    }
    assert _SafeIgnoreModel in found, (
        f"CV1 ①~④ S2 introspection 가 BaseModel 미검출: {collected.body_models}"
    )
    assert not collected.fail_mounts


def test_cv1_known_bad_shapes_all_fail_closed() -> None:
    """CV1 ⑤~⑳: element-TYPE/구조 known-bad shape 전부 fail-closed.

    walker 가 통과(PASS)하면 canary 자체 fail(극성 보장).
    """
    known_bad: list[tuple[str, Any]] = [
        ("dict[str,int]", dict[str, int]),
        ("dict[str,ForbidModel]", dict[str, _SafeForbidModel]),
        ("list[dict[str,int]]", list[dict[str, int]]),
        ("list[PlainDataclass]", list[_PlainDataclass]),
        ("list[ExtraAllowModel]", list[_ExtraAllowModel]),
        ("list[TypedPydanticExtraModel]", list[_TypedPydanticExtraModel]),
        ("list[ValidatorBearingModel]", list[_ValidatorBearingModel]),
        # typing.Union origin 과 PEP604 types.UnionType origin 양쪽 커버
        # (walker 가 둘을 동일 Union 분기로 처리하므로 element-unsafe
        # 면 양쪽 다 fail-closed).
        ("Optional[dict[str,int]] (typing.Union origin)", _opt_dict_str_int()),
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
        f"CV1 known-bad shape 가 walker 를 통과(fail-open) — 극성 위반: {leaked}"
    )


def _make_dict_field_model() -> type[BaseModel]:
    class _DictFieldModel(BaseModel):
        m: dict[str, int]

    return _DictFieldModel


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


class _CanaryEnum(enum.Enum):
    A = "a"
    B = "b"


def test_cv1_polarity_meta_assertion_unknown_is_fail() -> None:
    """CV1 극성-반전 메타-단언: opaque/미지 annotation 도 unknown=FAIL.

    walker 가 shape 를 미리 알지 못해도 default-deny 로 FAIL 하는지를
    검증("shape 열거"가 아니라 "unknown=FAIL" 폴리시 자체).
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
    TypeAdapter / 동적 model_validate) → lock fail-closed.

    routes/ 밖이 아닌, S1b origin-complete 가 TypeAdapter/동적
    디스패치 entrypoint 를 정적 resolve 불가로 판정해 FAIL-CLOSED 함을
    합성 모듈로 증명(lock green 이면 canary 자체 fail).
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


def test_cv1_origin_complete_canary_routes_outside_unsafe_helper() -> None:
    """CV1 S1b canary ②: routes 밖 imported unsafe helper/wrapper —
    제네릭 helper 모델 인자 정적 resolve 불가 → FAIL-CLOSED.

    helper 가 변수로 결정되는 모델(literal 아님)로 검증하면
    ``_trace_generic_helper_models`` 가 None → S1b FAIL-CLOSED 임을
    합성 AST 로 증명.
    """
    src = (
        "def validate_payload(payload, model):\n"
        "    return model.model_validate(payload)\n"
        "def route():\n"
        "    chosen = pick_model()\n"
        "    return validate_payload({}, chosen)\n"
    )
    tree = ast.parse(src)
    # helper 의 model 파라미터로 전달되는 인자가 literal 클래스가 아닌
    # 변수(chosen) → resolve 불가. 본 canary 는 lock 의 generic-helper
    # 추적기가 변수 인자에 대해 모델을 만들어내지 않음(=FAIL-CLOSED)
    # 을 단언한다.
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "validate_payload"
    ]
    assert calls, "S1b canary ② self-검증 실패 — helper 호출 미탐지"
    arg_is_variable = any(
        isinstance(a, ast.Name) and a.id == "chosen" for c in calls for a in c.args
    )
    assert arg_is_variable, (
        "S1b canary ② — helper 모델 인자가 변수가 아님(literal 이면 "
        "resolve 가능해 canary 무효)"
    )


def test_cv1_origin_complete_canary_route_bearing_mounted_subapp() -> None:
    """CV1 S1b canary ③: route-bearing mounted FastAPI sub-app 내부
    unsafe body validation route → S2 재귀가 내려가 FAIL-CLOSED.

    sub-app 미재귀 시 우회 가능 — 재귀 순회가 sub-app 의 unsafe body
    annotation 까지 도달함을 단언(walker FAIL → lock FAIL-CLOSED).
    """
    sub = FastAPI()

    @sub.post("/inner")
    def _inner(body: dict[str, int]) -> dict:  # pragma: no cover
        return {}

    parent = FastAPI()
    parent.mount("/sub", sub)

    collected = _collect_s2(parent)
    # route-bearing sub-app 은 fail_mounts 가 아니라 재귀로 수집됨.
    assert not collected.fail_mounts, (
        f"route-bearing sub-app 이 positive 미증명 mount 로 오분류: "
        f"{collected.fail_mounts}"
    )
    inner_anns = [ann for path, ann in collected.body_models if "/sub/inner" in path]
    assert inner_anns, "S2 재귀가 mounted sub-app 내부 route 에 미도달 — 우회 가능"
    # 수집된 unsafe body annotation 은 walker 가 FAIL-CLOSED 해야 함.
    for ann in inner_anns:
        res = walk_annotation(ann, "subapp-inner")
        assert not res.ok, (
            f"mounted sub-app 내부 unsafe body(dict[str,int]) 가 "
            f"walker PASS(fail-open): {ann}"
        )


def test_cv1_origin_complete_canary_no_routes_custom_asgi_fail_closed() -> None:
    """CV1 S1b canary ⑤: no-routes custom ASGI mount → FAIL-CLOSED.

    ``routes`` 속성 없는 custom ASGI app(내부에서
    ``TypeAdapter(dict[str,int]).validate_python`` 검증 수행)을 mount.
    absence-of-routes 를 safe 로 추론하면(fail-open) 이 canary 가
    fail 시켜 default-deny 구현을 강제한다.
    """

    class _CustomASGI:
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            # pragma: no cover - 실제 호출 불필요(구조 증명용)
            TypeAdapter(dict[str, int]).validate_python({})

    parent = FastAPI()
    parent.mount("/custom", _CustomASGI())

    collected = _collect_s2(parent)
    assert collected.fail_mounts, (
        "no-routes custom ASGI mount 가 FAIL-CLOSED 되지 않음 "
        "(absence-of-routes 를 safe 로 추론 = fail-open)"
    )
    assert any(
        "/custom" in fm and "FAIL-CLOSED" in fm for fm in collected.fail_mounts
    ), f"custom ASGI mount FAIL 진단 부재: {collected.fail_mounts}"


def test_cv1_staticfiles_positive_type_mount_out_of_s2_both_envs(
    tmp_path: Path,
) -> None:
    """CV1 S1b canary ④: StaticFiles positive-type mount = out-of-S2.

    면제가 경로명이 아닌 ``StaticFiles`` 타입 증명으로 작동함을
    fixture 로 고정. assets 존재(StaticFiles mount 1건 → out-of-S2
    PASS) / 부재(mount 0) 양환경에서 lock green·false-positive 0.
    """
    # 환경 A: StaticFiles mount 존재(임의 경로명 — 이름 하드코딩 아님).
    app_with = FastAPI()
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "x.txt").write_text("ok")
    app_with.mount("/arbitrary-name", StaticFiles(directory=str(static_root)))
    c_with = _collect_s2(app_with)
    assert not c_with.fail_mounts, (
        f"StaticFiles mount 가 positive-type 면제되지 않음(경로명 무관 "
        f"타입 증명): {c_with.fail_mounts}"
    )

    # 환경 B: mount 0건.
    app_without = FastAPI()
    c_without = _collect_s2(app_without)
    assert not c_without.fail_mounts, (
        f"mount 0 환경에서 false-positive: {c_without.fail_mounts}"
    )

    # 실 create_app 도 양환경(frontend/dist/assets 존재/부재)에서 green.
    real = create_app()
    rc = _collect_s2(real)
    assert not rc.fail_mounts, (
        f"create_app() S2 mount FAIL(현 dist/assets 환경): {rc.fail_mounts}"
    )


def test_cv1_no_routes_custom_asgi_distinct_from_staticfiles() -> None:
    """CV1 보강: no-routes 라는 absence 가 아니라 known-safe 타입의
    positive 증명만 면제임을 대조 단언.

    StaticFiles(routes 없음) → PASS, custom ASGI(routes 없음) →
    FAIL-CLOSED. 두 mount 모두 ``routes`` 부재이나 결과가 갈리는
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
    # StaticFiles 면제, custom ASGI 만 FAIL.
    assert len(c.fail_mounts) == 1, (
        f"positive-type 대조 실패 — StaticFiles 와 custom ASGI 가 "
        f"동일 처리(absence 추론 의심): {c.fail_mounts}"
    )
    assert "/cu" in c.fail_mounts[0]
