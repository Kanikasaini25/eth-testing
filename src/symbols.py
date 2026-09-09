"""Delta India symbol helpers for crypto + tokenized gold."""

from __future__ import annotations

# Delta India has no classic XAUUSD CFD/forex pair.
# Default gold perpetual: PAXGUSD (PAX Gold). XAUTUSD remains available.
DELTA_GOLD_ALIAS = {
    "XAUUSD": "PAXGUSD",
    "XAU": "PAXGUSD",
    "GOLD": "PAXGUSD",
    "PAXG": "PAXGUSD",
    "XAUT": "XAUTUSD",
}

DELTA_TRADEABLE = ("ETHUSD", "BTCUSD", "PAXGUSD", "XAUTUSD")


def resolve_delta_symbol(symbol: str) -> tuple[str, str | None]:
    """Return (delta_symbol, optional_notice).

    Maps common gold aliases (e.g. XAUUSD) to Delta's live perpetual.
    """
    raw = (symbol or "").strip().upper()
    if not raw:
        return "ETHUSD", None
    mapped = DELTA_GOLD_ALIAS.get(raw, raw)
    if raw != mapped:
        return mapped, (
            f"{raw} is not listed on Delta India. "
            f"Using live tokenized-gold perpetual {mapped} instead."
        )
    return mapped, None
