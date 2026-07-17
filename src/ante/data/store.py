"""Data Pipeline — Parquet 파일 읽기/쓰기/관리."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Literal

import polars as pl

from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical

logger = logging.getLogger(__name__)


class ParquetReadError(Exception):
    """Parquet 파티션을 읽는 도중 손상 파일을 만났을 때 발생.

    `ParquetStore.read(..., strict=True)` 경로 전용 예외다. tolerant
    경로(`strict=False`, 기본)는 손상 파티션을 logger.warning + continue로
    skip하므로 이 예외를 발생시키지 않는다(feed/CLI 회귀 방지). strict
    경로(backtest data 로드 등)는 손상 파티션을 만나면 부분 데이터로
    silent 성공하지 않고 이 예외로 즉시 실패한다(#2095).

    메시지에 손상 파일 경로와 원인 예외를 포함하며, `raise ... from exc`
    로 원인 예외 체인을 보존한다.
    """


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

# `read(end=...)`에서 엄격 date-only(`YYYY-MM-DD`)를 식별하는 정규식.
# 시간 성분/timezone suffix/basic ISO 등 그 외 형식은 매치하지 않으며
# 기존 `<= end`(정확 instant) 경로로 처리된다(#2081).
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# subminute 파티셔닝 해상도 집합(04-schema.md 파일 규격, core.md 축 B 명시값).
# OHLCV 중 이 timeframe은 월별이 아니라 **일별**(`YYYY-MM-DD.parquet`)로
# 파티셔닝한다. OHLCV bar timeframe vocabulary(축 A,
# `CANONICAL_TIMEFRAMES`)와는 별개 축이며, 여기에 값을 추가/재정의하지
# 않는다(#2115).
_SUBMINUTE_TIMEFRAMES: frozenset[str] = frozenset({"10s", "30s"})

# legacy 월별 파일(`YYYY-MM.parquet`)만 매치하는 glob 패턴. 일별 파일
# (`YYYY-MM-DD.parquet` = `????-??-??.parquet`)은 segment 수가 달라
# 미매치다. subminute dir이 이미 월별로 채워져 있는지(coexistence 방지)
# 판정하는 데만 쓴다(#2115).
_LEGACY_MONTHLY_GLOB = "????-??.parquet"


def _natural_key(data_type: str, columns: list[str]) -> list[str]:
    """data_type별 merge/dedup용 natural key 컬럼 목록을 결정한다.

    natural key는 같은 월 파티션 내에서 "같은 논리 행"을 식별하는 기준이며,
    merge 시 `unique(subset=key, keep="last")`로 멱등성을 보장한다.

    - fundamental: `["date", "source"]`(둘 다 존재 시) 또는 `["date"]`.
      DART 재무제표 date는 분기말일(3/31·6/30·9/30·12/31)이라
      data.go.kr의 같은 거래일 일별 fundamental과 같은 월 파티션에서
      date가 충돌할 수 있다. `source`까지 키에 포함하면 두 소스의
      서로 다른(null-complementary) 행을 **모두 보존**한다(#1964).
      `available_date`(point-in-time 공시 접수일, #2010)는 논리 행을
      식별하는 키가 아니라 **value 속성**이므로 natural key에 넣지 않는다.
      key는 period_end(`date`)+`source`로 한 분기·소스당 한 논리 행을
      식별하고, 정정공시/재제출로 동일 period_end에 후속 접수가 들어오면
      `keep="last"`가 최신 `available_date`/값으로 overwrite한다(완전한
      revision history 보존은 비목표, known-limitation).
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


def _date_str(value: object) -> str:
    """Datetime/Date/str을 YYYY-MM-DD 문자열로."""
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]  # type: ignore[attr-defined]
    return str(value)[:10]


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
        # 신규 파티션 파일 mode(umask 존중)를 **1회** 계산해 재사용한다(#2413
        # 리뷰 [666]). hot-path마다 `os.umask(0)`/복원 probe를 돌리면 umask=0 창의
        # thread-safety 문제와 불필요한 syscall이 반복된다. 기존 target이 있으면
        # 그 mode를 보존하고(아래 `_apply_partition_mode`), 없을 때만 이 값을 쓴다.
        _cur_umask = os.umask(0)
        os.umask(_cur_umask)
        self._default_file_mode = 0o666 & ~_cur_umask

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
            `{"type": str, "path": str, "message": str}` 형태이며 ``type`` 은
            둘 중 하나다:
            - ``"store_merge"``: read 성공 후 concat/schema 실패로 이번 write를
              건너뛰고 **기존 파일을 보존**했다. checkpoint 전진 게이트다(소비자
              ``backfill_runner._drain_store_warnings`` /
              ``pending_merge_failure_count`` 가 이 타입만 필터해 checkpoint를
              미전진시킨다).
            - ``"store_recovered"``: read 실패(손상/0바이트/미완성)로 파일을
              ``.corrupted`` 로 격리하고 현재 group으로 **재생성(self-heal)** 했다
              (#2413). 위 게이트 소비자는 이 타입을 세지 않으므로 by-construction
              **비게이트**다(checkpoint 전진 허용 → loud-stuck 해소).
        """
        drained = list(self._pending_warnings)
        self._pending_warnings.clear()
        return drained

    def pending_merge_failure_count(self) -> int:
        """현재 버퍼에 쌓인 ``store_merge`` 경고 수를 **비파괴적으로** 센다.

        ``drain_warnings()`` 와 달리 버퍼를 비우지 않는다(read-only count).
        DART collector처럼 checkpoint.save를 자체적으로 수행하는 호출자가
        ``store.write`` 직전/직후 이 값을 비교해 이번 단계에서 발생한
        store-merge 실패(파티션 merge 실패 → 기존 파일 보존, 데이터 미반영)를
        감지하는 데 쓴다(#1993). 누적 카운트이므로 **직전/직후 증가분**으로
        이번 단계의 실패를 판정해야 한다(이전 단계 경고가 아직 runner에 의해
        drain되지 않았을 수 있음).

        파괴적 drain은 backfill_runner가 collect 종료 후 단일 소유로 수행하므로,
        DART가 여기서 drain하면 runner가 보고할 경고를 소실시킨다. 따라서 이
        메서드는 절대 버퍼를 비우지 않는다(drain 소유권 보존, #1993 R2).

        Returns:
            ``type == "store_merge"`` 인 pending 경고의 수.
        """
        return sum(1 for w in self._pending_warnings if w.get("type") == "store_merge")

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
        strict: bool = False,
    ) -> pl.DataFrame:
        """Parquet에서 데이터 읽기.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임 (1m, 5m, 15m, 1h, 1d)
            start: 시작 시간 (ISO 형식, inclusive)
            end: 종료 시간 (ISO 형식, inclusive). date-only(`YYYY-MM-DD`)는
                해당 날짜 whole-day inclusive(당일 23:59:59.999까지)로
                해석되어 intraday 당일 장중 데이터가 포함된다(#2081).
                시간 성분이 있는 형식은 그 정확 instant까지 inclusive다.
            limit: 최근 N건만 반환
            data_type: 데이터 타입 (ohlcv, fundamental, tick)
            exchange: 거래소 코드 (KRX, NYSE, NASDAQ 등)
            strict: 손상 파티션 처리 정책(#2095).
                - False(기본): tolerant. 손상 파티션을 logger.warning 후
                  skip하고 나머지로 부분 DataFrame을 반환한다(feed/CLI 등
                  부분-허용 공용 경로의 기존 동작 보존).
                - True: fail-closed. 손상 파티션을 만나면 부분 데이터로
                  silent 성공하지 않고 즉시 `ParquetReadError`를 raise한다
                  (backtest 데이터 로드 전용). 부분 데이터로 백테스트가
                  일부 기간을 빠뜨린 채 성공하는 버그를 차단한다.

        Raises:
            ParquetReadError: strict=True이며 손상 파티션을 만났을 때.
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
            except Exception as exc:
                if strict:
                    raise ParquetReadError(
                        f"Corrupt parquet partition: {f}: {exc}"
                    ) from exc
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
            # date-only end(`YYYY-MM-DD`)는 whole-day inclusive로 해석한다.
            # `<= 2026-01-02 00:00 UTC`로 파싱하면 intraday(1m/5m/1h) 당일
            # 장중 row(09:01, 15:30 등)가 모두 제외된다(#2081). 따라서
            # date-only일 때는 자정 instant가 아니라 그 날 전체를 포함하도록
            # `< (end_date + 1 day)`(당일 23:59:59.999까지)로 필터한다.
            # 1d(daily) bar는 00:00이라 +1day exclusive로도 당일 bar가
            # 그대로 포함되어 기존 동작과 동일하다(회귀 없음).
            #
            # 시간 성분이 있는 end(datetime, timezone suffix, basic ISO 등
            # date-only가 아닌 모든 형식)는 기존 `<= end`(정확 instant)를
            # 유지한다.
            if _DATE_ONLY_RE.match(end):
                df = df.filter(
                    pl.col(time_col)
                    < pl.lit(end).str.to_datetime(time_zone="UTC") + pl.duration(days=1)
                )
            else:
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
    ) -> int:
        """데이터를 Parquet에 기록. 파티셔닝, 중복 제거(merge).

        Returns:
            이번 write로 **실제 새로 저장된 net-new 행 수**(rows_written, #1993).
            파티션별 net delta = ``max(0, len(merged) - len(existing))``의 합이다
            (legacy 중복 정리로 merged < existing이면 0으로 clamp). 빈 입력/
            exchange는 0. 기존엔 입력 ``len(data)`` 를 누적해 dedup·재수집을
            과대계상했다. 신규 파티션 write는 dedup 후 결과 행 수다. merge 실패
            (기존 파일 보존 + store_merge 경고)는 0(저장 반영 없음). 반환은 정보용
            이며 silent overwrite/transaction 동작은 변경하지 않는다(하위호환:
            기존 None 반환을 사용하던 호출자 0건).

        파티셔닝 해상도(04-schema.md 파일 규격, #2115):
        - OHLCV 중 subminute(`_SUBMINUTE_TIMEFRAMES` = 10s/30s)는 **일별**
          (`YYYY-MM-DD.parquet`). 단 해당 dir에 이미 legacy 월별 파일
          (`_LEGACY_MONTHLY_GLOB`)이 있으면 월별-only를 유지하고 일별을
          신규 생성하지 않는다(월별+일별 coexistence 시 read glob+concat이
          중복 timestamp를 반환하므로 이를 원천 차단). legacy 월별→일별
          전환 migration은 destructive하므로 별도 follow-up #2267로 분리한다.
        - 그 외(1m+ OHLCV, fundamental/tick 등)는 기존대로 **월별**
          (`YYYY-MM.parquet`).

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
            return 0

        time_col = _TIME_COLUMN.get(data_type, "timestamp")
        if time_col in data.columns and bool(data[time_col].is_null().any()):
            raise ValueError(
                f"partition key '{time_col}'에 null 값이 있어 저장을 거부합니다 "
                f"(symbol={symbol}, timeframe={timeframe}, data_type={data_type})"
            )

        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        path.mkdir(parents=True, exist_ok=True)

        key = _natural_key(data_type, data.columns)

        # 파티셔닝 해상도 결정(#2115). subminute OHLCV는 일별이 기본이나,
        # 이미 legacy 월별 파일이 있는 dir은 월별을 유지해 coexistence(월별+
        # 일별 혼재 → read 중복 timestamp)를 만들지 않는다.
        use_daily = data_type == "ohlcv" and timeframe in _SUBMINUTE_TIMEFRAMES
        if use_daily and next(path.glob(_LEGACY_MONTHLY_GLOB), None) is not None:
            use_daily = False
            logger.warning(
                "legacy 월별 파티션 존재 — 일별 전환은 #2267, 월별 유지"
                "(coexistence 미생성): %s",
                path,
            )

        if use_daily:
            partitioned = self._partition_by_day(data, time_col)
        else:
            partitioned = self._partition_by_month(data, time_col)

        net_delta = 0
        for part_val, group in partitioned:
            filepath = path / f"{part_val}.parquet"
            net_delta += self._persist_partition(filepath, group, key)

        logger.debug(
            "Wrote %s/%s: input=%d net_new=%d",
            symbol,
            timeframe,
            len(data),
            net_delta,
        )
        return net_delta

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

    def _partition_by_day(
        self, data: pl.DataFrame, time_col: str
    ) -> list[tuple[str, pl.DataFrame]]:
        """데이터를 일별로 분할하여 (`YYYY-MM-DD`, DataFrame) 리스트 반환.

        `_partition_by_month`와 동형이며 파티션 key 해상도만 일별
        (`%Y-%m-%d` / Date면 `cast(Utf8).str.slice(0, 10)`)이다. subminute
        OHLCV(10s/30s) 일별 파티셔닝 전용(04-schema.md, #2115).
        """
        if time_col in data.columns:
            if data[time_col].dtype == pl.Date:
                day_series = data[time_col].cast(pl.Utf8).str.slice(0, 10)
            else:
                day_series = data[time_col].dt.strftime("%Y-%m-%d")
        else:
            day_series = pl.Series(["unknown"] * len(data))

        data_with_day = data.with_columns(day_series.alias("_day"))
        return [
            (
                day_val,
                data_with_day.filter(pl.col("_day") == day_val).drop("_day"),
            )
            for day_val in data_with_day["_day"].unique().to_list()
        ]

    @staticmethod
    def _dedup_sort_by_key(df: pl.DataFrame, key: list[str]) -> pl.DataFrame:
        """natural key로 dedup(`keep="last"`) 후 정렬한다(멱등 merge).

        key가 비었거나 df에 key 컬럼이 하나도 없으면 원본을 그대로 반환한다.
        """
        if key:
            present = [c for c in key if c in df.columns]
            if present:
                return df.unique(subset=present, keep="last").sort(present)
        return df

    @staticmethod
    def _sweep_stale_tmp(partition_dir: Path) -> int:
        """대상 파티션 dir의 stale ``*.tmp`` (orphan)를 삭제하고 삭제 수를 반환.

        원자 write의 임시 파일은 hard-kill/전원 손실 시 최종 rename 전에 orphan으로
        남는다. ``*.tmp`` 는 read glob(``*.parquet``) 밖이라 무한 누적되므로
        회수한다(#2413 리뷰 [661]). Ante는 **단일 writer**(02-write-ownership.md,
        단일 asyncio·sync 파티션 write)이므로, 어떤 write 진입 시점에도 동시 진행
        중인 live tmp가 없다 — 그때 존재하는 ``*.tmp`` 는 이전 크래시의 orphan이다.
        (프로세스 시작 시점 전역 GC는 본 이슈 Known Limitations의 follow-up.)
        """
        removed = 0
        try:
            stale_files = list(partition_dir.glob("*.tmp"))
        except OSError:
            return 0
        for stale in stale_files:
            try:
                stale.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def _apply_partition_mode(self, tmp_path: str, target: Path) -> None:
        """replace 전 tmp 파일 mode를 결정: 기존 target 보존 or umask 기본(#2413 [668]).

        ``tempfile.mkstemp`` 는 항상 ``0o600`` 으로 tmp를 만들고 ``Path.replace`` 가
        그 mode를 유지한다. 조정하지 않으면 모든 파티션이 owner-only-readable이 되어
        분리된 reader 계정/그룹이 EACCES로 실패한다(LXC 배포). 따라서:

        - 기존 ``target`` 이 있으면 **그 operator mode를 보존**(0o600 등 의도 존중).
        - 없으면(신규 파티션) umask 존중 기본(`_default_file_mode`, 통상 0o644).
        """
        try:
            mode = os.stat(target).st_mode & 0o777
        except OSError:
            mode = self._default_file_mode
        os.chmod(tmp_path, mode)

    def _atomic_write_parquet(self, df: pl.DataFrame, filepath: Path) -> None:
        """DataFrame을 파티션 파일에 **원자적으로** 기록(write-then-replace, #2413).

        checkpoint.save()(`feed/pipeline/checkpoint.py`)와 동일 패턴이다: 같은
        디렉토리에 임시 파일을 만들어 write한 뒤 ``Path.replace`` 로 원자 교체한다.
        write 도중 중단(OOM/kill/전원 손실)이 있어도 최종 경로에는 0바이트/부분
        parquet이 남지 않는다(중단 시 tmp만 잔존 → 즉시 cleanup + 다음 write에서 회수).
        권한은 `_apply_partition_mode`(기존 mode 보존 or umask 기본)를 따른다.

        Args:
            df: 기록할 DataFrame.
            filepath: 최종 파티션 파일 경로.

        Raises:
            write/replace 실패 시 원 예외를 그대로 재-raise한다(임시 파일 정리 후).
            (self-heal 경로는 이 raise를 삼켜 never-raise 불변을 강제한다.)
        """
        # orphan tmp 회수(#2413 [661]). 파티션 dir은 write()가 이미 생성(#2413 [9]).
        self._sweep_stale_tmp(filepath.parent)
        # mkstemp는 fd를 열어 반환한다. polars가 경로로 다시 열어 write하므로
        # fd는 즉시 명시적으로 close/consume해 leak을 막는다(checkpoint.save 미러).
        fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
        os.close(fd)
        try:
            df.write_parquet(tmp_path, compression=self._compression)
            self._apply_partition_mode(tmp_path, filepath)
            Path(tmp_path).replace(filepath)
        except BaseException:
            # 실패 시(예외/취소 포함) 임시 파일 정리 후 재-raise. 최종 경로는
            # 손대지 않았으므로 기존 상태(부재 또는 이전 유효본)가 보존된다.
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _quarantine_corrupt(self, filepath: Path) -> Path:
        """손상 파티션을 ``.corrupted`` 로 격리(**rename**)하고 격리 경로를 반환.

        `validate(fix)` 전용 격리 헬퍼다(target을 옮겨 치운다 — validate는 healed
        대체본이 없으므로). 기본 격리명은 ``with_suffix(".corrupted")`` 이되, 동명이
        이미 있으면 **덮어쓰지 않고** uniquifier(``.corrupted.<n>``)로 회피한다
        (반복 손상 증적 보존·POSIX 덮어쓰기 방지·Windows ``FileExistsError`` 회피,
        #2413 리뷰 [10]). self-heal은 target을 보존해야 하므로 rename이 아니라
        `_best_effort_quarantine`(copy)를 쓴다.
        """
        target = self._next_corrupted_path(filepath)
        filepath.rename(target)
        return target

    @staticmethod
    def _next_corrupted_path(filepath: Path) -> Path:
        """충돌하지 않는 ``.corrupted``/``.corrupted.<n>`` 격리 경로를 계산한다."""
        target = filepath.with_suffix(".corrupted")
        n = 1
        while target.exists():
            target = filepath.with_name(f"{filepath.stem}.corrupted.{n}")
            n += 1
        return target

    def _best_effort_quarantine(self, filepath: Path) -> Path | None:
        """손상 target을 ``.corrupted`` 로 **copy**해 증적 보존(target은 그대로 둠).

        self-heal 전용. rename이 아니라 copy이므로 target이 제거되지 않아, 뒤이은
        ``replace(tmp → target)`` 가 실패해도 target이 file-less가 되지 않는다(#2413
        리뷰 [777]/Class A). **best-effort** — 격리 copy 실패는 로그만 남기고 무시해
        healing을 우선한다(격리 실패가 healing을 막지 않는다).

        Returns:
            격리 copy 경로(성공) 또는 None(실패·무시).
        """
        try:
            target = self._next_corrupted_path(filepath)
            shutil.copyfile(filepath, target)
            return target
        except OSError as exc:
            logger.warning(
                "손상 파티션 증적 격리(copy) 실패 — 무시하고 healing 진행: %s (%s)",
                filepath,
                exc,
            )
            return None

    # polars가 truncated/garbage/0바이트 parquet에 내는 실측 corruption 마커.
    # (관찰: `ComputeError: parquet: File out of specification: ...`.) 이 마커에만
    # self-heal을 발동해 오분류(→ silent data loss)를 막는다(#2413 Class B).
    _PARQUET_CORRUPT_MARKER = "File out of specification"

    @classmethod
    def _is_corrupt_parquet(cls, filepath: Path, exc: BaseException) -> bool:
        """read 실패가 **genuine·확정 corruption**인지(self-heal 대상인지) 판정한다.

        비용 비대칭이 판정의 핵심이다(#2413 Class B):
        - false-negative(진짜 손상을 미healing) = **loud-stuck**(가시적, `validate
          --fix` + 재backfill로 복구 가능).
        - false-positive(유효 파일을 healing) = **silent data loss**(수개월치 격리 +
          현재 group만 landing, 복구 불가).
        따라서 **불확실하면 항상 False**(preserve + store_merge로 편향)한다.

        확정 corruption 신호(둘 중 하나면 True):
        1. ``pl.exceptions.ComputeError`` 이며 메시지에 정확한 corruption 마커
           (``File out of specification``)가 포함(truncated/garbage/0바이트 실측).
           넓은 ``startswith("parquet:")`` 는 비손상 ComputeError(I/O·압축·미지원)까지
           오분류하므로 **쓰지 않는다**.
        2. ``st_size == 0`` (0바이트 = 중단 write 잔재). 단 ``stat`` 이 실패하면
           corrupt로 **단정하지 않는다**(preserve 편향) — 마커(1)로만 판정한다.

        그 외(MemoryError/PermissionError/일반 OSError·기타 ComputeError)는
        corruption이 아니며, 호출부가 격리 없이 기존 보존 + ``store_merge``
        (게이트→재시도)로 처리한다.
        """
        if isinstance(
            exc, pl.exceptions.ComputeError
        ) and cls._PARQUET_CORRUPT_MARKER in str(exc):
            return True
        try:
            if filepath.stat().st_size == 0:
                return True
        except OSError:
            # stat 실패: corrupt로 단정하지 않는다(preserve로 편향).
            return False
        return False

    def _record_merge_failure(
        self, filepath: Path, exc: BaseException, *, message: str | None = None
    ) -> int:
        """기존 파일 보존 + ``store_merge`` 경고를 적재하고 net-new 0을 반환한다.

        concat/schema 실패, 원자 write 실패, 일시적 read 오류, self-heal 불가(격리·
        재생성 write 실패)를 모두 동일하게 처리한다: 기존 데이터를 절대 덮어쓰지
        않고 checkpoint 전진 게이트(``store_merge``)로 표면화해 다음 run 재시도를
        유도한다(#2413 리뷰 [0]/[3]).
        """
        logger.warning(
            "Parquet 파티션 merge 실패: %s — 기존 파일 보존, write 건너뜀 (%s)",
            filepath,
            exc,
        )
        self._pending_warnings.append(
            {
                "type": "store_merge",
                "path": str(filepath),
                "message": message
                or (
                    f"파티션 merge 실패로 이번 write를 건너뛰어 기존 데이터를 "
                    f"보존했습니다: {exc}"
                ),
            }
        )
        return 0

    def _self_heal_partition(
        self,
        filepath: Path,
        group: pl.DataFrame,
        key: list[str],
        read_exc: BaseException,
    ) -> int:
        """손상 파티션을 재생성한다. **never raise, never file-less**(Class A).

        Class A 불변식(#2413 리뷰 [777]): self-heal을 결정한 순간부터 어떤 단계
        (증적 격리·dedup·재생성 write·replace)가 실패해도 **예외를 호출부(write())로
        전파하지 않으며**(항상 int 반환), 어떤 실패 경로에서도 **target 경로에 파일이
        남는다**(file-less 금지 → backfill/DART 크래시 방지).

        강제 구조(파괴적 단계를 마지막에):
        1. healed group을 tmp에 원자 준비(write + mode 조정).
        2. 손상 target을 ``.corrupted`` 로 **best-effort copy 격리**(실패해도 무시,
           target은 그대로 둠 → 증적만 확보, healing 차단 안 함).
        3. ``Path(tmp).replace(target)`` 로 원자 덮어쓰기(격리 실패해도 healed landing).

        어떤 단계라도 실패하면 tmp를 정리하고 target(기존 손상 내용)을 그대로 둔 채
        ``store_merge`` (게이트→재시도) + return 0로 처리한다(target은 file-less가
        아니라 손상본 유지 → 다음 run이 재-self-heal). 성공하면 ``store_recovered``
        (비게이트)를 적재해 checkpoint 전진을 허용한다(→ loud-stuck 해소).

        Returns:
            재생성 성공 시 net-new 행 수(신규 파티션 경로와 동일 = dedup 후 len).
            어떤 단계라도 실패 시 0(target 손상본 유지 + store_merge).
        """
        group = self._dedup_sort_by_key(group, key)
        quarantined: Path | None = None
        try:
            self._sweep_stale_tmp(filepath.parent)
            fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
            os.close(fd)
            try:
                # ① healed group을 tmp에 원자 준비(mode = 기존 손상본 mode 보존).
                group.write_parquet(tmp_path, compression=self._compression)
                self._apply_partition_mode(tmp_path, filepath)
                # ② 손상 target 증적을 best-effort copy 격리(target 보존).
                quarantined = self._best_effort_quarantine(filepath)
                # ③ tmp → target 원자 덮어쓰기(격리 실패해도 healed landing).
                Path(tmp_path).replace(filepath)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        except Exception as heal_exc:
            # never raise: 어떤 단계 실패라도 예외를 삼킨다. target은 손상 내용을
            # 그대로 유지(replace 전이라 file-less 아님) → store_merge(게이트) 재시도.
            # (KeyboardInterrupt/SystemExit 등 BaseException은 의도적으로 전파.)
            logger.warning(
                "Parquet 파티션 self-heal 실패: %s (%s) — 손상본 유지 + store_merge "
                "재시도(파티션 file-less 아님).",
                filepath,
                heal_exc,
            )
            return self._record_merge_failure(
                filepath,
                heal_exc,
                message=(
                    f"손상 파티션 self-heal 재생성이 실패해 이번 write를 건너뛰었습니다"
                    f"(손상본 유지, 다음 run 재시도): {heal_exc}"
                ),
            )

        message = (
            f"손상/미완성 파티션을 격리(.corrupted)하고 현재 수집분으로 재생성"
            f"했습니다(self-heal, 원 예외: {read_exc}). "
            f"주의: 격리된 파티션에 이전 데이터가 있었다면 이번 재생성은 현재 "
            f"수집 group만 담으므로 checkpoint 이전 구간이 유실될 수 있습니다"
            f"(forward-only 침묵 공백). 완전 복구는 명시 range 재backfill로만 "
            f"가능합니다."
        )
        logger.warning(
            "Parquet 파티션 self-heal: %s — 손상 파일을 %s 로 격리하고 재생성 "
            "(원 예외: %s). 이전 데이터가 있었다면 forward-only 공백 가능 — "
            "range 재backfill 필요.",
            filepath,
            quarantined if quarantined is not None else "(격리 실패·증적 없음)",
            read_exc,
        )
        self._pending_warnings.append(
            {
                "type": "store_recovered",
                "path": str(filepath),
                "message": message,
            }
        )
        # 신규 파티션 경로와 동일하게 dedup 후 결과 행 수가 net-new 저장 행 수.
        return len(group)

    def _persist_partition(
        self, filepath: Path, group: pl.DataFrame, key: list[str]
    ) -> int:
        """단일 파티션을 Parquet 파일에 기록. 기존 파일이 있으면 merge.

        원자성(#2413): 모든 파티션 write는 `_atomic_write_parquet`(임시 파일 +
        원자 rename)로 수행한다. write 중단 시 최종 경로에 0바이트/부분 parquet이
        남지 않는다(checkpoint.save durability 불변과 정합).

        merge 전략(#1964):
        - 기존 파일 **읽기**(`pl.read_parquet`)와 **결합**(`pl.concat`)을 분리한다:
          * read 실패이며 **genuine·확정 corruption**(`_is_corrupt_parquet`: 0바이트
            또는 정확한 corruption 마커 `File out of specification`) → self-heal로
            현재 group을 landing(**never raise/never file-less**, `store_recovered`).
            corrupt 파일엔 보존할 유효 데이터가 없으므로 #1964의 무손실 취지를
            위반하지 않으며, 읽기 불가 파티션의 영구 stuck(#2413)을 해소한다.
          * read 실패이나 **일시적·환경 오류**(MemoryError/PermissionError/OSError·
            비-마커 ComputeError 등, corruption 아님) → 유효 파티션일 수 있으므로
            **격리하지 않고** 기존 보존 + `store_merge`(게이트→재시도). 오분류=silent
            data loss이므로 불확실하면 preserve로 편향한다(#2413 리뷰 [0]/[721]).
          * read 성공 후 `pl.concat(how="diagonal_relaxed")`가 (방어적으로)
            여전히 raise하는 결합-불가(유효하나 non-coercible 스키마) →
            **기존 파일을 덮어쓰지 않고** `store_merge` 경고만 기록(현행 보존).
            기존 데이터 보존을 신규 반영보다 우선한다.
        - natural key가 있으면 `unique(subset=key, keep="last")`로 신규 write
          우선 dedup 후 key로 정렬한다(멱등성).

        Args:
            filepath: 대상 파티션 파일 경로.
            group: 이번 write로 들어온 (단일 월) DataFrame.
            key: natural key 컬럼 목록. 비어 있으면 dedup/sort 생략.

        Returns:
            이 파티션에 **새로 저장된 net-new 행 수**(#1993):
            ``max(0, len(merged) - len(existing))``. 기존 파일이 없거나 self-heal
            재생성이면 dedup 결과 행 수(신규 전량). 재write/dedup으로 merged 행 수가
            늘지 않으면 0. legacy 중복 정리로 merged < existing이면(행이 줄어들면)
            0으로 clamp한다. merge 실패(기존 파일 보존)는 저장 반영이 없으므로 0.
        """
        if filepath.exists():
            try:
                existing = pl.read_parquet(filepath)
            except Exception as read_exc:
                if self._is_corrupt_parquet(filepath, read_exc):
                    # 진짜 corruption(0바이트/decode-fail): 격리 후 self-heal.
                    return self._self_heal_partition(filepath, group, key, read_exc)
                # 일시적/환경 오류(EACCES/OSError/MemoryError 등): 유효 파티션일
                # 수 있으므로 격리하지 않고 기존 보존 + store_merge(게이트→재시도).
                return self._record_merge_failure(
                    filepath,
                    read_exc,
                    message=(
                        f"파티션 읽기가 일시적/환경 오류로 실패해(손상 아님 판정, "
                        f"격리 안 함) 기존 파일을 보존하고 write를 건너뛰었습니다: "
                        f"{read_exc}"
                    ),
                )

            existing_len = len(existing)
            try:
                merged = pl.concat([existing, group], how="diagonal_relaxed")
                merged = self._dedup_sort_by_key(merged, key)
                self._atomic_write_parquet(merged, filepath)
                # net-new = merged 행 수 - 기존 행 수. dedup으로 그대로면 0,
                # legacy 중복 정리로 줄면 음수 → 0으로 clamp(과대/음수 방지).
                return max(0, len(merged) - existing_len)
            except Exception as exc:
                # read는 성공했으나 diagonal_relaxed로도 결합 불가(유효하나
                # non-coercible 스키마)하거나 원자 write가 실패한 케이스. 기존
                # 파일을 절대 덮어쓰지 않고(원자 write라 기존본 무손상) 이상만
                # 기록한다. 저장 반영이 없으므로 net-new는 0이다.
                return self._record_merge_failure(filepath, exc)

        group = self._dedup_sort_by_key(group, key)
        self._atomic_write_parquet(group, filepath)
        # 신규 파티션: dedup 후 결과 행 수가 곧 net-new 저장 행 수.
        return len(group)

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
        """종목의 데이터 기간 조회. (첫 row 날짜, 마지막 row 날짜) YYYY-MM-DD 반환.

        파일은 월별 stem 정렬이므로 첫 파일 min(time_col) = 전역 최소,
        마지막 파일 max(time_col) = 전역 최대. 읽기 실패/빈 컬럼 시 파일 stem fallback.
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        files = sorted(path.glob("*.parquet")) if path.exists() else []
        if not files:
            return None
        time_col = _TIME_COLUMN.get(data_type, "timestamp")
        try:
            first_min = pl.read_parquet(files[0]).select(pl.col(time_col).min()).item()
            last_max = pl.read_parquet(files[-1]).select(pl.col(time_col).max()).item()
        except Exception:
            return files[0].stem, files[-1].stem
        if first_min is None or last_max is None:
            return files[0].stem, files[-1].stem
        return _date_str(first_min), _date_str(last_max)

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
             "valid": int, "corrupted": int, "corrupted_files": list[str],
             "stale_tmp_removed": int}

            ``stale_tmp_removed`` 는 회수한 orphan ``*.tmp`` (이전 hard-kill 시 원자
            write가 replace 전에 남긴 잔재) 수다(#2413 리뷰 [661]). read glob
            (``*.parquet``) 밖이라 누적되므로 validate가 가시화·정리한다.
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        result: dict = {
            "symbol": symbol,
            "timeframe": timeframe,
            "total": 0,
            "valid": 0,
            "corrupted": 0,
            "corrupted_files": [],
            "stale_tmp_removed": 0,
        }

        if not path.exists():
            return result

        # orphan *.tmp 회수(가시화·정리). 단일 writer라 validate 시점의 *.tmp는
        # live가 아니라 이전 크래시 잔재다(#2413 리뷰 [661]).
        stale_removed = self._sweep_stale_tmp(path)
        result["stale_tmp_removed"] = stale_removed
        if stale_removed:
            logger.info("orphan .tmp %d개 회수: %s", stale_removed, path)

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
                    # self-heal과 공유하는 격리 헬퍼(uniquifier)로 이동한다.
                    # 동명 `.corrupted` 존재 시 덮어쓰지 않고 `.corrupted.<n>`으로
                    # 증적을 보존한다(#2413 리뷰 [10], Windows FileExistsError 방지).
                    corrupted_path = self._quarantine_corrupt(f)
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
