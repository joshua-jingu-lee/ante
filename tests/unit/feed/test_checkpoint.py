"""Checkpoint 모듈 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ante.feed.pipeline.checkpoint import CHECKPOINT_DIR, Checkpoint


@pytest.fixture
def feed_dir(tmp_path: Path) -> Path:
    """임시 .feed 디렉토리를 생성한다."""
    d = tmp_path / ".feed"
    d.mkdir()
    return d


class TestCheckpointInit:
    """Checkpoint 초기화 테스트."""

    def test_file_path_format(self, feed_dir: Path) -> None:
        """체크포인트 파일 경로가 {source}_{data_type}.json 형식이다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        expected = feed_dir / CHECKPOINT_DIR / "data_go_kr_ohlcv.json"
        assert cp.file_path == expected

    def test_different_source_data_type(self, feed_dir: Path) -> None:
        """소스와 데이터 유형이 다르면 다른 파일 경로를 가진다."""
        cp1 = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp2 = Checkpoint(feed_dir, "dart", "fundamental")
        assert cp1.file_path != cp2.file_path


class TestCheckpointSaveLoad:
    """체크포인트 저장/로드 테스트."""

    def test_save_creates_file(self, feed_dir: Path) -> None:
        """save()는 체크포인트 파일을 생성한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        assert cp.file_path.exists()

    def test_save_creates_checkpoint_dir(self, feed_dir: Path) -> None:
        """save()는 checkpoints 디렉토리가 없으면 생성한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        assert (feed_dir / CHECKPOINT_DIR).is_dir()

    def test_save_and_load_roundtrip(self, feed_dir: Path) -> None:
        """저장한 체크포인트를 로드하면 동일한 데이터를 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")

        data = cp.load()
        assert data is not None
        assert data["source"] == "data_go_kr"
        assert data["data_type"] == "ohlcv"
        assert data["last_date"] == "2024-06-15"
        assert "updated_at" in data

    def test_save_overwrites_previous(self, feed_dir: Path) -> None:
        """같은 소스/타입에 대해 다시 save()하면 덮어쓴다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        cp.save("2024-06-20")

        data = cp.load()
        assert data is not None
        assert data["last_date"] == "2024-06-20"

    def test_save_idempotent(self, feed_dir: Path) -> None:
        """같은 날짜로 여러 번 저장해도 안전하다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        cp.save("2024-06-15")

        data = cp.load()
        assert data is not None
        assert data["last_date"] == "2024-06-15"

    def test_save_json_format(self, feed_dir: Path) -> None:
        """저장된 파일이 유효한 JSON이다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")

        raw = cp.file_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, dict)


class TestCheckpointMissing:
    """체크포인트 미존재 시 기본 동작 테스트."""

    def test_load_returns_none_when_no_file(self, feed_dir: Path) -> None:
        """파일이 없으면 load()는 None을 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        assert cp.load() is None

    def test_get_last_date_returns_none_when_no_file(self, feed_dir: Path) -> None:
        """파일이 없으면 get_last_date()는 None을 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        assert cp.get_last_date() is None

    def test_load_returns_none_for_corrupted_file(self, feed_dir: Path) -> None:
        """파일이 손상되면 load()는 None을 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp_dir = feed_dir / CHECKPOINT_DIR
        cp_dir.mkdir(parents=True, exist_ok=True)
        cp.file_path.write_text("not valid json", encoding="utf-8")

        assert cp.load() is None


class TestCheckpointGetLastDate:
    """get_last_date() 테스트."""

    def test_returns_last_date(self, feed_dir: Path) -> None:
        """저장된 체크포인트의 last_date를 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        assert cp.get_last_date() == "2024-06-15"

    def test_returns_updated_date_after_resave(self, feed_dir: Path) -> None:
        """재저장 후 get_last_date()는 새 날짜를 반환한다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")
        cp.save("2024-07-01")
        assert cp.get_last_date() == "2024-07-01"


class TestCheckpointConcurrentAccess:
    """동시 접근 안전성 테스트."""

    def test_atomic_write_no_partial_file(self, feed_dir: Path) -> None:
        """write-then-rename 패턴으로 임시 파일이 남지 않는다."""
        cp = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp.save("2024-06-15")

        cp_dir = feed_dir / CHECKPOINT_DIR
        tmp_files = list(cp_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_multiple_instances_same_target(self, feed_dir: Path) -> None:
        """같은 소스/타입의 Checkpoint 인스턴스 여러 개가 동시 사용 가능하다."""
        cp1 = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        cp2 = Checkpoint(feed_dir, "data_go_kr", "ohlcv")

        cp1.save("2024-06-15")
        data = cp2.load()
        assert data is not None
        assert data["last_date"] == "2024-06-15"

        cp2.save("2024-06-20")
        assert cp1.get_last_date() == "2024-06-20"
