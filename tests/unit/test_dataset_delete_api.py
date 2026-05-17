"""데이터셋 API 테스트 — 목록 조회(페이지네이션·필터) 및 삭제."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import polars as pl
import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.data.store import ParquetStore  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


def _make_ohlcv_df() -> pl.DataFrame:
    timestamps = pl.datetime_range(
        datetime(2026, 3, 1, 9, 0),
        datetime(2026, 3, 1, 9, 2),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    n = len(timestamps)
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": ["005930"] * n,
            "open": [50000.0] * n,
            "high": [50100.0] * n,
            "low": [49900.0] * n,
            "close": [50050.0] * n,
            "volume": [1000] * n,
            "source": ["test"] * n,
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


class TestListDatasets:
    """GET /api/data/datasets — 응답 형식·필드·페이지네이션·필터 검증."""

    async def test_response_wrapper_format(self, client, store):
        """응답이 {items, total} 래퍼를 사용한다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 1
        assert len(body["items"]) == 1

    async def test_field_names(self, client, store):
        """각 데이터셋에 id, start_date, end_date, row_count 필드가 있다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets")
        ds = resp.json()["items"][0]
        assert ds["id"] == "005930__1d"
        assert ds["symbol"] == "005930"
        assert ds["timeframe"] == "1d"
        assert "start_date" in ds
        assert "end_date" in ds
        assert isinstance(ds["row_count"], int)
        # 목록 API에서는 성능상 row_count=0을 반환 (#950), 상세 조회에서만 실제 값
        assert ds["row_count"] == 0

    async def test_pagination(self, client, store):
        """offset/limit 파라미터로 페이지네이션이 동작한다."""
        for sym in ["000010", "000020", "000030"]:
            store.write(sym, "1d", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"offset": 0, "limit": 2})
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

        resp2 = client.get("/api/data/datasets", params={"offset": 2, "limit": 2})
        body2 = resp2.json()
        assert body2["total"] == 3
        assert len(body2["items"]) == 1

    async def test_filter_by_symbol(self, client, store):
        """symbol 필터로 특정 종목만 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df())
        store.write("035720", "1d", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"symbol": "005930"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["symbol"] == "005930"

    async def test_filter_by_timeframe(self, client, store):
        """timeframe 필터로 특정 타임프레임만 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df())
        store.write("005930", "1h", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"timeframe": "1d"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["timeframe"] == "1d"

    def test_empty_store(self, client):
        """데이터가 없으면 빈 목록과 total=0을 반환한다."""
        resp = client.get("/api/data/datasets")
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


class TestDeleteDataset:
    async def test_delete_success(self, client, store):
        """데이터셋 삭제 성공."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.delete("/api/data/datasets/005930__1d")
        assert resp.status_code == 204

    def test_delete_nonexistent(self, client):
        """존재하지 않는 데이터셋 → 404."""
        resp = client.delete("/api/data/datasets/999999__1d")
        assert resp.status_code == 404

    def test_delete_invalid_id_format(self, client):
        """잘못된 dataset_id 형식 → 400."""
        resp = client.delete("/api/data/datasets/invalid_format")
        assert resp.status_code == 400

    async def test_datasets_empty_after_delete(self, client, store):
        """삭제 후 목록에서 제거 확인."""
        store.write("005930", "1d", _make_ohlcv_df())
        client.delete("/api/data/datasets/005930__1d")
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_delete_invalid_data_type_rejected(self, client):
        """enum 외 data_type 값은 422 (#1438).

        과거에는 unknown 값이 ohlcv 경로로 fallback 되어 404 가 반환되었다.
        Literal narrowing 이후 ingress 에서 거부되어야 한다.
        """
        resp = client.delete(
            "/api/data/datasets/005930__1d",
            params={"data_type": "oracle_invalid_type"},
        )
        assert resp.status_code == 422

    def test_delete_empty_data_type_rejected(self, client):
        """빈 문자열 data_type 은 422 (#1438)."""
        resp = client.delete(
            "/api/data/datasets/005930__1d",
            params={"data_type": ""},
        )
        assert resp.status_code == 422

    async def test_delete_default_data_type_ohlcv(self, client, store):
        """data_type 미지정 시 기본 ohlcv 회귀 (#1438)."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.delete("/api/data/datasets/005930__1d")
        assert resp.status_code == 204

    def test_delete_ohlcv_explicit_data_type(self, client):
        """data_type=ohlcv 명시 시 기존 404 회귀 (#1438)."""
        resp = client.delete(
            "/api/data/datasets/999999__1d",
            params={"data_type": "ohlcv"},
        )
        assert resp.status_code == 404

    def test_delete_fundamental_explicit_data_type(self, client):
        """data_type=fundamental 명시 시 기존 404 회귀 (#1438)."""
        resp = client.delete(
            "/api/data/datasets/999999__fundamental",
            params={"data_type": "fundamental"},
        )
        assert resp.status_code == 404


class TestDeleteDatasetPathTraversal:
    """DELETE /api/data/datasets/{dataset_id} path traversal 방어 (#1631).

    `..__1d` 등이 `shutil.rmtree`로 의도 디렉토리 밖을 삭제하던 destructive
    결함을 400으로 거부하고 rmtree가 호출되지 않는지 검증한다.
    """

    def test_parent_traversal_rejected_and_rmtree_not_called(self, client, store):
        """`..__1d` → 400 + `shutil.rmtree` 미호출."""
        store.write("005930", "1d", _make_ohlcv_df())
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete("/api/data/datasets/..__1d")
        assert resp.status_code == 400, (
            f"path traversal `..__1d` DELETE가 거부되지 않음: {resp.status_code}"
        )
        mock_rmtree.assert_not_called()

    @pytest.mark.parametrize(
        "dataset_id",
        [
            "..__1d",
            "005930__..",
            "005930__.",
            ".__1d",
        ],
    )
    def test_no_slash_traversal_rejected_400_no_rmtree(self, client, dataset_id):
        """slash 없는 traversal(`..`/`.`) → ingress 400 + rmtree 미호출."""
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete(f"/api/data/datasets/{dataset_id}")
        assert resp.status_code == 400, (
            f"traversal 변형 DELETE 거부 실패: {dataset_id} → {resp.status_code}"
        )
        mock_rmtree.assert_not_called()

    def test_url_encoded_dotdot_decoded_rejected_400_no_rmtree(self, client):
        """URL-encoded `%2e%2e`(slash 없음) → decode 후 400 + rmtree 미호출."""
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete("/api/data/datasets/%2e%2e__1d")
        assert resp.status_code == 400
        mock_rmtree.assert_not_called()

    @pytest.mark.parametrize(
        "dataset_id",
        [
            "../../x__1d",
            "a/b__1d",
            "005930__../../x",
            "005930__a/b",
        ],
    )
    def test_slash_bearing_traversal_unreachable_no_rmtree(self, client, dataset_id):
        """slash 포함 입력은 라우트 미매치로 handler 도달 불가 → rmtree
        절대 미호출(404/400, destructive 코드 구조적 도달 불가).

        400 강제는 catch-all 라우트/path-scheme 변경 필요 — Non-Goal.
        보안 불변: rmtree 미호출 + 204 아님.
        """
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete(f"/api/data/datasets/{dataset_id}")
        assert resp.status_code != 204, f"slash traversal DELETE가 성공함: {dataset_id}"
        assert resp.status_code in (400, 404)
        mock_rmtree.assert_not_called()

    @pytest.mark.parametrize(
        "raw_path",
        [
            "/api/data/datasets/005930__%2e%2e%2f%2e%2e%2fx",
            "/api/data/datasets/%2e%2e%2f%2e%2e%2fx__1d",
            "/api/data/datasets/%2fetc%2fpasswd__1d",
        ],
    )
    def test_url_encoded_slash_traversal_no_rmtree(self, client, raw_path):
        """URL-encoded slash(`%2f`) 포함 → rmtree 미호출 + 204 아님."""
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete(raw_path)
        assert resp.status_code != 204
        assert resp.status_code in (400, 404)
        mock_rmtree.assert_not_called()

    async def test_legacy_non_6digit_symbol_not_rejected(self, client, store):
        """legacy out-of-vocab symbol(path-safe)은 400 아님 — 정상 삭제.

        spec 05:76 legacy 호환 보존.
        """
        store.write("ABCDEF", "1d", _make_ohlcv_df())
        resp = client.delete("/api/data/datasets/ABCDEF__1d")
        assert resp.status_code == 204, (
            f"legacy path-safe symbol DELETE가 회귀: {resp.status_code}"
        )

    def test_legacy_missing_symbol_404_not_400(self, client):
        """미존재 legacy path-safe symbol DELETE → 404 (400 아님)."""
        resp = client.delete("/api/data/datasets/ABCDEF__1d")
        assert resp.status_code == 404


class TestDeleteDatasetDataTypeContract:
    """DELETE `data_type` ↔ dataset_id timeframe segment 일치 계약 (#1631).

    kind SSOT = dataset_id timeframe segment. data_type query 생략 시 파생값
    사용, 명시 시 파생값과 불일치하면 400(rmtree 오삭제 방지).
    """

    # ── omitted: 파생값 사용 ──
    async def test_omitted_fundamental_segment_uses_fundamental(self, client, store):
        """`005930__fundamental` (query 생략) → fundamental 정상 삭제."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.delete("/api/data/datasets/005930__fundamental")
        assert resp.status_code == 204
        listing = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert listing.json()["items"] == []

    async def test_omitted_ohlcv_segment_uses_ohlcv(self, client, store):
        """`005930__1d` (query 생략) → ohlcv 정상 삭제."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.delete("/api/data/datasets/005930__1d")
        assert resp.status_code == 204

    # ── 명시 일치: 정상 ──
    async def test_explicit_match_fundamental(self, client, store):
        """`005930__fundamental?data_type=fundamental` → 정상 삭제."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.delete(
            "/api/data/datasets/005930__fundamental",
            params={"data_type": "fundamental"},
        )
        assert resp.status_code == 204

    async def test_explicit_match_ohlcv(self, client, store):
        """`005930__1d?data_type=ohlcv` → 정상 삭제."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.delete(
            "/api/data/datasets/005930__1d",
            params={"data_type": "ohlcv"},
        )
        assert resp.status_code == 204

    # ── 명시 mismatch: 400 + rmtree 미호출 ──
    async def test_explicit_mismatch_fundamental_segment_ohlcv_query(
        self, client, store
    ):
        """`005930__fundamental?data_type=ohlcv` → 400 + rmtree 미호출."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete(
                "/api/data/datasets/005930__fundamental",
                params={"data_type": "ohlcv"},
            )
        assert resp.status_code == 400, (
            f"mismatch(fundamental seg / ohlcv query) 거부 실패: {resp.status_code}"
        )
        mock_rmtree.assert_not_called()

    async def test_explicit_mismatch_ohlcv_segment_fundamental_query(
        self, client, store
    ):
        """`005930__1d?data_type=fundamental` → 400 + rmtree 미호출."""
        store.write("005930", "1d", _make_ohlcv_df())
        with patch("ante.web.routes.data.shutil.rmtree") as mock_rmtree:
            resp = client.delete(
                "/api/data/datasets/005930__1d",
                params={"data_type": "fundamental"},
            )
        assert resp.status_code == 400, (
            f"mismatch(ohlcv seg / fundamental query) 거부 실패: {resp.status_code}"
        )
        mock_rmtree.assert_not_called()

    def test_invalid_enum_data_type_still_422(self, client):
        """enum 외 data_type 값은 여전히 422 (#1438 회귀 보존)."""
        resp = client.delete(
            "/api/data/datasets/005930__1d",
            params={"data_type": "oracle_invalid_type"},
        )
        assert resp.status_code == 422


class TestFundamentalDatasets:
    """fundamental 데이터 유형 API 테스트."""

    async def test_list_fundamental_datasets(self, client, store):
        """fundamental 데이터셋 목록 조회."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        ds = body["items"][0]
        assert ds["symbol"] == "005930"
        assert ds["data_type"] == "fundamental"

    async def test_list_ohlcv_excludes_fundamental(self, client, store):
        """OHLCV 조회 시 fundamental 데이터가 포함되지 않음."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_delete_fundamental_dataset(self, client, store):
        """fundamental 데이터셋 삭제."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.delete(
            "/api/data/datasets/005930__fundamental",
            params={"data_type": "fundamental"},
        )
        assert resp.status_code == 204

        # 삭제 후 목록에서 제거 확인
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.json()["items"] == []

    def test_schema_fundamental(self, client):
        """fundamental 스키마 조회."""
        resp = client.get("/api/data/schema", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert "per" in data
        assert "pbr" in data
        assert "market_cap" in data
