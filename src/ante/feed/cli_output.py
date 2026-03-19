"""ante feed CLI — 결과 출력 포매터.

CLI 서브커맨드들이 공유하는 CollectionResult 출력 로직을 분리한 모듈이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from ante.feed.models.result import CollectionResult


def format_backfill_result(
    result: CollectionResult,
    fmt: Any,  # OutputFormatter  # noqa: ANN401
) -> None:
    """Backfill 결과를 text 또는 JSON으로 출력한다."""
    if fmt.is_json:
        fmt.output(_backfill_result_dict(result))
    else:
        _echo_backfill_text(result)


def format_daily_result(
    result: CollectionResult,
    fmt: Any,  # OutputFormatter  # noqa: ANN401
) -> None:
    """Daily 결과를 text 또는 JSON으로 출력한다."""
    if fmt.is_json:
        fmt.output(_daily_result_dict(result))
    else:
        _echo_daily_text(result)


def _backfill_result_dict(result: CollectionResult) -> dict[str, Any]:
    """Backfill 결과를 JSON 직렬화용 dict로 변환한다."""
    return {
        "mode": result.mode,
        "symbols_total": result.symbols_total,
        "symbols_success": result.symbols_success,
        "symbols_failed": result.symbols_failed,
        "rows_written": result.rows_written,
        "data_types": result.data_types,
        "duration_seconds": result.duration_seconds,
        "config_errors": result.config_errors,
    }


def _daily_result_dict(result: CollectionResult) -> dict[str, Any]:
    """Daily 결과를 JSON 직렬화용 dict로 변환한다."""
    return {
        "mode": result.mode,
        "target_date": result.target_date,
        "symbols_total": result.symbols_total,
        "symbols_success": result.symbols_success,
        "symbols_failed": result.symbols_failed,
        "rows_written": result.rows_written,
        "data_types": result.data_types,
        "duration_seconds": result.duration_seconds,
        "config_errors": result.config_errors,
    }


def _echo_backfill_text(result: CollectionResult) -> None:
    """Backfill 결과를 사람이 읽기 좋은 텍스트로 출력한다."""
    click.echo()
    click.echo(
        f"Backfill 완료: {result.symbols_success}/{result.symbols_total} 종목 성공"
    )
    _echo_common_stats(result)


def _echo_daily_text(result: CollectionResult) -> None:
    """Daily 결과를 사람이 읽기 좋은 텍스트로 출력한다."""
    click.echo()
    click.echo(
        f"Daily 수집 완료 ({result.target_date}): "
        f"{result.symbols_success}/{result.symbols_total} 종목 성공"
    )
    _echo_common_stats(result)


def _echo_common_stats(result: CollectionResult) -> None:
    """공통 통계 항목(rows, data_types, 소요시간, 경고)을 출력한다."""
    click.echo(f"  기록: {result.rows_written} rows")
    click.echo(f"  데이터: {', '.join(result.data_types) or '없음'}")
    click.echo(f"  소요: {result.duration_seconds:.1f}초")
    if result.config_errors:
        click.echo()
        for err in result.config_errors:
            click.echo(f"  [경고] {err.get('error', err)}")
    click.echo()
