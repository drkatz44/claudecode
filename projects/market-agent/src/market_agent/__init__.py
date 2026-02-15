"""Market agent — financial markets analysis and trading signals."""

import re


def validate_symbol(symbol: str) -> str:
    """Validate and normalize a ticker symbol."""
    s = symbol.upper().strip()
    if not re.match(r'^[A-Z0-9.\-]{1,12}$', s):
        raise ValueError(f"Invalid symbol: {symbol!r}")
    return s
