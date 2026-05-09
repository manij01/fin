"""Ticker normalization and validation helpers."""

import re

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,11}$")


def normalize_ticker(value: str) -> str:
    """Return a normalized ticker symbol or raise ValueError."""
    ticker = value.upper().strip()
    if not ticker:
        raise ValueError("Ticker is required")
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError(f"Invalid ticker: {value}")
    return ticker
