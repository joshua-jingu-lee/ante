"""GET /api/data/datasets/{dataset_id} 데이터셋 상세 API 테스트."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.data.store import ParquetStore  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


def _make_ohlcv_df(n: int = 10) -> pl.DataFrame:
    timestamps = pl.datetime_range(
        datetime(2026, 3, 1, 9, 0),
        datetime(2026, 3, 1, 9, n - 1),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    count = len(timestamps)
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": ["005930"] * count,
            "open": [50000.0 + i for i in range(count)],
            "high": [50100.0] * count,
            "low": [49900.0] * count,
            "close": [50050.0] * count,
            "volume": [1000] * count,
            "source": ["test"] * count,
        }
    )


def _make_fundamental_df() -> pl.DataFrame:
    from datetime import date

    return pl.DataFrame(
        {
            "date": [date(2026, 3, 1), date(2026, 3, 2)],
            "symbol": ["005930", "005930"],
            "market_cap": [400_000_000_000, 401_000_000_000],
            "per": [12.5, 12.6],
            "pbr": [1.2, 1.3],
            "source": ["test", "test"],
        }
    )


@pytest.fixture
def store(tmp_path):
    return ParquetStore(base_path=tmp_path / "data")


@pytest.fixture
def client(store):
    app = create_app(data_store=store, member_service=make_master_member_service())
    return make_authed_client(app)


class TestDatasetDetail:
    """GET /api/data/datasets/{dataset_id} 상세 조회 테스트."""

    async def test_basic_response_structure(self, client, store):
        """응답이 dataset + preview 구조를 갖는다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        assert resp.status_code == 200
        body = resp.json()
        assert "dataset" in body
        assert "preview" in body

    async def test_metadata_fields(self, client, store):
        """메타데이터에 필수 필드가 모두 포함된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        ds = resp.json()["dataset"]
        assert ds["id"] == "005930__1d"
        assert ds["symbol"] == "005930"
        assert ds["timeframe"] == "1d"
        assert ds["data_type"] == "ohlcv"
        assert ds["start_date"] is not None
        assert ds["end_date"] is not None
        assert isinstance(ds["row_count"], int)
        assert ds["row_count"] > 0

    async def test_preview_limit_5(self, client, store):
        """미리보기는 최대 5행을 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df(n=10))
        resp = client.get("/api/data/datasets/005930__1d")
        preview = resp.json()["preview"]
        assert len(preview) == 5

    async def test_preview_less_than_5(self, client, store):
        """데이터가 5행 미만이면 전체를 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df(n=3))
        resp = client.get("/api/data/datasets/005930__1d")
        preview = resp.json()["preview"]
        assert len(preview) == 3

    async def test_preview_contains_ohlcv_fields(self, client, store):
        """미리보기 행에 OHLCV 필드가 포함된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        row = resp.json()["preview"][0]
        for field in ("timestamp", "open", "high", "low", "close", "volume"):
            assert field in row, f"missing field: {field}"

    async def test_preview_serializes_datetime(self, client, store):
        """datetime이 ISO 문자열로 직렬화된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        row = resp.json()["preview"][0]
        assert isinstance(row["timestamp"], str)

    def test_not_found(self, client):
        """존재하지 않는 dataset_id는 404를 반환한다."""
        resp = client.get("/api/data/datasets/999999__1d")
        assert resp.status_code == 404

    def test_invalid_id_format(self, client):
        """잘못된 dataset_id 형식은 400을 반환한다."""
        resp = client.get("/api/data/datasets/invalid_format")
        assert resp.status_code == 400

    def test_store_unavailable(self):
        """store가 None이면 503을 반환한다."""
        app = create_app(data_store=None, member_service=make_master_member_service())
        c = make_authed_client(app)
        resp = c.get("/api/data/datasets/005930__1d")
        assert resp.status_code == 503

    async def test_fundamental_dataset_detail(self, client, store):
        """fundamental 데이터셋 상세 조회."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets/005930__fundamental")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset"]["data_type"] == "fundamental"
        assert body["dataset"]["symbol"] == "005930"
        assert len(body["preview"]) > 0


class TestDatasetDetailPathTraversal:
    """GET /api/data/datasets/{dataset_id} path traversal 방어 (#1631).

    `..__1d`(symbol=`..`) 등이 parent 디렉토리를 정상 dataset으로 해석해
    200을 반환하던 보안 결함을 400으로 거부하는지 검증한다.
    """

    def test_parent_traversal_symbol_rejected(self, client, store):
        """원 재현 벡터: `..__1d` (symbol=`..`) → 400 (200 아님)."""
        # parent를 leaf로 해석하지 못하도록, parent dir이 실제 존재해도
        # 거부되어야 한다.
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/..__1d")
        assert resp.status_code == 400, (
            f"path traversal `..__1d`가 거부되지 않음: {resp.status_code}"
        )

    @pytest.mark.parametrize(
        "dataset_id",
        [
            "..__1d",
            "005930__..",
            "005930__.",
            ".__1d",
        ],
    )
    def test_no_slash_traversal_variants_rejected_400(self, client, dataset_id):
        """slash 없는 traversal 변형(`..`/`.`) → ingress 400."""
        resp = client.get(f"/api/data/datasets/{dataset_id}")
        assert resp.status_code == 400, (
            f"traversal 변형 거부 실패: {dataset_id} → {resp.status_code}"
        )

    def test_url_encoded_dotdot_decoded_and_rejected_400(self, client):
        """URL-encoded `%2e%2e`(slash 없음) → decode 후 ingress 400."""
        resp = client.get("/api/data/datasets/%2e%2e__1d")
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "dataset_id",
        [
            "../../x__1d",
            "a/b__1d",
            "005930__../../x",
            "005930__a/b",
        ],
    )
    def test_slash_bearing_traversal_unreachable(self, client, dataset_id):
        """slash 포함 입력은 path param이 `/`를 캡처하지 않아 라우트 자체가
        매치되지 않음 → handler 도달 불가(404, 200 아님).

        400을 강제하려면 catch-all 라우트/path-scheme 변경이 필요한데 이는
        Non-Goal(`_resolve_path` 경로 스킴 구조 변경 금지). 200/메타데이터
        노출이 발생하지 않는 것이 보안 불변.
        """
        resp = client.get(f"/api/data/datasets/{dataset_id}")
        assert resp.status_code != 200, (
            f"slash traversal이 200으로 노출됨: {dataset_id}"
        )
        assert resp.status_code in (400, 404)

    @pytest.mark.parametrize(
        "raw_path",
        [
            "/api/data/datasets/005930__%2e%2e%2f%2e%2e%2fx",
            "/api/data/datasets/%2e%2e%2f%2e%2e%2fx__1d",
            "/api/data/datasets/%2fetc%2fpasswd__1d",
        ],
    )
    def test_url_encoded_slash_traversal_not_exposed(self, client, raw_path):
        """URL-encoded slash(`%2f`) 포함 → 200 노출 안 됨(라우트 미매치)."""
        resp = client.get(raw_path)
        assert resp.status_code != 200, (
            f"URL-encoded slash traversal이 200으로 노출됨: {raw_path}"
        )
        assert resp.status_code in (400, 404)

    async def test_legacy_non_6digit_symbol_not_rejected(self, client, store):
        """legacy out-of-vocab symbol(6자리 외, path-safe)은 400 아님.

        `ABCDEF__1d`/`oracle-safe-symbol__1d`는 path-safe이므로 존재 시
        정상 200, 미존재 시 404 — spec 05:76 legacy 호환 보존.
        """
        store.write("ABCDEF", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/ABCDEF__1d")
        assert resp.status_code == 200
        assert resp.json()["dataset"]["symbol"] == "ABCDEF"

        # hyphen 포함 legacy symbol 디렉토리도 path-safe → 정상 동작
        legacy_dir = store.base_path / "ohlcv" / "1d" / "KRX" / "oracle-safe-symbol"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        resp2 = client.get("/api/data/datasets/oracle-safe-symbol__1d")
        assert resp2.status_code != 400, (
            f"legacy path-safe symbol이 400으로 회귀: {resp2.status_code}"
        )

    def test_legacy_missing_symbol_404_not_400(self, client):
        """미존재 legacy path-safe symbol → 404 (400 아님)."""
        resp = client.get("/api/data/datasets/ABCDEF__1d")
        assert resp.status_code == 404
