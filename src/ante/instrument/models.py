"""Instrument 데이터 모델."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    """종목 마스터 데이터."""

    symbol: str
    exchange: str
    name: str = ""
    name_en: str = ""
    instrument_type: str = ""  # "stock" | "etf" | "etn" | ...
    logo_url: str = ""
    listed: bool = True
    updated_at: str = ""
