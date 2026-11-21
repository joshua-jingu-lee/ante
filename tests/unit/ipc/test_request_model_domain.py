"""요청 모델이 있는 모든 IPC 명령은 정의역 밖 인자를 거부한다 (#2665, 축 1).

명령 목록을 손으로 쓰지 않는다. 새 ``CommandRegistry``에 ``register_all_handlers``를
적용해 ``request_model``이 있는 명령 전부를 대상으로 하고, 모델의 필드 타입에서
유효 기준값과 변형을 만든다. 변형은 기준값에서 한 곳만 바꾼다.

판정은 실제 ``IPCServer._dispatch``의 응답 전체와 호출을 기록하는 대역 핸들러다.
기대 오류 종류는 아래 표에 리터럴로 적는다. 구현 모듈의 상수를 기대값으로 쓰지 않는다.
"""

from __future__ import annotations

import json
import logging
import typing
from dataclasses import dataclass, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import AsyncMock, MagicMock

import annotated_types
import pytest
from pydantic import Field, field_validator
from pydantic.fields import FieldInfo

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, CommandSpec, register_all_handlers
from ante.ipc.requests import IPCRequest
from ante.ipc.server import IPCServer, IPCServerState

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = REPO_ROOT / "scripts" / "entry_ratchet_baseline.json"

JSON_KINDS = ("string", "int", "float", "bool", "null", "array", "object")
ACCEPTED_KINDS = {
    "str": {"string"},
    "int": {"int"},
    "float": {"int", "float"},
    "bool": {"bool"},
    "literal": {"string"},
}
WRONG_TYPE = {
    "str": "string_type",
    "int": "int_type",
    "float": "float_type",
    "bool": "bool_type",
    "literal": "literal_error",
}
CONSTRAINT_TYPE = {
    "ge": "greater_than_equal",
    "gt": "greater_than",
    "le": "less_than_equal",
    "lt": "less_than",
    "min_length": "string_too_short",
    "max_length": "string_too_long",
}
NOT_FINITE = (("nan", float("nan")), ("inf", float("inf")), ("-inf", float("-inf")))
EXTRA_KEY = "zz_extra"
UNBOUNDED_FIELDS: frozenset[tuple[str, str]] = frozenset()


class UnsupportedFieldError(Exception):
    pass


@dataclass(frozen=True)
class Variant:
    loc: str
    kind: str
    expected: str
    args: Any
    marker: str | None


@dataclass(frozen=True)
class Inside:
    loc: str
    kind: str
    args: dict[str, Any]
    value: Any


class _Markers:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"MARK{self._prefix}{self._n:03d}SECRET"


def _is_unbounded(annotation: Any) -> bool:
    origin = typing.get_origin(annotation)
    return annotation in (Any, object) or annotation is dict or origin is dict


def _kind(info: FieldInfo) -> str:
    annotation = info.annotation
    if _is_unbounded(annotation):
        raise UnsupportedFieldError(f"unbounded field: {annotation!r}")
    if typing.get_origin(annotation) is Literal:
        if not all(isinstance(m, str) for m in typing.get_args(annotation)):
            raise UnsupportedFieldError(f"non-string Literal: {annotation!r}")
        return "literal"
    for kind, python_type in (("bool", bool), ("int", int), ("float", float)):
        if annotation is python_type:
            return kind
    if annotation is str:
        return "str"
    raise UnsupportedFieldError(f"unsupported annotation: {annotation!r}")


CONSTRAINT_CLASSES = (
    ("ge", annotated_types.Ge, "int"),
    ("gt", annotated_types.Gt, "int"),
    ("le", annotated_types.Le, "int"),
    ("lt", annotated_types.Lt, "int"),
    ("min_length", annotated_types.MinLen, "str"),
    ("max_length", annotated_types.MaxLen, "str"),
)


def _constraints(info: FieldInfo, kind: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for item in info.metadata:
        for name, cls, owner in CONSTRAINT_CLASSES:
            if isinstance(item, cls) and owner == kind:
                found[name] = getattr(item, name)
                break
        else:
            raise UnsupportedFieldError(f"unsupported constraint on {kind}: {item!r}")
    return found


def _has_default(info: FieldInfo) -> bool:
    return not info.is_required()


def _int_base(info: FieldInfo, limits: dict[str, int]) -> int:
    low = limits.get("ge", limits["gt"] + 1 if "gt" in limits else None)
    high = limits.get("le", limits["lt"] - 1 if "lt" in limits else None)
    start = low if low is not None else (high if high is not None else 1)
    for value in (start, start + 1, start - 1):
        inside = (low is None or value >= low) and (high is None or value <= high)
        if inside and not (_has_default(info) and info.default == value):
            return value
    raise UnsupportedFieldError(f"no base value inside {limits!r}")


def _str_base(info: FieldInfo, limits: dict[str, int]) -> str:
    length = max(limits.get("min_length", 1), 1)
    if "max_length" in limits and length > limits["max_length"]:
        raise UnsupportedFieldError(f"no base value inside {limits!r}")
    value = "v" * length
    if _has_default(info) and info.default == value:
        value = "w" * length
    return value


def _base_value(info: FieldInfo) -> Any:
    kind = _kind(info)
    limits = _constraints(info, kind)
    default = info.default if _has_default(info) else None
    if kind == "int":
        return _int_base(info, limits)
    if kind == "str":
        return _str_base(info, limits)
    if kind == "float":
        return 2.5 if default == 1.5 else 1.5
    if kind == "bool":
        return default is not True
    members = typing.get_args(info.annotation)
    candidates = [m for m in members if not (_has_default(info) and m == default)]
    if not candidates:
        raise UnsupportedFieldError(
            f"no Literal member other than the default: {members}"
        )
    return candidates[0]


def base_args(model: type[IPCRequest]) -> dict[str, Any]:
    if model.__pydantic_decorators__.model_validators:
        raise UnsupportedFieldError(
            f"{model.__name__}: a model validator needs a declared valid example"
        )
    return {name: _base_value(info) for name, info in model.model_fields.items()}


def _sized(marker: str, length: int) -> tuple[str, str | None]:
    if length >= len(marker):
        return marker + "x" * (length - len(marker)), marker
    return "x" * length, None


def _wrong_value(json_kind: str, markers: _Markers) -> tuple[Any, str | None]:
    if json_kind == "string":
        marker = markers.next()
        return marker, marker
    values = {
        "int": 7,
        "float": 2.5,
        "bool": False,
        "null": None,
        "array": [],
        "object": {},
    }
    return values[json_kind], None


def _field_variants(
    name: str, info: FieldInfo, base: dict[str, Any], markers: _Markers
) -> list[Variant]:
    kind = _kind(info)
    limits = _constraints(info, kind)
    out: list[Variant] = []

    def one(variant_kind: str, expected: str, value: Any, marker: str | None) -> None:
        out.append(Variant(name, variant_kind, expected, {**base, name: value}, marker))

    if info.is_required():
        args = {k: v for k, v in base.items() if k != name}
        out.append(Variant(name, "missing", "missing", args, None))
    for json_kind in JSON_KINDS:
        if json_kind in ACCEPTED_KINDS[kind]:
            continue
        value, marker = _wrong_value(json_kind, markers)
        one(f"wrong:{json_kind}", WRONG_TYPE[kind], value, marker)
    if kind == "literal":
        marker = markers.next()
        one("literal", "literal_error", marker, marker)
    outside = {
        "ge": lambda b: b - 1,
        "gt": lambda b: b,
        "le": lambda b: b + 1,
        "lt": lambda b: b,
    }
    for constraint in ("ge", "gt", "le", "lt"):
        if constraint in limits:
            value = outside[constraint](limits[constraint])
            one(constraint, CONSTRAINT_TYPE[constraint], value, None)
    if "min_length" in limits:
        value, marker = _sized(markers.next(), limits["min_length"] - 1)
        one("min_length", "string_too_short", value, marker)
    if "max_length" in limits:
        value, marker = _sized(markers.next(), limits["max_length"] + 1)
        one("max_length", "string_too_long", value, marker)
    if kind == "float":
        for label, value in NOT_FINITE:
            one(label, "finite_number", value, None)
    return out


def variants(model: type[IPCRequest], prefix: str) -> list[Variant]:
    markers = _Markers(prefix)
    base = base_args(model)
    if EXTRA_KEY in model.model_fields:
        raise UnsupportedFieldError(f"{model.__name__} has a field named {EXTRA_KEY}")
    out: list[Variant] = []
    for name, info in model.model_fields.items():
        out.extend(_field_variants(name, info, base, markers))
    marker = markers.next()
    out.append(
        Variant(
            EXTRA_KEY, "extra", "extra_forbidden", {**base, EXTRA_KEY: marker}, marker
        )
    )
    marker = markers.next()
    out.append(Variant("args", "not_object:string", "model_type", marker, marker))
    for label, value in (("int", 7), ("array", []), ("null", None)):
        out.append(Variant("args", f"not_object:{label}", "model_type", value, None))
    return out


def inside_values(model: type[IPCRequest]) -> list[Inside]:
    base = base_args(model)
    out: list[Inside] = []
    for name, info in model.model_fields.items():
        kind = _kind(info)
        limits = _constraints(info, kind)
        inside = {
            "ge": lambda b: b,
            "gt": lambda b: b + 1,
            "le": lambda b: b,
            "lt": lambda b: b - 1,
            "min_length": lambda b: "i" * b,
            "max_length": lambda b: "i" * b,
        }
        for constraint, bound in limits.items():
            value = inside[constraint](bound)
            out.append(Inside(name, constraint, {**base, name: value}, value))
    return out


# ── 대상: 등록된 명령과 생성기 표의 픽스처 ─────────────────────────────────


class _TableRequest(IPCRequest):
    title: str
    label: str = "d"
    mode: Literal["fast", "slow"]
    level: int = Field(ge=1, le=5)
    ratio: float
    flag: bool
    code: str = Field(min_length=3)


class _SecretRequest(IPCRequest):
    token: str

    @field_validator("token")
    @classmethod
    def _reject(cls, v: str) -> str:
        raise ValueError(f"bad {v}")


def _registered_specs() -> list[CommandSpec]:
    registry = CommandRegistry()
    register_all_handlers(registry)
    return registry.iter_specs()


def _modeled_specs() -> list[CommandSpec]:
    return [spec for spec in _registered_specs() if spec.request_model is not None]


TABLE_COMMAND = "table.fixture"
TARGETS: list[tuple[str, type[IPCRequest], CommandSpec | None]] = [
    *((spec.name, spec.request_model, spec) for spec in _modeled_specs()),
    (TABLE_COMMAND, _TableRequest, None),
]


def _cases() -> list[Any]:
    cases = []
    for index, (command, model, spec) in enumerate(TARGETS):
        for variant in variants(model, f"{index:02d}"):
            cases.append(
                pytest.param(
                    command,
                    model,
                    spec,
                    variant,
                    id=f"{command}-{variant.loc}-{variant.kind}",
                )
            )
    return cases


def _inside_cases() -> list[Any]:
    return [
        pytest.param(
            command, model, spec, inside, id=f"{command}-{inside.loc}-{inside.kind}"
        )
        for command, model, spec in TARGETS
        for inside in inside_values(model)
    ]


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def __call__(self, svc: Any, request: Any, actor: str) -> dict:
        self.calls.append(request)
        return {"recorded": True}


def _server(
    command: str, model: type[IPCRequest], spec: CommandSpec | None
) -> tuple[IPCServer, _Recorder]:
    recorder = _Recorder()
    registry = CommandRegistry()
    if spec is None:
        registry.register(command, recorder, is_mutating=True, request_model=model)
        required: frozenset[str] = frozenset()
    else:
        kwargs = {
            f.name: getattr(spec, f.name)
            for f in fields(spec)
            if f.name not in {"name", "handler"}
        }
        registry.register(command, recorder, **kwargs)
        required = spec.required_services
    services: dict[str, Any] = {name: MagicMock() for name in required}
    audit = MagicMock()
    audit.log = AsyncMock(return_value=None)
    services["audit_logger"] = audit
    service_registry = cast(ServiceRegistry, SimpleNamespace(**services))
    server = IPCServer("/tmp/unused.sock", service_registry, registry)
    server._state = IPCServerState.RUNNING
    return server, recorder


async def _send(server: IPCServer, command: str, args: Any) -> dict:
    return await server._dispatch(
        {"id": "gen-1", "command": command, "args": args, "actor": "ops-lead"}
    )


# ── 구조와 빈 통과 방지 ─────────────────────────────────────────────────────


def test_request_models_inherit_the_frame_and_its_five_settings() -> None:
    models = [IPCRequest, *(spec.request_model for spec in _modeled_specs())]
    assert len(models) > 1
    for model in models:
        assert model is not None
        assert issubclass(model, IPCRequest), model
        config = {
            key: model.model_config.get(key)
            for key in (
                "extra",
                "strict",
                "allow_inf_nan",
                "hide_input_in_errors",
                "frozen",
            )
        }
        assert config == {
            "extra": "forbid",
            "strict": True,
            "allow_inf_nan": False,
            "hide_input_in_errors": True,
            "frozen": True,
        }, model


def test_targets_are_every_command_outside_the_ratchet_baseline() -> None:
    baseline = set(
        json.loads(BASELINE.read_text(encoding="utf-8"))["ipc_handlers_without_model"]
    )
    registered = {spec.name for spec in _registered_specs()}
    modeled = {spec.name for spec in _modeled_specs()}
    assert modeled
    assert modeled == registered - baseline
    counts = {command: len(variants(model, "00")) for command, model, _ in TARGETS}
    assert all(count > 0 for count in counts.values()), counts
    print(f"request model targets={len(modeled)} variants={counts}")


def test_no_field_without_a_domain() -> None:
    unbounded = {
        (spec.request_model.__name__, name)
        for spec in _modeled_specs()
        if spec.request_model is not None
        for name, info in spec.request_model.model_fields.items()
        if _is_unbounded(info.annotation)
    }
    assert unbounded == UNBOUNDED_FIELDS


# ── 생성기 자체의 표 ─────────────────────────────────────────────────────────


def test_generator_table_for_each_field_kind() -> None:
    got = [(v.loc, v.kind, v.expected) for v in variants(_TableRequest, "00")]
    string_kinds = ("int", "float", "bool", "null", "array", "object")
    assert got == [
        ("title", "missing", "missing"),
        *(("title", f"wrong:{k}", "string_type") for k in string_kinds),
        *(("label", f"wrong:{k}", "string_type") for k in string_kinds),
        ("mode", "missing", "missing"),
        *(("mode", f"wrong:{k}", "literal_error") for k in string_kinds),
        ("mode", "literal", "literal_error"),
        ("level", "missing", "missing"),
        ("level", "wrong:string", "int_type"),
        ("level", "wrong:float", "int_type"),
        ("level", "wrong:bool", "int_type"),
        ("level", "wrong:null", "int_type"),
        ("level", "wrong:array", "int_type"),
        ("level", "wrong:object", "int_type"),
        ("level", "ge", "greater_than_equal"),
        ("level", "le", "less_than_equal"),
        ("ratio", "missing", "missing"),
        ("ratio", "wrong:string", "float_type"),
        ("ratio", "wrong:bool", "float_type"),
        ("ratio", "wrong:null", "float_type"),
        ("ratio", "wrong:array", "float_type"),
        ("ratio", "wrong:object", "float_type"),
        ("ratio", "nan", "finite_number"),
        ("ratio", "inf", "finite_number"),
        ("ratio", "-inf", "finite_number"),
        ("flag", "missing", "missing"),
        ("flag", "wrong:string", "bool_type"),
        ("flag", "wrong:int", "bool_type"),
        ("flag", "wrong:float", "bool_type"),
        ("flag", "wrong:null", "bool_type"),
        ("flag", "wrong:array", "bool_type"),
        ("flag", "wrong:object", "bool_type"),
        ("code", "missing", "missing"),
        *(("code", f"wrong:{k}", "string_type") for k in string_kinds),
        ("code", "min_length", "string_too_short"),
        ("zz_extra", "extra", "extra_forbidden"),
        ("args", "not_object:string", "model_type"),
        ("args", "not_object:int", "model_type"),
        ("args", "not_object:array", "model_type"),
        ("args", "not_object:null", "model_type"),
    ]
    assert base_args(_TableRequest) == {
        "title": "v",
        "label": "v",
        "mode": "fast",
        "level": 1,
        "ratio": 1.5,
        "flag": True,
        "code": "vvv",
    }
    assert [(i.loc, i.kind, i.value) for i in inside_values(_TableRequest)] == [
        ("level", "ge", 1),
        ("level", "le", 5),
        ("code", "min_length", "iii"),
    ]


def test_generator_one_change_per_variant() -> None:
    base = base_args(_TableRequest)
    for variant in variants(_TableRequest, "00"):
        if variant.loc == "args":
            assert not isinstance(variant.args, dict), variant
            continue
        changed = {
            key
            for key in {*base, *variant.args}
            if base.get(key, ...) != variant.args.get(key, ...)
            or (key in base) != (key in variant.args)
        }
        assert changed == {variant.loc}, variant


def test_generator_rejects_fields_it_cannot_bound() -> None:
    class _Open(IPCRequest):
        anything: Any

    class _Mapping(IPCRequest):
        values: dict[str, Any]

    class _Listed(IPCRequest):
        items: list[str]

    class _Patterned(IPCRequest):
        name: str = Field(pattern="^a+$")

    for model in (_Open, _Mapping, _Listed, _Patterned):
        with pytest.raises(UnsupportedFieldError):
            variants(model, "00")


# ── 실제 _dispatch로 판정 ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "model", "spec"), TARGETS, ids=[t[0] for t in TARGETS]
)
async def test_base_args_reach_the_handler_as_the_model(
    command: str, model: type[IPCRequest], spec: CommandSpec | None
) -> None:
    server, recorder = _server(command, model, spec)
    base = base_args(model)
    response = await _send(server, command, base)
    assert response == {"id": "gen-1", "status": "ok", "result": {"recorded": True}}
    assert len(recorder.calls) == 1
    assert type(recorder.calls[0]) is model
    assert recorder.calls[0].model_dump() == base


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "model", "spec", "inside"), _inside_cases())
async def test_value_inside_a_bound_is_accepted(
    command: str, model: type[IPCRequest], spec: CommandSpec | None, inside: Inside
) -> None:
    server, recorder = _server(command, model, spec)
    response = await _send(server, command, inside.args)
    assert response["status"] == "ok", response
    assert getattr(recorder.calls[0], inside.loc) == inside.value


@pytest.mark.asyncio
@pytest.mark.parametrize(("command", "model", "spec", "variant"), _cases())
async def test_value_outside_the_domain_is_rejected(
    command: str,
    model: type[IPCRequest],
    spec: CommandSpec | None,
    variant: Variant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    server, recorder = _server(command, model, spec)
    response = await _send(server, command, variant.args)
    assert response == {
        "id": "gen-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": f"{command} 인자 검증 실패: {variant.loc}({variant.expected})",
        },
    }
    assert recorder.calls == []
    assert "RequestValidationError" in caplog.text
    if variant.marker is not None:
        assert variant.marker not in json.dumps(response, ensure_ascii=False)
        assert variant.marker not in caplog.text


@pytest.mark.asyncio
async def test_user_validator_message_does_not_reflect_the_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "MARKUSER001SECRET"
    server, recorder = _server("demo.secret", _SecretRequest, None)
    response = await _send(server, "demo.secret", {"token": marker})
    assert response == {
        "id": "gen-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "demo.secret 인자 검증 실패: token(value_error)",
        },
    }
    assert recorder.calls == []
    assert "IPC 커맨드 실행 오류: demo.secret" in caplog.text
    assert "RequestValidationError" in caplog.text
    assert marker not in json.dumps(response, ensure_ascii=False)
    assert marker not in caplog.text
