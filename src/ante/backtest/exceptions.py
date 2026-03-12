"""Backtest Engine 예외 클래스."""


class BacktestError(Exception):
    """Backtest 기본 예외."""


class BacktestConfigError(BacktestError):
    """설정 오류."""


class BacktestDataError(BacktestError):
    """데이터 관련 오류."""
