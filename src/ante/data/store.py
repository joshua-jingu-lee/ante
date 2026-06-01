"""Data Pipeline — Parquet 파일 읽기/쓰기/관리."""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Literal

import polars as pl

from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical

logger = logging.getLogger(__name__)


def _is_safe_path_segment(seg: str) -> bool:
    """단일 path segment가 traversal-safe한지 판정.

    저장소 경로(`base/.../{symbol}` 등)의 각 segment는 정확히 한 단계의
    디렉토리 이름이어야 한다. 이 술어는 **vocabulary와 무관**하다 — KRX
    6자리 형식이나 canonical timeframe 여부를 검사하지 않으며, legacy
    out-of-vocabulary symbol(`ABCDEF`, `oracle-safe-symbol` 등)은 통과
    한다(core spec Legacy 호환 정책 정합).
    오직 path traversal/escape 벡터만 거부한다.

    거부 조건:
      - 빈 문자열
      - `.` 또는 `..` (현재/부모 디렉토리)
      - `/`, `\\`, NUL 문자 포함 (경로 구분자/인젝션)
      - 절대 경로 또는 드라이브 지정 (`os.path.isabs`)

    Returns:
        traversal-safe하면 True, 그 외 False.
    """
    if not seg:
        return False
    if seg in (".", ".."):
        return False
    if "/" in seg or "\\" in seg or "\x00" in seg:
        return False
    if os.path.isabs(seg):
        return False
    # Windows 드라이브/UNC(`C:`, `\\\\host`) 방어. POSIX에서는 no-op.
    if os.path.splitdrive(seg)[0]:
        return False
    return True


# write_parquet compression 타입
CompressionType = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]

# data_type별 시간 컬럼명
_TIME_COLUMN: dict[str, str] = {
    "ohlcv": "timestamp",
    "fundamental": "date",
    "tick": "timestamp",
}


def _natural_key(data_type: str, columns: list[str]) -> list[str]:
    """data_type별 merge/dedup용 natural key 컬럼 목록을 결정한다.

    natural key는 같은 월 파티션 내에서 "같은 논리 행"을 식별하는 기준이며,
    merge 시 `unique(subset=key, keep="last")`로 멱등성을 보장한다.

    - fundamental: `["date", "source"]`(둘 다 존재 시) 또는 `["date"]`.
      DART 재무제표 date는 분기말일(3/31·6/30·9/30·12/31)이라
      data.go.kr의 같은 거래일 일별 fundamental과 같은 월 파티션에서
      date가 충돌할 수 있다. `source`까지 키에 포함하면 두 소스의
      서로 다른(null-complementary) 행을 **모두 보존**한다(#1964).
    - ohlcv/tick(및 기타 default): `["timestamp"]`(존재 시) 또는 `[]`.

    Args:
        data_type: 데이터 타입 (ohlcv/fundamental/tick/...).
        columns: 대상 DataFrame의 컬럼 목록.

    Returns:
        natural key 컬럼 목록. 키 컬럼이 데이터에 없으면 빈 목록.
    """
    cols = set(columns)
    if data_type == "fundamental":
        if "date" in cols and "source" in cols:
            return ["date", "source"]
        if "date" in cols:
            return ["date"]
        return []
    # ohlcv/tick 및 default: 단일 timestamp 키
    if "timestamp" in cols:
        return ["timestamp"]
    return []


# 알려진 거래소 이름 — 마이그레이션 시 이미 exchange 디렉토리인지 판별용.
# 코드 레벨 SSOT(`ante.core.exchange.CANONICAL_EXCHANGES`)에 위임한다.
# 값(canonical 5종 frozenset)·`migrate_parquet_paths()` 동작은 위임
# 전과 완전히 동일하다(#1576 narrow-scope: zero-change).
_KNOWN_EXCHANGES: frozenset[str] = CANONICAL_EXCHANGES

# legacy parquet path migration 판별용 KRX 심볼 형식: 6자리 숫자.
# **신규 입력 ASCII 검증과 별개 축이다**(core.md
# ``### symbol/timeframe 축 구분`` 축 E · ``### Legacy out-of-vocabulary
# 호환 정책``). `\d` 는 Unicode digit까지 매치하며, 이는 6자리 Unicode-digit
# legacy dir이 `migrate_parquet_paths()` 로 `KRX/` 하위로 이동되던 기존
# 동작을 보존하기 위해 **의도적으로** 유지된다. 신규 입력 KRX symbol
# 검증(`ante.core.market_data_vocab._KRX_SYMBOL_REGEX`, ASCII `[0-9]`,
# fullmatch)으로 위임·대체·강화하지 않는다 — 위임 시 Unicode-digit
# legacy dir migration이 silent 회귀한다(#1613 narrow-scope: legacy 무손상
# 보존, 축 E 분리).
_LEGACY_KRX_SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"^\d{6}$")


def _get_actual_dir_name(parent: Path, name: str) -> str | None:
    """파일시스템 상의 실제 디렉토리 이름을 반환.

    case-insensitive FS에서 krx/KRX 구분을 위해 사용한다.
    """
    if not parent.exists():
        return None
    for entry in parent.iterdir():
        if entry.is_dir() and entry.name.lower() == name.lower():
            return entry.name
    return None


def migrate_parquet_paths(data_path: Path) -> int:
    """기존 exchange 없는 경로를 KRX/ 하위로 이동.

    Args:
        data_path: 데이터 저장소 루트 경로 (예: data/)

    Returns:
        이동된 디렉토리 수
    """
    moved = 0

    # ohlcv 디렉토리 마이그레이션
    ohlcv_path = data_path / "ohlcv"
    if ohlcv_path.exists():
        # 불변식(#1613 R1-F2): timeframe dir 순회는 `TIMEFRAME_SET`/canonical
        # 필터를 적용하지 않는다. 어떤 set 검사도 없이 모든 timeframe dir의
        # legacy symbol dir을 `KRX/` 하위로 이동한다. 필터를 추가하면
        # `ohlcv/<non-canonical_tf>/<6digit>/`(예: `ohlcv/2h/005930/`)가
        # exchange-less 위치에 잔존해 `read(symbol,<tf>,exchange='KRX')`
        # 에서 silent 비가시가 된다(legacy non-canonical timeframe migration
        # 동작 보존 — core.md ``### Legacy out-of-vocabulary 호환 정책``).
        for timeframe_dir in ohlcv_path.iterdir():
            if not timeframe_dir.is_dir():
                continue
            for symbol_dir in list(timeframe_dir.iterdir()):
                if not symbol_dir.is_dir():
                    continue
                # 이미 exchange 디렉토리면 스킵
                if symbol_dir.name in _KNOWN_EXCHANGES:
                    continue
                # KRX 심볼은 6자리 숫자 형식 검증 (legacy `\d` Unicode 판별,
                # 신규 입력 ASCII 검증과 별개 축 — 위 상수 주석 참조)
                if not _LEGACY_KRX_SYMBOL_PATTERN.match(symbol_dir.name):
                    logger.warning(
                        "마이그레이션 스킵: %s — KRX 심볼 형식(6자리 숫자)이 아님",
                        symbol_dir,
                    )
                    continue
                target = timeframe_dir / "KRX" / symbol_dir.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(symbol_dir), str(target))
                moved += 1
                logger.info("마이그레이션: %s → %s", symbol_dir, target)

    # fundamental/tick 디렉토리 마이그레이션 (krx → KRX)
    for dtype in ("fundamental", "tick"):
        dtype_path = data_path / dtype
        if not dtype_path.exists():
            continue
        krx_lower = dtype_path / "krx"
        if not krx_lower.exists():
            continue
        # case-insensitive FS에서는 krx == KRX이므로 실제 이름 확인
        actual_name = _get_actual_dir_name(dtype_path, "krx")
        if actual_name == "KRX":
            # 이미 대문자 → 스킵
            continue
        # case-sensitive FS에서 krx → KRX 이동
        target = dtype_path / "KRX"
        if not target.exists():
            shutil.move(str(krx_lower), str(target))
            moved += 1
            logger.info("마이그레이션: %s → %s", krx_lower, target)

    if moved > 0:
        logger.info("마이그레이션 완료: %d개 디렉토리 이동", moved)

    return moved


class ParquetStore:
    """Parquet 파일 관리. 다양한 데이터 타입의 읽기/쓰기/파티셔닝 담당."""

    def __init__(
        self,
        base_path: str | Path = "data/",
        compression: CompressionType = "snappy",
    ) -> None:
        self._base = Path(base_path)
        self._compression = compression
        # merge 이상(데이터 손실 가능성이 있던 케이스)을 구조화 경고로 버퍼링.
        # backfill_runner가 collector/indicator 호출 직후 drain하여
        # CollectionResult.warnings(→ report `warnings`)로 전파한다(#1964).
        self._pending_warnings: list[dict] = []

    @property
    def base_path(self) -> Path:
        return self._base

    def drain_warnings(self) -> list[dict]:
        """누적된 store 이상 경고를 반환하고 버퍼를 비운다.

        호출자(backfill_runner)가 한 단계(collector/indicator) 종료 직후
        drain하여 run context의 warnings로 옮긴다. 반환 후 내부 버퍼는
        비워지므로 같은 경고가 중복 전파되지 않는다.

        Returns:
            누적 경고 목록의 복사본. 각 항목은
            `{"type": "store_merge", "path": str, "message": str}` 형태.
        """
        drained = list(self._pending_warnings)
        self._pending_warnings.clear()
        return drained

    def _resolve_path(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> Path:
        """data_type에 따라 저장 경로를 결정.

        - ohlcv: {base}/ohlcv/{timeframe}/{exchange}/{symbol}/
        - fundamental: {base}/fundamental/{exchange}/{symbol}/
        - tick: {base}/tick/{exchange}/{symbol}/

        path traversal 방어(#1631): 경로에 **실제로 사용되는** 각 segment
        (`symbol`/`exchange`/`data_type`, ohlcv 계열은 `timeframe`)를
        `_is_safe_path_segment`로 검증하고, resolved(`.resolve()` symlink
        해소) 기준으로 candidate가 정확히 expected parent 직하위이며 base
        하위에 포함되는지 단언한다. 위반 시 `ValueError`. legacy
        out-of-vocabulary symbol 등 정상 caller는 모두 통과한다.
        """
        used_segments: tuple[str, ...]
        if data_type == "ohlcv":
            candidate = self._base / "ohlcv" / timeframe / exchange / symbol
            expected_parent = self._base / "ohlcv" / timeframe / exchange
            used_segments = (timeframe, exchange, symbol)
        elif data_type == "fundamental":
            candidate = self._base / "fundamental" / exchange / symbol
            expected_parent = self._base / "fundamental" / exchange
            used_segments = (exchange, symbol)
        elif data_type == "tick":
            candidate = self._base / "tick" / exchange / symbol
            expected_parent = self._base / "tick" / exchange
            used_segments = (exchange, symbol)
        else:
            candidate = self._base / data_type / timeframe / exchange / symbol
            expected_parent = self._base / data_type / timeframe / exchange
            used_segments = (data_type, timeframe, exchange, symbol)

        # data_type별 expected-parent 검증: 경로에 사용되지 않는 segment
        # (fundamental/tick의 `timeframe=""`)는 검사 대상에서 제외한다.
        for seg in used_segments:
            if not _is_safe_path_segment(seg):
                raise ValueError(
                    f"path traversal 차단: 안전하지 않은 경로 segment '{seg}' "
                    f"(data_type={data_type})"
                )

        # resolved(symlink 해소) containment 단언. lexical 검사만으로는
        # 중간 디렉토리(`ohlcv/{tf}/{exchange}` 등)가 base 밖을 가리키는
        # symlink면 통과해 `shutil.rmtree` 등이 base 밖으로 탈출할 수
        # 있다. base/expected_parent/candidate를 동일하게 resolve한 뒤
        # candidate가 expected_parent 직하위이며 base 하위인지 확인한다.
        # data root 전체가 symlink인 정상 deployment는 base/candidate가
        # 동일 resolve되어 통과한다(거부 대상은 resolved 후 base 밖 탈출).
        resolved_base = self._base.resolve()
        resolved_parent = expected_parent.resolve()
        resolved_candidate = candidate.resolve()
        if (
            resolved_candidate.parent != resolved_parent
            or not resolved_candidate.is_relative_to(resolved_base)
        ):
            raise ValueError(
                f"path traversal 차단: 해석된 경로가 예상 위치를 벗어남 "
                f"(symbol={symbol!r}, timeframe={timeframe!r}, "
                f"data_type={data_type!r})"
            )

        return candidate

    def resolve_path(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> Path:
        """데이터 경로를 해석한다. _resolve_path()의 public 인터페이스."""
        return self._resolve_path(symbol, timeframe, data_type, exchange)

    def read(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> pl.DataFrame:
        """Parquet에서 데이터 읽기.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임 (1m, 5m, 15m, 1h, 1d)
            start: 시작 시간 (ISO 형식, inclusive)
            end: 종료 시간 (ISO 형식, inclusive)
            limit: 최근 N건만 반환
            data_type: 데이터 타입 (ohlcv, fundamental, tick)
            exchange: 거래소 코드 (KRX, NYSE, NASDAQ 등)
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        if not path.exists():
            return pl.DataFrame()

        files = sorted(path.glob("*.parquet"))
        if not files:
            return pl.DataFrame()

        dfs = []
        for f in files:
            try:
                dfs.append(pl.read_parquet(f))
            except Exception:
                logger.warning("Failed to read parquet file: %s", f)
                continue

        if not dfs:
            return pl.DataFrame()

        # 월별 파티션은 소스/시기에 따라 이종 스키마일 수 있다
        # (data.go.kr-only, DART-only, 지표 보강 후 등). diagonal_relaxed로
        # 컬럼 합집합 + null-fill + supertype 강제 결합하여 raise 없이 읽는다.
        df = pl.concat(dfs, how="diagonal_relaxed")
        time_col = _TIME_COLUMN.get(data_type, "timestamp")

        if start and time_col in df.columns:
            df = df.filter(
                pl.col(time_col) >= pl.lit(start).str.to_datetime(time_zone="UTC")
            )
        if end and time_col in df.columns:
            df = df.filter(
                pl.col(time_col) <= pl.lit(end).str.to_datetime(time_zone="UTC")
            )

        if time_col in df.columns:
            df = df.sort(time_col)

        if limit:
            df = df.tail(limit)

        return df

    def write(
        self,
        symbol: str,
        timeframe: str,
        data: pl.DataFrame,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> None:
        """데이터를 Parquet에 기록. 월별 파티셔닝, 중복 제거(merge).

        신규 write/append/경로 생성은 canonical exchange만 허용한다
        (core.md ``## Canonical Exchange Vocabulary``). `append()`는
        `self.write(...)`로 위임하므로 이 guard가 append도 함께 커버한다.
        read/`_resolve_path`/`migrate_parquet_paths` 등 기존·legacy 조회
        표면에는 검증을 추가하지 않는다(Legacy out-of-vocabulary read 면제).
        """
        # 비문자열은 frozenset membership에서 unhashable TypeError를
        # 유발할 수 있으므로 isinstance 선검사 후 거부(#1577 교훈).
        if not isinstance(exchange, str) or not is_canonical(exchange):
            raise ValueError(
                f"유효하지 않은 exchange: '{exchange}'. "
                f"허용 값: {sorted(CANONICAL_EXCHANGES)}"
            )

        if data.is_empty():
            return

        time_col = _TIME_COLUMN.get(data_type, "timestamp")
        if time_col in data.columns and bool(data[time_col].is_null().any()):
            raise ValueError(
                f"partition key '{time_col}'에 null 값이 있어 저장을 거부합니다 "
                f"(symbol={symbol}, timeframe={timeframe}, data_type={data_type})"
            )

        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        path.mkdir(parents=True, exist_ok=True)

        key = _natural_key(data_type, data.columns)
        partitioned = self._partition_by_month(data, time_col)

        for month_val, group in partitioned:
            filepath = path / f"{month_val}.parquet"
            self._persist_partition(filepath, group, key)

        logger.debug("Wrote %d rows for %s/%s", len(data), symbol, timeframe)

    def _partition_by_month(
        self, data: pl.DataFrame, time_col: str
    ) -> list[tuple[str, pl.DataFrame]]:
        """데이터를 월별로 분할하여 (월, DataFrame) 리스트 반환."""
        if time_col in data.columns:
            if data[time_col].dtype == pl.Date:
                month_series = data[time_col].cast(pl.Utf8).str.slice(0, 7)
            else:
                month_series = data[time_col].dt.strftime("%Y-%m")
        else:
            month_series = pl.Series(["unknown"] * len(data))

        data_with_month = data.with_columns(month_series.alias("_month"))
        return [
            (
                month_val,
                data_with_month.filter(pl.col("_month") == month_val).drop("_month"),
            )
            for month_val in data_with_month["_month"].unique().to_list()
        ]

    def _persist_partition(
        self, filepath: Path, group: pl.DataFrame, key: list[str]
    ) -> None:
        """단일 파티션을 Parquet 파일에 기록. 기존 파일이 있으면 merge.

        merge 전략(#1964):
        - 기존 파일이 있으면 `pl.concat(how="diagonal_relaxed")`로
          컬럼 합집합 + null-fill + supertype 강제 결합한다(이종 스키마 무손실).
        - natural key가 있으면 `unique(subset=key, keep="last")`로 신규 write
          우선 dedup 후 key로 정렬한다(멱등성).
        - **silent overwrite 금지**: concat이 (방어적으로) 여전히 raise하면
          기존 파일을 덮어쓰지 않고 store 이상 경고만 기록한 뒤 반환한다.
          기존 데이터 보존을 데이터 신규 반영보다 우선한다.

        Args:
            filepath: 대상 파티션 파일 경로.
            group: 이번 write로 들어온 (단일 월) DataFrame.
            key: natural key 컬럼 목록. 비어 있으면 dedup/sort 생략.
        """
        if filepath.exists():
            try:
                existing = pl.read_parquet(filepath)
                merged = pl.concat([existing, group], how="diagonal_relaxed")
                if key:
                    present = [c for c in key if c in merged.columns]
                    if present:
                        merged = merged.unique(subset=present, keep="last").sort(
                            present
                        )
                merged.write_parquet(str(filepath), compression=self._compression)
                return
            except Exception as exc:
                # 방어: diagonal_relaxed로도 결합 불가한 케이스. 기존 파일을
                # 절대 덮어쓰지 않고(데이터 손실 방지) 이상만 기록한다.
                logger.warning(
                    "Parquet 파티션 merge 실패: %s — 기존 파일 보존, write 건너뜀 (%s)",
                    filepath,
                    exc,
                )
                self._pending_warnings.append(
                    {
                        "type": "store_merge",
                        "path": str(filepath),
                        "message": (
                            f"파티션 merge 실패로 이번 write를 건너뛰어 기존 데이터를 "
                            f"보존했습니다: {exc}"
                        ),
                    }
                )
                return

        if key:
            present = [c for c in key if c in group.columns]
            if present:
                group = group.unique(subset=present, keep="last").sort(present)
        group.write_parquet(str(filepath), compression=self._compression)

    def append(
        self,
        symbol: str,
        timeframe: str,
        rows: list[dict],
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> None:
        """버퍼 데이터를 기존 Parquet에 추가."""
        df = pl.DataFrame(rows)
        # exchange canonical 검증은 write()로 위임되어 자동 커버된다
        # (별도 guard 불요 — 단일 chokepoint 유지).
        self.write(symbol, timeframe, df, data_type=data_type, exchange=exchange)

    def list_symbols(
        self,
        timeframe: str = "1d",
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> list[str]:
        """보유 데이터의 종목 목록."""
        if data_type == "ohlcv":
            path = self._base / "ohlcv" / timeframe / exchange
        elif data_type in ("fundamental", "tick"):
            path = self._base / data_type / exchange
        else:
            path = self._base / data_type / timeframe / exchange
        if not path.exists():
            return []
        return sorted([d.name for d in path.iterdir() if d.is_dir()])

    def get_date_range(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> tuple[str, str] | None:
        """종목의 데이터 기간 조회. (첫 파일 stem, 마지막 파일 stem) 반환."""
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        files = sorted(path.glob("*.parquet")) if path.exists() else []
        if not files:
            return None
        return files[0].stem, files[-1].stem

    def get_row_count(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> int:
        """종목의 총 행 수 조회. Parquet 메타데이터만 읽어 빠르게 반환."""
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        if not path.exists():
            return 0
        files = sorted(path.glob("*.parquet"))
        total = 0
        for f in files:
            try:
                total += pl.scan_parquet(f).select(pl.len()).collect().item()
            except Exception:
                logger.warning("Failed to read row count: %s", f)
                continue
        return total

    def get_storage_usage(self) -> dict[str, int]:
        """저장 용량 현황 (바이트). 데이터 타입/타임프레임별 합산."""
        usage: dict[str, int] = {}
        # ohlcv: timeframe별
        ohlcv_path = self._base / "ohlcv"
        if ohlcv_path.exists():
            for tf_dir in ohlcv_path.iterdir():
                if tf_dir.is_dir():
                    size = sum(f.stat().st_size for f in tf_dir.rglob("*.parquet"))
                    usage[tf_dir.name] = size
        # fundamental, tick
        for dtype in ("fundamental", "tick"):
            dtype_path = self._base / dtype
            if dtype_path.exists():
                size = sum(f.stat().st_size for f in dtype_path.rglob("*.parquet"))
                if size > 0:
                    usage[dtype] = size
        return usage

    def validate(
        self,
        symbol: str,
        timeframe: str,
        fix: bool = False,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> dict:
        """Parquet 파일 무결성 검증.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임
            fix: True이면 손상 파일을 .corrupted 확장자로 이동
            data_type: 데이터 타입 (ohlcv, fundamental, tick)
            exchange: 거래소 코드 (KRX, NYSE, NASDAQ 등)

        Returns:
            {"symbol": str, "timeframe": str, "total": int,
             "valid": int, "corrupted": int, "corrupted_files": list[str]}
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        result: dict = {
            "symbol": symbol,
            "timeframe": timeframe,
            "total": 0,
            "valid": 0,
            "corrupted": 0,
            "corrupted_files": [],
        }

        if not path.exists():
            return result

        files = sorted(path.glob("*.parquet"))
        result["total"] = len(files)

        for f in files:
            try:
                pl.read_parquet(f)
                result["valid"] += 1
            except Exception:
                logger.warning("손상된 Parquet 파일 발견: %s", f)
                result["corrupted"] += 1
                result["corrupted_files"].append(str(f))
                if fix:
                    corrupted_path = f.with_suffix(".corrupted")
                    f.rename(corrupted_path)
                    logger.info("손상 파일 이동: %s → %s", f, corrupted_path)

        return result

    def delete_file(
        self,
        symbol: str,
        timeframe: str,
        month: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> bool:
        """특정 Parquet 파일 삭제. 성공 여부 반환."""
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        filepath = path / f"{month}.parquet"
        if filepath.exists():
            filepath.unlink()
            logger.info("Deleted parquet file: %s", filepath)
            return True
        return False
