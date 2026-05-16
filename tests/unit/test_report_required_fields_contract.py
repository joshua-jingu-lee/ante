"""report submit required-fields contract 회귀 테스트 (#1625).

oracle A7 host probe ``report_required_fields_contract`` 가 검출한
contract-drift 를 회귀 보호한다:

`/api/reports/schema` 와 ``ReportStore.get_schema()`` 는 ``backtest_period``,
``total_return_pct``, ``total_trades``, ``summary``, ``rationale`` 를 required
field 로 노출하지만, 이전까지 ``ReportSubmitRequest`` 가 이 5필드를 기본값으로
선언하여 API ``POST /api/reports`` (201) 와 CLI ``ante report submit`` (exit 0)
양쪽이 누락 payload 를 성공 처리했다.

본 모듈은 다음을 검증한다:

1. ``ReportStore.get_schema()["required_fields"]`` (모델 외부 필드 제외) 가
   ``ReportSubmitRequest`` 의 required 필드 집합 (``model_fields`` 중
   ``is_required()``) 과 **양방향 동치** — 재-drift SSOT 락.
2. probe payload (``strategy_name``/``strategy_version``/``strategy_path`` 만)
   → API 422 (``application/problem+json`` ``type=/errors/validation``) /
   CLI exit 1 (stdout ``REPORT_VALIDATION_ERROR``).
3. 5필드 **각각 단독 누락** × {API, CLI} → 거부.
4. 8필드 완비 payload → API 201 / CLI exit 0 (정상 회귀).
5. ``extra='forbid'`` + required 상호작용 (미지정 required + unknown key
   동시) → 422 / exit 1.

SSOT:
- ``docs/specs/report-store/report-store.md`` (제출 스키마 required_fields)
- ``src/ante/report/store.py::ReportStore.get_schema``
- ``src/ante/web/schemas.py::ReportSubmitRequest``

Note (#1625 narrow-scope): 본 모듈은 API/CLI submit boundary 만 검증한다.
``ReportStore.submit``/``StrategyReport``/draft 등 ``ReportSubmitRequest``
미경유 쓰기 경로의 persistence invariant 는 후속 후보 B 영역이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.report.store import ReportStore
from ante.web.schemas import ReportSubmitRequest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# #1625 가 required 화하는 5필드. ``strategy_name``/``strategy_version``/
# ``strategy_path`` 는 이전부터 required 였으므로 본 회귀의 대상이 아니다.
_DRIFTED_REQUIRED_FIELDS = (
    "backtest_period",
    "total_return_pct",
    "total_trades",
    "summary",
    "rationale",
)

# ``get_schema()["required_fields"]`` 에는 있으나 ``ReportSubmitRequest`` 에는
# 없는 모델 외부 필드. 동치 비교 시 schema 측에서 제외한다 (현재는 없음 —
# 미래 drift 방지를 위해 명시적으로 둔다).
_MODEL_EXTERNAL_REQUIRED_FIELDS: frozenset[str] = frozenset()


# ── get_schema ⟺ model required-set 동치 (재-drift SSOT 락) ──────────────


class TestSchemaModelRequiredSetEquivalence:
    """``ReportStore.get_schema()`` 의 required_fields 와
    ``ReportSubmitRequest`` 의 required 필드 집합이 양방향 동치임을 검증한다.

    어느 한쪽만 변경되면 (모델 default 재추가 / spec required 변경) 본
    테스트가 실패하여 contract-drift 가 재발하지 못하도록 락을 건다.
    """

    def _model_required(self) -> set[str]:
        return {
            name
            for name, info in ReportSubmitRequest.model_fields.items()
            if info.is_required()
        }

    def _schema_required(self) -> set[str]:
        required = set(ReportStore.get_schema()["required_fields"])
        return required - _MODEL_EXTERNAL_REQUIRED_FIELDS

    def test_required_sets_are_equivalent(self) -> None:
        """schema required (모델 외부 제외) == 모델 required (양방향)."""
        assert self._schema_required() == self._model_required()

    def test_drifted_five_fields_are_required_in_model(self) -> None:
        """#1625 가 required 화한 5필드가 모델에서 실제 required."""
        model_required = self._model_required()
        for name in _DRIFTED_REQUIRED_FIELDS:
            assert name in model_required, f"{name} 은 required 여야 한다"

    def test_drifted_five_fields_not_optional(self) -> None:
        """5필드는 ``Optional`` 이 아니어야 한다 (Pydantic ``Field()`` no
        default = required, ``| None`` 추가 금지)."""
        for name in _DRIFTED_REQUIRED_FIELDS:
            info = ReportSubmitRequest.model_fields[name]
            assert info.is_required(), f"{name} 은 required 여야 한다"

    def test_guards_preserved(self) -> None:
        """``total_trades >= 0`` / metric ``allow_inf_nan=False`` 가드 보존."""
        # ge 가드 유지: total_trades=-1 거부.
        with pytest.raises(ValueError):
            ReportSubmitRequest.model_validate(_full_payload(total_trades=-1))
        # allow_inf_nan=False 유지: total_return_pct=inf 거부.
        with pytest.raises(ValueError):
            ReportSubmitRequest.model_validate(
                _full_payload(total_return_pct=float("inf"))
            )


# ── payload 헬퍼 ──────────────────────────────────────────────


def _full_payload(**overrides: Any) -> dict[str, Any]:
    """8필드 완비 payload (정상 제출 가능)."""
    payload: dict[str, Any] = {
        "strategy_name": "required_contract_probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/required_contract_probe.py",
        "backtest_period": "2024-01 ~ 2026-03",
        "total_return_pct": 12.5,
        "total_trades": 7,
        "summary": "required-fields contract probe",
        "rationale": "ensure schema-required fields are enforced at submit",
        "detail_json": "{}",
    }
    payload.update(overrides)
    return payload


def _probe_payload() -> dict[str, Any]:
    """oracle probe payload — strategy_* 만 포함, 5필드 모두 누락."""
    return {
        "strategy_name": "required_contract_probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/required_contract_probe.py",
    }


# ── API fixtures (#1374 인증: master Bearer) ────────────────────


@dataclass
class _FakeMember:
    member_id: str
    type: str = "human"
    role: str = "master"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _FakeMemberService:
    """``require_report_write`` dependency 를 통과시키는 최소 stub."""

    def __init__(self) -> None:
        self._members: dict[str, _FakeMember] = {
            "master-user": _FakeMember(member_id="master-user"),
        }
        self._tokens: dict[str, str] = {"master-token": "master-user"}

    async def authenticate(self, token: str) -> _FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _FakeMember | None:
        return self._members.get(member_id)


_AUTH_HEADERS: dict[str, str] = {"Authorization": "Bearer master-token"}


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def report_store(db):
    store = ReportStore(db)
    await store.initialize()
    return store


@pytest.fixture
def app(report_store):
    return create_app(report_store=report_store, member_service=_FakeMemberService())


@pytest.fixture
def client(app):
    return TestClient(app)


# ── API: probe payload → 422 problem+json ──────────────────────


class TestApiRequiredFieldsRejection:
    def test_probe_payload_rejected_422_problem_json(self, client: TestClient) -> None:
        """probe payload (strategy_* 만) → 422 problem+json
        ``type=/errors/validation``."""
        res = client.post(
            "/api/reports",
            json=_probe_payload(),
            headers=_AUTH_HEADERS,
        )
        assert res.status_code == 422, res.text
        assert res.headers["content-type"] == "application/problem+json"
        body = res.json()
        assert body["type"] == "/errors/validation"
        assert body["status"] == 422

    @pytest.mark.parametrize("missing", _DRIFTED_REQUIRED_FIELDS)
    def test_each_field_single_omission_rejected(
        self, client: TestClient, missing: str
    ) -> None:
        """5필드 각각 단독 누락 → 422 (다른 7필드는 완비)."""
        payload = _full_payload()
        del payload[missing]
        res = client.post("/api/reports", json=payload, headers=_AUTH_HEADERS)
        assert res.status_code == 422, (
            f"{missing} 누락은 422 로 거부되어야 한다 (got {res.status_code}): "
            f"{res.text}"
        )
        assert res.headers["content-type"] == "application/problem+json"

    def test_full_payload_accepted_201(self, client: TestClient) -> None:
        """8필드 완비 payload → 201 (정상 회귀)."""
        res = client.post(
            "/api/reports",
            json=_full_payload(),
            headers=_AUTH_HEADERS,
        )
        assert res.status_code == 201, res.text

    def test_missing_required_plus_unknown_key_rejected(
        self, client: TestClient
    ) -> None:
        """``extra='forbid'`` + required 상호작용: 미지정 required(summary)
        누락 + unknown key 동시 → 422."""
        payload = _full_payload(unexpected_key="x")
        del payload["summary"]
        res = client.post("/api/reports", json=payload, headers=_AUTH_HEADERS)
        assert res.status_code == 422, res.text
        assert res.headers["content-type"] == "application/problem+json"


# ── CLI fixtures ───────────────────────────────────────────────

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """auth bypass 가 적용된 CliRunner (test_cli_report_submit_invariant 패턴)."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _write_payload(tmp_path, payload: dict[str, Any]) -> str:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(payload))
    return str(p)


def _invoke_submit(runner: CliRunner, tmp_path, json_path: str) -> Any:
    db_path = str(tmp_path / "test.db")
    return runner.invoke(
        cli,
        ["--format", "json", "report", "submit", json_path, "--db-path", db_path],
    )


# ── CLI: probe payload → exit 1 REPORT_VALIDATION_ERROR ─────────


class TestCliRequiredFieldsRejection:
    def test_probe_payload_rejected_exit1(self, runner, tmp_path) -> None:
        """probe payload → exit 1 + JSON ``code=REPORT_VALIDATION_ERROR``."""
        path = _write_payload(tmp_path, _probe_payload())
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["status"] == "error"
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    @pytest.mark.parametrize("missing", _DRIFTED_REQUIRED_FIELDS)
    def test_each_field_single_omission_rejected(
        self, runner, tmp_path, missing: str
    ) -> None:
        """5필드 각각 단독 누락 → exit 1 (다른 7필드 완비)."""
        payload = _full_payload()
        del payload[missing]
        path = _write_payload(tmp_path, payload)
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 1, (
            f"{missing} 누락은 exit 1 이어야 한다: {result.output}"
        )
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    def test_full_payload_accepted_exit0(self, runner, tmp_path) -> None:
        """8필드 완비 payload → exit 0 (정상 회귀)."""
        path = _write_payload(tmp_path, _full_payload())
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output

    def test_missing_required_plus_unknown_key_rejected(self, runner, tmp_path) -> None:
        """``extra='forbid'`` + required 상호작용 → exit 1."""
        payload = _full_payload(unexpected_key="x")
        del payload["rationale"]
        path = _write_payload(tmp_path, payload)
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"
