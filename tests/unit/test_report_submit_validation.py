"""POST /api/reports 입력 검증 테스트 (#1353).

SSOT:
- ``docs/specs/report-store/report-store.md`` — ``"win_rate": 58.0`` (percent 0~100).
- ``src/ante/web/schemas.py::ReportSubmitRequest``.

검증 대상:
- ``total_trades >= 0`` (음수 거부).
- ``win_rate`` percent 단위 0.0~100.0 (out-of-range 거부, ``None`` 허용).
- 4개 metric (``total_return_pct``, ``sharpe_ratio``, ``max_drawdown_pct``,
  ``win_rate``)은 finite (NaN/Inf 거부).
- ``extra="forbid"``로 미지정 키 거부.

Note: 단위 통일(percent ↔ ratio)은 본 PR에서 다루지 않고 별도 follow-up
이슈에서 처리한다 (detail_json/backtest_runs/CLI submit 등 광범위 영향).
"""

from __future__ import annotations

from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def report_store(db):
    from ante.report.store import ReportStore

    store = ReportStore(db)
    await store.initialize()
    return store


@pytest.fixture
def app(report_store):
    return create_app(report_store=report_store)


@pytest.fixture
def client(app):
    return TestClient(app)


def _base_payload(**overrides: Any) -> dict[str, Any]:
    """제출 요청의 기본 payload. 케이스별 override만 적용한다."""
    payload: dict[str, Any] = {
        "strategy_name": "validation_probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/probe.py",
        "backtest_period": "2024-01 ~ 2026-03",
        "total_return_pct": 0.0,
        "total_trades": 0,
        "summary": "validation probe",
        "rationale": "ensure invalid metrics are rejected",
        "detail_json": "{}",
    }
    payload.update(overrides)
    return payload


# ── total_trades ──────────────────────────────────────────


class TestTotalTradesValidation:
    def test_negative_rejected(self, client: TestClient) -> None:
        """``total_trades=-1`` → 422 (거래 수는 음수 불가)."""
        res = client.post("/api/reports", json=_base_payload(total_trades=-1))
        assert res.status_code == 422

    @pytest.mark.parametrize("value", [0, 1, 1000])
    def test_non_negative_accepted(self, client: TestClient, value: int) -> None:
        """``total_trades >= 0``는 정상 처리 (201)."""
        res = client.post("/api/reports", json=_base_payload(total_trades=value))
        assert res.status_code == 201


# ── win_rate ───────────────────────────────────────────────


class TestWinRateValidation:
    @pytest.mark.parametrize("value", [150.0, -0.1])
    def test_out_of_percent_range_rejected(
        self, client: TestClient, value: float
    ) -> None:
        """percent 단위 (0.0~100.0) 범위 밖 값 거부."""
        res = client.post("/api/reports", json=_base_payload(win_rate=value))
        assert res.status_code == 422

    @pytest.mark.parametrize("value", [0.0, 1.5, 50.0, 100.0])
    def test_in_range_accepted(self, client: TestClient, value: float) -> None:
        """percent 단위 (0.0~100.0) 범위 내 값은 정상 처리."""
        res = client.post("/api/reports", json=_base_payload(win_rate=value))
        assert res.status_code == 201

    def test_null_accepted(self, client: TestClient) -> None:
        """``win_rate=null``은 옵션 필드로 허용."""
        res = client.post("/api/reports", json=_base_payload(win_rate=None))
        assert res.status_code == 201


# ── finite (NaN/Inf 거부) ──────────────────────────────────


class TestFiniteValidation:
    """4개 metric 필드는 NaN/Inf 거부 (allow_inf_nan=False).

    JSON spec은 NaN/Inf를 허용하지 않지만 Python json 모듈은 ``allow_nan=True``
    기본값으로 ``NaN``/``Infinity`` 토큰을 직렬화한다. FastAPI의 기본 디코더도
    이 토큰을 ``float('nan')``/``float('inf')``로 파싱하므로 Pydantic 단의
    ``allow_inf_nan=False`` 검증이 SSOT다.
    """

    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate"],
    )
    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_rejected(
        self,
        client: TestClient,
        field: str,
        token: str,
    ) -> None:
        """NaN/Inf 토큰을 가진 metric 값은 422로 거부."""
        # Python json은 allow_nan=True 기본이므로 raw body로 비표준 토큰을 보낸다.
        payload = _base_payload()
        payload[field] = 0.0  # placeholder — 곧 raw로 치환
        # Build raw JSON body manually to inject NaN/Infinity tokens.
        import json

        body = json.dumps(payload)
        # field 의 placeholder 0.0 을 비표준 token 으로 치환
        body = body.replace(f'"{field}": 0.0', f'"{field}": {token}', 1)
        res = client.post(
            "/api/reports",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 422, (
            f"{field}={token} 은 422로 거부되어야 함 (got {res.status_code}): "
            f"{res.text}"
        )


# ── extra="forbid" ─────────────────────────────────────────


class TestExtraForbid:
    def test_unknown_key_rejected(self, client: TestClient) -> None:
        """미지정 키(``foo``)는 ``extra='forbid'``로 422 거부."""
        res = client.post("/api/reports", json=_base_payload(foo="bar"))
        assert res.status_code == 422
