"""FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션.

소스 어댑터(data.go.kr, DART)에서 데이터를 수집하고,
Normalizer로 정규화, Validator로 검증, ParquetStore로 저장한다.
파생 지표(PER/PBR/EPS/BPS/ROE/부채비율) 계산도 이 모듈에서 수행한다.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ante.data.normalizer import DARTNormalizer, DataGoKrNormalizer
from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.scheduler import (
    generate_backfill_dates,
    generate_daily_date,
)
from ante.feed.report.generator import ReportGenerator
from ante.feed.sources.dart import (
    CriticalApiError as DARTCriticalError,
)
from ante.feed.sources.dart import (
    DailyLimitExceededError as DARTDailyLimitError,
)
from ante.feed.sources.dart import DARTSource
from ante.feed.sources.data_go_kr import (
    CriticalApiError as DataGoKrCriticalError,
)
from ante.feed.sources.data_go_kr import (
    DailyLimitExceededError as DataGoKrDailyLimitError,
)
from ante.feed.sources.data_go_kr import DataGoKrSource
from ante.feed.transform.validate import validate_all

logger = logging.getLogger(__name__)

# 기본 설정 상수
DEFAULT_BACKFILL_SINCE = "2015-01-01"
LOCK_FILE = "lock"

# DART 보고서 코드 (분기별)
REPRT_CODES = ["11013", "11012", "11014", "11011"]

# OHLCV 필수 검증 필드
OHLCV_REQUIRED_FIELDS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


class FeedOrchestrator:
    """DataFeed ETL 오케스트레이터.

    backfill과 daily 두 모드를 지원하며,
    data.go.kr + DART 데이터를 수집/정규화/검증/저장한다.

    책임:
      - 방어 가드(blocked_days, blocked_hours) 적용
      - 일일 한도 확인 및 도달 시 체크포인트 저장 후 종료
      - 소스별 수집 실패 스킵 및 집계
      - 파생 지표(PER/PBR/EPS/BPS/ROE/부채비율) 계산
      - lock 파일로 동시 실행 방지
      - CollectionResult 생성
    """

    def __init__(
        self,
        data_go_kr_source: DataGoKrSource | None = None,
        dart_source: DARTSource | None = None,
        store: ParquetStore | None = None,
        data_go_kr_normalizer: DataGoKrNormalizer | None = None,
        dart_normalizer: DARTNormalizer | None = None,
        report_generator: ReportGenerator | None = None,
    ) -> None:
        """FeedOrchestrator를 초기화한다.

        Args:
            data_go_kr_source: data.go.kr 소스 어댑터.
            dart_source: DART 소스 어댑터.
            store: ParquetStore 인스턴스.
            data_go_kr_normalizer: data.go.kr 정규화기.
            dart_normalizer: DART 정규화기.
            report_generator: 리포트 생성기.
        """
        self._data_go_kr_source = data_go_kr_source
        self._dart_source = dart_source
        self._store = store
        self._data_go_kr_normalizer = data_go_kr_normalizer or DataGoKrNormalizer()
        self._dart_normalizer = dart_normalizer or DARTNormalizer()
        self._report_generator = report_generator

    async def run_backfill(
        self,
        data_path: Path,
        config: dict[str, Any],
    ) -> CollectionResult:
        """과거 데이터 대량 수집 (backfill 모드).

        1. 체크포인트 로드 -> 날짜 범위 생성
        2. 날짜별: data.go.kr fetch -> normalize -> validate -> store
        3. 분기별: DART fetch -> normalize -> validate -> store
        4. 파생 지표 계산
        5. 체크포인트 저장, 리포트 생성

        Args:
            data_path: Ante 데이터 저장소 루트 경로.
            config: 설정 딕셔너리 (schedule, guard 섹션 포함).

        Returns:
            수집 결과 CollectionResult.
        """
        feed_dir = data_path / ".feed"
        started_at = datetime.now(tz=UTC)

        # lock 파일 확인/생성
        if not self._acquire_lock(feed_dir):
            return self._make_result(
                "backfill",
                started_at,
                config_errors=[{"error": "다른 수집 프로세스가 이미 실행 중"}],
            )

        try:
            return await self._run_backfill_inner(
                data_path, config, feed_dir, started_at
            )
        finally:
            self._release_lock(feed_dir)

    async def _run_backfill_inner(
        self,
        data_path: Path,
        config: dict[str, Any],
        feed_dir: Path,
        started_at: datetime,
    ) -> CollectionResult:
        """Backfill 내부 구현."""
        schedule = config.get("schedule", {})
        backfill_since = schedule.get("backfill_since", DEFAULT_BACKFILL_SINCE)

        # 체크포인트 로드
        ohlcv_checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        dart_checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        last_ohlcv_date = ohlcv_checkpoint.get_last_date()

        # 날짜 범위 생성
        dates = list(
            generate_backfill_dates(
                start=backfill_since,
                last_checkpoint=last_ohlcv_date,
            )
        )

        if not dates:
            logger.info("Backfill: 수집할 날짜 없음 (이미 완료)")
            return self._make_result("backfill", started_at)

        # 결과 집계 변수
        failures: list[dict] = []
        warnings: list[dict] = []
        config_errors: list[dict] = []
        total_symbols: set[str] = set()
        success_symbols: set[str] = set()
        rows_written = 0
        data_types: set[str] = set()

        # 소스 누락 확인
        if self._data_go_kr_source is None:
            config_errors.append(
                {
                    "error": "data.go.kr API 키 미설정",
                    "source": "data_go_kr",
                }
            )
        if self._dart_source is None:
            config_errors.append(
                {
                    "error": "DART API 키 미설정",
                    "source": "dart",
                }
            )

        store = self._store or ParquetStore(base_path=data_path)

        # --- data.go.kr 날짜별 수집 ---
        if self._data_go_kr_source is not None:
            for target_date in dates:
                # 방어 가드 체크
                if self._is_blocked(config, target_date):
                    logger.debug("방어 가드: %s 스킵", target_date)
                    continue

                try:
                    written, syms, warns = await self._collect_data_go_kr_date(
                        target_date, store
                    )
                    rows_written += written
                    total_symbols.update(syms)
                    success_symbols.update(syms)
                    if warns:
                        warnings.extend(warns)
                    if written > 0:
                        data_types.add("ohlcv")
                        data_types.add("fundamental")

                    # 날짜별 체크포인트 갱신
                    ohlcv_checkpoint.save(target_date)

                except (DataGoKrDailyLimitError, DataGoKrCriticalError) as exc:
                    logger.critical("data.go.kr 수집 중단: %s", exc)
                    config_errors.append(
                        {
                            "error": str(exc),
                            "source": "data_go_kr",
                        }
                    )
                    break
                except Exception as exc:
                    logger.error("data.go.kr 수집 실패: date=%s, %s", target_date, exc)
                    failures.append(
                        {
                            "date": target_date,
                            "source": "data_go_kr",
                            "reason": str(exc),
                        }
                    )

        # --- DART 분기별 수집 ---
        if self._dart_source is not None:
            try:
                dart_written, dart_syms, dart_warns = await self._collect_dart(
                    data_path, feed_dir, dart_checkpoint, config
                )
                rows_written += dart_written
                total_symbols.update(dart_syms)
                success_symbols.update(dart_syms)
                if dart_warns:
                    warnings.extend(dart_warns)
                if dart_written > 0:
                    data_types.add("fundamental")
            except (DARTDailyLimitError, DARTCriticalError) as exc:
                logger.critical("DART 수집 중단: %s", exc)
                config_errors.append(
                    {
                        "error": str(exc),
                        "source": "dart",
                    }
                )
            except Exception as exc:
                logger.error("DART 수집 실패: %s", exc)
                failures.append(
                    {
                        "source": "dart",
                        "reason": str(exc),
                    }
                )

        # --- 파생 지표 계산 ---
        if "fundamental" in data_types and success_symbols:
            try:
                derived_written = await self._compute_derived_indicators(
                    store, list(success_symbols)
                )
                rows_written += derived_written
            except Exception as exc:
                logger.error("파생 지표 계산 실패: %s", exc)
                warnings.append(
                    {
                        "type": "derived_indicators",
                        "message": f"파생 지표 계산 실패: {exc}",
                    }
                )

        # 실패 종목 집계
        failed_symbols = total_symbols - success_symbols

        # 리포트 생성
        result = self._make_result(
            mode="backfill",
            started_at=started_at,
            symbols_total=len(total_symbols),
            symbols_success=len(success_symbols),
            symbols_failed=len(failed_symbols),
            rows_written=rows_written,
            data_types=sorted(data_types),
            failures=failures,
            warnings=warnings,
            config_errors=config_errors,
        )

        self._save_report(data_path, feed_dir, result, "backfill")

        return result

    async def run_daily(
        self,
        data_path: Path,
        config: dict[str, Any],
    ) -> CollectionResult:
        """일별 증분 수집 (daily 모드).

        어제 1일치 데이터를 수집한다. backfill과 동일한 ETL 흐름.

        Args:
            data_path: Ante 데이터 저장소 루트 경로.
            config: 설정 딕셔너리.

        Returns:
            수집 결과 CollectionResult.
        """
        feed_dir = data_path / ".feed"
        started_at = datetime.now(tz=UTC)

        # lock 파일 확인/생성
        if not self._acquire_lock(feed_dir):
            return self._make_result(
                "daily",
                started_at,
                config_errors=[{"error": "다른 수집 프로세스가 이미 실행 중"}],
            )

        try:
            return await self._run_daily_inner(data_path, config, feed_dir, started_at)
        finally:
            self._release_lock(feed_dir)

    async def _run_daily_inner(
        self,
        data_path: Path,
        config: dict[str, Any],
        feed_dir: Path,
        started_at: datetime,
    ) -> CollectionResult:
        """Daily 내부 구현."""
        target_date = generate_daily_date()

        # 방어 가드
        if self._is_blocked(config, target_date):
            logger.info("Daily: 방어 가드에 의해 스킵 (date=%s)", target_date)
            return self._make_result(
                "daily",
                started_at,
                target_date=target_date,
            )

        failures: list[dict] = []
        warnings: list[dict] = []
        config_errors: list[dict] = []
        total_symbols: set[str] = set()
        success_symbols: set[str] = set()
        rows_written = 0
        data_types: set[str] = set()

        store = self._store or ParquetStore(base_path=data_path)

        # data.go.kr 수집
        if self._data_go_kr_source is not None:
            try:
                written, syms, warns = await self._collect_data_go_kr_date(
                    target_date, store
                )
                rows_written += written
                total_symbols.update(syms)
                success_symbols.update(syms)
                if warns:
                    warnings.extend(warns)
                if written > 0:
                    data_types.add("ohlcv")
                    data_types.add("fundamental")
            except (DataGoKrDailyLimitError, DataGoKrCriticalError) as exc:
                config_errors.append(
                    {
                        "error": str(exc),
                        "source": "data_go_kr",
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "date": target_date,
                        "source": "data_go_kr",
                        "reason": str(exc),
                    }
                )
        else:
            config_errors.append(
                {
                    "error": "data.go.kr API 키 미설정",
                    "source": "data_go_kr",
                }
            )

        # DART 수집 (daily에서는 현재 분기 기준)
        if self._dart_source is not None:
            dart_checkpoint = Checkpoint(feed_dir, "dart", "fundamental")
            try:
                dart_written, dart_syms, dart_warns = await self._collect_dart(
                    data_path, feed_dir, dart_checkpoint, config
                )
                rows_written += dart_written
                total_symbols.update(dart_syms)
                success_symbols.update(dart_syms)
                if dart_warns:
                    warnings.extend(dart_warns)
                if dart_written > 0:
                    data_types.add("fundamental")
            except (DARTDailyLimitError, DARTCriticalError) as exc:
                config_errors.append(
                    {
                        "error": str(exc),
                        "source": "dart",
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "source": "dart",
                        "reason": str(exc),
                    }
                )
        else:
            config_errors.append(
                {
                    "error": "DART API 키 미설정",
                    "source": "dart",
                }
            )

        # 파생 지표 계산
        if "fundamental" in data_types and success_symbols:
            try:
                derived_written = await self._compute_derived_indicators(
                    store, list(success_symbols)
                )
                rows_written += derived_written
            except Exception as exc:
                warnings.append(
                    {
                        "type": "derived_indicators",
                        "message": f"파생 지표 계산 실패: {exc}",
                    }
                )

        failed_symbols = total_symbols - success_symbols

        result = self._make_result(
            mode="daily",
            started_at=started_at,
            target_date=target_date,
            symbols_total=len(total_symbols),
            symbols_success=len(success_symbols),
            symbols_failed=len(failed_symbols),
            rows_written=rows_written,
            data_types=sorted(data_types),
            failures=failures,
            warnings=warnings,
            config_errors=config_errors,
        )

        self._save_report(data_path, feed_dir, result, "daily")

        return result

    # ── data.go.kr 수집 ───────────────────────────────────

    async def _collect_data_go_kr_date(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, set[str], list[dict]]:
        """data.go.kr에서 특정 날짜 전종목 데이터를 수집한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, 경고 목록).
        """
        assert self._data_go_kr_source is not None

        # API 호출
        raw_items = await self._data_go_kr_source.fetch(target_date)
        if not raw_items:
            logger.debug("data.go.kr: date=%s 데이터 없음", target_date)
            return 0, set(), []

        # 검증
        validation = validate_all(
            raw_items,
            OHLCV_REQUIRED_FIELDS,
        )
        warns: list[dict] = []
        if validation.warnings:
            for w in validation.warnings:
                warns.append(
                    {
                        "date": target_date,
                        "source": "data_go_kr",
                        "type": "business_rule",
                        "message": w,
                    }
                )

        # DataFrame 변환
        df = pl.DataFrame(raw_items)

        # 중복 제거
        if "srtnCd" in df.columns and "basDt" in df.columns:
            df = df.unique(subset=["srtnCd", "basDt"])

        # OHLCV 정규화 + 저장
        ohlcv_df = self._data_go_kr_normalizer.normalize_ohlcv(df)
        rows_written = 0
        symbols: set[str] = set()

        if not ohlcv_df.is_empty() and "symbol" in ohlcv_df.columns:
            symbol_list = ohlcv_df["symbol"].unique().to_list()
            for sym in symbol_list:
                sym_df = ohlcv_df.filter(pl.col("symbol") == sym)
                await store.write(sym, "1d", sym_df, data_type="ohlcv")
                rows_written += len(sym_df)
                symbols.add(sym)

        # FUNDAMENTAL 정규화 + 저장
        fundamental_df = self._data_go_kr_normalizer.normalize_fundamental(df)
        if not fundamental_df.is_empty() and "symbol" in fundamental_df.columns:
            fund_symbols = fundamental_df["symbol"].unique().to_list()
            for sym in fund_symbols:
                sym_df = fundamental_df.filter(pl.col("symbol") == sym)
                await store.write(sym, "krx", sym_df, data_type="fundamental")
                rows_written += len(sym_df)
                symbols.add(sym)

        logger.info(
            "data.go.kr 수집 완료: date=%s symbols=%d rows=%d",
            target_date,
            len(symbols),
            rows_written,
        )

        return rows_written, symbols, warns

    # ── DART 수집 ─────────────────────────────────────────

    async def _collect_dart(
        self,
        data_path: Path,
        feed_dir: Path,
        checkpoint: Checkpoint,
        config: dict[str, Any],
    ) -> tuple[int, set[str], list[dict]]:
        """DART에서 재무제표를 분기별로 수집한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, 경고 목록).
        """
        assert self._dart_source is not None

        store = self._store or ParquetStore(base_path=data_path)

        # corp_code 매핑 로드 또는 다운로드
        corp_codes_path = feed_dir / "dart_corp_codes.json"
        corp_code_map = await self._dart_source.fetch_corp_codes(
            save_path=corp_codes_path
        )

        if not corp_code_map:
            logger.warning("DART: 고유번호 매핑이 비어있음")
            return 0, set(), []

        corp_codes_list = list(corp_code_map.keys())

        # 수집 연도/분기 범위 결정
        schedule = config.get("schedule", {})
        backfill_since = schedule.get("backfill_since", DEFAULT_BACKFILL_SINCE)
        start_year = int(backfill_since[:4])
        end_year = date.today().year

        last_checkpoint = checkpoint.get_last_date()

        rows_written = 0
        symbols: set[str] = set()
        warns: list[dict] = []

        for year in range(start_year, end_year + 1):
            for reprt_code in REPRT_CODES:
                # 체크포인트 기반 스킵
                quarter_key = f"{year}-{reprt_code}"
                if last_checkpoint and quarter_key <= last_checkpoint:
                    continue

                try:
                    raw_items = await self._dart_source.fetch_financial(
                        corp_codes_list, str(year), reprt_code
                    )
                except (DARTDailyLimitError, DARTCriticalError):
                    raise
                except Exception as exc:
                    logger.warning(
                        "DART 수집 실패: year=%s reprt=%s: %s",
                        year,
                        reprt_code,
                        exc,
                    )
                    warns.append(
                        {
                            "source": "dart",
                            "year": str(year),
                            "reprt_code": reprt_code,
                            "message": str(exc),
                        }
                    )
                    continue

                if not raw_items:
                    continue

                # DataFrame 변환 + 정규화
                df = pl.DataFrame(raw_items)
                normalized = self._dart_normalizer.normalize(df, corp_code_map)

                if normalized.is_empty():
                    continue

                # 심볼별 저장
                if "symbol" in normalized.columns:
                    sym_list = normalized["symbol"].unique().to_list()
                    for sym in sym_list:
                        sym_df = normalized.filter(pl.col("symbol") == sym)
                        await store.write(sym, "krx", sym_df, data_type="fundamental")
                        rows_written += len(sym_df)
                        symbols.add(sym)

                # 분기별 체크포인트 갱신
                checkpoint.save(quarter_key)

        logger.info(
            "DART 수집 완료: symbols=%d rows=%d",
            len(symbols),
            rows_written,
        )

        return rows_written, symbols, warns

    # ── 파생 지표 계산 ────────────────────────────────────

    async def _compute_derived_indicators(
        self,
        store: ParquetStore,
        symbols: list[str],
    ) -> int:
        """PER/PBR/EPS/BPS/ROE/부채비율을 계산하여 fundamental에 merge한다.

        계산 공식:
        - PER = 시가총액 / 당기순이익
        - PBR = 시가총액 / 자본총계
        - EPS = 당기순이익 / 상장주식수
        - BPS = 자본총계 / 상장주식수
        - ROE = 당기순이익 / 자본총계
        - 부채비율 = 부채총계 / 자본총계

        Args:
            store: ParquetStore 인스턴스.
            symbols: 대상 심볼 목록.

        Returns:
            갱신된 행 수.
        """
        rows_updated = 0

        for sym in symbols:
            try:
                fundamental = await store.read(sym, "krx", data_type="fundamental")
            except Exception:
                continue

            if fundamental.is_empty():
                continue

            # 필수 컬럼 존재 확인
            cols = set(fundamental.columns)
            has_market_cap = "market_cap" in cols
            has_shares = "shares_listed" in cols
            has_net_income = "net_income" in cols
            has_equity = "total_equity" in cols
            has_debt = "total_debt" in cols

            exprs: list[pl.Expr] = []

            # PER = 시가총액 / 당기순이익
            if has_market_cap and has_net_income:
                exprs.append(
                    pl.when(pl.col("net_income") != 0)
                    .then(
                        pl.col("market_cap").cast(pl.Float64)
                        / pl.col("net_income").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("per")
                )

            # PBR = 시가총액 / 자본총계
            if has_market_cap and has_equity:
                exprs.append(
                    pl.when(pl.col("total_equity") != 0)
                    .then(
                        pl.col("market_cap").cast(pl.Float64)
                        / pl.col("total_equity").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("pbr")
                )

            # EPS = 당기순이익 / 상장주식수
            if has_net_income and has_shares:
                exprs.append(
                    pl.when(pl.col("shares_listed") != 0)
                    .then(
                        pl.col("net_income").cast(pl.Float64)
                        / pl.col("shares_listed").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("eps")
                )

            # BPS = 자본총계 / 상장주식수
            if has_equity and has_shares:
                exprs.append(
                    pl.when(pl.col("shares_listed") != 0)
                    .then(
                        pl.col("total_equity").cast(pl.Float64)
                        / pl.col("shares_listed").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("bps")
                )

            # ROE = 당기순이익 / 자본총계
            if has_net_income and has_equity:
                exprs.append(
                    pl.when(pl.col("total_equity") != 0)
                    .then(
                        pl.col("net_income").cast(pl.Float64)
                        / pl.col("total_equity").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("roe")
                )

            # 부채비율 = 부채총계 / 자본총계
            if has_debt and has_equity:
                exprs.append(
                    pl.when(pl.col("total_equity") != 0)
                    .then(
                        pl.col("total_debt").cast(pl.Float64)
                        / pl.col("total_equity").cast(pl.Float64)
                    )
                    .otherwise(None)
                    .alias("debt_to_equity")
                )

            if not exprs:
                continue

            updated = fundamental.with_columns(exprs)
            await store.write(sym, "krx", updated, data_type="fundamental")
            rows_updated += len(updated)

        logger.info(
            "파생 지표 계산 완료: symbols=%d rows=%d",
            len(symbols),
            rows_updated,
        )
        return rows_updated

    # ── 방어 가드 ─────────────────────────────────────────

    @staticmethod
    def _is_blocked(config: dict[str, Any], target_date: str) -> bool:
        """방어 가드 조건을 확인한다.

        Args:
            config: 설정 딕셔너리 (guard 섹션).
            target_date: 확인할 날짜 (YYYY-MM-DD).

        Returns:
            차단되면 True.
        """
        guard = config.get("guard", {})

        # blocked_days 확인
        blocked_days = guard.get("blocked_days", [])
        if blocked_days:
            d = date.fromisoformat(target_date)
            day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            current_day = day_names[d.weekday()]
            if current_day in [bd.lower() for bd in blocked_days]:
                return True

        # blocked_hours 확인 (현재 시각 기준)
        pause_during_trading = guard.get("pause_during_trading", False)
        blocked_hours = guard.get("blocked_hours", [])

        if pause_during_trading and blocked_hours:
            kst = timezone(timedelta(hours=9))
            now_kst = datetime.now(tz=kst)
            current_hour_min = now_kst.strftime("%H:%M")

            for window in blocked_hours:
                if "-" in window:
                    start_time, end_time = window.split("-")
                    if start_time.strip() <= current_hour_min <= end_time.strip():
                        return True

        return False

    # ── Lock 파일 관리 ────────────────────────────────────

    @staticmethod
    def _acquire_lock(feed_dir: Path) -> bool:
        """Lock 파일을 생성하여 동시 실행을 방지한다.

        Args:
            feed_dir: .feed 디렉토리 경로.

        Returns:
            lock 획득 성공 시 True.
        """
        lock_path = feed_dir / LOCK_FILE
        feed_dir.mkdir(parents=True, exist_ok=True)

        if lock_path.exists():
            try:
                pid = int(lock_path.read_text().strip())
                # 프로세스 존재 여부 확인
                os.kill(pid, 0)
                logger.error("다른 수집 프로세스가 실행 중 (PID=%d)", pid)
                return False
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                # 프로세스 없음 (비정상 종료) -> lock 파일 제거 후 진행
                logger.warning("비정상 lock 파일 감지, 제거 후 진행")
                lock_path.unlink(missing_ok=True)

        lock_path.write_text(str(os.getpid()))
        return True

    @staticmethod
    def _release_lock(feed_dir: Path) -> None:
        """Lock 파일을 제거한다."""
        lock_path = feed_dir / LOCK_FILE
        lock_path.unlink(missing_ok=True)

    # ── 유틸리티 ──────────────────────────────────────────

    @staticmethod
    def _make_result(
        mode: str,
        started_at: datetime,
        target_date: str | None = None,
        symbols_total: int = 0,
        symbols_success: int = 0,
        symbols_failed: int = 0,
        rows_written: int = 0,
        data_types: list[str] | None = None,
        failures: list[dict] | None = None,
        warnings: list[dict] | None = None,
        config_errors: list[dict] | None = None,
    ) -> CollectionResult:
        """CollectionResult를 생성한다."""
        finished_at = datetime.now(tz=UTC)
        duration = (finished_at - started_at).total_seconds()

        return CollectionResult(
            mode=mode,
            started_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            finished_at=finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_seconds=duration,
            target_date=target_date,
            symbols_total=symbols_total,
            symbols_success=symbols_success,
            symbols_failed=symbols_failed,
            rows_written=rows_written,
            data_types=data_types or [],
            failures=failures or [],
            warnings=warnings or [],
            config_errors=config_errors or [],
        )

    def _save_report(
        self,
        data_path: Path,
        feed_dir: Path,
        result: CollectionResult,
        mode: str,
    ) -> None:
        """리포트를 생성하고 저장한다."""
        generator = self._report_generator or ReportGenerator(feed_dir)
        report = generator.generate(result)
        generator.save(data_path, report, mode)
