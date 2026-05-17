"""ParquetStore._resolve_path / _is_safe_path_segment path traversal 방어 (#1631).

Layer 2 방어: route 우회 caller(public resolve_path, read/write/delete_file/
retention/backtest)까지 보호하는 segment-level + resolved-containment 단언을
검증한다. 정상 caller(legacy 6자리외 symbol, fundamental tf="", data root
symlink deployment)는 전부 통과해야 한다.
"""

from __future__ import annotations

import pytest

from ante.data.store import ParquetStore, _is_safe_path_segment


class TestIsSafePathSegment:
    """`_is_safe_path_segment` 술어 — vocabulary 무관, traversal만 거부."""

    @pytest.mark.parametrize(
        "seg",
        [
            "005930",  # KRX 6자리
            "ABCDEF",  # legacy out-of-vocab (6자리 외)
            "oracle-safe-symbol",  # hyphen 포함 legacy
            "1d",
            "1m",
            "fundamental",
            "KRX",
            "NASDAQ",
            "A005930",
            "005930.KS",  # dot 포함 (단일 `.`/`..`가 아님)
        ],
    )
    def test_safe_segments_pass(self, seg):
        """정상/legacy out-of-vocab segment는 통과 (vocabulary 미검사)."""
        assert _is_safe_path_segment(seg) is True

    @pytest.mark.parametrize(
        "seg",
        [
            "",  # 빈 문자열
            ".",  # 현재 디렉토리
            "..",  # 부모 디렉토리 (원 재현 벡터)
            "a/b",  # slash 포함
            "../../x",  # 다단계 traversal
            "a\\b",  # 백슬래시
            "/etc/passwd",  # 절대경로
            "a\x00b",  # NUL 인젝션
            "..\\..\\x",
        ],
    )
    def test_unsafe_segments_rejected(self, seg):
        """traversal/escape 벡터는 거부."""
        assert _is_safe_path_segment(seg) is False


class TestResolvePathSegmentValidation:
    """`_resolve_path` segment-level + expected-parent 단언."""

    @pytest.fixture
    def store(self, tmp_path):
        return ParquetStore(base_path=tmp_path / "data")

    @pytest.mark.parametrize(
        ("symbol", "timeframe", "data_type"),
        [
            ("..", "1d", "ohlcv"),
            ("../../x", "1d", "ohlcv"),
            ("a/b", "1d", "ohlcv"),
            ("005930", "..", "ohlcv"),
            ("005930", "../../x", "ohlcv"),
            ("005930", "a/b", "ohlcv"),
            ("..", "", "fundamental"),
            ("/etc/passwd", "1d", "ohlcv"),
            ("005930", "1d", "../evil"),  # data_type segment traversal
        ],
    )
    def test_traversal_segment_raises_value_error(
        self, store, symbol, timeframe, data_type
    ):
        """traversal segment → ValueError (rmtree 도달 전 차단)."""
        with pytest.raises(ValueError, match="path traversal 차단"):
            store._resolve_path(symbol, timeframe, data_type=data_type)

    def test_normal_ohlcv_symbol_passes(self, store):
        """정상 KRX symbol → 통과 + resolved leaf parent == expected parent."""
        path = store._resolve_path("005930", "1d", data_type="ohlcv")
        expected_parent = store.base_path / "ohlcv" / "1d" / "KRX"
        assert path.resolve().parent == expected_parent.resolve()
        assert path.name == "005930"

    def test_legacy_non_6digit_symbol_passes(self, store):
        """legacy out-of-vocab symbol(path-safe)은 통과 — 회귀 0."""
        for sym in ("ABCDEF", "oracle-safe-symbol", "A005930"):
            path = store._resolve_path(sym, "1d", data_type="ohlcv")
            assert path.name == sym

    def test_fundamental_empty_timeframe_passes(self, store):
        """fundamental의 `timeframe=""`는 경로 미사용 → 통과."""
        path = store._resolve_path("005930", "", data_type="fundamental")
        expected_parent = store.base_path / "fundamental" / "KRX"
        assert path.resolve().parent == expected_parent.resolve()

    def test_tick_empty_timeframe_passes(self, store):
        """tick의 `timeframe=""`도 경로 미사용 → 통과."""
        path = store._resolve_path("005930", "", data_type="tick")
        expected_parent = store.base_path / "tick" / "KRX"
        assert path.resolve().parent == expected_parent.resolve()

    def test_non_canonical_timeframe_passes(self, store):
        """non-canonical timeframe(legacy `2h` 등 path-safe)은 통과.

        vocabulary 검사를 하지 않으므로 legacy non-canonical tf dir
        migration 동작이 보존된다.
        """
        path = store._resolve_path("005930", "2h", data_type="ohlcv")
        assert path.name == "005930"
        assert path.parent.name == "KRX"

    def test_public_resolve_path_also_protected(self, store):
        """public resolve_path도 동일 방어 — route 우회 caller 보호."""
        with pytest.raises(ValueError, match="path traversal 차단"):
            store.resolve_path("..", "1d")


class TestResolvePathSymlinkContainment:
    """resolved(symlink 해소) containment 단언 (Codex r2 [medium])."""

    def test_intermediate_dir_symlink_outside_base_rejected(self, tmp_path):
        """중간 dir(`ohlcv/1d/KRX`)이 base 밖 symlink → ValueError.

        DELETE의 `shutil.rmtree` 도달 전 차단되어야 한다.
        """
        base = tmp_path / "data"
        outside = tmp_path / "outside_target"
        outside.mkdir(parents=True)
        (base / "ohlcv" / "1d").mkdir(parents=True)
        # ohlcv/1d/KRX → 외부 디렉토리 symlink (spelling은 base 하위)
        (base / "ohlcv" / "1d" / "KRX").symlink_to(outside, target_is_directory=True)

        store = ParquetStore(base_path=base)
        with pytest.raises(ValueError, match="예상 위치를 벗어남"):
            store._resolve_path("005930", "1d", data_type="ohlcv")

    def test_symbol_leaf_symlink_outside_base_rejected(self, tmp_path):
        """symbol-leaf가 base 밖을 가리키는 symlink → ValueError."""
        base = tmp_path / "data"
        outside = tmp_path / "outside_leaf"
        outside.mkdir(parents=True)
        krx = base / "ohlcv" / "1d" / "KRX"
        krx.mkdir(parents=True)
        (krx / "005930").symlink_to(outside, target_is_directory=True)

        store = ParquetStore(base_path=base)
        with pytest.raises(ValueError, match="예상 위치를 벗어남"):
            store._resolve_path("005930", "1d", data_type="ohlcv")

    def test_data_root_full_symlink_deployment_passes(self, tmp_path):
        """data root 전체가 symlink인 정상 deployment → 통과.

        base/candidate 양쪽이 동일 resolve되므로 거부되지 않아야 한다
        (정상 deployment false-positive 방지 — Stop Condition).
        """
        real_data = tmp_path / "real_data"
        real_data.mkdir(parents=True)
        symlinked_base = tmp_path / "data"
        symlinked_base.symlink_to(real_data, target_is_directory=True)

        store = ParquetStore(base_path=symlinked_base)
        # 예외 없이 정상 경로 반환
        path = store._resolve_path("005930", "1d", data_type="ohlcv")
        assert path.name == "005930"
        # resolved 기준으로도 real_data 하위
        assert path.resolve().is_relative_to(real_data.resolve())

    def test_inside_base_symlink_passes(self, tmp_path):
        """base 내부를 가리키는 symlink는 통과 (탈출 아님)."""
        base = tmp_path / "data"
        krx = base / "ohlcv" / "1d" / "KRX"
        krx.mkdir(parents=True)
        real_symbol = base / "ohlcv" / "1d" / "KRX" / "_real_005930"
        real_symbol.mkdir()
        (krx / "005930").symlink_to(real_symbol, target_is_directory=True)

        store = ParquetStore(base_path=base)
        # leaf symlink target이 base 하위 → 통과
        path = store._resolve_path("005930", "1d", data_type="ohlcv")
        assert path.resolve().is_relative_to(base.resolve())


class TestLegacyMigrationUnaffected:
    """legacy migration(store.py:73-101)이 _resolve_path 미경유 — 무영향."""

    def test_migration_still_moves_legacy_dirs(self, tmp_path):
        """`migrate_parquet_paths`가 6자리 legacy dir을 KRX/로 이동 (회귀 0)."""
        from ante.data.store import migrate_parquet_paths

        base = tmp_path / "data"
        legacy = base / "ohlcv" / "1d" / "005930"
        legacy.mkdir(parents=True)
        (legacy / "2026-01.parquet").write_bytes(b"x")

        moved = migrate_parquet_paths(base)
        assert moved == 1
        assert (base / "ohlcv" / "1d" / "KRX" / "005930").exists()
        assert not (base / "ohlcv" / "1d" / "005930").exists()

    def test_migration_skips_non_6digit(self, tmp_path):
        """6자리 외 legacy dir은 migration 스킵 (기존 동작 보존)."""
        from ante.data.store import migrate_parquet_paths

        base = tmp_path / "data"
        legacy = base / "ohlcv" / "1d" / "ABCDEF"
        legacy.mkdir(parents=True)

        moved = migrate_parquet_paths(base)
        assert moved == 0
        assert (base / "ohlcv" / "1d" / "ABCDEF").exists()
